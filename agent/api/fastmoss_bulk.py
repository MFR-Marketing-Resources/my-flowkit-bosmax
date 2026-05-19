"""
FastMoss Bulk Promotion API — Wave 1.
Mount prefix: /api/fastmoss-bulk

Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue:     #92
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent.services import fastmoss_bulk_promotion_service as _svc

router = APIRouter(prefix="/fastmoss-bulk", tags=["fastmoss-bulk"])


class SyncQueueRequest(BaseModel):
    batch_id: str | None = None


class BulkCreateDraftsRequest(BaseModel):
    reference_ids: list[str]


class BulkApproveDraftsRequest(BaseModel):
    reference_ids: list[str]
    confirmation_phrase: str


class UpdateQueueRowStatusRequest(BaseModel):
    promotion_status: str


@router.get("/queue")
async def list_queue(
    promotion_status: str | None = Query(None),
    claim_risk_level: str | None = Query(None),
    image_readiness: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return await _svc.list_bulk_queue(
        promotion_status=promotion_status,
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )


@router.get("/queue/stats")
async def get_queue_stats() -> dict[str, Any]:
    return await _svc.get_queue_stats()


@router.post("/queue/sync")
async def sync_queue(body: SyncQueueRequest | None = None) -> dict[str, Any]:
    batch_id = body.batch_id if body else None
    return await _svc.sync_bulk_queue(batch_id=batch_id)


@router.post("/queue/{reference_id}/create-draft")
async def create_draft_from_reference(reference_id: str) -> dict[str, Any]:
    result = await _svc.create_draft_from_reference(reference_id)
    if "error" in result and result["error"] in ("REFERENCE_NOT_IN_QUEUE",):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/queue/bulk-create-drafts")
async def bulk_create_drafts(body: BulkCreateDraftsRequest) -> dict[str, Any]:
    if not body.reference_ids:
        raise HTTPException(status_code=422, detail="reference_ids must not be empty")
    return await _svc.bulk_create_drafts(body.reference_ids)


@router.post("/queue/bulk-approve-drafts")
async def bulk_approve_drafts(body: BulkApproveDraftsRequest) -> dict[str, Any]:
    if not body.reference_ids:
        raise HTTPException(status_code=422, detail="reference_ids must not be empty")
    result = await _svc.bulk_approve_drafts(body.reference_ids, body.confirmation_phrase)
    if result.get("commit_status") == "BLOCKED" and result.get("error") == "INVALID_CONFIRMATION_PHRASE":
        raise HTTPException(status_code=403, detail="INVALID_CONFIRMATION_PHRASE")
    return result


@router.patch("/queue/{reference_id}/status")
async def update_queue_row_status(
    reference_id: str, body: UpdateQueueRowStatusRequest
) -> dict[str, Any]:
    result = await _svc.update_queue_row_status(reference_id, body.promotion_status)
    if "error" in result:
        status_code = 404 if result["error"] == "NOT_IN_QUEUE" else 422
        raise HTTPException(status_code=status_code, detail=result["error"])
    return result
