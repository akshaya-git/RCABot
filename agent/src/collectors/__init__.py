"""
CloudWatch Collectors Package.

Provides collectors for various CloudWatch data sources:
- Alarms: CloudWatch alarm state monitoring
- Metrics: Metric threshold and anomaly detection
- Logs: Log pattern scanning
- Insights: Advanced log analysis with Log Insights queries
"""

from .base import BaseCollector, CloudWatchEvent, EventType, ResourceType
from .alarms import AlarmsCollector
from .metrics import MetricsCollector
from .logs import LogsCollector
from .insights import InsightsCollector

__all__ = [
    # Base classes
    "BaseCollector",
    "CloudWatchEvent",
    "EventType",
    "ResourceType",
    # Collectors
    "AlarmsCollector",
    "MetricsCollector",
    "LogsCollector",
    "InsightsCollector",
]


class CollectorManager:
    """
    Manages all CloudWatch collectors and orchestrates data collection.
    """

    def __init__(self, config: dict):
        """
        Initialize collector manager with configuration.

        Args:
            config: Configuration dict with collector settings
        """
        self.config = config
        self.collectors = {}
        self._initialize_collectors()

    def _initialize_collectors(self):
        """Initialize all configured collectors."""
        collector_classes = {
            "alarms": AlarmsCollector,
            "metrics": MetricsCollector,
            "logs": LogsCollector,
            "insights": InsightsCollector,
        }

        collectors_config = self.config.get("collectors", {})

        for name, collector_cls in collector_classes.items():
            collector_config = collectors_config.get(name, {})
            if collector_config.get("enabled", True):
                # Merge global config with collector-specific config
                merged_config = {
                    "region": self.config.get("region", "us-east-1"),
                    "namespaces": self.config.get("namespaces", []),
                    **collector_config,
                }
                self.collectors[name] = collector_cls(merged_config)

    async def collect_all(self) -> list[CloudWatchEvent]:
        """
        Collect events from all enabled collectors.

        Returns:
            List of CloudWatchEvent from all collectors
        """
        all_events = []

        for name, collector in self.collectors.items():
            if collector.is_enabled():
                try:
                    events = await collector.collect()
                    all_events.extend(events)
                    print(f"Collected {len(events)} events from {name}")
                except Exception as e:
                    print(f"Error collecting from {name}: {e}")

        return all_events

    async def test_all_connections(self) -> dict:
        """
        Test connections for all collectors.

        Returns:
            Dict of collector name to test result
        """
        results = {}

        for name, collector in self.collectors.items():
            try:
                results[name] = await collector.test_connection()
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}

        return results

    def get_collector(self, name: str) -> BaseCollector | None:
        """Get a specific collector by name."""
        return self.collectors.get(name)

    def list_collectors(self) -> list[str]:
        """List all initialized collector names."""
        return list(self.collectors.keys())
