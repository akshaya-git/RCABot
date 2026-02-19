"""
Integrations Package.

External service integrations:
- JiraIntegration: Incident ticket management
- NotificationService: Email alerts via SNS/SES
"""

from .jira import JiraIntegration
from .notifications import NotificationService

__all__ = [
    "JiraIntegration",
    "NotificationService",
]
