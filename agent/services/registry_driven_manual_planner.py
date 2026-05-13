from __future__ import annotations

from typing import Any

from agent.db import crud
from agent.models.prompt_planning import PromptAssetBinding, PromptPlanningRequest
from agent.models.registry_driven_planning import (
    RegistryDrivenManualPlannerRequest,
    RegistryDrivenManualPlannerResponse,
)
from agent.services.offline_prompt_planner import create_offline_prompt_plan
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics
from agent.services.product_preflight import (
    build_product_preflight,
    evaluate_mapping_status,
    resolve_creative_profile,
)


ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT", "PROMPT_BLOCK_PLAN"}
ALLOWED_EXTENSION_STRATEGIES = {"NONE", "EXTEND_CONTINUITY", "INSERT_JUMP_TO", "MIXED"}
ALLOWED_TARGET_DURATIONS = {8, 16, 24, 32}

FORBIDDEN_DOM_KEYS = {
    "execute_dom",
    "dom_execution",
    "trigger_generation",
    "extend_button_click",
    "insert_button_click",
    "render_complete_detection",
    "execute_extension_runtime",
    "extension_runtime_execution",
}
FORBIDDEN_FLOW_KEYS = {"execute_flow", "flow_execution", "execute_flow_job", "smoke_execute_flow_job"}
FORBIDDEN_BATCH_KEYS = {"batch_execution", "execute_batch", "queue_batch", "run_batch"}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "write_canonical_registry",
    "auto_write_registry",
}
FORBIDDEN_PREVIEW_CANONICALIZATION_KEYS = {
    "mark_preview_only_as_canonical",
    "preview_to_canonical",
    "canonicalize_preview_value",
    "promote_preview_to_canonical",
}
FORBIDDEN_DIMENSION_INVENTION_KEYS = {"invent_product_dimensions", "invent_dimensions"}
FORBIDDEN_CLAIM_INVENTION_KEYS = {"invent_product_claims", "invent_claims"}
FORBIDDEN_EXTERNAL_TRUTH_PROOF_KEYS = {
    "external_registry_truth_verified",
    "mark_external_registry_verified",
    "treat_operator_pack_as_local_truth",
}
FORBIDDEN_MEDIA_PROOF_KEYS = {"product_media_upload_verified", "mark_product_media_upload_verified"}

EXTERNAL_REGISTRY_DEPENDENCIES = [
    "OPERATOR_PACK_DIR",
    "MASTER_IGNITION_TEMPLATE.yaml",
    "SCRIPT_REGISTRY_UNIFIED.yaml",
]


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | RegistryDrivenManualPlannerRequest,
) -> tuple[RegistryDrivenManualPlannerRequest, dict[str, Any]]:
    if isinstance(request_input, RegistryDrivenManualPlannerRequest):
        return request_input, request_input.model_dump()
    parsed = RegistryDrivenManualPlannerRequest.model_validate(request_input)
    return parsed, dict(request_input)


async def _resolve_product_seed(request: RegistryDrivenManualPlannerRequest) -> tuple[dict[str, Any] | None, str | None]:
    if request.product_id:
        existing = await crud.get_product(request.product_id)
        if not existing:
            return None, "PRODUCT_NOT_FOUND"
        if request.product_payload:
            merged = dict(existing)
            merged.update(request.product_payload)
            return merged, None
        return dict(existing), None

    if request.product_payload:
        return dict(request.product_payload), None

    return None, None


def _build_enriched_product(product_seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product_seed)
    payload["id"] = payload.get("id") or payload.get("product_id")

    mapping = resolve_product_mapping(
        product=payload,
        product_name=payload.get("raw_product_title")
        or payload.get("product_display_name")
        or payload.get("product_short_name"),
        source_hint=payload.get("source"),
    )
    payload.update(mapping)

    physics = resolve_product_physics(product=payload)
    payload.update(physics)

    creative_profile = resolve_creative_profile(payload)
    payload.update(creative_profile)

    payload.update(evaluate_mapping_status(payload))
    payload.update(evaluate_prompt_readiness(payload, physics))
    payload["preflight"] = build_product_preflight(payload)
    payload["product_id"] = payload.get("id") or payload.get("product_id")
    return payload


def _has_product_image(payload: dict[str, Any]) -> bool:
    return any(bool(payload.get(field)) for field in ("image_url", "local_image_path", "media_id"))


def _product_asset_source(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or "").upper()
    if source == "FASTMOSS":
        return "FASTMOSS"
    return "REGISTERED_PRODUCT"


def _normalize_asset_bindings(
    request: RegistryDrivenManualPlannerRequest,
    product: dict[str, Any] | None,
) -> list[PromptAssetBinding]:
    normalized: list[PromptAssetBinding] = [
        PromptAssetBinding.model_validate(binding) for binding in request.asset_bindings
    ]

    has_product_binding = any(binding.asset_role == "PRODUCT" for binding in normalized)
    if product and not has_product_binding and _has_product_image(product):
        normalized.append(
            PromptAssetBinding(
                asset_role="PRODUCT",
                asset_source=_product_asset_source(product),
                asset_id=product.get("id") or product.get("product_id") or None,
                source_url=product.get("image_url") or product.get("local_image_path") or None,
            )
        )
    return normalized


def _selected_fields(request: RegistryDrivenManualPlannerRequest) -> dict[str, Any]:
    return {
        "product_id": request.product_id,
        "avatar_id": request.avatar_id,
        "avatar_selection": request.avatar_selection,
        "wardrobe_id": request.wardrobe_id,
        "wardrobe_selection": request.wardrobe_selection,
        "headwear_style": request.headwear_style,
        "scene_context": request.scene_context,
        "camera_style": request.camera_style,
        "camera_behavior": request.camera_behavior,
        "trigger_id": request.trigger_id,
        "silo": request.silo,
        "formula": request.formula,
        "language": request.language,
        "platform": request.platform,
        "engine": request.engine,
        "destination_mode": request.destination_mode,
        "output_type": request.output_type,
        "target_duration_seconds": request.target_duration_seconds,
        "extension_strategy": request.extension_strategy,
    }


def _build_manual_context(
    request: RegistryDrivenManualPlannerRequest,
    product: dict[str, Any] | None,
) -> dict[str, Any]:
    context = {
        "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
        "avatar_id": request.avatar_id or request.avatar_selection,
        "wardrobe_id": request.wardrobe_id or request.wardrobe_selection,
        "headwear_style": request.headwear_style,
        "scene_context": request.scene_context or (product or {}).get("scene_context"),
        "camera_style": request.camera_style or (product or {}).get("camera_style"),
        "camera_behavior": request.camera_behavior or (product or {}).get("camera_behavior"),
        "trigger_id": request.trigger_id or (product or {}).get("trigger_id"),
        "silo": request.silo or (product or {}).get("silo"),
        "formula": request.formula or (product or {}).get("formula"),
        "language": request.language,
        "platform": request.platform,
        "engine": request.engine,
        "destination_mode": request.destination_mode,
        "output_type": request.output_type,
        "target_duration_seconds": request.target_duration_seconds,
        "extension_strategy": request.extension_strategy or "NONE",
        "product_context": {},
    }
    if product:
        context["product_context"] = {
            "product_id": product.get("id") or product.get("product_id"),
            "raw_product_title": product.get("raw_product_title"),
            "product_display_name": product.get("product_display_name"),
            "product_short_name": product.get("product_short_name"),
            "category": product.get("category"),
            "subcategory": product.get("subcategory"),
            "type": product.get("type"),
            "product_scale": product.get("product_scale"),
            "copywriting_angle": product.get("copywriting_angle"),
            "claim_risk_level": product.get("claim_risk_level"),
            "scene_context": product.get("scene_context"),
            "camera_style": product.get("camera_style"),
            "camera_behavior": product.get("camera_behavior"),
            "section_5_product_physics_prompt": product.get("section_5_product_physics_prompt"),
            "image_url": product.get("image_url"),
            "local_image_path": product.get("local_image_path"),
            "media_id": product.get("media_id"),
        }
    return context


def _build_provenance(product_seed: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "scope": "ROUND_3_REGISTRY_DRIVEN_MANUAL_ASSISTED_PLANNER_ONLY",
        "product_lookup": "crud.get_product" if product_seed and (product_seed.get("id") or product_seed.get("product_id")) else "inline_payload_or_none",
        "reused_services": [
            "agent.services.product_mapping.resolve_product_mapping",
            "agent.services.product_physics.resolve_product_physics",
            "agent.services.product_physics.evaluate_prompt_readiness",
            "agent.services.product_preflight.resolve_creative_profile",
            "agent.services.product_preflight.evaluate_mapping_status",
            "agent.services.product_preflight.build_product_preflight",
            "agent.services.offline_prompt_planner.create_offline_prompt_plan",
        ],
        "operator_slot_vocabulary_source": "agent.api.operator.BlueprintInput",
        "safe_read_only_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_product_driven_auto_service": False,
    }


def _build_compatibility_status(warnings: list[str]) -> dict[str, Any]:
    return {
        "status": "NOT_VERIFIED" if warnings else "UNASSESSED",
        "tuple_legality_validation": "NOT_VERIFIED",
        "canonical_vs_preview_isolation": "NOT_VERIFIED",
        "notes": [
            "Current repo does not prove one unified legality validator for full manual tuples.",
            "Current repo does not prove canonical-vs-preview isolation enforcement.",
        ],
    }


def _build_failure_response(
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
    manual_context: dict[str, Any],
    selected_fields: dict[str, Any],
    not_verified_fields: list[str],
    external_registry_dependencies: list[str],
    compatibility_status: dict[str, Any],
    planner_request: dict[str, Any] | None = None,
    planner_output: dict[str, Any] | None = None,
) -> RegistryDrivenManualPlannerResponse:
    return RegistryDrivenManualPlannerResponse(
        planning_status="FAIL",
        manual_context=manual_context,
        selected_fields=selected_fields,
        planner_request=planner_request,
        planner_output=planner_output,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        not_verified_fields=not_verified_fields,
        external_registry_dependencies=external_registry_dependencies,
        compatibility_status=compatibility_status,
    )


def _has_manual_slot_selection(request: RegistryDrivenManualPlannerRequest) -> bool:
    return any(
        bool(value)
        for value in [
            request.avatar_id,
            request.avatar_selection,
            request.headwear_style,
            request.camera_style,
            request.scene_context,
            request.formula,
            request.language,
            request.trigger_id,
            request.silo,
        ]
    )


async def create_registry_driven_manual_plan(
    request_input: dict[str, Any] | RegistryDrivenManualPlannerRequest,
) -> RegistryDrivenManualPlannerResponse:
    request, raw_request = _normalize_request(request_input)
    warnings: list[str] = []
    errors: list[str] = []
    not_verified_fields: list[str] = []
    external_registry_dependencies = list(EXTERNAL_REGISTRY_DEPENDENCIES)

    if raw_request.get("source_route") and raw_request.get("source_route") != "REGISTRY_DRIVEN_MANUAL_ASSISTED":
        _unique_append(errors, f"INVALID_INTERNAL_SOURCE_ROUTE:{raw_request.get('source_route')}")

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_3")
    if _has_truthy_flag(raw_request, FORBIDDEN_FLOW_KEYS):
        _unique_append(errors, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_3")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_3")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_3")
    if _has_truthy_flag(raw_request, FORBIDDEN_PREVIEW_CANONICALIZATION_KEYS):
        _unique_append(errors, "PREVIEW_ONLY_VALUE_CANNOT_BE_MARKED_CANONICAL")
    if _has_truthy_flag(raw_request, FORBIDDEN_DIMENSION_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED")
    if _has_truthy_flag(raw_request, FORBIDDEN_CLAIM_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED")
    if _has_truthy_flag(raw_request, FORBIDDEN_EXTERNAL_TRUTH_PROOF_KEYS):
        _unique_append(errors, "EXTERNAL_OPERATOR_PACK_TRUTH_CANNOT_BE_MARKED_LOCAL_VERIFIED")
    if _has_truthy_flag(raw_request, FORBIDDEN_MEDIA_PROOF_KEYS):
        _unique_append(errors, "PRODUCT_MEDIA_UPLOAD_VERIFICATION_NOT_PROVEN")

    if request.destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_DESTINATION_MODE:{request.destination_mode}")
    if request.output_type not in ALLOWED_OUTPUT_TYPES:
        _unique_append(errors, f"UNKNOWN_OUTPUT_TYPE:{request.output_type}")
    if request.extension_strategy not in ALLOWED_EXTENSION_STRATEGIES:
        _unique_append(errors, f"UNKNOWN_EXTENSION_STRATEGY:{request.extension_strategy}")
    if request.target_duration_seconds not in ALLOWED_TARGET_DURATIONS:
        _unique_append(errors, f"INVALID_TARGET_DURATION_SECONDS:{request.target_duration_seconds}")

    product_seed, product_error = await _resolve_product_seed(request)
    provenance = _build_provenance(product_seed)
    if product_error == "PRODUCT_NOT_FOUND":
        _unique_append(errors, "PRODUCT_NOT_FOUND")

    enriched_product = _build_enriched_product(product_seed) if product_seed else None
    manual_context = _build_manual_context(request, enriched_product)
    selected_fields = _selected_fields(request)

    _unique_append(warnings, "EXTERNAL_OPERATOR_PACK_REGISTRY_NOT_LOCAL_REPO_TRUTH")
    _unique_append(not_verified_fields, "external_operator_pack_registry")

    if request.wardrobe_id or request.wardrobe_selection:
        _unique_append(warnings, "WARDROBE_REGISTRY_NOT_PROVEN")
        _unique_append(not_verified_fields, "wardrobe_registry")

    if _has_manual_slot_selection(request):
        _unique_append(warnings, "SELECTED_MANUAL_INPUT_SLOTS_ARE_NOT_VERIFIED_REGISTRY_DATASETS")
        _unique_append(not_verified_fields, "manual_slot_registry_truth")

    _unique_append(warnings, "FULL_TUPLE_LEGALITY_VALIDATION_NOT_PROVEN")
    _unique_append(not_verified_fields, "tuple_legality_validation")

    _unique_append(warnings, "CANONICAL_VS_PREVIEW_ISOLATION_NOT_ENFORCED")
    _unique_append(not_verified_fields, "canonical_preview_isolation")

    if enriched_product:
        _unique_append(warnings, "PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED")
        _unique_append(not_verified_fields, "product_dimensions")
        _unique_append(warnings, "PRODUCT_UPLOAD_TO_FLOW_MEDIA_HANDOFF_NOT_IMPLEMENTED")
        _unique_append(not_verified_fields, "product_media_handoff")
        _unique_append(warnings, "CLAIM_BOUNDARY_NOT_HARD_ENFORCED_END_TO_END")
        _unique_append(not_verified_fields, "claim_boundary_enforcement")
        if not _has_product_image(enriched_product):
            _unique_append(warnings, "PRODUCT_IMAGE_MISSING")
            _unique_append(not_verified_fields, "product_image")

    _unique_append(warnings, "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE")

    if request.destination_mode in {"INGREDIENTS", "IMAGE"}:
        _unique_append(warnings, "PRODUCT_SLOT_NOT_FIRST_CLASS_IN_CURRENT_UI_SERVICE")

    compatibility_status = _build_compatibility_status(warnings)

    if errors:
        return _build_failure_response(
            errors=errors,
            warnings=warnings,
            provenance=provenance,
            manual_context=manual_context,
            selected_fields=selected_fields,
            not_verified_fields=not_verified_fields,
            external_registry_dependencies=external_registry_dependencies,
            compatibility_status=compatibility_status,
        )

    planner_request_model = PromptPlanningRequest(
        source_route="REGISTRY_DRIVEN_MANUAL_ASSISTED",
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        product_id=enriched_product.get("id") if enriched_product else request.product_id,
        asset_bindings=_normalize_asset_bindings(request, enriched_product),
        target_duration_seconds=request.target_duration_seconds,
        block_duration_seconds=8,
        extension_strategy=request.extension_strategy or "NONE",
    )
    planner_request_payload = planner_request_model.model_dump()
    planner_output = await create_offline_prompt_plan(planner_request_model)
    planner_output_payload = planner_output.model_dump()

    for warning in planner_output.warnings:
        _unique_append(warnings, warning)
    for error in planner_output.errors:
        _unique_append(errors, error)

    planning_status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return RegistryDrivenManualPlannerResponse(
        planning_status=planning_status,
        manual_context=manual_context,
        selected_fields=selected_fields,
        planner_request=planner_request_payload,
        planner_output=planner_output_payload,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        not_verified_fields=not_verified_fields,
        external_registry_dependencies=external_registry_dependencies,
        compatibility_status=compatibility_status,
    )
