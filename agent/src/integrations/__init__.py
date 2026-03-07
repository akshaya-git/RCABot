"""
Integrations Package.

External service integrations:
- ServiceNowIntegration: Incident ticket management
- NotificationService: Email alerts via SNS/SES
"""

from integrations.servicenow import ServiceNowIntegration
from integrations.notifications import NotificationService

__all__ = [
    "ServiceNowIntegration",
    "NotificationService",
]
