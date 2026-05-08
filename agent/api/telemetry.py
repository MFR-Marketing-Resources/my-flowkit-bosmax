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
    last_error: str
    idle_seconds: float

class StageEventCreate(BaseModel):
    request_id: str
    stage: str
    status: str
    message: Optional[str] = None
    source: str

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
    # Update telemetry status based on stage if needed
    status_map = {
        "FLOW_MODE_SELECTED": "FLOW_RUNNING",
        "GENERATION_STARTED": "FLOW_RUNNING",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED"
    }
    
    kw = {"google_flow_stage": event.stage, "extension_stage": event.stage}
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
        event.source
    )
