"""DE-AUTHORIZED FOR FINAL ENGINE OUTPUT (ADR-008, 2026-07-02).

This module is a FROZEN legacy prompt surface. Its section taxonomy conflicts
with the retained canonical 9-section authority. THE only sanctioned final
engine-facing prompt renderer is agent/services/canonical_prompt_compiler.py
(reached via ugc_video_prompt_compiler_service.compile_ugc_video_prompt).

Kept temporarily for preview/back-compat surfaces only. Do NOT wire it into any
final output path; do NOT repair it; delete it once parity proof exists.
"""
from __future__ import annotations

from typing import Any

from agent.models.prompt_preview import PromptPreviewRequest, PromptPreviewResponse
from agent.services.destination_mode_adapters import adapt_destination_mode_payload
from agent.services.product_driven_auto_planner import create_product_driven_auto_plan
from agent.services.prompt_output_composer import compose_prompt_output
from agent.services.registry_driven_manual_planner import create_registry_driven_manual_plan
from agent.services.temporal_block_planner import create_temporal_block_plan


ALLOWED_SOURCE_ROUTES = {"PRODUCT_DRIVEN_AUTO", "REGISTRY_DRIVEN_MANUAL_ASSISTED"}
ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT", "PROMPT_BLOCK_PLAN"}
COMPOSER_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT"}
TEMPORAL_OUTPUT_TYPES = {"VIDEO_9_SECTION_PROMPT"}
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
    "invent_dimensions",
}
FORBIDDEN_CLAIM_INVENTION_KEYS = {
    "invent_product_claims",
    "infer_unverified_claims",
    "force_product_claims",
    "invent_claims",
}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | PromptPreviewRequest,
) -> tuple[PromptPreviewRequest, dict[str, Any]]:
    if isinstance(request_input, PromptPreviewRequest):
        return request_input, request_input.model_dump()
    parsed = PromptPreviewRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _build_provenance(request: PromptPreviewRequest) -> dict[str, Any]:
    return {
        "scope": "ROUND_7_API_PREVIEW_LAYER_ONLY",
        "preview_pipeline_service": "agent.services.prompt_preview_pipeline.run_prompt_preview_pipeline",
        "preview_only_mode": True,
        "safe_offline_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_ui_modules": False,
        "uses_runtime_orchestration": False,
        "api_endpoint": "/api/prompt-preview/offline",
        "source_route": request.source_route,
        "destination_mode": request.destination_mode,
        "output_type": request.output_type,
    }


def _fail_response(
    request: PromptPreviewRequest,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
    planner_output: dict[str, Any] | None = None,
    adapter_output: dict[str, Any] | None = None,
    composer_output: dict[str, Any] | None = None,
    temporal_output: dict[str, Any] | None = None,
) -> PromptPreviewResponse:
    return PromptPreviewResponse(
        preview_status="FAIL",
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        planner_output=planner_output or {},
        adapter_output=adapter_output or {},
        composer_output=composer_output or {},
        temporal_output=temporal_output or {},
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        execution_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
        dry_run_only=True,
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


def _contains_forbidden_marker(value: Any) -> bool:
    for text in _collect_strings(value):
        for marker in FORBIDDEN_INTERNAL_MARKERS:
            if marker in text:
                return True
    return False


def _prompt_bearing_outputs(
    adapter_output: dict[str, Any],
    composer_output: dict[str, Any],
    temporal_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "adapter_mode_payload": adapter_output.get("mode_payload", {}),
        "composer_prompt_text": composer_output.get("prompt_text", ""),
        "composer_sections": composer_output.get("sections", []),
        "temporal_blocks": [
            {
                "continuation_prefix": block.get("continuation_prefix"),
                "prompt_text": block.get("prompt_text"),
            }
            for block in temporal_output.get("temporal_blocks", [])
        ],
    }


def _validate_request(request: PromptPreviewRequest, raw_request: dict[str, Any]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    if request.dry_run_only is not True:
        _unique_append(errors, "DRY_RUN_ONLY_FALSE_NOT_ALLOWED_IN_ROUND_7")

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_FLOW_KEYS):
        _unique_append(errors, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_EXTEND_INSERT_EXECUTION_KEYS):
        _unique_append(errors, "EXTEND_INSERT_EXECUTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_RENDER_DETECTION_KEYS):
        _unique_append(errors, "RENDER_COMPLETE_DETECTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_UPLOAD_EXECUTION_KEYS):
        _unique_append(errors, "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_7")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_7")
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

    return warnings, errors


def _planner_request_payload(request: PromptPreviewRequest) -> dict[str, Any]:
    payload = request.model_dump()
    payload["dry_run_only"] = True
    return payload


def _planner_output_dict(planner_response: Any) -> dict[str, Any]:
    return planner_response.model_dump() if planner_response else {}


def _adapter_request_payload(
    request: PromptPreviewRequest,
    planner_response: Any,
) -> dict[str, Any]:
    payload = {
        "source_route": request.source_route,
        "destination_mode": request.destination_mode,
        "output_type": request.output_type,
        "planner_output": planner_response.planner_output,
        "asset_bindings": request.asset_bindings,
        "warnings": list(planner_response.warnings),
        "errors": list(planner_response.errors),
        "provenance": dict(planner_response.provenance),
        "dry_run_only": True,
    }
    if hasattr(planner_response, "product_context"):
        payload["product_context"] = planner_response.product_context
    if hasattr(planner_response, "inferred_context"):
        payload["inferred_context"] = planner_response.inferred_context
    if hasattr(planner_response, "manual_context"):
        payload["manual_context"] = planner_response.manual_context
    return payload


def _preview_status(warnings: list[str], errors: list[str]) -> str:
    if errors:
        return "FAIL"
    if warnings:
        return "WARN"
    return "PASS"


def _merge_provenance(base: dict[str, Any], planner: dict[str, Any], adapter: dict[str, Any], composer: dict[str, Any], temporal: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged["planner_scope"] = planner.get("scope")
    merged["adapter_scope"] = adapter.get("scope")
    merged["composer_scope"] = composer.get("scope")
    merged["temporal_scope"] = temporal.get("scope")
    return merged


async def run_prompt_preview_pipeline(
    request_input: dict[str, Any] | PromptPreviewRequest,
) -> PromptPreviewResponse:
    request, raw_request = _normalize_request(request_input)
    warnings, errors = _validate_request(request, raw_request)
    provenance = _build_provenance(request)
    planner_output: dict[str, Any] = {}
    adapter_output: dict[str, Any] = {}
    composer_output: dict[str, Any] = {}
    temporal_output: dict[str, Any] = {}

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    planner_request = _planner_request_payload(request)
    if request.source_route == "PRODUCT_DRIVEN_AUTO":
        planner_response = await create_product_driven_auto_plan(planner_request)
    else:
        planner_response = await create_registry_driven_manual_plan(planner_request)

    planner_output = _planner_output_dict(planner_response)
    for item in planner_response.warnings:
        _unique_append(warnings, item)
    for item in planner_response.errors:
        _unique_append(errors, item)

    if planner_response.planning_status == "FAIL":
        _unique_append(errors, "DOWNSTREAM_PLANNER_FAIL")
        return _fail_response(request, errors, warnings, provenance, planner_output=planner_output)
    if planner_response.planning_status == "WARN":
        _unique_append(warnings, "DOWNSTREAM_PLANNER_WARN")

    adapter_response = await adapt_destination_mode_payload(_adapter_request_payload(request, planner_response))
    adapter_output = adapter_response.model_dump()
    for item in adapter_response.warnings:
        _unique_append(warnings, item)
    for item in adapter_response.errors:
        _unique_append(errors, item)

    if adapter_response.adapter_status == "FAIL":
        _unique_append(errors, "DOWNSTREAM_ADAPTER_FAIL")
        return _fail_response(
            request,
            errors,
            warnings,
            provenance,
            planner_output=planner_output,
            adapter_output=adapter_output,
        )
    if adapter_response.adapter_status == "WARN":
        _unique_append(warnings, "DOWNSTREAM_ADAPTER_WARN")

    if request.output_type in COMPOSER_OUTPUT_TYPES:
        composer_response = await compose_prompt_output(adapter_output)
        composer_output = composer_response.model_dump()
        for item in composer_response.warnings:
            _unique_append(warnings, item)
        for item in composer_response.errors:
            _unique_append(errors, item)

        if composer_response.composer_status == "FAIL":
            _unique_append(errors, "DOWNSTREAM_COMPOSER_FAIL")
            return _fail_response(
                request,
                errors,
                warnings,
                provenance,
                planner_output=planner_output,
                adapter_output=adapter_output,
                composer_output=composer_output,
            )
        if composer_response.composer_status == "WARN":
            _unique_append(warnings, "DOWNSTREAM_COMPOSER_WARN")

        if request.include_temporal_plan and request.output_type in TEMPORAL_OUTPUT_TYPES:
            temporal_request = {
                **composer_output,
                "target_duration_seconds": request.target_duration_seconds,
                "block_duration_seconds": request.block_duration_seconds,
                "extension_strategy": request.extension_strategy,
                "transition_intent": request.transition_intent,
                "allow_insert_jump_to": request.allow_insert_jump_to,
                "allow_mixed_strategy": request.allow_mixed_strategy,
                "requested_block_count": request.requested_block_count,
                "per_block_intent_notes": request.per_block_intent_notes,
                "allow_image_prompt_temporal_metadata_only": request.allow_image_prompt_temporal_metadata_only,
                "dry_run_only": True,
            }
            temporal_response = await create_temporal_block_plan(temporal_request)
            temporal_output = temporal_response.model_dump()
            for item in temporal_response.warnings:
                _unique_append(warnings, item)
            for item in temporal_response.errors:
                _unique_append(errors, item)

            if temporal_response.temporal_status == "FAIL":
                _unique_append(errors, "DOWNSTREAM_TEMPORAL_FAIL")
                return _fail_response(
                    request,
                    errors,
                    warnings,
                    provenance,
                    planner_output=planner_output,
                    adapter_output=adapter_output,
                    composer_output=composer_output,
                    temporal_output=temporal_output,
                )
            if temporal_response.temporal_status == "WARN":
                _unique_append(warnings, "DOWNSTREAM_TEMPORAL_WARN")
                _unique_append(warnings, "TEMPORAL_OUTPUT_IS_PLANNING_METADATA_ONLY")

    if _contains_forbidden_marker(_prompt_bearing_outputs(adapter_output, composer_output, temporal_output)):
        _unique_append(errors, "FORBIDDEN_INTERNAL_MARKER_LEAKAGE")
        return _fail_response(
            request,
            errors,
            warnings,
            provenance,
            planner_output=planner_output,
            adapter_output=adapter_output,
            composer_output=composer_output,
            temporal_output=temporal_output,
        )

    _unique_append(warnings, "PREVIEW_IS_OFFLINE_ONLY_NOT_FLOW_EXECUTION_READY")
    _unique_append(warnings, "GOOGLE_FLOW_DELIVERY_NOT_IMPLEMENTED")
    if request.include_temporal_plan and request.output_type in TEMPORAL_OUTPUT_TYPES:
        _unique_append(warnings, "TEMPORAL_OUTPUT_IS_PLANNING_METADATA_ONLY")

    preview_status = _preview_status(warnings, errors)
    return PromptPreviewResponse(
        preview_status=preview_status,
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        planner_output=planner_output,
        adapter_output=adapter_output,
        composer_output=composer_output,
        temporal_output=temporal_output,
        warnings=warnings,
        errors=errors,
        provenance=_merge_provenance(
            provenance,
            planner_output.get("provenance", {}),
            adapter_output.get("provenance", {}),
            composer_output.get("provenance", {}),
            temporal_output.get("provenance", {}),
        ),
        execution_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
        dry_run_only=True,
    )
