"""
Bulk FastMoss Product Truth Promotion Service — Wave 1.

Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue:     #92

Governance invariants enforced here:
- FASTMOSS_REFERENCE and FASTMOSS lanes are never directly committed.
- Only FASTMOSS_PROMOTED drafts may be committed via this service.
- Confirmation phrase: PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
- LOW claim risk only is eligible for READY_FOR_APPROVAL.
- MEDIUM → NEEDS_REVIEW, HIGH → CLAIM_RISK (not bulk-approvable).
- IMAGE_MISSING rows cannot become READY_FOR_APPROVAL.
- Duplicate rows → DUPLICATE_SUSPECTED (not bulk-approvable).
- Lineage (fastmoss_reference_id, source_url, raw_product_title, batch_provenance) must be
  preserved on every generated draft and committed product.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from agent.db import crud
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.models.product_registration import RegistrationCommitRequest, RegistrationReviewDraft
from agent.services.fastmoss_product_reference_service import list_fastmoss_reference_products
from agent.services.product_knowledge_service import complete_product_knowledge
from agent.services.product_registration_service import create_registration_review_draft
from agent.services.registration_commit_service import RegistrationCommitService
from agent.services.registration_draft_recompute_service import derive_draft_image_asset_state
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService

_BULK_APPROVE_PHRASE = "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH"

_READY_STATUSES = {"READY_FOR_APPROVAL"}
_BLOCKED_BULK_STATUSES = {"NEEDS_REVIEW", "CLAIM_RISK", "IMAGE_MISSING",
                          "DUPLICATE_SUSPECTED", "MISSING_REQUIRED_FIELD", "APPROVED", "REJECTED"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _derive_image_readiness(image_url: str | None) -> str:
    return "IMAGE_PRESENT" if _clean(image_url) else "IMAGE_MISSING"


def _classify_promotion_status(
    claim_risk_level: str,
    image_readiness: str,
    missing_fields: list[str],
    is_duplicate: bool,
) -> str:
    if is_duplicate:
        return "DUPLICATE_SUSPECTED"
    if claim_risk_level == "HIGH":
        return "CLAIM_RISK"
    if claim_risk_level == "MEDIUM":
        return "NEEDS_REVIEW"
    if claim_risk_level != "LOW":
        # UNKNOWN or any non-LOW value → block until evaluated
        return "NEEDS_REVIEW"
    # LOW risk path
    if image_readiness == "IMAGE_MISSING":
        return "IMAGE_MISSING"
    if missing_fields:
        return "MISSING_REQUIRED_FIELD"
    return "READY_FOR_APPROVAL"


async def _detect_queue_duplicate(reference_id: str, raw_product_title: str,
                                   tiktok_product_url: str | None) -> bool:
    """Check if a matching product already exists in owned canonical rows.

    Canonical sources that block promotion:
      - source=MANUAL (user-owned product truth)
      - any product with mapping_source=FASTMOSS_PROMOTED (already committed via this pipeline)

    Raw source=FASTMOSS reference-catalog rows must NOT block promotion — they
    are the reference inputs being promoted, not owned canonical product truth.
    Querying them as blockers caused every reference row to self-match and become
    DUPLICATE_SUSPECTED on first Generate Drafts run.
    """
    title_clean = raw_product_title.strip().lower()
    if not title_clean:
        return False

    def _row_matches(row: dict) -> bool:
        row_names = {
            _clean(row.get("raw_product_title")).lower(),
            _clean(row.get("product_display_name")).lower(),
            _clean(row.get("product_short_name")).lower(),
        }
        if title_clean in row_names:
            return True
        return bool(tiktok_product_url and tiktok_product_url == _clean(row.get("tiktok_product_url")))

    candidates = await crud.list_products(query=raw_product_title, limit=50)
    for row in candidates:
        src = row.get("source", "")
        mapping_src = row.get("mapping_source", "")
        # Raw FASTMOSS reference rows are inputs to this promotion pipeline.
        # Only block on them once they have been committed (mapping_source=FASTMOSS_PROMOTED).
        if src == "FASTMOSS" and mapping_src != "FASTMOSS_PROMOTED":
            continue
        if _row_matches(row):
            return True

    return False


def _ref_to_completion_request(ref: dict[str, Any]) -> ProductKnowledgeCompleteRequest:
    raw_title = _clean(ref.get("raw_product_title"))
    category = _clean(ref.get("category")) or None
    commission_rate = _clean(ref.get("commission_rate")) or None
    sold_count = ref.get("sold_count")

    # Populate paste_anything_about_product from available ref metadata so
    # PRODUCT_DESCRIPTION_OR_KNOWLEDGE is not falsely flagged as missing.
    # Only real ref fields are used — no fabrication.
    knowledge_parts = [f"Product: {raw_title}"] if raw_title else []
    if category:
        knowledge_parts.append(f"Category: {category}")
    if sold_count:
        knowledge_parts.append(f"Sold count: {sold_count}")
    if commission_rate:
        knowledge_parts.append(f"Commission: {commission_rate}")
    paste_knowledge = " | ".join(knowledge_parts) or None

    return ProductKnowledgeCompleteRequest(
        product_name=raw_title,
        source_lane="FASTMOSS_PROMOTED",
        paste_anything_about_product=paste_knowledge,
        category=category,
        image_url=_clean(ref.get("image_url")) or None,
        source_url=_clean(ref.get("source_url")) or None,
        tiktok_product_url=_clean(ref.get("tiktok_product_url")) or None,
        commission_rate=commission_rate,
        price=ref.get("price"),
        currency=ref.get("currency") or "MYR",
    )


def _apply_lineage_to_draft(
    draft: RegistrationReviewDraft,
    ref: dict[str, Any],
    reference_id: str,
) -> RegistrationReviewDraft:
    """Stamp FastMoss lineage fields onto a draft — must never be stripped."""
    draft.fastmoss_reference_id = reference_id
    draft.source_lane = "FASTMOSS_PROMOTED"
    # Ensure declared evidence carries lineage fields
    evidence = dict(draft.declared_evidence_fields)
    if not evidence.get("source_url"):
        evidence["source_url"] = _clean(ref.get("source_url")) or None
    if not evidence.get("tiktok_product_url"):
        evidence["tiktok_product_url"] = _clean(ref.get("tiktok_product_url")) or None
    if not evidence.get("image_url"):
        evidence["image_url"] = _clean(ref.get("image_url")) or None
    draft.declared_evidence_fields = evidence
    prov = list(draft.provenance or [])
    prov_entry = f"fastmoss_bulk_promotion:reference_id={reference_id}"
    if prov_entry not in prov:
        prov.append(prov_entry)
    batch = _clean(ref.get("fastmoss_source_file"))
    if batch:
        batch_entry = f"fastmoss_source_file:{batch}"
        if batch_entry not in prov:
            prov.append(batch_entry)
    draft.provenance = prov
    return draft


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def sync_bulk_queue(batch_id: str | None = None) -> dict[str, Any]:
    """
    Load FastMoss reference rows and upsert into fastmoss_bulk_draft_status.
    Idempotent: existing rows are skipped (INSERT OR IGNORE).
    Returns sync summary.
    """
    refs = await list_fastmoss_reference_products(limit=2000)
    synced, skipped, errors = 0, 0, 0

    for ref in refs:
        reference_id: str = _clean(ref.get("id"))
        raw_title: str = _clean(ref.get("raw_product_title"))
        if not reference_id or not raw_title:
            errors += 1
            continue

        try:
            existing = await crud.get_bulk_queue_row(reference_id)
        except Exception as _db_err:
            logger.error("sync_bulk_queue: DB error querying row %s: %s", reference_id, _db_err)
            errors += 1
            continue
        if existing:
            skipped += 1
            continue

        claim_risk = _clean(ref.get("claim_risk_level") or "HIGH")
        image_url = _clean(ref.get("image_url")) or None
        image_readiness = _derive_image_readiness(image_url)
        tiktok_url = _clean(ref.get("tiktok_product_url")) or None
        source_url = _clean(ref.get("source_url")) or None
        category = _clean(ref.get("category")) or None
        mapping_confidence_raw = ref.get("mapping_confidence")
        mapping_confidence: float | None = None
        try:
            mapping_confidence = float(mapping_confidence_raw) if mapping_confidence_raw is not None else None
        except (TypeError, ValueError):
            pass

        sold_count_raw = ref.get("sold_count")
        sold_count: int | None = None
        try:
            sold_count = int(sold_count_raw) if sold_count_raw is not None else None
        except (TypeError, ValueError):
            pass

        commission_rate = str(ref.get("commission_rate") or "") or None

        try:
            await crud.create_bulk_queue_row(
                reference_id=reference_id,
                raw_product_title=raw_title,
                source_url=source_url,
                tiktok_product_url=tiktok_url,
                image_url=image_url,
                category=category,
                claim_risk_level=claim_risk or "HIGH",
                mapping_confidence=mapping_confidence,
                image_readiness=image_readiness,
                sold_count=sold_count,
                commission_rate=commission_rate,
                promotion_status="PENDING_DRAFT",
                batch_provenance=batch_id or _clean(ref.get("fastmoss_source_file")),
            )
            synced += 1
        except Exception:
            errors += 1

    return {
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "total_refs_loaded": len(refs),
        "synced_at": _now(),
    }


async def list_bulk_queue(
    promotion_status: str | None = None,
    claim_risk_level: str | None = None,
    image_readiness: str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    rows = await crud.list_bulk_queue(
        promotion_status=promotion_status,
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )
    total = await crud.count_bulk_queue(
        promotion_status=promotion_status,
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        category=category,
        q=q,
    )
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


async def get_queue_stats() -> dict[str, Any]:
    return await crud.get_bulk_queue_stats()


async def create_draft_from_reference(reference_id: str) -> dict[str, Any]:
    """
    Generate a RegistrationReviewDraft from one FastMoss reference row.
    Classifies promotion_status and saves the queue row + draft.
    """
    row = await crud.get_bulk_queue_row(reference_id)
    if not row:
        return {"error": "REFERENCE_NOT_IN_QUEUE", "reference_id": reference_id}

    if row.get("promotion_status") in ("APPROVED",):
        return {"error": "ALREADY_APPROVED", "reference_id": reference_id,
                "promotion_status": row["promotion_status"]}

    # Find the live reference product to pick up enriched data
    all_refs = await list_fastmoss_reference_products(limit=2000)
    ref = next((r for r in all_refs if _clean(r.get("id")) == reference_id), None)
    if not ref:
        ref = {
            "id": reference_id,
            "raw_product_title": row["raw_product_title"],
            "source_url": row.get("source_url"),
            "tiktok_product_url": row.get("tiktok_product_url"),
            "image_url": row.get("image_url"),
            "category": row.get("category"),
            "claim_risk_level": row.get("claim_risk_level", "HIGH"),
            "commission_rate": row.get("commission_rate"),
            "fastmoss_source_file": row.get("batch_provenance"),
        }

    completion_req = _ref_to_completion_request(ref)
    try:
        completion = complete_product_knowledge(completion_req)
    except Exception as e:
        await crud.update_bulk_queue_row(
            reference_id, promotion_status="MISSING_REQUIRED_FIELD",
            error_message=f"completion_failed:{e}", updated_at=_now()
        )
        return {"error": "COMPLETION_FAILED", "reference_id": reference_id, "detail": str(e)}

    draft = create_registration_review_draft(completion)
    draft = _apply_lineage_to_draft(draft, ref, reference_id)
    draft.last_recomputed_at = _now()
    draft.draft_freshness_status = "FRESH"

    # Re-derive image asset state from the evidence we just wrote
    img_status, img_detail = derive_draft_image_asset_state(draft.declared_evidence_fields)
    draft.image_asset_status = img_status
    draft.image_asset_detail = img_detail

    # Pre-approve normalized_name if product_name is present (bulk workflow)
    if draft.declared_evidence_fields.get("product_name"):
        draft.approval_checklist["normalized_name"] = True

    # Save the draft
    saved_draft = RegistrationDraftStorageService.save_draft(draft)

    # Classify promotion status
    image_readiness = _derive_image_readiness(draft.declared_evidence_fields.get("image_url"))
    claim_risk = draft.claim_risk_level or "HIGH"
    missing = list(draft.missing_required_evidence or [])
    is_dup = await _detect_queue_duplicate(
        reference_id,
        draft.declared_evidence_fields.get("product_name") or row["raw_product_title"],
        draft.declared_evidence_fields.get("tiktok_product_url"),
    )
    promo_status = _classify_promotion_status(claim_risk, image_readiness, missing, is_dup)

    # Persist blocking reason for operator visibility
    err_msg: str | None = None
    if promo_status == "MISSING_REQUIRED_FIELD" and missing:
        err_msg = "MISSING:" + ",".join(missing[:10])
    elif promo_status == "CLAIM_RISK":
        claim_tokens_str = ",".join(draft.claim_tokens[:5]) if draft.claim_tokens else ""
        err_msg = f"CLAIM_RISK:{draft.claim_gate}" + (f":{claim_tokens_str}" if claim_tokens_str else "")

    await crud.update_bulk_queue_row(
        reference_id,
        promotion_status=promo_status,
        draft_id=saved_draft.review_draft_id,
        claim_risk_level=claim_risk,
        image_readiness=image_readiness,
        error_message=err_msg,
        updated_at=_now(),
    )

    return {
        "reference_id": reference_id,
        "draft_id": saved_draft.review_draft_id,
        "promotion_status": promo_status,
        "claim_risk_level": claim_risk,
        "image_readiness": image_readiness,
        "draft": saved_draft.model_dump(),
    }


async def bulk_create_drafts(reference_ids: list[str]) -> dict[str, Any]:
    """
    Create drafts for multiple reference IDs. Partial failures are tolerated.
    """
    results = []
    success, failed = 0, 0
    for ref_id in reference_ids:
        try:
            result = await create_draft_from_reference(ref_id)
            if "error" in result:
                failed += 1
                results.append({"reference_id": ref_id, "status": "ERROR", "error": result["error"]})
            else:
                success += 1
                results.append({
                    "reference_id": ref_id,
                    "status": "OK",
                    "draft_id": result.get("draft_id"),
                    "promotion_status": result.get("promotion_status"),
                })
        except Exception as e:
            failed += 1
            results.append({"reference_id": ref_id, "status": "ERROR", "error": str(e)})
    return {"success": success, "failed": failed, "results": results}


async def bulk_approve_drafts(
    reference_ids: list[str], confirmation_phrase: str
) -> dict[str, Any]:
    """
    Bulk approve READY_FOR_APPROVAL rows only.
    Non-ready rows are skipped with per-row result — they do NOT cause the batch to abort.
    Requires exact confirmation phrase: PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
    """
    if confirmation_phrase != _BULK_APPROVE_PHRASE:
        return {
            "commit_status": "BLOCKED",
            "error": "INVALID_CONFIRMATION_PHRASE",
            "expected": _BULK_APPROVE_PHRASE,
            "results": [],
        }

    results = []
    approved, skipped, failed = 0, 0, 0

    for ref_id in reference_ids:
        row = await crud.get_bulk_queue_row(ref_id)
        if not row:
            skipped += 1
            results.append({"reference_id": ref_id, "outcome": "SKIPPED", "reason": "NOT_IN_QUEUE"})
            continue

        if row.get("promotion_status") != "READY_FOR_APPROVAL":
            skipped += 1
            results.append({
                "reference_id": ref_id,
                "outcome": "SKIPPED",
                "reason": f"NOT_READY:{row.get('promotion_status')}",
            })
            continue

        draft_id = row.get("draft_id")
        if not draft_id:
            failed += 1
            await crud.update_bulk_queue_row(ref_id, promotion_status="MISSING_REQUIRED_FIELD",
                                              error_message="DRAFT_ID_MISSING", updated_at=_now())
            results.append({"reference_id": ref_id, "outcome": "FAILED", "reason": "DRAFT_ID_MISSING"})
            continue

        commit_req = RegistrationCommitRequest(
            draft_id=draft_id,
            write_back_confirmed=True,
            user_confirmation_phrase=_BULK_APPROVE_PHRASE,
        )
        commit_result = await RegistrationCommitService.commit_fastmoss_promoted_draft(commit_req)

        if commit_result.get("commit_status") == "COMMITTED":
            committed_id = commit_result.get("committed_product_id")
            await crud.update_bulk_queue_row(
                ref_id,
                promotion_status="APPROVED",
                committed_product_id=committed_id,
                error_message=None,
                updated_at=_now(),
            )
            approved += 1
            results.append({
                "reference_id": ref_id,
                "outcome": "APPROVED",
                "committed_product_id": committed_id,
            })
        else:
            reasons = commit_result.get("blocked_reasons") or commit_result.get("errors") or []
            reason_str = ";".join(str(r) for r in reasons)
            await crud.update_bulk_queue_row(
                ref_id,
                error_message=reason_str[:500],
                updated_at=_now(),
            )
            failed += 1
            results.append({
                "reference_id": ref_id,
                "outcome": "FAILED",
                "reason": reason_str,
                "commit_status": commit_result.get("commit_status"),
            })

    return {
        "approved": approved,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


_RECOMPUTE_ELIGIBLE_STATUSES = {"MISSING_REQUIRED_FIELD", "PENDING_DRAFT"}
_RECOMPUTE_SKIP_REASONS = {
    "CLAIM_RISK": "CLAIM_RISK_RECOMPUTE_BLOCKED",
    "DUPLICATE_SUSPECTED": "DUPLICATE_REVIEW_REQUIRED",
    "APPROVED": "APPROVED_ROWS_CANNOT_RECOMPUTE",
    "REJECTED": "REJECTED_ROWS_CANNOT_RECOMPUTE",
}


async def recompute_selected(reference_ids: list[str]) -> dict[str, Any]:
    """
    Re-run smart mapping + draft classification for operator-selected rows.

    Eligible:
    - MISSING_REQUIRED_FIELD
    - PENDING_DRAFT

    Skipped explicitly:
    - CLAIM_RISK
    - DUPLICATE_SUSPECTED
    - APPROVED
    - REJECTED

    Governance:
    - never creates Product Truth
    - never approves rows
    - preserves FastMoss reference lineage via create_draft_from_reference
    """
    results: list[dict[str, Any]] = []
    recomputed = 0
    ready_for_approval = 0
    missing_required_field = 0
    claim_risk = 0
    duplicate_suspected = 0
    image_missing = 0
    failed = 0
    skipped = 0

    for ref_id in reference_ids:
        row = await crud.get_bulk_queue_row(ref_id)
        now = _now()
        if not row:
            skipped += 1
            results.append({
                "reference_id": ref_id,
                "previous_status": None,
                "new_status": None,
                "previous_error_message": None,
                "new_error_message": None,
                "draft_id": None,
                "outcome": "SKIPPED",
                "error": "NOT_IN_QUEUE",
            })
            continue

        previous_status = row.get("promotion_status", "")
        previous_error_message = row.get("error_message") or None

        if previous_status not in _RECOMPUTE_ELIGIBLE_STATUSES:
            skipped += 1
            results.append({
                "reference_id": ref_id,
                "previous_status": previous_status,
                "new_status": previous_status,
                "previous_error_message": previous_error_message,
                "new_error_message": previous_error_message,
                "draft_id": row.get("draft_id"),
                "outcome": "SKIPPED",
                "error": _RECOMPUTE_SKIP_REASONS.get(
                    previous_status,
                    f"STATUS_NOT_ELIGIBLE_FOR_RECOMPUTE:{previous_status}",
                ),
            })
            continue

        try:
            result = await create_draft_from_reference(ref_id)
        except Exception as e:
            failed += 1
            await crud.update_bulk_queue_row(
                ref_id,
                recomputed_at=now,
                recompute_previous_status=previous_status,
                recompute_previous_error=previous_error_message,
                updated_at=now,
            )
            results.append({
                "reference_id": ref_id,
                "previous_status": previous_status,
                "new_status": previous_status,
                "previous_error_message": previous_error_message,
                "new_error_message": previous_error_message,
                "draft_id": row.get("draft_id"),
                "outcome": "ERROR",
                "error": str(e),
            })
            continue

        updated_row = await crud.get_bulk_queue_row(ref_id) or row
        new_status = updated_row.get("promotion_status", previous_status)
        new_error_message = updated_row.get("error_message") or None
        draft_id = updated_row.get("draft_id")

        await crud.update_bulk_queue_row(
            ref_id,
            recomputed_at=now,
            recompute_previous_status=previous_status,
            recompute_previous_error=previous_error_message,
            updated_at=now,
        )

        if "error" in result:
            failed += 1
            results.append({
                "reference_id": ref_id,
                "previous_status": previous_status,
                "new_status": new_status,
                "previous_error_message": previous_error_message,
                "new_error_message": new_error_message,
                "draft_id": draft_id,
                "outcome": "ERROR",
                "error": result.get("error"),
            })
            continue

        recomputed += 1
        if new_status == "READY_FOR_APPROVAL":
            ready_for_approval += 1
        elif new_status == "MISSING_REQUIRED_FIELD":
            missing_required_field += 1
        elif new_status == "CLAIM_RISK":
            claim_risk += 1
        elif new_status == "DUPLICATE_SUSPECTED":
            duplicate_suspected += 1
        elif new_status == "IMAGE_MISSING":
            image_missing += 1

        results.append({
            "reference_id": ref_id,
            "previous_status": previous_status,
            "new_status": new_status,
            "previous_error_message": previous_error_message,
            "new_error_message": new_error_message,
            "draft_id": draft_id,
            "outcome": "OK",
            "error": None,
        })

    return {
        "recomputed": recomputed,
        "ready_for_approval": ready_for_approval,
        "missing_required_field": missing_required_field,
        "claim_risk": claim_risk,
        "duplicate_suspected": duplicate_suspected,
        "image_missing": image_missing,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


async def update_queue_row_status(reference_id: str, promotion_status: str) -> dict[str, Any]:
    """Manual status override — used for operator REJECT or PENDING_DRAFT reset."""
    _allowed = {
        "REJECTED", "PENDING_DRAFT", "NEEDS_REVIEW",
        "MISSING_REQUIRED_FIELD", "DUPLICATE_SUSPECTED",
    }
    if promotion_status not in _allowed:
        return {"error": f"STATUS_NOT_MANUALLY_SETTABLE:{promotion_status}"}
    row = await crud.get_bulk_queue_row(reference_id)
    if not row:
        return {"error": "NOT_IN_QUEUE"}
    updated = await crud.update_bulk_queue_row(
        reference_id, promotion_status=promotion_status, updated_at=_now()
    )
    return updated or {"reference_id": reference_id, "promotion_status": promotion_status}
