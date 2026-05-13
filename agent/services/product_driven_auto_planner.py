from __future__ import annotations

from typing import Any

from agent.db import crud
from agent.models.product_driven_planning import (
    ProductDrivenAutoPlannerRequest,
    ProductDrivenAutoPlannerResponse,
)
from agent.models.prompt_planning import PromptAssetBinding, PromptPlanningRequest
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
    "execute_flow",
    "flow_execution",
    "trigger_generation",
    "extend_button_click",
    "insert_button_click",
    "render_complete_detection",
}
FORBIDDEN_BATCH_KEYS = {"batch_execution", "execute_batch", "queue_batch", "run_batch"}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "write_canonical_registry",
    "auto_write_registry",
}
FORBIDDEN_DIMENSION_INVENTION_KEYS = {"invent_product_dimensions", "invent_dimensions"}
FORBIDDEN_CLAIM_INVENTION_KEYS = {"invent_product_claims", "invent_claims"}
FORBIDDEN_MEDIA_PROOF_KEYS = {"product_media_upload_verified", "mark_product_media_upload_verified"}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | ProductDrivenAutoPlannerRequest,
) -> tuple[ProductDrivenAutoPlannerRequest, dict[str, Any]]:
    if isinstance(request_input, ProductDrivenAutoPlannerRequest):
        return request_input, request_input.model_dump()
    parsed = ProductDrivenAutoPlannerRequest.model_validate(request_input)
    return parsed, dict(request_input)


async def _resolve_product_seed(request: ProductDrivenAutoPlannerRequest) -> tuple[dict[str, Any] | None, str | None]:
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

    return None, "PRODUCT_CONTEXT_REQUIRED"


def _build_enriched_product(product_seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product_seed)
    payload["id"] = payload.get("id") or payload.get("product_id")

    mapping = resolve_product_mapping(
        product=payload,
        product_name=payload.get("raw_product_title") or payload.get("product_display_name") or payload.get("product_short_name"),
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
    request: ProductDrivenAutoPlannerRequest,
    product: dict[str, Any],
) -> list[PromptAssetBinding]:
    normalized: list[PromptAssetBinding] = [
        PromptAssetBinding.model_validate(binding) for binding in request.asset_bindings
    ]

    has_product_binding = any(binding.asset_role == "PRODUCT" for binding in normalized)
    if not has_product_binding and _has_product_image(product):
        normalized.append(
            PromptAssetBinding(
                asset_role="PRODUCT",
                asset_source=_product_asset_source(product),
                asset_id=product.get("id") or product.get("product_id") or None,
                source_url=product.get("image_url") or product.get("local_image_path") or None,
            )
        )
    return normalized


def _build_product_context(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": product.get("id") or product.get("product_id"),
        "source": product.get("source"),
        "raw_product_title": product.get("raw_product_title"),
        "product_display_name": product.get("product_display_name"),
        "product_short_name": product.get("product_short_name"),
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "type": product.get("type"),
        "product_type": product.get("product_type"),
        "product_type_id": product.get("product_type_id"),
        "product_scale": product.get("product_scale"),
        "copywriting_angle": product.get("copywriting_angle"),
        "scene_context": product.get("scene_context"),
        "camera_style": product.get("camera_style"),
        "camera_behavior": product.get("camera_behavior"),
        "section_5_product_physics_prompt": product.get("section_5_product_physics_prompt"),
        "claim_risk_level": product.get("claim_risk_level"),
        "mapping_status": product.get("mapping_status"),
        "prompt_readiness_status": product.get("prompt_readiness_status"),
        "image_url": product.get("image_url"),
        "local_image_path": product.get("local_image_path"),
        "media_id": product.get("media_id"),
    }


def _build_inferred_context(
    request: ProductDrivenAutoPlannerRequest,
    product: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    explicit_character_data = bool(product.get("character_recommendations"))
    inferred = {
        "scene_context": request.requested_scene or product.get("scene_context"),
        "camera_style": product.get("camera_style"),
        "camera_behavior": product.get("camera_behavior"),
        "camera_shot": product.get("camera_shot"),
        "copywriting_angle": product.get("copywriting_angle"),
        "product_scale": product.get("product_scale"),
        "section_5_product_physics_prompt": product.get("section_5_product_physics_prompt"),
        "requested_character": request.requested_character,
        "requested_language": request.requested_language,
        "requested_platform": request.requested_platform,
        "requested_engine": request.requested_engine,
        "character_recommendations": product.get("character_recommendations") or [],
        "character_inference_status": "EXPLICIT_DATA" if explicit_character_data else "NOT_VERIFIED",
    }
    return inferred, explicit_character_data


def _build_provenance(product_seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": "ROUND_2_PRODUCT_DRIVEN_AUTO_PLANNER_ONLY",
        "product_lookup": "crud.get_product" if product_seed.get("id") or product_seed.get("product_id") else "inline_payload",
        "reused_services": [
            "agent.services.product_mapping.resolve_product_mapping",
            "agent.services.product_physics.resolve_product_physics",
            "agent.services.product_physics.evaluate_prompt_readiness",
            "agent.services.product_preflight.resolve_creative_profile",
            "agent.services.product_preflight.evaluate_mapping_status",
            "agent.services.product_preflight.build_product_preflight",
            "agent.services.offline_prompt_planner.create_offline_prompt_plan",
        ],
        "safe_read_only_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
    }


def _build_failure_response(
    request: ProductDrivenAutoPlannerRequest,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
    product_context: dict[str, Any] | None = None,
    inferred_context: dict[str, Any] | None = None,
    planner_request: dict[str, Any] | None = None,
    planner_output: dict[str, Any] | None = None,
    not_verified_fields: list[str] | None = None,
) -> ProductDrivenAutoPlannerResponse:
    return ProductDrivenAutoPlannerResponse(
        planning_status="FAIL",
        product_context=product_context or {},
        inferred_context=inferred_context or {},
        planner_request=planner_request,
        planner_output=planner_output,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        not_verified_fields=not_verified_fields or [],
    )


def _payload_backed_without_lookup(request: ProductDrivenAutoPlannerRequest) -> bool:
    return bool(request.product_payload) and not bool(request.product_id)


async def create_product_driven_auto_plan(
    request_input: dict[str, Any] | ProductDrivenAutoPlannerRequest,
) -> ProductDrivenAutoPlannerResponse:
    request, raw_request = _normalize_request(request_input)
    warnings: list[str] = []
    errors: list[str] = []
    not_verified_fields: list[str] = []

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_2")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_2")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_2")
    if _has_truthy_flag(raw_request, FORBIDDEN_DIMENSION_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED")
    if _has_truthy_flag(raw_request, FORBIDDEN_CLAIM_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED")
    if _has_truthy_flag(raw_request, FORBIDDEN_MEDIA_PROOF_KEYS):
        _unique_append(errors, "PRODUCT_MEDIA_UPLOAD_VERIFICATION_NOT_PROVEN")

    product_seed, lookup_error = await _resolve_product_seed(request)
    provenance = _build_provenance(product_seed or {})
    if lookup_error == "PRODUCT_NOT_FOUND":
        return _build_failure_response(request, ["PRODUCT_NOT_FOUND"], warnings, provenance)
    if lookup_error == "PRODUCT_CONTEXT_REQUIRED":
        return _build_failure_response(request, ["PRODUCT_CONTEXT_REQUIRED"], warnings, provenance)

    if request.destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_DESTINATION_MODE:{request.destination_mode}")
    if request.output_type not in ALLOWED_OUTPUT_TYPES:
        _unique_append(errors, f"UNKNOWN_OUTPUT_TYPE:{request.output_type}")
    if request.extension_strategy not in ALLOWED_EXTENSION_STRATEGIES:
        _unique_append(errors, f"UNKNOWN_EXTENSION_STRATEGY:{request.extension_strategy}")
    if request.target_duration_seconds not in ALLOWED_TARGET_DURATIONS:
        _unique_append(errors, f"INVALID_TARGET_DURATION_SECONDS:{request.target_duration_seconds}")

    enriched_product = _build_enriched_product(product_seed or {})
    product_context = _build_product_context(enriched_product)
    inferred_context, has_explicit_character_data = _build_inferred_context(request, enriched_product)

    _unique_append(warnings, "PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED")
    _unique_append(not_verified_fields, "product_dimensions")

    if not _has_product_image(enriched_product):
        _unique_append(warnings, "PRODUCT_IMAGE_MISSING")
        _unique_append(not_verified_fields, "product_image")

    _unique_append(warnings, "PRODUCT_UPLOAD_TO_FLOW_MEDIA_HANDOFF_NOT_IMPLEMENTED")
    _unique_append(not_verified_fields, "product_media_handoff")

    if not has_explicit_character_data:
        _unique_append(warnings, "AUTOMATIC_CHARACTER_INFERENCE_NOT_VERIFIED")
        _unique_append(not_verified_fields, "automatic_character_inference")

    _unique_append(warnings, "EXTERNAL_OPERATOR_PACK_REGISTRY_NOT_LOCAL_REPO_TRUTH")
    _unique_append(not_verified_fields, "external_operator_pack_registry")

    _unique_append(warnings, "CLAIM_BOUNDARY_NOT_HARD_ENFORCED_END_TO_END")
    _unique_append(not_verified_fields, "claim_boundary_enforcement")

    _unique_append(warnings, "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE")

    if request.destination_mode in {"INGREDIENTS", "IMAGE"}:
        _unique_append(warnings, "PRODUCT_SLOT_NOT_FIRST_CLASS_IN_CURRENT_UI_SERVICE")

    if errors:
        return _build_failure_response(
            request,
            errors,
            warnings,
            provenance,
            product_context=product_context,
            inferred_context=inferred_context,
            not_verified_fields=not_verified_fields,
        )

    planner_request_model = PromptPlanningRequest(
        source_route="PRODUCT_DRIVEN_AUTO",
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        product_id=enriched_product.get("id") or enriched_product.get("product_id"),
        asset_bindings=_normalize_asset_bindings(request, enriched_product),
        target_duration_seconds=request.target_duration_seconds,
        block_duration_seconds=8,
        extension_strategy=request.extension_strategy or "NONE",
    )
    planner_request_payload = planner_request_model.model_dump()
    planner_output = await create_offline_prompt_plan(planner_request_model)

    planner_warnings = list(planner_output.warnings)
    planner_errors = list(planner_output.errors)
    if _payload_backed_without_lookup(request):
        planner_errors = [
            error
            for error in planner_errors
            if error not in {"PRODUCT_ID_REQUIRED_FOR_PRODUCT_DRIVEN_AUTO", "PRODUCT_NOT_FOUND_FOR_PRODUCT_DRIVEN_AUTO"}
        ]

    for warning in planner_warnings:
        _unique_append(warnings, warning)
    for error in planner_errors:
        _unique_append(errors, error)

    planner_output_payload = planner_output.model_dump()
    planner_output_payload["warnings"] = planner_warnings
    planner_output_payload["errors"] = planner_errors
    planner_output_payload["planning_status"] = "FAIL" if planner_errors else "WARN" if planner_warnings else "PASS"

    planning_status = "FAIL" if errors else "WARN" if warnings or planner_output_payload["planning_status"] == "WARN" else "PASS"
    return ProductDrivenAutoPlannerResponse(
        planning_status=planning_status,
        product_context=product_context,
        inferred_context=inferred_context,
        planner_request=planner_request_payload,
        planner_output=planner_output_payload,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        not_verified_fields=not_verified_fields,
    )
