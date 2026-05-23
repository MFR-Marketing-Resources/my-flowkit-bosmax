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


class BatchPatchRequest(BaseModel):
    quantity: int | None = None
    engine: str | None = None
    duration: int | None = None
    mode: str | None = None
    variation_level: str | None = None
    platform: str | None = None
    objective: str | None = None
    language: str | None = None

@router.post("/draft")
async def post_batch_draft(request: BatchDraftRequest):
    result = await create_batch_draft(request.model_dump())
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@router.get("")
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


@router.patch("/{batch_id}")
async def patch_batch(batch_id: str, request: BatchPatchRequest):
    from agent.db import crud
    from agent.db.schema import get_db, _db_lock
    import datetime

    detail = await get_batch_detail(batch_id)
    if "error" in detail:
        raise HTTPException(status_code=404, detail=detail["error"])
    if detail.get("status") not in ("DRAFT", "DRAFT_BLOCKED"):
        raise HTTPException(status_code=409, detail="BATCH_NOT_DRAFT")

    fields: dict = {}
    if request.quantity is not None:
        fields["quantity"] = request.quantity
    if request.engine is not None:
        fields["engine"] = request.engine
    if request.duration is not None:
        fields["duration"] = request.duration
    if request.mode is not None:
        fields["mode"] = request.mode
    if request.variation_level is not None:
        fields["variation_level"] = request.variation_level
    if request.platform is not None:
        fields["platform"] = request.platform
    if request.objective is not None:
        fields["objective"] = request.objective
    if request.language is not None:
        fields["language"] = request.language

    if not fields:
        return detail

    fields["updated_at"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [batch_id]

    db = await get_db()
    async with _db_lock:
        await db.execute(f"UPDATE batch SET {set_clause} WHERE id = ?", values)
        await db.commit()

    return await get_batch_detail(batch_id)


@router.delete("/{batch_id}", status_code=204)
async def delete_batch(batch_id: str):
    from agent.db.schema import get_db, _db_lock

    detail = await get_batch_detail(batch_id)
    if "error" in detail:
        raise HTTPException(status_code=404, detail=detail["error"])

    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM batch WHERE id = ?", (batch_id,))
        await db.commit()
