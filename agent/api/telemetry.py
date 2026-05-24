from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from agent.db import crud
from agent.models.request import Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

class TelemetrySummary(BaseModel):
    total_today: int
    queued: int
    processing: int
    waiting_flow: int
    flow_running: int
    completed: int
    failed: int
    last_job_status: str
    last_stage: str
    last_error: Optional[str] = None
    idle_seconds: float

class StageEventCreate(BaseModel):
    request_id: str
    timestamp: str
    git_sha: str
    background_build_id: str
    content_build_id: str
    stage: str
    checkpoint: str
    status: str
    message: Optional[str] = None
    source: str
    runtime_ready: bool = False
    build_match: bool = False
    selector_used: Optional[str] = None
    evidence_pointer: Optional[str] = None
    fail_code: Optional[str] = None
    first_fail_stage: Optional[str] = None

@router.get("/summary", response_model=TelemetrySummary)
async def get_summary():
    return await crud.get_telemetry_summary()

@router.get("/requests")
async def get_requests(
    project_id: Optional[str] = None,
    video_id: Optional[str] = None,
    request_type: Optional[str] = None,
    mode: Optional[str] = None,
    limit: int = 50
):
    return await crud.list_request_telemetry(
        project_id,
        video_id,
        limit,
        request_type=request_type,
        mode=mode,
    )

@router.get("/requests/{request_id}")
async def get_request_detail(request_id: str):
    telemetry = await crud.get_request_telemetry(request_id)
    if not telemetry:
        raise HTTPException(status_code=404, detail="Telemetry not found")
    
    stages = await crud.get_stage_history(request_id)
    return {
        "telemetry": telemetry,
        "stages": stages
    }

@router.post("/stage")
async def add_stage(event: StageEventCreate):
    if event.request_id.strip().upper() == "N/A":
        raise HTTPException(status_code=422, detail="REQUEST_ID_NA_REJECTED")
    if event.background_build_id.strip().lower() == "legacy" or event.content_build_id.strip().lower() == "legacy":
        raise HTTPException(status_code=422, detail="LEGACY_BUILD_REJECTED")

    # Update telemetry status based on stage if needed
    status_map = {
        "FLOW_MODE_SELECTED": "FLOW_RUNNING",
        "GENERATION_STARTED": "FLOW_RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED"
    }
    
    kw = {
        "git_sha": event.git_sha,
        "background_build_id": event.background_build_id,
        "content_build_id": event.content_build_id,
        "last_checkpoint": event.checkpoint,
        "runtime_ready": 1 if event.runtime_ready else 0,
        "build_match": 1 if event.build_match else 0,
        "google_flow_stage": event.stage,
        "extension_stage": event.stage,
    }
    if event.stage in status_map:
        kw["status"] = status_map[event.stage]
    
    if event.stage == "FAILED":
        kw["failed_at"] = crud._now()
        kw["error_message"] = event.message
    elif event.stage == "COMPLETED":
        kw["completed_at"] = crud._now()
    
    kw["last_heartbeat_at"] = crud._now()
    
    await crud.upsert_request_telemetry(event.request_id, **kw)
    return await crud.add_stage_event(
        event.request_id, 
        event.stage, 
        event.status, 
        event.message, 
        event.source,
        checkpoint=event.checkpoint,
        git_sha=event.git_sha,
        background_build_id=event.background_build_id,
        content_build_id=event.content_build_id,
        runtime_ready=1 if event.runtime_ready else 0,
        build_match=1 if event.build_match else 0,
        selector_used=event.selector_used,
        evidence_pointer=event.evidence_pointer,
        fail_code=event.fail_code,
        first_fail_stage=event.first_fail_stage,
    )

@router.post("/self-test")
async def telemetry_self_test():
    test_id = f"test-{crud._uuid()[:8]}"
    
    # Satisfy FK constraint by inserting into 'request' table first
    from agent.db.schema import get_db
    db = await get_db()
    now = crud._now()
    async with crud._db_lock:
        await db.execute(
            "INSERT INTO request (id, type, status, created_at, updated_at) VALUES (?,?,?,?,?)",
            (test_id, "TELEMETRY_SELF_TEST", "COMPLETED", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        test_id,
        request_type="TELEMETRY_SELF_TEST",
        status="COMPLETED",
        google_flow_stage="SELF_TEST_PASSED",
        completed_at=crud._now()
    )
    await crud.add_stage_event(
        test_id,
        "TELEMETRY_SELF_TEST",
        "PASS",
        "Harmless telemetry self-test event generated.",
        "backend"
    )
    return {
        "ok": True,
        "stage": "TELEMETRY_SELF_TEST",
        "request_logged": True,
        "summary_updated": True,
        "test_id": test_id
    }
