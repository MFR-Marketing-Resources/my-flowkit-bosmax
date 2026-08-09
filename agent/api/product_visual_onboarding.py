"""Smart Registration visual onboarding operator API.

All write routes are local, deterministic, and review-gated.  They do not
invoke image providers, create provider operations, or approve Product Truth.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agent.db import crud
from agent.services.product_visual_onboarding_service import (
    ProductVisualOnboardingError,
    get_product_visual_readiness,
    preview_bulk_cutout_preparation,
    prepare_product_cutout,
    request_bulk_cutout_cancellation,
    run_bulk_cutout_preparation,
)

router = APIRouter(prefix="/product-visual-onboarding", tags=["product-visual-onboarding"])


class BulkPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    preview_digest: str = Field(min_length=64, max_length=64)
    batch_size: int = Field(default=5, ge=1, le=25)
    concurrency: int = Field(default=2, ge=1, le=4)


def _error(exc: ProductVisualOnboardingError) -> HTTPException:
    status = 404 if exc.code == "PRODUCT_NOT_FOUND" else 409
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
    product_ids = list(preview.get("eligible_product_ids") or [])
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
