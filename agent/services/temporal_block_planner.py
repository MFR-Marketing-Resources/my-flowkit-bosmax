from __future__ import annotations

from typing import Any

from agent.models.temporal_block_planner import (
    TemporalBlockPlannerRequest,
    TemporalBlockPlannerResponse,
    TemporalPlanBlock,
)


ALLOWED_SOURCE_ROUTES = {"PRODUCT_DRIVEN_AUTO", "REGISTRY_DRIVEN_MANUAL_ASSISTED"}
ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT"}
ALLOWED_TARGET_DURATIONS = {8, 16, 24, 32}
ALLOWED_EXTENSION_STRATEGIES = {"NONE", "EXTEND_CONTINUITY", "INSERT_JUMP_TO", "MIXED"}
DEFAULT_CONTINUATION_PREFIX = "From the last frame, the same character continues..."
ALLOWED_PLANNED_ACTIONS = {"INITIAL_GENERATE", "EXTEND_CONTINUITY", "INSERT_JUMP_TO"}
ALLOWED_PROMPT_ROLES = {"OPENING", "CONTINUATION", "INSERTION"}
ALLOWED_TRANSITION_INTENTS = {"START", "FROM_LAST_FRAME", "JUMP_TO"}
FORBIDDEN_INTERNAL_MARKERS = [
    "CTX_",
    "SHOT_",
    "CAM_",
    "CLASS_",
    "PROP_",
    "SCRIPT_",
    "DNA_",
    "ANCHOR_",
    "BLOCK_",
    "INTERVAL_",
    "{{",
    "}}",
    "[START_TIME",
    "[END_TIME",
]

FORBIDDEN_DOM_KEYS = {
    "execute_dom",
    "dom_execution",
}
FORBIDDEN_FLOW_KEYS = {
    "execute_flow",
    "flow_execution",
    "execute_flow_job",
    "smoke_execute_flow_job",
    "upload_to_flow",
    "trigger_generation",
}
FORBIDDEN_EXTEND_INSERT_EXECUTION_KEYS = {
    "execute_extend",
    "execute_insert",
    "extend_button_click",
    "insert_button_click",
}
FORBIDDEN_RENDER_DETECTION_KEYS = {
    "render_complete_detection",
    "wait_render_complete",
    "detect_render_complete",
}
FORBIDDEN_BATCH_KEYS = {"batch_execution", "execute_batch", "queue_batch", "run_batch"}
FORBIDDEN_UPLOAD_EXECUTION_KEYS = {
    "execute_upload",
    "execute_generation",
    "run_generation",
    "run_upload",
}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "write_canonical_registry",
    "auto_write_registry",
}
FORBIDDEN_UNVERIFIED_PROOF_KEYS = {
    "mark_unverified_truth_as_verified",
    "verify_external_truth",
    "verify_unverified_assets",
}
FORBIDDEN_DIMENSION_INVENTION_KEYS = {
    "invent_product_dimensions",
    "infer_unverified_dimensions",
    "force_product_dimensions",
}
FORBIDDEN_CLAIM_INVENTION_KEYS = {
    "invent_product_claims",
    "infer_unverified_claims",
    "force_product_claims",
}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | TemporalBlockPlannerRequest,
) -> tuple[TemporalBlockPlannerRequest, dict[str, Any]]:
    if isinstance(request_input, TemporalBlockPlannerRequest):
        return request_input, request_input.model_dump()
    parsed = TemporalBlockPlannerRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _build_provenance(request: TemporalBlockPlannerRequest) -> dict[str, Any]:
    return {
        "scope": "ROUND_6_TEMPORAL_BLOCK_PLANNER_ONLY",
        "temporal_planner_service": "agent.services.temporal_block_planner.create_temporal_block_plan",
        "safe_offline_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_ui_api_modules": False,
        "uses_runtime_orchestration": False,
        "upstream_scope": request.provenance.get("scope"),
    }


def _fail_response(
    request: TemporalBlockPlannerRequest,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
) -> TemporalBlockPlannerResponse:
    return TemporalBlockPlannerResponse(
        temporal_status="FAIL",
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        target_duration_seconds=request.target_duration_seconds,
        block_duration_seconds=request.block_duration_seconds,
        block_count=0,
        extension_strategy=request.extension_strategy,
        temporal_blocks=[],
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        execution_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
    )


def _collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_collect_strings(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_collect_strings(item))
        return result
    return []


def _best_effort_scrub(text: str) -> str:
    scrubbed = text.replace("{{", "").replace("}}", "")
    scrubbed = scrubbed.replace("[START_TIME", "START_TIME").replace("[END_TIME", "END_TIME")
    return scrubbed.strip()


def _contains_forbidden_marker(values: list[str]) -> bool:
    for value in values:
        for marker in FORBIDDEN_INTERNAL_MARKERS:
            if marker in value:
                return True
    return False


def _validate_common_request(request: TemporalBlockPlannerRequest, raw_request: dict[str, Any]) -> tuple[list[str], list[str]]:
    warnings = list(request.warnings)
    errors = list(request.errors)

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_FLOW_KEYS):
        _unique_append(errors, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_EXTEND_INSERT_EXECUTION_KEYS):
        _unique_append(errors, "EXTEND_INSERT_EXECUTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_RENDER_DETECTION_KEYS):
        _unique_append(errors, "RENDER_COMPLETE_DETECTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_UPLOAD_EXECUTION_KEYS):
        _unique_append(errors, "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_6")
    if _has_truthy_flag(raw_request, FORBIDDEN_UNVERIFIED_PROOF_KEYS):
        _unique_append(errors, "UNVERIFIED_TRUTH_CANNOT_BE_MARKED_VERIFIED")
    if _has_truthy_flag(raw_request, FORBIDDEN_DIMENSION_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED")
    if _has_truthy_flag(raw_request, FORBIDDEN_CLAIM_INVENTION_KEYS):
        _unique_append(errors, "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED")

    if request.source_route not in ALLOWED_SOURCE_ROUTES:
        _unique_append(errors, f"UNKNOWN_SOURCE_ROUTE:{request.source_route}")
    if request.destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_DESTINATION_MODE:{request.destination_mode}")
    if request.output_type not in ALLOWED_OUTPUT_TYPES:
        _unique_append(errors, f"UNKNOWN_OUTPUT_TYPE:{request.output_type}")
    if request.composer_status == "FAIL":
        _unique_append(errors, "UPSTREAM_COMPOSER_FAIL")
    if request.composer_status == "WARN":
        _unique_append(warnings, "UPSTREAM_COMPOSER_WARN")
    if not _normalize_text(request.prompt_text):
        _unique_append(errors, "MISSING_COMPOSER_OUTPUT")

    if request.target_duration_seconds not in ALLOWED_TARGET_DURATIONS:
        _unique_append(errors, f"INVALID_TARGET_DURATION_SECONDS:{request.target_duration_seconds}")
    if request.block_duration_seconds != 8:
        _unique_append(errors, f"INVALID_BLOCK_DURATION_SECONDS:{request.block_duration_seconds}")
    if request.extension_strategy not in ALLOWED_EXTENSION_STRATEGIES:
        _unique_append(errors, f"UNKNOWN_EXTENSION_STRATEGY:{request.extension_strategy}")

    strings_to_check = [request.prompt_text, *request.sections]
    if _contains_forbidden_marker(strings_to_check):
        _unique_append(errors, "FORBIDDEN_INTERNAL_MARKER_LEAKAGE")

    return warnings, errors


def _resolve_block_count(request: TemporalBlockPlannerRequest, errors: list[str]) -> int:
    if request.block_duration_seconds <= 0:
        _unique_append(errors, f"INVALID_BLOCK_DURATION_SECONDS:{request.block_duration_seconds}")
        return 0
    if request.target_duration_seconds % request.block_duration_seconds != 0:
        _unique_append(errors, "TARGET_DURATION_NOT_DIVISIBLE_BY_BLOCK_DURATION")
        return 0

    computed = request.target_duration_seconds // request.block_duration_seconds
    if request.requested_block_count is not None and request.requested_block_count != computed:
        _unique_append(errors, "REQUESTED_BLOCK_COUNT_MISMATCH")
    return computed


def _build_insert_prompt(base_prompt: str, note: str | None = None) -> str:
    prefix = "Jump to a deliberate insertion beat while preserving verified character and product truth."
    if note:
        return f"{prefix} {note} {base_prompt}".strip()
    return f"{prefix} {base_prompt}".strip()


def _build_extend_prompt(base_prompt: str, note: str | None = None) -> str:
    if note:
        return f"{DEFAULT_CONTINUATION_PREFIX} {note} {base_prompt}".strip()
    return f"{DEFAULT_CONTINUATION_PREFIX} {base_prompt}".strip()


def _metadata_for_block(per_block_intent_notes: list[dict[str, Any]], block_index: int) -> dict[str, Any] | None:
    for item in per_block_intent_notes:
        if item.get("block_index") == block_index:
            return item
    return None


def _build_temporal_blocks(
    request: TemporalBlockPlannerRequest,
    block_count: int,
    warnings: list[str],
    errors: list[str],
) -> list[TemporalPlanBlock]:
    base_prompt = _best_effort_scrub(request.prompt_text)
    blocks: list[TemporalPlanBlock] = [
        TemporalPlanBlock(
            block_index=1,
            duration_seconds=request.block_duration_seconds,
            flow_action_planned="INITIAL_GENERATE",
            prompt_role="OPENING",
            depends_on_block_index=None,
            transition_intent="START",
            continuation_prefix=None,
            prompt_text=base_prompt,
            warnings=[],
            execution_status="PLANNED",
        )
    ]

    for block_index in range(2, block_count + 1):
        block_warnings: list[str] = []
        metadata = _metadata_for_block(request.per_block_intent_notes, block_index)
        if request.extension_strategy == "EXTEND_CONTINUITY":
            planned_action = "EXTEND_CONTINUITY"
            prompt_role = "CONTINUATION"
            transition_intent = "FROM_LAST_FRAME"
            continuation_prefix = DEFAULT_CONTINUATION_PREFIX
            prompt_text = _build_extend_prompt(base_prompt, _normalize_text((metadata or {}).get("note")))
        elif request.extension_strategy == "INSERT_JUMP_TO":
            planned_action = "INSERT_JUMP_TO"
            prompt_role = "INSERTION"
            transition_intent = "JUMP_TO"
            continuation_prefix = None
            prompt_text = _build_insert_prompt(base_prompt, _normalize_text((metadata or {}).get("note")))
        else:
            if metadata is None:
                _unique_append(errors, "MIXED_STRATEGY_REQUIRES_PER_BLOCK_METADATA")
                return []
            strategy = _normalize_text(metadata.get("strategy"))
            note = _normalize_text(metadata.get("note"))
            if strategy == "EXTEND_CONTINUITY":
                planned_action = "EXTEND_CONTINUITY"
                prompt_role = "CONTINUATION"
                transition_intent = "FROM_LAST_FRAME"
                continuation_prefix = DEFAULT_CONTINUATION_PREFIX
                prompt_text = _build_extend_prompt(base_prompt, note)
            elif strategy == "INSERT_JUMP_TO":
                planned_action = "INSERT_JUMP_TO"
                prompt_role = "INSERTION"
                transition_intent = "JUMP_TO"
                continuation_prefix = None
                prompt_text = _build_insert_prompt(base_prompt, note)
            else:
                _unique_append(errors, f"UNKNOWN_MIXED_BLOCK_STRATEGY:{strategy}")
                return []

        prompt_text = _best_effort_scrub(prompt_text)
        if _contains_forbidden_marker([prompt_text]):
            _unique_append(errors, "FORBIDDEN_INTERNAL_MARKER_LEAKAGE")
            return []
        blocks.append(
            TemporalPlanBlock(
                block_index=block_index,
                duration_seconds=request.block_duration_seconds,
                flow_action_planned=planned_action,
                prompt_role=prompt_role,
                depends_on_block_index=block_index - 1,
                transition_intent=transition_intent,
                continuation_prefix=continuation_prefix,
                prompt_text=prompt_text,
                warnings=block_warnings,
                execution_status="PLANNED",
            )
        )

    return blocks


async def create_temporal_block_plan(
    request_input: dict[str, Any] | TemporalBlockPlannerRequest,
) -> TemporalBlockPlannerResponse:
    request, raw_request = _normalize_request(request_input)
    warnings, errors = _validate_common_request(request, raw_request)
    provenance = _build_provenance(request)

    if request.output_type == "IMAGE_PROMPT":
        if not request.allow_image_prompt_temporal_metadata_only:
            _unique_append(errors, "IMAGE_PROMPT_TEMPORAL_PLANNING_NOT_ALLOWED_BY_DEFAULT")
        else:
            _unique_append(warnings, "IMAGE_PROMPT_TEMPORAL_PLANNING_IS_METADATA_ONLY")
            if request.target_duration_seconds != 8:
                _unique_append(errors, "IMAGE_PROMPT_TEMPORAL_METADATA_ONLY_SUPPORTS_SINGLE_BLOCK")
            if request.extension_strategy != "NONE":
                _unique_append(errors, "IMAGE_PROMPT_TEMPORAL_METADATA_ONLY_REQUIRES_NONE_STRATEGY")

    block_count = _resolve_block_count(request, errors)
    if request.extension_strategy == "NONE" and block_count > 1:
        _unique_append(errors, "NONE_STRATEGY_NOT_ALLOWED_FOR_MULTI_BLOCK_OUTPUT")
    if request.extension_strategy == "INSERT_JUMP_TO" and not request.allow_insert_jump_to:
        _unique_append(errors, "INSERT_JUMP_TO_NOT_ENABLED_FOR_REQUEST")
    if request.extension_strategy == "MIXED":
        if not request.allow_mixed_strategy:
            _unique_append(errors, "MIXED_STRATEGY_NOT_ENABLED_FOR_REQUEST")
        if not request.per_block_intent_notes:
            _unique_append(errors, "MIXED_STRATEGY_REQUIRES_PER_BLOCK_METADATA")

    if request.output_type == "VIDEO_9_SECTION_PROMPT" and request.section_count != 9:
        _unique_append(errors, "VIDEO_9_SECTION_PROMPT_MUST_CONTAIN_EXACTLY_NINE_SECTIONS")

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    _unique_append(warnings, "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE")
    _unique_append(warnings, "CURRENT_OPERATOR_BLUEPRINT_4_SCENE_8_SCENE_LOGIC_MAY_CONFLICT_WITH_DURATION_DIVIDED_BY_8_BLOCK_PLANNING")
    _unique_append(warnings, "TEMPORAL_OUTPUT_IS_OFFLINE_ONLY_NOT_FLOW_EXECUTION_READY")
    _unique_append(warnings, "EXTEND_INSERT_ARE_PLANNING_METADATA_ONLY")

    blocks = _build_temporal_blocks(request, block_count, warnings, errors)
    if errors:
        return _fail_response(request, errors, warnings, provenance)

    for block in blocks:
        if block.execution_status != "PLANNED":
            _unique_append(errors, "NON_PLANNED_EXECUTION_STATUS_NOT_ALLOWED")
        if block.flow_action_planned not in ALLOWED_PLANNED_ACTIONS:
            _unique_append(errors, f"INVALID_FLOW_ACTION_PLANNED:{block.flow_action_planned}")
        if block.prompt_role not in ALLOWED_PROMPT_ROLES:
            _unique_append(errors, f"INVALID_PROMPT_ROLE:{block.prompt_role}")
        if block.transition_intent not in ALLOWED_TRANSITION_INTENTS:
            _unique_append(errors, f"INVALID_TRANSITION_INTENT:{block.transition_intent}")
        if block.block_index > 1 and block.depends_on_block_index != block.block_index - 1:
            _unique_append(errors, f"INVALID_BLOCK_DEPENDENCY:{block.block_index}")
        if block.flow_action_planned == "INSERT_JUMP_TO" and block.continuation_prefix:
            _unique_append(errors, f"INSERT_BLOCK_MUST_NOT_USE_CONTINUATION_PREFIX:{block.block_index}")
        if block.flow_action_planned == "EXTEND_CONTINUITY" and block.continuation_prefix != DEFAULT_CONTINUATION_PREFIX:
            _unique_append(errors, f"EXTEND_BLOCK_REQUIRES_CONTINUATION_PREFIX:{block.block_index}")

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    temporal_status = "WARN" if warnings else "PASS"
    return TemporalBlockPlannerResponse(
        temporal_status=temporal_status,
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        target_duration_seconds=request.target_duration_seconds,
        block_duration_seconds=request.block_duration_seconds,
        block_count=block_count,
        extension_strategy=request.extension_strategy,
        temporal_blocks=blocks,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        execution_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
    )
