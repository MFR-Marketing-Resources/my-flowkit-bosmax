"""HTTP surface for the Final Prompt Approval Gate.

Drives the per-dispatch review -> (edit) -> approve -> (invalidate) lifecycle for
the active generation surfaces. The provider-ready execution envelope is frozen
here at review time; the dispatch boundary (make_video.start_generate and the
other credit-bearing chokes) verifies against it. Provider-free — no route in
this module ever calls a generation provider or spends a credit.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.services import execution_approval_service as eas


router = APIRouter(prefix="/execution-approval", tags=["execution-approval"])


class ReviewSnapshotRequest(BaseModel):
    surface: str
    logical_mode: str
    final_prompt_text: str = Field(..., min_length=1)
    product_id: str | None = None
    source_mode: str | None = None
    model: str | None = None
    aspect: str | None = None
    duration_s: int | None = None
    count: int | None = None
    image_model: str | None = None
    asset_media_ids: list[str] | None = None
    review_session_id: str | None = None
    created_by: str | None = None


class EditSnapshotRequest(BaseModel):
    edited_prompt_text: str = Field(..., min_length=1)
    editor_id: str | None = None


class ApproveSnapshotRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)


class InvalidateSnapshotRequest(BaseModel):
    reason: str = Field(..., min_length=1)


def _raise(exc: eas.ExecutionApprovalError):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message, "details": exc.details},
    ) from exc


@router.post("/review")
async def create_review(req: ReviewSnapshotRequest) -> dict[str, Any]:
    return await eas.create_review_snapshot(
        surface=req.surface,
        logical_mode=req.logical_mode,
        final_prompt_text=req.final_prompt_text,
        product_id=req.product_id,
        source_mode=req.source_mode,
        model=req.model,
        aspect=req.aspect,
        duration_s=req.duration_s,
        count=req.count,
        image_model=req.image_model,
        asset_media_ids=req.asset_media_ids,
        review_session_id=req.review_session_id,
        created_by=req.created_by,
    )


@router.get("/{snapshot_id}")
async def get_snapshot(snapshot_id: str) -> dict[str, Any]:
    snap = await eas.get_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail={"error": "SNAPSHOT_NOT_FOUND"})
    return snap


@router.get("")
async def list_snapshots(
    product_id: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    from agent.db import execution_approval_crud as _crud

    items = await _crud.list_snapshots(product_id=product_id, surface=surface, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/{snapshot_id}/edit")
async def edit_snapshot(snapshot_id: str, req: EditSnapshotRequest) -> dict[str, Any]:
    try:
        return await eas.apply_edit(
            snapshot_id, edited_prompt_text=req.edited_prompt_text, editor_id=req.editor_id,
        )
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.post("/{snapshot_id}/approve")
async def approve_snapshot(snapshot_id: str, req: ApproveSnapshotRequest) -> dict[str, Any]:
    try:
        return await eas.approve_snapshot(snapshot_id, approved_by=req.approved_by)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.post("/{snapshot_id}/invalidate")
async def invalidate_snapshot(snapshot_id: str, req: InvalidateSnapshotRequest) -> dict[str, Any]:
    try:
        return await eas.invalidate_snapshot(snapshot_id, reason=req.reason)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)
