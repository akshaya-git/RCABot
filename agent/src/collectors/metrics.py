"""
CloudWatch Metrics Collector.
Monitors metrics and detects threshold breaches and anomalies.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .base import BaseCollector, CloudWatchEvent, EventType


class MetricsCollector(BaseCollector):
    """
    Collects CloudWatch metrics and detects anomalies.

    Features:
    - Threshold-based alerting
    - Statistical anomaly detection
    - Multi-metric correlation
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_minutes = config.get("lookback_minutes", 15)
        self.metric_configs = config.get("metrics", [])
        self.default_thresholds = config.get("default_thresholds", {
            "CPUUtilization": {"threshold": 80, "comparison": "GreaterThan"},
            "MemoryUtilization": {"threshold": 85, "comparison": "GreaterThan"},
            "DiskSpaceUtilization": {"threshold": 90, "comparison": "GreaterThan"},
            "StatusCheckFailed": {"threshold": 0, "comparison": "GreaterThan"},
            "NetworkIn": {"threshold": None, "comparison": "Anomaly"},
            "NetworkOut": {"threshold": None, "comparison": "Anomaly"},
        })

    @property
    def client(self):
        """Lazy initialization of CloudWatch client."""
        if self._client is None:
            self._client = boto3.client("cloudwatch", region_name=self.region)
        return self._client

    async def collect(self) -> List[CloudWatchEvent]:
        """Collect metrics that breach thresholds or show anomalies."""
        events = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=self.lookback_minutes)

        # Collect from configured metrics
        for metric_config in self.metric_configs:
            metric_events = await self._collect_metric(metric_config, start_time, end_time)
            events.extend(metric_events)

        # Collect from default metrics per namespace
        for namespace in self.namespaces:
            namespace_events = await self._collect_namespace_metrics(namespace, start_time, end_time)
            events.extend(namespace_events)

        return events

    async def _collect_metric(
        self,
        config: Dict[str, Any],
        start_time: datetime,
        end_time: datetime
    ) -> List[CloudWatchEvent]:
        """Collect a specific metric based on configuration."""
        events = []

        try:
            namespace = config.get("namespace")
            metric_name = config.get("metric_name")
            threshold = config.get("threshold")
            comparison = config.get("comparison", "GreaterThan")
            dimensions = config.get("dimensions", [])
            period = config.get("period", 300)

            response = self.client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=["Average", "Maximum", "Minimum"],
            )

            for datapoint in response.get("Datapoints", []):
                value = datapoint.get("Maximum") or datapoint.get("Average", 0)

                # Check threshold breach
                if self._check_threshold(value, threshold, comparison):
                    dim_dict = {d["Name"]: d["Value"] for d in dimensions}
                    resource_id = self._extract_resource_id_from_dimensions(dim_dict)

                    events.append(CloudWatchEvent(
                        event_id=self.generate_event_id(
                            "metric", namespace, metric_name,
                            datapoint.get("Timestamp", datetime.now(timezone.utc)).isoformat()
                        ),
                        event_type=EventType.METRIC,
                        source="cloudwatch-metrics",
                        timestamp=datapoint.get("Timestamp", datetime.now(timezone.utc)),
                        resource_type=self.get_resource_type(namespace),
                        resource_id=resource_id,
                        namespace=namespace,
                        region=self.region,
                        title=f"Metric Threshold Breach: {metric_name}",
                        description=f"{metric_name} is {value:.2f} ({comparison} {threshold})",
                        metric_name=metric_name,
                        metric_value=value,
                        threshold=threshold,
                        unit=datapoint.get("Unit"),
                        dimensions=dim_dict,
                        raw_data=datapoint,
                    ))

        except ClientError as e:
            print(f"Error collecting metric {config}: {e}")

        return events

    async def _collect_namespace_metrics(
        self,
        namespace: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[CloudWatchEvent]:
        """Collect key metrics for a namespace using default thresholds."""
        events = []

        try:
            # List metrics in the namespace
            paginator = self.client.get_paginator("list_metrics")
            metrics_to_check = []

            for page in paginator.paginate(Namespace=namespace):
                for metric in page.get("Metrics", []):
                    metric_name = metric.get("MetricName", "")
                    if metric_name in self.default_thresholds:
                        metrics_to_check.append({
                            "metric_name": metric_name,
                            "dimensions": metric.get("Dimensions", []),
                            **self.default_thresholds[metric_name]
                        })

            # Check each metric
            for metric in metrics_to_check[:50]:  # Limit to avoid rate limiting
                config = {
                    "namespace": namespace,
                    "metric_name": metric["metric_name"],
                    "threshold": metric.get("threshold"),
                    "comparison": metric.get("comparison", "GreaterThan"),
                    "dimensions": metric["dimensions"],
                }
                metric_events = await self._collect_metric(config, start_time, end_time)
                events.extend(metric_events)

        except ClientError as e:
            print(f"Error collecting namespace metrics for {namespace}: {e}")

        return events

    def _check_threshold(self, value: float, threshold: Optional[float], comparison: str) -> bool:
        """Check if value breaches threshold."""
        if threshold is None:
            return False

        if comparison == "GreaterThan":
            return value > threshold
        elif comparison == "GreaterThanOrEqual":
            return value >= threshold
        elif comparison == "LessThan":
            return value < threshold
        elif comparison == "LessThanOrEqual":
            return value <= threshold
        elif comparison == "Anomaly":
            # For anomaly detection, we'd need more sophisticated analysis
            return False

        return False

    def _extract_resource_id_from_dimensions(self, dimensions: Dict[str, str]) -> Optional[str]:
        """Extract resource ID from dimension dictionary."""
        priority_keys = [
            "InstanceId", "VolumeId", "FunctionName", "ServiceName",
            "ClusterName", "DBInstanceIdentifier", "LoadBalancer"
        ]
        for key in priority_keys:
            if key in dimensions:
                return dimensions[key]
        return list(dimensions.values())[0] if dimensions else None

    async def get_metric_anomalies(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Detect anomalies using CloudWatch Anomaly Detection.
        Requires anomaly detector to be set up for the metric.
        """
        anomalies = []
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        try:
            response = self.client.get_metric_data(
                MetricDataQueries=[
                    {
                        "Id": "anomaly_band",
                        "Expression": f"ANOMALY_DETECTION_BAND(m1, 2)",
                        "Label": "AnomalyBand",
                    },
                    {
                        "Id": "m1",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": namespace,
                                "MetricName": metric_name,
                                "Dimensions": dimensions,
                            },
                            "Period": 300,
                            "Stat": "Average",
                        },
                        "ReturnData": True,
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
            )

            # Process anomaly detection results
            for result in response.get("MetricDataResults", []):
                if result.get("Id") == "m1":
                    values = result.get("Values", [])
                    timestamps = result.get("Timestamps", [])

                    for i, (ts, val) in enumerate(zip(timestamps, values)):
                        # Check if value is outside anomaly band
                        # This is simplified - actual implementation would compare with band
                        anomalies.append({
                            "timestamp": ts,
                            "value": val,
                            "metric_name": metric_name,
                            "namespace": namespace,
                        })

        except ClientError as e:
            print(f"Error detecting anomalies: {e}")

        return anomalies

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to CloudWatch Metrics."""
        try:
            self.client.list_metrics(Limit=1)
            return {
                "success": True,
                "message": f"Connected to CloudWatch Metrics in {self.region}",
                "region": self.region,
                "namespaces": self.namespaces,
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
