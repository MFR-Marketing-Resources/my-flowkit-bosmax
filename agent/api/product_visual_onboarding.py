"""Smart Registration visual onboarding operator API.

All write routes are local, deterministic, and review-gated.  They do not
invoke image providers, create provider operations, or approve Product Truth.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
import uuid
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from agent.db import crud
from agent.services.product_visual_onboarding_service import (
    ProductVisualOnboardingError,
    get_product_visual_readiness,
    get_product_cutout_history,
    preview_bulk_cutout_preparation,
    prepare_product_cutout,
    reject_product_cutout,
    request_bulk_cutout_cancellation,
    resolve_product_visual_preview,
    run_bulk_cutout_preparation,
    upload_manual_product_cutout,
    use_original_product_fallback,
)
from agent.services.canva_cutout_workflow_service import (
    CanvaCutoutWorkflowError,
    advance_canva_stage,
    bypass_canva_cutout_bulk_item,
    cancel_canva_cutout_bulk,
    complete_canva_cutout,
    get_canva_cutout_bulk_run,
    get_canva_cutout_workflow,
    pause_canva_cutout_bulk,
    prepare_canva_cutout_bulk,
    preview_canva_cutout_bulk,
    record_canva_preflight,
    resume_canva_cutout_bulk,
    start_canva_cutout,
)

router = APIRouter(prefix="/product-visual-onboarding", tags=["product-visual-onboarding"])


class BulkPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    preview_digest: str = Field(min_length=64, max_length=64)
    batch_size: int = Field(default=5, ge=1, le=25)
    concurrency: int = Field(default=2, ge=1, le=4)
    max_products: int = Field(default=5, ge=1, le=25)


class CutoutDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


CanvaCapabilityStatus = Literal["READY", "UNAVAILABLE", "UNKNOWN", "PRO_REQUIRED", "USER_ACTION_REQUIRED"]
CanvaMethod = Literal["MAGIC_GRAB", "BACKGROUND_REMOVER", "MAGIC_LAYERS"]
CanvaStage = Literal[
    "PREFLIGHT",
    "OPENING_CANVA",
    "MAGIC_GRAB",
    "BACKGROUND_REMOVER",
    "MAGIC_LAYERS",
    "CLEAN_CANVAS",
    "READY_TO_EXPORT",
    "EXPORTING",
    "PAUSED",
]


class CanvaPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canva_method: CanvaMethod | None = None
    design_id: str | None = Field(default=None, max_length=256)
    design_url: str | None = Field(default=None, max_length=2000)
    login_status: CanvaCapabilityStatus = "UNKNOWN"
    magic_grab_status: CanvaCapabilityStatus = "UNKNOWN"
    background_remover_status: CanvaCapabilityStatus = "UNKNOWN"
    magic_layers_status: CanvaCapabilityStatus = "UNKNOWN"
    transparent_export_status: CanvaCapabilityStatus = "UNKNOWN"

    def capability_payload(self) -> dict[str, str]:
        return {
            "login_status": self.login_status,
            "magic_grab_status": self.magic_grab_status,
            "background_remover_status": self.background_remover_status,
            "magic_layers_status": self.magic_layers_status,
            "transparent_export_status": self.transparent_export_status,
        }


class CanvaStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: CanvaStage
    canva_method: CanvaMethod
    design_id: str | None = Field(default=None, max_length=256)
    design_url: str | None = Field(default=None, max_length=2000)


class CanvaBulkPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    preview_digest: str = Field(min_length=64, max_length=64)
    max_products: int = Field(default=3, ge=1, le=25)
    priority_product_ids: list[str] = Field(default_factory=list, max_length=25)
    preflight: CanvaPreflightRequest = Field(default_factory=CanvaPreflightRequest)


class CanvaBulkResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight: CanvaPreflightRequest = Field(default_factory=CanvaPreflightRequest)


class CanvaBulkBypassRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=2000)


def _error(exc: ProductVisualOnboardingError) -> HTTPException:
    status = getattr(exc, "status_code", None) or (404 if exc.code == "PRODUCT_NOT_FOUND" else 409)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


def _canva_error(exc: CanvaCutoutWorkflowError) -> HTTPException:
    status = getattr(exc, "status_code", None) or 409
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message})


@router.get("/catalog-summary")
async def get_catalog_visual_summary(limit: int = Query(default=1000, ge=1, le=1000)):
    """Read-only visual cohort summary; no lazy generation or provider work."""
    return await preview_bulk_cutout_preparation(limit=limit)


@router.get("/bulk/preview")
async def preview_bulk_prepare(limit: int = Query(default=454, ge=1, le=1000)):
    """Preview eligible canonical IDs before an operator confirms execution."""
    return await preview_bulk_cutout_preparation(limit=limit)


@router.post("/bulk/prepare")
async def queue_bulk_prepare(request: BulkPrepareRequest):
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail={"code": "EXPLICIT_CONFIRMATION_REQUIRED", "message": "Preview the canonical cohort and confirm before queueing."},
        )
    preview = await preview_bulk_cutout_preparation(limit=1000)
    if request.preview_digest != preview["preview_digest"]:
        raise HTTPException(
            status_code=409,
            detail={"code": "PREVIEW_STALE", "message": "Catalog changed after preview; refresh the preview before execution."},
        )
    eligible_product_ids = list(preview.get("eligible_product_ids") or [])
    product_ids = eligible_product_ids[: request.max_products]
    run_id = f"pvo_{uuid.uuid4().hex}"
    await crud.create_product_visual_onboarding_run(
        run_id,
        status="QUEUED",
        total_expected=len(product_ids),
        batch_size=request.batch_size,
        product_ids_json=json.dumps(product_ids, separators=(",", ":")),
        error_log_json="[]",
    )
    asyncio.create_task(
        run_bulk_cutout_preparation(
            run_id,
            product_ids,
            request.batch_size,
            request.concurrency,
        )
    )
    return {
        "run_id": run_id,
        "status": "QUEUED",
        "total_expected": len(product_ids),
        "eligible_total": len(eligible_product_ids),
        "max_products": request.max_products,
        "estimated_throughput": (preview.get("bounded_batch") or {}).get("estimated_throughput"),
        "counts": preview["counts"],
        "concurrency": request.concurrency,
        "provider_operations": 0,
        "created_without_credit": True,
    }


@router.get("/bulk/runs/{run_id}")
async def get_bulk_prepare_run(run_id: str):
    row = await crud.get_product_visual_onboarding_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Visual onboarding run not found")
    row["product_ids"] = json.loads(row.pop("product_ids_json") or "[]")
    row["errors"] = json.loads(row.pop("error_log_json") or "[]")
    row["provider_operations"] = 0
    row["created_without_credit"] = True
    created = _parse_utc(row.get("created_at"))
    terminal = str(row.get("status") or "").upper() in {
        "COMPLETED",
        "PARTIAL_FAILED",
        "FAILED",
    }
    updated = _parse_utc(row.get("updated_at"))
    elapsed_seconds = (
        max(0.0, ((updated or datetime.now(UTC)) - created).total_seconds())
        if created
        else 0.0
    )
    processed = int(row.get("total_processed") or 0)
    total = int(row.get("total_expected") or 0)
    products_per_minute = processed / (elapsed_seconds / 60.0) if elapsed_seconds > 0 else 0.0
    remaining = max(0, total - processed)
    row.update({
        "elapsed_seconds": round(elapsed_seconds, 3),
        "products_per_minute": round(products_per_minute, 3),
        "remaining": remaining,
        "estimated_remaining_seconds": round(remaining / (products_per_minute / 60.0), 3)
        if products_per_minute > 0 else None,
    })
    return row


def _parse_utc(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post("/bulk/runs/{run_id}/cancel")
async def cancel_bulk_prepare_run(run_id: str):
    try:
        return await request_bulk_cutout_cancellation(run_id)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.post("/{product_id}/cutout/manual")
async def upload_visual_manual_cutout(
    product_id: str,
    cutout: UploadFile = File(...),
    uploaded_by: str = Form("operator"),
):
    try:
        raw_bytes = await cutout.read()
        return await upload_manual_product_cutout(
            product_id,
            filename=cutout.filename or "manual-cutout.png",
            content_type=cutout.content_type,
            raw_bytes=raw_bytes,
            uploaded_by=uploaded_by,
        )
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc
    finally:
        await cutout.close()


@router.post("/{product_id}/cutout/reject")
async def reject_visual_cutout(product_id: str, request: CutoutDecisionRequest):
    try:
        return await reject_product_cutout(
            product_id,
            rejected_by=request.operator,
            reason=request.reason,
        )
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.post("/{product_id}/cutout/fallback")
async def fallback_visual_cutout(product_id: str, request: CutoutDecisionRequest):
    try:
        return await use_original_product_fallback(
            product_id,
            selected_by=request.operator,
            reason=request.reason,
        )
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.get("/{product_id}/cutout/history")
async def get_visual_cutout_history(product_id: str):
    try:
        return await get_product_cutout_history(product_id)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.get("/{product_id}/cutout/preview/{variant}")
async def get_visual_cutout_preview(
    product_id: str,
    variant: str,
    history_id: str | None = Query(default=None),
):
    try:
        path = await resolve_product_visual_preview(product_id, variant, history_id=history_id)
        return FileResponse(path, media_type="image/png", filename=path.name)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.get("/canva/bulk/preview")
async def preview_canva_bulk(limit: int = Query(default=1000, ge=1, le=1000)):
    try:
        return await preview_canva_cutout_bulk(limit=limit)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/canva/bulk/prepare")
async def prepare_canva_bulk(request: CanvaBulkPrepareRequest):
    try:
        return await prepare_canva_cutout_bulk(
            confirm=request.confirm,
            preview_digest=request.preview_digest,
            max_products=request.max_products,
            priority_product_ids=request.priority_product_ids,
            preflight=request.preflight.capability_payload(),
        )
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.get("/canva/bulk/runs/{run_id}")
async def get_canva_bulk_run(run_id: str):
    try:
        return await get_canva_cutout_bulk_run(run_id)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/canva/bulk/runs/{run_id}/pause")
async def pause_canva_bulk_run(run_id: str):
    try:
        return await pause_canva_cutout_bulk(run_id)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/canva/bulk/runs/{run_id}/resume")
async def resume_canva_bulk_run(run_id: str, request: CanvaBulkResumeRequest):
    try:
        return await resume_canva_cutout_bulk(
            run_id,
            preflight=request.preflight.capability_payload(),
        )
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/canva/bulk/runs/{run_id}/cancel")
async def cancel_canva_bulk_run(run_id: str):
    try:
        return await cancel_canva_cutout_bulk(run_id)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/canva/bulk/runs/{run_id}/items/{product_id}/bypass")
async def bypass_canva_bulk_item(run_id: str, product_id: str, request: CanvaBulkBypassRequest):
    try:
        return await bypass_canva_cutout_bulk_item(run_id, product_id, reason=f"{request.operator}: {request.reason}")
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.get("/{product_id}/canva")
async def get_canva_workflow(product_id: str):
    try:
        return await get_canva_cutout_workflow(product_id)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/{product_id}/canva/start")
async def start_canva_workflow(product_id: str):
    try:
        return await start_canva_cutout(product_id)
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/{product_id}/canva/preflight")
async def record_canva_workflow_preflight(product_id: str, request: CanvaPreflightRequest):
    try:
        return await record_canva_preflight(
            product_id,
            canva_method=request.canva_method,
            design_id=request.design_id,
            design_url=request.design_url,
            preflight=request.capability_payload(),
        )
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/{product_id}/canva/stage")
async def advance_canva_workflow_stage(product_id: str, request: CanvaStageRequest):
    try:
        return await advance_canva_stage(
            product_id,
            stage=request.stage,
            canva_method=request.canva_method,
            design_id=request.design_id,
            design_url=request.design_url,
        )
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc


@router.post("/{product_id}/canva/complete")
async def complete_canva_workflow(
    product_id: str,
    cutout: UploadFile = File(...),
    canva_method: CanvaMethod = Form(...),
    uploaded_by: str = Form("operator"),
    design_id: str | None = Form(default=None),
    design_url: str | None = Form(default=None),
):
    try:
        raw_bytes = await cutout.read()
        return await complete_canva_cutout(
            product_id,
            filename=cutout.filename or "canva-cutout.png",
            content_type=cutout.content_type,
            raw_bytes=raw_bytes,
            uploaded_by=uploaded_by,
            canva_method=canva_method,
            design_id=design_id,
            design_url=design_url,
        )
    except CanvaCutoutWorkflowError as exc:
        raise _canva_error(exc) from exc
    finally:
        await cutout.close()


@router.get("/{product_id}")
async def get_visual_readiness(product_id: str):
    try:
        return await get_product_visual_readiness(product_id)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.post("/{product_id}/cutout/prepare")
async def prepare_visual_cutout(product_id: str):
    try:
        return await prepare_product_cutout(product_id)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc


@router.post("/{product_id}/cutout/rebuild")
async def rebuild_visual_cutout(product_id: str):
    try:
        return await prepare_product_cutout(product_id, force=True)
    except ProductVisualOnboardingError as exc:
        raise _error(exc) from exc
