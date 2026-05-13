import inspect

import pytest

from agent.services.prompt_output_composer import compose_prompt_output


def _image_request() -> dict:
    return {
        "adapter_status": "WARN",
        "source_route": "PRODUCT_DRIVEN_AUTO",
        "destination_mode": "IMAGE",
        "output_type": "IMAGE_PROMPT",
        "mode_payload": {
            "mode": "IMAGE",
            "image_generation": True,
            "video_continuation": False,
            "image_intent": "create_character_holding_product",
            "composition": "Hero character in three-quarter framing holding the product near eye level.",
            "lighting": "Soft studio key light with natural skin tones and clean shadow separation.",
            "product_handling": "Hold the bottle upright with label visible and scale preserved.",
            "negative_prompt_notes": [
                "Do not invent unsupported product claims.",
                "Do not distort the bottle shape.",
            ],
            "aspect_ratio_or_platform": "vertical_9_16",
        },
        "asset_requirements": [
            {"asset_role": "PRODUCT", "required": False, "satisfied": False, "reason": "Optional product asset."},
            {"asset_role": "SUBJECT_CHARACTER", "required": False, "satisfied": False, "reason": "Optional character asset."},
        ],
        "missing_assets": [],
        "warnings": [
            "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED",
            "PRODUCT_CLAIMS_NOT_HARD_ENFORCED",
            "PRODUCT_IMAGE_MISSING",
            "IMAGE_PRODUCT_HANDLING_INFERRED",
            "IMAGE_CHARACTER_ASSET_NOT_VERIFIED",
            "PRODUCT_SLOT_NOT_FIRST_CLASS_IN_CURRENT_UI_SERVICE",
        ],
        "errors": [],
        "provenance": {
            "scope": "ROUND_4_DESTINATION_MODE_ADAPTERS_ONLY",
            "uses_flow_execution": False,
            "uses_batch_execution": False,
            "uses_extension_runtime": False,
        },
        "planner_block_summary": {
            "planning_status": "WARN",
            "block_count": 1,
            "block_duration_seconds": 8,
            "extension_strategy": "NONE",
        },
        "execution_allowed": False,
    }


def _video_request() -> dict:
    return {
        "adapter_status": "WARN",
        "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
        "destination_mode": "TEXT_TO_VIDEO",
        "output_type": "VIDEO_9_SECTION_PROMPT",
        "mode_payload": {
            "mode": "TEXT_TO_VIDEO",
            "character_description": "A confident presenter with stable facial features and clean wardrobe continuity.",
            "product_description": "A compact fragrance bottle with visible label and realistic handheld scale.",
            "scene_description": "A premium vanity environment with reflective surface control and warm atmosphere.",
            "action_description": "The presenter reveals the product, rotates it slightly, and brings it closer to camera.",
            "camera_description": "Start on a controlled medium shot, then tighten into a clean product-emphasis close-up.",
            "dialogue_or_narration": "Confident, concise narration focused on sensory appeal without unsupported claims.",
            "overlay_strategy": "Minimal mobile-safe benefit text with restrained branding.",
        },
        "asset_requirements": [
            {"asset_role": "PRODUCT", "required": False, "satisfied": False, "reason": "Optional textual product reference."},
        ],
        "missing_assets": [],
        "warnings": [
            "BLOCK_LOGIC_IS_PROPOSED_ONLY_AND_MAY_CONFLICT_WITH_OPERATOR_SCENE_BLUEPRINT",
            "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED",
            "PRODUCT_CLAIMS_NOT_HARD_ENFORCED",
        ],
        "errors": [],
        "provenance": {
            "scope": "ROUND_4_DESTINATION_MODE_ADAPTERS_ONLY",
            "uses_flow_execution": False,
            "uses_batch_execution": False,
            "uses_extension_runtime": False,
        },
        "planner_block_summary": {
            "planning_status": "WARN",
            "block_count": 2,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        },
        "execution_allowed": False,
    }


@pytest.mark.asyncio
async def test_image_prompt_composer_produces_offline_image_prompt_text_from_image_adapter_payload():
    result = await compose_prompt_output(_image_request())

    assert result.composer_status == "WARN"
    assert "Composition:" in result.prompt_text
    assert "Lighting:" in result.prompt_text
    assert result.negative_prompt_notes
    assert result.aspect_ratio_or_platform == "vertical_9_16"
    assert result.product_handling_notes == "Hold the bottle upright with label visible and scale preserved."


@pytest.mark.asyncio
async def test_image_prompt_preserves_upstream_warnings():
    result = await compose_prompt_output(_image_request())

    assert "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED" in result.warnings
    assert "PRODUCT_CLAIMS_NOT_HARD_ENFORCED" in result.warnings
    assert "PRODUCT_IMAGE_MISSING" in result.warnings


@pytest.mark.asyncio
async def test_image_prompt_returns_execution_allowed_false():
    result = await compose_prompt_output(_image_request())

    assert result.execution_allowed is False


@pytest.mark.asyncio
async def test_video_9_section_prompt_composer_produces_9_sections_when_safe_inputs_exist():
    result = await compose_prompt_output(_video_request())

    assert result.composer_status == "WARN"
    assert len(result.sections) == 9
    assert result.section_count == 9
    assert result.prompt_text.count("1. Biometric Anchor DNA & Temporal Persistence:") == 1
    assert result.overlay_notes == "Minimal mobile-safe benefit text with restrained branding."


@pytest.mark.asyncio
async def test_video_9_section_prompt_fails_if_assembly_cannot_be_completed_safely():
    request = _video_request()
    request["mode_payload"].pop("camera_description")

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "VIDEO_9_SECTION_REQUIRED_FIELDS_MISSING:camera_description" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_if_adapter_status_fail():
    request = _image_request()
    request["adapter_status"] = "FAIL"

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "UPSTREAM_ADAPTER_FAIL" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_invalid_output_type():
    request = _image_request()
    request["output_type"] = "PROMPT_BLOCK_PLAN"

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "UNKNOWN_OUTPUT_TYPE:PROMPT_BLOCK_PLAN" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_missing_adapter_payload():
    request = _image_request()
    request["mode_payload"] = None

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "MISSING_ADAPTER_PAYLOAD" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_dom_flow_and_batch_execution_attempts():
    dom_request = _image_request()
    dom_request["execute_dom"] = True
    flow_request = _image_request()
    flow_request["execute_flow"] = True
    batch_request = _image_request()
    batch_request["batch_execution"] = True

    dom_result = await compose_prompt_output(dom_request)
    flow_result = await compose_prompt_output(flow_request)
    batch_result = await compose_prompt_output(batch_request)

    assert "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_5" in dom_result.errors
    assert "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_5" in flow_result.errors
    assert "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_5" in batch_result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_upload_generation_execution_attempts():
    request = _image_request()
    request["execute_generation"] = True

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "UPLOAD_OR_GENERATION_EXECUTION_NOT_ALLOWED_IN_ROUND_5" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_canonical_registry_write_attempt():
    request = _image_request()
    request["canonical_registry_write"] = True

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_5" in result.errors


@pytest.mark.asyncio
async def test_composer_fails_on_dimension_or_claim_invention_attempt():
    dimension_request = _image_request()
    dimension_request["invent_product_dimensions"] = True
    claim_request = _image_request()
    claim_request["invent_product_claims"] = True

    dimension_result = await compose_prompt_output(dimension_request)
    claim_result = await compose_prompt_output(claim_request)

    assert "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED" in dimension_result.errors
    assert "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED" in claim_result.errors


@pytest.mark.asyncio
async def test_composer_warns_on_unverified_product_dimensions_and_non_hard_enforced_claims():
    result = await compose_prompt_output(_image_request())

    assert "PRODUCT_DIMENSIONS_NOT_VERIFIED" in result.warnings
    assert "PRODUCT_CLAIMS_NOT_HARD_ENFORCED" in result.warnings
    assert "OUTPUT_IS_OFFLINE_ONLY_NOT_FLOW_EXECUTION_READY" in result.warnings


@pytest.mark.asyncio
async def test_composer_fails_on_forbidden_internal_marker_leakage():
    request = _video_request()
    request["mode_payload"]["character_description"] = "CTX_HERO presenter with stable wardrobe continuity."

    result = await compose_prompt_output(request)

    assert result.composer_status == "FAIL"
    assert "FORBIDDEN_INTERNAL_MARKER_LEAKAGE" in result.errors


@pytest.mark.asyncio
async def test_composer_does_not_import_or_call_forbidden_runtime_or_round2_round3_or_ui_api_modules():
    result = await compose_prompt_output(_image_request())

    from agent.services import prompt_output_composer

    source = inspect.getsource(prompt_output_composer)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "product_driven_auto_planner",
        "create_product_driven_auto_plan",
        "registry_driven_manual_planner",
        "create_registry_driven_manual_plan",
        "agent.api",
        "dashboard.",
    ]

    assert result.provenance["uses_flow_execution"] is False
    assert result.provenance["uses_extension_runtime"] is False
    assert result.provenance["uses_batch_execution"] is False
    assert result.provenance["uses_product_driven_auto_service"] is False
    assert result.provenance["uses_registry_driven_manual_service"] is False
    assert result.provenance["uses_ui_api_modules"] is False
    for token in banned_tokens:
        assert token not in source
