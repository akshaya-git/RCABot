"""
FastAPI Application for Proactive Monitoring Agent.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_config
from agent import MonitoringAgent, get_agent


# Request/Response Models
class RunbookRequest(BaseModel):
    title: str
    content: str
    category: str = "general"
    keywords: list = []
    steps: list = []


class IncidentResolveRequest(BaseModel):
    resolution: str


# Application Setup
config = get_config()
agent: Optional[MonitoringAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    global agent

    print("Starting Proactive Monitoring Agent...")
    print(f"Region: {config.region}")
    print(f"Model: {config.model_id}")

    try:
        agent = get_agent(config.to_dict())
        print("Agent initialized")

        # Ensure RAG indices exist
        await agent.rag.ensure_indices()
        print("RAG indices ready")

    except Exception as e:
        print(f"Initialization warning: {e}")

    yield

    print("Shutting down...")


app = FastAPI(
    title="Proactive Monitoring Agent",
    description="AI-powered CloudWatch monitoring with Jira integration",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health Endpoints
@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "region": config.region,
        "model": config.model_id,
    }


@app.get("/ready")
async def ready():
    """Readiness check endpoint."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")
    return {"status": "ready"}


@app.get("/status")
async def status():
    """Get agent status."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    return agent.get_status()


# Monitoring Endpoints
@app.post("/collect")
async def trigger_collection(background_tasks: BackgroundTasks):
    """Trigger a manual collection cycle."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    result = await agent.run()
    return result


@app.get("/incidents")
async def list_incidents():
    """List recent incidents."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    # Search for recent incidents in RAG store
    incidents = await agent.rag.search_similar_incidents("", max_results=50)
    return {"incidents": incidents}


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    """Get incident details."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    # Search for specific incident
    incidents = await agent.rag.search_similar_incidents(incident_id, max_results=1)
    if not incidents:
        raise HTTPException(404, "Incident not found")

    return incidents[0]


@app.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str, request: IncidentResolveRequest):
    """Resolve an incident."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    # Update incident in store
    success = await agent.rag.index_incident({
        "incident_id": incident_id,
        "resolution": request.resolution,
        "status": "resolved",
    })

    return {"success": success, "incident_id": incident_id}


# Runbook Endpoints
@app.post("/runbooks")
async def index_runbook(runbook: RunbookRequest):
    """Index a new runbook."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    success = await agent.rag.index_runbook(runbook.dict())
    return {"success": success}


@app.get("/runbooks/search")
async def search_runbooks(query: str, category: Optional[str] = None):
    """Search runbooks."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.rag.search_runbooks(query, category=category)
    return {"runbooks": results}


# Test Endpoints
@app.get("/test/connections")
async def test_connections():
    """Test all component connections."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.test_connections()
    return results


@app.get("/test/collectors")
async def test_collectors():
    """Test CloudWatch collectors."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.collector_manager.test_all_connections()
    return results


@app.get("/test/jira")
async def test_jira():
    """Test Jira connection."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    result = await agent.jira.test_connection()
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
