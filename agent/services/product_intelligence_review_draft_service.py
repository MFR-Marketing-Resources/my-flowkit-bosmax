from __future__ import annotations

import hashlib as _hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceFieldDispositionRequest,
    ProductIntelligenceReviewDraft,
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewDraftListResponse,
    ProductIntelligenceReviewDraftRejectRequest,
    ProductIntelligenceReviewDraftUpdateRequest,
    ProductIntelligenceReviewDraftValidationResponse,
    ProductIntelligenceReviewFieldProvenance,
    ProductIntelligenceReviewFieldProvenanceInput,
    ReviewDraftStatus,
)
from agent.models.product_intelligence_snapshot import ProductIntelligenceSnapshot
from agent.services import copy_angle_derivation
from agent.services.product_intelligence_claim_safety_service import (
    evaluate_claim_safety,
)
from agent.services.product_intelligence_draft_lifecycle import (
    TERMINAL_REVIEW_STATUSES,
)


REQUIRED_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "source_urls_json",
    "image_evidence_json",
    "claim_gate",
    "claim_risk_level",
)

# The subset of REQUIRED_FIELDS that copy generation actually consumes: the
# persona, the angle strategy, positioning (benefits/usp/description/audience)
# and the claim gate. The remaining REQUIRED_FIELDS are product KNOWLEDGE
# (ingredients/usage/warnings) or provenance — they enrich the record but are
# NOT copy inputs. approve_review_draft(allow_incomplete_product_knowledge=True)
# gates only on this subset so a draft with a complete persona/angle set can be
# approved for copy grounding while product knowledge stays open. Claim safety
# is enforced separately (CLAIM_BLOCKED / CLAIM_REVIEW_REQUIRED) and is never
# bypassed by this.
COPY_GROUNDING_REQUIRED_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "target_customer_text",
    # The copy-specific incomplete-knowledge mechanism may relax product knowledge,
    # never the explicit boundary that says which claims the copy may make.
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "claim_gate",
    "claim_risk_level",
)

JSON_LIST_FIELDS = (
    "benefits_json",
    "usp_json",
    "claim_tokens_json",
    "allowed_claims_json",
    "blocked_claims_json",
)
JSON_DICT_FIELDS = (
    "source_urls_json",
    "image_evidence_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
TEXT_FIELDS = (
    "product_description",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "reviewer_note",
    "created_by",
    "reviewed_by",
    "approved_by",
    "approved_at",
    "rejected_by",
    "rejected_at",
    "claim_gate",
    "claim_risk_level",
    "readiness_status",
)
PROVENANCE_AUTO_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "source_urls_json",
    "image_evidence_json",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "allowed_claims_json",
    "blocked_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
MEANINGFUL_CONTENT_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
# One lifecycle authority. SUPERSEDED is terminal evidence, not an open draft that may
# be edited, dispositioned, rejected, approved, or reused by angle expansion.
TERMINAL_STATUSES = TERMINAL_REVIEW_STATUSES

# ── Mission-08D: governed field absence ──────────────────────────────────────
# A required field the source genuinely does not state must not deadlock approval
# forever — and it must not be "fixed" by typing N/A into the value column, which every
# downstream reader (claim scan, copy grounding, KPI) would mistake for real knowledge.
# The governed answer is a field-scoped provenance row on the CURRENT draft:
#   evidence_kind = FIELD_ABSENCE_DISPOSITION
#   verification_status = the disposition itself
#   reviewer_decision / reviewer_note / timestamps = the accountability trail
# Provenance rows already survive draft saves (they round-trip through
# `provenance_items`) and are copied into the snapshot at approval, so the decision has
# lineage for free — no schema change, no new table.
DISPOSITION_EVIDENCE_KIND = "FIELD_ABSENCE_DISPOSITION"
DISPOSITION_NOT_STATED = "NOT_STATED_IN_SOURCE"
DISPOSITION_NOT_APPLICABLE = "NOT_APPLICABLE"
DISPOSITION_EXTERNAL = "REQUIRES_EXTERNAL_EVIDENCE"
# PI-11: the live source cannot be acquired at all (TikTok automation externally blocked).
# A truthful SUPPLY gap that satisfies the field blocker as a governed absence — like
# NOT_STATED_IN_SOURCE, but it never claims a source was inspected.
DISPOSITION_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
FIELD_ABSENCE_DISPOSITIONS = (
    DISPOSITION_NOT_STATED, DISPOSITION_NOT_APPLICABLE, DISPOSITION_EXTERNAL,
    DISPOSITION_SOURCE_UNAVAILABLE,
)
# Only product-KNOWLEDGE requirements may be dispositioned. Copy-critical fields stay
# hard-required (they are what copy grounds on), and `allowed_claims_json` is locked by
# owner decision: a claims boundary is authored by a reviewer, never waived as absent.
DISPOSITION_ELIGIBLE_FIELDS = ("ingredients_text", "warnings_text", "usage_text")

# The readiness a draft/snapshot carries when every remaining required-field gap is
# covered by a valid disposition. Deliberately a DIFFERENT value from
# READY_FOR_APPROVAL: reporting must be able to tell "complete" from "governed absence"
# forever, including inside the frozen snapshot.
READINESS_GOVERNED_ABSENCE = "READY_WITH_GOVERNED_ABSENCE"

# Category matrix for NOT_APPLICABLE, fail-closed. NA is allowed ONLY when the
# product's category clearly matches a reviewer-confirmable family; every unknown,
# empty, chemical-bearing, ingestible, child-related or body-contact category stays
# strict (NA rejected server-side; NOT_STATED_IN_SOURCE remains available there
# because documenting absence is always truthful).
_NA_CONFIRMABLE_CATEGORY_RE = re.compile(
    r"(?i)\b(?:apparel|clothing|textile|fashion|jersi|jersey|muslimah|stationery|"
    r"office|gift|kad|card|bag|luggage|electronic|gadget|phone|computer|"
    r"tools?|equipment|hardware|furniture|decoration|ornament)\b")
# Explicit strict override: if any of these appear, NA is refused even when a
# confirmable word also matches ("children's apparel", "toy tool set").
_NA_STRICT_OVERRIDE_RE = re.compile(
    r"(?i)\b(?:food|beverages?|supplements?|vitamins?|ingest\w*|edibles?|snacks?|beauty|"
    r"skincare|cosmetics?|personal\s*care|wellness|herbals?|health|medic(?:al|ine)?|"
    r"pharma|baby|infants?|kids?|child(?:ren)?|toys?|chemical|cleaner|cleaning|coating|"
    r"detergent|pesticide|automotive|motorcycle|home\s*supplies)\b")


def na_allowed_for_category(category: str | None) -> bool:
    text = str(category or "").strip()
    if not text:
        return False  # unknown category -> strict
    if _NA_STRICT_OVERRIDE_RE.search(text):
        return False
    return bool(_NA_CONFIRMABLE_CATEGORY_RE.search(text))


# Placeholder strings must never masquerade as product knowledge. This guards the
# REQUIRED-field check only (a description legitimately containing "N/A" mid-sentence is
# untouched — the guard fires only when the WHOLE value is a placeholder token).
_PLACEHOLDER_TOKENS = frozenset({
    "n/a", "na", "n.a.", "none", "nil", "-", "--", "tbd", "unknown", "not available",
    "not_available", "not stated", "not_stated", "not_stated_in_source",
    "not applicable", "not_applicable", "requires_external_evidence", "tiada",
    "tidak dinyatakan", "tidak berkenaan",
})


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _PLACEHOLDER_TOKENS


def _required_field_present(value: Any) -> bool:
    return _has_value(value) and not _is_placeholder(value)


def _dispositions_from_items(items: Any) -> dict[str, dict[str, Any]]:
    """field_name -> the disposition row (as attribute-bag/dict), latest wins."""
    out: dict[str, dict[str, Any]] = {}
    for item in items or []:
        kind = getattr(item, "evidence_kind", None) or (
            item.get("evidence_kind") if isinstance(item, dict) else None)
        if kind != DISPOSITION_EVIDENCE_KIND:
            continue
        get = item.get if isinstance(item, dict) else lambda k, _i=item: getattr(_i, k, None)
        out[str(get("field_name"))] = {
            "disposition": str(get("verification_status") or ""),
            "reviewed_by": get("reviewer_decision"),
            "reviewer_note": get("reviewer_note"),
        }
    return out


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_json_field(
    raw: Any,
    *,
    default: list[Any] | dict[str, Any],
    expected_type: type[list] | type[dict],
) -> list[Any] | dict[str, Any]:
    fallback = deepcopy(default)
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, expected_type):
        return raw
    if not isinstance(raw, str):
        return fallback
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, expected_type) else fallback


def _serialize_json(value: Any, fallback: list[Any] | dict[str, Any]) -> str:
    return json.dumps(value if value is not None else fallback)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {
            str(key): item
            for key, item in value.items()
            if _has_value(item)
        }
    return {}


def _stringify_value(value: Any) -> str | None:
    if not _has_value(value):
        return None
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True)


def _row_to_provenance(row: dict[str, Any]) -> ProductIntelligenceReviewFieldProvenance:
    return ProductIntelligenceReviewFieldProvenance.model_validate(row)


def _row_to_draft(
    row: dict[str, Any],
    *,
    provenance_items: list[ProductIntelligenceReviewFieldProvenance] | None = None,
) -> ProductIntelligenceReviewDraft:
    payload = dict(row)
    payload["benefits_json"] = _parse_json_field(
        payload.get("benefits_json"),
        default=[],
        expected_type=list,
    )
    payload["usp_json"] = _parse_json_field(
        payload.get("usp_json"),
        default=[],
        expected_type=list,
    )
    payload["source_urls_json"] = _parse_json_field(
        payload.get("source_urls_json"),
        default={},
        expected_type=dict,
    )
    payload["image_evidence_json"] = _parse_json_field(
        payload.get("image_evidence_json"),
        default={},
        expected_type=dict,
    )
    payload["claim_tokens_json"] = _parse_json_field(
        payload.get("claim_tokens_json"),
        default=[],
        expected_type=list,
    )
    payload["allowed_claims_json"] = _parse_json_field(
        payload.get("allowed_claims_json"),
        default=[],
        expected_type=list,
    )
    payload["blocked_claims_json"] = _parse_json_field(
        payload.get("blocked_claims_json"),
        default=[],
        expected_type=list,
    )
    payload["buyer_persona_snapshot_json"] = _parse_json_field(
        payload.get("buyer_persona_snapshot_json"),
        default={},
        expected_type=dict,
    )
    payload["copy_strategy_summary_json"] = _parse_json_field(
        payload.get("copy_strategy_summary_json"),
        default={},
        expected_type=dict,
    )
    payload["provenance_items"] = provenance_items or []
    return ProductIntelligenceReviewDraft.model_validate(payload)


async def _load_provenance_for_draft(
    draft_id: str,
) -> list[ProductIntelligenceReviewFieldProvenance]:
    rows = await crud.list_product_intelligence_review_field_provenance(draft_id=draft_id)
    return [_row_to_provenance(row) for row in rows]


async def _get_product_or_raise(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    return product


async def _get_draft_row_or_raise(draft_id: str) -> dict[str, Any]:
    row = await crud.get_product_intelligence_review_draft(draft_id)
    if not row:
        raise ValueError("DRAFT_NOT_FOUND")
    return row


def _seed_payload_from_product(product: dict[str, Any]) -> dict[str, Any]:
    # Image evidence from the product record.
    image_evidence_json: dict[str, Any] = {}
    if _has_value(product.get("image_url")):
        image_evidence_json["image_url"] = product["image_url"]
    if _has_value(product.get("local_image_path")):
        image_evidence_json["local_image_path"] = product["local_image_path"]
    image_evidence_available = bool(image_evidence_json)

    # Source provenance. Prefer a real external URL; otherwise auto-record the internal
    # product record as provenance so a MANUAL product (no external URL) is never left
    # with an empty required field it cannot legitimately fill by hand. source_urls_json
    # is required by the approval gate and MUST NOT be empty when the product row exists.
    source_urls_json: dict[str, Any] = {}
    if _has_value(product.get("source_url")):
        source_urls_json["source_url"] = product["source_url"]
    if _has_value(product.get("tiktok_product_url")):
        source_urls_json["tiktok_product_url"] = product["tiktok_product_url"]
    if not source_urls_json:
        product_name = (
            str(
                product.get("product_display_name")
                or product.get("product_short_name")
                or product.get("raw_product_title")
                or ""
            ).strip()
            or None
        )
        source_urls_json = {
            "source_type": "MANUAL_PRODUCT_RECORD",
            "product_id": product.get("id"),
            "product_name": product_name,
            "local_image_path": product.get("local_image_path") or None,
            "image_evidence_available": image_evidence_available,
        }

    return {
        "source_urls_json": source_urls_json,
        "image_evidence_json": image_evidence_json,
        "claim_risk_level": str(product.get("claim_risk_level") or "").strip() or None,
    }


def _normalize_mutation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for field_name in JSON_LIST_FIELDS:
        if field_name in normalized:
            normalized[field_name] = _normalize_list(normalized[field_name])
    for field_name in JSON_DICT_FIELDS:
        if field_name in normalized:
            normalized[field_name] = _normalize_dict(normalized[field_name])
    for field_name in TEXT_FIELDS:
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if value is None:
            continue
        normalized[field_name] = str(value).strip() or None
    return normalized


def _apply_derived_angles(payload: dict[str, Any]) -> dict[str, Any]:
    """Phase A2 — fill `copy_strategy_summary_json.angles` from THIS product's
    approved persona instead of leaving it for the framework family default.

    Background: the field is a pass-through, and nothing ever derived its
    angles, so every product inherited a generic family template (measured
    2026-07-24: 30/30 approved snapshots, 7 templates, 0 product-specific).
    The copy generator rotates whatever is here, so a wrong axis yields a
    correct-looking rotation over irrelevant labels.

    Two invariants:

    * NON-DESTRUCTIVE — an explicitly supplied `angles` list is never
      overwritten. Operator/caller intent wins.
    * FAIL-CLOSED — an underivable persona leaves the field untouched, so the
      reader keeps today's framework-family fallback. Never invents an angle.

    `angles` holds the human-readable pain text because it is injected into the
    LLM brief verbatim as `target_angle_strategy`; a hash there would be worse
    than the generic label it replaces. The structured records (stable
    `angle_key`, audience, conflict flag) go alongside in `angle_registry`,
    which Phase B keys its component pool on.
    """
    strategy = payload.get("copy_strategy_summary_json")
    strategy = dict(strategy) if isinstance(strategy, dict) else {}
    if strategy.get("angles"):
        return payload

    derivation = copy_angle_derivation.derive_angles(
        payload.get("buyer_persona_snapshot_json")
    )
    if not derivation.get("derived"):
        return payload

    angles = derivation["angles"]
    strategy["angles"] = [a["label"] for a in angles]
    strategy["angle_registry"] = [
        {
            "angle_key": a["angle_key"],
            "label": a["label"],
            "audience": a["audience"],
            "audience_conflict": a["audience_conflict"],
        }
        for a in angles
    ]
    strategy["angle_source"] = "DERIVED_FROM_APPROVED_PERSONA"
    if derivation.get("warnings"):
        strategy["angle_warnings"] = list(derivation["warnings"])

    updated = dict(payload)
    updated["copy_strategy_summary_json"] = strategy
    return updated


def _build_auto_provenance_items(
    *,
    draft_id: str,
    product_id: str,
    payload: dict[str, Any],
) -> list[ProductIntelligenceReviewFieldProvenanceInput]:
    items: list[ProductIntelligenceReviewFieldProvenanceInput] = []
    for field_name in PROVENANCE_AUTO_FIELDS:
        value = payload.get(field_name)
        if not _has_value(value):
            continue
        items.append(
            ProductIntelligenceReviewFieldProvenanceInput(
                field_name=field_name,
                declared_value=_stringify_value(value),
                normalized_value=_stringify_value(value),
                source_type="REVIEW_DRAFT",
                source_url=(
                    payload.get("source_urls_json", {}).get("source_url")
                    if isinstance(payload.get("source_urls_json"), dict)
                    else None
                ),
                source_lane="PRODUCT_INTELLIGENCE_REVIEW_DRAFT",
                evidence_kind="JSON" if isinstance(value, (list, dict)) else "TEXT",
                extraction_method="MANUAL_REVIEW",
                confidence_score=payload.get("confidence_score"),
                verification_status="PENDING_REVIEW",
                claim_risk_flag=payload.get("claim_risk_level"),
                reviewer_note=payload.get("reviewer_note"),
            ),
        )
    return items


# Claim posture is ORDERED. A computed verdict may raise the floor, never sink
# below it.
_GATE_ORDER = {"CLAIM_SAFE": 0, "CLAIM_REVIEW_REQUIRED": 1, "CLAIM_BLOCKED": 2}
_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _claim_floor(product: dict[str, Any] | None) -> tuple[str, str]:
    """The lowest claim posture a draft for THIS product may ever record.

    `evaluate_claim_safety` scans the draft TEXT for banned tokens. That is a
    content check, and content checks miss category risk: a male-vitality
    topical whose draft says "melancarkan peredaran darah" contains no banned
    token, so the scan returns CLAIM_SAFE/LOW even though the catalog marks the
    product claim_risk_level=HIGH and its framework family demands
    CLAIM_REVIEW_REQUIRED. That combination produced a READY_FOR_APPROVAL draft
    with a falsely-safe posture on the most sensitive product in the catalog.

    The floor closes that hole. It can only ever RAISE the posture, so it cannot
    make any existing draft less safe — at worst it forces a review that was
    already warranted.

    Driven by the product's OWN `claim_risk_level` only. A first version also
    pulled the framework family's gate, which swept in every unclassified
    product and would have forced claim review on ordinary household items — a
    broad block for no safety gain. Narrowed deliberately: only a product the
    catalog already marks HIGH raises the gate.
    """
    if not isinstance(product, dict) or not product:
        return "CLAIM_SAFE", "LOW"

    risk = str(product.get("claim_risk_level") or "").strip().upper()
    if risk not in _RISK_ORDER:
        return "CLAIM_SAFE", "LOW"
    gate = "CLAIM_REVIEW_REQUIRED" if risk == "HIGH" else "CLAIM_SAFE"
    return gate, risk


def _evaluate_validation_payload(
    payload: dict[str, Any],
    product: dict[str, Any] | None = None,
    dispositions: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    claim = evaluate_claim_safety(payload, product=product)
    payload.update(claim)

    floor_gate, floor_risk = _claim_floor(product)
    if _GATE_ORDER.get(str(payload.get("claim_gate") or "CLAIM_SAFE"), 0) < _GATE_ORDER[floor_gate]:
        payload["claim_gate"] = floor_gate
    if _RISK_ORDER.get(str(payload.get("claim_risk_level") or "LOW"), 0) < _RISK_ORDER[floor_risk]:
        payload["claim_risk_level"] = floor_risk
    # `_required_field_present`, not `_has_value`: a whole-value placeholder string
    # ("N/A", "NOT_AVAILABLE", "-") is MISSING knowledge, not present knowledge. The
    # governed way to record absence is a disposition, never a magic value.
    missing_required_fields = [
        field_name for field_name in REQUIRED_FIELDS
        if not _required_field_present(payload.get(field_name))
    ]
    present_required_fields = [
        field_name for field_name in REQUIRED_FIELDS if field_name not in missing_required_fields
    ]
    # Completeness stays TRUTHFUL: a governed absence never counts as presence.
    completeness_score = round(
        len(present_required_fields) / len(REQUIRED_FIELDS),
        4,
    )

    # Partition the missing set by disposition. Only DISPOSITION_ELIGIBLE_FIELDS may be
    # governed at all; NOT_APPLICABLE is additionally re-checked against the category
    # matrix HERE (not only at write time) so a product recategorised after the
    # disposition was recorded fails closed instead of keeping a now-illegal waiver.
    dispositions = dispositions or {}
    category = product.get("category") if isinstance(product, dict) else None
    governed_absent_fields: dict[str, str] = {}
    unresolved_external_fields: list[str] = []
    for field_name in missing_required_fields:
        row = dispositions.get(field_name)
        if not row or field_name not in DISPOSITION_ELIGIBLE_FIELDS:
            continue
        disposition = str(row.get("disposition") or "")
        if disposition == DISPOSITION_NOT_STATED:
            governed_absent_fields[field_name] = disposition
        elif disposition == DISPOSITION_SOURCE_UNAVAILABLE:
            # A truthful supply gap satisfies the blocker as a governed absence, exactly like
            # NOT_STATED — but it does not assert an inspected source.
            governed_absent_fields[field_name] = disposition
        elif disposition == DISPOSITION_NOT_APPLICABLE and na_allowed_for_category(category):
            governed_absent_fields[field_name] = disposition
        elif disposition == DISPOSITION_EXTERNAL:
            unresolved_external_fields.append(field_name)
    ungoverned_missing = [
        field_name for field_name in missing_required_fields
        if field_name not in governed_absent_fields
        and field_name not in unresolved_external_fields
    ]

    # Which dispositions COULD govern each still-ungoverned eligible field — the server
    # is the single authority; the UI renders exactly this, disabled reasons included.
    disposition_options = {
        field_name: (
            [DISPOSITION_NOT_STATED]
            + ([DISPOSITION_NOT_APPLICABLE] if na_allowed_for_category(category) else [])
            + [DISPOSITION_SOURCE_UNAVAILABLE, DISPOSITION_EXTERNAL]
        )
        for field_name in missing_required_fields
        if field_name in DISPOSITION_ELIGIBLE_FIELDS
    }

    approval_blockers: list[str] = []
    readiness_status = "READY_FOR_APPROVAL"
    if governed_absent_fields:
        readiness_status = READINESS_GOVERNED_ABSENCE
    if ungoverned_missing:
        readiness_status = "MISSING_REQUIRED_FIELDS"
        approval_blockers.append(
            f"MISSING_REQUIRED_FIELDS:{','.join(ungoverned_missing)}",
        )
    if unresolved_external_fields:
        # Documented-but-unresolved is still BLOCKING — that is the whole meaning of
        # REQUIRES_EXTERNAL_EVIDENCE. Its own prefix so no relaxation path (which strips
        # MISSING_REQUIRED_FIELDS only) can ever clear it.
        if readiness_status != "MISSING_REQUIRED_FIELDS":
            readiness_status = "MISSING_REQUIRED_FIELDS"
        approval_blockers.append(
            f"REQUIRES_EXTERNAL_EVIDENCE:{','.join(unresolved_external_fields)}",
        )
    if payload["claim_gate"] == "CLAIM_BLOCKED":
        readiness_status = "CLAIM_BLOCKED"
        approval_blockers.append(
            f"CLAIM_BLOCKED:{','.join(payload['claim_tokens_json']) or 'UNSPECIFIED'}",
        )
    elif payload["claim_gate"] == "CLAIM_REVIEW_REQUIRED" and readiness_status in (
        "READY_FOR_APPROVAL", READINESS_GOVERNED_ABSENCE,
    ):
        # Claim review is an approval blocker, not a field-completeness class. Preserve
        # governed absence as the frozen snapshot/reporting authority while the separate
        # claim gate and blocker continue to require an explicit acknowledgement.
        if readiness_status == "READY_FOR_APPROVAL":
            readiness_status = "CLAIM_REVIEW_REQUIRED"
        approval_blockers.append(
            f"CLAIM_REVIEW_REQUIRED:{','.join(payload['claim_tokens_json']) or 'UNSPECIFIED'}",
        )
    payload["completeness_score"] = completeness_score
    payload["readiness_status"] = readiness_status
    return {
        "missing_required_fields": missing_required_fields,
        "present_required_fields": present_required_fields,
        "completeness_score": completeness_score,
        "readiness_status": readiness_status,
        "claim_gate": payload["claim_gate"],
        "claim_risk_level": payload["claim_risk_level"],
        "claim_tokens_json": payload["claim_tokens_json"],
        "allowed_claims_json": payload["allowed_claims_json"],
        "blocked_claims_json": payload["blocked_claims_json"],
        "approval_blockers": approval_blockers,
        "governed_absent_fields": governed_absent_fields,
        "unresolved_external_fields": unresolved_external_fields,
        "disposition_options": disposition_options,
    }


def _derive_review_status(
    payload: dict[str, Any],
    *,
    current_status: str | None,
) -> ReviewDraftStatus:
    if current_status in TERMINAL_STATUSES:
        return current_status  # type: ignore[return-value]
    if not any(_has_value(payload.get(field_name)) for field_name in MEANINGFUL_CONTENT_FIELDS):
        return "DRAFT"
    # Governed absence IS reviewable: every gap is either filled or carries a
    # reviewer-attributed disposition, so the draft is ready for human review exactly
    # like a fully complete one (the DISTINCT readiness value keeps them tellable).
    if payload.get("readiness_status") in ("READY_FOR_APPROVAL", READINESS_GOVERNED_ABSENCE):
        return "READY_FOR_REVIEW"
    return "NEEDS_REVISION"


async def _replace_draft_provenance(
    *,
    draft_id: str,
    product_id: str,
    items: list[ProductIntelligenceReviewFieldProvenanceInput],
) -> None:
    await crud.delete_product_intelligence_review_field_provenance_for_draft(draft_id)
    for item in items:
        await crud.create_product_intelligence_review_field_provenance(
            draft_id=draft_id,
            product_id=product_id,
            field_name=item.field_name,
            source_type=item.source_type,
            evidence_kind=item.evidence_kind,
            extraction_method=item.extraction_method,
            verification_status=item.verification_status,
            declared_value=item.declared_value,
            normalized_value=item.normalized_value,
            source_url=item.source_url,
            source_lane=item.source_lane,
            confidence_score=item.confidence_score,
            claim_risk_flag=item.claim_risk_flag,
            reviewer_decision=item.reviewer_decision,
            reviewer_note=item.reviewer_note,
        )


async def get_review_draft_by_id(
    draft_id: str,
) -> ProductIntelligenceReviewDraft | None:
    row = await crud.get_product_intelligence_review_draft(draft_id)
    if not row:
        return None
    provenance_items = await _load_provenance_for_draft(draft_id)
    return _row_to_draft(row, provenance_items=provenance_items)


async def create_review_draft(
    product_id: str,
    request: ProductIntelligenceReviewDraftCreateRequest,
) -> ProductIntelligenceReviewDraft:
    product = await _get_product_or_raise(product_id)
    payload = _seed_payload_from_product(product)
    payload.update(request.model_dump(exclude_unset=True))
    payload = _normalize_mutation_payload(payload)
    payload = _apply_derived_angles(payload)
    validation = _evaluate_validation_payload(
        payload, product,
        dispositions=_dispositions_from_items(request.provenance_items))
    review_status = _derive_review_status(payload, current_status=None)
    row = await crud.create_product_intelligence_review_draft(
        product_id=product_id,
        review_status=review_status,
        product_description=payload.get("product_description"),
        benefits_json=_serialize_json(payload.get("benefits_json"), []),
        usp_json=_serialize_json(payload.get("usp_json"), []),
        usage_text=payload.get("usage_text"),
        ingredients_text=payload.get("ingredients_text"),
        warnings_text=payload.get("warnings_text"),
        target_customer_text=payload.get("target_customer_text"),
        paste_anything_summary=payload.get("paste_anything_summary"),
        source_urls_json=_serialize_json(payload.get("source_urls_json"), {}),
        image_evidence_json=_serialize_json(payload.get("image_evidence_json"), {}),
        package_notes=payload.get("package_notes"),
        size_or_volume=payload.get("size_or_volume"),
        product_form_factor=payload.get("product_form_factor"),
        packaging_description=payload.get("packaging_description"),
        product_truth_lock=payload.get("product_truth_lock"),
        claim_gate=validation["claim_gate"],
        claim_risk_level=validation["claim_risk_level"],
        claim_tokens_json=_serialize_json(validation["claim_tokens_json"], []),
        allowed_claims_json=_serialize_json(validation["allowed_claims_json"], []),
        blocked_claims_json=_serialize_json(validation["blocked_claims_json"], []),
        buyer_persona_snapshot_json=_serialize_json(
            payload.get("buyer_persona_snapshot_json"),
            {},
        ),
        copy_strategy_summary_json=_serialize_json(
            payload.get("copy_strategy_summary_json"),
            {},
        ),
        confidence_score=payload.get("confidence_score"),
        completeness_score=validation["completeness_score"],
        readiness_status=validation["readiness_status"],
        reviewer_note=payload.get("reviewer_note"),
        created_by=payload.get("created_by"),
        reviewed_by=payload.get("reviewed_by"),
    )
    draft_id = str(row["draft_id"])
    provenance_items = request.provenance_items or _build_auto_provenance_items(
        draft_id=draft_id,
        product_id=product_id,
        payload=payload,
    )
    await _replace_draft_provenance(
        draft_id=draft_id,
        product_id=product_id,
        items=provenance_items,
    )
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    return draft


async def list_review_drafts(
    product_id: str,
    *,
    limit: int = 20,
) -> ProductIntelligenceReviewDraftListResponse:
    await _get_product_or_raise(product_id)
    rows = await crud.list_product_intelligence_review_drafts(product_id=product_id, limit=limit)
    items: list[ProductIntelligenceReviewDraft] = []
    for row in rows:
        draft = _row_to_draft(row)
        items.append(draft)
    return ProductIntelligenceReviewDraftListResponse(product_id=product_id, items=items)


async def update_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftUpdateRequest,
) -> ProductIntelligenceReviewDraft:
    existing_row = await _get_draft_row_or_raise(draft_id)
    existing = _row_to_draft(existing_row)
    if existing.review_status in TERMINAL_STATUSES:
        raise ValueError(f"DRAFT_UPDATE_FORBIDDEN:{existing.review_status}")

    payload = existing.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"})
    payload.update(request.model_dump(exclude_unset=True))
    payload = _normalize_mutation_payload(payload)
    payload = _apply_derived_angles(payload)
    product = await crud.get_product(existing.product_id)
    # Dispositions live on the draft's provenance; an update that does not touch
    # provenance must still validate WITH them, or every Save would flip a governed
    # draft back to MISSING_REQUIRED_FIELDS.
    incoming_items = request.provenance_items if "provenance_items" in request.model_fields_set else None
    stored_items = await _load_provenance_for_draft(draft_id)
    validation = _evaluate_validation_payload(
        payload, product,
        dispositions=_dispositions_from_items(
            incoming_items if incoming_items is not None else stored_items))
    review_status = _derive_review_status(payload, current_status=existing.review_status)
    await crud.update_product_intelligence_review_draft(
        draft_id,
        review_status=review_status,
        product_description=payload.get("product_description"),
        benefits_json=_serialize_json(payload.get("benefits_json"), []),
        usp_json=_serialize_json(payload.get("usp_json"), []),
        usage_text=payload.get("usage_text"),
        ingredients_text=payload.get("ingredients_text"),
        warnings_text=payload.get("warnings_text"),
        target_customer_text=payload.get("target_customer_text"),
        paste_anything_summary=payload.get("paste_anything_summary"),
        source_urls_json=_serialize_json(payload.get("source_urls_json"), {}),
        image_evidence_json=_serialize_json(payload.get("image_evidence_json"), {}),
        package_notes=payload.get("package_notes"),
        size_or_volume=payload.get("size_or_volume"),
        product_form_factor=payload.get("product_form_factor"),
        packaging_description=payload.get("packaging_description"),
        product_truth_lock=payload.get("product_truth_lock"),
        claim_gate=validation["claim_gate"],
        claim_risk_level=validation["claim_risk_level"],
        claim_tokens_json=_serialize_json(validation["claim_tokens_json"], []),
        allowed_claims_json=_serialize_json(validation["allowed_claims_json"], []),
        blocked_claims_json=_serialize_json(validation["blocked_claims_json"], []),
        buyer_persona_snapshot_json=_serialize_json(
            payload.get("buyer_persona_snapshot_json"),
            {},
        ),
        copy_strategy_summary_json=_serialize_json(
            payload.get("copy_strategy_summary_json"),
            {},
        ),
        confidence_score=payload.get("confidence_score"),
        completeness_score=validation["completeness_score"],
        readiness_status=validation["readiness_status"],
        reviewer_note=payload.get("reviewer_note"),
        created_by=payload.get("created_by"),
        reviewed_by=payload.get("reviewed_by"),
    )
    provenance_items = request.provenance_items
    if provenance_items is not None:
        await _replace_draft_provenance(
            draft_id=draft_id,
            product_id=existing.product_id,
            items=provenance_items,
        )
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    return draft


async def validate_review_draft(
    draft_id: str,
) -> ProductIntelligenceReviewDraftValidationResponse:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    # The claim FLOOR needs the product. Omitting it here would let /validate
    # report a safe-looking posture that create/update would refuse — the UI
    # calls this endpoint to decide whether a draft is approvable, so it must
    # apply the same floor.
    product = await crud.get_product(draft.product_id)
    if draft.review_status in TERMINAL_STATUSES:
        validation = _evaluate_validation_payload(
            draft.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
            product,
            dispositions=_dispositions_from_items(draft.provenance_items),
        )
        return ProductIntelligenceReviewDraftValidationResponse(
            draft=draft,
            **validation,
        )

    updated = await update_review_draft(
        draft_id,
        ProductIntelligenceReviewDraftUpdateRequest(
            provenance_items=[
                ProductIntelligenceReviewFieldProvenanceInput.model_validate(
                    item.model_dump(
                        exclude={"review_provenance_id", "draft_id", "product_id", "created_at", "updated_at"},
                    ),
                )
                for item in draft.provenance_items
            ],
        ),
    )
    validation = _evaluate_validation_payload(
        updated.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
        product,
        dispositions=_dispositions_from_items(updated.provenance_items),
    )
    return ProductIntelligenceReviewDraftValidationResponse(draft=updated, **validation)


async def set_field_disposition(
    draft_id: str,
    request: "ProductIntelligenceFieldDispositionRequest",
) -> ProductIntelligenceReviewDraftValidationResponse:
    """Record one reviewer-attributed absence disposition on the CURRENT draft.

    Upsert by (draft_id, field_name, FIELD_ABSENCE_DISPOSITION): a retry or a changed
    decision UPDATES the single governing row — never a duplicate, and never touching
    any other provenance. Every rule here fails closed with a typed ValueError the API
    maps to a status the UI can explain.
    """
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status in TERMINAL_STATUSES:
        # A terminal draft's provenance is part of an approved/rejected record;
        # governing absence happens on the OPEN draft only.
        raise ValueError(f"DRAFT_DISPOSITION_FORBIDDEN:{draft.review_status}")
    field_name = request.field_name.strip()
    if field_name not in DISPOSITION_ELIGIBLE_FIELDS:
        # Copy-critical fields and allowed_claims_json are hard requirements by owner
        # decision — there is no governed way to declare them absent.
        raise ValueError(f"FIELD_NOT_DISPOSITION_ELIGIBLE:{field_name}")
    if _required_field_present(getattr(draft, field_name, None)):
        # "This field has a value AND the source doesn't state it" is a contradiction;
        # clear the value first if the evidence is wrong.
        raise ValueError(f"FIELD_HAS_VALUE:{field_name}")
    reviewed_by = request.reviewed_by.strip()
    if not reviewed_by:
        raise ValueError("REVIEWER_REQUIRED")
    note = request.reviewer_note.strip()
    if len(note) < 5:
        # The note is the accountability record; "x" is not a rationale.
        raise ValueError("REVIEWER_NOTE_REQUIRED")
    product = await crud.get_product(draft.product_id)
    if (request.disposition == DISPOSITION_NOT_APPLICABLE
            and not na_allowed_for_category((product or {}).get("category"))):
        raise ValueError(
            "NOT_APPLICABLE_FORBIDDEN_FOR_CATEGORY:"
            f"{(product or {}).get('category') or 'UNKNOWN'}")

    now = _now_iso()
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "SELECT review_provenance_id FROM product_intelligence_review_field_provenance "
            "WHERE draft_id=? AND field_name=? AND evidence_kind=?",
            (draft_id, field_name, DISPOSITION_EVIDENCE_KIND),
        )
        existing = await cursor.fetchone()
        await cursor.close()
        if existing:
            await db.execute(
                "UPDATE product_intelligence_review_field_provenance "
                "SET verification_status=?, reviewer_decision=?, reviewer_note=?, updated_at=? "
                "WHERE review_provenance_id=?",
                (request.disposition, reviewed_by, note, now,
                 str(existing["review_provenance_id"])),
            )
        else:
            await db.execute(
                "INSERT INTO product_intelligence_review_field_provenance ("
                " review_provenance_id, draft_id, product_id, field_name, declared_value,"
                " normalized_value, source_type, source_url, source_lane, evidence_kind,"
                " extraction_method, confidence_score, verification_status,"
                " claim_risk_flag, reviewer_decision, reviewer_note, created_at, updated_at"
                ") VALUES (?,?,?,?,NULL,NULL,?,NULL,?,?,?,NULL,?,NULL,?,?,?,?)",
                (str(uuid4()), draft_id, draft.product_id, field_name,
                 "REVIEWER_DISPOSITION", "PRODUCTS_GOVERNED_ABSENCE",
                 DISPOSITION_EVIDENCE_KIND, "MANUAL_REVIEW",
                 request.disposition, reviewed_by, note, now, now),
            )
        await db.commit()

    # Re-validate so the STORED readiness reflects the new disposition immediately —
    # the response is the same shape the Validate button returns, so the UI needs no
    # second call to know what changed.
    return await validate_review_draft(draft_id)


async def reject_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftRejectRequest,
) -> ProductIntelligenceReviewDraft:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status == "APPROVED":
        raise ValueError("DRAFT_ALREADY_APPROVED")
    if draft.review_status == "REJECTED":
        raise ValueError("DRAFT_ALREADY_REJECTED")
    if draft.review_status in TERMINAL_STATUSES:
        raise ValueError(f"DRAFT_UPDATE_FORBIDDEN:{draft.review_status}")
    rejected_by = (request.rejected_by or draft.reviewed_by or "operator").strip()
    await crud.update_product_intelligence_review_draft(
        draft_id,
        review_status="REJECTED",
        reviewer_note=request.reviewer_note if request.reviewer_note is not None else draft.reviewer_note,
        reviewed_by=draft.reviewed_by or rejected_by,
        rejected_by=rejected_by,
        rejected_at=_now_iso(),
    )
    updated = await get_review_draft_by_id(draft_id)
    if not updated:
        raise ValueError("DRAFT_NOT_FOUND")
    return updated


def _snapshot_from_row(row: dict[str, Any]) -> ProductIntelligenceSnapshot:
    payload = dict(row)
    payload["benefits_json"] = _parse_json_field(payload.get("benefits_json"), default=[], expected_type=list)
    payload["usp_json"] = _parse_json_field(payload.get("usp_json"), default=[], expected_type=list)
    payload["source_urls_json"] = _parse_json_field(payload.get("source_urls_json"), default={}, expected_type=dict)
    payload["image_evidence_json"] = _parse_json_field(payload.get("image_evidence_json"), default={}, expected_type=dict)
    payload["claim_tokens_json"] = _parse_json_field(payload.get("claim_tokens_json"), default=[], expected_type=list)
    payload["allowed_claims_json"] = _parse_json_field(payload.get("allowed_claims_json"), default=[], expected_type=list)
    payload["blocked_claims_json"] = _parse_json_field(payload.get("blocked_claims_json"), default=[], expected_type=list)
    payload["buyer_persona_snapshot_json"] = _parse_json_field(
        payload.get("buyer_persona_snapshot_json"),
        default={},
        expected_type=dict,
    )
    payload["copy_strategy_summary_json"] = _parse_json_field(
        payload.get("copy_strategy_summary_json"),
        default={},
        expected_type=dict,
    )
    return ProductIntelligenceSnapshot.model_validate(payload)


async def approve_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftApproveRequest,
) -> ProductIntelligenceSnapshot:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status == "APPROVED":
        raise ValueError("DRAFT_ALREADY_APPROVED")
    if draft.review_status == "REJECTED":
        raise ValueError("DRAFT_ALREADY_REJECTED")
    if draft.review_status in TERMINAL_STATUSES:
        raise ValueError(f"DRAFT_UPDATE_FORBIDDEN:{draft.review_status}")
    validation = await validate_review_draft(draft_id)
    blockers = list(validation.approval_blockers or [])
    # CLAIM_REVIEW_REQUIRED asks for human eyes on the claim set; it is
    # SATISFIABLE by an explicit acknowledgement. Treating it as an absolute
    # block made every high-claim-risk product permanently unapprovable — a
    # deadlock rather than a safeguard, and the exact wall a real approval
    # attempt hit on BOSMAX HERBS. CLAIM_BLOCKED and MISSING_REQUIRED_FIELDS
    # are NOT satisfiable this way and still stop approval dead.
    # 1) Relax product-knowledge FIRST (opt-in), then RE-ASSERT the claim gate.
    #    _evaluate_validation_payload only surfaces the CLAIM_REVIEW_REQUIRED
    #    blocker while readiness is READY_FOR_APPROVAL — so when fields are
    #    missing it is SUPPRESSED. Dropping the missing-fields block would then
    #    silently let a review-required/blocked claim through. Re-assert it here.
    if request.allow_incomplete_product_knowledge:
        missing_copy_critical = [
            f for f in (validation.missing_required_fields or [])
            if f in COPY_GROUNDING_REQUIRED_FIELDS
        ]
        if not missing_copy_critical:
            blockers = [b for b in blockers if not b.startswith("MISSING_REQUIRED_FIELDS")]
            tokens = ",".join(validation.claim_tokens_json or []) or "UNSPECIFIED"
            if validation.claim_gate == "CLAIM_BLOCKED" and not any(
                b.startswith("CLAIM_BLOCKED") for b in blockers
            ):
                blockers.append(f"CLAIM_BLOCKED:{tokens}")
            elif validation.claim_gate == "CLAIM_REVIEW_REQUIRED" and not any(
                b.startswith("CLAIM_REVIEW_REQUIRED") for b in blockers
            ):
                blockers.append(f"CLAIM_REVIEW_REQUIRED:{tokens}")
        else:
            # A copy-critical field is itself missing -> never approvable; keep
            # the block (re-labelled so the reason is unambiguous).
            blockers = [
                (f"MISSING_COPY_CRITICAL_FIELDS:{','.join(missing_copy_critical)}"
                 if b.startswith("MISSING_REQUIRED_FIELDS") else b)
                for b in blockers
            ]
    # 2) CLAIM_REVIEW_REQUIRED asks for human eyes on the claim set; it is
    #    SATISFIABLE by an explicit acknowledgement (records that the approver
    #    read the claims). Applied AFTER the re-assertion above so an
    #    acknowledged review clears whether the blocker came from validation or
    #    the re-assertion. CLAIM_BLOCKED and MISSING_* are NOT satisfiable this
    #    way and still stop approval dead.
    if request.claim_review_acknowledged:
        blockers = [b for b in blockers if not b.startswith("CLAIM_REVIEW_REQUIRED")]
    if blockers:
        hint = ""
        if any(b.startswith("CLAIM_REVIEW_REQUIRED") for b in blockers):
            hint = " (set claim_review_acknowledged=true to record the review)"
        raise ValueError(f"DRAFT_NOT_APPROVABLE:{'|'.join(blockers)}{hint}")

    await _get_product_or_raise(draft.product_id)
    approved_by = (request.approved_by or draft.reviewed_by or draft.created_by or "operator").strip()
    approval_note = request.approval_note if request.approval_note is not None else draft.reviewer_note
    now = _now_iso()
    if request.claim_review_acknowledged and validation.claim_gate == "CLAIM_REVIEW_REQUIRED":
        acknowledgement = (
            "CLAIM_REVIEW_ACKNOWLEDGED: "
            f"{approved_by} acknowledged {','.join(validation.claim_tokens_json or []) or 'UNSPECIFIED'} "
            f"at {now}"
        )
        approval_note = "\n".join(
            part for part in (str(approval_note or "").strip(), acknowledgement) if part
        )
    db = await get_db()
    snapshot_id = str(uuid4())
    async with _db_lock:
        latest_cur = await db.execute(
            """
            SELECT * FROM product_intelligence_snapshot
            WHERE product_id=? AND status='APPROVED'
            ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC
            LIMIT 1
            """,
            (draft.product_id,),
        )
        latest_row = await latest_cur.fetchone()
        latest_snapshot = dict(latest_row) if latest_row else None

        version_cur = await db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM product_intelligence_snapshot WHERE product_id=?",
            (draft.product_id,),
        )
        next_version = int((await version_cur.fetchone())[0]) + 1
        if latest_snapshot:
            await db.execute(
                """
                UPDATE product_intelligence_snapshot
                SET status='SUPERSEDED', updated_at=?
                WHERE snapshot_id=?
                """,
                (now, latest_snapshot["snapshot_id"]),
            )

        await db.execute(
            """
            INSERT INTO product_intelligence_snapshot (
                snapshot_id, product_id, version, status, product_description, benefits_json,
                usp_json, usage_text, ingredients_text, warnings_text, target_customer_text,
                paste_anything_summary, source_urls_json, image_evidence_json, package_notes,
                size_or_volume, product_form_factor, packaging_description, product_truth_lock,
                claim_gate, claim_risk_level, claim_tokens_json, allowed_claims_json,
                blocked_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json,
                confidence_score, completeness_score, readiness_status, created_from_review_draft_id,
                created_by, approved_by, approved_at, supersedes_snapshot_id, created_at, updated_at
            ) VALUES (?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                draft.product_id,
                next_version,
                draft.product_description,
                json.dumps(draft.benefits_json),
                json.dumps(draft.usp_json),
                draft.usage_text,
                draft.ingredients_text,
                draft.warnings_text,
                draft.target_customer_text,
                draft.paste_anything_summary,
                json.dumps(draft.source_urls_json),
                json.dumps(draft.image_evidence_json),
                draft.package_notes,
                draft.size_or_volume,
                draft.product_form_factor,
                draft.packaging_description,
                draft.product_truth_lock,
                draft.claim_gate,
                draft.claim_risk_level,
                json.dumps(draft.claim_tokens_json),
                json.dumps(draft.allowed_claims_json),
                json.dumps(draft.blocked_claims_json),
                json.dumps(draft.buyer_persona_snapshot_json),
                json.dumps(draft.copy_strategy_summary_json),
                draft.confidence_score,
                # From the JUST-COMPUTED validation, not the draft row: the draft object
                # here was fetched BEFORE validate refreshed it, and a stale readiness
                # is exactly how 318 historical snapshots froze MISSING_REQUIRED_FIELDS
                # while claiming approval. The frozen value is the classification
                # authority (FULLY_COMPLETE vs READY_WITH_GOVERNED_ABSENCE) forever.
                validation.completeness_score,
                validation.readiness_status,
                draft.draft_id,
                draft.created_by,
                approved_by,
                now,
                latest_snapshot["snapshot_id"] if latest_snapshot else None,
                now,
                now,
            ),
        )

        provenance_rows = [
            item.model_dump(exclude={"review_provenance_id", "draft_id", "product_id", "created_at", "updated_at"})
            for item in draft.provenance_items
        ]
        if not provenance_rows:
            provenance_rows = [
                item.model_dump()
                for item in _build_auto_provenance_items(
                    draft_id=draft.draft_id,
                    product_id=draft.product_id,
                    payload=draft.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
                )
            ]
        for item in provenance_rows:
            await db.execute(
                """
                INSERT INTO product_intelligence_field_provenance (
                    provenance_id, snapshot_id, product_id, field_name, declared_value,
                    normalized_value, source_type, source_url, source_lane, evidence_kind,
                    extraction_method, confidence_score, verification_status, claim_risk_flag,
                    reviewer_decision, reviewer_note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    snapshot_id,
                    draft.product_id,
                    item["field_name"],
                    item.get("declared_value"),
                    item.get("normalized_value"),
                    item["source_type"],
                    item.get("source_url"),
                    item.get("source_lane"),
                    item["evidence_kind"],
                    item["extraction_method"],
                    item.get("confidence_score"),
                    # A governed disposition is the immutable semantic value. Replacing
                    # it with REVIEWED_APPROVED destroys which absence was approved and
                    # makes the snapshot depend on the mutable review-draft table.
                    (item.get("verification_status")
                     if item.get("evidence_kind") == DISPOSITION_EVIDENCE_KIND
                     else "REVIEWED_APPROVED"),
                    item.get("claim_risk_flag"),
                    item.get("reviewer_decision") or "APPROVED",
                    item.get("reviewer_note") or approval_note,
                    now,
                    now,
                ),
            )

        await db.execute(
            """
            UPDATE product_intelligence_review_draft
            SET review_status='APPROVED', reviewer_note=?, reviewed_by=?, approved_by=?,
                approved_at=?, updated_at=?
            WHERE draft_id=?
            """,
            (
                approval_note,
                draft.reviewed_by or approved_by,
                approved_by,
                now,
                now,
                draft.draft_id,
            ),
        )
        await db.commit()

    snapshot_row = await crud.get_product_intelligence_snapshot(snapshot_id)
    if not snapshot_row:
        raise ValueError("SNAPSHOT_NOT_FOUND")
    return _snapshot_from_row(snapshot_row)


# ── AI Fill Missing (DeepSeek-backed draft field enrichment) ──────────────────
# DISTINCT from deterministic Recompute: this is the ONLY draft action that calls
# the AI provider. It proposes DRAFT values for missing/selected Product Truth
# fields only, records field-level provenance + AI metadata, and NEVER approves.
# It reuses the existing text_assist provider adapter (DeepSeek) — no new
# framework, no hardcoded secrets — and the existing update_review_draft path
# (exclude_unset preserves valid human evidence). Copy Intelligence enters ONLY
# as APPROVED supporting persona/strategy; hook/CTA never become product facts.
AI_FILL_TARGET_FIELDS = (
    "product_description",         # Product Knowledge Text
    "benefits_json",              # Benefits Text (factual benefits list)
    "usp_json",                   # Unique selling propositions (factual list)
    "usage_text",                 # Usage Text
    "target_customer_text",       # Target Customer Text (product-identity supported inference)
    "buyer_persona_snapshot_json",  # Buyer Persona (product-specific object, supported inference)
    "copy_strategy_summary_json",   # Copy Strategy (product-specific object, supported inference)
    "ingredients_text",           # Ingredients Text
    "warnings_text",              # Warnings Text
)
_AI_FILL_LIST_FIELDS = ("benefits_json", "usp_json")
_AI_FILL_OBJECT_FIELDS = ("buyer_persona_snapshot_json", "copy_strategy_summary_json")
AI_FILL_PROMPT_VERSION = "product_intel_ai_fill_v2"

_AI_FILL_SYSTEM = (
    "You enrich a PRODUCT TRUTH review draft for human approval. You propose "
    "DRAFT values for ONLY the requested fields, grounded strictly in the supplied "
    "evidence (product identity, taxonomy/product type, stated use, form factor, "
    "grounded benefits). You NEVER approve anything and NEVER invent facts. When "
    "evidence is insufficient, you MUST return status INSUFFICIENT_EVIDENCE rather "
    "than fabricating. Every proposal MUST be PRODUCT-SPECIFIC — never a generic "
    "template that could apply to any product.\n"
    "Field contracts (fill only requested fields):\n"
    "- product_description: factual product description / supported details.\n"
    "- benefits_json: factual, evidence-supported benefits as an array of short "
    "strings. NOT hooks, hashtags, CTA, music/duration instructions, or hype.\n"
    "- usp_json: factual unique selling propositions as an array of short strings "
    "(distinctive product attributes). NOT marketing hooks or CTA.\n"
    "- usage_text: how the product is used; INSUFFICIENT_EVIDENCE if unsupported.\n"
    "- target_customer_text: status INFERENCE. A PRODUCT-SPECIFIC audience inferred "
    "ONLY from product identity, taxonomy/product type, stated use, form factor and "
    "grounded benefits (e.g. the need the product serves). NEVER assume age, gender, "
    "income, medical condition, profession, lifestyle, or efficacy expectation. No "
    "hook/promotional sentence.\n"
    "- buyer_persona_snapshot_json: status INFERENCE. A PRODUCT-SPECIFIC persona "
    "OBJECT derived from the grounded target_customer + product type + use + "
    "benefits, e.g. {\"audience\":..., \"needs\":[...], \"purchase_context\":..., "
    "\"tone\":..., \"pronoun\":\"you\"}. FORBIDDEN: 'generic consumer', 'everyday "
    "users', 'suitable for everyone', placeholder personas, or the same persona "
    "across unrelated products. No demographic assumptions, no efficacy claims.\n"
    "- copy_strategy_summary_json: status INFERENCE. A PRODUCT-SPECIFIC strategy "
    "OBJECT derived from product type, use context and grounded benefit/USP, e.g. "
    "{\"recommended_formula\":..., \"angles\":[...], \"market_problem_language\":"
    "[...]}. Must differ across unrelated products. No hooks/CTA, no efficacy.\n"
    "- ingredients_text: actual ingredients / materials / components / features, or "
    "NOT_APPLICABLE for the product type. NEVER put CTA or marketing copy here.\n"
    "- warnings_text: real warnings / cautions / restrictions, or "
    "INSUFFICIENT_EVIDENCE. Do NOT invent warnings.\n"
    "Copy Intelligence (avatar/pain/emotion/dream/hook/cta/strategy) is SUPPORTING "
    "persona & angle evidence only — it is NOT product truth. Never turn hook/CTA "
    "text into a product fact. No medical/cure/treatment/guaranteed-result claims. "
    "Return STRICT JSON only: {\"fields\": {\"<field>\": {\"value\": <string, array "
    "for benefits_json/usp_json, or object for persona/strategy>, \"status\": "
    "\"FACT|INFERENCE|NOT_APPLICABLE|INSUFFICIENT_EVIDENCE\", \"confidence\": "
    "<0..1>, \"rationale\": <short>}}}."
)


def _ai_fill_field_value(draft: ProductIntelligenceReviewDraft, field: str) -> Any:
    return getattr(draft, field, None)


def _coerce_ai_fill_value(field: str, value: Any) -> Any:
    """Coerce a model-proposed value to the field's storage shape (list for
    benefits_json/usp_json, dict for persona/strategy objects, trimmed string
    otherwise). Returns None when empty."""
    if field in _AI_FILL_LIST_FIELDS:
        items = _normalize_list(value)
        return items or None
    if field in _AI_FILL_OBJECT_FIELDS:
        if isinstance(value, dict):
            cleaned = {k: v for k, v in value.items() if v not in (None, "", [], {})}
            return cleaned or None
        return None
    text = str(value or "").strip()
    return text or None


def _build_ai_fill_user_prompt(
    product: dict[str, Any] | None,
    draft: ProductIntelligenceReviewDraft,
    approved_ci: dict[str, Any],
    targets: list[str],
) -> str:
    product = product or {}
    product_meta = {
        "title": product.get("product_display_name") or product.get("raw_product_title"),
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "type": product.get("type") or product.get("product_type"),
        "brand": product.get("brand"),
        "price": product.get("price"),
        "currency": product.get("currency"),
        "product_url": product.get("tiktok_product_url") or product.get("source_url"),
        "product_scale": product.get("product_scale"),
        "physics_class": product.get("physics_class"),
    }
    current_evidence = {
        "product_description": draft.product_description,
        "benefits": list(draft.benefits_json or []),
        "usp": list(getattr(draft, "usp_json", []) or []),
        "usage_text": draft.usage_text,
        "target_customer_text": draft.target_customer_text,
        "ingredients_text": draft.ingredients_text,
        "warnings_text": draft.warnings_text,
        "paste_anything_summary": draft.paste_anything_summary,
        "package_notes": draft.package_notes,
        "size_or_volume": draft.size_or_volume,
        "product_form_factor": draft.product_form_factor,
        "packaging_description": draft.packaging_description,
    }
    # Defence-in-depth: hook_script / cta_script are deliberately EXCLUDED — they
    # are marketing copy and must never seed a product FACT. Only persona/angle
    # signals cross into the enrichment prompt (they support target_customer).
    supporting_ci = [
        {
            "target_avatar": item.get("target_avatar"),
            "pain_point": item.get("pain_point"),
            "emotion_trigger": item.get("emotion_trigger"),
            "dream_outcome": item.get("dream_outcome"),
            "key_features": item.get("key_ingredients_features"),
        }
        for item in (approved_ci.get("items") or [])
    ]
    guardrails = {
        "claim_gate": draft.claim_gate,
        "claim_risk_level": draft.claim_risk_level,
        "allowed_claims": list(getattr(draft, "allowed_claims_json", []) or []),
        "blocked_claims": list(getattr(draft, "blocked_claims_json", []) or []),
    }
    context = {
        "fields_to_fill": targets,
        "product_metadata": product_meta,
        "current_draft_evidence": current_evidence,
        "approved_copy_intelligence_supporting_only": supporting_ci,
        "claim_guardrails": guardrails,
    }
    return (
        "Fill ONLY these fields: " + ", ".join(targets) + ".\n"
        "Use only the evidence below. Prefer INSUFFICIENT_EVIDENCE over guessing.\n\n"
        + json.dumps(context, ensure_ascii=False, default=str)
    )


async def ai_fill_missing_review_draft(
    draft_id: str,
    *,
    selected_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Propose DeepSeek draft values for missing (or explicitly selected) Product
    Truth fields. Fail-closed when the provider lane is unconfigured. Never
    overwrites valid human evidence, never approves, never creates a snapshot,
    never mutates Product Truth or Copy Sets. Persists proposals into the existing
    draft + field-level provenance with AI metadata; result stays a review draft."""
    from agent.services import ai_copy_provider_adapter as _prov
    from agent.services import kalodata_import_service as _ci

    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status in TERMINAL_STATUSES:
        raise ValueError(f"DRAFT_UPDATE_FORBIDDEN:{draft.review_status}")

    provider_id = None
    model_id = None
    try:
        status = _prov.provider_status()
        provider_id = status.get("provider_id")
        model_id = status.get("model_id")
    except Exception:
        pass
    if not _prov.is_configured():
        raise _prov.AICopyProviderNotConfigured(_prov.ERR_NOT_CONFIGURED)

    selected = {f for f in (selected_fields or []) if f in AI_FILL_TARGET_FIELDS}
    if selected:
        targets = [f for f in AI_FILL_TARGET_FIELDS if f in selected]
    else:
        targets = [f for f in AI_FILL_TARGET_FIELDS if not _has_value(_ai_fill_field_value(draft, f))]
    if not targets:
        return {
            "draft_id": draft_id, "product_id": draft.product_id,
            "review_status": draft.review_status, "provider": provider_id,
            "model": model_id, "prompt_version": AI_FILL_PROMPT_VERSION,
            "targeted_fields": [], "proposed": [], "unresolved": [],
            "provider_configured": True,
        }

    product = await crud.get_product(draft.product_id)
    approved_ci = await _ci.get_approved_copy_intelligence_context(
        target_product_id=draft.product_id, limit=20
    )
    user_prompt = _build_ai_fill_user_prompt(product, draft, approved_ci, targets)
    raw = _prov.complete_json(_AI_FILL_SYSTEM, user_prompt)  # DeepSeek structured JSON
    fields_out = raw.get("fields") if isinstance(raw.get("fields"), dict) else raw

    generated_at = _now_iso()
    update_fields: dict[str, Any] = {}
    proposed: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for field in targets:
        entry = fields_out.get(field) if isinstance(fields_out, dict) else None
        if not isinstance(entry, dict):
            unresolved.append({"field": field, "status": "INSUFFICIENT_EVIDENCE", "rationale": "no proposal returned"})
            continue
        status_value = str(entry.get("status") or "INSUFFICIENT_EVIDENCE").upper()
        coerced = _coerce_ai_fill_value(field, entry.get("value"))
        # Enforce the status ENUM: ONLY FACT / INFERENCE may fill a field. NOT_APPLICABLE,
        # INSUFFICIENT_EVIDENCE, or any unrecognised status (defence against a malformed model
        # response) leaves the field unresolved — never silently accepted.
        if status_value not in ("FACT", "INFERENCE") or coerced is None:
            unresolved.append({"field": field, "status": status_value, "rationale": str(entry.get("rationale") or "")})
            continue
        # Defence-in-depth: never overwrite a non-empty human field unless explicitly selected.
        if field not in selected and _has_value(_ai_fill_field_value(draft, field)):
            unresolved.append({"field": field, "status": "SKIPPED_NON_EMPTY", "rationale": "existing human evidence preserved"})
            continue
        update_fields[field] = coerced
        proposed.append({
            "field": field, "status": status_value,
            "confidence": entry.get("confidence"),
            "rationale": str(entry.get("rationale") or ""),
            "previous_value": _ai_fill_field_value(draft, field),
            "proposed_value": coerced,
        })

    if update_fields:
        # Product/taxonomy identity fingerprint (evidence lineage for the supported inference).
        _identity = {
            "product_id": draft.product_id,
            "category": (product or {}).get("category"),
            "subcategory": (product or {}).get("subcategory"),
            "type": (product or {}).get("type") or (product or {}).get("product_type"),
        }
        identity_fingerprint = _hashlib.sha256(
            json.dumps(_identity, sort_keys=True, default=str).encode("utf-8", "replace")
        ).hexdigest()[:16]
        product_url = (product or {}).get("tiktok_product_url") or (product or {}).get("source_url")
        request = ProductIntelligenceReviewDraftUpdateRequest(**update_fields)
        await update_review_draft(draft_id, request)  # never yields APPROVED
        for item in proposed:
            await crud.create_product_intelligence_review_field_provenance(
                draft_id=draft_id,
                product_id=draft.product_id,
                field_name=item["field"],
                source_type="AI_ENRICHMENT",
                source_url=product_url,
                evidence_kind=item["status"],
                extraction_method=f"deepseek:{model_id or 'unknown'}",
                verification_status="AI_PROPOSED",
                declared_value=json.dumps(item["proposed_value"], ensure_ascii=False, default=str),
                confidence_score=item["confidence"] if isinstance(item["confidence"], (int, float)) else None,
                source_lane=_prov.LANE,
                reviewer_note=(
                    f"{AI_FILL_PROMPT_VERSION} | provider={provider_id} model={model_id} "
                    f"generated_at={generated_at} | identity_fingerprint={identity_fingerprint} "
                    f"| evidence=product:{draft.product_id},taxonomy:{_identity['category']}/"
                    f"{_identity['subcategory']}/{_identity['type']} | classification={item['status']} "
                    f"| previous={item['previous_value']!r} | rationale={item['rationale']}"
                ),
            )

    after = await get_review_draft_by_id(draft_id)
    return {
        "draft_id": draft_id,
        "product_id": draft.product_id,
        "review_status": after.review_status if after else draft.review_status,
        "provider": provider_id,
        "model": model_id,
        "prompt_version": AI_FILL_PROMPT_VERSION,
        "generated_at": generated_at,
        "targeted_fields": targets,
        "proposed": proposed,
        "unresolved": unresolved,
        "provider_configured": True,
    }
