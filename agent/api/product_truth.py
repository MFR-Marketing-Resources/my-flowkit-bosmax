from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from agent.db import crud
from agent.models.product_truth_lock import (
    ProductTruthLockApprovalRequest,
    ProductTruthLockOnboardingRequest,
)
from agent.services.product_truth_service import ProductTruthService
from agent.services.product_truth_lock_service import (
    ProductTruthLockError,
    approve_product_truth_lock,
    create_pending_product_truth_lock,
    inspect_product_truth_lock,
    register_product_truth_cutout_media,
)

router = APIRouter(prefix="/product-truth", tags=["product-truth"])

@router.get("/reconciliation-audit")
async def get_reconciliation_audit(sample_limit: int = Query(default=20, ge=1, le=100)):
    """
    Catalog-level reconciliation audit (Read-Only).
    Aligned with PRODUCT_TRUTH_RECONCILIATION_CONTRACT.md
    """
    raw_products = await crud.list_products(limit=1000)
    profiles = [ProductTruthService.build_computed_profile(dict(p)) for p in raw_products]
    
    # Simple summary for Phase 1
    total = len(profiles)
    contradictions = sum(1 for p in profiles if p.reconciliation.contradiction_flags)
    confidence_dist = {}
    for p in profiles:
        label = p.reconciliation.confidence_label
        confidence_dist[label] = confidence_dist.get(label, 0) + 1
        
    return {
        "total_products": total,
        "contradiction_count": contradictions,
        "confidence_distribution": confidence_dist,
        "samples": profiles[:sample_limit],
        "no_write_back": True
    }

@router.get("/fastmoss-taxonomy-audit")
async def get_fastmoss_taxonomy_audit(sample_limit: int = Query(default=20, ge=1, le=100)):
    """
    Specific FastMoss taxonomy reconciliation audit.
    Identifies mapping contamination and raw source availability.
    """
    from agent.services.fastmoss_taxonomy_reconciliation_service import FastMossTaxonomyReconciliationService
    report = await FastMossTaxonomyReconciliationService.perform_full_fastmoss_audit(limit=sample_limit)
    return report


@router.get("/{product_id}/visual-lock")
async def get_visual_product_truth_lock(product_id: str):
    """Read-only exact-IMG preflight; never creates or approves a lock."""
    return inspect_product_truth_lock(product_id)


def _truth_lock_http_error(exc: ProductTruthLockError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post("/{product_id}/visual-lock/cutout")
async def upload_visual_product_truth_cutout(
    product_id: str,
    cutout: UploadFile = File(...),
):
    """Register a transparent cutout for review; never creates or approves a lock."""

    try:
        raw_bytes = await cutout.read(10 * 1024 * 1024 + 1)
        return await register_product_truth_cutout_media(
            product_id,
            filename=cutout.filename or "review-cutout.png",
            content_type=cutout.content_type,
            raw_bytes=raw_bytes,
        )
    except ProductTruthLockError as exc:
        raise _truth_lock_http_error(exc) from exc
    finally:
        await cutout.close()


@router.post("/{product_id}/visual-lock/onboard")
async def onboard_visual_product_truth_lock(
    product_id: str,
    request: ProductTruthLockOnboardingRequest,
):
    """Persist a cutout-backed lock as PENDING_REVIEW; never auto-approves."""
    try:
        return await create_pending_product_truth_lock(product_id, request)
    except ProductTruthLockError as exc:
        raise _truth_lock_http_error(exc) from exc


@router.post("/{product_id}/visual-lock/approve")
async def approve_visual_product_truth_lock(
    product_id: str,
    request: ProductTruthLockApprovalRequest,
):
    """Separate explicit human approval gate for exact product output."""
    try:
        return await approve_product_truth_lock(product_id, request)
    except ProductTruthLockError as exc:
        raise _truth_lock_http_error(exc) from exc
