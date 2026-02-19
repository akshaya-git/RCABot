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

        # Jira Configuration
        self.jira_url = os.getenv("JIRA_URL", "")
        self.jira_email = os.getenv("JIRA_EMAIL", "")
        self.jira_api_token = os.getenv("JIRA_API_TOKEN", "")
        self.jira_project = os.getenv("JIRA_PROJECT", "OPS")

        # OpenSearch Configuration
        self.opensearch_endpoint = os.getenv("OPENSEARCH_ENDPOINT", "")

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
            "jira": {
                "enabled": bool(self.jira_url and self.jira_email),
                "url": self.jira_url,
                "email": self.jira_email,
                "api_token": self.jira_api_token,
                "project": self.jira_project,
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
        }


_config: Config = None


def get_config() -> Config:
    """Get configuration singleton."""
    global _config
    if _config is None:
        _config = Config()
    return _config
