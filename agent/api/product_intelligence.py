from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent.models.product_intelligence import ProductIntelligenceResolveRequest
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftRejectRequest,
    ProductIntelligenceReviewDraftUpdateRequest,
)
from agent.models.product_intelligence_snapshot import (
    ProductIntelligenceFieldProvenanceListResponse,
)
from agent.services.product_intelligence_service import (
    get_product_intelligence_backfill_preview,
    get_product_intelligence_by_id,
    get_product_intelligence_summary,
    resolve_product_intelligence_request,
)
from agent.services.product_intelligence_snapshot_service import (
    get_provenance_list_response,
)
from agent.services.product_intelligence_review_draft_service import (
    approve_review_draft,
    get_review_draft_by_id,
    reject_review_draft,
    update_review_draft,
    validate_review_draft,
)
from agent.services.all_product_mapping_audit_service import (
    get_all_product_mapping_audit,
)


router = APIRouter(prefix="/product-intelligence", tags=["product-intelligence"])


@router.get("/summary")
async def product_intelligence_summary() -> dict:
    return await get_product_intelligence_summary()


@router.post("/backfill-preview")
async def product_intelligence_backfill_preview() -> dict:
    return await get_product_intelligence_backfill_preview()


@router.get("/mapping-audit")
async def product_intelligence_mapping_audit(sample_limit: int = 20) -> dict:
    return await get_all_product_mapping_audit(sample_limit=sample_limit)


@router.post("/resolve")
async def product_intelligence_resolve(
    request: ProductIntelligenceResolveRequest,
) -> dict:
    return await resolve_product_intelligence_request(request)


@router.get("/snapshots/{snapshot_id}/provenance")
async def product_intelligence_snapshot_provenance(
    snapshot_id: str,
    field_name: str | None = None,
) -> ProductIntelligenceFieldProvenanceListResponse:
    try:
        return await get_provenance_list_response(snapshot_id, field_name=field_name)
    except ValueError as exc:
        if str(exc) == "SNAPSHOT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND") from exc
        raise


@router.get("/review-drafts/{draft_id}")
async def product_intelligence_review_draft_detail(draft_id: str) -> dict:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
    return draft.model_dump()


@router.patch("/review-drafts/{draft_id}")
async def product_intelligence_review_draft_update(
    draft_id: str,
    request: ProductIntelligenceReviewDraftUpdateRequest,
) -> dict:
    try:
        return (await update_review_draft(draft_id, request)).model_dump()
    except ValueError as exc:
        code = str(exc)
        if code == "DRAFT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=code) from exc
        if code.startswith("DRAFT_UPDATE_FORBIDDEN:"):
            raise HTTPException(status_code=409, detail=code) from exc
        raise


@router.post("/review-drafts/{draft_id}/validate")
async def product_intelligence_review_draft_validate(draft_id: str) -> dict:
    try:
        return (await validate_review_draft(draft_id)).model_dump()
    except ValueError as exc:
        if str(exc) == "DRAFT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="DRAFT_NOT_FOUND") from exc
        raise


@router.post("/review-drafts/{draft_id}/approve")
async def product_intelligence_review_draft_approve(
    draft_id: str,
    request: ProductIntelligenceReviewDraftApproveRequest,
) -> dict:
    try:
        return (await approve_review_draft(draft_id, request)).model_dump()
    except ValueError as exc:
        code = str(exc)
        if code in {"DRAFT_NOT_FOUND", "PRODUCT_NOT_FOUND"}:
            raise HTTPException(status_code=404, detail=code) from exc
        if code in {"DRAFT_ALREADY_APPROVED", "DRAFT_ALREADY_REJECTED"}:
            raise HTTPException(status_code=409, detail=code) from exc
        if code.startswith("DRAFT_NOT_APPROVABLE:"):
            raise HTTPException(status_code=409, detail=code) from exc
        raise


@router.post("/review-drafts/{draft_id}/reject")
async def product_intelligence_review_draft_reject(
    draft_id: str,
    request: ProductIntelligenceReviewDraftRejectRequest,
) -> dict:
    try:
        return (await reject_review_draft(draft_id, request)).model_dump()
    except ValueError as exc:
        code = str(exc)
        if code == "DRAFT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=code) from exc
        if code in {"DRAFT_ALREADY_APPROVED", "DRAFT_ALREADY_REJECTED"}:
            raise HTTPException(status_code=409, detail=code) from exc
        raise


@router.get("/{product_id}")
async def product_intelligence_detail(product_id: str) -> dict:
    return await get_product_intelligence_by_id(product_id)
