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


class RawRunbookRequest(BaseModel):
    """Request for uploading raw/unstructured runbook content."""
    content: str
    filename: Optional[str] = None


class RawCaseHistoryRequest(BaseModel):
    """Request for uploading raw/unstructured case history content."""
    content: str
    incident_id: Optional[str] = None


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
    description="AI-powered CloudWatch monitoring with ServiceNow integration",
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


@app.get("/test/servicenow")
async def test_servicenow():
    """Test ServiceNow connection."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    result = await agent.servicenow.test_connection()
    return result


# =============================================================================
# S3 RAG Sync Endpoints
# =============================================================================

@app.get("/s3/status")
async def s3_status():
    """Get S3 RAG sync status."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    status = await agent.s3_sync.get_sync_status()
    return status


@app.get("/s3/runbooks")
async def list_s3_runbooks():
    """List runbooks stored in S3."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    runbooks = await agent.s3_sync.list_s3_runbooks()
    return {"runbooks": runbooks, "count": len(runbooks)}


@app.post("/s3/sync/runbooks")
async def sync_runbooks_from_s3(force: bool = False):
    """
    Sync all runbooks from S3 to OpenSearch.

    Args:
        force: If True, re-index all runbooks regardless of version
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.s3_sync.sync_runbooks_from_s3(force=force)
    return results


@app.post("/s3/sync/case-history")
async def sync_case_history_from_s3():
    """Sync case history from S3 to OpenSearch."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.s3_sync.sync_case_history_from_s3()
    return results


@app.post("/s3/sync/all")
async def bulk_import_from_s3(source_prefix: Optional[str] = None):
    """
    Bulk import all RAG data from S3 to OpenSearch.

    This imports:
    - All runbooks from runbooks/ prefix
    - All case history from case-history/ prefix
    - Any additional data from the specified source_prefix
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    results = await agent.s3_sync.bulk_import(source_prefix=source_prefix)
    return results


@app.post("/s3/runbooks")
async def upload_runbook_to_s3(runbook: RunbookRequest, filename: Optional[str] = None):
    """
    Upload a runbook to S3 and index to OpenSearch.

    This stores the runbook in S3 (source of truth) and indexes it to OpenSearch.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    result = await agent.s3_sync.upload_runbook(runbook.dict(), filename=filename)
    return result


@app.get("/test/s3")
async def test_s3():
    """Test S3 connection."""
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    result = await agent.s3_sync.test_connection()
    return result


# =============================================================================
# Extraction Endpoints (for unstructured data)
# =============================================================================

@app.post("/extract/runbook")
async def extract_runbook(request: RawRunbookRequest):
    """
    Extract structured runbook data from raw/unstructured content.

    Uses LLM to parse unstructured text (markdown, plain text, etc.)
    and extract: title, content, category, keywords, steps.

    The extracted data follows the runbook schema.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    extracted = await agent.s3_sync.extractor.extract_runbook(
        request.content,
        request.filename
    )

    return {
        "success": True,
        "extracted": extracted,
        "extraction_failed": extracted.get("_extraction_failed", False),
    }


@app.post("/extract/runbook/index")
async def extract_and_index_runbook(request: RawRunbookRequest):
    """
    Extract structured data from raw runbook content AND index to OpenSearch.

    Combines extraction + indexing in one step.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    # Extract structured data
    extracted = await agent.s3_sync.extractor.extract_runbook(
        request.content,
        request.filename
    )

    # Index to OpenSearch
    indexed = await agent.rag.index_runbook(extracted)

    return {
        "success": indexed,
        "extracted": extracted,
        "indexed": indexed,
    }


@app.post("/extract/case-history")
async def extract_case_history(request: RawCaseHistoryRequest):
    """
    Extract structured case history from raw incident documentation.

    Uses LLM to parse post-mortems, incident reports, etc.
    and extract: title, description, root_cause, resolution, etc.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    extracted = await agent.s3_sync.extractor.extract_case_history(
        request.content,
        request.incident_id
    )

    return {
        "success": True,
        "extracted": extracted,
        "extraction_failed": extracted.get("_extraction_failed", False),
    }


@app.post("/extract/case-history/index")
async def extract_and_index_case_history(request: RawCaseHistoryRequest):
    """
    Extract structured data from raw case history AND index to OpenSearch.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    # Extract structured data
    extracted = await agent.s3_sync.extractor.extract_case_history(
        request.content,
        request.incident_id
    )

    # Index to OpenSearch
    indexed = await agent.rag.index_incident(extracted)

    return {
        "success": indexed,
        "extracted": extracted,
        "indexed": indexed,
    }


@app.post("/s3/raw/upload")
async def upload_raw_to_s3(request: RawRunbookRequest, doc_type: str = "runbook"):
    """
    Upload raw/unstructured content to S3 raw/ prefix.

    Files in the raw/ prefix are automatically extracted during sync.
    """
    if agent is None:
        raise HTTPException(503, "Agent not initialized")

    if not agent.s3_sync.bucket:
        raise HTTPException(400, "S3 bucket not configured")

    try:
        filename = request.filename or f"raw-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        prefix = agent.s3_sync.raw_prefix if doc_type == "runbook" else f"raw-cases/"
        key = f"{prefix}{filename}"

        agent.s3_sync.s3_client.put_object(
            Bucket=agent.s3_sync.bucket,
            Key=key,
            Body=request.content,
            ContentType="text/plain",
        )

        return {
            "success": True,
            "s3_key": key,
            "s3_uri": f"s3://{agent.s3_sync.bucket}/{key}",
            "message": "File uploaded. Run /s3/sync/runbooks to extract and index.",
        }

    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")


from datetime import datetime

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
