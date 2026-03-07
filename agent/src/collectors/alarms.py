"""
CloudWatch Alarms Collector.
Monitors and collects CloudWatch alarms in ALARM state.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from collectors.base import BaseCollector, CloudWatchEvent, EventType, ResourceType


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
        """Collect alarms in ALARM state AND recently transitioned alarms."""
        events = []
        seen_alarm_names = set()

        try:
            # 1. Collect alarms currently in ALARM state
            metric_alarms = await self._collect_metric_alarms()
            for event in metric_alarms:
                events.append(event)
                seen_alarm_names.add(event.title)

            # 2. Collect composite alarms currently in ALARM state
            composite_alarms = await self._collect_composite_alarms()
            for event in composite_alarms:
                events.append(event)
                seen_alarm_names.add(event.title)

            # 3. Also check alarm history for recent transitions to ALARM
            #    This catches alarms that fired but reverted to OK before we polled
            recent_alarms = await self._collect_recent_alarm_history()
            for event in recent_alarms:
                if event.title not in seen_alarm_names:
                    events.append(event)

        except NoCredentialsError:
            print("AWS credentials not configured for CloudWatch Alarms")
        except ClientError as e:
            print(f"Error collecting CloudWatch alarms: {e}")

        return events

    async def _collect_recent_alarm_history(self) -> List[CloudWatchEvent]:
        """Check alarm history for alarms that transitioned to ALARM recently."""
        from datetime import timedelta
        import json as _json

        events = []
        end_time = datetime.now(timezone.utc)
        # Look back 2x the collection interval to avoid missing any
        start_time = end_time - timedelta(seconds=max(120, self.config.get("collection_interval", 60) * 2))

        try:
            response = self.client.describe_alarm_history(
                HistoryItemType="StateUpdate",
                StartDate=start_time,
                EndDate=end_time,
                MaxRecords=50,
            )

            for item in response.get("AlarmHistoryItems", []):
                # Parse the history data to find transitions TO alarm state
                try:
                    history_data = _json.loads(item.get("HistoryData", "{}"))
                    new_state = history_data.get("newState", {}).get("stateValue", "")
                    if new_state != "ALARM":
                        continue

                    alarm_name = item.get("AlarmName", "")

                    # Get the full alarm details
                    alarm_response = self.client.describe_alarms(AlarmNames=[alarm_name])
                    for alarm in alarm_response.get("MetricAlarms", []):
                        namespace = alarm.get("Namespace", "")
                        if self.namespaces and namespace not in self.namespaces:
                            continue
                        if self.alarm_name_prefixes:
                            if not any(alarm_name.startswith(p) for p in self.alarm_name_prefixes):
                                continue

                        # Use the history timestamp and reason for the event
                        alarm["StateReason"] = history_data.get("newState", {}).get("stateReason", alarm.get("StateReason", ""))
                        history_ts = item.get("Timestamp")
                        if history_ts:
                            alarm["StateUpdatedTimestamp"] = history_ts

                        event = self._alarm_to_event(alarm)
                        if event:
                            events.append(event)

                except (_json.JSONDecodeError, KeyError):
                    continue

        except ClientError as e:
            print(f"Error checking alarm history: {e}")

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
            metric_value=None,
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
