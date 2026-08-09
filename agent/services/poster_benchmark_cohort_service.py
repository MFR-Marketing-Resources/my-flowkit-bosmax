"""Read-only readiness rules for the Phase E1 Campaign benchmark cohort.

This module does not resolve or create assets and has no provider boundary.  It
only scores already-scouted catalog evidence and fails closed when a required
authority is absent.  In particular, volume or pixel geometry is never
converted into an invented physical measurement.
"""
from __future__ import annotations

from typing import Any


BENCHMARK_EXP_IDS = ("EXP-01", "EXP-02", "EXP-03", "EXP-04", "EXP-05")
PRODUCTION_COPY_SCORE_THRESHOLD = 72


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def _physical_scale_ready(candidate: dict[str, Any]) -> bool:
    evidence = candidate.get("physical_measurement_evidence")
    if not isinstance(evidence, dict):
        return False
    # A volume is useful context but is not a bottle/package bounding box.  A
    # candidate can only pass this gate with authored dimensions or an
    # approved reference that explicitly carries known physical dimensions.
    dimensions = (
        evidence.get("physical_width_mm"),
        evidence.get("physical_height_mm"),
        evidence.get("physical_depth_mm"),
    )
    if all(isinstance(value, (int, float)) and float(value) > 0 for value in dimensions):
        return True
    return _truthy(evidence.get("approved_scale_reference_with_known_dimensions"))


def assess_benchmark_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a serialisable, fail-closed readiness decision for one candidate."""

    blockers = [str(item) for item in candidate.get("blockers") or [] if _clean(item)]
    if not _truthy(candidate.get("product_exists")):
        blockers.append("PRODUCT_NOT_FOUND")
    if not _truthy(candidate.get("active_eligible")):
        blockers.append("PRODUCT_NOT_ACTIVE_OR_ELIGIBLE")
    if not _truthy(candidate.get("approved_snapshot")):
        blockers.append("APPROVED_INTELLIGENCE_REQUIRED")
    if not _truthy(candidate.get("copy_eligible")):
        blockers.append("COPY_ELIGIBLE_REQUIRED")
    if not _clean(candidate.get("approved_copy_set_id")):
        blockers.append("APPROVED_POSTER_COPY_SET_REQUIRED")
    try:
        copy_score = int(candidate.get("copy_route_score") or 0)
    except (TypeError, ValueError):
        copy_score = 0
    if copy_score < PRODUCTION_COPY_SCORE_THRESHOLD:
        blockers.append(f"COPY_SCORE_BELOW_THRESHOLD:{copy_score}")
    if not _truthy(candidate.get("reference_pack_approved")):
        blockers.append("REFERENCE_PACK_APPROVAL_REQUIRED")
    if not _truthy(candidate.get("canonical_reference_available")):
        blockers.append("CANONICAL_PRODUCT_REFERENCE_REQUIRED")
    roles = {str(role) for role in candidate.get("available_reference_roles") or []}
    if "PRODUCT_CANONICAL" not in roles:
        blockers.append("PRODUCT_CANONICAL_REFERENCE_ROLE_REQUIRED")
    if candidate.get("label_logo_required") and not {
        "PRODUCT_LABEL_CROP",
        "PRODUCT_LOGO_CROP",
    }.issubset(roles):
        blockers.append("LABEL_LOGO_REFERENCE_ROLES_REQUIRED")
    if not _truthy(candidate.get("claim_provenance_approved")):
        blockers.append("APPROVED_CLAIM_PROVENANCE_REQUIRED")
    if not _truthy(candidate.get("campaign_brief_ready")):
        blockers.append("CAMPAIGN_DESIGN_BRIEF_READY_REQUIRED")
    if not _physical_scale_ready(candidate):
        blockers.append("PHYSICAL_SCALE_EVIDENCE_UNVERIFIED")
    if not _truthy(candidate.get("human_review_path_available", True)):
        blockers.append("HUMAN_REVIEW_PATH_REQUIRED")
    blockers = sorted(set(blockers))
    return {
        **candidate,
        "copy_route_score": copy_score,
        "blockers": blockers,
        "readiness_decision": "READY" if not blockers else "BLOCKED",
        "physical_measurement_evidence": candidate.get("physical_measurement_evidence") or {},
    }


def rank_benchmark_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank candidates without making a blocked candidate appear ready."""

    assessed = [assess_benchmark_candidate(candidate) for candidate in candidates]

    def key(item: dict[str, Any]) -> tuple[int, int, int, str]:
        evidence = item.get("physical_measurement_evidence") or {}
        authored_dimensions = sum(
            isinstance(evidence.get(name), (int, float)) and float(evidence.get(name)) > 0
            for name in ("physical_width_mm", "physical_height_mm", "physical_depth_mm")
        )
        ready_fields = sum(
            _truthy(item.get(name))
            for name in (
                "active_eligible",
                "approved_snapshot",
                "copy_eligible",
                "reference_pack_approved",
                "canonical_reference_available",
                "claim_provenance_approved",
                "campaign_brief_ready",
            )
        )
        return (
            0 if item["readiness_decision"] == "READY" else 1,
            -authored_dimensions,
            -ready_fields,
            _clean(item.get("display_name")).casefold(),
        )

    return sorted(assessed, key=key)


def select_recommendations(
    candidates_by_exp: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any] | None]:
    """Select exactly one READY candidate per class, otherwise ``None``."""

    recommendations: dict[str, dict[str, Any] | None] = {}
    for exp_id in BENCHMARK_EXP_IDS:
        ranked = rank_benchmark_candidates(candidates_by_exp.get(exp_id, []))
        recommendations[exp_id] = next(
            (item for item in ranked if item["readiness_decision"] == "READY"),
            None,
        )
    return recommendations


def build_phase_e2_operation_plan(
    recommendations: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    """Build a dry-run plan; this function intentionally cannot submit work."""

    operations = []
    blockers = []
    for exp_id in BENCHMARK_EXP_IDS:
        candidate = recommendations.get(exp_id)
        if candidate is None:
            blockers.append(f"BENCHMARK_CANDIDATE_NOT_READY:{exp_id}:NO_READY_CANDIDATE")
            operations.append(
                {
                    "exp_id": exp_id,
                    "status": "BLOCKED_NOT_EXECUTABLE",
                    "maximum_provider_operations": 0,
                    "max_retry_operations": 0,
                }
            )
            continue
        operations.append(
            {
                "exp_id": exp_id,
                "product_id": candidate.get("product_id"),
                "status": "PLANNED_NOT_SUBMITTED",
                "model": "NANO_BANANA_PRO",
                "output_intent": "CLEAN_KEY_VISUAL",
                "raw_key_visual_count": 1,
                "deterministic_poster_variants": 3,
                "maximum_provider_operations": 1,
                "max_retry_operations": 0,
                "estimated_credit_exposure": "NOT VERIFIED",
            }
        )
    return {
        "provider": "GOOGLE_FLOW",
        "status": "READY_FOR_AUTHORIZATION" if not blockers else "COHORT_INCOMPLETE",
        "live_benchmark_authorization_required": True,
        "credit_exposure": "NOT VERIFIED",
        "maximum_future_provider_operations": 5,
        "provider_operation_count": 0,
        "max_retry_operations": 0,
        "hidden_retries": False,
        "operations": operations,
        "blockers": sorted(set(blockers)),
    }
