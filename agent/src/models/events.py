"""
Event and Incident models for the monitoring system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib


class Priority(str, Enum):
    """Incident priority levels (P1-P6)."""
    P1 = "P1"  # Critical - Production down
    P2 = "P2"  # High - Major feature impacted
    P3 = "P3"  # Medium - Minor feature impacted
    P4 = "P4"  # Low - Minimal impact
    P5 = "P5"  # Very Low - Informational
    P6 = "P6"  # Trivial - Cosmetic


class IncidentStatus(str, Enum):
    """Incident lifecycle status."""
    DETECTED = "detected"
    ANALYZING = "analyzing"
    CLASSIFIED = "classified"
    TICKET_CREATED = "ticket_created"
    NOTIFIED = "notified"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentCategory(str, Enum):
    """Categories of incidents."""
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    ERROR_RATE = "error_rate"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    SECURITY = "security"
    CONFIGURATION = "configuration"
    CAPACITY = "capacity"
    UNKNOWN = "unknown"


@dataclass
class AnomalyScore:
    """Score indicating anomaly severity."""
    score: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reasoning: str
    factors: List[str] = field(default_factory=list)

    def is_anomaly(self, threshold: float = 0.7) -> bool:
        """Check if score indicates an anomaly."""
        return self.score >= threshold


@dataclass
class Incident:
    """
    Represents a detected incident from CloudWatch events.
    """
    # Identification
    incident_id: str
    title: str
    description: str

    # Classification
    priority: Priority
    category: IncidentCategory
    status: IncidentStatus = IncidentStatus.DETECTED

    # Timing
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Source events
    source_events: List[Dict[str, Any]] = field(default_factory=list)
    event_count: int = 1

    # Resource information
    affected_resources: List[str] = field(default_factory=list)
    resource_type: Optional[str] = None
    region: Optional[str] = None
    account_id: Optional[str] = None

    # Analysis
    anomaly_score: Optional[AnomalyScore] = None
    root_cause_analysis: Optional[str] = None
    recommended_actions: List[str] = field(default_factory=list)

    # Ticket tracking
    jira_ticket_key: Optional[str] = None
    jira_ticket_url: Optional[str] = None

    # Notifications
    notifications_sent: List[Dict[str, Any]] = field(default_factory=list)

    # Additional context
    tags: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "incident_id": self.incident_id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority.value,
            "category": self.category.value,
            "status": self.status.value,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "last_updated": self.last_updated.isoformat(),
            "source_events": self.source_events,
            "event_count": self.event_count,
            "affected_resources": self.affected_resources,
            "resource_type": self.resource_type,
            "region": self.region,
            "account_id": self.account_id,
            "anomaly_score": {
                "score": self.anomaly_score.score,
                "confidence": self.anomaly_score.confidence,
                "reasoning": self.anomaly_score.reasoning,
                "factors": self.anomaly_score.factors,
            } if self.anomaly_score else None,
            "root_cause_analysis": self.root_cause_analysis,
            "recommended_actions": self.recommended_actions,
            "jira_ticket_key": self.jira_ticket_key,
            "jira_ticket_url": self.jira_ticket_url,
            "notifications_sent": self.notifications_sent,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Incident":
        """Create from dictionary."""
        anomaly_data = data.get("anomaly_score")
        anomaly_score = None
        if anomaly_data:
            anomaly_score = AnomalyScore(
                score=anomaly_data["score"],
                confidence=anomaly_data["confidence"],
                reasoning=anomaly_data["reasoning"],
                factors=anomaly_data.get("factors", []),
            )

        return cls(
            incident_id=data["incident_id"],
            title=data["title"],
            description=data["description"],
            priority=Priority(data["priority"]),
            category=IncidentCategory(data.get("category", "unknown")),
            status=IncidentStatus(data.get("status", "detected")),
            detected_at=datetime.fromisoformat(data["detected_at"]),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            last_updated=datetime.fromisoformat(data.get("last_updated", data["detected_at"])),
            source_events=data.get("source_events", []),
            event_count=data.get("event_count", 1),
            affected_resources=data.get("affected_resources", []),
            resource_type=data.get("resource_type"),
            region=data.get("region"),
            account_id=data.get("account_id"),
            anomaly_score=anomaly_score,
            root_cause_analysis=data.get("root_cause_analysis"),
            recommended_actions=data.get("recommended_actions", []),
            jira_ticket_key=data.get("jira_ticket_key"),
            jira_ticket_url=data.get("jira_ticket_url"),
            notifications_sent=data.get("notifications_sent", []),
            tags=data.get("tags", {}),
            metadata=data.get("metadata", {}),
        )

    def is_high_priority(self) -> bool:
        """Check if incident requires immediate attention (P1-P3)."""
        return self.priority in [Priority.P1, Priority.P2, Priority.P3]

    def is_low_priority(self) -> bool:
        """Check if incident is low priority (P4-P6)."""
        return self.priority in [Priority.P4, Priority.P5, Priority.P6]

    def should_auto_close(self) -> bool:
        """Check if incident should be auto-closed after logging."""
        return self.is_low_priority()

    def update_status(self, status: IncidentStatus):
        """Update incident status with timestamp."""
        self.status = status
        self.last_updated = datetime.now(timezone.utc)

    def add_event(self, event: Dict[str, Any]):
        """Add a source event to the incident."""
        self.source_events.append(event)
        self.event_count = len(self.source_events)
        self.last_updated = datetime.now(timezone.utc)

    def set_ticket(self, key: str, url: str):
        """Set Jira ticket information."""
        self.jira_ticket_key = key
        self.jira_ticket_url = url
        self.update_status(IncidentStatus.TICKET_CREATED)

    def resolve(self, resolution: Optional[str] = None):
        """Mark incident as resolved."""
        self.resolved_at = datetime.now(timezone.utc)
        self.update_status(IncidentStatus.RESOLVED)
        if resolution:
            self.metadata["resolution"] = resolution


def generate_incident_id(events: List[Dict[str, Any]]) -> str:
    """Generate a unique incident ID from events."""
    content = ":".join(
        str(e.get("event_id", e.get("title", "")))
        for e in events[:5]
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    return hashlib.sha256(f"{content}:{timestamp}".encode()).hexdigest()[:12]
