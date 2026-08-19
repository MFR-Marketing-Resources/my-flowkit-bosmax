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


# --------------------------------------------------------------------------- #
# Server-side prepare (grounding BEFORE review — the WYSIWYG guarantee)
# --------------------------------------------------------------------------- #

class PrepareDispatchRequest(BaseModel):
    surface: str
    logical_mode: str
    prompt: str = Field(..., min_length=1)
    product_id: str | None = None
    source_mode: str | None = None
    model: str | None = None
    aspect: str | None = None
    duration_s: int | None = None
    count: int | None = None
    image_model: str | None = None
    asset_media_ids: list[str] | None = None
    visual_lane_id: str | None = None
    reference_pack_id: str | None = None
    creative_mode: str | None = None
    review_session_id: str | None = None
    created_by: str | None = None


async def _ground_final_prompt(req: "PrepareDispatchRequest") -> tuple[str, list[str]]:
    """Return the FINAL provider-ready prompt + the approval asset set for review.

    IMG product-aware: apply the SAME deterministic product-truth grounding the
    dispatch applies, so the operator reviews the grounded FINAL prompt (never the
    raw prompt) and the dispatch re-grounds to byte-identical text. Product IMG
    binds on the stable product_id anchor, so the review asset set is empty (the
    volatile Flow media id never enters the approval hash). Every other mode
    reviews its prompt + provided reference assets as given.
    """
    if (req.logical_mode or "").strip().upper() == "IMG" and req.product_id:
        from agent.api.flow import _apply_img_product_truth_gate
        grounded, _refs, _exact = await _apply_img_product_truth_gate(
            product_id=req.product_id,
            visual_lane_id=req.visual_lane_id,
            prompt=req.prompt,
            request_refs={},
            start_asset=None,
            reference_pack_id=req.reference_pack_id,
            creative_mode=req.creative_mode,
        )
        return grounded, []
    return req.prompt, list(req.asset_media_ids or [])


@router.post("/prepare")
async def prepare_dispatch(req: PrepareDispatchRequest) -> dict[str, Any]:
    """Compile the FINAL provider-ready prompt server-side and freeze a
    REVIEW_REQUIRED snapshot. The modal shows the returned ``final_prompt_text``;
    the dispatch boundary recomputes the SAME identity, so the approved prompt is
    dispatched EXACT. Provider-free — no credit is spent here."""
    try:
        final_prompt, asset_ids = await _ground_final_prompt(req)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)
    except Exception as exc:  # grounding refused (e.g. product visual not locked)
        raise HTTPException(
            status_code=422,
            detail={"error": "PREPARE_GROUNDING_FAILED", "message": str(exc)},
        ) from exc
    return await eas.create_review_snapshot(
        surface=req.surface,
        logical_mode=req.logical_mode,
        final_prompt_text=final_prompt,
        product_id=req.product_id,
        source_mode=req.source_mode,
        model=req.model,
        aspect=req.aspect,
        duration_s=req.duration_s,
        count=req.count,
        image_model=req.image_model,
        asset_media_ids=asset_ids,
        review_session_id=req.review_session_id,
        created_by=req.created_by,
    )


# --------------------------------------------------------------------------- #
# Approved Generation Manifest (multi-operation explicit approval)
# --------------------------------------------------------------------------- #

class ManifestItemRequest(BaseModel):
    item_key: str | None = None
    mode: str
    final_prompt_text: str = Field(..., min_length=1)
    product_id: str | None = None
    source_mode: str | None = None
    model: str | None = None
    aspect: str | None = None
    duration_s: int | None = None
    count: int | None = None
    image_model: str | None = None
    asset_media_ids: list[str] | None = None


class CreateManifestRequest(BaseModel):
    surface: str
    items: list[ManifestItemRequest] = Field(..., min_length=1)
    product_id: str | None = None
    logical_mode: str | None = None
    run_ref: str | None = None
    created_by: str | None = None


class ApproveManifestRequest(BaseModel):
    approved_by: str = Field(..., min_length=1)


class InvalidateManifestRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class EditManifestItemRequest(BaseModel):
    edited_prompt_text: str = Field(..., min_length=1)
    editor_id: str | None = None


@router.post("/manifest")
async def create_manifest(req: CreateManifestRequest) -> dict[str, Any]:
    try:
        return await eas.create_manifest(
            surface=req.surface,
            items=[i.model_dump() for i in req.items],
            product_id=req.product_id,
            logical_mode=req.logical_mode,
            run_ref=req.run_ref,
            created_by=req.created_by,
        )
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.get("/manifest")
async def list_manifests(
    run_ref: str | None = Query(default=None),
    surface: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    from agent.db import execution_approval_crud as _crud

    items = await _crud.list_manifests(run_ref=run_ref, surface=surface, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/manifest/{manifest_id}")
async def get_manifest(manifest_id: str) -> dict[str, Any]:
    try:
        return await eas.get_manifest_with_items(manifest_id)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.post("/manifest/{manifest_id}/item/{snapshot_id}/edit")
async def edit_manifest_item(
    manifest_id: str, snapshot_id: str, req: EditManifestItemRequest,
) -> dict[str, Any]:
    try:
        return await eas.edit_manifest_item(
            manifest_id, snapshot_id,
            edited_prompt_text=req.edited_prompt_text, editor_id=req.editor_id,
        )
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.post("/manifest/{manifest_id}/approve")
async def approve_manifest(manifest_id: str, req: ApproveManifestRequest) -> dict[str, Any]:
    try:
        return await eas.approve_manifest(manifest_id, approved_by=req.approved_by)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)


@router.post("/manifest/{manifest_id}/invalidate")
async def invalidate_manifest(manifest_id: str, req: InvalidateManifestRequest) -> dict[str, Any]:
    try:
        return await eas.invalidate_manifest(manifest_id, reason=req.reason)
    except eas.ExecutionApprovalError as exc:
        _raise(exc)
