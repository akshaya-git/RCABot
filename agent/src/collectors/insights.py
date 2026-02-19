"""
CloudWatch Log Insights Collector.
Uses Log Insights queries for advanced log analysis and pattern detection.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .base import BaseCollector, CloudWatchEvent, EventType, ResourceType


class InsightsCollector(BaseCollector):
    """
    Collects insights from CloudWatch Logs using Log Insights queries.

    Features:
    - Custom query execution
    - Error aggregation
    - Pattern analysis
    - Top error ranking
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.log_groups = config.get("log_groups", [])
        self.lookback_minutes = config.get("lookback_minutes", 60)
        self.custom_queries = config.get("queries", [])
        self.query_timeout = config.get("query_timeout", 30)

        # Default queries for error detection
        self.default_queries = [
            {
                "name": "error_summary",
                "query": """
                    fields @timestamp, @message, @logStream
                    | filter @message like /(?i)(error|exception|failed|fatal)/
                    | stats count(*) as error_count by bin(5m) as time_bucket
                    | sort time_bucket desc
                    | limit 20
                """,
                "description": "Error count aggregated by 5-minute buckets",
            },
            {
                "name": "top_errors",
                "query": """
                    fields @timestamp, @message
                    | filter @message like /(?i)(error|exception)/
                    | parse @message /(?<error_type>\\w+Error|\\w+Exception)/
                    | stats count(*) as count by error_type
                    | sort count desc
                    | limit 10
                """,
                "description": "Top error types by frequency",
            },
            {
                "name": "latency_issues",
                "query": """
                    fields @timestamp, @message
                    | filter @message like /(?i)(timeout|latency|slow|duration)/
                    | parse @message /(?<duration>\\d+)\\s*(ms|milliseconds|seconds)/
                    | stats avg(duration) as avg_latency, max(duration) as max_latency by bin(5m)
                    | sort @timestamp desc
                    | limit 20
                """,
                "description": "Latency patterns over time",
            },
            {
                "name": "oom_events",
                "query": """
                    fields @timestamp, @message, @logStream
                    | filter @message like /(?i)(OutOfMemory|OOM|MemoryError|heap)/
                    | sort @timestamp desc
                    | limit 50
                """,
                "description": "Out of memory events",
            },
        ]

    @property
    def client(self):
        """Lazy initialization of CloudWatch Logs client."""
        if self._client is None:
            self._client = boto3.client("logs", region_name=self.region)
        return self._client

    async def collect(self) -> List[CloudWatchEvent]:
        """Run insight queries and collect significant findings."""
        events = []

        # Get log groups to analyze
        log_groups_to_analyze = await self._get_log_groups()
        if not log_groups_to_analyze:
            return events

        # Run default queries
        for query_config in self.default_queries:
            try:
                query_events = await self._run_query(
                    query_config["query"],
                    log_groups_to_analyze,
                    query_config["name"],
                    query_config["description"],
                )
                events.extend(query_events)
            except Exception as e:
                print(f"Error running query {query_config['name']}: {e}")

        # Run custom queries
        for query_config in self.custom_queries:
            try:
                query_events = await self._run_query(
                    query_config.get("query", ""),
                    query_config.get("log_groups", log_groups_to_analyze),
                    query_config.get("name", "custom"),
                    query_config.get("description", "Custom query"),
                )
                events.extend(query_events)
            except Exception as e:
                print(f"Error running custom query: {e}")

        return events

    async def _get_log_groups(self) -> List[str]:
        """Get list of log groups to analyze."""
        if self.log_groups:
            # Resolve log group names (may include patterns)
            resolved = []
            for lg in self.log_groups:
                if isinstance(lg, str):
                    if "*" in lg:
                        # Pattern matching
                        prefix = lg.replace("*", "")
                        try:
                            response = self.client.describe_log_groups(
                                logGroupNamePrefix=prefix,
                                limit=10,
                            )
                            resolved.extend([g["logGroupName"] for g in response.get("logGroups", [])])
                        except ClientError:
                            pass
                    else:
                        resolved.append(lg)
            return resolved[:10]  # Limit to 10 log groups per query

        # Auto-discover relevant log groups
        return await self._discover_log_groups()

    async def _discover_log_groups(self) -> List[str]:
        """Auto-discover relevant log groups."""
        discovered = []
        prefixes = ["/aws/lambda/", "/aws/eks/", "/aws/ecs/", "/aws/rds/", "/ecs/"]

        try:
            for prefix in prefixes:
                response = self.client.describe_log_groups(
                    logGroupNamePrefix=prefix,
                    limit=5,
                )
                discovered.extend([g["logGroupName"] for g in response.get("logGroups", [])])
        except ClientError:
            pass

        return discovered[:10]

    async def _run_query(
        self,
        query: str,
        log_groups: List[str],
        query_name: str,
        description: str
    ) -> List[CloudWatchEvent]:
        """Run a Log Insights query and convert results to events."""
        events = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=self.lookback_minutes)

        try:
            # Start query
            response = self.client.start_query(
                logGroupNames=log_groups,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query.strip(),
            )
            query_id = response["queryId"]

            # Wait for query completion
            results = await self._wait_for_query(query_id)

            # Process results
            if results:
                events = self._process_query_results(
                    results, log_groups, query_name, description
                )

        except ClientError as e:
            print(f"Query error: {e}")

        return events

    async def _wait_for_query(self, query_id: str) -> List[Dict[str, Any]]:
        """Wait for query to complete and return results."""
        for _ in range(self.query_timeout):
            try:
                response = self.client.get_query_results(queryId=query_id)
                status = response.get("status", "")

                if status == "Complete":
                    return response.get("results", [])
                elif status in ["Failed", "Cancelled"]:
                    return []

                await asyncio.sleep(1)

            except ClientError:
                break

        return []

    def _process_query_results(
        self,
        results: List[List[Dict[str, str]]],
        log_groups: List[str],
        query_name: str,
        description: str
    ) -> List[CloudWatchEvent]:
        """Convert query results to CloudWatchEvents."""
        events = []

        for row in results:
            # Convert row to dict
            row_dict = {field["field"]: field["value"] for field in row}

            # Skip if no significant data
            if not row_dict:
                continue

            # Extract timestamp if available
            timestamp_str = row_dict.get("@timestamp", row_dict.get("time_bucket", ""))
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                timestamp = datetime.now(timezone.utc)

            # Build event title and description
            title = f"Log Insight: {query_name}"
            event_description = f"{description}\n\nResults:\n"
            for key, value in row_dict.items():
                if not key.startswith("@"):
                    event_description += f"  {key}: {value}\n"

            # Check if this indicates an issue (error count > 0, etc.)
            has_issues = False
            for key, value in row_dict.items():
                if "error" in key.lower() or "count" in key.lower():
                    try:
                        if float(value) > 0:
                            has_issues = True
                            break
                    except (ValueError, TypeError):
                        pass

            if has_issues or query_name in ["oom_events", "latency_issues"]:
                events.append(CloudWatchEvent(
                    event_id=self.generate_event_id("insight", query_name, timestamp.isoformat()),
                    event_type=EventType.INSIGHT,
                    source="cloudwatch-insights",
                    timestamp=timestamp,
                    resource_type=ResourceType.UNKNOWN,
                    namespace=",".join(log_groups[:3]),
                    region=self.region,
                    title=title,
                    description=event_description.strip(),
                    tags={"query": query_name},
                    raw_data=row_dict,
                ))

        return events

    async def run_custom_query(
        self,
        query: str,
        log_groups: List[str],
        hours: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Run a custom Log Insights query.
        Useful for ad-hoc analysis.
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        try:
            response = self.client.start_query(
                logGroupNames=log_groups,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query.strip(),
            )
            query_id = response["queryId"]

            results = await self._wait_for_query(query_id)
            return [
                {field["field"]: field["value"] for field in row}
                for row in results
            ]

        except ClientError as e:
            print(f"Custom query error: {e}")
            return []

    async def get_error_trends(
        self,
        log_groups: List[str],
        hours: int = 24
    ) -> Dict[str, Any]:
        """Get error trends over time."""
        query = """
            fields @timestamp
            | filter @message like /(?i)(error|exception|failed)/
            | stats count(*) as errors by bin(1h) as hour
            | sort hour asc
        """

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        try:
            response = self.client.start_query(
                logGroupNames=log_groups,
                startTime=int(start_time.timestamp()),
                endTime=int(end_time.timestamp()),
                queryString=query,
            )

            results = await self._wait_for_query(response["queryId"])

            trend_data = []
            for row in results:
                row_dict = {field["field"]: field["value"] for field in row}
                trend_data.append({
                    "hour": row_dict.get("hour", ""),
                    "errors": int(row_dict.get("errors", 0)),
                })

            return {
                "log_groups": log_groups,
                "hours_analyzed": hours,
                "trend": trend_data,
            }

        except ClientError:
            return {"error": "Failed to get error trends"}

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to CloudWatch Log Insights."""
        try:
            # Try to describe log groups (simpler than running a query)
            self.client.describe_log_groups(limit=1)
            return {
                "success": True,
                "message": f"Connected to CloudWatch Log Insights in {self.region}",
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
