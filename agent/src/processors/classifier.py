"""
Severity Classifier.
Classifies incidents into priority levels (P1-P6).
"""

import json
from typing import Any, Dict, List, Optional
import boto3

from ..models.events import (
    AnomalyScore,
    Incident,
    IncidentCategory,
    IncidentStatus,
    Priority,
    generate_incident_id,
)
from ..collectors.base import CloudWatchEvent


class SeverityClassifier:
    """
    Classifies incidents into priority levels P1-P6.

    Classification criteria:
    - P1 (Critical): Production down, data loss risk, security breach
    - P2 (High): Major feature impacted, significant degradation
    - P3 (Medium): Minor feature impacted, workaround available
    - P4 (Low): Minimal impact, non-critical systems
    - P5 (Very Low): Informational, potential future issue
    - P6 (Trivial): Cosmetic, no functional impact
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize classifier.

        Args:
            config: Configuration including:
                - region: AWS region
                - model_id: Bedrock model ID for AI classification
                - use_ai: Whether to use AI for classification
        """
        self.region = config.get("region", "us-east-1")
        self.model_id = config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0")
        self.use_ai = config.get("use_ai_classification", True)
        self._client = None

        # Rule-based classification thresholds
        self.classification_rules = config.get("classification_rules", {
            "anomaly_thresholds": {
                "P1": 0.95,
                "P2": 0.85,
                "P3": 0.70,
                "P4": 0.50,
                "P5": 0.30,
                "P6": 0.0,
            },
            "category_weights": {
                "availability": {"P1": 0.3, "P2": 0.2},
                "security": {"P1": 0.4, "P2": 0.3},
                "error_rate": {"P2": 0.2, "P3": 0.2},
                "performance": {"P3": 0.3, "P4": 0.2},
                "resource_exhaustion": {"P2": 0.3, "P3": 0.2},
                "configuration": {"P4": 0.3, "P5": 0.2},
                "capacity": {"P3": 0.2, "P4": 0.2},
            },
            "keywords": {
                "P1": ["production down", "outage", "data loss", "security breach", "critical failure"],
                "P2": ["degraded", "major impact", "significant", "urgent"],
                "P3": ["partial", "minor impact", "workaround"],
                "P4": ["low impact", "non-critical"],
                "P5": ["informational", "warning"],
                "P6": ["cosmetic", "trivial"],
            },
        })

    @property
    def client(self):
        """Lazy initialization of Bedrock client."""
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def classify(
        self,
        analyzed_events: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> List[Incident]:
        """
        Classify analyzed events into incidents with priorities.

        Args:
            analyzed_events: Events with anomaly scores from AnomalyDetector
            context: Optional context for classification

        Returns:
            List of Incident objects with assigned priorities
        """
        incidents = []

        # Group related events into potential incidents
        incident_groups = self._group_into_incidents(analyzed_events)

        for group in incident_groups:
            # Calculate base priority from rules
            priority = self._rule_based_classification(group)

            # Optionally refine with AI
            if self.use_ai and len(group) > 0:
                try:
                    ai_priority = await self._ai_classification(group, context)
                    # Take the more severe classification
                    priority = self._more_severe(priority, ai_priority)
                except Exception as e:
                    print(f"AI classification error: {e}")

            # Create incident
            incident = self._create_incident(group, priority)
            incidents.append(incident)

        return incidents

    def _group_into_incidents(
        self,
        analyzed_events: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """Group analyzed events into potential incidents."""
        # Filter for actual anomalies
        anomalies = [
            e for e in analyzed_events
            if e.get("is_anomaly", False) or
            (e.get("anomaly_score") and e["anomaly_score"].score >= 0.5)
        ]

        if not anomalies:
            return []

        # Group by category and resource
        groups = {}
        for event in anomalies:
            category = event.get("category", IncidentCategory.UNKNOWN)
            resource = event.get("event", {}).get("resource_id", "unknown")
            key = f"{category.value}:{resource}"

            if key not in groups:
                groups[key] = []
            groups[key].append(event)

        return list(groups.values())

    def _rule_based_classification(self, events: List[Dict[str, Any]]) -> Priority:
        """Classify using rule-based approach."""
        if not events:
            return Priority.P6

        # Get highest anomaly score
        max_score = max(
            e.get("anomaly_score", AnomalyScore(0, 0, "")).score
            for e in events
        )

        # Determine category
        categories = [e.get("category", IncidentCategory.UNKNOWN) for e in events]
        primary_category = max(set(categories), key=categories.count)

        # Check anomaly thresholds
        thresholds = self.classification_rules["anomaly_thresholds"]
        base_priority = Priority.P6

        for priority_str, threshold in sorted(thresholds.items()):
            if max_score >= threshold:
                base_priority = Priority(priority_str)
                break

        # Adjust based on category
        category_weights = self.classification_rules["category_weights"]
        if primary_category.value in category_weights:
            weights = category_weights[primary_category.value]
            for priority_str, weight in weights.items():
                if max_score >= (thresholds[priority_str] - weight):
                    candidate = Priority(priority_str)
                    base_priority = self._more_severe(base_priority, candidate)
                    break

        # Check keywords in descriptions
        all_text = " ".join(
            e.get("event", {}).get("description", "").lower()
            for e in events
        )

        keywords = self.classification_rules["keywords"]
        for priority_str, kw_list in keywords.items():
            if any(kw in all_text for kw in kw_list):
                candidate = Priority(priority_str)
                base_priority = self._more_severe(base_priority, candidate)
                break

        return base_priority

    async def _ai_classification(
        self,
        events: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None
    ) -> Priority:
        """Use Claude for intelligent classification."""
        # Prepare events summary
        events_summary = []
        for e in events[:10]:
            event_data = e.get("event", {})
            events_summary.append({
                "title": event_data.get("title", ""),
                "description": event_data.get("description", "")[:300],
                "anomaly_score": e.get("anomaly_score", AnomalyScore(0, 0, "")).score,
                "category": e.get("category", IncidentCategory.UNKNOWN).value,
                "resource": event_data.get("resource_id", ""),
                "root_cause": e.get("root_cause", ""),
            })

        prompt = f"""You are an expert SRE classifying incident severity.

Classify the following incident into a priority level:
- P1: Critical - Production down, data loss risk, security breach
- P2: High - Major feature impacted, significant service degradation
- P3: Medium - Minor feature impacted, workaround available
- P4: Low - Minimal impact, non-critical systems affected
- P5: Very Low - Informational, potential future issue
- P6: Trivial - Cosmetic, no functional impact

Incident Events:
{json.dumps(events_summary, indent=2)}

Consider:
- Business impact
- Number of affected users/systems
- Data integrity risks
- Security implications
- Availability impact

Respond with ONLY the priority level (P1, P2, P3, P4, P5, or P6) and a brief justification in this format:
{{"priority": "P2", "justification": "..."}}"""

        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            })

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            response_text = response_body["content"][0]["text"]

            # Parse response
            result = json.loads(response_text)
            priority_str = result.get("priority", "P4")
            return Priority(priority_str)

        except Exception as e:
            print(f"AI classification failed: {e}")
            return Priority.P4  # Default to P4 on failure

    def _more_severe(self, p1: Priority, p2: Priority) -> Priority:
        """Return the more severe priority."""
        order = [Priority.P1, Priority.P2, Priority.P3, Priority.P4, Priority.P5, Priority.P6]
        return p1 if order.index(p1) < order.index(p2) else p2

    def _create_incident(
        self,
        events: List[Dict[str, Any]],
        priority: Priority
    ) -> Incident:
        """Create an Incident from analyzed events."""
        # Extract common information
        source_events = [e.get("event", {}) for e in events]
        categories = [e.get("category", IncidentCategory.UNKNOWN) for e in events]
        primary_category = max(set(categories), key=categories.count)

        # Get affected resources
        affected_resources = list(set(
            e.get("event", {}).get("resource_id")
            for e in events
            if e.get("event", {}).get("resource_id")
        ))

        # Build title and description
        first_event = events[0].get("event", {})
        title = first_event.get("title", "Unknown Incident")
        if len(events) > 1:
            title = f"{title} (+{len(events)-1} related events)"

        descriptions = [e.get("event", {}).get("description", "") for e in events]
        description = "\n\n".join(d for d in descriptions[:5] if d)

        # Get recommendations
        all_recommendations = []
        for e in events:
            all_recommendations.extend(e.get("recommended_actions", []))
        unique_recommendations = list(dict.fromkeys(all_recommendations))[:5]

        # Get root cause if available
        root_causes = [e.get("root_cause") for e in events if e.get("root_cause")]
        root_cause = root_causes[0] if root_causes else None

        # Get anomaly score (highest)
        anomaly_scores = [
            e.get("anomaly_score")
            for e in events
            if e.get("anomaly_score")
        ]
        best_score = max(anomaly_scores, key=lambda s: s.score) if anomaly_scores else None

        return Incident(
            incident_id=generate_incident_id(source_events),
            title=title,
            description=description,
            priority=priority,
            category=primary_category,
            status=IncidentStatus.CLASSIFIED,
            source_events=source_events,
            event_count=len(events),
            affected_resources=affected_resources,
            resource_type=first_event.get("resource_type"),
            region=first_event.get("region"),
            anomaly_score=best_score,
            root_cause_analysis=root_cause,
            recommended_actions=unique_recommendations,
        )

    def get_priority_description(self, priority: Priority) -> str:
        """Get human-readable description of priority."""
        descriptions = {
            Priority.P1: "Critical - Production down, data loss risk, immediate action required",
            Priority.P2: "High - Major feature impacted, urgent attention needed",
            Priority.P3: "Medium - Minor feature impacted, workaround available",
            Priority.P4: "Low - Minimal impact, can be addressed in normal workflow",
            Priority.P5: "Very Low - Informational, monitor for changes",
            Priority.P6: "Trivial - Cosmetic issue, no functional impact",
        }
        return descriptions.get(priority, "Unknown priority")
