from __future__ import annotations

from typing import Any

from agent.models.destination_adapters import (
    DestinationAdapterRequest,
    DestinationAdapterResponse,
)
from agent.models.prompt_planning import PromptAssetBinding, PromptAssetRequirement, PromptPlanningResult


ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT", "PROMPT_BLOCK_PLAN"}
ALLOWED_SOURCE_ROUTES = {"PRODUCT_DRIVEN_AUTO", "REGISTRY_DRIVEN_MANUAL_ASSISTED"}

FORBIDDEN_DOM_KEYS = {
    "execute_dom",
    "dom_execution",
    "extend_button_click",
    "insert_button_click",
    "render_complete_detection",
}
FORBIDDEN_FLOW_KEYS = {
    "execute_flow",
    "flow_execution",
    "execute_flow_job",
    "smoke_execute_flow_job",
    "upload_to_flow",
    "trigger_generation",
}
FORBIDDEN_BATCH_KEYS = {"batch_execution", "execute_batch", "queue_batch", "run_batch"}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "write_canonical_registry",
    "auto_write_registry",
}
FORBIDDEN_FINAL_PROSE_KEYS = {
    "generate_final_prompt_prose",
    "final_prompt_prose",
    "compose_final_prompt",
    "write_final_prompt",
}
FORBIDDEN_UPLOAD_EXECUTION_KEYS = {
    "execute_upload",
    "execute_generation",
    "run_generation",
    "run_upload",
}
FORBIDDEN_UNVERIFIED_PROOF_KEYS = {
    "mark_unverified_truth_as_verified",
    "verify_external_truth",
    "verify_unverified_assets",
}

TEXT_TO_VIDEO_REQUIRED_FIELDS = [
    "character_description",
    "product_description",
    "scene_description",
    "action_description",
    "camera_description",
    "dialogue_or_narration",
]
IMAGE_SUPPORTED_INTENTS = [
    "create_character_asset",
    "create_character_holding_product",
    "create_product_lifestyle_image",
    "combine_character_and_product",
    "create_scene_reference",
]


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | DestinationAdapterRequest,
) -> tuple[DestinationAdapterRequest, dict[str, Any]]:
    if isinstance(request_input, DestinationAdapterRequest):
        return request_input, request_input.model_dump()
    parsed = DestinationAdapterRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _fail_response(
    request: DestinationAdapterRequest,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
) -> DestinationAdapterResponse:
    return DestinationAdapterResponse(
        adapter_status="FAIL",
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        mode_payload={},
        asset_requirements=[],
        missing_assets=[],
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        planner_block_summary={},
        execution_allowed=False,
    )


def _build_provenance(request: DestinationAdapterRequest) -> dict[str, Any]:
    return {
        "scope": "ROUND_4_DESTINATION_MODE_ADAPTERS_ONLY",
        "adapter_service": "agent.services.destination_mode_adapters.adapt_destination_mode_payload",
        "safe_offline_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_product_driven_auto_service": False,
        "uses_registry_driven_manual_service": False,
        "upstream_scope": request.provenance.get("scope"),
    }


def _to_binding_objects(bindings: list[dict[str, Any]]) -> list[PromptAssetBinding]:
    return [PromptAssetBinding.model_validate(binding) for binding in bindings]


def _to_requirement_objects(requirements: list[dict[str, Any]]) -> list[PromptAssetRequirement]:
    return [PromptAssetRequirement.model_validate(requirement) for requirement in requirements]


def _planner_summary(planner_output: PromptPlanningResult) -> dict[str, Any]:
    return {
        "planning_status": planner_output.planning_status,
        "block_count": planner_output.block_count,
        "block_duration_seconds": planner_output.block_duration_seconds,
        "extension_strategy": planner_output.extension_strategy,
        "block_flow_actions": [block.flow_action for block in planner_output.blocks],
        "upstream_warning_count": len(planner_output.warnings),
        "upstream_error_count": len(planner_output.errors),
    }


def _missing_asset_roles(requirements: list[PromptAssetRequirement]) -> list[str]:
    return [requirement.asset_role for requirement in requirements if requirement.required and not requirement.satisfied]


def _binding_present(bindings: list[PromptAssetBinding], role: str) -> bool:
    return any(binding.asset_role == role for binding in bindings)


def _binding_with_content(bindings: list[PromptAssetBinding], role: str) -> bool:
    for binding in bindings:
        if binding.asset_role != role:
            continue
        if binding.asset_id or binding.source_url:
            return True
    return False


def _product_has_image(request: DestinationAdapterRequest, bindings: list[PromptAssetBinding]) -> bool:
    if _binding_with_content(bindings, "PRODUCT"):
        return True
    product = request.product_context or request.manual_context.get("product_context") or {}
    return any(product.get(field) for field in ("image_url", "local_image_path", "media_id"))


def _text_to_video_payload(
    request: DestinationAdapterRequest,
    planner_output: PromptPlanningResult,
    bindings: list[PromptAssetBinding],
    warnings: list[str],
) -> dict[str, Any]:
    product = request.product_context or request.manual_context.get("product_context") or {}
    inferred = request.inferred_context or {}

    _unique_append(warnings, "TEXT_TO_VIDEO_PRODUCT_HALLUCINATION_RISK")
    if not _product_has_image(request, bindings):
        _unique_append(warnings, "TEXT_TO_VIDEO_WITHOUT_PRODUCT_IMAGE")
    _unique_append(warnings, "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED")
    _unique_append(warnings, "PRODUCT_CLAIMS_NOT_HARD_ENFORCED")

    return {
        "mode": "TEXT_TO_VIDEO",
        "requires_images": False,
        "text_only_generation": True,
        "required_prompt_fields": TEXT_TO_VIDEO_REQUIRED_FIELDS,
        "character_description": inferred.get("requested_character")
        or request.manual_context.get("avatar_id")
        or "Character details must be supplied at final composition time.",
        "product_description": product.get("product_short_name")
        or product.get("product_display_name")
        or "Product details must be described textually from verified truth only.",
        "scene_description": request.manual_context.get("scene_context")
        or inferred.get("scene_context")
        or "Scene description required from planner context.",
        "action_description": "Action should follow planner block intent without inventing unsupported product behavior.",
        "camera_description": request.manual_context.get("camera_style")
        or inferred.get("camera_style")
        or "Camera route must be supplied at final composition time.",
        "dialogue_or_narration": request.manual_context.get("language")
        or inferred.get("requested_language")
        or "Dialogue language must be selected before final composition.",
        "flow_execution_instruction": None,
    }


def _frames_payload(
    planner_output: PromptPlanningResult,
    bindings: list[PromptAssetBinding],
    warnings: list[str],
    missing_assets: list[str],
) -> dict[str, Any]:
    if "START_FRAME" in missing_assets:
        _unique_append(warnings, "FRAMES_START_FRAME_MISSING")
    if not _binding_present(bindings, "SUBJECT_CHARACTER") and _binding_present(bindings, "PRODUCT"):
        _unique_append(warnings, "FRAMES_PRODUCT_ONLY_REFERENCE_REQUIRES_IMAGINED_CHARACTER")
    _unique_append(warnings, "FRAMES_VISUAL_CONTRADICTION_RISK")

    return {
        "mode": "FRAMES",
        "requires_start_frame": True,
        "supports_end_frame": True,
        "required_asset_roles": ["START_FRAME"],
        "optional_asset_roles": ["END_FRAME"],
        "prompt_intent": [
            "elaborate uploaded frame",
            "preserve visual source",
            "do not contradict uploaded product or character features",
        ],
        "preserve_visual_source": True,
        "planner_blocks": planner_output.block_count,
        "flow_execution_instruction": None,
    }


def _ingredients_payload(
    planner_output: PromptPlanningResult,
    bindings: list[PromptAssetBinding],
    warnings: list[str],
    missing_assets: list[str],
) -> dict[str, Any]:
    for role, warning_code in [
        ("SUBJECT_CHARACTER", "INGREDIENTS_SUBJECT_MISSING"),
        ("SCENE", "INGREDIENTS_SCENE_MISSING"),
        ("STYLE", "INGREDIENTS_STYLE_MISSING"),
    ]:
        if role in missing_assets:
            _unique_append(warnings, warning_code)

    if _binding_present(bindings, "PRODUCT"):
        _unique_append(warnings, "INGREDIENTS_PRODUCT_SLOT_NOT_FIRST_CLASS")

    return {
        "mode": "INGREDIENTS",
        "required_asset_roles": ["SUBJECT_CHARACTER", "SCENE", "STYLE"],
        "optional_asset_roles": ["PRODUCT"],
        "combine_subject_scene_style_product": True,
        "preserve_subject_identity": True,
        "preserve_product_appearance_where_available": True,
        "prompt_intent": [
            "combine subject, scene, style, and product references if supplied",
            "preserve subject identity",
            "preserve product appearance where available",
        ],
        "planner_blocks": planner_output.block_count,
        "flow_execution_instruction": None,
    }


def _image_payload(
    request: DestinationAdapterRequest,
    warnings: list[str],
) -> dict[str, Any]:
    product = request.product_context or request.manual_context.get("product_context") or {}
    asset_ids = {binding.get("asset_role"): binding.get("asset_id") for binding in request.asset_bindings}

    image_intent = str(request.manual_context.get("image_intent") or request.inferred_context.get("image_intent") or "").strip()
    if image_intent not in IMAGE_SUPPORTED_INTENTS:
        image_intent = "create_character_holding_product" if product else "create_character_asset"

    _unique_append(warnings, "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED")
    if not any(product.get(field) for field in ("image_url", "local_image_path", "media_id")):
        _unique_append(warnings, "PRODUCT_IMAGE_MISSING")
    _unique_append(warnings, "IMAGE_PRODUCT_HANDLING_INFERRED")
    _unique_append(warnings, "IMAGE_CHARACTER_ASSET_NOT_VERIFIED")

    return {
        "mode": "IMAGE",
        "image_generation": True,
        "video_continuation": False,
        "supported_intents": IMAGE_SUPPORTED_INTENTS,
        "image_intent": image_intent,
        "composition": "Planning-only composition scaffold derived from available assets.",
        "lighting": "Planning-only lighting scaffold; final prose generation is out of scope.",
        "product_handling": product.get("section_5_product_physics_prompt")
        or "Product handling remains inferred from available truth and must be finalized later.",
        "negative_prompt_notes": [
            "Do not invent unsupported product claims.",
            "Do not contradict verified product appearance.",
            "Do not treat unverified character identity as canonical.",
        ],
        "aspect_ratio_or_platform": request.manual_context.get("platform") or "platform_not_selected",
        "asset_reference_summary": asset_ids,
        "flow_execution_instruction": None,
    }


async def adapt_destination_mode_payload(
    request_input: dict[str, Any] | DestinationAdapterRequest,
) -> DestinationAdapterResponse:
    request, raw_request = _normalize_request(request_input)
    warnings = list(request.warnings)
    errors = list(request.errors)
    provenance = _build_provenance(request)

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_FLOW_KEYS):
        _unique_append(errors, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_FINAL_PROSE_KEYS):
        _unique_append(errors, "FINAL_PROMPT_PROSE_GENERATION_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_UPLOAD_EXECUTION_KEYS):
        _unique_append(errors, "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_4")
    if _has_truthy_flag(raw_request, FORBIDDEN_UNVERIFIED_PROOF_KEYS):
        _unique_append(errors, "UNVERIFIED_TRUTH_CANNOT_BE_MARKED_VERIFIED")

    if request.source_route not in ALLOWED_SOURCE_ROUTES:
        _unique_append(errors, f"UNKNOWN_SOURCE_ROUTE:{request.source_route}")
    if request.destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_DESTINATION_MODE:{request.destination_mode}")
    if request.output_type not in ALLOWED_OUTPUT_TYPES:
        _unique_append(errors, f"UNKNOWN_OUTPUT_TYPE:{request.output_type}")
    if not request.planner_output:
        _unique_append(errors, "MISSING_PLANNER_OUTPUT")

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    planner_output = PromptPlanningResult.model_validate(request.planner_output)
    bindings = _to_binding_objects(request.asset_bindings or planner_output.asset_bindings)
    requirements = _to_requirement_objects([req.model_dump() if hasattr(req, "model_dump") else req for req in planner_output.asset_requirements])
    missing_assets = _missing_asset_roles(requirements)
    summary = _planner_summary(planner_output)

    if planner_output.planning_status == "WARN":
        _unique_append(warnings, "UPSTREAM_PLANNER_WARN")
    if planner_output.planning_status == "FAIL":
        _unique_append(errors, "UPSTREAM_PLANNER_FAIL")

    if "BLOCK_LOGIC_IS_PROPOSED_ONLY_AND_MAY_CONFLICT_WITH_OPERATOR_SCENE_BLUEPRINT" in planner_output.warnings:
        _unique_append(warnings, "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE")

    mode_payload: dict[str, Any]
    if request.destination_mode == "TEXT_TO_VIDEO":
        mode_payload = _text_to_video_payload(request, planner_output, bindings, warnings)
    elif request.destination_mode == "FRAMES":
        if "START_FRAME" in missing_assets:
            _unique_append(errors, "FRAMES_START_FRAME_REQUIRED")
        mode_payload = _frames_payload(planner_output, bindings, warnings, missing_assets)
    elif request.destination_mode == "INGREDIENTS":
        if any(role in missing_assets for role in ["SUBJECT_CHARACTER", "SCENE", "STYLE"]):
            _unique_append(errors, "INGREDIENTS_REQUIRED_ASSETS_MISSING")
        mode_payload = _ingredients_payload(planner_output, bindings, warnings, missing_assets)
    else:
        mode_payload = _image_payload(request, warnings)

    adapter_status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return DestinationAdapterResponse(
        adapter_status=adapter_status,
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        mode_payload=mode_payload,
        asset_requirements=[requirement.model_dump() for requirement in requirements],
        missing_assets=missing_assets,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        planner_block_summary=summary,
        execution_allowed=False,
    )
