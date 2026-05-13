import inspect

import pytest

from agent.db import crud
from agent.services import registry_driven_manual_planner
from agent.services.registry_driven_manual_planner import create_registry_driven_manual_plan


async def _create_product_with_image() -> str:
    created = await crud.create_product(
        raw_product_title="Round 3 Manual Planner Test Product",
        source="FASTMOSS",
        product_display_name="Round 3 Manual Planner Test Product",
        product_short_name="Round 3 Manual Planner Test Product",
        image_url="https://example.com/round3-product.jpg",
        commission_rate="10%",
        price=29.9,
        category="Beauty Personal Care",
        subcategory="Fragrance",
        type="Body Spray",
        copywriting_angle="Fresh daily confidence",
        claim_risk_level="LOW",
        scene_context="clean vanity shelf",
        camera_style="beauty product close-up",
        camera_behavior="slow reflective rotation",
        section_5_product_physics_prompt="Keep the bottle label-forward with careful wrist control.",
    )
    return created["id"]


def _base_manual_payload() -> dict:
    return {
        "avatar_id": "avatar_malay_female_01",
        "headwear_style": "none",
        "scene_context": "car interior ugc scene",
        "camera_style": "ugc handheld",
        "camera_behavior": "slow front-seat pan",
        "trigger_id": "TRUST_01",
        "silo": "perfume_mass_01",
        "formula": "PAS",
        "language": "Malay",
        "platform": "TikTok",
        "engine": "google_flow",
        "destination_mode": "TEXT_TO_VIDEO",
        "output_type": "PROMPT_BLOCK_PLAN",
        "target_duration_seconds": 8,
        "extension_strategy": "NONE",
    }


@pytest.mark.asyncio
async def test_valid_manual_payload_creates_registry_driven_planner_request():
    payload = _base_manual_payload()

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "WARN"
    assert result.planner_request["source_route"] == "REGISTRY_DRIVEN_MANUAL_ASSISTED"
    assert result.planner_request["destination_mode"] == "TEXT_TO_VIDEO"
    assert result.planner_request["output_type"] == "PROMPT_BLOCK_PLAN"


@pytest.mark.asyncio
async def test_selected_fields_map_into_manual_context():
    payload = _base_manual_payload()

    result = await create_registry_driven_manual_plan(payload)

    assert result.manual_context["avatar_id"] == "avatar_malay_female_01"
    assert result.manual_context["headwear_style"] == "none"
    assert result.manual_context["scene_context"] == "car interior ugc scene"
    assert result.manual_context["camera_style"] == "ugc handheld"
    assert result.manual_context["camera_behavior"] == "slow front-seat pan"
    assert result.manual_context["formula"] == "PAS"
    assert result.manual_context["language"] == "Malay"


@pytest.mark.asyncio
async def test_external_operator_pack_registry_dependency_generates_warning():
    result = await create_registry_driven_manual_plan(_base_manual_payload())

    assert "EXTERNAL_OPERATOR_PACK_REGISTRY_NOT_LOCAL_REPO_TRUTH" in result.warnings
    assert "external_operator_pack_registry" in result.not_verified_fields
    assert "MASTER_IGNITION_TEMPLATE.yaml" in result.external_registry_dependencies


@pytest.mark.asyncio
async def test_wardrobe_registry_not_proven_generates_warning():
    payload = _base_manual_payload()
    payload["wardrobe_id"] = "wardrobe_preview_01"

    result = await create_registry_driven_manual_plan(payload)

    assert "WARDROBE_REGISTRY_NOT_PROVEN" in result.warnings
    assert "wardrobe_registry" in result.not_verified_fields


@pytest.mark.asyncio
async def test_full_tuple_legality_not_proven_generates_warning():
    result = await create_registry_driven_manual_plan(_base_manual_payload())

    assert "FULL_TUPLE_LEGALITY_VALIDATION_NOT_PROVEN" in result.warnings
    assert result.compatibility_status["tuple_legality_validation"] == "NOT_VERIFIED"


@pytest.mark.asyncio
async def test_canonical_vs_preview_isolation_not_enforced_generates_warning():
    result = await create_registry_driven_manual_plan(_base_manual_payload())

    assert "CANONICAL_VS_PREVIEW_ISOLATION_NOT_ENFORCED" in result.warnings
    assert result.compatibility_status["canonical_vs_preview_isolation"] == "NOT_VERIFIED"


@pytest.mark.asyncio
async def test_text_to_video_works_with_manual_context_and_warnings():
    payload = _base_manual_payload()
    payload["product_id"] = await _create_product_with_image()

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "WARN"
    assert result.manual_context["product_context"]["product_id"] is not None
    assert result.planner_output["block_count"] == 1


@pytest.mark.asyncio
async def test_frames_16s_with_start_frame_creates_two_blocks():
    payload = _base_manual_payload()
    payload["destination_mode"] = "FRAMES"
    payload["target_duration_seconds"] = 16
    payload["extension_strategy"] = "EXTEND_CONTINUITY"
    payload["asset_bindings"] = [
        {"asset_role": "START_FRAME", "asset_source": "UPLOADED_IMAGE", "asset_id": "frame-1"},
    ]

    result = await create_registry_driven_manual_plan(payload)

    assert result.planner_output["block_count"] == 2
    assert len(result.planner_output["blocks"]) == 2
    assert result.planner_output["blocks"][1]["depends_on_block_index"] == 1


@pytest.mark.asyncio
async def test_ingredients_24s_with_subject_scene_style_creates_three_blocks():
    payload = _base_manual_payload()
    payload["destination_mode"] = "INGREDIENTS"
    payload["target_duration_seconds"] = 24
    payload["extension_strategy"] = "EXTEND_CONTINUITY"
    payload["asset_bindings"] = [
        {"asset_role": "SUBJECT_CHARACTER", "asset_source": "UPLOADED_IMAGE", "asset_id": "subject-1"},
        {"asset_role": "SCENE", "asset_source": "UPLOADED_IMAGE", "asset_id": "scene-1"},
        {"asset_role": "STYLE", "asset_source": "UPLOADED_IMAGE", "asset_id": "style-1"},
    ]

    result = await create_registry_driven_manual_plan(payload)

    assert result.planner_output["block_count"] == 3
    assert len(result.planner_output["blocks"]) == 3


@pytest.mark.asyncio
async def test_image_mode_creates_non_continuation_image_planning():
    payload = _base_manual_payload()
    payload["destination_mode"] = "IMAGE"
    payload["output_type"] = "IMAGE_PROMPT"
    payload["target_duration_seconds"] = 32
    payload["extension_strategy"] = "EXTEND_CONTINUITY"

    result = await create_registry_driven_manual_plan(payload)

    assert result.planner_output["block_count"] == 1
    assert len(result.planner_output["blocks"]) == 1
    assert result.planner_output["blocks"][0]["flow_action"] == "INITIAL_GENERATE"


@pytest.mark.asyncio
async def test_missing_start_frame_for_frames_fails_via_round_1_planner():
    payload = _base_manual_payload()
    payload["destination_mode"] = "FRAMES"
    payload["target_duration_seconds"] = 16
    payload["extension_strategy"] = "EXTEND_CONTINUITY"

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "FAIL"
    assert "MISSING_REQUIRED_ASSET_ROLE:START_FRAME" in result.errors


@pytest.mark.asyncio
async def test_attempt_to_canonicalize_preview_only_value_returns_fail():
    payload = _base_manual_payload()
    payload["mark_preview_only_as_canonical"] = True

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "FAIL"
    assert "PREVIEW_ONLY_VALUE_CANNOT_BE_MARKED_CANONICAL" in result.errors


@pytest.mark.asyncio
async def test_attempted_dom_flow_and_batch_execution_return_fail():
    dom_payload = _base_manual_payload()
    dom_payload["execute_dom"] = True
    flow_payload = _base_manual_payload()
    flow_payload["execute_flow"] = True
    batch_payload = _base_manual_payload()
    batch_payload["batch_execution"] = True

    dom_result = await create_registry_driven_manual_plan(dom_payload)
    flow_result = await create_registry_driven_manual_plan(flow_payload)
    batch_result = await create_registry_driven_manual_plan(batch_payload)

    assert "DOM_EXECUTION_NOT_ALLOWED_IN_ROUND_3" in dom_result.errors
    assert "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_3" in flow_result.errors
    assert "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_3" in batch_result.errors


@pytest.mark.asyncio
async def test_attempted_canonical_registry_write_returns_fail():
    payload = _base_manual_payload()
    payload["canonical_registry_write"] = True

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "FAIL"
    assert "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_3" in result.errors


@pytest.mark.asyncio
async def test_attempt_to_invent_product_dimensions_or_claims_returns_fail():
    dimension_payload = _base_manual_payload()
    dimension_payload["invent_product_dimensions"] = True
    claim_payload = _base_manual_payload()
    claim_payload["invent_product_claims"] = True

    dimension_result = await create_registry_driven_manual_plan(dimension_payload)
    claim_result = await create_registry_driven_manual_plan(claim_payload)

    assert dimension_result.planning_status == "FAIL"
    assert "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED" in dimension_result.errors
    assert claim_result.planning_status == "FAIL"
    assert "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED" in claim_result.errors


@pytest.mark.asyncio
async def test_no_flow_extension_batch_dom_or_product_driven_service_imported_or_called():
    result = await create_registry_driven_manual_plan(_base_manual_payload())

    source = inspect.getsource(registry_driven_manual_planner)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "content-flow-dom",
        "simulateFileUpload",
        "product_driven_auto_planner",
        "create_product_driven_auto_plan",
    ]

    assert result.provenance["uses_flow_execution"] is False
    assert result.provenance["uses_extension_runtime"] is False
    assert result.provenance["uses_batch_execution"] is False
    assert result.provenance["uses_product_driven_auto_service"] is False
    for token in banned_tokens:
        assert token not in source


@pytest.mark.asyncio
async def test_invalid_destination_mode_returns_fail():
    payload = _base_manual_payload()
    payload["destination_mode"] = "BAD_MODE"

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "FAIL"
    assert "UNKNOWN_DESTINATION_MODE:BAD_MODE" in result.errors


@pytest.mark.asyncio
async def test_invalid_output_type_returns_fail():
    payload = _base_manual_payload()
    payload["output_type"] = "BAD_OUTPUT"

    result = await create_registry_driven_manual_plan(payload)

    assert result.planning_status == "FAIL"
    assert "UNKNOWN_OUTPUT_TYPE:BAD_OUTPUT" in result.errors


@pytest.mark.asyncio
async def test_attempt_to_mark_external_registry_truth_or_media_upload_as_verified_returns_fail():
    registry_payload = _base_manual_payload()
    registry_payload["mark_external_registry_verified"] = True
    media_payload = _base_manual_payload()
    media_payload["product_media_upload_verified"] = True

    registry_result = await create_registry_driven_manual_plan(registry_payload)
    media_result = await create_registry_driven_manual_plan(media_payload)

    assert registry_result.planning_status == "FAIL"
    assert "EXTERNAL_OPERATOR_PACK_TRUTH_CANNOT_BE_MARKED_LOCAL_VERIFIED" in registry_result.errors
    assert media_result.planning_status == "FAIL"
    assert "PRODUCT_MEDIA_UPLOAD_VERIFICATION_NOT_PROVEN" in media_result.errors
