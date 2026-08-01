"""B-08A-02 — promote approved registration Product Knowledge into Product Intelligence.

THE DEFECT THIS CLOSES
`registration_commit_service.canonical_payload` carries identity, taxonomy, physics,
commerce and media only. It contains NO Product Knowledge key, creates NO
`product_intelligence_review_draft`, writes NO snapshot and transfers NO provenance. An
operator could approve Product Knowledge candidates, press "Commit to DB", and every one
of those approved values was discarded.

The loss was also INVISIBLE: the commit response computes
`excluded_fields = [f for f in canonical_candidate_fields if not approval_checklist[f]]`
— i.e. candidates the operator did NOT approve. A field the operator DID approve but which
had no `canonical_payload` mapping appeared in neither `committed_fields` nor
`excluded_fields`. It simply vanished.

That is why the four fields registration collects but never promoted sit near zero across
the catalogue (package_notes 0.0%, packaging_description 0.4%, product_form_factor 0.7%,
size_or_volume 1.3% of drafted real products). Registration captured the evidence and
commit threw it away, so the intelligence layer started empty and stayed empty.

WHAT THIS DOES
Builds the promotion payload from the registration draft and hands it to the EXISTING
`create_review_draft` service, so claim-gate evaluation, review-status derivation and the
completeness scan all stay in one place. Field provenance is transferred row by row.

WHAT IT DELIBERATELY DOES NOT DO
  * it never approves anything — no `approved_by`, no `approved_at`, no acknowledgement.
    Registration approval is approval of a CANDIDATE VALUE, not of Product Truth; the
    intelligence draft stays review-required and the snapshot is still a separate human
    act through the existing approval service;
  * it never invents a reviewer identity;
  * it never silently drops a field: everything the operator approved is either promoted
    or returned in `dropped_fields` with an explicit reason.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewFieldProvenanceInput,
)

# Registration draft key -> Product Intelligence review-draft column.
# Several registration lanes use different names for the same evidence, so each target
# lists its accepted source keys in priority order.
PROMOTION_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("product_description", ("product_knowledge_text", "product_knowledge_summary",
                             "product_description")),
    ("benefits_json", ("benefits_text", "benefits")),
    ("usp_json", ("usp_list", "usp", "usp_text")),
    ("usage_text", ("usage_text", "usage_summary")),
    ("ingredients_text", ("ingredients_text", "materials_text",
                          "materials_or_components")),
    ("warnings_text", ("warnings_text", "warnings_or_limitations")),
    ("target_customer_text", ("target_customer_text", "target_customer")),
    ("size_or_volume", ("size_or_volume",)),
    ("package_notes", ("package_notes",)),
    ("packaging_description", ("packaging_description",)),
    ("product_form_factor", ("product_form_factor",)),
)

# Columns that hold a list rather than free text.
_LIST_TARGETS = {"benefits_json", "usp_json"}

_SOURCE_URL_KEYS = ("source_url", "product_url", "tiktok_product_url",
                    "tiktok_shop_url")
_IMAGE_KEYS = ("image_url", "local_image_path")


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if _clean(v)]
    text = _clean(value)
    if not text:
        return []
    # registration stores multi-line evidence as one blob
    parts = [p.strip(" -•\t") for p in text.splitlines()]
    return [p for p in parts if p] or [text]


def _lookup(draft: Any, keys: Iterable[str]) -> tuple[str | None, Any, str | None]:
    """Return (source_key, value, origin) for the first populated key.

    Declared evidence outranks a canonical candidate: an operator-entered fact is
    stronger than a derived one.
    """
    declared: Mapping[str, Any] = getattr(draft, "declared_evidence_fields", {}) or {}
    candidates: Mapping[str, Any] = getattr(draft, "canonical_candidate_fields", {}) or {}
    for key in keys:
        if _clean(declared.get(key)) is not None:
            return key, declared.get(key), "DECLARED_EVIDENCE"
    for key in keys:
        if _clean(candidates.get(key)) is not None:
            return key, candidates.get(key), "CANONICAL_CANDIDATE"
    return None, None, None


def build_promotion_payload(draft: Any) -> dict[str, Any]:
    """Pure. Decide what would be promoted, and account for everything that would not."""
    approval: Mapping[str, bool] = getattr(draft, "approval_checklist", {}) or {}
    candidates: Mapping[str, Any] = getattr(draft, "canonical_candidate_fields", {}) or {}

    fields: dict[str, Any] = {}
    promoted: list[dict[str, str]] = []
    dropped: list[dict[str, str]] = []

    for target, source_keys in PROMOTION_MAP:
        source_key, value, origin = _lookup(draft, source_keys)
        if source_key is None:
            continue
        # A CANDIDATE needs explicit operator approval. Declared evidence is the
        # operator's own input and is promoted as-is.
        if origin == "CANONICAL_CANDIDATE" and not approval.get(source_key):
            dropped.append({"target": target, "source": source_key,
                            "reason": "CANDIDATE_NOT_APPROVED_BY_OPERATOR"})
            continue
        fields[target] = _as_list(value) if target in _LIST_TARGETS else _clean(value)
        promoted.append({"target": target, "source": source_key, "origin": origin})

    # Any approved candidate with no promotion target must be reported, never silently
    # lost. This is the exact hole the old commit response could not show.
    promoted_sources = {p["source"] for p in promoted}
    known_sources = {k for _t, keys in PROMOTION_MAP for k in keys}
    for key, approved in approval.items():
        if not approved or key in promoted_sources:
            continue
        if key in known_sources or _clean(candidates.get(key)) is None:
            continue
        dropped.append({"target": "", "source": key,
                        "reason": "NO_INTELLIGENCE_TARGET_FOR_APPROVED_FIELD"})

    declared: Mapping[str, Any] = getattr(draft, "declared_evidence_fields", {}) or {}
    source_urls = {k: _clean(declared.get(k)) for k in _SOURCE_URL_KEYS
                   if _clean(declared.get(k))}
    image_evidence = {k: _clean(declared.get(k)) for k in _IMAGE_KEYS
                      if _clean(declared.get(k))}

    return {
        "fields": fields,
        "source_urls_json": source_urls,
        "image_evidence_json": image_evidence,
        "promoted_fields": promoted,
        "dropped_fields": dropped,
        # carried so the intelligence claim gate starts from the registration verdict
        # rather than a default; `create_review_draft` re-derives it either way.
        "claim_risk_level": getattr(draft, "claim_risk_level", None),
        "claim_tokens_json": list(getattr(draft, "claim_tokens", []) or []),
    }


def build_provenance_inputs(
    draft: Any, payload: Mapping[str, Any],
) -> list[ProductIntelligenceReviewFieldProvenanceInput]:
    """One provenance row per promoted field, preserving where the value came from."""
    declared: Mapping[str, Any] = getattr(draft, "declared_evidence_fields", {}) or {}
    source_url = next((_clean(declared.get(k)) for k in _SOURCE_URL_KEYS
                       if _clean(declared.get(k))), None)
    rows: list[ProductIntelligenceReviewFieldProvenanceInput] = []
    for entry in payload["promoted_fields"]:
        target = entry["target"]
        value = payload["fields"].get(target)
        declared_value = ", ".join(value) if isinstance(value, list) else value
        # B-586-07: a lane may override these. A FastMoss workbook row or a TikTok link
        # import is IMPORTED marketplace evidence — calling it OPERATOR_DECLARED /
        # REGISTRATION_COMMIT asserts a human vouched for it when nobody did.
        lane_source_type = getattr(draft, "provenance_source_type", None)
        lane_evidence_kind = getattr(draft, "provenance_evidence_kind", None)
        lane_extraction = getattr(draft, "provenance_extraction_method", None)
        rows.append(ProductIntelligenceReviewFieldProvenanceInput(
            field_name=target,
            declared_value=declared_value,
            normalized_value=declared_value,
            source_type=lane_source_type or "REGISTRATION_COMMIT",
            source_url=source_url,
            source_lane=str(getattr(draft, "source_lane", "") or "") or None,
            evidence_kind=lane_evidence_kind or (
                "OPERATOR_DECLARED" if entry["origin"] == "DECLARED_EVIDENCE"
                else "OPERATOR_APPROVED_CANDIDATE"),
            extraction_method=lane_extraction or "REGISTRATION_PROMOTION",
            # Registration approval approves the VALUE, not Product Truth. The
            # intelligence layer still requires its own review.
            verification_status="PENDING_REVIEW",
            claim_risk_flag=str(getattr(draft, "claim_risk_level", "") or "") or None,
            reviewer_decision=("OPERATOR_APPROVED"
                               if entry["origin"] == "CANONICAL_CANDIDATE"
                               and lane_evidence_kind is None else None),
            reviewer_note=f"promoted from registration draft field '{entry['source']}'",
        ))
    return rows


def build_create_request(payload: Mapping[str, Any]) -> ProductIntelligenceReviewDraftCreateRequest:
    """Build the request for the EXISTING create_review_draft service.

    `review_status` is intentionally omitted where possible so the service derives it;
    no approval field is ever set here.
    """
    data: dict[str, Any] = dict(payload["fields"])
    if payload["source_urls_json"]:
        data["source_urls_json"] = dict(payload["source_urls_json"])
    if payload["image_evidence_json"]:
        data["image_evidence_json"] = dict(payload["image_evidence_json"])
    if payload.get("claim_tokens_json"):
        data["claim_tokens_json"] = list(payload["claim_tokens_json"])
    data["reviewer_note"] = (
        "Promoted from Smart Registration commit (B-08A-02). Values are operator-declared "
        "or operator-approved candidates; Product Truth review is still required."
    )
    return ProductIntelligenceReviewDraftCreateRequest(**data)


async def promote_registration_to_intelligence(product_id: str, draft: Any) -> dict[str, Any]:
    """Create the intelligence review draft + provenance for a freshly committed product.

    Returns a promotion receipt. Raises on failure so the caller can compensate — a
    canonical product must never be left without its promised intelligence record.
    """
    from agent.db import crud
    from agent.services import product_intelligence_review_draft_service as svc

    payload = build_promotion_payload(draft)
    # A draft whose approved evidence is purely identity / taxonomy / physics / commerce
    # promotes zero knowledge fields. Returning early here (the first version of this
    # service did) is NOT safe: the caller only treats an EXCEPTION as failure, so commit
    # returned COMMITTED with intelligence_draft_id=None and the product entered the
    # catalogue with no intelligence row at all — silently, and invisible to the KPI.
    # That is the same orphan condition this mission exists to remove.
    #
    # Instead the product still enters the review lifecycle, with an empty draft that
    # reads as "evidence required" rather than as nothing. `create_review_draft` derives
    # review_status DRAFT for a contentless payload, which is exactly right.
    minimal = not payload["fields"]

    created = await svc.create_review_draft(product_id, build_create_request(payload))
    draft_id = getattr(created, "draft_id", None)

    for row in build_provenance_inputs(draft, payload):
        await crud.create_product_intelligence_review_field_provenance(
            draft_id=draft_id,
            product_id=product_id,
            field_name=row.field_name,
            source_type=row.source_type,
            evidence_kind=row.evidence_kind,
            extraction_method=row.extraction_method,
            verification_status=row.verification_status,
            declared_value=row.declared_value,
            normalized_value=row.normalized_value,
            source_url=row.source_url,
            source_lane=row.source_lane,
            confidence_score=row.confidence_score,
            claim_risk_flag=row.claim_risk_flag,
            reviewer_decision=row.reviewer_decision,
            reviewer_note=row.reviewer_note,
        )

    return {
        "promoted": not minimal,
        # True when NO knowledge field was promotable. The product is still in the review
        # lifecycle; it just has nothing to review yet.
        "minimal_draft": minimal,
        "reason": "NO_PROMOTABLE_FIELDS" if minimal else None,
        "intelligence_draft_id": draft_id,
        "intelligence_review_status": getattr(created, "review_status", None),
        "intelligence_claim_gate": getattr(created, "claim_gate", None),
        "promoted_fields": [p["target"] for p in payload["promoted_fields"]],
        "promoted_field_count": len(payload["promoted_fields"]),
        "dropped_fields": payload["dropped_fields"],
        "provenance_rows": len(payload["promoted_fields"]),
        # never set by promotion; a snapshot remains a separate human approval
        "approved_snapshot_id": None,
    }
