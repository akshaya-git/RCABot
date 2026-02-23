"""
ServiceNow Integration for incident ticket management.
Handles ticket creation, updates, and auto-closure based on priority.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from ..models.events import Incident, IncidentStatus, Priority


class ServiceNowIntegration:
    """
    Manages ServiceNow incidents for monitoring alerts.

    Features:
    - Create incidents for P1-P3 alerts (keep open)
    - Create, log, and close incidents for P4-P6 alerts
    - Update incidents with analysis and resolution
    - Link related incidents using correlation
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize ServiceNow integration.

        Args:
            config: Configuration including:
                - instance: ServiceNow instance name (e.g., 'dev12345')
                - username: Service account username
                - password: Service account password
                - assignment_group: Default assignment group
                - caller_id: Caller sys_id for incidents
        """
        self.instance = config.get("instance", "")
        self.base_url = f"https://{self.instance}.service-now.com"
        self.username = config.get("username", "")
        self.password = config.get("password", "")
        self.assignment_group = config.get("assignment_group", "")
        self.caller_id = config.get("caller_id", "")
        self.enabled = config.get("enabled", True)

        # Priority mapping to ServiceNow impact/urgency
        # ServiceNow uses Impact (1-3) and Urgency (1-3) to determine Priority
        self.priority_mapping = config.get("priority_mapping", {
            "P1": {"impact": "1", "urgency": "1"},  # Critical
            "P2": {"impact": "1", "urgency": "2"},  # High
            "P3": {"impact": "2", "urgency": "2"},  # Medium
            "P4": {"impact": "2", "urgency": "3"},  # Low
            "P5": {"impact": "3", "urgency": "3"},  # Very Low
            "P6": {"impact": "3", "urgency": "3"},  # Trivial
        })

        # Category mapping
        self.category_mapping = config.get("category_mapping", {
            "performance": "Software",
            "availability": "Hardware",
            "error": "Software",
            "security": "Security",
            "capacity": "Hardware",
            "configuration": "Software",
        })

        # Close state for auto-closed incidents
        self.close_state = config.get("close_state", "7")  # 7 = Closed in ServiceNow

    @property
    def _auth(self) -> tuple:
        """Get authentication tuple."""
        return (self.username, self.password)

    @property
    def _headers(self) -> Dict[str, str]:
        """Get request headers."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def create_ticket(self, incident: Incident) -> Optional[Dict[str, Any]]:
        """
        Create a ServiceNow incident for a monitoring alert.

        Args:
            incident: Incident to create ticket for

        Returns:
            Dict with incident number and URL, or None on failure
        """
        if not self.enabled:
            return None

        # Build incident payload
        payload = {
            "short_description": self._build_short_description(incident),
            "description": self._build_description(incident),
            "impact": self.priority_mapping.get(incident.priority.value, {}).get("impact", "2"),
            "urgency": self.priority_mapping.get(incident.priority.value, {}).get("urgency", "2"),
            "category": self.category_mapping.get(incident.category.value, "Software"),
            "subcategory": "Performance",
            "assignment_group": self.assignment_group,
            "caller_id": self.caller_id,
            "correlation_id": incident.incident_id,
            "correlation_display": f"Monitoring Bot: {incident.incident_id}",
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/now/table/incident",
                    auth=self._auth,
                    headers=self._headers,
                    json=payload,
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json().get("result", {})

                incident_number = data.get("number", "")
                sys_id = data.get("sys_id", "")
                incident_url = f"{self.base_url}/nav_to.do?uri=incident.do?sys_id={sys_id}"

                # Update incident with ticket info
                incident.set_ticket(incident_number, incident_url)

                # Auto-close if low priority
                if incident.should_auto_close():
                    await self._add_work_note(sys_id, self._get_auto_close_work_note(incident))
                    await self._close_incident(sys_id, incident)

                return {
                    "key": incident_number,
                    "sys_id": sys_id,
                    "url": incident_url,
                    "auto_closed": incident.should_auto_close(),
                }

        except httpx.HTTPError as e:
            print(f"Error creating ServiceNow incident: {e}")
            return None

    def _build_short_description(self, incident: Incident) -> str:
        """Build incident short description."""
        return f"[{incident.priority.value}] {incident.title}"

    def _build_description(self, incident: Incident) -> str:
        """Build incident description from monitoring alert."""
        description = f"""INCIDENT DETAILS
================
Incident ID: {incident.incident_id}
Priority: {incident.priority.value}
Category: {incident.category.value}
Status: {incident.status.value}
Detected: {incident.detected_at.isoformat()}

DESCRIPTION
===========
{incident.description}

AFFECTED RESOURCES
==================
"""
        for resource in incident.affected_resources[:10]:
            description += f"- {resource}\n"

        if incident.anomaly_score:
            description += f"""
ANOMALY ANALYSIS
================
Score: {incident.anomaly_score.score:.2f}
Confidence: {incident.anomaly_score.confidence:.2f}
Reasoning: {incident.anomaly_score.reasoning}

Contributing Factors:
"""
            for factor in incident.anomaly_score.factors:
                description += f"- {factor}\n"

        if incident.root_cause_analysis:
            description += f"""
ROOT CAUSE ANALYSIS
===================
{incident.root_cause_analysis}
"""

        if incident.recommended_actions:
            description += """
RECOMMENDED ACTIONS
===================
"""
            for i, action in enumerate(incident.recommended_actions, 1):
                description += f"{i}. {action}\n"

        description += f"""
---
This incident was automatically created by the Proactive Monitoring Bot.
Event Count: {incident.event_count}
"""

        return description

    def _get_auto_close_work_note(self, incident: Incident) -> str:
        """Get work note for auto-closed incidents."""
        reasons = {
            Priority.P4: "Low impact incident - minimal effect on operations",
            Priority.P5: "Informational alert - logged for tracking purposes",
            Priority.P6: "Trivial issue - no functional impact detected",
        }
        reason = reasons.get(incident.priority, "Low priority incident")

        return f"""AUTO-CLOSE NOTIFICATION
=======================
This incident has been automatically logged and closed due to its low priority ({incident.priority.value}).

Summary:
- Anomaly Score: {incident.anomaly_score.score if incident.anomaly_score else 'N/A'}
- Event Count: {incident.event_count}
- Category: {incident.category.value}

Reason for Auto-Close:
{reason}

If this requires attention, please reopen this incident and escalate appropriately.
"""

    async def _add_work_note(self, sys_id: str, note: str) -> bool:
        """Add a work note to an incident."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{self.base_url}/api/now/table/incident/{sys_id}",
                    auth=self._auth,
                    headers=self._headers,
                    json={"work_notes": note},
                    timeout=30.0,
                )
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def _close_incident(self, sys_id: str, incident: Incident) -> bool:
        """Close an incident."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{self.base_url}/api/now/table/incident/{sys_id}",
                    auth=self._auth,
                    headers=self._headers,
                    json={
                        "state": self.close_state,
                        "close_code": "Closed/Resolved by Caller",
                        "close_notes": f"Auto-closed by Monitoring Bot. Priority: {incident.priority.value}",
                    },
                    timeout=30.0,
                )
                return response.status_code < 400
        except httpx.HTTPError as e:
            print(f"Error closing incident {sys_id}: {e}")
            return False

    async def add_comment(self, ticket_key: str, comment: str) -> bool:
        """Add a comment (additional_comments) to an incident."""
        # First, find the sys_id by incident number
        sys_id = await self._get_sys_id_by_number(ticket_key)
        if not sys_id:
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"{self.base_url}/api/now/table/incident/{sys_id}",
                    auth=self._auth,
                    headers=self._headers,
                    json={"comments": comment},
                    timeout=30.0,
                )
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def _get_sys_id_by_number(self, incident_number: str) -> Optional[str]:
        """Get sys_id by incident number."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/now/table/incident",
                    auth=self._auth,
                    headers=self._headers,
                    params={"sysparm_query": f"number={incident_number}", "sysparm_limit": "1"},
                    timeout=30.0,
                )
                response.raise_for_status()
                results = response.json().get("result", [])
                return results[0].get("sys_id") if results else None
        except httpx.HTTPError:
            return None

    async def update_ticket(
        self,
        ticket_key: str,
        fields: Optional[Dict[str, Any]] = None,
        comment: Optional[str] = None
    ) -> bool:
        """Update an incident's fields and/or add a comment."""
        sys_id = await self._get_sys_id_by_number(ticket_key)
        if not sys_id:
            return False

        try:
            async with httpx.AsyncClient() as client:
                update_payload = {}

                if fields:
                    update_payload.update(fields)

                if comment:
                    update_payload["work_notes"] = comment

                if update_payload:
                    response = await client.patch(
                        f"{self.base_url}/api/now/table/incident/{sys_id}",
                        auth=self._auth,
                        headers=self._headers,
                        json=update_payload,
                        timeout=30.0,
                    )
                    return response.status_code < 400

                return True

        except httpx.HTTPError:
            return False

    async def get_ticket(self, ticket_key: str) -> Optional[Dict[str, Any]]:
        """Get incident details by number."""
        sys_id = await self._get_sys_id_by_number(ticket_key)
        if not sys_id:
            return None

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/now/table/incident/{sys_id}",
                    auth=self._auth,
                    headers=self._headers,
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json().get("result")
        except httpx.HTTPError:
            return None

    async def search_tickets(self, query: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Search incidents using encoded query."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/now/table/incident",
                    auth=self._auth,
                    headers=self._headers,
                    params={
                        "sysparm_query": query,
                        "sysparm_limit": str(max_results),
                        "sysparm_fields": "number,short_description,state,priority,sys_created_on,correlation_id",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json().get("result", [])
        except httpx.HTTPError:
            return []

    async def find_existing_ticket(self, incident_id: str) -> Optional[str]:
        """Find existing incident for a monitoring alert using correlation_id."""
        query = f"correlation_id={incident_id}^ORDERBYDESCsys_created_on"
        incidents = await self.search_tickets(query, max_results=1)
        return incidents[0].get("number") if incidents else None

    async def test_connection(self) -> Dict[str, Any]:
        """Test connection to ServiceNow."""
        if not self.enabled:
            return {"success": False, "error": "ServiceNow integration disabled"}

        if not self.instance:
            return {"success": False, "error": "ServiceNow instance not configured"}

        try:
            async with httpx.AsyncClient() as client:
                # Test by getting the logged-in user info
                response = await client.get(
                    f"{self.base_url}/api/now/table/sys_user",
                    auth=self._auth,
                    headers=self._headers,
                    params={"sysparm_query": f"user_name={self.username}", "sysparm_limit": "1"},
                    timeout=10.0,
                )
                response.raise_for_status()
                results = response.json().get("result", [])

                if results:
                    user = results[0]
                    return {
                        "success": True,
                        "message": f"Connected as {user.get('name', user.get('user_name', 'Unknown'))}",
                        "user": user.get("name", user.get("user_name")),
                        "instance": self.instance,
                        "assignment_group": self.assignment_group,
                    }
                else:
                    return {"success": False, "error": "User not found"}

        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}
