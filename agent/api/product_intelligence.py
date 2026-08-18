from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.models.product_intelligence import ProductIntelligenceResolveRequest
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceAIFillRequest,
    ProductIntelligenceAIFillResult,
    ProductIntelligenceFieldDispositionRequest,
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
    ai_fill_missing_review_draft,
    approve_review_draft,
    get_review_draft_by_id,
    reject_review_draft,
    update_review_draft,
    validate_review_draft,
)
from agent.services.product_truth_import_soft_reconciliation import (
    close_safe_import_soft_revisions,
    preview_import_soft_reconciliation,
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


@router.post("/review-drafts/{draft_id}/ai-fill-missing")
async def product_intelligence_review_draft_ai_fill_missing(
    draft_id: str,
    request: ProductIntelligenceAIFillRequest | None = None,
) -> ProductIntelligenceAIFillResult:
    """AI Fill Missing — DeepSeek proposes DRAFT values for missing/selected
    Product Truth fields only. Distinct from deterministic Recompute (no AI).
    Fail-closed (409) when the provider lane is unconfigured; 502 on a provider
    call failure. Never approves, never overwrites valid human evidence, never
    creates a snapshot. Result is a review draft with field-level provenance."""
    from agent.services import ai_copy_provider_adapter as _prov

    selected = request.selected_fields if request else None
    try:
        result = await ai_fill_missing_review_draft(draft_id, selected_fields=selected)
        return ProductIntelligenceAIFillResult(**result)
    except _prov.AICopyProviderNotConfigured as exc:
        raise HTTPException(status_code=409, detail={"error": exc.code}) from exc
    except _prov.AICopyProviderError as exc:
        raise HTTPException(status_code=502, detail={"error": exc.code, "detail": exc.detail}) from exc
    except ValueError as exc:
        code = str(exc)
        if code == "DRAFT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=code) from exc
        if code.startswith("DRAFT_UPDATE_FORBIDDEN:"):
            raise HTTPException(status_code=409, detail=code) from exc
        raise


@router.post("/review-drafts/{draft_id}/field-dispositions")
async def product_intelligence_review_draft_field_disposition(
    draft_id: str,
    request: ProductIntelligenceFieldDispositionRequest,
) -> dict:
    """Record ONE governed absence disposition (Mission-08D).

    NOT_STATED_IN_SOURCE / NOT_APPLICABLE / REQUIRES_EXTERNAL_EVIDENCE, stored as a
    reviewer-attributed provenance row on the OPEN draft — never as a placeholder in the
    value column. Upsert semantics: a retry or changed decision updates the single
    governing row. Returns the same validation payload as /validate so the UI sees the
    effect immediately. 422 = the request itself is illegal (ineligible field, missing
    note/reviewer, category forbids NOT_APPLICABLE); 409 = the draft's state refuses it
    (terminal draft, field already has a value).
    """
    from agent.services.product_intelligence_review_draft_service import (
        set_field_disposition,
    )

    try:
        return (await set_field_disposition(draft_id, request)).model_dump()
    except ValueError as exc:
        code = str(exc)
        if code == "DRAFT_NOT_FOUND":
            raise HTTPException(status_code=404, detail=code) from exc
        if code.startswith(("DRAFT_DISPOSITION_FORBIDDEN:", "FIELD_HAS_VALUE:")):
            raise HTTPException(status_code=409, detail=code) from exc
        if code.startswith(("FIELD_NOT_DISPOSITION_ELIGIBLE:",
                            "NOT_APPLICABLE_FORBIDDEN_FOR_CATEGORY:")) or code in (
                "REVIEWER_REQUIRED", "REVIEWER_NOTE_REQUIRED"):
            raise HTTPException(status_code=422, detail=code) from exc
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
        if code in {"DRAFT_ALREADY_APPROVED", "DRAFT_ALREADY_REJECTED"} or code.startswith(
            "DRAFT_UPDATE_FORBIDDEN:"
        ):
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
        if code in {"DRAFT_ALREADY_APPROVED", "DRAFT_ALREADY_REJECTED"} or code.startswith(
            "DRAFT_UPDATE_FORBIDDEN:"
        ):
            raise HTTPException(status_code=409, detail=code) from exc
        raise


@router.post("/{product_id}/recompute")
async def product_intelligence_recompute(product_id: str) -> dict:
    """Re-acquire an EXISTING product's evidence from its own stored source link.

    Deliberately NOT `/api/products/import-tiktokshop`: that route is an intake door and
    calls `crud.create_product`, so using it to refresh a product already in the catalogue
    would mint a duplicate row on every press. This one is product-ID scoped, reuses the
    product's open draft, and never approves anything.
    """
    from agent.services.product_intelligence_recompute_service import (
        ERR_NO_SOURCE_URL,
        ERR_PRODUCT_NOT_FOUND,
        RecomputeError,
        recompute_product_intelligence,
    )

    from agent.services.tiktokshop_browser_relay import TikTokRelayError

    try:
        return await recompute_product_intelligence(product_id)
    except RecomputeError as exc:
        # 404 for "no such product", 422 for "this product cannot be recomputed yet" —
        # a missing source link is an operator-fixable data gap, not a server fault.
        status = 404 if exc.code == ERR_PRODUCT_NOT_FOUND else (
            422 if exc.code == ERR_NO_SOURCE_URL else 502)
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except TikTokRelayError as exc:
        # 409 for the states the operator resolves in their own browser (open the product
        # tab, clear TikTok's Security Check by hand, reconnect the extension) and 502 for
        # everything else. Without that split, "go press something in Chrome" is presented
        # as a backend fault and the operator has no reason to believe a Retry would work.
        # The code itself is never swallowed — the UI branches on it.
        status = 409 if exc.operator_actionable else 502
        raise HTTPException(status_code=status, detail={
            "code": exc.code,
            "reason": exc.detail,
            "product_url": exc.product_url,
            "operator_actionable": exc.operator_actionable,
        }) from exc
    except Exception as exc:  # noqa: BLE001
        from agent.services.tiktokshop_extraction_service import (
            TikTokShopExtractionError,
        )
        if isinstance(exc, TikTokShopExtractionError):
            # The listing could not be read. Surfaced as a real failure rather than a
            # silent empty success, so the operator is never shown "done" for nothing.
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise


@router.post("/{product_id}/diagnose-evidence-tab")
async def product_intelligence_diagnose_evidence_tab(product_id: str) -> dict:
    """READ-ONLY: ask the extension to self-diagnose the dedicated evidence tab for this
    product (sanitized background-vs-active comparison). No provider call, no PI mutation —
    it exists to classify WHY a tab read empty from proof, not to write anything."""
    from agent.db import crud
    from agent.services import tiktokshop_browser_relay as relay
    from agent.services.product_intelligence_recompute_service import (
        ERR_NO_SOURCE_URL, resolve_source_url,
    )

    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="PRODUCT_NOT_FOUND")
    source_url = resolve_source_url(product)
    if not source_url:
        raise HTTPException(status_code=422, detail=ERR_NO_SOURCE_URL)
    try:
        result = await relay.diagnose_evidence_tab(source_url)
    except relay.TikTokRelayError as exc:
        status = 409 if exc.operator_actionable else 502
        raise HTTPException(status_code=status, detail={
            "code": exc.code, "product_url": exc.product_url,
            "operator_actionable": exc.operator_actionable}) from exc
    return {"product_id": product_id, "source_url": source_url, **result}




class ImportSoftReconciliationCloseRequest(BaseModel):
    """Explicit operator confirmation for SAFE import soft-field batch close."""

    confirm: bool = False
    confirm_phrase: str = Field(
        default="",
        description="Must be exactly: CLOSE SAFE IMPORT REVISIONS",
    )
    actor: str = "operator"
    expected_count: int | None = 549
    implementation_sha: str | None = None


@router.get("/import-soft-reconciliation/preview")
async def import_soft_reconciliation_preview() -> dict:
    """Dry-run candidate set for SAFE AA-AH import soft-field closure."""
    return await preview_import_soft_reconciliation()


@router.post("/import-soft-reconciliation/close")
async def import_soft_reconciliation_close(
    request: ImportSoftReconciliationCloseRequest,
) -> dict:
    """Governed batch: KEEP approved Product Truth + SUPERSEDE safe import revisions.

    Never approves import soft values into Product Truth. Never deletes history.
    Excludes review-required and claim-conflict drafts.
    """
    try:
        return await close_safe_import_soft_revisions(
            confirm=bool(request.confirm),
            actor=(request.actor or "operator").strip() or "operator",
            confirm_phrase=request.confirm_phrase,
            expected_count=request.expected_count,
            implementation_sha=request.implementation_sha,
        )
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=400, detail=code) from exc


@router.get("/{product_id}")
async def product_intelligence_detail(product_id: str) -> dict:
    return await get_product_intelligence_by_id(product_id)
