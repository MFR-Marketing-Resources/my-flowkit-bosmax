"""Kalodata/External catalog import API.
Mount prefix: /api/kalodata

Additive staged import (2026-07-13): parses the Owner's Kalodata/Fastmoss
merged workbook into the staged reference catalog + HUB enrichment files.
Zero AI calls, zero direct `product` writes — promotion stays behind the
existing reviewed /fastmoss-bulk gates.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from agent.models.kalodata_import import (
    KalodataApplyHubRequest,
    KalodataCacheImagesRequest,
    KalodataImportReport,
    KalodataImportRequest,
    CopyIntelligenceBulkImportReport,
    CopyIntelligenceBulkImportRequest,
    CopyIntelligenceUploadedSourceRequest,
    CopyIntelligenceApprovedContextResponse,
    CopyIntelligencePromoteResult,
    CopyIntelligenceSeedLedgerResponse,
    CopyIntelligenceSeedReviewRequest,
    CopyIntelligenceSeedReviewResult,
    CopyIntelligenceWorkbookUploadReport,
)
from agent.services import kalodata_import_service as _svc

router = APIRouter(prefix="/kalodata", tags=["kalodata"])

# Default source workbook on the Owner's machine; the request may override.
DEFAULT_SOURCE_PATH = (
    r"C:\Users\USER\Desktop\Fastmoss\Kalodata-BONUS 300 DATA PRODUK.xlsx"
)

_CACHE_IMAGES_MAX = 25
_CACHE_IMAGE_ATTEMPTS = 3


@router.post("/import", response_model=KalodataImportReport)
async def import_external_catalog(body: KalodataImportRequest):
    source_path = (body.source_path or "").strip() or DEFAULT_SOURCE_PATH
    try:
        # Duplicate law: the TikTok Product ID is the product identity — rows
        # whose tid already exists in the system are never staged.
        existing_tids = await _svc.collect_system_tids()
        return await asyncio.to_thread(
            _svc.import_workbook, source_path, existing_tids
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, f"WORKBOOK_NOT_FOUND:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim, never partial-staged
        raise HTTPException(422, f"IMPORT_FAILED:{exc}") from exc


@router.post("/copy-intelligence/dry-run")
async def dry_run_copy_intelligence_seed(body: KalodataImportRequest):
    """Read COPYWRITING HUB and return a review-only seed audit."""
    source_path = (body.source_path or "").strip()
    if not source_path:
        raise HTTPException(422, "SOURCE_PATH_REQUIRED")
    try:
        return await _svc.build_copy_intelligence_dry_run_for_system(source_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"WORKBOOK_NOT_FOUND:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — fail closed before any seed action
        raise HTTPException(422, f"COPY_INTELLIGENCE_DRY_RUN_FAILED:{exc}") from exc


@router.post(
    "/copy-intelligence/workbooks",
    response_model=CopyIntelligenceWorkbookUploadReport,
)
async def upload_copy_intelligence_workbook(
    workbook: UploadFile = File(...),
):
    """Accept the full workbook source without exposing runtime file paths."""
    try:
        return await asyncio.to_thread(
            _svc.store_copy_intelligence_workbook_upload,
            original_filename=workbook.filename or "",
            payload=await workbook.read(),
        )
    except ValueError as exc:
        raise HTTPException(422, f"COPY_INTELLIGENCE_WORKBOOK_INVALID:{exc}") from exc


@router.post("/copy-intelligence/dry-run-upload")
async def dry_run_uploaded_copy_intelligence_seed(
    body: CopyIntelligenceUploadedSourceRequest,
):
    """Run the existing read-only audit against a validated uploaded source."""
    try:
        source_path = _svc.resolve_copy_intelligence_workbook_source(body.source_id)
        return await _svc.build_copy_intelligence_dry_run_for_system(source_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"UPLOADED_WORKBOOK_NOT_FOUND:{exc}") from exc
    except ValueError as exc:
        raise HTTPException(422, f"COPY_INTELLIGENCE_UPLOADED_SOURCE_INVALID:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — fail closed before any seed action
        raise HTTPException(422, f"COPY_INTELLIGENCE_DRY_RUN_FAILED:{exc}") from exc


@router.get(
    "/copy-intelligence/seeds",
    response_model=CopyIntelligenceSeedLedgerResponse,
)
async def list_copy_intelligence_seed_ledger(
    confidence: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    """List persisted review rows only; this endpoint has no seed side effect."""
    return await _svc.list_copy_intelligence_seed_records(
        confidence=confidence, status=status, search=search, limit=limit,
    )


@router.get(
    "/copy-intelligence/approved-context",
    response_model=CopyIntelligenceApprovedContextResponse,
)
async def list_approved_copy_intelligence_context(
    target_product_id: str | None = None,
    reference_id: str | None = None,
    seed_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    """Read-only APPROVED-only Copy Intelligence context for a product/reference.

    The safe consumption boundary for downstream Copy Assistant / Smart
    Registration: returns ONLY approved rows (NEEDS_REVIEW / REJECTED excluded),
    empty list when none. No seed/review/generation side effect; does not mutate
    Product Truth or Copy Sets and does not call any AI provider.
    """
    return await _svc.get_approved_copy_intelligence_context(
        target_product_id=target_product_id, reference_id=reference_id,
        seed_id=seed_id, limit=limit,
    )


async def _review_copy_intelligence_seed(seed_id: str, action: str, body: CopyIntelligenceSeedReviewRequest):
    """Shared handler for the approve/reject transition routes. Fail-closed: any
    guard failure raises, and no status transition is written. This endpoint
    never seeds, never materializes, and never routes a row to generation."""
    try:
        return await _svc.review_copy_intelligence_seed(
            seed_id,
            action=action,
            reviewed_by=body.reviewed_by,
            review_note=body.review_note,
            confirmation_phrase=body.confirmation_phrase,
        )
    except _svc.CopyIntelligenceReviewError as exc:
        raise HTTPException(
            exc.status_code, {"error": exc.code, "detail": exc.detail}
        ) from exc


@router.post(
    "/copy-intelligence/seeds/{seed_id}/approve",
    response_model=CopyIntelligenceSeedReviewResult,
)
async def approve_copy_intelligence_seed(seed_id: str, body: CopyIntelligenceSeedReviewRequest):
    """Approve ONE persisted ledger row (NEEDS_REVIEW -> APPROVED). Requires the
    exact confirmation phrase (stronger for MEDIUM confidence), a non-empty note,
    and reviewer identity. Approval records audit metadata only — it does not
    expose the row to Product Truth, Copy Sets, DeepSeek, or the compiler."""
    return await _review_copy_intelligence_seed(seed_id, "APPROVE", body)


@router.post(
    "/copy-intelligence/seeds/{seed_id}/reject",
    response_model=CopyIntelligenceSeedReviewResult,
)
async def reject_copy_intelligence_seed(seed_id: str, body: CopyIntelligenceSeedReviewRequest):
    """Reject ONE persisted ledger row (NEEDS_REVIEW -> REJECTED). Requires the
    exact reject phrase, a non-empty note, and reviewer identity."""
    return await _review_copy_intelligence_seed(seed_id, "REJECT", body)


@router.post(
    "/copy-intelligence/bulk-import-drafts",
    response_model=CopyIntelligenceBulkImportReport,
)
async def bulk_import_copy_intelligence_drafts(body: CopyIntelligenceBulkImportRequest):
    """Bulk-assemble MULTI-ANGLE review DRAFTS from the COPYWRITING HUB.

    For every HUB row that matches a catalog product (by normalized name) and
    does NOT already have an approved snapshot or a live draft, build a
    multi-angle persona (Pain Point + each Dream Outcome line) plus light
    product knowledge, and create a review DRAFT via the existing validated
    path. NEVER auto-approves; idempotent (re-running skips products already
    covered). `dry_run` (default True) matches + assembles but writes nothing.

    Provide `source_id` (validated upload — preferred) or `source_path`
    (Owner-machine override). Fails closed if neither is given: this workbook
    differs from the staging default, so there is no implicit source.
    """
    from agent.services import copy_intelligence_bulk_importer as _bulk

    source_id = (body.source_id or "").strip()
    source_path = (body.source_path or "").strip()
    try:
        if source_id:
            source_path = _svc.resolve_copy_intelligence_workbook_source(source_id)
        if not source_path:
            raise HTTPException(422, "SOURCE_REQUIRED:source_id_or_source_path")
        return await _bulk.import_hub_to_drafts(
            source_path, dry_run=body.dry_run, limit=body.limit,
        )
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(404, f"WORKBOOK_NOT_FOUND:{exc}") from exc
    except ValueError as exc:
        raise HTTPException(422, f"COPY_INTELLIGENCE_SOURCE_INVALID:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — fail closed; never partial-commit silently
        raise HTTPException(422, f"BULK_IMPORT_FAILED:{exc}") from exc


@router.post(
    "/copy-intelligence/seeds/{seed_id}/promote-to-review-draft",
    response_model=CopyIntelligencePromoteResult,
)
async def promote_copy_intelligence_seed_to_review_draft(seed_id: str):
    """Promote ONE APPROVED Copy Intelligence seed into a Product Intelligence
    review DRAFT (via the existing validated review-draft path). Fails closed for
    NEEDS_REVIEW / REJECTED seeds or seeds with no target product. Creates a
    non-approved DRAFT only — no Product Truth overwrite, no Copy Set write, no AI
    call, no auto-approve. The draft must pass the existing review gate before use."""
    try:
        return await _svc.promote_approved_copy_intelligence_to_review_draft(seed_id)
    except _svc.CopyIntelligencePromotionError as exc:
        raise HTTPException(
            exc.status_code, {"error": exc.code, "detail": exc.detail}
        ) from exc


@router.post("/purge-duplicates")
async def purge_duplicates(dry_run: bool = False):
    """Purge never-drafted queue rows whose TikTok product id duplicates
    another queue row or an already-committed product."""
    return await _svc.purge_redundant_queue_rows(dry_run=dry_run)


@router.post("/apply-hub-enrichment")
async def apply_hub_enrichment(body: KalodataApplyHubRequest):
    return await _svc.apply_hub_enrichment(body.reference_ids)


@router.get("/hub-gaps")
async def get_hub_gaps():
    return await _svc.hub_gaps()


@router.post("/cache-images")
async def cache_images(body: KalodataCacheImagesRequest) -> dict[str, Any]:
    """Bounded batch wrapper over the existing per-product cache-image door
    (committed products only). Sequential with per-item retry — never parallel
    hammering of the CDN."""
    product_ids = [p.strip() for p in body.product_ids if p and p.strip()]
    if not product_ids:
        raise HTTPException(422, "PRODUCT_IDS_REQUIRED")
    if len(product_ids) > _CACHE_IMAGES_MAX:
        raise HTTPException(422, f"MAX_{_CACHE_IMAGES_MAX}_PRODUCTS_PER_CALL")

    from agent.api.products import cache_product_image

    results: list[dict[str, Any]] = []
    cached = failed = 0
    for product_id in product_ids:
        outcome: dict[str, Any] = {"product_id": product_id}
        for attempt in range(1, _CACHE_IMAGE_ATTEMPTS + 1):
            try:
                result = await cache_product_image(product_id)
            except HTTPException as exc:
                outcome.update(status="failed", detail=str(exc.detail))
                break
            except Exception as exc:  # noqa: BLE001
                outcome.update(status="failed", detail=str(exc)[:200])
                break
            outcome.update(result)
            if result.get("status") == "success":
                break
            if attempt < _CACHE_IMAGE_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)
        if outcome.get("status") == "success":
            cached += 1
        else:
            failed += 1
        results.append(outcome)
    return {"results": results, "cached": cached, "failed": failed}
