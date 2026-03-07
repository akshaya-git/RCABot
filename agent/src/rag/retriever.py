"""
RAG Retriever for runbooks and case history.
Uses OpenSearch for vector storage and retrieval.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json
import hashlib

from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3


class RAGRetriever:
    """
    Retrieves relevant runbooks and case history using vector search.

    Features:
    - Semantic search for relevant documents
    - Case history similarity matching
    - Runbook retrieval for incident types
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize RAG retriever.

        Args:
            config: Configuration including:
                - opensearch_endpoint: OpenSearch domain endpoint
                - region: AWS region
                - runbook_index: Index name for runbooks
                - case_history_index: Index name for case history
        """
        self.endpoint = config.get("opensearch_endpoint", "")
        self.region = config.get("region", "us-east-1")
        self.runbook_index = config.get("runbook_index", "runbooks")
        self.case_history_index = config.get("case_history_index", "case-history")
        self.embedding_model = config.get("embedding_model", "amazon.titan-embed-text-v1")

        self._client = None
        self._bedrock_client = None

    @property
    def client(self) -> Optional[OpenSearch]:
        """Lazy initialization of OpenSearch client."""
        if self._client is None and self.endpoint:
            credentials = boto3.Session().get_credentials()
            auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                self.region,
                "es",
                session_token=credentials.token,
            )

            self._client = OpenSearch(
                hosts=[{"host": self.endpoint, "port": 443}],
                http_auth=auth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
            )

        return self._client

    @property
    def bedrock_client(self):
        """Lazy initialization of Bedrock client for embeddings."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=self.region
            )
        return self._bedrock_client

    async def get_embedding(self, text: str) -> List[float]:
        """Get embedding vector for text using Bedrock."""
        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.embedding_model,
                body=json.dumps({"inputText": text}),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            return response_body.get("embedding", [])

        except Exception as e:
            print(f"Error getting embedding: {e}")
            return []

    async def search_runbooks(
        self,
        query: str,
        category: Optional[str] = None,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant runbooks.

        Args:
            query: Search query (incident description)
            category: Optional category filter
            max_results: Maximum results to return

        Returns:
            List of relevant runbook documents
        """
        if not self.client:
            return []

        try:
            # Get query embedding
            embedding = await self.get_embedding(query)
            if not embedding:
                return await self._keyword_search_runbooks(query, category, max_results)

            # Build search query
            search_body = {
                "size": max_results,
                "query": {
                    "bool": {
                        "must": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": embedding,
                                        "k": max_results,
                                    }
                                }
                            }
                        ]
                    }
                }
            }

            if category:
                search_body["query"]["bool"]["filter"] = [
                    {"term": {"category": category}}
                ]

            response = self.client.search(
                index=self.runbook_index,
                body=search_body,
            )

            results = []
            for hit in response.get("hits", {}).get("hits", []):
                doc = hit.get("_source", {})
                doc["_score"] = hit.get("_score", 0)
                results.append(doc)

            return results

        except Exception as e:
            print(f"Error searching runbooks: {e}")
            return []

    async def _keyword_search_runbooks(
        self,
        query: str,
        category: Optional[str],
        max_results: int
    ) -> List[Dict[str, Any]]:
        """Fallback keyword search for runbooks."""
        try:
            search_body = {
                "size": max_results,
                "query": {
                    "bool": {
                        "should": [
                            {"match": {"title": {"query": query, "boost": 2}}},
                            {"match": {"content": query}},
                            {"match": {"keywords": {"query": query, "boost": 1.5}}},
                        ]
                    }
                }
            }

            if category:
                search_body["query"]["bool"]["filter"] = [
                    {"term": {"category": category}}
                ]

            response = self.client.search(
                index=self.runbook_index,
                body=search_body,
            )

            return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

        except Exception:
            return []

    async def search_similar_incidents(
        self,
        incident_description: str,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for similar past incidents.

        Args:
            incident_description: Description of current incident
            max_results: Maximum results to return

        Returns:
            List of similar past incidents
        """
        if not self.client:
            return []

        try:
            embedding = await self.get_embedding(incident_description)

            if embedding:
                search_body = {
                    "size": max_results,
                    "query": {
                        "knn": {
                            "embedding": {
                                "vector": embedding,
                                "k": max_results,
                            }
                        }
                    }
                }
            else:
                # Keyword search fallback
                search_body = {
                    "size": max_results,
                    "query": {
                        "multi_match": {
                            "query": incident_description,
                            "fields": ["title", "description", "root_cause"],
                        }
                    }
                }

            response = self.client.search(
                index=self.case_history_index,
                body=search_body,
            )

            results = []
            for hit in response.get("hits", {}).get("hits", []):
                doc = hit.get("_source", {})
                doc["_score"] = hit.get("_score", 0)
                results.append(doc)

            return results

        except Exception as e:
            print(f"Error searching similar incidents: {e}")
            return []

    async def index_runbook(self, runbook: Dict[str, Any]) -> bool:
        """
        Index a new runbook.

        Args:
            runbook: Runbook document with title, content, category

        Returns:
            True if successful
        """
        if not self.client:
            return False

        try:
            # Generate ID
            doc_id = hashlib.sha256(
                runbook.get("title", "").encode()
            ).hexdigest()[:12]

            # Get embedding
            content = f"{runbook.get('title', '')} {runbook.get('content', '')}"
            embedding = await self.get_embedding(content)

            doc = {
                "title": runbook.get("title", ""),
                "content": runbook.get("content", ""),
                "category": runbook.get("category", "general"),
                "keywords": runbook.get("keywords", []),
                "steps": runbook.get("steps", []),
                "embedding": embedding,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }

            self.client.index(
                index=self.runbook_index,
                id=doc_id,
                body=doc,
                refresh=True,
            )

            return True

        except Exception as e:
            print(f"Error indexing runbook: {e}")
            return False

    async def index_incident(self, incident: Dict[str, Any]) -> bool:
        """
        Index a resolved incident for future learning.

        Args:
            incident: Incident document with resolution

        Returns:
            True if successful
        """
        if not self.client:
            return False

        try:
            doc_id = incident.get("incident_id", hashlib.sha256(
                str(datetime.now(timezone.utc)).encode()
            ).hexdigest()[:12])

            # Get embedding
            content = f"{incident.get('title', '')} {incident.get('description', '')}"
            embedding = await self.get_embedding(content)

            doc = {
                "incident_id": doc_id,
                "title": incident.get("title", ""),
                "description": incident.get("description", ""),
                "priority": incident.get("priority", ""),
                "category": incident.get("category", ""),
                "root_cause": incident.get("root_cause_analysis", ""),
                "resolution": incident.get("resolution", ""),
                "recommended_actions": incident.get("recommended_actions", []),
                "affected_resources": incident.get("affected_resources", []),
                "embedding": embedding,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
                "detected_at": incident.get("detected_at", ""),
                "resolved_at": incident.get("resolved_at", ""),
            }

            self.client.index(
                index=self.case_history_index,
                id=doc_id,
                body=doc,
                refresh=True,
            )

            return True

        except Exception as e:
            print(f"Error indexing incident: {e}")
            return False

    async def ensure_indices(self) -> bool:
        """Ensure required indices exist with proper mappings."""
        if not self.client:
            return False

        index_mappings = {
            self.runbook_index: {
                "mappings": {
                    "properties": {
                        "title": {"type": "text"},
                        "content": {"type": "text"},
                        "category": {"type": "keyword"},
                        "keywords": {"type": "keyword"},
                        "steps": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 1536,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib",
                            }
                        },
                        "indexed_at": {"type": "date"},
                    }
                },
                "settings": {
                    "index.knn": True,
                }
            },
            self.case_history_index: {
                "mappings": {
                    "properties": {
                        "incident_id": {"type": "keyword"},
                        "title": {"type": "text"},
                        "description": {"type": "text"},
                        "priority": {"type": "keyword"},
                        "category": {"type": "keyword"},
                        "root_cause": {"type": "text"},
                        "resolution": {"type": "text"},
                        "recommended_actions": {"type": "text"},
                        "affected_resources": {"type": "keyword"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 1536,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "nmslib",
                            }
                        },
                        "indexed_at": {"type": "date"},
                        "detected_at": {"type": "date"},
                        "resolved_at": {"type": "date"},
                    }
                },
                "settings": {
                    "index.knn": True,
                }
            }
        }

        try:
            for index_name, mapping in index_mappings.items():
                if not self.client.indices.exists(index=index_name):
                    self.client.indices.create(index=index_name, body=mapping)
                    print(f"Created index: {index_name}")

            return True

        except Exception as e:
            print(f"Error ensuring indices: {e}")
            return False

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to OpenSearch."""
        if not self.client:
            return {"success": False, "error": "OpenSearch not configured"}

        try:
            info = self.client.info()
            return {
                "success": True,
                "message": f"Connected to OpenSearch {info.get('version', {}).get('number', 'unknown')}",
                "cluster": info.get("cluster_name"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
