import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, List, Optional
from agent.services.batch_planner import create_batch_draft, get_batch_detail, list_batches
from agent.services.batch_queue import queue_batch, cancel_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batches", tags=["batches"])

class BatchDraftRequest(BaseModel):
    product_id: str
    quantity: int = 1
    platform: str = "TikTok"
    objective: str = "conversion"
    language: str = "Malay"
    engine: str = "VEO_3_1"
    duration: int = 8
    mode: str = "Frames"
    variation_level: str = "medium"
    max_parallel_jobs: int = 1
    interval_min_seconds: int = 45
    interval_max_seconds: int = 120
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 300
    daily_credit_limit: int = 0
    approval_required: bool = True

@router.post("/draft")
async def post_batch_draft(request: BatchDraftRequest):
    result = await create_batch_draft(request.model_dump())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/")
async def get_batches():
    return await list_batches()

@router.get("/{batch_id}")
async def get_batch(batch_id: str):
    result = await get_batch_detail(batch_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.post("/{batch_id}/queue")
async def post_batch_queue(batch_id: str):
    result = await queue_batch(batch_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.post("/{batch_id}/cancel")
async def post_batch_cancel(batch_id: str):
    result = await cancel_batch(batch_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("/{batch_id}/events")
async def get_batch_events(batch_id: str):
    detail = await get_batch_detail(batch_id)
    if "error" in detail:
        raise HTTPException(status_code=404, detail=detail["error"])
    return detail.get("events", [])
