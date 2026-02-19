"""
Base collector class and event models for CloudWatch data collection.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib


class EventType(str, Enum):
    """Types of CloudWatch events."""
    ALARM = "alarm"
    METRIC = "metric"
    LOG = "log"
    INSIGHT = "insight"


class ResourceType(str, Enum):
    """AWS resource types being monitored."""
    EC2 = "ec2"
    EBS = "ebs"
    ECS = "ecs"
    EKS = "eks"
    LAMBDA = "lambda"
    RDS = "rds"
    ALB = "alb"
    UNKNOWN = "unknown"


@dataclass
class CloudWatchEvent:
    """
    Normalized event from CloudWatch.
    Used as input for anomaly detection and classification.
    """
    # Event identification
    event_id: str
    event_type: EventType
    source: str  # e.g., "cloudwatch-alarms", "cloudwatch-metrics"

    # Timing
    timestamp: datetime
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Resource information
    resource_type: ResourceType = ResourceType.UNKNOWN
    resource_id: Optional[str] = None
    resource_arn: Optional[str] = None
    namespace: Optional[str] = None
    region: Optional[str] = None
    account_id: Optional[str] = None

    # Event details
    title: str = ""
    description: str = ""
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    unit: Optional[str] = None

    # State information
    state: Optional[str] = None  # e.g., "ALARM", "OK"
    previous_state: Optional[str] = None

    # Additional context
    dimensions: Dict[str, str] = field(default_factory=dict)
    tags: Dict[str, str] = field(default_factory=dict)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "timestamp": self.timestamp.isoformat(),
            "collected_at": self.collected_at.isoformat(),
            "resource_type": self.resource_type.value,
            "resource_id": self.resource_id,
            "resource_arn": self.resource_arn,
            "namespace": self.namespace,
            "region": self.region,
            "account_id": self.account_id,
            "title": self.title,
            "description": self.description,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "unit": self.unit,
            "state": self.state,
            "previous_state": self.previous_state,
            "dimensions": self.dimensions,
            "tags": self.tags,
            "raw_data": self.raw_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CloudWatchEvent":
        """Create from dictionary."""
        return cls(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            source=data["source"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            collected_at=datetime.fromisoformat(data.get("collected_at", datetime.now(timezone.utc).isoformat())),
            resource_type=ResourceType(data.get("resource_type", "unknown")),
            resource_id=data.get("resource_id"),
            resource_arn=data.get("resource_arn"),
            namespace=data.get("namespace"),
            region=data.get("region"),
            account_id=data.get("account_id"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            metric_name=data.get("metric_name"),
            metric_value=data.get("metric_value"),
            threshold=data.get("threshold"),
            unit=data.get("unit"),
            state=data.get("state"),
            previous_state=data.get("previous_state"),
            dimensions=data.get("dimensions", {}),
            tags=data.get("tags", {}),
            raw_data=data.get("raw_data", {}),
        )


class BaseCollector(ABC):
    """
    Abstract base class for CloudWatch collectors.

    All collectors should inherit from this class and implement:
    - collect(): Gather events from CloudWatch
    - test_connection(): Verify connectivity
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize collector with configuration.

        Args:
            config: Collector configuration including:
                - region: AWS region
                - namespaces: List of CloudWatch namespaces to monitor
                - collection_interval: How often to collect (seconds)
        """
        self.config = config
        self.region = config.get("region", "us-east-1")
        self.namespaces = config.get("namespaces", [])
        self.enabled = config.get("enabled", True)
        self._client = None

    @abstractmethod
    async def collect(self) -> List[CloudWatchEvent]:
        """
        Collect events from CloudWatch.

        Returns:
            List of CloudWatchEvent objects
        """
        pass

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to CloudWatch.

        Returns:
            Dict with 'success' (bool) and 'message' or 'error' (str)
        """
        pass

    def is_enabled(self) -> bool:
        """Check if collector is enabled."""
        return self.enabled

    def generate_event_id(self, *args) -> str:
        """Generate a unique event ID from components."""
        content = ":".join(str(a) for a in args)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get_resource_type(self, namespace: str) -> ResourceType:
        """Determine resource type from CloudWatch namespace."""
        namespace_mapping = {
            "AWS/EC2": ResourceType.EC2,
            "AWS/EBS": ResourceType.EBS,
            "AWS/ECS": ResourceType.ECS,
            "AWS/EKS": ResourceType.EKS,
            "AWS/Lambda": ResourceType.LAMBDA,
            "AWS/RDS": ResourceType.RDS,
            "AWS/ApplicationELB": ResourceType.ALB,
            "AWS/NetworkELB": ResourceType.ALB,
        }
        return namespace_mapping.get(namespace, ResourceType.UNKNOWN)
