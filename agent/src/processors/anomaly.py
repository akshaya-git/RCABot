"""
Anomaly Detection Processor.
Uses Amazon Bedrock (Claude) for intelligent anomaly detection.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

from ..collectors.base import CloudWatchEvent
from ..models.events import AnomalyScore, IncidentCategory


class AnomalyDetector:
    """
    Detects anomalies in CloudWatch events using AI analysis.

    Uses Amazon Bedrock with Claude model for:
    - Pattern recognition
    - Correlation analysis
    - Root cause identification
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize anomaly detector.

        Args:
            config: Configuration including:
                - region: AWS region
                - model_id: Bedrock model ID
                - threshold: Anomaly score threshold
        """
        self.region = config.get("region", "us-east-1")
        self.model_id = config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        self.threshold = config.get("anomaly_threshold", 0.7)
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Bedrock client."""
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def analyze_events(
        self,
        events: List[CloudWatchEvent],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Analyze a batch of events for anomalies.

        Args:
            events: List of CloudWatch events to analyze
            context: Optional context (runbooks, history)

        Returns:
            List of analyzed events with anomaly scores
        """
        if not events:
            return []

        # Group events by type for batch analysis
        grouped = self._group_events(events)
        results = []

        for event_type, type_events in grouped.items():
            try:
                analysis = await self._analyze_event_group(type_events, event_type, context)
                results.extend(analysis)
            except Exception as e:
                print(f"Error analyzing {event_type} events: {e}")
                # Return events with default scores on error
                for event in type_events:
                    results.append({
                        "event": event.to_dict(),
                        "anomaly_score": AnomalyScore(
                            score=0.5,
                            confidence=0.3,
                            reasoning="Analysis unavailable",
                            factors=["Error during analysis"],
                        ),
                        "category": IncidentCategory.UNKNOWN,
                    })

        return results

    def _group_events(self, events: List[CloudWatchEvent]) -> Dict[str, List[CloudWatchEvent]]:
        """Group events by type for efficient batch analysis."""
        grouped = {}
        for event in events:
            event_type = event.event_type.value
            if event_type not in grouped:
                grouped[event_type] = []
            grouped[event_type].append(event)
        return grouped

    async def _analyze_event_group(
        self,
        events: List[CloudWatchEvent],
        event_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Analyze a group of events using Claude."""
        # Prepare events summary for the prompt
        events_summary = []
        for event in events[:20]:  # Limit to avoid token limits
            events_summary.append({
                "id": event.event_id,
                "type": event.event_type.value,
                "title": event.title,
                "description": event.description[:500],
                "timestamp": event.timestamp.isoformat(),
                "resource_type": event.resource_type.value,
                "resource_id": event.resource_id,
                "metric_name": event.metric_name,
                "metric_value": event.metric_value,
                "threshold": event.threshold,
                "state": event.state,
            })

        prompt = self._build_analysis_prompt(events_summary, event_type, context)

        try:
            response = await self._invoke_claude(prompt)
            return self._parse_analysis_response(response, events)
        except Exception as e:
            print(f"Claude analysis error: {e}")
            raise

    def _build_analysis_prompt(
        self,
        events: List[Dict[str, Any]],
        event_type: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build the analysis prompt for Claude."""
        context_section = ""
        if context:
            if context.get("runbooks"):
                context_section += f"\n\nRelevant Runbooks:\n{json.dumps(context['runbooks'][:3], indent=2)}"
            if context.get("similar_incidents"):
                context_section += f"\n\nSimilar Past Incidents:\n{json.dumps(context['similar_incidents'][:3], indent=2)}"

        return f"""You are an expert SRE/DevOps engineer analyzing CloudWatch monitoring events.

Analyze the following {event_type} events and determine:
1. Whether each event represents a genuine anomaly or incident
2. The severity/category of the issue
3. Potential root causes
4. Recommended actions

Events to analyze:
{json.dumps(events, indent=2)}
{context_section}

For each event, provide your analysis in the following JSON format:
{{
    "analyses": [
        {{
            "event_id": "event id from input",
            "is_anomaly": true/false,
            "anomaly_score": 0.0-1.0 (higher = more severe),
            "confidence": 0.0-1.0,
            "category": "performance|availability|error_rate|resource_exhaustion|security|configuration|capacity|unknown",
            "reasoning": "explanation of why this is or isn't an anomaly",
            "factors": ["list", "of", "contributing", "factors"],
            "root_cause": "potential root cause if identifiable",
            "recommended_actions": ["action 1", "action 2"]
        }}
    ]
}}

Consider:
- Threshold breaches vs normal fluctuations
- Correlation between events
- Time patterns and trends
- Resource utilization context
- Common false positive patterns

Respond ONLY with valid JSON, no additional text."""

    async def _invoke_claude(self, prompt: str) -> str:
        """Invoke Claude model via Bedrock."""
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3,
        })

        response = self.client.invoke_model(
            modelId=self.model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        response_body = json.loads(response["body"].read())
        return response_body["content"][0]["text"]

    def _parse_analysis_response(
        self,
        response: str,
        events: List[CloudWatchEvent]
    ) -> List[Dict[str, Any]]:
        """Parse Claude's analysis response."""
        results = []

        try:
            # Parse JSON response
            analysis_data = json.loads(response)
            analyses = analysis_data.get("analyses", [])

            # Create lookup for events
            event_lookup = {e.event_id: e for e in events}

            for analysis in analyses:
                event_id = analysis.get("event_id", "")
                event = event_lookup.get(event_id)

                if event:
                    anomaly_score = AnomalyScore(
                        score=float(analysis.get("anomaly_score", 0.5)),
                        confidence=float(analysis.get("confidence", 0.5)),
                        reasoning=analysis.get("reasoning", ""),
                        factors=analysis.get("factors", []),
                    )

                    category_str = analysis.get("category", "unknown")
                    try:
                        category = IncidentCategory(category_str)
                    except ValueError:
                        category = IncidentCategory.UNKNOWN

                    results.append({
                        "event": event.to_dict(),
                        "anomaly_score": anomaly_score,
                        "category": category,
                        "is_anomaly": analysis.get("is_anomaly", False),
                        "root_cause": analysis.get("root_cause"),
                        "recommended_actions": analysis.get("recommended_actions", []),
                    })

        except json.JSONDecodeError as e:
            print(f"Failed to parse Claude response: {e}")
            # Return events with default analysis
            for event in events:
                results.append({
                    "event": event.to_dict(),
                    "anomaly_score": AnomalyScore(
                        score=0.5,
                        confidence=0.3,
                        reasoning="Failed to parse AI analysis",
                    ),
                    "category": IncidentCategory.UNKNOWN,
                    "is_anomaly": True,  # Assume anomaly on parse failure
                })

        return results

    async def correlate_events(
        self,
        events: List[CloudWatchEvent]
    ) -> List[List[CloudWatchEvent]]:
        """
        Group related events that may be part of the same incident.

        Returns:
            List of event groups (correlated events)
        """
        if len(events) <= 1:
            return [events] if events else []

        # Simple correlation based on resource and time
        groups = []
        used = set()

        for i, event in enumerate(events):
            if i in used:
                continue

            group = [event]
            used.add(i)

            for j, other in enumerate(events[i+1:], start=i+1):
                if j in used:
                    continue

                # Check if events are related
                if self._events_related(event, other):
                    group.append(other)
                    used.add(j)

            groups.append(group)

        return groups

    def _events_related(self, e1: CloudWatchEvent, e2: CloudWatchEvent) -> bool:
        """Check if two events are related."""
        # Same resource
        if e1.resource_id and e1.resource_id == e2.resource_id:
            return True

        # Same namespace within 5 minutes
        if e1.namespace == e2.namespace:
            time_diff = abs((e1.timestamp - e2.timestamp).total_seconds())
            if time_diff <= 300:
                return True

        return False

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to Bedrock."""
        try:
            # Simple test prompt
            test_prompt = "Respond with 'OK' if you can read this."
            response = await self._invoke_claude(test_prompt)

            return {
                "success": True,
                "message": f"Connected to Bedrock ({self.model_id})",
                "model": self.model_id,
            }
        except ClientError as e:
            return {
                "success": False,
                "error": str(e),
            }
