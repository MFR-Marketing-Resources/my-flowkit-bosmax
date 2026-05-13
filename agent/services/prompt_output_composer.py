from __future__ import annotations

from typing import Any

from agent.models.prompt_output_composer import (
    PromptOutputComposerRequest,
    PromptOutputComposerResponse,
)
from agent.services.prompt_compiler_9_section import compile_9_section_prompt


ALLOWED_OUTPUT_TYPES = {"IMAGE_PROMPT", "VIDEO_9_SECTION_PROMPT"}
ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
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

IMAGE_REQUIRED_FIELDS = [
    "image_intent",
    "composition",
    "lighting",
    "product_handling",
    "negative_prompt_notes",
    "aspect_ratio_or_platform",
]
VIDEO_REQUIRED_FIELDS = [
    "character_description",
    "product_description",
    "scene_description",
    "action_description",
    "camera_description",
    "dialogue_or_narration",
]


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


def _normalize_request(
    request_input: dict[str, Any] | PromptOutputComposerRequest,
) -> tuple[PromptOutputComposerRequest, dict[str, Any]]:
    if isinstance(request_input, PromptOutputComposerRequest):
        return request_input, request_input.model_dump()
    parsed = PromptOutputComposerRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _build_provenance(request: PromptOutputComposerRequest) -> dict[str, Any]:
    return {
        "scope": "ROUND_5_PROMPT_OUTPUT_COMPOSER_ONLY",
        "composer_service": "agent.services.prompt_output_composer.compose_prompt_output",
        "safe_offline_mode": True,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_product_driven_auto_service": False,
        "uses_registry_driven_manual_service": False,
        "uses_ui_api_modules": False,
        "upstream_scope": request.provenance.get("scope"),
        "used_existing_9_section_compiler": False,
    }


def _fail_response(
    request: PromptOutputComposerRequest,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
) -> PromptOutputComposerResponse:
    return PromptOutputComposerResponse(
        composer_status="FAIL",
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        execution_allowed=False,
    )


def _normalize_notes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _asset_reference_notes(request: PromptOutputComposerRequest) -> list[str]:
    notes: list[str] = []
    requirement_roles = [item.get("asset_role") for item in request.asset_requirements if item.get("asset_role")]
    if requirement_roles:
        notes.append(f"Required asset roles: {', '.join(requirement_roles)}")
    if request.missing_assets:
        notes.append(f"Missing asset roles: {', '.join(request.missing_assets)}")
    notes.append(f"Destination mode scaffold: {request.destination_mode or 'UNKNOWN'}")
    return notes


def _best_effort_scrub(text: str) -> str:
    scrubbed = text.replace("{{", "").replace("}}", "")
    scrubbed = scrubbed.replace("[START_TIME", "START_TIME").replace("[END_TIME", "END_TIME")
    return scrubbed.strip()


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


def _contains_forbidden_marker(values: list[str]) -> bool:
    for value in values:
        for marker in FORBIDDEN_INTERNAL_MARKERS:
            if marker in value:
                return True
    return False


def _maybe_add_warning_from_upstream(warnings: list[str], upstream: list[str], source_code: str, target_code: str) -> None:
    if source_code in upstream:
        _unique_append(warnings, target_code)


def _compiler_variant_plan(mode_payload: dict[str, Any], raw_request: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    variant_plan = {
        "camera_route": _normalize_text(mode_payload.get("camera_description")) or _normalize_text(raw_request.get("camera_route")),
        "scene_context": _normalize_text(mode_payload.get("scene_description")) or _normalize_text(raw_request.get("scene_context")),
        "hook_angle": _normalize_text(mode_payload.get("action_description")) or _normalize_text(raw_request.get("hook_angle")),
        "overlay_strategy": _normalize_text(mode_payload.get("overlay_strategy")) or _normalize_text(raw_request.get("overlay_strategy")),
    }
    missing = [key for key, value in variant_plan.items() if not value]
    return variant_plan, missing


async def _compose_video_sections(
    request: PromptOutputComposerRequest,
    raw_request: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    provenance: dict[str, Any],
) -> tuple[list[str], str | None, str | None]:
    mode_payload = request.mode_payload or {}
    missing_fields = [field for field in VIDEO_REQUIRED_FIELDS if not _normalize_text(mode_payload.get(field))]
    if missing_fields:
        _unique_append(errors, f"VIDEO_9_SECTION_REQUIRED_FIELDS_MISSING:{','.join(missing_fields)}")
        return [], None, None

    overlay_notes = _normalize_text(mode_payload.get("overlay_strategy")) or _normalize_text(raw_request.get("overlay_strategy"))
    if not overlay_notes:
        overlay_notes = "Keep overlays minimal, readable, and subordinate to the visual story."

    product_handling_notes = _normalize_text(mode_payload.get("product_handling")) or _normalize_text(
        raw_request.get("product_handling_notes")
    )
    if not product_handling_notes:
        product_handling_notes = "Maintain product handling within verified appearance and known scale only."

    product_id = _normalize_text(raw_request.get("product_id"))
    variant_plan, compiler_missing = _compiler_variant_plan(mode_payload, raw_request)
    if not product_id:
        compiler_missing = ["product_id", *compiler_missing]
    if compiler_missing:
        _unique_append(
            warnings,
            f"NINE_SECTION_COMPILER_REQUIRES_MISSING_FIELDS:{','.join(dict.fromkeys(compiler_missing))}",
        )

    sections: list[str]
    if product_id and not compiler_missing:
        compiled = await compile_9_section_prompt(product_id, variant_plan)
        if compiled.startswith("Error:"):
            _unique_append(errors, f"NINE_SECTION_COMPILER_FAILED:{compiled}")
            return [], product_handling_notes, overlay_notes
        sections = [part.strip() for part in compiled.split("\n\n") if part.strip()]
        provenance["used_existing_9_section_compiler"] = True
    else:
        character_description = _normalize_text(mode_payload.get("character_description"))
        product_description = _normalize_text(mode_payload.get("product_description"))
        scene_description = _normalize_text(mode_payload.get("scene_description"))
        action_description = _normalize_text(mode_payload.get("action_description"))
        camera_description = _normalize_text(mode_payload.get("camera_description"))
        dialogue_or_narration = _normalize_text(mode_payload.get("dialogue_or_narration"))
        block_count = request.planner_block_summary.get("block_count") or 0
        extension_strategy = _normalize_text(request.planner_block_summary.get("extension_strategy")) or "NONE"

        sections = [
            f"1. Biometric Anchor DNA & Temporal Persistence: {character_description}",
            f"2. Lighting & Scene Physics: Preserve realistic lighting continuity within {scene_description}.",
            f"3. Camera & Framing: {camera_description}",
            f"4. Visual Action & Expansion: {action_description}",
            f"5. Product Physics & HOI: {product_handling_notes} Product reference: {product_description}",
            f"6. Dialogue & Silo Purity: {dialogue_or_narration}",
            "7. Audio Sync & Tone: Keep spoken or implied audio aligned with the visible action and emotional tone.",
            f"8. Temporal Chaining & Manifold Logic: Maintain continuity across {block_count or 1} planned block(s) with extension strategy {extension_strategy}.",
            f"9. Overlay & Typography: {overlay_notes}",
        ]

    if len(sections) != 9:
        _unique_append(errors, "VIDEO_9_SECTION_OUTPUT_NOT_EXACTLY_NINE_SECTIONS")
        return [], product_handling_notes, overlay_notes

    return sections, product_handling_notes, overlay_notes


def _compose_image_prompt(
    request: PromptOutputComposerRequest,
    warnings: list[str],
    errors: list[str],
) -> tuple[str, list[str], str | None, str | None]:
    mode_payload = request.mode_payload or {}
    missing_fields = [field for field in IMAGE_REQUIRED_FIELDS if not mode_payload.get(field)]
    if missing_fields:
        _unique_append(errors, f"IMAGE_PROMPT_REQUIRED_FIELDS_MISSING:{','.join(missing_fields)}")
        return "", [], None, None

    negative_prompt_notes = _normalize_notes(mode_payload.get("negative_prompt_notes"))
    aspect_ratio_or_platform = _normalize_text(mode_payload.get("aspect_ratio_or_platform"))
    product_handling_notes = _normalize_text(mode_payload.get("product_handling"))
    prompt_text = (
        f"{_normalize_text(mode_payload.get('image_intent'))}. "
        f"Composition: {_normalize_text(mode_payload.get('composition'))}. "
        f"Lighting: {_normalize_text(mode_payload.get('lighting'))}. "
        f"Product handling: {product_handling_notes}. "
        "Preserve referenced appearance where assets exist and avoid unsupported product truth."
    ).strip()

    _maybe_add_warning_from_upstream(warnings, request.warnings, "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED", "PRODUCT_DIMENSIONS_NOT_VERIFIED")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED", "PRODUCT_DIMENSIONS_NOT_VERIFIED")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "PRODUCT_CLAIMS_NOT_HARD_ENFORCED", "PRODUCT_CLAIMS_NOT_HARD_ENFORCED")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "CLAIM_BOUNDARY_NOT_HARD_ENFORCED_END_TO_END", "PRODUCT_CLAIMS_NOT_HARD_ENFORCED")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "PRODUCT_IMAGE_MISSING", "PRODUCT_IMAGE_MISSING")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "IMAGE_CHARACTER_ASSET_NOT_VERIFIED", "CHARACTER_ASSET_NOT_VERIFIED")
    _maybe_add_warning_from_upstream(warnings, request.warnings, "IMAGE_PRODUCT_HANDLING_INFERRED", "PRODUCT_HANDLING_INFERRED")
    _maybe_add_warning_from_upstream(
        warnings,
        request.warnings,
        "PRODUCT_SLOT_NOT_FIRST_CLASS_IN_CURRENT_UI_SERVICE",
        "PRODUCT_SLOT_LIMITATION_PRESENT",
    )
    _maybe_add_warning_from_upstream(
        warnings,
        request.warnings,
        "INGREDIENTS_PRODUCT_SLOT_NOT_FIRST_CLASS",
        "PRODUCT_SLOT_LIMITATION_PRESENT",
    )

    return prompt_text, negative_prompt_notes, aspect_ratio_or_platform, product_handling_notes


async def compose_prompt_output(
    request_input: dict[str, Any] | PromptOutputComposerRequest,
) -> PromptOutputComposerResponse:
    request, raw_request = _normalize_request(request_input)
    warnings = list(request.warnings)
    errors = list(request.errors)
    provenance = _build_provenance(request)

    if _has_truthy_flag(raw_request, FORBIDDEN_DOM_KEYS):
        _unique_append(errors, "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_5")
    if _has_truthy_flag(raw_request, FORBIDDEN_FLOW_KEYS):
        _unique_append(errors, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_5")
    if _has_truthy_flag(raw_request, FORBIDDEN_BATCH_KEYS):
        _unique_append(errors, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_5")
    if _has_truthy_flag(raw_request, FORBIDDEN_UPLOAD_EXECUTION_KEYS):
        _unique_append(errors, "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_5")
    if _has_truthy_flag(raw_request, FORBIDDEN_CANONICAL_WRITE_KEYS):
        _unique_append(errors, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_5")
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
    if request.adapter_status == "FAIL":
        _unique_append(errors, "UPSTREAM_ADAPTER_FAIL")
    if request.adapter_status == "WARN":
        _unique_append(warnings, "UPSTREAM_ADAPTER_WARN")
    if not request.mode_payload:
        _unique_append(errors, "MISSING_ADAPTER_PAYLOAD")

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    _unique_append(warnings, "OUTPUT_IS_OFFLINE_ONLY_NOT_FLOW_EXECUTION_READY")
    _unique_append(warnings, "INTERNAL_MARKER_SCRUB_IS_BEST_EFFORT_UNTIL_PROVEN_BY_TEST")
    asset_reference_notes = _asset_reference_notes(request)

    prompt_text = ""
    sections: list[str] = []
    section_count = 0
    block_summary = dict(request.planner_block_summary)
    negative_prompt_notes: list[str] = []
    aspect_ratio_or_platform: str | None = None
    product_handling_notes: str | None = None
    dialogue_or_narration_notes: str | None = None
    overlay_notes: str | None = None

    if request.output_type == "IMAGE_PROMPT":
        if _normalize_text((request.mode_payload or {}).get("mode")) != "IMAGE":
            _unique_append(errors, "IMAGE_PROMPT_REQUIRES_IMAGE_MODE_PAYLOAD")
        else:
            prompt_text, negative_prompt_notes, aspect_ratio_or_platform, product_handling_notes = _compose_image_prompt(
                request,
                warnings,
                errors,
            )
            dialogue_or_narration_notes = None
            overlay_notes = None
    else:
        if _normalize_text((request.mode_payload or {}).get("mode")) == "IMAGE":
            _unique_append(errors, "VIDEO_9_SECTION_PROMPT_REQUIRES_VIDEO_CAPABLE_MODE")
        else:
            sections, product_handling_notes, overlay_notes = await _compose_video_sections(
                request,
                raw_request,
                warnings,
                errors,
                provenance,
            )
            section_count = len(sections)
            prompt_text = "\n\n".join(sections)
            dialogue_or_narration_notes = _normalize_text((request.mode_payload or {}).get("dialogue_or_narration")) or None
            if section_count != 9:
                _unique_append(errors, "VIDEO_9_SECTION_PROMPT_CANNOT_BE_ASSEMBLED_SAFELY")

    prompt_text = _best_effort_scrub(prompt_text)
    cleaned_sections = [_best_effort_scrub(section) for section in sections]

    strings_to_validate = [prompt_text, *cleaned_sections, *negative_prompt_notes, *(asset_reference_notes or [])]
    if _contains_forbidden_marker(strings_to_validate):
        _unique_append(errors, "FORBIDDEN_INTERNAL_MARKER_LEAKAGE")

    if errors:
        return _fail_response(request, errors, warnings, provenance)

    composer_status = "WARN" if warnings else "PASS"
    return PromptOutputComposerResponse(
        composer_status=composer_status,
        source_route=request.source_route,
        destination_mode=request.destination_mode,
        output_type=request.output_type,
        prompt_text=prompt_text,
        sections=cleaned_sections,
        section_count=len(cleaned_sections),
        block_summary=block_summary,
        negative_prompt_notes=negative_prompt_notes,
        aspect_ratio_or_platform=aspect_ratio_or_platform,
        product_handling_notes=product_handling_notes,
        asset_reference_notes=asset_reference_notes,
        dialogue_or_narration_notes=dialogue_or_narration_notes,
        overlay_notes=overlay_notes,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        execution_allowed=False,
    )
