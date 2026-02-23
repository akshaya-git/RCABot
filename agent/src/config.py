"""
Configuration management for the Proactive Monitoring Agent.
"""

import os
from typing import Any, Dict, List
import yaml


class Config:
    """Configuration loaded from environment and YAML."""

    def __init__(self):
        # AWS Configuration
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")

        # CloudWatch Configuration
        self.cloudwatch_namespaces = os.getenv("CLOUDWATCH_NAMESPACES", "").split(",")
        self.collection_interval = int(os.getenv("COLLECTION_INTERVAL", "60"))

        # ServiceNow Configuration
        self.servicenow_instance = os.getenv("SERVICENOW_INSTANCE", "")
        self.servicenow_username = os.getenv("SERVICENOW_USERNAME", "")
        self.servicenow_password = os.getenv("SERVICENOW_PASSWORD", "")
        self.servicenow_assignment_group = os.getenv("SERVICENOW_ASSIGNMENT_GROUP", "")
        self.servicenow_caller_id = os.getenv("SERVICENOW_CALLER_ID", "")

        # OpenSearch Configuration
        self.opensearch_endpoint = os.getenv("OPENSEARCH_ENDPOINT", "")

        # S3 RAG Data Configuration
        self.rag_s3_bucket = os.getenv("RAG_S3_BUCKET", "")
        self.rag_s3_runbooks_prefix = os.getenv("RAG_S3_RUNBOOKS_PREFIX", "runbooks/")
        self.rag_s3_case_history_prefix = os.getenv("RAG_S3_CASE_HISTORY_PREFIX", "case-history/")

        # Notification Configuration
        self.sns_topic_arn = os.getenv("SNS_TOPIC_ARN", "")
        self.notification_emails = os.getenv("NOTIFICATION_EMAILS", "").split(",")

        # Application Configuration
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8080"))
        self.debug = os.getenv("DEBUG", "false").lower() == "true"

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for agent initialization."""
        return {
            "region": self.region,
            "model_id": self.model_id,
            "namespaces": [ns.strip() for ns in self.cloudwatch_namespaces if ns.strip()],
            "collection_interval": self.collection_interval,
            "collectors": {
                "alarms": {"enabled": True},
                "metrics": {"enabled": True},
                "logs": {"enabled": True},
                "insights": {"enabled": True},
            },
            "servicenow": {
                "enabled": bool(self.servicenow_instance and self.servicenow_username),
                "instance": self.servicenow_instance,
                "username": self.servicenow_username,
                "password": self.servicenow_password,
                "assignment_group": self.servicenow_assignment_group,
                "caller_id": self.servicenow_caller_id,
            },
            "notifications": {
                "enabled": bool(self.sns_topic_arn),
                "region": self.region,
                "sns_topic_arn": self.sns_topic_arn,
                "distribution_list": [e.strip() for e in self.notification_emails if e.strip()],
            },
            "rag": {
                "opensearch_endpoint": self.opensearch_endpoint,
                "region": self.region,
            },
            "s3_rag": {
                "enabled": bool(self.rag_s3_bucket),
                "bucket": self.rag_s3_bucket,
                "region": self.region,
                "runbooks_prefix": self.rag_s3_runbooks_prefix,
                "case_history_prefix": self.rag_s3_case_history_prefix,
            },
        }


_config: Config = None


def get_config() -> Config:
    """Get configuration singleton."""
    global _config
    if _config is None:
        _config = Config()
    return _config
