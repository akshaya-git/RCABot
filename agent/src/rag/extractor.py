"""
RAG Data Extractor.
Uses LLM to extract structured data from unstructured runbooks and documents.
"""

import json
from typing import Any, Dict, List, Optional
import boto3


class RunbookExtractor:
    """
    Extracts structured runbook data from unstructured content using LLM.

    Handles:
    - Plain text runbooks
    - Markdown documents
    - Wiki pages
    - Confluence exports
    - Any unstructured incident documentation
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the extractor.

        Args:
            config: Configuration including:
                - region: AWS region
                - model_id: Bedrock model ID for extraction
        """
        self.region = config.get("region", "us-east-1")
        self.model_id = config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        self._bedrock_client = None

    @property
    def bedrock_client(self):
        """Lazy initialization of Bedrock client."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=self.region
            )
        return self._bedrock_client

    async def extract_runbook(self, raw_content: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract structured runbook data from unstructured content.

        Args:
            raw_content: Raw text content (markdown, plain text, etc.)
            filename: Optional filename for context

        Returns:
            Structured runbook matching the schema:
            {
                "title": str,
                "content": str,
                "category": str,
                "keywords": list[str],
                "steps": list[str]
            }
        """
        prompt = self._build_extraction_prompt(raw_content, filename)

        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            assistant_message = response_body.get("content", [{}])[0].get("text", "")

            # Parse the JSON from the response
            extracted = self._parse_extraction_response(assistant_message)

            # Validate and fill defaults
            return self._validate_and_normalize(extracted, raw_content)

        except Exception as e:
            print(f"Error extracting runbook: {e}")
            # Return a basic structure with the raw content
            return self._fallback_extraction(raw_content, filename)

    def _build_extraction_prompt(self, content: str, filename: Optional[str]) -> str:
        """Build the extraction prompt for the LLM."""
        context = f"Filename: {filename}\n\n" if filename else ""

        return f"""You are a technical documentation parser. Extract structured information from the following runbook/documentation.

{context}DOCUMENT CONTENT:
```
{content[:8000]}
```

Extract and return a JSON object with the following fields:

1. **title**: A clear, concise title for this runbook (if not explicitly stated, infer from content)
2. **content**: A cleaned-up summary of what this runbook covers (1-3 paragraphs)
3. **category**: One of: "performance", "availability", "error", "security", "capacity", "configuration", "general"
4. **keywords**: Array of 5-10 relevant keywords for search (lowercase, include AWS services, error types, etc.)
5. **steps**: Array of actionable steps extracted from the document. Each step should be clear and actionable. If the document doesn't have explicit steps, extract the key actions/procedures mentioned.

IMPORTANT:
- If the document has numbered steps, preserve them
- If no clear steps exist, extract key procedures/actions as steps
- Keywords should help find this runbook when similar incidents occur
- Category should reflect the primary purpose of this runbook

Return ONLY valid JSON, no additional text:

```json
{{
  "title": "...",
  "content": "...",
  "category": "...",
  "keywords": ["...", "..."],
  "steps": ["1. ...", "2. ...", "..."]
}}
```"""

    def _parse_extraction_response(self, response: str) -> Dict[str, Any]:
        """Parse the LLM response to extract JSON."""
        # Try to find JSON in the response
        try:
            # Look for JSON block
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "{" in response:
                start = response.find("{")
                end = response.rfind("}") + 1
                json_str = response[start:end]
            else:
                json_str = response

            return json.loads(json_str)

        except json.JSONDecodeError:
            return {}

    def _validate_and_normalize(self, extracted: Dict[str, Any], original_content: str) -> Dict[str, Any]:
        """Validate extracted data and fill in defaults."""
        valid_categories = ["performance", "availability", "error", "security", "capacity", "configuration", "general"]

        result = {
            "title": extracted.get("title", "Untitled Runbook"),
            "content": extracted.get("content", original_content[:2000]),
            "category": extracted.get("category", "general"),
            "keywords": extracted.get("keywords", []),
            "steps": extracted.get("steps", []),
        }

        # Normalize category
        if result["category"].lower() not in valid_categories:
            result["category"] = "general"
        else:
            result["category"] = result["category"].lower()

        # Ensure keywords is a list
        if not isinstance(result["keywords"], list):
            result["keywords"] = []

        # Ensure steps is a list
        if not isinstance(result["steps"], list):
            result["steps"] = []

        return result

    def _fallback_extraction(self, content: str, filename: Optional[str]) -> Dict[str, Any]:
        """Fallback extraction when LLM fails."""
        # Try to extract title from first line
        lines = content.strip().split("\n")
        title = lines[0].strip("#").strip() if lines else "Untitled Runbook"

        # If filename provided, use it as title hint
        if filename:
            # Convert filename to title (e.g., "high-cpu-troubleshooting.md" -> "High Cpu Troubleshooting")
            clean_name = filename.replace("-", " ").replace("_", " ")
            clean_name = clean_name.rsplit(".", 1)[0]  # Remove extension
            if len(clean_name) > len(title) or title == "Untitled Runbook":
                title = clean_name.title()

        return {
            "title": title,
            "content": content[:2000],
            "category": "general",
            "keywords": [],
            "steps": [],
            "_extraction_failed": True,
        }

    async def extract_case_history(self, raw_content: str, incident_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract structured case history from unstructured incident documentation.

        Args:
            raw_content: Raw incident report/post-mortem content
            incident_id: Optional incident ID

        Returns:
            Structured case history matching the schema
        """
        prompt = self._build_case_extraction_prompt(raw_content, incident_id)

        try:
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            assistant_message = response_body.get("content", [{}])[0].get("text", "")

            extracted = self._parse_extraction_response(assistant_message)
            return self._validate_case_history(extracted, raw_content, incident_id)

        except Exception as e:
            print(f"Error extracting case history: {e}")
            return self._fallback_case_extraction(raw_content, incident_id)

    def _build_case_extraction_prompt(self, content: str, incident_id: Optional[str]) -> str:
        """Build extraction prompt for case history."""
        id_context = f"Incident ID: {incident_id}\n\n" if incident_id else ""

        return f"""You are an incident analyst. Extract structured information from the following incident report/post-mortem.

{id_context}INCIDENT DOCUMENT:
```
{content[:8000]}
```

Extract and return a JSON object with the following fields:

1. **incident_id**: The incident ID (use "{incident_id or 'INC-UNKNOWN'}" if not found in document)
2. **title**: A clear title describing the incident
3. **description**: What happened (1-2 paragraphs)
4. **priority**: One of "P1", "P2", "P3", "P4", "P5", "P6" based on severity described
5. **category**: One of "performance", "availability", "error", "security", "capacity", "configuration"
6. **root_cause**: The identified root cause (IMPORTANT - this is critical for future learning)
7. **resolution**: How the incident was resolved (IMPORTANT - this is critical for future learning)
8. **recommended_actions**: Array of actions/steps that helped resolve or prevent recurrence
9. **affected_resources**: Array of AWS resources/services affected (e.g., "i-abc123", "prod-api-cluster")

IMPORTANT:
- root_cause and resolution are the MOST important fields for learning
- If root cause is unclear, state what was identified
- Include specific commands, configs, or changes in resolution if mentioned

Return ONLY valid JSON:

```json
{{
  "incident_id": "...",
  "title": "...",
  "description": "...",
  "priority": "...",
  "category": "...",
  "root_cause": "...",
  "resolution": "...",
  "recommended_actions": ["...", "..."],
  "affected_resources": ["...", "..."]
}}
```"""

    def _validate_case_history(self, extracted: Dict[str, Any], original: str, incident_id: Optional[str]) -> Dict[str, Any]:
        """Validate case history extraction."""
        valid_priorities = ["P1", "P2", "P3", "P4", "P5", "P6"]
        valid_categories = ["performance", "availability", "error", "security", "capacity", "configuration"]

        result = {
            "incident_id": extracted.get("incident_id", incident_id or "INC-UNKNOWN"),
            "title": extracted.get("title", "Untitled Incident"),
            "description": extracted.get("description", original[:1000]),
            "priority": extracted.get("priority", "P3"),
            "category": extracted.get("category", "error"),
            "root_cause": extracted.get("root_cause", ""),
            "resolution": extracted.get("resolution", ""),
            "recommended_actions": extracted.get("recommended_actions", []),
            "affected_resources": extracted.get("affected_resources", []),
        }

        # Normalize priority
        if result["priority"].upper() not in valid_priorities:
            result["priority"] = "P3"
        else:
            result["priority"] = result["priority"].upper()

        # Normalize category
        if result["category"].lower() not in valid_categories:
            result["category"] = "error"
        else:
            result["category"] = result["category"].lower()

        return result

    def _fallback_case_extraction(self, content: str, incident_id: Optional[str]) -> Dict[str, Any]:
        """Fallback for case history extraction."""
        lines = content.strip().split("\n")
        title = lines[0].strip("#").strip() if lines else "Untitled Incident"

        return {
            "incident_id": incident_id or "INC-UNKNOWN",
            "title": title,
            "description": content[:1000],
            "priority": "P3",
            "category": "error",
            "root_cause": "",
            "resolution": "",
            "recommended_actions": [],
            "affected_resources": [],
            "_extraction_failed": True,
        }

    async def extract_batch(
        self,
        documents: List[Dict[str, Any]],
        doc_type: str = "runbook"
    ) -> List[Dict[str, Any]]:
        """
        Extract structured data from multiple documents.

        Args:
            documents: List of {"content": str, "filename": str} or {"content": str, "incident_id": str}
            doc_type: "runbook" or "case_history"

        Returns:
            List of extracted structured documents
        """
        results = []

        for doc in documents:
            content = doc.get("content", "")

            if doc_type == "runbook":
                extracted = await self.extract_runbook(content, doc.get("filename"))
            else:
                extracted = await self.extract_case_history(content, doc.get("incident_id"))

            results.append(extracted)

        return results
