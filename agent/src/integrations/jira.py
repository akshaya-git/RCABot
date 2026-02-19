"""
Jira Integration for incident ticket management.
Handles ticket creation, updates, and auto-closure based on priority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from ..models.events import Incident, IncidentStatus, Priority


class JiraIntegration:
    """
    Manages Jira tickets for incidents.

    Features:
    - Create tickets for P1-P3 incidents (keep open)
    - Create, log, and close tickets for P4-P6 incidents
    - Update tickets with analysis and resolution
    - Link related tickets
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Jira integration.

        Args:
            config: Configuration including:
                - url: Jira base URL
                - email: Service account email
                - api_token: API token
                - project: Default project key
                - issue_type: Default issue type
        """
        self.base_url = config.get("url", "").rstrip("/")
        self.email = config.get("email", "")
        self.api_token = config.get("api_token", "")
        self.project = config.get("project", "OPS")
        self.issue_type = config.get("issue_type", "Incident")
        self.enabled = config.get("enabled", True)

        # Priority mapping to Jira priority
        self.priority_mapping = config.get("priority_mapping", {
            "P1": "Highest",
            "P2": "High",
            "P3": "Medium",
            "P4": "Low",
            "P5": "Low",
            "P6": "Lowest",
        })

        # Labels for auto-created tickets
        self.labels = config.get("labels", ["monitoring-bot", "automated"])

        # Transitions for closing tickets
        self.close_transition = config.get("close_transition", "Done")

    @property
    def _auth(self) -> tuple:
        """Get authentication tuple."""
        return (self.email, self.api_token)

    @property
    def _headers(self) -> Dict[str, str]:
        """Get request headers."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def create_ticket(self, incident: Incident) -> Optional[Dict[str, Any]]:
        """
        Create a Jira ticket for an incident.

        Args:
            incident: Incident to create ticket for

        Returns:
            Dict with ticket key and URL, or None on failure
        """
        if not self.enabled:
            return None

        # Build ticket fields
        fields = {
            "project": {"key": self.project},
            "summary": self._build_summary(incident),
            "description": self._build_description(incident),
            "issuetype": {"name": self.issue_type},
            "priority": {"name": self.priority_mapping.get(incident.priority.value, "Medium")},
            "labels": self.labels + [incident.priority.value, incident.category.value],
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/rest/api/2/issue",
                    auth=self._auth,
                    headers=self._headers,
                    json={"fields": fields},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                ticket_key = data.get("key", "")
                ticket_url = f"{self.base_url}/browse/{ticket_key}"

                # Update incident with ticket info
                incident.set_ticket(ticket_key, ticket_url)

                # Auto-close if low priority
                if incident.should_auto_close():
                    await self._add_resolution_comment(ticket_key, incident)
                    await self._close_ticket(ticket_key)

                return {
                    "key": ticket_key,
                    "url": ticket_url,
                    "auto_closed": incident.should_auto_close(),
                }

        except httpx.HTTPError as e:
            print(f"Error creating Jira ticket: {e}")
            return None

    def _build_summary(self, incident: Incident) -> str:
        """Build ticket summary from incident."""
        return f"[{incident.priority.value}] {incident.title}"

    def _build_description(self, incident: Incident) -> str:
        """Build ticket description from incident."""
        description = f"""h2. Incident Details

*Incident ID:* {incident.incident_id}
*Priority:* {incident.priority.value}
*Category:* {incident.category.value}
*Status:* {incident.status.value}
*Detected:* {incident.detected_at.isoformat()}

h2. Description

{incident.description}

h2. Affected Resources

"""
        for resource in incident.affected_resources[:10]:
            description += f"* {resource}\n"

        if incident.anomaly_score:
            description += f"""
h2. Anomaly Analysis

*Score:* {incident.anomaly_score.score:.2f}
*Confidence:* {incident.anomaly_score.confidence:.2f}
*Reasoning:* {incident.anomaly_score.reasoning}

*Contributing Factors:*
"""
            for factor in incident.anomaly_score.factors:
                description += f"* {factor}\n"

        if incident.root_cause_analysis:
            description += f"""
h2. Root Cause Analysis

{incident.root_cause_analysis}
"""

        if incident.recommended_actions:
            description += """
h2. Recommended Actions

"""
            for i, action in enumerate(incident.recommended_actions, 1):
                description += f"{i}. {action}\n"

        description += f"""
----
_This ticket was automatically created by the Proactive Monitoring Bot._
_Event Count: {incident.event_count}_
"""

        return description

    async def _add_resolution_comment(self, ticket_key: str, incident: Incident):
        """Add resolution comment for auto-closed tickets."""
        comment = f"""This incident has been automatically logged and closed due to its low priority ({incident.priority.value}).

*Summary:*
- Anomaly Score: {incident.anomaly_score.score if incident.anomaly_score else 'N/A'}
- Event Count: {incident.event_count}
- Category: {incident.category.value}

*Reason for Auto-Close:*
{self._get_auto_close_reason(incident)}

_If this requires attention, please reopen this ticket and escalate appropriately._
"""
        await self.add_comment(ticket_key, comment)

    def _get_auto_close_reason(self, incident: Incident) -> str:
        """Get reason for auto-closing based on priority."""
        reasons = {
            Priority.P4: "Low impact incident - minimal effect on operations",
            Priority.P5: "Informational alert - logged for tracking purposes",
            Priority.P6: "Trivial issue - no functional impact detected",
        }
        return reasons.get(incident.priority, "Low priority incident")

    async def _close_ticket(self, ticket_key: str) -> bool:
        """Close a ticket using transition."""
        try:
            async with httpx.AsyncClient() as client:
                # Get available transitions
                response = await client.get(
                    f"{self.base_url}/rest/api/2/issue/{ticket_key}/transitions",
                    auth=self._auth,
                    headers=self._headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                transitions = response.json().get("transitions", [])

                # Find close transition
                transition_id = None
                for t in transitions:
                    if t.get("name", "").lower() in ["done", "closed", "resolved", "close"]:
                        transition_id = t["id"]
                        break

                if transition_id:
                    response = await client.post(
                        f"{self.base_url}/rest/api/2/issue/{ticket_key}/transitions",
                        auth=self._auth,
                        headers=self._headers,
                        json={
                            "transition": {"id": transition_id},
                            "fields": {
                                "resolution": {"name": "Done"}
                            }
                        },
                        timeout=30.0,
                    )
                    return response.status_code < 400

        except httpx.HTTPError as e:
            print(f"Error closing ticket {ticket_key}: {e}")

        return False

    async def add_comment(self, ticket_key: str, comment: str) -> bool:
        """Add a comment to a ticket."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/rest/api/2/issue/{ticket_key}/comment",
                    auth=self._auth,
                    headers=self._headers,
                    json={"body": comment},
                    timeout=30.0,
                )
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def update_ticket(
        self,
        ticket_key: str,
        fields: Optional[Dict[str, Any]] = None,
        comment: Optional[str] = None
    ) -> bool:
        """Update a ticket's fields and/or add a comment."""
        try:
            async with httpx.AsyncClient() as client:
                if fields:
                    response = await client.put(
                        f"{self.base_url}/rest/api/2/issue/{ticket_key}",
                        auth=self._auth,
                        headers=self._headers,
                        json={"fields": fields},
                        timeout=30.0,
                    )
                    if response.status_code >= 400:
                        return False

                if comment:
                    await self.add_comment(ticket_key, comment)

                return True

        except httpx.HTTPError:
            return False

    async def get_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        """Get ticket details."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/rest/api/2/issue/{ticket_key}",
                    auth=self._auth,
                    headers=self._headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError:
            return None

    async def search_tickets(self, jql: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Search tickets using JQL."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/rest/api/2/search",
                    auth=self._auth,
                    headers=self._headers,
                    json={
                        "jql": jql,
                        "maxResults": max_results,
                        "fields": ["summary", "status", "priority", "created"],
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json().get("issues", [])
        except httpx.HTTPError:
            return []

    async def find_existing_ticket(self, incident_id: str) -> Optional[str]:
        """Find existing ticket for an incident."""
        jql = f'project = "{self.project}" AND text ~ "{incident_id}" ORDER BY created DESC'
        tickets = await self.search_tickets(jql, max_results=1)
        return tickets[0]["key"] if tickets else None

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to Jira."""
        if not self.enabled:
            return {"success": False, "error": "Jira integration disabled"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/rest/api/2/myself",
                    auth=self._auth,
                    headers=self._headers,
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

                return {
                    "success": True,
                    "message": f"Connected as {data.get('displayName', 'Unknown')}",
                    "user": data.get("displayName"),
                    "project": self.project,
                }
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
