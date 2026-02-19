"""
LangGraph Agent for Proactive Monitoring.
Orchestrates the monitoring workflow using LangGraph.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict, Annotated
from operator import add

from langgraph.graph import StateGraph, END
from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .collectors import CollectorManager, CloudWatchEvent
from .processors import AnomalyDetector, SeverityClassifier
from .integrations import JiraIntegration, NotificationService
from .rag import RAGRetriever
from .models import Incident, IncidentStatus, Priority


class AgentState(TypedDict):
    """State for the monitoring agent workflow."""
    # Input events
    events: List[CloudWatchEvent]

    # Processed data
    analyzed_events: List[Dict[str, Any]]
    incidents: List[Incident]

    # Context from RAG
    runbooks: List[Dict[str, Any]]
    similar_incidents: List[Dict[str, Any]]

    # Results
    tickets_created: Annotated[List[Dict[str, Any]], add]
    notifications_sent: Annotated[List[Dict[str, Any]], add]
    incidents_stored: Annotated[List[str], add]

    # Workflow state
    error: Optional[str]
    current_step: str


class MonitoringAgent:
    """
    Main monitoring agent using LangGraph for workflow orchestration.

    Workflow:
    1. Collect events from CloudWatch
    2. Retrieve relevant context (runbooks, history)
    3. Detect anomalies using AI
    4. Classify incidents by severity (P1-P6)
    5. Create Jira tickets
    6. Send notifications (for P1-P3, summary for P4-P6)
    7. Store for learning
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the monitoring agent.

        Args:
            config: Configuration for all components
        """
        self.config = config
        self.region = config.get("region", "us-east-1")

        # Initialize components
        self.collector_manager = CollectorManager(config)
        self.anomaly_detector = AnomalyDetector(config)
        self.classifier = SeverityClassifier(config)
        self.jira = JiraIntegration(config.get("jira", {}))
        self.notifications = NotificationService(config.get("notifications", {}))
        self.rag = RAGRetriever(config.get("rag", {}))

        # Initialize LLM for analysis
        self.llm = ChatBedrock(
            model_id=config.get("model_id", "anthropic.claude-3-sonnet-20240229-v1:0"),
            region_name=self.region,
        )

        # Build workflow graph
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("collect", self._collect_node)
        workflow.add_node("retrieve_context", self._retrieve_context_node)
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("create_tickets", self._create_tickets_node)
        workflow.add_node("notify", self._notify_node)
        workflow.add_node("store", self._store_node)

        # Add edges
        workflow.set_entry_point("collect")
        workflow.add_edge("collect", "retrieve_context")
        workflow.add_edge("retrieve_context", "analyze")
        workflow.add_edge("analyze", "classify")
        workflow.add_edge("classify", "create_tickets")
        workflow.add_edge("create_tickets", "notify")
        workflow.add_edge("notify", "store")
        workflow.add_edge("store", END)

        return workflow.compile()

    async def _collect_node(self, state: AgentState) -> AgentState:
        """Collect events from CloudWatch."""
        state["current_step"] = "collect"

        try:
            events = await self.collector_manager.collect_all()
            state["events"] = events
            print(f"Collected {len(events)} events")
        except Exception as e:
            state["error"] = f"Collection error: {e}"
            state["events"] = []

        return state

    async def _retrieve_context_node(self, state: AgentState) -> AgentState:
        """Retrieve relevant runbooks and case history."""
        state["current_step"] = "retrieve_context"

        if not state["events"]:
            state["runbooks"] = []
            state["similar_incidents"] = []
            return state

        try:
            # Build query from events
            event_descriptions = " ".join(
                e.description[:200] for e in state["events"][:5]
            )

            # Get runbooks
            runbooks = await self.rag.search_runbooks(event_descriptions)
            state["runbooks"] = runbooks

            # Get similar incidents
            similar = await self.rag.search_similar_incidents(event_descriptions)
            state["similar_incidents"] = similar

            print(f"Retrieved {len(runbooks)} runbooks, {len(similar)} similar incidents")

        except Exception as e:
            print(f"Context retrieval error: {e}")
            state["runbooks"] = []
            state["similar_incidents"] = []

        return state

    async def _analyze_node(self, state: AgentState) -> AgentState:
        """Analyze events for anomalies."""
        state["current_step"] = "analyze"

        if not state["events"]:
            state["analyzed_events"] = []
            return state

        try:
            context = {
                "runbooks": state.get("runbooks", []),
                "similar_incidents": state.get("similar_incidents", []),
            }

            analyzed = await self.anomaly_detector.analyze_events(
                state["events"],
                context=context
            )
            state["analyzed_events"] = analyzed

            anomaly_count = sum(1 for a in analyzed if a.get("is_anomaly", False))
            print(f"Analyzed {len(analyzed)} events, {anomaly_count} anomalies detected")

        except Exception as e:
            print(f"Analysis error: {e}")
            state["analyzed_events"] = []

        return state

    async def _classify_node(self, state: AgentState) -> AgentState:
        """Classify incidents by severity."""
        state["current_step"] = "classify"

        if not state["analyzed_events"]:
            state["incidents"] = []
            return state

        try:
            context = {
                "runbooks": state.get("runbooks", []),
                "similar_incidents": state.get("similar_incidents", []),
            }

            incidents = await self.classifier.classify(
                state["analyzed_events"],
                context=context
            )
            state["incidents"] = incidents

            # Summary by priority
            priority_counts = {}
            for inc in incidents:
                p = inc.priority.value
                priority_counts[p] = priority_counts.get(p, 0) + 1

            print(f"Classified {len(incidents)} incidents: {priority_counts}")

        except Exception as e:
            print(f"Classification error: {e}")
            state["incidents"] = []

        return state

    async def _create_tickets_node(self, state: AgentState) -> AgentState:
        """Create Jira tickets for incidents."""
        state["current_step"] = "create_tickets"
        state["tickets_created"] = []

        for incident in state.get("incidents", []):
            try:
                result = await self.jira.create_ticket(incident)
                if result:
                    state["tickets_created"].append({
                        "incident_id": incident.incident_id,
                        "ticket_key": result.get("key"),
                        "auto_closed": result.get("auto_closed", False),
                    })
                    print(f"Created ticket {result.get('key')} for incident {incident.incident_id}")
            except Exception as e:
                print(f"Ticket creation error: {e}")

        return state

    async def _notify_node(self, state: AgentState) -> AgentState:
        """Send notifications for incidents."""
        state["current_step"] = "notify"
        state["notifications_sent"] = []

        for incident in state.get("incidents", []):
            try:
                result = await self.notifications.notify(incident)
                if result.get("success") or result.get("sns") or result.get("ses"):
                    state["notifications_sent"].append({
                        "incident_id": incident.incident_id,
                        "priority": incident.priority.value,
                        "result": result,
                    })
            except Exception as e:
                print(f"Notification error: {e}")

        print(f"Sent {len(state['notifications_sent'])} notifications")
        return state

    async def _store_node(self, state: AgentState) -> AgentState:
        """Store incidents for learning."""
        state["current_step"] = "store"
        state["incidents_stored"] = []

        for incident in state.get("incidents", []):
            try:
                # Index incident for future learning
                success = await self.rag.index_incident(incident.to_dict())
                if success:
                    state["incidents_stored"].append(incident.incident_id)
            except Exception as e:
                print(f"Storage error: {e}")

        print(f"Stored {len(state['incidents_stored'])} incidents for learning")
        return state

    async def run(self) -> Dict[str, Any]:
        """
        Run the monitoring workflow.

        Returns:
            Workflow results including incidents, tickets, notifications
        """
        initial_state: AgentState = {
            "events": [],
            "analyzed_events": [],
            "incidents": [],
            "runbooks": [],
            "similar_incidents": [],
            "tickets_created": [],
            "notifications_sent": [],
            "incidents_stored": [],
            "error": None,
            "current_step": "init",
        }

        try:
            final_state = await self.workflow.ainvoke(initial_state)

            return {
                "success": True,
                "events_collected": len(final_state.get("events", [])),
                "incidents_created": len(final_state.get("incidents", [])),
                "tickets_created": final_state.get("tickets_created", []),
                "notifications_sent": len(final_state.get("notifications_sent", [])),
                "incidents_stored": len(final_state.get("incidents_stored", [])),
                "incidents": [i.to_dict() for i in final_state.get("incidents", [])],
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    async def run_continuous(self, interval: int = 60):
        """
        Run the monitoring workflow continuously.

        Args:
            interval: Collection interval in seconds
        """
        print(f"Starting continuous monitoring (interval: {interval}s)")

        while True:
            try:
                result = await self.run()
                print(f"Cycle complete: {result.get('incidents_created', 0)} incidents")
            except Exception as e:
                print(f"Cycle error: {e}")

            await asyncio.sleep(interval)

    async def test_connections(self) -> Dict[str, Any]:
        """Test all component connections."""
        results = {}

        # Test collectors
        results["collectors"] = await self.collector_manager.test_all_connections()

        # Test anomaly detector (Bedrock)
        results["anomaly_detector"] = await self.anomaly_detector.test_connection()

        # Test Jira
        results["jira"] = await self.jira.test_connection()

        # Test notifications
        results["notifications"] = await self.notifications.test_connection()

        # Test RAG
        results["rag"] = await self.rag.test_connection()

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get agent status."""
        return {
            "collectors": self.collector_manager.list_collectors(),
            "region": self.region,
            "model": self.config.get("model_id"),
        }


# Singleton instance
_agent: Optional[MonitoringAgent] = None


def get_agent(config: Optional[Dict[str, Any]] = None) -> MonitoringAgent:
    """Get or create the monitoring agent singleton."""
    global _agent
    if _agent is None:
        if config is None:
            raise ValueError("Configuration required for first initialization")
        _agent = MonitoringAgent(config)
    return _agent
