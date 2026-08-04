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

import asyncio
import csv
import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from agent.db import crud
from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.models.product_registration import RegistrationCommitRequest, RegistrationReviewDraft
from agent.services.fastmoss_product_reference_service import (
    get_fastmoss_reference_product,
    list_fastmoss_reference_products,
)
from agent.services.product_knowledge_service import complete_product_knowledge
from agent.services.product_intelligence_service import evaluate_product_claims
from agent.services.product_registration_service import create_registration_review_draft
from agent.services.registration_commit_service import RegistrationCommitService
from agent.services.registration_draft_recompute_service import derive_draft_image_asset_state
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService

_BULK_APPROVE_PHRASE = "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH"
_CLEAR_DUPLICATE_PHRASE = "CLEAR_DUPLICATE_FOR_REVIEW"
_RECOMPUTE_RULESET_VERSION = "PI_RECOMPUTE_TRUTH_V2"
_RECOMPUTE_APPLY_PHRASE = "APPLY_RECONCILE_METADATA_NO_PRODUCT_WRITES"
_REFERENCE_FULL_SCAN_LIMIT = 10_000

_READY_STATUSES = {"READY_FOR_APPROVAL"}
_BLOCKED_BULK_STATUSES = {"NEEDS_REVIEW", "CLAIM_RISK", "IMAGE_MISSING",
                          "DUPLICATE_SUSPECTED", "MISSING_REQUIRED_FIELD", "APPROVED", "REJECTED"}

_DUPLICATE_REVIEW_ACTIONS = {
    "LINK_TO_EXISTING_PRODUCT",
    "MARK_FALSE_DUPLICATE",
    "KEEP_BLOCKED",
    "REJECT_REFERENCE",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _derive_image_readiness(image_url: str | None) -> str:
    return "IMAGE_PRESENT" if _clean(image_url) else "IMAGE_MISSING"


def _reference_fingerprint(ref: dict[str, Any]) -> str:
    """Fingerprint only authoritative FastMoss inputs used by recompute."""
    payload = {
        key: ref.get(key)
        for key in (
            "id",
            "raw_product_title",
            "category",
            "subcategory",
            "type",
            "product_type",
            "product_type_id",
            "image_url",
            "source_url",
            "tiktok_product_url",
            "sold_count",
            "commission_rate",
            "price",
            "currency",
            "fastmoss_source_file",
        )
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _row_reference_fallback(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("reference_id"),
        "raw_product_title": row.get("raw_product_title"),
        "category": row.get("category"),
        "image_url": row.get("image_url"),
        "source_url": row.get("source_url"),
        "tiktok_product_url": row.get("tiktok_product_url"),
        "sold_count": row.get("sold_count"),
        "commission_rate": row.get("commission_rate"),
        "fastmoss_source_file": row.get("batch_provenance"),
    }


async def _current_reference_map(
    *,
    limit: int | None = None,
    reference_ids: list[str] | set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Authoritative refetch used by freshness checks; no provider/AI calls.

    The catalogue is currently 665 rows, so a bounded 500-row read is not an
    authoritative lookup.  Full scans use a high deterministic cap and
    single-row operations additionally perform an exact-ID fallback when a
    source adapter still returns a truncated page.
    """
    required_ids = {_clean(reference_id) for reference_id in (reference_ids or [])}
    required_ids.discard("")
    scan_limit = max(
        _REFERENCE_FULL_SCAN_LIMIT,
        len(required_ids),
        int(limit or 0),
        1,
    )
    refs = await list_fastmoss_reference_products(limit=scan_limit)
    mapped = {
        _clean(ref.get("id")): ref
        for ref in refs
        if _clean(ref.get("id"))
    }
    for reference_id in required_ids - set(mapped):
        exact = await get_fastmoss_reference_product(reference_id)
        if exact and _clean(exact.get("id")) == reference_id:
            mapped[reference_id] = exact
    return mapped


def _computed_metadata_for_row(row: dict[str, Any]) -> tuple[str, str]:
    """Return the last successful compute lineage, not reconciliation metadata.

    The legacy fallback is limited to rows that were already completed before
    the split fields existed.  A row explicitly marked STALE is never allowed
    to infer successful computation from its current input/ruleset metadata.
    """
    computed_fingerprint = _clean(row.get("computed_input_fingerprint"))
    computed_ruleset = _clean(row.get("computed_ruleset_version"))
    state = _clean(row.get("recompute_state"))
    legacy_completed_status = _clean(row.get("promotion_status")) in {
        "APPROVED",
        "DUPLICATE_LINKED",
        "MISSING_REQUIRED_FIELD",
        "REJECTED",
    }
    if (
        not computed_fingerprint
        and not computed_ruleset
        and _clean(row.get("recomputed_at"))
        and (
            state not in {"STALE", "QUEUED", "RECOMPUTING"}
            or legacy_completed_status
        )
    ):
        computed_fingerprint = _clean(row.get("input_fingerprint"))
        computed_ruleset = _clean(row.get("ruleset_version"))
    return computed_fingerprint, computed_ruleset


def _state_payload(
    *,
    state: str,
    reason: str,
    current_fingerprint: str,
    computed_fingerprint: str,
    computed_ruleset: str,
    review_hold_reason: str | None = None,
    current_claim_risk: str | None = None,
    current_claim_tokens: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recompute_state": state,
        "recompute_reason": reason,
        # input_fingerprint is the latest authoritative source observation.
        "input_fingerprint": current_fingerprint,
        # computed_* are written only after a successful deterministic compute.
        "computed_input_fingerprint": computed_fingerprint or None,
        "computed_ruleset_version": computed_ruleset or None,
        "review_hold_reason": review_hold_reason,
    }
    if current_claim_risk is not None:
        payload["current_claim_risk_level"] = current_claim_risk
    if current_claim_tokens is not None:
        payload["current_claim_tokens"] = current_claim_tokens
    return payload


def _recompute_state_for_row(
    row: dict[str, Any],
    ref: dict[str, Any],
) -> dict[str, Any]:
    status = _clean(row.get("promotion_status"))
    current_fingerprint = _reference_fingerprint(ref)
    observed_fingerprint = _clean(row.get("input_fingerprint"))
    observed_ruleset = _clean(row.get("ruleset_version"))
    stored_state = _clean(row.get("recompute_state"))
    computed_fingerprint, computed_ruleset = _computed_metadata_for_row(row)
    source_changed_since_observation = bool(
        observed_fingerprint and observed_fingerprint != current_fingerprint
    )
    computed_input_changed = bool(
        computed_fingerprint and computed_fingerprint != current_fingerprint
    )
    computed_ruleset_changed = bool(
        computed_ruleset and computed_ruleset != _RECOMPUTE_RULESET_VERSION
    )
    computed_current = (
        bool(computed_fingerprint and computed_ruleset)
        and computed_fingerprint == current_fingerprint
        and computed_ruleset == _RECOMPUTE_RULESET_VERSION
    )

    if stored_state in {"QUEUED", "RECOMPUTING"}:
        return _state_payload(
            state=stored_state,
            reason=row.get("recompute_reason") or "RECOMPUTE_IN_PROGRESS",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            review_hold_reason=row.get("review_hold_reason"),
        )

    if status == "MISSING_REQUIRED_FIELD":
        # A missing-evidence result is tied to the source input that produced
        # it.  If authoritative evidence changes, reopen the row as STALE so
        # the deterministic engine can evaluate the new evidence.
        if (
            source_changed_since_observation
            or computed_input_changed
            or (observed_ruleset and observed_ruleset != _RECOMPUTE_RULESET_VERSION)
            or computed_ruleset_changed
        ):
            return _state_payload(
                state="STALE",
                reason="SOURCE_INPUT_CHANGED_OR_UNSTAMPED",
                current_fingerprint=current_fingerprint,
                computed_fingerprint=computed_fingerprint,
                computed_ruleset=computed_ruleset,
            )
        return _state_payload(
            state="BLOCKED_MISSING_EVIDENCE",
            reason=row.get("error_message") or "MISSING_REQUIRED_EVIDENCE",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
        )

    blocked_tokens, review_tokens, _warnings = evaluate_product_claims(ref)
    current_claim_tokens = sorted(set(blocked_tokens + review_tokens))
    current_claim_risk = "HIGH" if (blocked_tokens or review_tokens) else "LOW"
    claim_reason = (
        "CLAIM_RISK_REVALIDATION_REQUIRED:" + ",".join(current_claim_tokens[:10])
        if current_claim_tokens
        else None
    )

    if status == "APPROVED":
        # An approved queue row is never silently recomputed or demoted.  A
        # newly detected unsafe claim becomes a review hold that also blocks
        # downstream content generation until a human revalidates it.
        if claim_reason:
            return _state_payload(
                state="BLOCKED_REVIEW_REQUIRED",
                reason=claim_reason,
                current_fingerprint=current_fingerprint,
                computed_fingerprint=computed_fingerprint,
                computed_ruleset=computed_ruleset,
                review_hold_reason=claim_reason,
                current_claim_risk=current_claim_risk,
                current_claim_tokens=current_claim_tokens,
            )
        return _state_payload(
            state="UP_TO_DATE",
            reason="APPROVED_ROW_AUDITED_NO_NEW_CLAIMS",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    if status in {"DUPLICATE_LINKED", "REJECTED"}:
        return _state_payload(
            state="UP_TO_DATE",
            reason=f"STATUS_NOT_RECOMPUTABLE:{status}",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    if status == "DUPLICATE_SUSPECTED":
        return _state_payload(
            state="BLOCKED_REVIEW_REQUIRED",
            reason=row.get("error_message") or "DUPLICATE_REVIEW_REQUIRED",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    if (
        stored_state == "FAILED"
        and observed_fingerprint == current_fingerprint
        and observed_ruleset == _RECOMPUTE_RULESET_VERSION
    ):
        return _state_payload(
            state="FAILED",
            reason=row.get("recompute_reason") or row.get("error_message") or "RECOMPUTE_FAILED",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    if not computed_current:
        return _state_payload(
            state="STALE",
            reason=(
                "RULESET_CHANGED"
                if (
                    computed_fingerprint == current_fingerprint
                    and computed_ruleset
                    and computed_ruleset != _RECOMPUTE_RULESET_VERSION
                )
                else "SOURCE_INPUT_CHANGED_OR_UNSTAMPED"
            ),
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    if status in {
        "CLAIM_RISK",
        "NEEDS_REVIEW",
        "IMAGE_MISSING",
    }:
        return _state_payload(
            state="BLOCKED_REVIEW_REQUIRED",
            reason=row.get("error_message") or f"STATUS_REQUIRES_REVIEW:{status}",
            current_fingerprint=current_fingerprint,
            computed_fingerprint=computed_fingerprint,
            computed_ruleset=computed_ruleset,
            current_claim_risk=current_claim_risk,
            current_claim_tokens=current_claim_tokens,
        )

    return _state_payload(
        state="UP_TO_DATE",
        reason="CURRENT_RULESET_AND_INPUT_MATCH",
        current_fingerprint=current_fingerprint,
        computed_fingerprint=computed_fingerprint,
        computed_ruleset=computed_ruleset,
        current_claim_risk=current_claim_risk,
        current_claim_tokens=current_claim_tokens,
    )


def _state_after_recompute(status: str, error_message: str | None) -> tuple[str, str]:
    if status == "MISSING_REQUIRED_FIELD":
        return "BLOCKED_MISSING_EVIDENCE", error_message or "MISSING_REQUIRED_EVIDENCE"
    if status in {"CLAIM_RISK", "NEEDS_REVIEW", "IMAGE_MISSING", "DUPLICATE_SUSPECTED"}:
        return "BLOCKED_REVIEW_REQUIRED", error_message or f"STATUS_REQUIRES_REVIEW:{status}"
    return "UP_TO_DATE", "RECOMPUTE_COMPLETED"


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
    return (
        await _detect_queue_duplicate_candidate(reference_id, raw_product_title, tiktok_product_url)
    ) is not None


async def _detect_queue_duplicate_candidate(
    reference_id: str,
    raw_product_title: str,
    tiktok_product_url: str | None,
    *,
    ignore_product_id: str | None = None,
) -> dict[str, Any] | None:
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
        return None

    def _row_matches(row: dict) -> str | None:
        row_names = {
            _clean(row.get("raw_product_title")).lower(),
            _clean(row.get("product_display_name")).lower(),
            _clean(row.get("product_short_name")).lower(),
        }
        if title_clean in row_names:
            return "TITLE_MATCH_EXISTING_PRODUCT"
        if tiktok_product_url and tiktok_product_url == _clean(row.get("tiktok_product_url")):
            return "TIKTOK_URL_MATCH_EXISTING_PRODUCT"
        return None

    def _candidate_payload(row: dict, match_reason: str) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "title": row.get("product_display_name")
            or row.get("product_short_name")
            or row.get("raw_product_title"),
            "source": row.get("source"),
            "mapping_source": row.get("mapping_source"),
            "match_reason": match_reason,
        }

    def _is_blocking_canonical(row: dict) -> bool:
        if ignore_product_id and str(row.get("id") or "") == ignore_product_id:
            return False
        src = row.get("source", "")
        mapping_src = row.get("mapping_source", "")
        # Raw FASTMOSS reference rows are inputs to this promotion pipeline.
        # Only block on them once they have been committed (mapping_source=FASTMOSS_PROMOTED).
        return not (src == "FASTMOSS" and mapping_src != "FASTMOSS_PROMOTED")

    candidates = await crud.list_products(query=raw_product_title, limit=50)
    for row in candidates:
        if not _is_blocking_canonical(row):
            continue
        match_reason = _row_matches(row)
        if match_reason:
            return _candidate_payload(row, match_reason)

    # TikTok Product ID match (Owner duplicate law, 2026-07-14): the id is the
    # product identity — it catches truncated/variant titles the title query
    # above can never see.
    tid_match = re.search(
        r"(?:/pdp/|/product/|[?&](?:pid|product_id)=)(\d{6,})",
        _clean(tiktok_product_url),
    )
    if tid_match:
        for row in await crud.find_products_by_tiktok_product_id(tid_match.group(1)):
            if not _is_blocking_canonical(row):
                continue
            return _candidate_payload(row, "TIKTOK_PRODUCT_ID_MATCH_EXISTING_PRODUCT")

    return None


def _queue_content_policy_from_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "content_generation_allowed": False,
            "resolved_product_id": None,
            "reason": "REFERENCE_NOT_IN_QUEUE",
        }

    status = str(row.get("promotion_status") or "")
    committed_product_id = _clean(row.get("committed_product_id")) or None
    linked_product_id = _clean(row.get("linked_product_id")) or None
    claim_risk_level = str(row.get("claim_risk_level") or "")
    recompute_state = str(row.get("recompute_state") or "")
    review_hold_reason = _clean(row.get("review_hold_reason")) or None

    if recompute_state == "BLOCKED_REVIEW_REQUIRED" or review_hold_reason:
        return {
            "content_generation_allowed": False,
            "resolved_product_id": None,
            "reason": review_hold_reason or "RECOMPUTE_REVIEW_REQUIRED",
        }

    if claim_risk_level == "HIGH" or status == "CLAIM_RISK":
        return {
            "content_generation_allowed": False,
            "resolved_product_id": None,
            "reason": "CLAIM_RISK_BLOCKS_CONTENT_GENERATION",
        }

    if status == "APPROVED" and committed_product_id:
        return {
            "content_generation_allowed": True,
            "resolved_product_id": committed_product_id,
            "reason": "APPROVED_PRODUCT_TRUTH",
        }
    if status == "DUPLICATE_LINKED" and linked_product_id:
        return {
            "content_generation_allowed": True,
            "resolved_product_id": linked_product_id,
            "reason": "LINKED_EXISTING_PRODUCT_TRUTH",
        }
    if status == "READY_FOR_APPROVAL":
        return {
            "content_generation_allowed": False,
            "resolved_product_id": None,
            "reason": "READY_FOR_APPROVAL_PREVIEW_ONLY",
        }
    return {
        "content_generation_allowed": False,
        "resolved_product_id": None,
        "reason": f"STATUS_BLOCKS_CONTENT_GENERATION:{status or 'UNKNOWN'}",
    }


async def can_generate_content_for_fastmoss_reference(reference_id: str) -> dict[str, Any]:
    row = await crud.get_bulk_queue_row(reference_id)
    if row:
        refs_by_id = await _current_reference_map(reference_ids=[reference_id])
        ref = refs_by_id.get(reference_id) or _row_reference_fallback(row)
        evaluation = _recompute_state_for_row(row, ref)
        if (
            evaluation["recompute_state"] == "BLOCKED_REVIEW_REQUIRED"
            and evaluation.get("review_hold_reason")
        ):
            return {
                "content_generation_allowed": False,
                "resolved_product_id": None,
                "reason": evaluation.get("review_hold_reason")
                or evaluation.get("recompute_reason")
                or "RECOMPUTE_REVIEW_REQUIRED",
            }
    policy = _queue_content_policy_from_row(row)
    resolved_product_id = policy.get("resolved_product_id")
    if resolved_product_id and not await crud.get_product(resolved_product_id):
        return {
            "content_generation_allowed": False,
            "resolved_product_id": None,
            "reason": "LINKED_OR_COMMITTED_PRODUCT_NOT_FOUND",
        }
    return policy


def _attach_duplicate_metadata_to_row(
    row: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(row)
    if evaluation:
        payload.update(evaluation)
    payload["duplicate_candidate"] = None
    suspected_existing_product_id = _clean(payload.get("suspected_existing_product_id")) or None
    if suspected_existing_product_id:
        payload["duplicate_candidate"] = {
            "product_id": suspected_existing_product_id,
            "title": payload.get("suspected_existing_product_title"),
            "source": payload.get("suspected_existing_product_source"),
            "mapping_source": payload.get("suspected_existing_product_mapping_source"),
            "match_reason": payload.get("duplicate_match_reason"),
        }
    policy = _queue_content_policy_from_row(payload)
    payload["content_generation_allowed"] = policy["content_generation_allowed"]
    payload["resolved_product_id"] = policy["resolved_product_id"]
    payload["content_generation_reason"] = policy["reason"]
    return payload


def _product_row_is_canonical_truth(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if row.get("reference_only"):
        return False
    src = str(row.get("source") or "").upper()
    mapping_source = str(row.get("mapping_source") or "").upper()
    mapping_status = str(row.get("mapping_status") or "").upper()
    fastmoss_reference_id = str(row.get("fastmoss_reference_id") or "")
    if mapping_status != "APPROVED":
        return False
    if src in {"MANUAL", "IMPORTED"}:
        return True
    if src == "FASTMOSS" and (mapping_source == "FASTMOSS_PROMOTED" or fastmoss_reference_id):
        return True
    return False


def _staged_hub_enrichment_for(reference_id: str) -> dict[str, Any]:
    """Staged Kalodata HUB copy for this reference, if any. Draft creation
    MUST carry it — before this, only /apply-hub-enrichment wrote these
    fields, so any later draft rebuild silently wiped the Owner's HUB copy
    (live incident 2026-07-14: langsir draft with all knowledge fields empty
    while its staged HUB entry existed)."""
    if not reference_id:
        return {}
    try:
        from agent.services.kalodata_import_service import load_hub_enrichment

        return dict(load_hub_enrichment().get(reference_id) or {})
    except Exception as exc:  # noqa: BLE001 — staged file optional
        logger.warning("staged hub enrichment unavailable for %s: %s", reference_id, exc)
        return {}


def _ref_to_completion_request(ref: dict[str, Any]) -> ProductKnowledgeCompleteRequest:
    raw_title = _clean(ref.get("raw_product_title"))
    category = _clean(ref.get("category")) or None
    commission_rate = _clean(ref.get("commission_rate")) or None
    sold_count = ref.get("sold_count")
    hub = _staged_hub_enrichment_for(_clean(ref.get("id")))

    def _hub_text(key: str) -> str | None:
        value = str(hub.get(key) or "").strip()
        return value or None

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
    hub_knowledge = _hub_text("product_knowledge_text")
    if hub_knowledge:
        paste_knowledge = (
            f"{paste_knowledge}\n\n{hub_knowledge}" if paste_knowledge else hub_knowledge
        )

    hub_price = hub.get("price")

    request = ProductKnowledgeCompleteRequest(
        product_name=raw_title,
        source_lane="FASTMOSS_PROMOTED",
        paste_anything_about_product=paste_knowledge,
        category=category,
        subcategory=_clean(ref.get("subcategory")) or _hub_text("subcategory"),
        type=_clean(ref.get("type")) or _hub_text("type"),
        product_type=(
            _clean(ref.get("product_type"))
            or _hub_text("product_type")
            or _hub_text("type_of_product")
        ),
        product_type_id=(
            _clean(ref.get("product_type_id"))
            or _hub_text("product_type_id")
        ),
        materials_text=_hub_text("materials_text"),
        image_url=_clean(ref.get("image_url")) or None,
        source_url=_clean(ref.get("source_url")) or None,
        tiktok_product_url=_clean(ref.get("tiktok_product_url")) or None,
        commission_rate=commission_rate,
        price=ref.get("price") if ref.get("price") is not None else hub_price,
        currency=ref.get("currency") or "MYR",
        benefits_text=_hub_text("benefits_text"),
        usage_text=_hub_text("usage_text"),
        target_customer_text=_hub_text("target_customer_text"),
        ingredients_text=_hub_text("ingredients_text"),
        warnings_text=_hub_text("warnings_text"),
    )
    # Staged Kalodata HUB copy is frequently TikTok *creative* metadata — hashtags,
    # background-music names, clip duration, CTA slogans — NOT product evidence
    # (e.g. a sanitary-napkin ref carrying "#SKINTIFIC #SnailMucin ... / 15-30s /
    # Hydration music"). Reuse the evidence-quality detector to reject that junk AT
    # INGESTION so it never lands in declared evidence; the field falls through to
    # MISSING -> grounded FILL instead. Detector-driven, so it cannot drift; no
    # fabrication and product-genuine copy is untouched.
    from agent.services.registration_evidence_quality_service import (
        audit_registration_evidence,
    )
    audit = audit_registration_evidence(request, product_family=None)
    rejected = {
        field: None
        for field in ("benefits_text", "target_customer_text", "ingredients_text")
        if getattr(request, field, None)
        and audit.sanitized_fields.get(field) is None
    }
    if rejected:
        request = request.model_copy(update=rejected)
    return request


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
                recompute_state="STALE",
                recompute_reason="SOURCE_ROW_NOT_COMPUTED",
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
    recompute_state: str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    if recompute_state:
        # ``recompute_state`` is derived from the current authoritative
        # reference evidence below.  SQL can only narrow the candidate set by
        # the persisted fields; applying its state predicate here would drop
        # rows whose source changed since the last stored observation.
        candidate_rows = await crud.list_bulk_queue(
            promotion_status=promotion_status,
            claim_risk_level=claim_risk_level,
            image_readiness=image_readiness,
            recompute_state=None,
            category=category,
            q=q,
            page=1,
            page_size=None,
        )
        refs_by_id = await _current_reference_map()
        matching_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for row in candidate_rows:
            evaluation = _recompute_state_for_row(
                row,
                refs_by_id.get(row.get("reference_id"))
                or _row_reference_fallback(row),
            )
            if evaluation.get("recompute_state") == recompute_state:
                matching_rows.append((row, evaluation))

        start = (page - 1) * page_size
        page_rows = matching_rows[start : start + page_size]
        return {
            "items": [
                _attach_duplicate_metadata_to_row(row, evaluation)
                for row, evaluation in page_rows
            ],
            "total": len(matching_rows),
            "page": page,
            "page_size": page_size,
        }

    rows = await crud.list_bulk_queue(
        promotion_status=promotion_status,
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        recompute_state=recompute_state,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )
    total = await crud.count_bulk_queue(
        promotion_status=promotion_status,
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        recompute_state=recompute_state,
        category=category,
        q=q,
    )
    refs_by_id = await _current_reference_map()
    return {
        "items": [
            _attach_duplicate_metadata_to_row(
                row,
                _recompute_state_for_row(
                    row,
                    refs_by_id.get(row.get("reference_id")) or _row_reference_fallback(row),
                ),
            )
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def list_duplicate_queue(
    *,
    claim_risk_level: str | None = None,
    image_readiness: str | None = None,
    category: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    return await list_bulk_queue(
        promotion_status="DUPLICATE_SUSPECTED",
        claim_risk_level=claim_risk_level,
        image_readiness=image_readiness,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )


async def get_queue_stats() -> dict[str, Any]:
    base = await crud.get_bulk_queue_stats()
    rows = await crud.list_all_bulk_queue_rows()
    refs_by_id = await _current_reference_map()
    by_recompute_state: dict[str, int] = {}
    review_hold_count = 0
    for row in rows:
        ref = refs_by_id.get(row.get("reference_id")) or _row_reference_fallback(row)
        evaluation = _recompute_state_for_row(row, ref)
        state = str(evaluation.get("recompute_state") or "STALE")
        by_recompute_state[state] = by_recompute_state.get(state, 0) + 1
        if evaluation.get("review_hold_reason"):
            review_hold_count += 1
    return {
        **base,
        "ruleset_version": _RECOMPUTE_RULESET_VERSION,
        "by_recompute_state": by_recompute_state,
        "review_hold_count": review_hold_count,
    }


async def reconcile_queue(*, dry_run: bool = True) -> dict[str, Any]:
    """Reconcile queue metadata without changing Product Truth or approvals.

    The dry-run is the default.  Apply mode writes only additive queue
    metadata in one SQLite transaction after the caller has explicitly chosen
    ``dry_run=False`` and passed the API confirmation phrase.
    """
    rows = await crud.list_all_bulk_queue_rows()
    refs_by_id = await _current_reference_map()
    updates: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    now = _now()
    for row in rows:
        reference_id = str(row.get("reference_id") or "")
        ref = refs_by_id.get(reference_id) or _row_reference_fallback(row)
        evaluation = _recompute_state_for_row(row, ref)
        state = str(evaluation.get("recompute_state") or "STALE")
        state_counts[state] = state_counts.get(state, 0) + 1
        desired = {
            "reference_id": reference_id,
            "ruleset_version": _RECOMPUTE_RULESET_VERSION,
            "input_fingerprint": evaluation.get("input_fingerprint"),
            "computed_ruleset_version": evaluation.get("computed_ruleset_version"),
            "computed_input_fingerprint": evaluation.get("computed_input_fingerprint"),
            "recompute_state": state,
            "recompute_reason": evaluation.get("recompute_reason"),
            "review_hold_reason": evaluation.get("review_hold_reason"),
        }
        changed = any(row.get(key) != value for key, value in desired.items() if key != "reference_id")
        if changed:
            desired["updated_at"] = now
            updates.append(desired)

    applied = 0
    if not dry_run and updates:
        applied = await crud.bulk_update_bulk_queue_rows(updates)

    return {
        "dry_run": dry_run,
        "ruleset_version": _RECOMPUTE_RULESET_VERSION,
        "total": len(rows),
        "state_counts": state_counts,
        "changed": len(updates),
        "applied": applied,
        "product_truth_writes": 0,
        "provider_calls": 0,
        "rows": [
            {
                "reference_id": update["reference_id"],
                "next_state": update["recompute_state"],
                "reason": update["recompute_reason"],
            }
            for update in updates
        ],
    }


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

    # Find the live reference product to pick up enriched data.  This is an
    # exact-ID authoritative lookup, not a first-page scan.
    ref = (await _current_reference_map(reference_ids=[reference_id])).get(reference_id)
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
            reference_id,
            error_message=f"completion_failed:{e}",
            ruleset_version=_RECOMPUTE_RULESET_VERSION,
            input_fingerprint=_reference_fingerprint(ref),
            recompute_state="FAILED",
            recompute_reason=f"COMPLETION_FAILED:{e}",
            updated_at=_now(),
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
    duplicate_candidate = await _detect_queue_duplicate_candidate(
        reference_id,
        draft.declared_evidence_fields.get("product_name") or row["raw_product_title"],
        draft.declared_evidence_fields.get("tiktok_product_url"),
        ignore_product_id=_clean(row.get("duplicate_ignore_product_id")) or None,
    )
    promo_status = _classify_promotion_status(
        claim_risk,
        image_readiness,
        missing,
        duplicate_candidate is not None,
    )

    # Persist blocking reason for operator visibility
    err_msg: str | None = None
    if promo_status == "MISSING_REQUIRED_FIELD" and missing:
        err_msg = "MISSING:" + ",".join(missing[:10])
    elif promo_status == "DUPLICATE_SUSPECTED" and duplicate_candidate:
        err_msg = (
            f"DUPLICATE_CANDIDATE:{duplicate_candidate.get('id')}:{duplicate_candidate.get('match_reason')}"
        )
    elif promo_status == "CLAIM_RISK":
        claim_tokens_str = ",".join(draft.claim_tokens[:5]) if draft.claim_tokens else ""
        err_msg = f"CLAIM_RISK:{draft.claim_gate}" + (f":{claim_tokens_str}" if claim_tokens_str else "")

    recompute_state, recompute_reason = _state_after_recompute(promo_status, err_msg)

    await crud.update_bulk_queue_row(
        reference_id,
        promotion_status=promo_status,
        draft_id=saved_draft.review_draft_id,
        claim_risk_level=claim_risk,
        image_readiness=image_readiness,
        suspected_existing_product_id=duplicate_candidate.get("id") if duplicate_candidate else None,
        suspected_existing_product_title=duplicate_candidate.get("title") if duplicate_candidate else None,
        suspected_existing_product_source=duplicate_candidate.get("source") if duplicate_candidate else None,
        suspected_existing_product_mapping_source=duplicate_candidate.get("mapping_source") if duplicate_candidate else None,
        duplicate_match_reason=duplicate_candidate.get("match_reason") if duplicate_candidate else None,
        error_message=err_msg,
        recomputed_at=_now(),
        ruleset_version=_RECOMPUTE_RULESET_VERSION,
        input_fingerprint=_reference_fingerprint(ref),
        computed_ruleset_version=_RECOMPUTE_RULESET_VERSION,
        computed_input_fingerprint=_reference_fingerprint(ref),
        recompute_state=recompute_state,
        recompute_reason=recompute_reason,
        review_hold_reason=recompute_reason if recompute_state == "BLOCKED_REVIEW_REQUIRED" else None,
        updated_at=_now(),
    )

    return {
        "reference_id": reference_id,
        "draft_id": saved_draft.review_draft_id,
        "promotion_status": promo_status,
        "claim_risk_level": claim_risk,
        "image_readiness": image_readiness,
        "duplicate_candidate": duplicate_candidate,
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
            row = await crud.get_bulk_queue_row(ref_id)
            if not row:
                failed += 1
                results.append({
                    "reference_id": ref_id,
                    "status": "ERROR",
                    "error": "REFERENCE_NOT_IN_QUEUE",
                })
                continue
            if row.get("promotion_status") != "PENDING_DRAFT":
                failed += 1
                results.append({
                    "reference_id": ref_id,
                    "status": "ERROR",
                    "error": (
                        "MISSING_EVIDENCE_REVIEW_REQUIRED"
                        if row.get("promotion_status") == "MISSING_REQUIRED_FIELD"
                        else f"STATUS_NOT_PENDING_DRAFT:{row.get('promotion_status')}"
                    ),
                })
                continue
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
                recompute_state="UP_TO_DATE",
                recompute_reason="APPROVED_ROW_COMMITTED_AFTER_HUMAN_GATE",
                review_hold_reason=None,
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


async def recompute_selected(
    reference_ids: list[str],
    *,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """
    Re-run smart mapping only for rows whose authoritative input/ruleset is
    ``STALE``.  A current missing-evidence result is a review/add-evidence
    path; a later authoritative input change reopens it as STALE so the new
    evidence can be evaluated.  ``retry_failed`` is the explicit controlled
    retry gate.

    Governance:
    - never creates Product Truth
    - never approves rows
    - preserves FastMoss reference lineage via create_draft_from_reference
    """
    results: list[dict[str, Any]] = []
    recomputed = 0
    ready_for_approval = 0
    missing_required_field = 0
    blocked_missing_evidence = 0
    claim_risk = 0
    duplicate_suspected = 0
    image_missing = 0
    failed = 0
    skipped = 0

    refs_by_id = await _current_reference_map(reference_ids=reference_ids)
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
        ref = refs_by_id.get(ref_id) or _row_reference_fallback(row)
        evaluation = _recompute_state_for_row(row, ref)
        current_state = evaluation.get("recompute_state")
        can_retry = retry_failed and current_state == "FAILED"
        if current_state != "STALE" and not can_retry:
            skipped += 1
            if current_state == "BLOCKED_MISSING_EVIDENCE":
                blocked_missing_evidence += 1
            skip_error = {
                "BLOCKED_MISSING_EVIDENCE": "BLOCKED_MISSING_EVIDENCE_REVIEW_REQUIRED",
                "BLOCKED_REVIEW_REQUIRED": "REVIEW_REQUIRED_NOT_RECOMPUTED",
                "FAILED": "FAILED_RETRY_REQUIRED",
                "UP_TO_DATE": "ROW_ALREADY_UP_TO_DATE",
            }.get(
                str(current_state),
                f"STATE_NOT_ELIGIBLE_FOR_RECOMPUTE:{current_state or 'UNKNOWN'}",
            )
            results.append({
                "reference_id": ref_id,
                "previous_status": previous_status,
                "new_status": previous_status,
                "previous_error_message": previous_error_message,
                "new_error_message": previous_error_message,
                "draft_id": row.get("draft_id"),
                "outcome": "SKIPPED",
                "error": skip_error,
            })
            continue

        attempt_count = int(row.get("recompute_attempt_count") or 0) + 1
        await crud.update_bulk_queue_row(
            ref_id,
            recompute_state="QUEUED",
            recompute_reason="RECOMPUTE_QUEUED",
            recompute_started_at=now,
            recompute_attempt_count=attempt_count,
            updated_at=now,
        )
        await crud.update_bulk_queue_row(
            ref_id,
            recompute_state="RECOMPUTING",
            recompute_reason="RECOMPUTE_IN_PROGRESS",
            updated_at=_now(),
        )

        try:
            result = await create_draft_from_reference(ref_id)
        except Exception as e:
            failed += 1
            await crud.update_bulk_queue_row(
                ref_id,
                recomputed_at=now,
                recompute_previous_status=previous_status,
                recompute_previous_error=previous_error_message,
                ruleset_version=_RECOMPUTE_RULESET_VERSION,
                input_fingerprint=_reference_fingerprint(ref),
                recompute_state="FAILED",
                recompute_reason=f"RECOMPUTE_FAILED:{e}",
                error_message=f"RECOMPUTE_FAILED:{e}",
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
        new_state, state_reason = _state_after_recompute(new_status, new_error_message)
        recompute_update: dict[str, Any] = {
            "recomputed_at": now,
            "recompute_previous_status": previous_status,
            "recompute_previous_error": previous_error_message,
            "ruleset_version": _RECOMPUTE_RULESET_VERSION,
            "input_fingerprint": _reference_fingerprint(ref),
            "recompute_state": "FAILED" if "error" in result else new_state,
            "recompute_reason": (
                f"RECOMPUTE_FAILED:{result.get('error')}"
                if "error" in result
                else state_reason
            ),
            "review_hold_reason": (
                state_reason if new_state == "BLOCKED_REVIEW_REQUIRED" else None
            ),
            "updated_at": now,
        }
        if "error" not in result:
            recompute_update.update(
                computed_ruleset_version=_RECOMPUTE_RULESET_VERSION,
                computed_input_fingerprint=_reference_fingerprint(ref),
            )

        await crud.update_bulk_queue_row(
            ref_id,
            **recompute_update,
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
            blocked_missing_evidence += 1
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
        "blocked_missing_evidence": blocked_missing_evidence,
        "claim_risk": claim_risk,
        "duplicate_suspected": duplicate_suspected,
        "image_missing": image_missing,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


_ENRICHMENT_EXPORT_FIELDS = [
    "reference_id",
    "draft_id",
    "raw_product_title",
    "category",
    "tiktok_product_url",
    "source_url",
    "image_url",
    "sold_count",
    "commission_rate",
    "missing_fields",
    "product_knowledge_text",
    "benefits_text",
    "usage_text",
    "target_customer_text",
    "ingredients_text",
    "warnings_text",
]


async def export_missing_as_csv() -> str:
    rows = await crud.list_bulk_queue(
        promotion_status="MISSING_REQUIRED_FIELD",
        page_size=2000,
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=_ENRICHMENT_EXPORT_FIELDS,
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        error_message = row.get("error_message") or ""
        missing_fields = (
            error_message[8:] if error_message.startswith("MISSING:") else error_message
        )
        writer.writerow(
            {
                "reference_id": row.get("reference_id", ""),
                "draft_id": row.get("draft_id") or "",
                "raw_product_title": row.get("raw_product_title", ""),
                "category": row.get("category") or "",
                "tiktok_product_url": row.get("tiktok_product_url") or "",
                "source_url": row.get("source_url") or "",
                "image_url": row.get("image_url") or "",
                "sold_count": row.get("sold_count") or "",
                "commission_rate": row.get("commission_rate") or "",
                "missing_fields": missing_fields,
                "product_knowledge_text": "",
                "benefits_text": "",
                "usage_text": "",
                "target_customer_text": "",
                "ingredients_text": "",
                "warnings_text": "",
            }
        )
    return output.getvalue()


async def import_enrichment(items: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    recomputed = 0
    skipped = 0
    failed = 0
    now = _now()

    refs_by_id = await _current_reference_map()

    for item in items:
        reference_id = str(item.get("reference_id") or "").strip()
        if not reference_id:
            skipped += 1
            results.append(
                {
                    "reference_id": reference_id,
                    "outcome": "SKIPPED",
                    "error": "MISSING_REFERENCE_ID",
                }
            )
            continue

        row = await crud.get_bulk_queue_row(reference_id)
        if not row:
            skipped += 1
            results.append(
                {
                    "reference_id": reference_id,
                    "outcome": "SKIPPED",
                    "error": "NOT_IN_QUEUE",
                }
            )
            continue

        def _s(key: str) -> str | None:
            value = str(item.get(key) or "").strip()
            return value or None

        raw_title = _clean(row.get("raw_product_title")) or ""
        category = _clean(row.get("category")) or None
        commission_rate = _clean(row.get("commission_rate")) or None
        sold_count = row.get("sold_count")
        ref = refs_by_id.get(reference_id) or {
            "id": reference_id,
            "raw_product_title": raw_title,
        }

        knowledge_parts = [f"Product: {raw_title}"] if raw_title else []
        if category:
            knowledge_parts.append(f"Category: {category}")
        if sold_count:
            knowledge_parts.append(f"Sold count: {sold_count}")
        if commission_rate:
            knowledge_parts.append(f"Commission: {commission_rate}")
        base_knowledge = " | ".join(knowledge_parts) or None
        extra_knowledge = _s("product_knowledge_text")
        if base_knowledge and extra_knowledge:
            paste_knowledge = base_knowledge + "\n\n" + extra_knowledge
        elif extra_knowledge:
            paste_knowledge = extra_knowledge
        else:
            paste_knowledge = base_knowledge

        item_price_raw = item.get("price")
        item_price: float | None = None
        if item_price_raw is not None:
            try:
                item_price = float(item_price_raw)
            except (TypeError, ValueError):
                item_price = None
        ref_price = ref.get("price")
        resolved_price = item_price if item_price is not None else ref_price

        completion_request = ProductKnowledgeCompleteRequest(
            product_name=raw_title or None,
            source_lane="FASTMOSS_PROMOTED",
            paste_anything_about_product=paste_knowledge,
            category=category,
            image_url=_clean(row.get("image_url")) or None,
            source_url=_clean(row.get("source_url")) or None,
            tiktok_product_url=_clean(row.get("tiktok_product_url")) or None,
            commission_rate=commission_rate,
            price=resolved_price,
            currency=row.get("currency") or ref.get("currency") or "MYR",
            benefits_text=_s("benefits_text"),
            usage_text=_s("usage_text"),
            target_customer_text=_s("target_customer_text"),
            ingredients_text=_s("ingredients_text"),
            warnings_text=_s("warnings_text"),
        )

        try:
            completion = await asyncio.to_thread(
                complete_product_knowledge,
                completion_request,
            )
            draft = create_registration_review_draft(completion)
            draft = _apply_lineage_to_draft(draft, ref, reference_id)
            draft.last_recomputed_at = now
            draft.draft_freshness_status = "FRESH"

            image_status, image_detail = derive_draft_image_asset_state(
                draft.declared_evidence_fields
            )
            draft.image_asset_status = image_status
            draft.image_asset_detail = image_detail

            if draft.declared_evidence_fields.get("product_name"):
                draft.approval_checklist["normalized_name"] = True

            saved_draft = RegistrationDraftStorageService.save_draft(draft)
            image_readiness = _derive_image_readiness(
                draft.declared_evidence_fields.get("image_url")
            )
            claim_risk = draft.claim_risk_level or "HIGH"
            missing = list(draft.missing_required_evidence or [])
            duplicate_candidate = await _detect_queue_duplicate_candidate(
                reference_id,
                draft.declared_evidence_fields.get("product_name") or raw_title,
                draft.declared_evidence_fields.get("tiktok_product_url"),
                ignore_product_id=_clean(row.get("duplicate_ignore_product_id")) or None,
            )
            promotion_status = _classify_promotion_status(
                claim_risk,
                image_readiness,
                missing,
                duplicate_candidate is not None,
            )

            error_message: str | None = None
            if promotion_status == "MISSING_REQUIRED_FIELD" and missing:
                error_message = "MISSING:" + ",".join(missing[:10])
            elif promotion_status == "DUPLICATE_SUSPECTED" and duplicate_candidate:
                error_message = (
                    "DUPLICATE_CANDIDATE:"
                    f"{duplicate_candidate.get('id')}:{duplicate_candidate.get('match_reason')}"
                )
            elif promotion_status == "CLAIM_RISK":
                claim_tokens_str = (
                    ",".join(draft.claim_tokens[:5]) if draft.claim_tokens else ""
                )
                error_message = f"CLAIM_RISK:{draft.claim_gate}"
                if claim_tokens_str:
                    error_message += f":{claim_tokens_str}"

            recompute_state, recompute_reason = _state_after_recompute(
                promotion_status,
                error_message,
            )

            await crud.update_bulk_queue_row(
                reference_id,
                promotion_status=promotion_status,
                draft_id=saved_draft.review_draft_id,
                claim_risk_level=claim_risk,
                image_readiness=image_readiness,
                error_message=error_message,
                recomputed_at=now,
                ruleset_version=_RECOMPUTE_RULESET_VERSION,
                input_fingerprint=_reference_fingerprint(ref),
                computed_ruleset_version=_RECOMPUTE_RULESET_VERSION,
                computed_input_fingerprint=_reference_fingerprint(ref),
                recompute_state=recompute_state,
                recompute_reason=recompute_reason,
                review_hold_reason=(
                    recompute_reason
                    if recompute_state == "BLOCKED_REVIEW_REQUIRED"
                    else None
                ),
                updated_at=now,
            )
            recomputed += 1
            results.append(
                {
                    "reference_id": reference_id,
                    "outcome": "OK",
                    "new_status": promotion_status,
                    "draft_id": saved_draft.review_draft_id,
                    "error": None,
                }
            )
        except Exception as exc:
            failed += 1
            logger.exception("import_enrichment failed for %s: %s", reference_id, exc)
            results.append(
                {
                    "reference_id": reference_id,
                    "outcome": "ERROR",
                    "new_status": None,
                    "error": str(exc),
                }
            )

    return {
        "total": len(items),
        "recomputed": recomputed,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


async def resolve_duplicate_queue_row(
    reference_id: str,
    *,
    action: str,
    linked_product_id: str | None = None,
    confirmation_phrase: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if action not in _DUPLICATE_REVIEW_ACTIONS:
        return {
            "error": f"INVALID_DUPLICATE_ACTION:{action}",
            "reference_id": reference_id,
        }

    row = await crud.get_bulk_queue_row(reference_id)
    if not row:
        return {"error": "NOT_IN_QUEUE", "reference_id": reference_id}

    previous_status = str(row.get("promotion_status") or "")
    claim_risk_level = str(row.get("claim_risk_level") or "")
    now = _now()

    if action == "LINK_TO_EXISTING_PRODUCT":
        if previous_status != "DUPLICATE_SUSPECTED":
            return {
                "error": f"DUPLICATE_REVIEW_NOT_ALLOWED_FOR_STATUS:{previous_status or 'UNKNOWN'}",
                "reference_id": reference_id,
            }
        if claim_risk_level == "HIGH":
            return {
                "error": "CLAIM_RISK_DUPLICATE_CANNOT_LINK",
                "reference_id": reference_id,
            }
        linked_product_id = _clean(linked_product_id)
        if not linked_product_id:
            return {"error": "LINKED_PRODUCT_ID_REQUIRED", "reference_id": reference_id}
        linked_product = await crud.get_product(linked_product_id)
        if not linked_product:
            return {"error": "LINKED_PRODUCT_NOT_FOUND", "reference_id": reference_id}
        if not _product_row_is_canonical_truth(linked_product):
            return {"error": "LINKED_PRODUCT_MUST_BE_CANONICAL_PRODUCT_TRUTH", "reference_id": reference_id}
        await crud.update_bulk_queue_row(
            reference_id,
            promotion_status="DUPLICATE_LINKED",
            linked_product_id=linked_product_id,
            linked_product_title=linked_product.get("product_display_name")
            or linked_product.get("product_short_name")
            or linked_product.get("raw_product_title"),
            duplicate_resolution="LINKED_TO_EXISTING_PRODUCT",
            duplicate_resolved_at=now,
            duplicate_resolution_note=note,
            updated_at=now,
        )
    elif action == "MARK_FALSE_DUPLICATE":
        if previous_status != "DUPLICATE_SUSPECTED":
            return {
                "error": f"DUPLICATE_REVIEW_NOT_ALLOWED_FOR_STATUS:{previous_status or 'UNKNOWN'}",
                "reference_id": reference_id,
            }
        if confirmation_phrase != _CLEAR_DUPLICATE_PHRASE:
            return {"error": "INVALID_FALSE_DUPLICATE_CONFIRMATION_PHRASE", "reference_id": reference_id}
        await crud.update_bulk_queue_row(
            reference_id,
            duplicate_ignore_product_id=_clean(row.get("suspected_existing_product_id")) or None,
            duplicate_resolution="FALSE_DUPLICATE_UNDER_REVIEW",
            duplicate_resolved_at=now,
            duplicate_resolution_note=note,
            linked_product_id=None,
            linked_product_title=None,
            updated_at=now,
        )
        recompute_result = await create_draft_from_reference(reference_id)
        if "error" in recompute_result:
            return {
                "reference_id": reference_id,
                "action": action,
                "previous_status": previous_status,
                "new_status": (await crud.get_bulk_queue_row(reference_id) or row).get("promotion_status"),
                "linked_product_id": None,
                "duplicate_resolution": "FALSE_DUPLICATE_RECOMPUTE_FAILED",
                "content_generation_allowed": False,
                "message": recompute_result["error"],
            }
        post_row = await crud.get_bulk_queue_row(reference_id) or row
        await crud.update_bulk_queue_row(
            reference_id,
            duplicate_resolution=(
                "FALSE_DUPLICATE_CLEARED"
                if post_row.get("promotion_status") != "DUPLICATE_SUSPECTED"
                else "FALSE_DUPLICATE_STILL_BLOCKED"
            ),
            duplicate_resolved_at=now,
            duplicate_resolution_note=note,
            updated_at=now,
        )
    elif action == "KEEP_BLOCKED":
        if previous_status != "DUPLICATE_SUSPECTED":
            return {
                "error": f"DUPLICATE_REVIEW_NOT_ALLOWED_FOR_STATUS:{previous_status or 'UNKNOWN'}",
                "reference_id": reference_id,
            }
        await crud.update_bulk_queue_row(
            reference_id,
            promotion_status="DUPLICATE_SUSPECTED",
            duplicate_resolution="KEEP_BLOCKED",
            duplicate_resolved_at=now,
            duplicate_resolution_note=note,
            updated_at=now,
        )
    elif action == "REJECT_REFERENCE":
        if previous_status != "DUPLICATE_SUSPECTED":
            return {
                "error": f"DUPLICATE_REVIEW_NOT_ALLOWED_FOR_STATUS:{previous_status or 'UNKNOWN'}",
                "reference_id": reference_id,
            }
        await crud.update_bulk_queue_row(
            reference_id,
            promotion_status="REJECTED",
            duplicate_resolution="REJECT_REFERENCE",
            duplicate_resolved_at=now,
            duplicate_resolution_note=note,
            updated_at=now,
        )

    updated_row = await crud.get_bulk_queue_row(reference_id) or row
    policy = await can_generate_content_for_fastmoss_reference(reference_id)
    return {
        "reference_id": reference_id,
        "action": action,
        "previous_status": previous_status,
        "new_status": updated_row.get("promotion_status"),
        "linked_product_id": updated_row.get("linked_product_id"),
        "duplicate_resolution": updated_row.get("duplicate_resolution"),
        "content_generation_allowed": policy["content_generation_allowed"],
        "message": policy["reason"],
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
        reference_id,
        promotion_status=promotion_status,
        recompute_state=(
            "BLOCKED_MISSING_EVIDENCE"
            if promotion_status == "MISSING_REQUIRED_FIELD"
            else "STALE"
        ),
        recompute_reason=(
            "MANUAL_MISSING_EVIDENCE_REVIEW_REQUIRED"
            if promotion_status == "MISSING_REQUIRED_FIELD"
            else "MANUAL_STATUS_UPDATE_REQUIRES_RECOMPUTE"
        ),
        review_hold_reason=None,
        updated_at=_now(),
    )
    return updated or {"reference_id": reference_id, "promotion_status": promotion_status}


async def sync_queue_row_from_draft(draft: Any) -> dict[str, Any] | None:
    """Re-evaluate the linked FastMoss queue row's status FROM A SAVED DRAFT.

    When an operator edits a draft's evidence (review/add, save-draft, analyze &
    repair), the draft is persisted but the queue row the list renders is written
    only by the HUB promotion/recompute path — so the row went stale and kept
    showing e.g. ``MISSING:SIZE_OR_VOLUME_EVIDENCE`` after the field was filled, and
    a routine recompute would REBUILD the draft from HUB and clobber the edit.

    This syncs the row from the *saved draft itself* using the same classifier the
    recompute uses (``_classify_promotion_status`` / ``_state_after_recompute``) —
    never a HUB rebuild — so filling a field clears the list warning immediately and
    the operator edit is authoritative. Returns the updated row, or None when the
    draft has no linked queue row (non-FastMoss lane). Best-effort: callers should
    not fail the save if this raises.
    """
    draft_id = _clean(getattr(draft, "review_draft_id", ""))
    if not draft_id:
        return None
    row = await crud.get_bulk_queue_row_by_draft_id(draft_id)
    if not row:
        return None
    ref_id = _clean(row.get("reference_id"))
    dec = getattr(draft, "declared_evidence_fields", None) or {}
    claim_risk = _clean(getattr(draft, "claim_risk_level", "")) or "HIGH"
    missing = list(getattr(draft, "missing_required_evidence", None) or [])
    image_readiness = _derive_image_readiness(dec.get("image_url"))
    duplicate_candidate = await _detect_queue_duplicate_candidate(
        ref_id,
        _clean(dec.get("product_name")) or _clean(row.get("raw_product_title")),
        dec.get("tiktok_product_url"),
        ignore_product_id=_clean(row.get("duplicate_ignore_product_id")) or None,
    )
    promotion_status = _classify_promotion_status(
        claim_risk, image_readiness, missing, duplicate_candidate is not None
    )
    error_message: str | None = None
    if promotion_status == "MISSING_REQUIRED_FIELD" and missing:
        error_message = "MISSING:" + ",".join(missing[:10])
    elif promotion_status == "DUPLICATE_SUSPECTED" and duplicate_candidate:
        error_message = (
            "DUPLICATE_CANDIDATE:"
            f"{duplicate_candidate.get('id')}:{duplicate_candidate.get('match_reason')}"
        )
    elif promotion_status == "CLAIM_RISK":
        tokens = ",".join((getattr(draft, "claim_tokens", None) or [])[:5])
        error_message = f"CLAIM_RISK:{_clean(getattr(draft, 'claim_gate', ''))}"
        if tokens:
            error_message += f":{tokens}"
    recompute_state, recompute_reason = _state_after_recompute(promotion_status, error_message)
    now = _now()
    updated = await crud.update_bulk_queue_row(
        ref_id,
        promotion_status=promotion_status,
        claim_risk_level=claim_risk,
        image_readiness=image_readiness,
        error_message=error_message,
        recompute_state=recompute_state,
        recompute_reason=recompute_reason,
        review_hold_reason=(
            recompute_reason if recompute_state == "BLOCKED_REVIEW_REQUIRED" else None
        ),
        recomputed_at=now,
        updated_at=now,
    )
    return updated
