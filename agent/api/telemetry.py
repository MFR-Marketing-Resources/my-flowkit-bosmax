import re
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from agent.db import crud
from agent.models.request import Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])
_ERROR_CODE_RE = re.compile(r"\b(ERR_[A-Z0-9_]+)\b")

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


def _derive_error_code(event: StageEventCreate) -> Optional[str]:
    candidate = str(event.fail_code or "").strip()
    if candidate:
        return candidate
    message = str(event.message or "")
    match = _ERROR_CODE_RE.search(message)
    if match:
        return match.group(1)
    return None


def _should_sync_gfv2psd_terminal_request_status(
    event: StageEventCreate,
    request_row: Optional[dict],
) -> bool:
    if event.source != "extension":
        return False
    if event.stage not in {"FAILED", "COMPLETED"}:
        return False
    if not event.request_id.startswith("gfv2psd-"):
        return False
    if not request_row:
        return False
    return request_row.get("type") == "MANUAL_FLOW_JOB"

@router.get("/summary", response_model=TelemetrySummary)
async def get_summary():
    return await crud.get_telemetry_summary()

@router.get("/requests")
async def get_requests(
    project_id: Optional[str] = None,
    video_id: Optional[str] = None,
    limit: int = 50
):
    return await crud.list_request_telemetry(project_id, video_id, limit)

@router.get("/requests/{request_id}")
async def get_request_detail(request_id: str):
    telemetry = await crud.get_request_telemetry(request_id)
    if not telemetry:
        raise HTTPException(status_code=404, detail="Telemetry not found")
    

@router.get("/summary", response_model=TelemetrySummary)
async def get_summary():
    return await crud.get_telemetry_summary()

@router.get("/requests")
async def get_requests(
    project_id: Optional[str] = None,
    video_id: Optional[str] = None,
    limit: int = 50
):
    return await crud.list_request_telemetry(project_id, video_id, limit)

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

    from agent.db.schema import get_db
    db = await get_db()
    cursor = await db.execute("SELECT id, type FROM request WHERE id = ?", (event.request_id,))
    row = await cursor.fetchone()
    request_row = dict(row) if row else None
    is_batch_variant = False
    if not row:
        is_batch_variant = True
        now = crud._now()
        async with crud._db_lock:
            await db.execute(
                "INSERT INTO request (id, type, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (event.request_id, "TRUE_F2V", "PROCESSING", now, now)
            )
            await db.commit()

    # Update telemetry status based on stage if needed
    status_map = {
        "FLOW_MODE_SELECTED": "FLOW_RUNNING",
        "GENERATION_STARTED": "FLOW_RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
        "ERROR": "FAILED"
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
    if is_batch_variant:
        kw["request_type"] = "TRUE_F2V"
    if event.stage in status_map:
        kw["status"] = status_map[event.stage]
    
    if event.stage in ("FAILED", "ERROR") or event.status == "FAIL":
        kw["status"] = "FAILED"
        kw["failed_at"] = crud._now()
        kw["error_message"] = event.message
        error_code = _derive_error_code(event)
        if error_code:
            kw["error_code"] = error_code
    elif event.stage == "COMPLETED":
        kw["completed_at"] = crud._now()
    
    kw["last_heartbeat_at"] = crud._now()
    
    await crud.upsert_request_telemetry(event.request_id, **kw)
    if _should_sync_gfv2psd_terminal_request_status(event, request_row):
        update_kw = {
            "status": "FAILED" if event.stage == "FAILED" else "COMPLETED",
            "error_message": (
                event.message or _derive_error_code(event)
                if event.stage == "FAILED"
                else None
            ),
        }
        await crud.update_request(event.request_id, **update_kw)
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
