from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent.db import crud
from agent.models.prompt_planning import (
    PromptAssetBinding,
    PromptAssetRequirement,
    PromptPlanBlock,
    PromptPlanningRequest,
    PromptPlanningResult,
)


ALLOWED_SOURCE_ROUTES = {"PRODUCT_DRIVEN_AUTO", "REGISTRY_DRIVEN_MANUAL_ASSISTED"}
ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT", "PROMPT_BLOCK_PLAN"}
ALLOWED_ASSET_ROLES = {"SUBJECT_CHARACTER", "PRODUCT", "SCENE", "STYLE", "START_FRAME", "END_FRAME"}
ALLOWED_ASSET_SOURCES = {"FASTMOSS", "REGISTERED_PRODUCT", "GENERATED_ASSET", "UPLOADED_IMAGE", "REGISTRY"}
ALLOWED_EXTENSION_STRATEGIES = {"NONE", "EXTEND_CONTINUITY", "INSERT_JUMP_TO", "MIXED"}
ALLOWED_TARGET_DURATIONS = {8, 16, 24, 32}
DEFAULT_CONTINUATION_PREFIX = "From the last frame, the same character continues..."

FORBIDDEN_DOM_KEYS = {
    "execute_dom",
    "dom_execution",
    "flow_execution",
    "execute_flow",
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

MODE_REQUIREMENTS: dict[str, list[tuple[str, bool, str]]] = {
    "TEXT_TO_VIDEO": [
        ("PRODUCT", False, "Optional product reference for stronger product truth grounding."),
        ("SUBJECT_CHARACTER", False, "Optional character reference for stronger continuity grounding."),
    ],
    "FRAMES": [
        ("START_FRAME", True, "Frames mode requires a start frame reference."),
        ("END_FRAME", False, "End frame is optional for continuation planning."),
    ],
    "INGREDIENTS": [
        ("SUBJECT_CHARACTER", True, "Current repo-wired Ingredients lane requires a subject reference."),
        ("SCENE", False, "Scene reference is optional but recommended for consistency."),
        ("STYLE", False, "Style reference is optional but recommended for consistency."),
        ("PRODUCT", False, "Product slot is not first-class in the current Ingredients UI."),
    ],
    "IMAGE": [
        ("SUBJECT_CHARACTER", False, "Image planning can be subject-led or subject-creation oriented."),
        ("SCENE", False, "Scene reference is optional for image planning."),
        ("STYLE", False, "Style reference is optional for image planning."),
        ("PRODUCT", False, "Product slot is not first-class in the current Image UI."),
    ],
}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _normalize_request(request_input: dict[str, Any] | PromptPlanningRequest) -> tuple[PromptPlanningRequest | None, dict[str, Any], list[str]]:
    if isinstance(request_input, PromptPlanningRequest):
        return request_input, request_input.model_dump(), []

    raw_request = dict(request_input)
    try:
        parsed = PromptPlanningRequest.model_validate(raw_request)
        return parsed, raw_request, []
    except ValidationError as exc:
        return None, raw_request, [err["msg"] for err in exc.errors()]


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _asset_role_present(asset_bindings: list[PromptAssetBinding], role: str) -> bool:
    return any(binding.asset_role == role for binding in asset_bindings)


def _product_binding_present(asset_bindings: list[PromptAssetBinding]) -> bool:
    return _asset_role_present(asset_bindings, "PRODUCT")


def _product_binding_has_image(asset_bindings: list[PromptAssetBinding]) -> bool:
    for binding in asset_bindings:
        if binding.asset_role != "PRODUCT":
            continue
        if binding.asset_id or binding.source_url:
            return True
    return False


def _build_asset_requirements(destination_mode: str, asset_bindings: list[PromptAssetBinding]) -> list[PromptAssetRequirement]:
    requirements: list[PromptAssetRequirement] = []
    for asset_role, required, reason in MODE_REQUIREMENTS.get(destination_mode, []):
        requirements.append(
            PromptAssetRequirement(
                asset_role=asset_role,
                required=required,
                satisfied=_asset_role_present(asset_bindings, asset_role),
                reason=reason,
            )
        )
    return requirements


def _resolve_video_extension_strategy(extension_strategy: str, block_count: int, warnings: list[str], errors: list[str]) -> str:
    if block_count <= 1:
        return extension_strategy

    if extension_strategy == "NONE":
        _unique_append(warnings, "MULTI_BLOCK_PLAN_AUTO_NORMALIZED_TO_EXTEND_CONTINUITY")
        return "EXTEND_CONTINUITY"

    if extension_strategy not in ALLOWED_EXTENSION_STRATEGIES:
        _unique_append(errors, f"UNKNOWN_EXTENSION_STRATEGY:{extension_strategy}")
        return extension_strategy

    return extension_strategy


def _build_blocks(destination_mode: str, block_count: int, extension_strategy: str) -> list[PromptPlanBlock]:
    if block_count <= 0:
        return []

    if destination_mode == "IMAGE":
        return [
            PromptPlanBlock(
                block_index=1,
                flow_action="INITIAL_GENERATE",
                depends_on_block_index=None,
                prompt_role="IMAGE_GENERATION",
                transition_intent="START",
                continuation_prefix=None,
                execution_status="PLANNED",
            )
        ]

    blocks: list[PromptPlanBlock] = [
        PromptPlanBlock(
            block_index=1,
            flow_action="INITIAL_GENERATE",
            depends_on_block_index=None,
            prompt_role="OPENING",
            transition_intent="START",
            continuation_prefix=None,
            execution_status="PLANNED",
        )
    ]

    for block_index in range(2, block_count + 1):
        if extension_strategy == "INSERT_JUMP_TO":
            flow_action = "INSERT_JUMP_TO"
            prompt_role = "INSERTION"
            transition_intent = "JUMP_TO"
            continuation_prefix = None
        elif extension_strategy == "MIXED":
            if block_index % 2 == 0:
                flow_action = "EXTEND_CONTINUITY"
                prompt_role = "CONTINUATION"
                transition_intent = "FROM_LAST_FRAME"
                continuation_prefix = DEFAULT_CONTINUATION_PREFIX
            else:
                flow_action = "INSERT_JUMP_TO"
                prompt_role = "INSERTION"
                transition_intent = "JUMP_TO"
                continuation_prefix = None
        else:
            flow_action = "EXTEND_CONTINUITY"
            prompt_role = "CONTINUATION"
            transition_intent = "FROM_LAST_FRAME"
            continuation_prefix = DEFAULT_CONTINUATION_PREFIX

        blocks.append(
            PromptPlanBlock(
                block_index=block_index,
                flow_action=flow_action,
                depends_on_block_index=block_index - 1,
                prompt_role=prompt_role,
                transition_intent=transition_intent,
                continuation_prefix=continuation_prefix,
                execution_status="PLANNED",
            )
        )

    return blocks


def _finalize_status(warnings: list[str], errors: list[str]) -> str:
    if errors:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def _fail_result(raw_request: dict[str, Any], errors: list[str], warnings: list[str] | None = None) -> PromptPlanningResult:
    return PromptPlanningResult(
        planning_status="FAIL",
        source_route=raw_request.get("source_route"),
        destination_mode=raw_request.get("destination_mode"),
        output_type=raw_request.get("output_type"),
        target_duration_seconds=raw_request.get("target_duration_seconds"),
        block_duration_seconds=raw_request.get("block_duration_seconds"),
        block_count=0,
        extension_strategy=raw_request.get("extension_strategy"),
        asset_requirements=[],
        asset_bindings=[],
        warnings=warnings or [],
        errors=errors,
        blocks=[],
        metadata={"scope": "ROUND_1_OFFLINE_PLANNER_ONLY"},
    )


async def create_offline_prompt_plan(request_input: dict[str, Any] | PromptPlanningRequest) -> PromptPlanningResult:
    request, raw_request, parse_errors = _normalize_request(request_input)
    if request is None:
        return _fail_result(raw_request, [f"REQUEST_VALIDATION_ERROR:{msg}" for msg in parse_errors])

    warnings: list[str] = []
    errors: list[str] = []

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_1")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_1")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_1")

    if request.source_route not in ALLOWED_SOURCE_ROUTES:
        _unique_append(errors, f"UNKNOWN_SOURCE_ROUTE:{request.source_route}")
    if request.destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_DESTINATION_MODE:{request.destination_mode}")
    if request.output_type not in ALLOWED_OUTPUT_TYPES:
        _unique_append(errors, f"UNKNOWN_OUTPUT_TYPE:{request.output_type}")
    if request.extension_strategy not in ALLOWED_EXTENSION_STRATEGIES:
        _unique_append(errors, f"UNKNOWN_EXTENSION_STRATEGY:{request.extension_strategy}")

    for binding in request.asset_bindings:
        if binding.asset_role not in ALLOWED_ASSET_ROLES:
            _unique_append(errors, f"UNKNOWN_ASSET_ROLE:{binding.asset_role}")
        if binding.asset_source not in ALLOWED_ASSET_SOURCES:
            _unique_append(warnings, f"UNKNOWN_ASSET_SOURCE:{binding.asset_source}")

    if request.target_duration_seconds not in ALLOWED_TARGET_DURATIONS:
        _unique_append(errors, f"INVALID_TARGET_DURATION_SECONDS:{request.target_duration_seconds}")
    if request.block_duration_seconds != 8:
        _unique_append(errors, f"INVALID_BLOCK_DURATION_SECONDS:{request.block_duration_seconds}")

    if request.destination_mode == "IMAGE":
        block_count = 1
    else:
        if request.block_duration_seconds <= 0 or request.target_duration_seconds % request.block_duration_seconds != 0:
            _unique_append(errors, "IMPOSSIBLE_DURATION_BLOCK_CONFIGURATION")
            block_count = 0
        else:
            block_count = request.target_duration_seconds // request.block_duration_seconds

    asset_requirements = _build_asset_requirements(request.destination_mode or "", request.asset_bindings)
    for requirement in asset_requirements:
        if requirement.required and not requirement.satisfied:
            _unique_append(errors, f"MISSING_REQUIRED_ASSET_ROLE:{requirement.asset_role}")

    product = None
    if request.product_id:
        product = await crud.get_product(request.product_id)

    if request.source_route == "PRODUCT_DRIVEN_AUTO":
        if not request.product_id:
            _unique_append(errors, "PRODUCT_ID_REQUIRED_FOR_PRODUCT_DRIVEN_AUTO")
        elif not product:
            _unique_append(errors, "PRODUCT_NOT_FOUND_FOR_PRODUCT_DRIVEN_AUTO")

    if request.source_route == "REGISTRY_DRIVEN_MANUAL_ASSISTED" or any(
        binding.asset_source == "REGISTRY" for binding in request.asset_bindings
    ):
        _unique_append(warnings, "EXTERNAL_REGISTRY_DATASETS_NOT_SOURCE_CONTROLLED")

    if request.destination_mode != "IMAGE":
        _unique_append(warnings, "BLOCK_LOGIC_IS_PROPOSED_ONLY_AND_MAY_CONFLICT_WITH_OPERATOR_SCENE_BLUEPRINT")

    if request.destination_mode in {"INGREDIENTS", "IMAGE"}:
        _unique_append(warnings, "PRODUCT_SLOT_IS_NOT_FIRST_CLASS_IN_CURRENT_UI")

    product_context_present = bool(request.product_id or _product_binding_present(request.asset_bindings))
    if product_context_present or request.source_route == "PRODUCT_DRIVEN_AUTO":
        _unique_append(warnings, "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED")
        _unique_append(warnings, "PRODUCT_UPLOAD_TO_FLOW_NOT_IMPLEMENTED")

    product_has_image = _product_binding_has_image(request.asset_bindings)
    if product and any(product.get(field) for field in ("image_url", "local_image_path", "media_id")):
        product_has_image = True

    if request.destination_mode == "TEXT_TO_VIDEO" and not product_has_image:
        _unique_append(warnings, "TEXT_TO_VIDEO_WITHOUT_PRODUCT_IMAGE")

    normalized_extension_strategy = request.extension_strategy or "NONE"
    if request.destination_mode == "IMAGE":
        if normalized_extension_strategy != "NONE":
            _unique_append(warnings, "IMAGE_MODE_DOES_NOT_USE_VIDEO_CONTINUATION_BLOCKS")
        normalized_extension_strategy = "NONE"
    else:
        normalized_extension_strategy = _resolve_video_extension_strategy(
            normalized_extension_strategy,
            block_count,
            warnings,
            errors,
        )

    blocks = _build_blocks(request.destination_mode or "", block_count, normalized_extension_strategy)
    if any(block.execution_status != "PLANNED" for block in blocks):
        _unique_append(errors, "NON_PLANNED_EXECUTION_STATUS_NOT_ALLOWED")
    for block in blocks:
        if block.block_index > 1 and block.depends_on_block_index != block.block_index - 1:
            _unique_append(errors, f"INVALID_BLOCK_DEPENDENCY:{block.block_index}")

    planning_status = _finalize_status(warnings, errors)
    return PromptPlanningResult(
        planning_status=planning_status,
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        target_duration_seconds=request.target_duration_seconds,
        block_duration_seconds=request.block_duration_seconds,
        block_count=block_count,
        extension_strategy=normalized_extension_strategy,
        asset_requirements=asset_requirements,
        asset_bindings=request.asset_bindings,
        warnings=warnings,
        errors=errors,
        blocks=blocks,
        metadata={
            "scope": "ROUND_1_OFFLINE_PLANNER_ONLY",
            "uses_flow_execution": False,
            "uses_batch_execution": False,
            "uses_extension_runtime": False,
        },
    )
