"""
CloudWatch Logs Collector.
Monitors log groups for errors and patterns.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .base import BaseCollector, CloudWatchEvent, EventType, ResourceType


class LogsCollector(BaseCollector):
    """
    Collects error patterns from CloudWatch Logs.

    Features:
    - Pattern-based log scanning
    - Error level detection
    - Multi-log-group monitoring
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.log_groups = config.get("log_groups", [])
        self.lookback_minutes = config.get("lookback_minutes", 15)
        self.max_events_per_group = config.get("max_events_per_group", 50)

        # Default error patterns to search for
        self.error_patterns = config.get("error_patterns", [
            "ERROR",
            "FATAL",
            "CRITICAL",
            "Exception",
            "Traceback",
            "failed",
            "timeout",
            "OutOfMemory",
            "OOMKilled",
        ])

    @property
    def client(self):
        """Lazy initialization of CloudWatch Logs client."""
        if self._client is None:
            self._client = boto3.client("logs", region_name=self.region)
        return self._client

    async def collect(self) -> List[CloudWatchEvent]:
        """Collect error events from configured log groups."""
        events = []

        # Get log groups to monitor
        log_groups_to_check = await self._get_log_groups()

        for log_group in log_groups_to_check:
            group_name = log_group if isinstance(log_group, str) else log_group.get("name")
            patterns = log_group.get("patterns", self.error_patterns) if isinstance(log_group, dict) else self.error_patterns

            try:
                group_events = await self._scan_log_group(group_name, patterns)
                events.extend(group_events)
            except ClientError as e:
                print(f"Error scanning log group {group_name}: {e}")

        return events

    async def _get_log_groups(self) -> List[Any]:
        """Get list of log groups to monitor."""
        if self.log_groups:
            return self.log_groups

        # Auto-discover log groups based on namespaces
        discovered = []
        try:
            paginator = self.client.get_paginator("describe_log_groups")
            for page in paginator.paginate():
                for group in page.get("logGroups", []):
                    group_name = group.get("logGroupName", "")
                    # Filter for relevant log groups
                    if any(ns.lower() in group_name.lower() for ns in ["ec2", "ecs", "eks", "lambda", "rds"]):
                        discovered.append(group_name)
        except ClientError:
            pass

        return discovered[:20]  # Limit auto-discovery

    async def _scan_log_group(self, log_group: str, patterns: List[str]) -> List[CloudWatchEvent]:
        """Scan a log group for error patterns."""
        events = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=self.lookback_minutes)

        # Build filter pattern
        filter_pattern = " ".join(f'?"{p}"' for p in patterns)

        try:
            response = self.client.filter_log_events(
                logGroupName=log_group,
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                filterPattern=filter_pattern,
                limit=self.max_events_per_group,
            )

            for log_event in response.get("events", []):
                event = self._log_event_to_cloudwatch_event(log_event, log_group)
                if event:
                    events.append(event)

        except ClientError as e:
            if "ResourceNotFoundException" not in str(e):
                raise

        return events

    def _log_event_to_cloudwatch_event(
        self,
        log_event: Dict[str, Any],
        log_group: str
    ) -> Optional[CloudWatchEvent]:
        """Convert CloudWatch log event to CloudWatchEvent."""
        message = log_event.get("message", "")
        timestamp_ms = log_event.get("timestamp", 0)
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        log_stream = log_event.get("logStreamName", "")

        # Determine severity from message content
        severity = self._determine_log_severity(message)

        # Extract resource info from log group name
        resource_type, resource_id = self._parse_log_group_name(log_group)

        # Truncate long messages
        truncated_message = message[:1000] if len(message) > 1000 else message

        return CloudWatchEvent(
            event_id=self.generate_event_id("log", log_group, log_stream, str(timestamp_ms)),
            event_type=EventType.LOG,
            source="cloudwatch-logs",
            timestamp=timestamp,
            resource_type=resource_type,
            resource_id=resource_id,
            namespace=log_group,
            region=self.region,
            title=f"Log Error: {log_group}",
            description=truncated_message,
            state=severity,
            dimensions={"logStream": log_stream},
            tags={"logGroup": log_group, "severity": severity},
            raw_data=log_event,
        )

    def _determine_log_severity(self, message: str) -> str:
        """Determine severity level from log message."""
        message_lower = message.lower()

        if any(p in message_lower for p in ["fatal", "critical", "panic", "emergency"]):
            return "CRITICAL"
        elif any(p in message_lower for p in ["error", "exception", "traceback", "failed"]):
            return "ERROR"
        elif any(p in message_lower for p in ["warn", "warning"]):
            return "WARNING"
        else:
            return "INFO"

    def _parse_log_group_name(self, log_group: str) -> tuple:
        """Extract resource type and ID from log group name."""
        # Common patterns:
        # /aws/lambda/function-name
        # /aws/eks/cluster/container-insights
        # /ecs/service-name
        # /aws/rds/instance/dbname

        parts = log_group.strip("/").split("/")

        if len(parts) >= 2:
            if parts[0] == "aws":
                service = parts[1].lower()
                resource_id = parts[-1] if len(parts) > 2 else None

                if service == "lambda":
                    return ResourceType.LAMBDA, resource_id
                elif service == "eks":
                    return ResourceType.EKS, parts[2] if len(parts) > 2 else None
                elif service == "rds":
                    return ResourceType.RDS, parts[-1] if len(parts) > 3 else None
                elif service == "ec2":
                    return ResourceType.EC2, resource_id
            elif parts[0] == "ecs":
                return ResourceType.ECS, parts[1] if len(parts) > 1 else None

        return ResourceType.UNKNOWN, log_group

    async def search_logs(
        self,
        log_group: str,
        query: str,
        hours: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Search logs using a specific query pattern.
        Useful for ad-hoc investigations.
        """
        results = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        try:
            response = self.client.filter_log_events(
                logGroupName=log_group,
                startTime=int(start_time.timestamp() * 1000),
                endTime=int(end_time.timestamp() * 1000),
                filterPattern=query,
                limit=100,
            )

            results = response.get("events", [])

        except ClientError as e:
            print(f"Error searching logs: {e}")

        return results

    async def get_log_group_info(self, log_group: str) -> Dict[str, Any]:
        """Get information about a log group."""
        try:
            response = self.client.describe_log_groups(
                logGroupNamePrefix=log_group,
                limit=1,
            )

            groups = response.get("logGroups", [])
            if groups:
                return groups[0]

        except ClientError:
            pass

        return {}

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to CloudWatch Logs."""
        try:
            self.client.describe_log_groups(limit=1)
            return {
                "success": True,
                "message": f"Connected to CloudWatch Logs in {self.region}",
                "region": self.region,
                "log_groups_configured": len(self.log_groups),
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
