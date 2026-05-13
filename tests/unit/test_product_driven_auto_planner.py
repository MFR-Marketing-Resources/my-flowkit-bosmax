import inspect

import pytest

from agent.db import crud
from agent.services import product_driven_auto_planner
from agent.services.product_driven_auto_planner import create_product_driven_auto_plan


async def _create_product_with_image() -> str:
    created = await crud.create_product(
        raw_product_title="Round 2 Planner Test Product",
        source="FASTMOSS",
        product_display_name="Round 2 Planner Test Product",
        product_short_name="Round 2 Planner Test Product",
        image_url="https://example.com/round2-product.jpg",
        commission_rate="10%",
        price=29.9,
        category="Beauty Personal Care",
        subcategory="Fragrance",
        type="Body Spray",
        product_scale="handheld_small",
        copywriting_angle="Fresh daily confidence",
        claim_risk_level="LOW",
        scene_context="clean vanity shelf",
        camera_style="beauty product close-up",
        camera_behavior="slow reflective rotation",
        section_5_product_physics_prompt="Keep the bottle label-forward with careful wrist control.",
    )
    return created["id"]


@pytest.mark.asyncio
async def test_valid_product_payload_creates_product_driven_planner_request():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Portable body spray test product",
                "product_display_name": "Portable body spray",
                "product_short_name": "Portable spray",
                "source": "FASTMOSS",
                "image_url": "https://example.com/spray.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "target_duration_seconds": 8,
            "extension_strategy": "NONE",
        }
    )

    assert result.planning_status == "WARN"
    assert result.planner_request["source_route"] == "PRODUCT_DRIVEN_AUTO"
    assert result.planner_request["destination_mode"] == "TEXT_TO_VIDEO"
    assert result.planner_request["output_type"] == "PROMPT_BLOCK_PLAN"


@pytest.mark.asyncio
async def test_product_context_maps_category_subcategory_and_product_scale():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Fragrance test product",
                "product_display_name": "Fragrance test product",
                "product_short_name": "Fragrance test",
                "source": "FASTMOSS",
                "category": "Beauty Personal Care",
                "subcategory": "Fragrance",
                "type": "Body Spray",
                "product_scale": "palm_size",
                "image_url": "https://example.com/fragrance.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert result.product_context["category"] == "Beauty & Personal Care"
    assert result.product_context["subcategory"] == "Fragrance"
    assert result.product_context["product_scale"] == "SMALL_OBJECT"


@pytest.mark.asyncio
async def test_missing_product_dimension_generates_not_verified_warning():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Dimension-missing product",
                "product_display_name": "Dimension-missing product",
                "product_short_name": "Dimension missing",
                "source": "FASTMOSS",
                "image_url": "https://example.com/product.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert "PRODUCT_DIMENSION_MISSING_OR_UNVERIFIED" in result.warnings
    assert "product_dimensions" in result.not_verified_fields


@pytest.mark.asyncio
async def test_missing_product_image_generates_warning():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Image-missing product",
                "product_display_name": "Image-missing product",
                "product_short_name": "Image missing",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert "PRODUCT_IMAGE_MISSING" in result.warnings


@pytest.mark.asyncio
async def test_product_upload_unimplemented_generates_warning():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Upload-pending product",
                "product_display_name": "Upload-pending product",
                "product_short_name": "Upload pending",
                "source": "FASTMOSS",
                "image_url": "https://example.com/upload-pending.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert "PRODUCT_UPLOAD_TO_FLOW_MEDIA_HANDOFF_NOT_IMPLEMENTED" in result.warnings


@pytest.mark.asyncio
async def test_automatic_character_inference_not_verified_unless_explicit_data_exists():
    result_without_data = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Character inference product",
                "product_display_name": "Character inference product",
                "product_short_name": "Character inference",
                "source": "FASTMOSS",
                "image_url": "https://example.com/character.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )
    result_with_data = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Character data product",
                "product_display_name": "Character data product",
                "product_short_name": "Character data",
                "source": "FASTMOSS",
                "image_url": "https://example.com/character-data.jpg",
                "character_recommendations": ["Adult female presenter"],
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert "AUTOMATIC_CHARACTER_INFERENCE_NOT_VERIFIED" in result_without_data.warnings
    assert "AUTOMATIC_CHARACTER_INFERENCE_NOT_VERIFIED" not in result_with_data.warnings
    assert result_with_data.inferred_context["character_inference_status"] == "EXPLICIT_DATA"


@pytest.mark.asyncio
async def test_text_to_video_works_with_product_context_and_warnings():
    result = await create_product_driven_auto_plan(
        {
            "product_id": await _create_product_with_image(),
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "target_duration_seconds": 8,
        }
    )

    assert result.planning_status == "WARN"
    assert result.product_context["product_id"] is not None
    assert result.planner_output["block_count"] == 1


@pytest.mark.asyncio
async def test_ingredients_16s_calls_offline_planner_and_creates_two_blocks(monkeypatch):
    actual = product_driven_auto_planner.create_offline_prompt_plan
    call_state = {"called": False}

    async def _spy(planner_request):
        call_state["called"] = True
        return await actual(planner_request)

    monkeypatch.setattr(product_driven_auto_planner, "create_offline_prompt_plan", _spy)

    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Ingredients planner product",
                "product_display_name": "Ingredients planner product",
                "product_short_name": "Ingredients planner",
                "source": "FASTMOSS",
                "image_url": "https://example.com/ingredients.jpg",
            },
            "destination_mode": "INGREDIENTS",
            "output_type": "PROMPT_BLOCK_PLAN",
            "target_duration_seconds": 16,
            "asset_bindings": [
                {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
                {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
                {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
            ],
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert call_state["called"] is True
    assert result.planner_output["block_count"] == 2
    assert len(result.planner_output["blocks"]) == 2


@pytest.mark.asyncio
async def test_image_mode_creates_product_driven_image_planning_without_video_continuation():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Image planner product",
                "product_display_name": "Image planner product",
                "product_short_name": "Image planner",
                "source": "FASTMOSS",
                "image_url": "https://example.com/image-planner.jpg",
            },
            "destination_mode": "IMAGE",
            "output_type": "IMAGE_PROMPT",
            "target_duration_seconds": 32,
            "extension_strategy": "EXTEND_CONTINUITY",
        }
    )

    assert result.planner_output["block_count"] == 1
    assert len(result.planner_output["blocks"]) == 1
    assert result.planner_output["blocks"][0]["flow_action"] == "INITIAL_GENERATE"


@pytest.mark.asyncio
async def test_invalid_product_id_returns_fail():
    result = await create_product_driven_auto_plan(
        {
            "product_id": "missing-product-id",
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    assert result.planning_status == "FAIL"
    assert "PRODUCT_NOT_FOUND" in result.errors


@pytest.mark.asyncio
async def test_attempt_to_invent_product_dimensions_or_claims_returns_fail():
    dimension_result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Unsafe dimension invention product",
                "product_display_name": "Unsafe dimension invention product",
                "product_short_name": "Unsafe dimension invention",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "invent_product_dimensions": True,
        }
    )
    claim_result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Unsafe claim invention product",
                "product_display_name": "Unsafe claim invention product",
                "product_short_name": "Unsafe claim invention",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "invent_product_claims": True,
        }
    )

    assert dimension_result.planning_status == "FAIL"
    assert "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED" in dimension_result.errors
    assert claim_result.planning_status == "FAIL"
    assert "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED" in claim_result.errors


@pytest.mark.asyncio
async def test_dom_batch_and_canonical_write_attempts_return_fail():
    dom_result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "DOM request product",
                "product_display_name": "DOM request product",
                "product_short_name": "DOM request",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "execute_dom": True,
        }
    )
    batch_result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Batch request product",
                "product_display_name": "Batch request product",
                "product_short_name": "Batch request",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "batch_execution": True,
        }
    )
    write_result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Canonical write request product",
                "product_display_name": "Canonical write request product",
                "product_short_name": "Canonical write request",
                "source": "FASTMOSS",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
            "canonical_registry_write": True,
        }
    )

    assert dom_result.planning_status == "FAIL"
    assert "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_2" in dom_result.errors
    assert batch_result.planning_status == "FAIL"
    assert "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_2" in batch_result.errors
    assert write_result.planning_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_2" in write_result.errors


@pytest.mark.asyncio
async def test_no_flow_extension_batch_or_dom_modules_imported_or_called():
    result = await create_product_driven_auto_plan(
        {
            "product_payload": {
                "raw_product_title": "Safety source inspection product",
                "product_display_name": "Safety source inspection product",
                "product_short_name": "Safety source inspection",
                "source": "FASTMOSS",
                "image_url": "https://example.com/safety.jpg",
            },
            "destination_mode": "TEXT_TO_VIDEO",
            "output_type": "PROMPT_BLOCK_PLAN",
        }
    )

    source = inspect.getsource(product_driven_auto_planner)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "execute_flow_job",
        "smoke_execute_flow_job",
    ]

    assert result.provenance["uses_flow_execution"] is False
    assert result.provenance["uses_extension_runtime"] is False
    assert result.provenance["uses_batch_execution"] is False
    for token in banned_tokens:
        assert token not in source
