import inspect

import pytest

from agent.services.temporal_block_planner import create_temporal_block_plan


def _video_request(duration: int = 8, strategy: str = "NONE") -> dict:
    return {
        "composer_status": "WARN",
        "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
        "destination_mode": "TEXT_TO_VIDEO",
        "output_type": "VIDEO_9_SECTION_PROMPT",
        "prompt_text": (
            "1. Biometric Anchor DNA & Temporal Persistence: Stable presenter.\n\n"
            "2. Lighting & Scene Physics: Premium warm vanity lighting.\n\n"
            "3. Camera & Framing: Medium shot into close-up.\n\n"
            "4. Visual Action & Expansion: Reveal and rotate product.\n\n"
            "5. Product Physics & HOI: Hold product upright with label visible.\n\n"
            "6. Dialogue & Silo Purity: Clear concise benefit-led narration.\n\n"
            "7. Audio Sync & Tone: Confident polished tone.\n\n"
            "8. Temporal Chaining & Manifold Logic: Stable continuity.\n\n"
            "9. Overlay & Typography: Minimal overlay strategy."
        ),
        "sections": [
            "1. Biometric Anchor DNA & Temporal Persistence: Stable presenter.",
            "2. Lighting & Scene Physics: Premium warm vanity lighting.",
            "3. Camera & Framing: Medium shot into close-up.",
            "4. Visual Action & Expansion: Reveal and rotate product.",
            "5. Product Physics & HOI: Hold product upright with label visible.",
            "6. Dialogue & Silo Purity: Clear concise benefit-led narration.",
            "7. Audio Sync & Tone: Confident polished tone.",
            "8. Temporal Chaining & Manifold Logic: Stable continuity.",
            "9. Overlay & Typography: Minimal overlay strategy.",
        ],
        "section_count": 9,
        "block_summary": {
            "block_count": 1,
            "extension_strategy": strategy,
        },
        "warnings": [
            "PRODUCT_DIMENSIONS_NOT_VERIFIED",
            "PRODUCT_CLAIMS_NOT_HARD_ENFORCED",
            "PRODUCT_IMAGE_MISSING",
            "CHARACTER_ASSET_NOT_VERIFIED",
            "PRODUCT_HANDLING_INFERRED",
        ],
        "errors": [],
        "provenance": {
            "scope": "ROUND_5_PROMPT_OUTPUT_COMPOSER_ONLY",
            "uses_flow_execution": False,
            "uses_batch_execution": False,
            "uses_extension_runtime": False,
        },
        "execution_allowed": False,
        "target_duration_seconds": duration,
        "block_duration_seconds": 8,
        "extension_strategy": strategy,
        "transition_intent": "START",
        "allow_insert_jump_to": strategy == "INSERT_JUMP_TO",
        "allow_mixed_strategy": strategy == "MIXED",
        "requested_block_count": duration // 8,
        "per_block_intent_notes": [],
    }


@pytest.mark.asyncio
async def test_8s_video_9_section_prompt_creates_one_opening_block():
    result = await create_temporal_block_plan(_video_request(8, "NONE"))

    assert result.temporal_status == "WARN"
    assert result.block_count == 1
    assert result.temporal_blocks[0].prompt_role == "OPENING"
    assert result.temporal_blocks[0].flow_action_planned == "INITIAL_GENERATE"


@pytest.mark.asyncio
async def test_16s_extend_continuity_creates_two_blocks_and_block2_depends_on_block1():
    result = await create_temporal_block_plan(_video_request(16, "EXTEND_CONTINUITY"))

    assert result.block_count == 2
    assert result.temporal_blocks[1].depends_on_block_index == 1
    assert result.temporal_blocks[1].flow_action_planned == "EXTEND_CONTINUITY"
    assert result.temporal_blocks[1].continuation_prefix == "From the last frame, the same character continues..."


@pytest.mark.asyncio
async def test_24s_extend_continuity_creates_three_blocks_with_sequential_dependencies():
    result = await create_temporal_block_plan(_video_request(24, "EXTEND_CONTINUITY"))

    assert result.block_count == 3
    assert [block.depends_on_block_index for block in result.temporal_blocks] == [None, 1, 2]


@pytest.mark.asyncio
async def test_32s_extend_continuity_creates_four_blocks_with_sequential_dependencies():
    result = await create_temporal_block_plan(_video_request(32, "EXTEND_CONTINUITY"))

    assert result.block_count == 4
    assert [block.depends_on_block_index for block in result.temporal_blocks] == [None, 1, 2, 3]


@pytest.mark.asyncio
async def test_insert_jump_to_creates_jump_to_intent_and_does_not_use_extend_wording_silently():
    result = await create_temporal_block_plan(_video_request(16, "INSERT_JUMP_TO"))

    second = result.temporal_blocks[1]
    assert second.transition_intent == "JUMP_TO"
    assert second.flow_action_planned == "INSERT_JUMP_TO"
    assert second.continuation_prefix is None
    assert "From the last frame" not in second.prompt_text


@pytest.mark.asyncio
async def test_mixed_without_per_block_strategy_metadata_fails():
    result = await create_temporal_block_plan(_video_request(16, "MIXED"))

    assert result.temporal_status == "FAIL"
    assert "MIXED_STRATEGY_REQUIRES_PER_BLOCK_METADATA" in result.errors


@pytest.mark.asyncio
async def test_none_with_multi_block_duration_fails():
    result = await create_temporal_block_plan(_video_request(16, "NONE"))

    assert result.temporal_status == "FAIL"
    assert "NONE_STRATEGY_NOT_ALLOWED_FOR_MULTI_BLOCK_OUTPUT" in result.errors


@pytest.mark.asyncio
async def test_non_divisible_target_duration_fails():
    request = _video_request(16, "EXTEND_CONTINUITY")
    request["target_duration_seconds"] = 12
    request["requested_block_count"] = None

    result = await create_temporal_block_plan(request)

    assert result.temporal_status == "FAIL"
    assert "INVALID_TARGET_DURATION_SECONDS:12" in result.errors


@pytest.mark.asyncio
async def test_upstream_warnings_are_preserved():
    result = await create_temporal_block_plan(_video_request(8, "NONE"))

    assert "PRODUCT_DIMENSIONS_NOT_VERIFIED" in result.warnings
    assert "PRODUCT_CLAIMS_NOT_HARD_ENFORCED" in result.warnings
    assert "UPSTREAM_COMPOSER_WARN" in result.warnings


@pytest.mark.asyncio
async def test_proposed_8_second_block_math_warning_exists():
    result = await create_temporal_block_plan(_video_request(16, "EXTEND_CONTINUITY"))

    assert "PROPOSED_8_SECOND_BLOCK_MATH_IN_USE" in result.warnings


@pytest.mark.asyncio
async def test_operator_blueprint_conflict_warning_exists():
    result = await create_temporal_block_plan(_video_request(16, "EXTEND_CONTINUITY"))

    assert "CURRENT_OPERATOR_BLUEPRINT_4_SCENE_8_SCENE_LOGIC_MAY_CONFLICT_WITH_DURATION_DIVIDED_BY_8_BLOCK_PLANNING" in result.warnings


@pytest.mark.asyncio
async def test_image_prompt_temporal_planning_fails_by_default():
    request = _video_request(8, "NONE")
    request["destination_mode"] = "IMAGE"
    request["output_type"] = "IMAGE_PROMPT"

    result = await create_temporal_block_plan(request)

    assert result.temporal_status == "FAIL"
    assert "IMAGE_PROMPT_TEMPORAL_PLANNING_NOT_ALLOWED_BY_DEFAULT" in result.errors


@pytest.mark.asyncio
async def test_dom_flow_and_batch_execution_attempts_fail():
    dom_request = _video_request(8, "NONE")
    dom_request["execute_dom"] = True
    flow_request = _video_request(8, "NONE")
    flow_request["execute_flow"] = True
    batch_request = _video_request(8, "NONE")
    batch_request["batch_execution"] = True

    dom_result = await create_temporal_block_plan(dom_request)
    flow_result = await create_temporal_block_plan(flow_request)
    batch_result = await create_temporal_block_plan(batch_request)

    assert "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_6" in dom_result.errors
    assert "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_6" in flow_result.errors
    assert "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_6" in batch_result.errors


@pytest.mark.asyncio
async def test_extend_insert_execution_attempts_fail():
    extend_request = _video_request(16, "EXTEND_CONTINUITY")
    extend_request["execute_extend"] = True
    insert_request = _video_request(16, "INSERT_JUMP_TO")
    insert_request["execute_insert"] = True
    insert_request["allow_insert_jump_to"] = True

    extend_result = await create_temporal_block_plan(extend_request)
    insert_result = await create_temporal_block_plan(insert_request)

    assert "EXTEND_INSERT_EXECUTION_NOT_ALLOWED_IN_ROUND_6" in extend_result.errors
    assert "EXTEND_INSERT_EXECUTION_NOT_ALLOWED_IN_ROUND_6" in insert_result.errors


@pytest.mark.asyncio
async def test_render_complete_detection_attempt_fails():
    request = _video_request(16, "EXTEND_CONTINUITY")
    request["render_complete_detection"] = True

    result = await create_temporal_block_plan(request)

    assert result.temporal_status == "FAIL"
    assert "RENDER_COMPLETE_DETECTION_NOT_ALLOWED_IN_ROUND_6" in result.errors


@pytest.mark.asyncio
async def test_canonical_registry_write_attempt_fails():
    request = _video_request(8, "NONE")
    request["canonical_registry_write"] = True

    result = await create_temporal_block_plan(request)

    assert result.temporal_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_6" in result.errors


@pytest.mark.asyncio
async def test_dimension_claim_invention_attempt_fails():
    dimension_request = _video_request(8, "NONE")
    dimension_request["invent_product_dimensions"] = True
    claim_request = _video_request(8, "NONE")
    claim_request["invent_product_claims"] = True

    dimension_result = await create_temporal_block_plan(dimension_request)
    claim_result = await create_temporal_block_plan(claim_request)

    assert "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED" in dimension_result.errors
    assert "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED" in claim_result.errors


@pytest.mark.asyncio
async def test_forbidden_internal_marker_leakage_fails():
    request = _video_request(8, "NONE")
    request["prompt_text"] = "CTX_BAD temporal prompt."

    result = await create_temporal_block_plan(request)

    assert result.temporal_status == "FAIL"
    assert "FORBIDDEN_INTERNAL_MARKER_LEAKAGE" in result.errors


@pytest.mark.asyncio
async def test_execution_flags_are_always_false():
    result = await create_temporal_block_plan(_video_request(24, "EXTEND_CONTINUITY"))

    assert result.execution_allowed is False
    assert result.flow_execution_allowed is False
    assert result.batch_execution_allowed is False


@pytest.mark.asyncio
async def test_no_flow_extension_batch_dom_ui_or_runtime_orchestration_modules_imported_or_called():
    result = await create_temporal_block_plan(_video_request(16, "EXTEND_CONTINUITY"))

    from agent.services import temporal_block_planner

    source = inspect.getsource(temporal_block_planner)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "agent.api",
        "dashboard.",
        "render_complete_detection_worker",
        "runtime_orchestrator",
    ]

    assert result.provenance["uses_flow_execution"] is False
    assert result.provenance["uses_extension_runtime"] is False
    assert result.provenance["uses_batch_execution"] is False
    assert result.provenance["uses_ui_api_modules"] is False
    assert result.provenance["uses_runtime_orchestration"] is False
    for token in banned_tokens:
        assert token not in source
