"""
Integrations Package.

External service integrations:
- ServiceNowIntegration: Incident ticket management
- NotificationService: Email alerts via SNS/SES
"""

from .servicenow import ServiceNowIntegration
from .notifications import NotificationService

__all__ = [
    "ServiceNowIntegration",
    "NotificationService",
]
