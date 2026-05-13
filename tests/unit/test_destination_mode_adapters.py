import inspect

import pytest

from agent.services.destination_mode_adapters import adapt_destination_mode_payload


def _base_planner_output(destination_mode: str, output_type: str, asset_requirements: list[dict], asset_bindings: list[dict], warnings: list[str] | None = None) -> dict:
    if destination_mode == "IMAGE":
        blocks = [
            {
                "block_index": 1,
                "flow_action": "INITIAL_GENERATE",
                "depends_on_block_index": None,
                "prompt_role": "IMAGE_GENERATION",
                "transition_intent": "START",
                "continuation_prefix": None,
                "execution_status": "PLANNED",
            }
        ]
        block_count = 1
    else:
        blocks = [
            {
                "block_index": 1,
                "flow_action": "INITIAL_GENERATE",
                "depends_on_block_index": None,
                "prompt_role": "OPENING",
                "transition_intent": "START",
                "continuation_prefix": None,
                "execution_status": "PLANNED",
            }
        ]
        block_count = 1

    return {
        "planning_status": "WARN" if warnings else "PASS",
        "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
        "destination_mode": destination_mode,
        "output_type": output_type,
        "target_duration_seconds": 8,
        "block_duration_seconds": 8,
        "block_count": block_count,
        "extension_strategy": "NONE",
        "asset_requirements": asset_requirements,
        "asset_bindings": asset_bindings,
        "warnings": warnings or [],
        "errors": [],
        "blocks": blocks,
        "metadata": {
            "scope": "ROUND_1_OFFLINE_PLANNER_ONLY",
            "uses_flow_execution": False,
            "uses_batch_execution": False,
            "uses_extension_runtime": False,
        },
    }


def _text_to_video_request() -> dict:
    return {
        "source_route": "PRODUCT_DRIVEN_AUTO",
        "destination_mode": "TEXT_TO_VIDEO",
        "output_type": "PROMPT_BLOCK_PLAN",
        "planner_output": _base_planner_output(
            "TEXT_TO_VIDEO",
            "PROMPT_BLOCK_PLAN",
            [
                {"asset_role": "PRODUCT", "required": False, "satisfied": False, "reason": "Optional product reference."},
                {"asset_role": "SUBJECT_CHARACTER", "required": False, "satisfied": False, "reason": "Optional character reference."},
            ],
            [],
            ["BLOCK_LOGIC_IS_PROPOSED_ONLY_AND_MAY_CONFLICT_WITH_OPERATOR_SCENE_BLUEPRINT"],
        ),
        "product_context": {
            "product_short_name": "Portable Spray",
            "scene_context": "clean vanity shelf",
        },
        "inferred_context": {
            "camera_style": "beauty close-up",
        },
        "warnings": ["PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED"],
    }


@pytest.mark.asyncio
async def test_text_to_video_adapter_returns_text_only_payload_with_required_fields():
    result = await adapt_destination_mode_payload(_text_to_video_request())

    payload = result.mode_payload
    assert result.adapter_status == "WARN"
    assert payload["mode"] == "TEXT_TO_VIDEO"
    assert payload["requires_images"] is False
    assert payload["text_only_generation"] is True
    assert payload["required_prompt_fields"] == [
        "character_description",
        "product_description",
        "scene_description",
        "action_description",
        "camera_description",
        "dialogue_or_narration",
    ]


@pytest.mark.asyncio
async def test_text_to_video_warns_on_missing_product_image_and_unverified_dimensions():
    result = await adapt_destination_mode_payload(_text_to_video_request())

    assert "TEXT_TO_VIDEO_WITHOUT_PRODUCT_IMAGE" in result.warnings
    assert "PRODUCT_DIMENSION_UNKNOWN_NOT_VERIFIED" in result.warnings
    assert "PRODUCT_CLAIMS_NOT_HARD_ENFORCED" in result.warnings


@pytest.mark.asyncio
async def test_frames_adapter_requires_start_frame_and_supports_optional_end_frame():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "planner_output": _base_planner_output(
                "FRAMES",
                "PROMPT_BLOCK_PLAN",
                [
                    {"asset_role": "START_FRAME", "required": True, "satisfied": True, "reason": "Frames mode requires start frame."},
                    {"asset_role": "END_FRAME", "required": False, "satisfied": False, "reason": "End frame optional."},
                ],
                [{"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"}],
            ),
            "asset_bindings": [{"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"}],
        }
    )

    assert result.mode_payload["requires_start_frame"] is True
    assert result.mode_payload["supports_end_frame"] is True


@pytest.mark.asyncio
async def test_frames_missing_start_frame_returns_fail():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "planner_output": _base_planner_output(
                "FRAMES",
                "PROMPT_BLOCK_PLAN",
                [
                    {"asset_role": "START_FRAME", "required": True, "satisfied": False, "reason": "Frames mode requires start frame."},
                ],
                [],
            ),
        }
    )

    assert result.adapter_status == "FAIL"
    assert "FRAMES_START_FRAME_REQUIRED" in result.errors


@pytest.mark.asyncio
async def test_ingredients_adapter_requires_subject_scene_style_roles():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "INGREDIENTS",
            "output_type": "PROMPT_BLOCK_PLAN",
            "planner_output": _base_planner_output(
                "INGREDIENTS",
                "PROMPT_BLOCK_PLAN",
                [
                    {"asset_role": "SUBJECT_CHARACTER", "required": True, "satisfied": True, "reason": "subject"},
                    {"asset_role": "SCENE", "required": True, "satisfied": True, "reason": "scene"},
                    {"asset_role": "STYLE", "required": True, "satisfied": True, "reason": "style"},
                ],
                [
                    {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                    {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                    {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
                ],
            ),
            "asset_bindings": [
                {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
            ],
        }
    )

    assert result.adapter_status in {"PASS", "WARN"}
    assert result.mode_payload["required_asset_roles"] == ["SUBJECT_CHARACTER", "SCENE", "STYLE"]


@pytest.mark.asyncio
async def test_ingredients_warns_when_product_is_supplied_because_slot_is_not_first_class():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "INGREDIENTS",
            "output_type": "PROMPT_BLOCK_PLAN",
            "planner_output": _base_planner_output(
                "INGREDIENTS",
                "PROMPT_BLOCK_PLAN",
                [
                    {"asset_role": "SUBJECT_CHARACTER", "required": True, "satisfied": True, "reason": "subject"},
                    {"asset_role": "SCENE", "required": True, "satisfied": True, "reason": "scene"},
                    {"asset_role": "STYLE", "required": True, "satisfied": True, "reason": "style"},
                    {"asset_role": "PRODUCT", "required": False, "satisfied": True, "reason": "product"},
                ],
                [
                    {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                    {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                    {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
                    {"asset_role": "PRODUCT", "asset_source": "REGISTERED_PRODUCT", "asset_id": "product-1"},
                ],
            ),
            "asset_bindings": [
                {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
                {"asset_role": "PRODUCT", "asset_source": "REGISTERED_PRODUCT", "asset_id": "product-1"},
            ],
        }
    )

    assert "INGREDIENTS_PRODUCT_SLOT_NOT_FIRST_CLASS" in result.warnings


@pytest.mark.asyncio
async def test_image_adapter_returns_image_only_payload_with_video_continuation_false():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "IMAGE",
            "output_type": "IMAGE_PROMPT",
            "planner_output": _base_planner_output("IMAGE", "IMAGE_PROMPT", [], []),
        }
    )

    assert result.mode_payload["mode"] == "IMAGE"
    assert result.mode_payload["image_generation"] is True
    assert result.mode_payload["video_continuation"] is False


@pytest.mark.asyncio
async def test_image_adapter_supports_character_holding_product_intent_as_planning_payload_only():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "PRODUCT_DRIVEN_AUTO",
            "destination_mode": "IMAGE",
            "output_type": "IMAGE_PROMPT",
            "planner_output": _base_planner_output("IMAGE", "IMAGE_PROMPT", [], []),
            "product_context": {"product_short_name": "Portable Spray"},
            "inferred_context": {"image_intent": "create_character_holding_product"},
        }
    )

    assert result.mode_payload["image_intent"] == "create_character_holding_product"
    assert "create_character_holding_product" in result.mode_payload["supported_intents"]


@pytest.mark.asyncio
async def test_upstream_warnings_are_preserved():
    result = await adapt_destination_mode_payload(_text_to_video_request())

    assert "PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED" in result.warnings
    assert "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE" in result.warnings
    assert "UPSTREAM_PLANNER_WARN" in result.warnings


@pytest.mark.asyncio
async def test_invalid_destination_mode_returns_fail():
    request = _text_to_video_request()
    request["destination_mode"] = "BAD_MODE"

    result = await adapt_destination_mode_payload(request)

    assert result.adapter_status == "FAIL"
    assert "UNKNOWN_DESTINATION_MODE:BAD_MODE" in result.errors


@pytest.mark.asyncio
async def test_missing_planner_output_returns_fail():
    result = await adapt_destination_mode_payload(
        {
            "source_route": "PRODUCT_DRIVEN_AUTO",
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert result.adapter_status == "FAIL"
    assert "MISSING_PLANNER_OUTPUT" in result.errors


@pytest.mark.asyncio
async def test_dom_flow_and_batch_execution_attempts_return_fail():
    dom_request = _text_to_video_request()
    dom_request["execute_dom"] = True
    flow_request = _text_to_video_request()
    flow_request["execute_flow"] = True
    batch_request = _text_to_video_request()
    batch_request["batch_execution"] = True

    dom_result = await adapt_destination_mode_payload(dom_request)
    flow_result = await adapt_destination_mode_payload(flow_request)
    batch_result = await adapt_destination_mode_payload(batch_request)

    assert "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_4" in dom_result.errors
    assert "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_4" in flow_result.errors
    assert "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_4" in batch_result.errors


@pytest.mark.asyncio
async def test_final_prompt_prose_generation_attempt_returns_fail():
    request = _text_to_video_request()
    request["generate_final_prompt_prose"] = True

    result = await adapt_destination_mode_payload(request)

    assert result.adapter_status == "FAIL"
    assert "FINAL_PROMPT_PROSE_GENERATION_NOT_ALLOWED_IN_ROUND_4" in result.errors


@pytest.mark.asyncio
async def test_canonical_registry_write_attempt_returns_fail():
    request = _text_to_video_request()
    request["canonical_registry_write"] = True

    result = await adapt_destination_mode_payload(request)

    assert result.adapter_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_4" in result.errors


@pytest.mark.asyncio
async def test_no_flow_extension_batch_dom_or_round2_round3_services_imported_or_called():
    result = await adapt_destination_mode_payload(_text_to_video_request())

    from agent.services import destination_mode_adapters

    source = inspect.getsource(destination_mode_adapters)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "product_driven_auto_planner",
        "create_product_driven_auto_plan",
        "registry_driven_manual_planner",
        "create_registry_driven_manual_plan",
    ]

    assert result.provenance["uses_flow_execution"] is False
    assert result.provenance["uses_extension_runtime"] is False
    assert result.provenance["uses_batch_execution"] is False
    assert result.provenance["uses_product_driven_auto_service"] is False
    assert result.provenance["uses_registry_driven_manual_service"] is False
    for token in banned_tokens:
        assert token not in source
