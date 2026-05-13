import inspect

import pytest

from agent.db import crud
from agent.services import offline_prompt_planner
from agent.services.offline_prompt_planner import create_offline_prompt_plan


async def _create_product_with_image() -> str:
    created = await crud.create_product(
        raw_product_title="Sumikko Planning Test Product",
        source="FASTMOSS",
        product_display_name="Sumikko Planning Test Product",
        product_short_name="Sumikko Planning Test Product",
        image_url="https://example.com/planner-product.jpg",
        commission_rate="10%",
        price=29.9,
    )
    return created["id"]


@pytest.mark.asyncio
async def test_text_to_video_8s_creates_1_block():
    result = await create_offline_prompt_plan(
        {
            "source_route": "PRODUCT_DRIVEN_AUTO",
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "product_id": await _create_product_with_image(),
            "target_duration_seconds": 8,
            "block_duration_seconds": 8,
            "extension_strategy": "NONE",
        }
    )

    assert result.block_count == 1
    assert len(result.blocks) == 1
    assert result.blocks[0].flow_action == "INITIAL_GENERATE"
    assert all(block.execution_status == "PLANNED" for block in result.blocks)


@pytest.mark.asyncio
async def test_ingredients_16s_creates_2_planned_blocks():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "INGREDIENTS",
            "output_type": "PROMPT_BLOCK_PLAN",
            "asset_bindings": [
                {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
            ],
            "target_duration_seconds": 16,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.planning_status == "WARN"
    assert result.block_count == 2
    assert len(result.blocks) == 2
    assert result.blocks[1].depends_on_block_index == 1
    assert all(block.execution_status == "PLANNED" for block in result.blocks)


@pytest.mark.asyncio
async def test_frames_24s_creates_3_planned_blocks():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "asset_bindings": [
                {"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"},
            ],
            "target_duration_seconds": 24,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.block_count == 3
    assert len(result.blocks) == 3
    assert result.blocks[2].depends_on_block_index == 2
    assert all(block.execution_status == "PLANNED" for block in result.blocks)


@pytest.mark.asyncio
async def test_image_mode_creates_image_prompt_planning_without_continuation_blocks():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "IMAGE",
            "output_type": "IMAGE_PROMPT",
            "target_duration_seconds": 32,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.block_count == 1
    assert len(result.blocks) == 1
    assert result.blocks[0].flow_action == "INITIAL_GENERATE"
    assert result.blocks[0].continuation_prefix is None
    assert all(block.flow_action != "EXTEND_CONTINUITY" for block in result.blocks)


@pytest.mark.asyncio
async def test_invalid_source_route_returns_fail():
    result = await create_offline_prompt_plan(
        {
            "source_route": "BAD_ROUTE",
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "target_duration_seconds": 8,
            "block_duration_seconds": 8,
            "extension_strategy": "NONE",
        }
    )

    assert result.planning_status == "FAIL"
    assert "UNKNOWN_SOURCE_ROUTE:BAD_ROUTE" in result.errors


@pytest.mark.asyncio
async def test_invalid_destination_mode_returns_fail():
    result = await create_offline_prompt_plan(
        {
            "source_route": "PRODUCT_DRIVEN_AUTO",
            "destination_mode": "BAD_MODE",
            "output_type": "PROMPT_BLOCK_PLAN",
            "product_id": await _create_product_with_image(),
            "target_duration_seconds": 8,
            "block_duration_seconds": 8,
            "extension_strategy": "NONE",
        }
    )

    assert result.planning_status == "FAIL"
    assert "UNKNOWN_DESTINATION_MODE:BAD_MODE" in result.errors


@pytest.mark.asyncio
async def test_missing_start_frame_for_frames_returns_fail():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "target_duration_seconds": 24,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.planning_status == "FAIL"
    assert "MISSING_REQUIRED_ASSET_ROLE:START_FRAME" in result.errors


@pytest.mark.asyncio
async def test_registry_route_emits_external_registry_warning():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "INGREDIENTS",
            "output_type": "PROMPT_BLOCK_PLAN",
            "asset_bindings": [
                {"asset_role": "SUBJECT_CHARACTER", "asset_source": "REGISTRY", "asset_id": "avatar-1"},
            ],
            "target_duration_seconds": 16,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert "EXTERNAL_REGISTRY_DATASETS_NOT_SOURCE_CONTROLLED" in result.warnings
    assert result.planning_status == "WARN"


@pytest.mark.asyncio
async def test_extend_continuity_depends_on_previous_block_and_uses_prefix():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "asset_bindings": [
                {"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"},
            ],
            "target_duration_seconds": 16,
            "block_duration_seconds": 8,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.blocks[1].depends_on_block_index == 1
    assert result.blocks[1].flow_action == "EXTEND_CONTINUITY"
    assert result.blocks[1].continuation_prefix == "From the last frame, the same character continues..."


@pytest.mark.asyncio
async def test_planner_never_calls_flow_batch_or_extension_runtime():
    result = await create_offline_prompt_plan(
        {
            "source_route": "REGISTRY_DRIVEN_MANUAL_ASSISTED",
            "destination_mode": "FRAMES",
            "output_type": "PROMPT_BLOCK_PLAN",
            "asset_bindings": [
                {"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"},
            ],
            "target_duration_seconds": 8,
            "block_duration_seconds": 8,
            "extension_strategy": "NONE",
        }
    )

    source = inspect.getsource(offline_prompt_planner)
    banned_tokens = [
        "execute_flow_job",
        "smoke_execute_flow_job",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "/api/flow/execute-flow-job",
    ]

    assert result.metadata["uses_flow_execution"] is False
    assert result.metadata["uses_batch_execution"] is False
    assert result.metadata["uses_extension_runtime"] is False
    assert await crud.list_requests() == []
    for token in banned_tokens:
        assert token not in source
