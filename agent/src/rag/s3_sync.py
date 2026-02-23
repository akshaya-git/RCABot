"""
S3 Sync for RAG Data.
Handles synchronization between S3 and OpenSearch for runbooks and case history.
Supports automatic extraction of structured data from unstructured documents.
"""

import json
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

from .extractor import RunbookExtractor


class S3RAGSync:
    """
    Synchronizes RAG data between S3 and OpenSearch.

    S3 Bucket Structure:
    - runbooks/           # Runbook JSON files
    - case-history/       # Resolved incident JSON files
    - imports/            # Bulk import staging area
    - exports/            # Export destination

    Features:
    - Bulk import from S3 to OpenSearch
    - Export case history to S3
    - Sync new/updated runbooks
    - Version tracking
    """

    def __init__(self, config: Dict[str, Any], rag_retriever):
        """
        Initialize S3 RAG Sync.

        Args:
            config: Configuration including:
                - bucket: S3 bucket name
                - region: AWS region
                - runbooks_prefix: Prefix for runbooks (default: runbooks/)
                - case_history_prefix: Prefix for case history (default: case-history/)
            rag_retriever: RAGRetriever instance for indexing
        """
        self.bucket = config.get("bucket", "")
        self.region = config.get("region", "us-east-1")
        self.runbooks_prefix = config.get("runbooks_prefix", "runbooks/")
        self.case_history_prefix = config.get("case_history_prefix", "case-history/")
        self.imports_prefix = config.get("imports_prefix", "imports/")
        self.exports_prefix = config.get("exports_prefix", "exports/")
        self.raw_prefix = config.get("raw_prefix", "raw/")  # For unstructured documents

        self.rag = rag_retriever
        self._s3_client = None

        # Initialize extractor for unstructured documents
        self.extractor = RunbookExtractor(config)

        # Supported file extensions for raw extraction
        self.raw_extensions = [".md", ".txt", ".rst", ".html", ".confluence"]
        self.structured_extensions = [".json"]

    @property
    def s3_client(self):
        """Lazy initialization of S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client

    async def sync_runbooks_from_s3(self, force: bool = False, include_raw: bool = True) -> Dict[str, Any]:
        """
        Sync all runbooks from S3 to OpenSearch.

        Handles both structured JSON files and raw text files (markdown, txt, etc.)
        Raw files are processed through LLM extraction to convert to structured format.

        Args:
            force: If True, re-index all runbooks regardless of version
            include_raw: If True, also process raw/unstructured files

        Returns:
            Sync results with counts
        """
        if not self.bucket:
            return {"success": False, "error": "S3 bucket not configured"}

        results = {
            "success": True,
            "indexed": 0,
            "extracted": 0,  # Count of files that needed LLM extraction
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        # File extensions to process
        valid_extensions = self.structured_extensions.copy()
        if include_raw:
            valid_extensions.extend(self.raw_extensions)

        try:
            # List all runbook files
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=self.runbooks_prefix,
            )

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    # Skip folder markers
                    if key.endswith("/"):
                        continue

                    # Check if file extension is supported
                    has_valid_ext = any(key.lower().endswith(ext) for ext in valid_extensions)
                    if not has_valid_ext:
                        continue

                    try:
                        result = await self._sync_single_runbook(key, force)
                        if result.get("indexed"):
                            results["indexed"] += 1
                            if result.get("extracted"):
                                results["extracted"] += 1
                        elif result.get("skipped"):
                            results["skipped"] += 1
                        else:
                            results["failed"] += 1
                            results["errors"].append(result.get("error", "Unknown error"))
                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append(f"{key}: {str(e)}")

            # Also process raw/ prefix if include_raw is True
            if include_raw:
                raw_results = await self._sync_raw_prefix()
                results["indexed"] += raw_results.get("indexed", 0)
                results["extracted"] += raw_results.get("extracted", 0)
                results["failed"] += raw_results.get("failed", 0)

            print(f"S3 Sync: {results['indexed']} indexed ({results['extracted']} extracted), "
                  f"{results['skipped']} skipped, {results['failed']} failed")

        except ClientError as e:
            results["success"] = False
            results["error"] = str(e)

        return results

    async def _sync_raw_prefix(self) -> Dict[str, Any]:
        """Sync files from the raw/ prefix (unstructured documents)."""
        results = {"indexed": 0, "extracted": 0, "failed": 0}

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=self.raw_prefix,
            )

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue

                    try:
                        result = await self._sync_single_runbook(key, force=True)
                        if result.get("indexed"):
                            results["indexed"] += 1
                            results["extracted"] += 1
                        else:
                            results["failed"] += 1
                    except Exception:
                        results["failed"] += 1

        except ClientError:
            pass

        return results

    async def _sync_single_runbook(self, key: str, force: bool) -> Dict[str, Any]:
        """Sync a single runbook from S3. Handles both structured JSON and raw text files."""
        try:
            # Get object
            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            content = response["Body"].read().decode("utf-8")

            # Determine if file is structured (JSON) or needs extraction
            is_json = key.lower().endswith(".json")

            if is_json:
                # Structured JSON file
                try:
                    runbook = json.loads(content)
                except json.JSONDecodeError:
                    # JSON file but invalid - try extraction
                    runbook = await self.extractor.extract_runbook(content, key.split("/")[-1])
            else:
                # Raw/unstructured file - use LLM to extract
                filename = key.split("/")[-1]
                runbook = await self.extractor.extract_runbook(content, filename)
                print(f"Extracted structured data from {key}: {runbook.get('title', 'Unknown')}")

            # Validate required fields
            if not runbook.get("title") or not runbook.get("content"):
                return {"error": f"Missing required fields in {key}"}

            # Add metadata
            runbook["_s3_key"] = key
            runbook["_s3_etag"] = response.get("ETag", "").strip('"')
            runbook["_s3_last_modified"] = response.get("LastModified", datetime.now(timezone.utc)).isoformat()
            runbook["_extracted"] = not is_json  # Flag if data was extracted

            # Index to OpenSearch
            success = await self.rag.index_runbook(runbook)

            if success:
                return {"indexed": True, "extracted": not is_json}
            else:
                return {"error": f"Failed to index {key}"}

        except Exception as e:
            return {"error": f"Error processing {key}: {e}"}

    async def sync_case_history_from_s3(self) -> Dict[str, Any]:
        """
        Sync case history from S3 to OpenSearch.

        Returns:
            Sync results with counts
        """
        if not self.bucket:
            return {"success": False, "error": "S3 bucket not configured"}

        results = {
            "success": True,
            "indexed": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=self.case_history_prefix,
            )

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    if key.endswith("/") or not key.endswith(".json"):
                        continue

                    try:
                        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
                        content = response["Body"].read().decode("utf-8")
                        incident = json.loads(content)

                        success = await self.rag.index_incident(incident)

                        if success:
                            results["indexed"] += 1
                        else:
                            results["failed"] += 1
                    except Exception as e:
                        results["failed"] += 1
                        results["errors"].append(f"{key}: {str(e)}")

        except ClientError as e:
            results["success"] = False
            results["error"] = str(e)

        return results

    async def export_incident_to_s3(self, incident: Dict[str, Any]) -> bool:
        """
        Export a resolved incident to S3 for backup.

        Args:
            incident: Incident document to export

        Returns:
            True if successful
        """
        if not self.bucket:
            return False

        try:
            incident_id = incident.get("incident_id", "unknown")
            timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            key = f"{self.case_history_prefix}{timestamp}/{incident_id}.json"

            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(incident, indent=2, default=str),
                ContentType="application/json",
            )

            print(f"Exported incident {incident_id} to s3://{self.bucket}/{key}")
            return True

        except ClientError as e:
            print(f"Error exporting incident to S3: {e}")
            return False

    async def bulk_import(self, source_prefix: Optional[str] = None) -> Dict[str, Any]:
        """
        Bulk import all RAG data from S3.

        This imports:
        - All runbooks from runbooks/ prefix
        - All case history from case-history/ prefix
        - Any additional data from imports/ prefix

        Args:
            source_prefix: Optional specific prefix to import from

        Returns:
            Import results
        """
        results = {
            "success": True,
            "runbooks": {"indexed": 0, "failed": 0},
            "case_history": {"indexed": 0, "failed": 0},
            "imports": {"indexed": 0, "failed": 0},
        }

        # Sync runbooks
        runbook_results = await self.sync_runbooks_from_s3(force=True)
        results["runbooks"]["indexed"] = runbook_results.get("indexed", 0)
        results["runbooks"]["failed"] = runbook_results.get("failed", 0)

        # Sync case history
        case_results = await self.sync_case_history_from_s3()
        results["case_history"]["indexed"] = case_results.get("indexed", 0)
        results["case_history"]["failed"] = case_results.get("failed", 0)

        # Process imports folder (for ad-hoc bulk imports)
        if source_prefix:
            import_results = await self._process_imports(source_prefix)
            results["imports"]["indexed"] = import_results.get("indexed", 0)
            results["imports"]["failed"] = import_results.get("failed", 0)

        total_indexed = (
            results["runbooks"]["indexed"] +
            results["case_history"]["indexed"] +
            results["imports"]["indexed"]
        )
        total_failed = (
            results["runbooks"]["failed"] +
            results["case_history"]["failed"] +
            results["imports"]["failed"]
        )

        print(f"Bulk import complete: {total_indexed} indexed, {total_failed} failed")

        return results

    async def _process_imports(self, prefix: str) -> Dict[str, Any]:
        """Process files from a specific import prefix."""
        results = {"indexed": 0, "failed": 0}

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    if key.endswith("/") or not key.endswith(".json"):
                        continue

                    try:
                        response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
                        content = response["Body"].read().decode("utf-8")
                        doc = json.loads(content)

                        # Determine document type and index accordingly
                        if "steps" in doc or doc.get("type") == "runbook":
                            success = await self.rag.index_runbook(doc)
                        else:
                            success = await self.rag.index_incident(doc)

                        if success:
                            results["indexed"] += 1
                        else:
                            results["failed"] += 1

                    except Exception as e:
                        results["failed"] += 1
                        print(f"Error processing {key}: {e}")

        except ClientError as e:
            print(f"Error processing imports: {e}")

        return results

    async def list_s3_runbooks(self) -> List[Dict[str, Any]]:
        """
        List all runbooks in S3.

        Returns:
            List of runbook metadata (key, size, last_modified)
        """
        if not self.bucket:
            return []

        runbooks = []

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(
                Bucket=self.bucket,
                Prefix=self.runbooks_prefix,
            )

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/") or not key.endswith(".json"):
                        continue

                    runbooks.append({
                        "key": key,
                        "name": key.replace(self.runbooks_prefix, "").replace(".json", ""),
                        "size": obj.get("Size", 0),
                        "last_modified": obj.get("LastModified", "").isoformat() if obj.get("LastModified") else "",
                    })

        except ClientError as e:
            print(f"Error listing runbooks: {e}")

        return runbooks

    async def upload_runbook(self, runbook: Dict[str, Any], filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload a runbook to S3 and index to OpenSearch.

        Args:
            runbook: Runbook document
            filename: Optional filename (defaults to title slugified)

        Returns:
            Upload result with S3 key and index status
        """
        if not self.bucket:
            return {"success": False, "error": "S3 bucket not configured"}

        try:
            # Generate filename from title if not provided
            if not filename:
                title = runbook.get("title", "untitled")
                filename = title.lower().replace(" ", "-").replace("/", "-")
                filename = "".join(c for c in filename if c.isalnum() or c == "-")

            if not filename.endswith(".json"):
                filename += ".json"

            key = f"{self.runbooks_prefix}{filename}"

            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=json.dumps(runbook, indent=2),
                ContentType="application/json",
            )

            # Index to OpenSearch
            indexed = await self.rag.index_runbook(runbook)

            return {
                "success": True,
                "s3_key": key,
                "s3_uri": f"s3://{self.bucket}/{key}",
                "indexed": indexed,
            }

        except ClientError as e:
            return {"success": False, "error": str(e)}

    async def get_sync_status(self) -> Dict[str, Any]:
        """
        Get synchronization status between S3 and OpenSearch.

        Returns:
            Status including counts and last sync time
        """
        status = {
            "s3_configured": bool(self.bucket),
            "bucket": self.bucket,
            "s3_runbooks_count": 0,
            "s3_case_history_count": 0,
            "opensearch_connected": False,
        }

        if not self.bucket:
            return status

        try:
            # Count S3 objects
            paginator = self.s3_client.get_paginator("list_objects_v2")

            # Count runbooks
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.runbooks_prefix):
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".json"):
                        status["s3_runbooks_count"] += 1

            # Count case history
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.case_history_prefix):
                for obj in page.get("Contents", []):
                    if obj["Key"].endswith(".json"):
                        status["s3_case_history_count"] += 1

            # Check OpenSearch connection
            rag_status = await self.rag.test_connection()
            status["opensearch_connected"] = rag_status.get("success", False)

        except ClientError as e:
            status["error"] = str(e)

        return status

    async def test_connection(self) -> Dict[str, Any]:
        """Test S3 connection and bucket access."""
        if not self.bucket:
            return {"success": False, "error": "S3 bucket not configured"}

        try:
            # Try to list objects (validates bucket access)
            self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                MaxKeys=1,
            )

            return {
                "success": True,
                "message": f"Connected to S3 bucket: {self.bucket}",
                "bucket": self.bucket,
                "prefixes": {
                    "runbooks": self.runbooks_prefix,
                    "case_history": self.case_history_prefix,
                    "imports": self.imports_prefix,
                    "exports": self.exports_prefix,
                }
            }

        except ClientError as e:
            return {"success": False, "error": str(e)}
