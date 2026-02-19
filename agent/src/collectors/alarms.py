"""
CloudWatch Alarms Collector.
Monitors and collects CloudWatch alarms in ALARM state.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .base import BaseCollector, CloudWatchEvent, EventType, ResourceType


class AlarmsCollector(BaseCollector):
    """
    Collects CloudWatch alarms that are in ALARM state.

    Monitors:
    - Metric alarms
    - Composite alarms
    - Anomaly detection alarms
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.alarm_name_prefixes = config.get("alarm_name_prefixes", [])
        self.include_ok_to_alarm = config.get("include_ok_to_alarm", True)

    @property
    def client(self):
        """Lazy initialization of CloudWatch client."""
        if self._client is None:
            self._client = boto3.client("cloudwatch", region_name=self.region)
        return self._client

    async def collect(self) -> List[CloudWatchEvent]:
        """Collect all alarms in ALARM state."""
        events = []

        try:
            # Collect metric alarms
            metric_alarms = await self._collect_metric_alarms()
            events.extend(metric_alarms)

            # Collect composite alarms
            composite_alarms = await self._collect_composite_alarms()
            events.extend(composite_alarms)

        except NoCredentialsError:
            print("AWS credentials not configured for CloudWatch Alarms")
        except ClientError as e:
            print(f"Error collecting CloudWatch alarms: {e}")

        return events

    async def _collect_metric_alarms(self) -> List[CloudWatchEvent]:
        """Collect metric alarms in ALARM state."""
        events = []

        paginator = self.client.get_paginator("describe_alarms")
        page_iterator = paginator.paginate(StateValue="ALARM")

        for page in page_iterator:
            for alarm in page.get("MetricAlarms", []):
                # Filter by namespace if specified
                namespace = alarm.get("Namespace", "")
                if self.namespaces and namespace not in self.namespaces:
                    continue

                # Filter by alarm name prefix if specified
                alarm_name = alarm.get("AlarmName", "")
                if self.alarm_name_prefixes:
                    if not any(alarm_name.startswith(p) for p in self.alarm_name_prefixes):
                        continue

                event = self._alarm_to_event(alarm)
                if event:
                    events.append(event)

        return events

    async def _collect_composite_alarms(self) -> List[CloudWatchEvent]:
        """Collect composite alarms in ALARM state."""
        events = []

        paginator = self.client.get_paginator("describe_alarms")
        page_iterator = paginator.paginate(
            StateValue="ALARM",
            AlarmTypes=["CompositeAlarm"]
        )

        for page in page_iterator:
            for alarm in page.get("CompositeAlarms", []):
                event = self._composite_alarm_to_event(alarm)
                if event:
                    events.append(event)

        return events

    def _alarm_to_event(self, alarm: Dict[str, Any]) -> Optional[CloudWatchEvent]:
        """Convert CloudWatch metric alarm to CloudWatchEvent."""
        alarm_name = alarm.get("AlarmName", "Unknown")
        namespace = alarm.get("Namespace", "")
        metric_name = alarm.get("MetricName", "")

        # Extract dimensions
        dimensions = {}
        for dim in alarm.get("Dimensions", []):
            dimensions[dim["Name"]] = dim["Value"]

        # Determine resource ID from dimensions
        resource_id = self._extract_resource_id(dimensions, namespace)

        # Get state transition timestamp
        state_updated = alarm.get("StateUpdatedTimestamp", datetime.now(timezone.utc))
        if isinstance(state_updated, str):
            state_updated = datetime.fromisoformat(state_updated.replace("Z", "+00:00"))

        # Build description
        description = alarm.get("AlarmDescription") or ""
        state_reason = alarm.get("StateReason", "")
        if state_reason:
            description = f"{description}\n\nReason: {state_reason}" if description else state_reason

        return CloudWatchEvent(
            event_id=self.generate_event_id("alarm", alarm_name, state_updated.isoformat()),
            event_type=EventType.ALARM,
            source="cloudwatch-alarms",
            timestamp=state_updated,
            resource_type=self.get_resource_type(namespace),
            resource_id=resource_id,
            resource_arn=alarm.get("AlarmArn"),
            namespace=namespace,
            region=self.region,
            title=f"CloudWatch Alarm: {alarm_name}",
            description=description,
            metric_name=metric_name,
            metric_value=alarm.get("StateReasonData", {}).get("recentDatapoints", [None])[0] if alarm.get("StateReasonData") else None,
            threshold=alarm.get("Threshold"),
            unit=alarm.get("Unit"),
            state="ALARM",
            previous_state=alarm.get("StateTransitionedTimestamp"),
            dimensions=dimensions,
            raw_data=alarm,
        )

    def _composite_alarm_to_event(self, alarm: Dict[str, Any]) -> Optional[CloudWatchEvent]:
        """Convert CloudWatch composite alarm to CloudWatchEvent."""
        alarm_name = alarm.get("AlarmName", "Unknown")

        state_updated = alarm.get("StateUpdatedTimestamp", datetime.now(timezone.utc))
        if isinstance(state_updated, str):
            state_updated = datetime.fromisoformat(state_updated.replace("Z", "+00:00"))

        return CloudWatchEvent(
            event_id=self.generate_event_id("composite", alarm_name, state_updated.isoformat()),
            event_type=EventType.ALARM,
            source="cloudwatch-alarms",
            timestamp=state_updated,
            resource_type=ResourceType.UNKNOWN,
            resource_arn=alarm.get("AlarmArn"),
            region=self.region,
            title=f"Composite Alarm: {alarm_name}",
            description=alarm.get("AlarmDescription") or alarm.get("StateReason", ""),
            state="ALARM",
            raw_data=alarm,
        )

    def _extract_resource_id(self, dimensions: Dict[str, str], namespace: str) -> Optional[str]:
        """Extract resource ID from dimensions based on namespace."""
        # Priority order for resource identification
        id_keys = {
            "AWS/EC2": ["InstanceId", "AutoScalingGroupName"],
            "AWS/EBS": ["VolumeId"],
            "AWS/ECS": ["ServiceName", "ClusterName"],
            "AWS/EKS": ["ClusterName"],
            "AWS/Lambda": ["FunctionName"],
            "AWS/RDS": ["DBInstanceIdentifier", "DBClusterIdentifier"],
            "AWS/ApplicationELB": ["LoadBalancer", "TargetGroup"],
        }

        keys_to_check = id_keys.get(namespace, list(dimensions.keys()))
        for key in keys_to_check:
            if key in dimensions:
                return dimensions[key]

        return None

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to CloudWatch Alarms."""
        try:
            # Try to describe alarms (limit 1)
            self.client.describe_alarms(MaxRecords=1)
            return {
                "success": True,
                "message": f"Connected to CloudWatch Alarms in {self.region}",
                "region": self.region,
            }
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS credentials not configured",
            }
        except ClientError as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def get_alarm_history(self, alarm_name: str, days: int = 7) -> List[Dict[str, Any]]:
        """Get history for a specific alarm."""
        from datetime import timedelta

        try:
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(days=days)

            response = self.client.describe_alarm_history(
                AlarmName=alarm_name,
                HistoryItemType="StateUpdate",
                StartDate=start_time,
                EndDate=end_time,
                MaxRecords=100,
            )

            return response.get("AlarmHistoryItems", [])
        except ClientError:
            return []
