"""
Notification Service for sending alerts via SNS/SES.
Handles email notifications to distribution lists.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import ClientError

from ..models.events import Incident, Priority


class NotificationService:
    """
    Sends notifications for incidents via AWS SNS/SES.

    Features:
    - Email notifications to distribution lists
    - Priority-based notification routing
    - Formatted incident summaries
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize notification service.

        Args:
            config: Configuration including:
                - region: AWS region
                - sns_topic_arn: SNS topic for notifications
                - from_email: SES verified sender email
                - distribution_list: List of email addresses
        """
        self.region = config.get("region", "us-east-1")
        self.sns_topic_arn = config.get("sns_topic_arn", "")
        self.from_email = config.get("from_email", "")
        self.distribution_list = config.get("distribution_list", [])
        self.enabled = config.get("enabled", True)

        # Notification preferences by priority
        self.notification_rules = config.get("notification_rules", {
            "P1": {"immediate": True, "channels": ["sns", "ses"]},
            "P2": {"immediate": True, "channels": ["sns", "ses"]},
            "P3": {"immediate": True, "channels": ["sns"]},
            "P4": {"immediate": False, "channels": ["sns"]},
            "P5": {"immediate": False, "channels": []},
            "P6": {"immediate": False, "channels": []},
        })

        self._sns_client = None
        self._ses_client = None

    @property
    def sns_client(self):
        """Lazy initialization of SNS client."""
        if self._sns_client is None:
            self._sns_client = boto3.client("sns", region_name=self.region)
        return self._sns_client

    @property
    def ses_client(self):
        """Lazy initialization of SES client."""
        if self._ses_client is None:
            self._ses_client = boto3.client("ses", region_name=self.region)
        return self._ses_client

    async def notify(self, incident: Incident) -> Dict[str, Any]:
        """
        Send notifications for an incident.

        Args:
            incident: Incident to notify about

        Returns:
            Dict with notification results
        """
        if not self.enabled:
            return {"success": False, "reason": "Notifications disabled"}

        results = {
            "sns": None,
            "ses": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Get notification rules for this priority
        rules = self.notification_rules.get(
            incident.priority.value,
            {"immediate": False, "channels": []}
        )

        if not rules.get("channels"):
            return {"success": True, "reason": "No notifications required for this priority"}

        # Send via configured channels
        if "sns" in rules["channels"] and self.sns_topic_arn:
            results["sns"] = await self._send_sns(incident)

        if "ses" in rules["channels"] and self.from_email and self.distribution_list:
            results["ses"] = await self._send_ses(incident)

        # Record notification in incident
        incident.notifications_sent.append({
            "timestamp": results["timestamp"],
            "channels": rules["channels"],
            "results": results,
        })

        return results

    async def _send_sns(self, incident: Incident) -> Dict[str, Any]:
        """Send notification via SNS."""
        try:
            subject = f"[{incident.priority.value}] {incident.title}"[:100]
            message = self._build_sns_message(incident)

            response = self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Subject=subject,
                Message=message,
                MessageAttributes={
                    "priority": {
                        "DataType": "String",
                        "StringValue": incident.priority.value,
                    },
                    "category": {
                        "DataType": "String",
                        "StringValue": incident.category.value,
                    },
                },
            )

            return {
                "success": True,
                "message_id": response.get("MessageId"),
            }

        except ClientError as e:
            return {"success": False, "error": str(e)}

    async def _send_ses(self, incident: Incident) -> Dict[str, Any]:
        """Send notification via SES."""
        try:
            subject = f"[{incident.priority.value}] {incident.title}"
            html_body = self._build_html_email(incident)
            text_body = self._build_text_email(incident)

            response = self.ses_client.send_email(
                Source=self.from_email,
                Destination={
                    "ToAddresses": self.distribution_list,
                },
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                    },
                },
            )

            return {
                "success": True,
                "message_id": response.get("MessageId"),
            }

        except ClientError as e:
            return {"success": False, "error": str(e)}

    def _build_sns_message(self, incident: Incident) -> str:
        """Build SNS message content."""
        message = f"""
INCIDENT ALERT - {incident.priority.value}

Title: {incident.title}
Category: {incident.category.value}
Detected: {incident.detected_at.isoformat()}

Description:
{incident.description[:500]}

Affected Resources:
{chr(10).join(f'- {r}' for r in incident.affected_resources[:5])}
"""

        if incident.jira_ticket_url:
            message += f"\nJira Ticket: {incident.jira_ticket_url}"

        if incident.recommended_actions:
            message += "\n\nRecommended Actions:"
            for i, action in enumerate(incident.recommended_actions[:3], 1):
                message += f"\n{i}. {action}"

        return message

    def _build_html_email(self, incident: Incident) -> str:
        """Build HTML email content."""
        priority_colors = {
            "P1": "#dc3545",
            "P2": "#fd7e14",
            "P3": "#ffc107",
            "P4": "#17a2b8",
            "P5": "#6c757d",
            "P6": "#28a745",
        }
        color = priority_colors.get(incident.priority.value, "#6c757d")

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; }}
        .header {{ background-color: {color}; color: white; padding: 15px; border-radius: 5px; }}
        .content {{ padding: 20px; }}
        .section {{ margin-bottom: 20px; }}
        .label {{ font-weight: bold; color: #333; }}
        .resource {{ background-color: #f8f9fa; padding: 5px 10px; margin: 2px 0; border-radius: 3px; }}
        .action {{ background-color: #e7f3ff; padding: 10px; margin: 5px 0; border-left: 3px solid #0366d6; }}
        .footer {{ color: #6c757d; font-size: 12px; margin-top: 30px; border-top: 1px solid #dee2e6; padding-top: 15px; }}
    </style>
</head>
<body>
    <div class="header">
        <h2 style="margin: 0;">Incident Alert - {incident.priority.value}</h2>
        <p style="margin: 5px 0 0 0;">{incident.title}</p>
    </div>

    <div class="content">
        <div class="section">
            <p><span class="label">Category:</span> {incident.category.value}</p>
            <p><span class="label">Detected:</span> {incident.detected_at.strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            <p><span class="label">Event Count:</span> {incident.event_count}</p>
        </div>

        <div class="section">
            <h3>Description</h3>
            <p>{incident.description[:1000]}</p>
        </div>

        <div class="section">
            <h3>Affected Resources</h3>
"""
        for resource in incident.affected_resources[:10]:
            html += f'            <div class="resource">{resource}</div>\n'

        if incident.recommended_actions:
            html += """
        </div>

        <div class="section">
            <h3>Recommended Actions</h3>
"""
            for action in incident.recommended_actions[:5]:
                html += f'            <div class="action">{action}</div>\n'

        if incident.jira_ticket_url:
            html += f"""
        </div>

        <div class="section">
            <h3>Ticket</h3>
            <p><a href="{incident.jira_ticket_url}">{incident.jira_ticket_key}</a></p>
        </div>
"""

        html += """
        <div class="footer">
            <p>This alert was generated by the Proactive Monitoring Bot.</p>
            <p>Do not reply to this email.</p>
        </div>
    </div>
</body>
</html>
"""
        return html

    def _build_text_email(self, incident: Incident) -> str:
        """Build plain text email content."""
        return self._build_sns_message(incident)

    async def send_resolution_notification(
        self,
        incident: Incident,
        resolution: str
    ) -> Dict[str, Any]:
        """Send notification when incident is resolved."""
        if not self.enabled:
            return {"success": False, "reason": "Notifications disabled"}

        try:
            subject = f"[RESOLVED] {incident.title}"
            message = f"""
INCIDENT RESOLVED - {incident.priority.value}

Title: {incident.title}
Incident ID: {incident.incident_id}

Resolution:
{resolution}

Duration: {self._calculate_duration(incident)}

Jira Ticket: {incident.jira_ticket_url or 'N/A'}
"""

            response = self.sns_client.publish(
                TopicArn=self.sns_topic_arn,
                Subject=subject[:100],
                Message=message,
            )

            return {"success": True, "message_id": response.get("MessageId")}

        except ClientError as e:
            return {"success": False, "error": str(e)}

    def _calculate_duration(self, incident: Incident) -> str:
        """Calculate incident duration."""
        if incident.resolved_at:
            duration = incident.resolved_at - incident.detected_at
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"{hours}h {minutes}m {seconds}s"
        return "Ongoing"

    async def test_connection(self) -> Dict[str, Any]:
        """Test notification service connections."""
        results = {"sns": None, "ses": None}

        # Test SNS
        if self.sns_topic_arn:
            try:
                self.sns_client.get_topic_attributes(TopicArn=self.sns_topic_arn)
                results["sns"] = {"success": True, "topic": self.sns_topic_arn}
            except ClientError as e:
                results["sns"] = {"success": False, "error": str(e)}

        # Test SES
        if self.from_email:
            try:
                self.ses_client.get_identity_verification_attributes(
                    Identities=[self.from_email]
                )
                results["ses"] = {"success": True, "email": self.from_email}
            except ClientError as e:
                results["ses"] = {"success": False, "error": str(e)}

        overall_success = any(
            r and r.get("success") for r in results.values()
        )

        return {
            "success": overall_success,
            "details": results,
        }
