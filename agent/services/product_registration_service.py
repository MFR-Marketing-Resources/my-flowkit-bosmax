from __future__ import annotations

from typing import Any

from agent.db import crud
from agent.models.product_registration import (
    ProductRegistrationEvaluateRequest,
    ProductRegistrationEvaluateResponse,
)
from agent.services.product_intelligence_service import (
    inject_product_intelligence_fields,
    resolve_product_intelligence_profile,
)
from agent.services.product_mapping import normalize_mapping_text
from agent.services.product_physics import resolve_product_physics
from agent.services.product_truth_service import ProductTruthService


AFFILIATE_SOURCES = {"FASTMOSS", "TIKTOKSHOP", "IMPORTED"}
STRONG_SOURCE_ANCHORS = {
    "PRESENT",
    "SOURCE_ANCHOR_PRESENT",
    "SOURCE_ANCHOR_PARTIAL",
    "SOURCE_ANCHOR_VERIFIED_FROM_RAW_SOURCE",
}
REVIEW_SOURCE_ANCHORS = {
    "SOURCE_ANCHOR_MISSING",
    "SOURCE_ANCHOR_UNVERIFIED",
    "SOURCE_ANCHOR_KEYWORD_DERIVED",
    "SOURCE_ANCHOR_RAW_SOURCE_NOT_AVAILABLE",
    "WEAK_FILE_HINT_ONLY",
    "COLUMN_NOT_FOUND",
}
TAXONOMY_CANONICAL_FIELDS = [
    "group",
    "sub_group",
    "type_of_product",
    "bosmax_product_family",
]
CLAIM_FIELD_NAMES = ["claim_gate", "claim_tokens", "claims"]
VISUAL_FIELD_NAMES = [
    "package_form",
    "physical_state",
    "product_scale_class",
    "product_scale",
    "recommended_grip",
    "hand_object_interaction",
]
DIMENSION_FIELD_NAMES = [
    "length_cm",
    "width_cm",
    "height_cm",
    "depth_cm",
    "diameter_cm",
    "volume_ml",
    "net_weight_g",
    "product_dimensions",
    "dimensions",
]
PHYSICS_FIELD_NAMES = [
    "physics_class",
    "handling_notes",
    "camera_handling_notes",
    "material_behavior",
    "surface_behavior",
    "section_5_product_physics_prompt",
]


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return dict(value or {})


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _normalize_compare(value: Any) -> str:
    return normalize_mapping_text(value)


def _seed_defaults(seed: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(seed)
    title = (
        enriched.get("raw_product_title")
        or enriched.get("product_display_name")
        or enriched.get("product_short_name")
        or "UNNAMED_PRODUCT"
    )
    enriched["raw_product_title"] = title
    enriched["product_display_name"] = enriched.get("product_display_name") or title
    enriched["product_short_name"] = enriched.get("product_short_name") or title[:80]
    enriched["source"] = str(enriched.get("source") or "MANUAL").upper()
    enriched["id"] = enriched.get("id") or enriched.get("product_id") or "registration-candidate"
    return enriched


async def _resolve_candidate_seed(
    request: ProductRegistrationEvaluateRequest,
) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    declared = dict(request.manual_declared_fields or {})
    if request.product_id:
        existing = await crud.get_product(request.product_id)
        if not existing:
            return None, declared, "PRODUCT_NOT_FOUND"
        seed = dict(existing)
        if request.product_payload:
            declared.update(dict(request.product_payload))
        return _seed_defaults(seed), declared, None
    if request.product_payload:
        return _seed_defaults(dict(request.product_payload)), declared, None
    return None, declared, "PRODUCT_REGISTRATION_CONTEXT_REQUIRED"


def _manual_declared_fields(seed: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    fields: list[str] = list(declared.keys())
    if str(seed.get("source") or "").upper() == "MANUAL":
        for key in (
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "brand",
            "category",
            "subcategory",
            "type",
            "shop_name",
            "claim_tokens",
            "product_scale",
            "package_form",
            "physical_state",
            *DIMENSION_FIELD_NAMES,
        ):
            if seed.get(key) not in (None, "", []):
                fields.append(key)
    return _unique(fields)


def _truth_status(truth_profile: Any) -> tuple[str, str, str]:
    recon = truth_profile.reconciliation
    source_anchors = truth_profile.source_anchors
    if recon.confidence_label == "HIGH":
        status = "SOURCE_ANCHORED_RECONCILED"
    elif recon.confidence_label == "MEDIUM":
        status = "SOURCE_ANCHORED_PRELIMINARY"
    elif source_anchors.source_anchor_status == "SOURCE_ANCHOR_UNVERIFIED":
        status = "MANUAL_DECLARED_PENDING_RECONCILIATION"
    else:
        status = "TRUTH_REVIEW_REQUIRED"
    return status, recon.authority_decision, source_anchors.source_anchor_status


def _dimension_truth_status(truth_profile: Any) -> str:
    dims = truth_profile.spec_evidence.dimension_normalized_cm
    if dims.display:
        return "SPEC_DERIVED_NOT_VERIFIED"
    return "DIMENSIONS_NOT_VERIFIED"


def _scale_truth(product: dict[str, Any], truth_profile: Any, physics: dict[str, Any]) -> tuple[str, str | None]:
    prompt = physics.get("section_5_product_physics_prompt") or None
    if not prompt:
        return "SCALE_NOT_FOUND", None
    if truth_profile.spec_evidence.dimension_normalized_cm.display:
        return "DERIVED_RELATIVE_SCALE", prompt
    return "DERIVED_RELATIVE_SCALE", prompt


def _physics_truth_status(truth_profile: Any, image_analysis: dict[str, Any]) -> str:
    visual_status = str(image_analysis.get("status") or "")
    visual_confidence = str(image_analysis.get("visual_confidence") or "")
    if visual_status == "ANALYZED" and visual_confidence == "HIGH":
        return "IMAGE_CORROBORATED_DERIVED"
    if truth_profile.source_anchors.source_anchor_status in STRONG_SOURCE_ANCHORS:
        return "SOURCE_ANCHORED_DERIVED"
    return "DERIVED_NOT_CANONICAL"


def _append_compare_conflict(
    *,
    field_name: str,
    manual_value: Any,
    authority_value: Any,
    blocked_fields: list[str],
    human_review_fields: list[str],
    warnings: list[str],
) -> None:
    if manual_value in (None, "", []):
        return
    if authority_value in (None, "", []):
        human_review_fields.append(field_name)
        warnings.append(f"MANUAL_DECLARED_{field_name.upper()}_HAS_NO_AUTHORITY_MATCH")
        return
    if _normalize_compare(manual_value) != _normalize_compare(authority_value):
        blocked_fields.append(field_name)
        warnings.append(f"MANUAL_DECLARED_{field_name.upper()}_CONFLICTS_WITH_AUTHORITY")


def _claimed_field_list(declared: dict[str, Any]) -> list[str]:
    present: list[str] = []
    for key in CLAIM_FIELD_NAMES:
        value = declared.get(key)
        if value not in (None, "", []):
            present.append(key)
    return present


def _dimension_field_list(seed: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    present: list[str] = []
    for key in DIMENSION_FIELD_NAMES:
        value = declared.get(key, seed.get(key))
        if value not in (None, "", []):
            present.append(key)
    return _unique(present)


def _visual_field_list(seed: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    present: list[str] = []
    for key in VISUAL_FIELD_NAMES:
        value = declared.get(key, seed.get(key))
        if value not in (None, "", []):
            present.append(key)
    return _unique(present)


def _physics_field_list(seed: dict[str, Any], declared: dict[str, Any]) -> list[str]:
    present: list[str] = []
    for key in PHYSICS_FIELD_NAMES:
        value = declared.get(key, seed.get(key))
        if value not in (None, "", []):
            present.append(key)
    return _unique(present)


async def evaluate_product_registration(
    request_input: dict[str, Any] | ProductRegistrationEvaluateRequest,
) -> ProductRegistrationEvaluateResponse:
    request = (
        request_input
        if isinstance(request_input, ProductRegistrationEvaluateRequest)
        else ProductRegistrationEvaluateRequest.model_validate(request_input)
    )
    seed, declared, resolution_error = await _resolve_candidate_seed(request)
    if resolution_error or not seed:
        return ProductRegistrationEvaluateResponse(
            registration_status="BLOCK_REGISTRATION",
            write_back_allowed=False,
            write_back_performed=False,
            dry_run_only=True,
            registration_errors=[resolution_error or "PRODUCT_REGISTRATION_CONTEXT_REQUIRED"],
            no_db_write_reason="WRITE_BACK_NOT_ENABLED_IN_THIS_PR",
            provenance={
                "scope": "PRODUCT_REGISTRATION_AUTHORITY_WRITE_BACK_GATE_PHASE_4",
                "preview_only": True,
                "write_back_enabled": False,
            },
        )

    truth_profile = ProductTruthService.build_computed_profile(seed)
    truth_status, truth_authority_source, source_anchor_status = _truth_status(truth_profile)
    intelligence_profile = _as_dict(resolve_product_intelligence_profile(seed))
    enriched_seed = inject_product_intelligence_fields(dict(seed), intelligence_profile)
    physics = resolve_product_physics(product=enriched_seed)
    image_analysis = _as_dict(intelligence_profile.get("image_analysis") or {})

    canonical_fields_allowed: list[str] = []
    blocked_fields: list[str] = []
    human_review_fields: list[str] = []
    required_evidence: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    declared_evidence_fields = _manual_declared_fields(seed, declared)

    affiliate_risk = str(seed.get("source") or "").upper() in AFFILIATE_SOURCES
    owned_product_lane_status = "OWNED_LANE_PREVIEW_ONLY"
    registration_status = "ALLOW_REGISTRATION_PREVIEW"

    if affiliate_risk:
        owned_product_lane_status = "AFFILIATE_SOURCE_REVIEW_REQUIRED"
        human_review_fields.extend(TAXONOMY_CANONICAL_FIELDS)
        warnings.append("AFFILIATE_SOURCE_CONTAMINATION_RISK")
        registration_status = "HUMAN_REVIEW_REQUIRED"

    source_anchor_upper = str(source_anchor_status or "").upper()
    if source_anchor_upper in REVIEW_SOURCE_ANCHORS or truth_status == "TRUTH_REVIEW_REQUIRED":
        human_review_fields.extend(TAXONOMY_CANONICAL_FIELDS)
        required_evidence.append("SOURCE_ANCHORED_PRODUCT_EVIDENCE")
        warnings.append("SOURCE_ANCHOR_REVIEW_REQUIRED")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"

    mapping_confidence = str(intelligence_profile.get("confidence") or "LOW")
    mapping_v2_status = str(intelligence_profile.get("intelligence_status") or "NEEDS_REVIEW")
    taxonomy_conflict = bool(intelligence_profile.get("taxonomy_conflict"))
    taxonomy_conflict_reason = intelligence_profile.get("taxonomy_conflict_reason")
    resolved_family = str(intelligence_profile.get("bosmax_product_family") or "UNKNOWN_REVIEW_REQUIRED")
    if (
        mapping_confidence in {"LOW", "NEEDS_REVIEW"}
        or mapping_v2_status == "NEEDS_REVIEW"
        or taxonomy_conflict
        or resolved_family == "UNKNOWN_REVIEW_REQUIRED"
    ):
        human_review_fields.extend(TAXONOMY_CANONICAL_FIELDS)
        warnings.append("MAPPING_V2_REVIEW_REQUIRED")
        if taxonomy_conflict:
            warnings.append("MAPPING_TAXONOMY_CONFLICT_PRESENT")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"
    elif not affiliate_risk and source_anchor_upper in STRONG_SOURCE_ANCHORS:
        canonical_fields_allowed.extend(TAXONOMY_CANONICAL_FIELDS)

    manual_compare_targets = {
        "raw_product_title": seed.get("raw_product_title"),
        "product_display_name": seed.get("product_display_name"),
        "category": truth_profile.source_anchors.source_category or truth_profile.final_output_preview.final_group,
        "subcategory": truth_profile.source_anchors.source_subcategory or truth_profile.final_output_preview.final_sub_group,
        "type": truth_profile.source_anchors.source_product_type or truth_profile.final_output_preview.final_type_of_product,
    }
    for field_name, authority_value in manual_compare_targets.items():
        _append_compare_conflict(
            field_name=field_name,
            manual_value=declared.get(field_name),
            authority_value=authority_value,
            blocked_fields=blocked_fields,
            human_review_fields=human_review_fields,
            warnings=warnings,
        )
    if blocked_fields:
        registration_status = "BLOCK_REGISTRATION"

    claim_gate = str(intelligence_profile.get("claim_gate") or "CLAIM_REVIEW_REQUIRED")
    claim_tokens = list(intelligence_profile.get("claim_tokens") or [])
    claim_review = claim_gate != "CLAIM_SAFE"
    declared_claim_fields = _claimed_field_list(declared)
    if claim_review or declared_claim_fields:
        blocked_fields.extend(declared_claim_fields or CLAIM_FIELD_NAMES[:2])
        human_review_fields.extend(["claim_gate", "claim_tokens"])
        warnings.append("CLAIM_GATE_REVIEW_REQUIRED" if claim_gate == "CLAIM_REVIEW_REQUIRED" else "CLAIM_GATE_BLOCKED")
        if claim_gate == "CLAIM_BLOCKED":
            registration_status = "BLOCK_REGISTRATION"
        elif registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"

    image_analysis_status = str(image_analysis.get("status") or "IMAGE_MISSING")
    image_analysis_provider = str(image_analysis.get("provider") or "not_configured")
    image_visual_confidence = str(image_analysis.get("visual_confidence") or "NOT_VERIFIED")
    visual_fields = _visual_field_list(seed, declared)
    if image_analysis_status != "ANALYZED" or image_visual_confidence == "NOT_VERIFIED":
        human_review_fields.extend(visual_fields or VISUAL_FIELD_NAMES)
        required_evidence.append("SEMANTIC_IMAGE_OR_OCR_PROOF")
        warnings.append("IMAGE_ANALYSIS_NOT_CANONICAL")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"

    dimension_fields = _dimension_field_list(seed, declared)
    dimension_truth_status = _dimension_truth_status(truth_profile)
    if dimension_truth_status != "VERIFIED_DIMENSIONS":
        blocked_fields.extend(dimension_fields)
        required_evidence.append("VERIFIED_DIMENSIONS_OR_SIZE_SPEC")
        warnings.append("DIMENSION_PROOF_REQUIRED")
        if dimension_fields:
            registration_status = "BLOCK_REGISTRATION"

    scale_truth_status, product_scale_prompt = _scale_truth(enriched_seed, truth_profile, physics)
    if scale_truth_status != "VERIFIED_DIMENSION_SCALE":
        human_review_fields.extend(["product_scale", "product_scale_prompt"])
        required_evidence.append("PRODUCT_SCALE_VERIFICATION")
        warnings.append("PRODUCT_SCALE_DERIVED_NOT_CANONICAL")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"

    physics_truth_status = _physics_truth_status(truth_profile, image_analysis)
    physics_fields = _physics_field_list(seed, declared)
    if physics_truth_status != "SOURCE_SPEC_VERIFIED":
        human_review_fields.extend(physics_fields or PHYSICS_FIELD_NAMES)
        warnings.append("PRODUCT_PHYSICS_DERIVED_NOT_CANONICAL")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "HUMAN_REVIEW_REQUIRED"

    if request.write_back_requested or not request.dry_run_only:
        errors.append("WRITE_BACK_NOT_ENABLED_IN_THIS_PR")
        if registration_status != "BLOCK_REGISTRATION":
            registration_status = "BLOCK_REGISTRATION"

    response = ProductRegistrationEvaluateResponse(
        registration_status=registration_status,
        write_back_allowed=False,
        write_back_performed=False,
        dry_run_only=True,
        product_truth_status=truth_status,
        truth_authority_source=truth_authority_source,
        source_anchor_status=source_anchor_status,
        mapping_v2_status=mapping_v2_status,
        mapping_confidence=mapping_confidence,
        taxonomy_conflict=taxonomy_conflict,
        taxonomy_conflict_reason=taxonomy_conflict_reason,
        owned_product_lane_status=owned_product_lane_status,
        affiliate_source_contamination_risk=affiliate_risk,
        canonical_fields_allowed=_unique(canonical_fields_allowed),
        declared_evidence_fields=_unique(declared_evidence_fields),
        blocked_fields=_unique(blocked_fields),
        human_review_fields=_unique(human_review_fields),
        required_evidence=_unique(required_evidence),
        claim_gate=claim_gate,
        claim_tokens=claim_tokens,
        claim_safety_requires_human_review=claim_review,
        scale_truth_status=scale_truth_status,
        product_scale_prompt=product_scale_prompt,
        dimension_truth_status=dimension_truth_status,
        image_analysis_status=image_analysis_status,
        image_analysis_provider=image_analysis_provider,
        image_analysis_visual_confidence=image_visual_confidence,
        physics_truth_status=physics_truth_status,
        registration_warnings=_unique(warnings),
        registration_errors=_unique(errors),
        provenance={
            "scope": "PRODUCT_REGISTRATION_AUTHORITY_WRITE_BACK_GATE_PHASE_4",
            "preview_only": True,
            "write_back_enabled": False,
            "target_lane": request.target_lane,
            "product_lookup": "crud.get_product" if request.product_id else "inline_payload",
            "reused_services": [
                "agent.services.product_truth_service.ProductTruthService.build_computed_profile",
                "agent.services.product_intelligence_service.resolve_product_intelligence_profile",
                "agent.services.product_intelligence_service.inject_product_intelligence_fields",
                "agent.services.product_physics.resolve_product_physics",
            ],
            "declared_manual_fields": _unique(declared_evidence_fields),
        },
        no_db_write_reason="WRITE_BACK_NOT_ENABLED_IN_THIS_PR",
    )
    return response
