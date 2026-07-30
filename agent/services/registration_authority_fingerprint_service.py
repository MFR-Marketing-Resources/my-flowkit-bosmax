from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.models.product_registration import RegistrationReviewDraft
from agent.services.registration_consistency_service import (
    evaluate_registration_consistency,
)


AUTHORITY_VERSIONS = {
    "evidence_quality": "registration_evidence_quality_v1",
    "product_intelligence": "product_intelligence_boundary_v2",
    "taxonomy_resolution": "source_taxonomy_precedence_v2",
    "consistency": "registration_consistency_v1",
    "hook_cta": "registration_hook_cta_reconciled_v2",
}
_IMAGE_DEPENDENT_MODES = {
    "IMG",
    "I2V",
    "F2V",
    "Images",
    "Ingredients",
    "Frames",
    "ProductAssetGenerator",
}


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def authority_fingerprint(draft: RegistrationReviewDraft) -> str:
    taxonomy = (
        draft.strategy_taxonomy.model_dump(mode="json")
        if draft.strategy_taxonomy is not None
        else None
    )
    return _digest(
        {
            "declared_evidence_fields": draft.declared_evidence_fields,
            "canonical_candidate_fields": draft.canonical_candidate_fields,
            "strategy_taxonomy": taxonomy,
            "authority_versions": AUTHORITY_VERSIONS,
        }
    )


def hook_cta_input_fingerprint(draft: RegistrationReviewDraft) -> str:
    candidates = draft.canonical_candidate_fields
    evidence = draft.declared_evidence_fields
    return _digest(
        {
            "name": candidates.get("normalized_name") or evidence.get("product_name"),
            "benefits": candidates.get("benefits"),
            "target_customer": candidates.get("target_customer"),
            "usage_summary": candidates.get("usage_summary"),
            "category": candidates.get("category"),
            "family": candidates.get("bosmax_product_family"),
            "copy_formula": candidates.get("copy_formula"),
            "claim_gate": draft.claim_gate,
        }
    )


def _enforce_semantic_readiness(draft: RegistrationReviewDraft) -> None:
    analysis_status = str(
        draft.system_inferred_fields.get("image_analysis_status") or "IMAGE_MISSING"
    ).upper()
    visual_confidence = str(
        draft.system_inferred_fields.get("image_analysis_visual_confidence")
        or "NOT_VERIFIED"
    ).upper()
    semantic_ready = analysis_status == "ANALYZED" and visual_confidence in {
        "HIGH",
        "MEDIUM",
    }
    if semantic_ready:
        return
    for mode, raw in list(draft.readiness_by_mode.items()):
        if mode not in _IMAGE_DEPENDENT_MODES:
            continue
        detail = (
            "SEMANTIC_IMAGE_ANALYSIS_REQUIRED: an image reference exists but "
            f"semantic vision is {analysis_status}/{visual_confidence}."
        )
        if hasattr(raw, "model_copy"):
            draft.readiness_by_mode[mode] = raw.model_copy(
                update={"status": "BLOCKED", "detail": detail}
            )
        else:
            readiness = dict(raw or {})
            readiness["status"] = "BLOCKED"
            readiness["detail"] = detail
            draft.readiness_by_mode[mode] = readiness


def stamp_authority_fingerprint(
    draft: RegistrationReviewDraft,
) -> RegistrationReviewDraft:
    consistency = evaluate_registration_consistency(
        draft.canonical_candidate_fields
    )
    draft.consistency_status = consistency.status
    draft.consistency_issues = consistency.issue_codes
    if consistency.issue_codes:
        draft.review_status = "NEEDS_HUMAN_REVIEW"
        draft.registration_gate_status = "NEEDS_HUMAN_REVIEW"
        draft.human_review_fields = list(
            dict.fromkeys(draft.human_review_fields + ["consistency_review"])
        )
    _enforce_semantic_readiness(draft)
    draft.authority_versions = dict(AUTHORITY_VERSIONS)
    draft.hook_cta_input_fingerprint = hook_cta_input_fingerprint(draft)
    draft.authority_fingerprint = authority_fingerprint(draft)
    draft.recompute_required_reasons = []
    draft.draft_freshness_status = "FRESH"
    return draft


def apply_authority_freshness(
    draft: RegistrationReviewDraft,
) -> RegistrationReviewDraft:
    reasons: list[str] = []
    if not draft.authority_fingerprint:
        reasons.append("AUTHORITY_FINGERPRINT_MISSING")
    elif draft.authority_fingerprint != authority_fingerprint(draft):
        reasons.append("AUTHORITY_INPUT_FINGERPRINT_CHANGED")
    if draft.authority_versions != AUTHORITY_VERSIONS:
        reasons.append("AUTHORITY_RESOLVER_VERSION_CHANGED")
    if reasons:
        draft.draft_freshness_status = "STALE_RECOMPUTE_REQUIRED"
        draft.recompute_required_reasons = reasons
        draft.registration_gate_status = "NEEDS_HUMAN_REVIEW"
    return draft
