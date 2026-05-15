import inspect

import pytest

from agent.services.product_asset_generator_service import (
    generate_product_asset_preview,
)


@pytest.fixture(autouse=True)
def fake_registry_hints(monkeypatch):
    class FakeRegistryHint:
        def __init__(self, asset_type: str, source_status: str):
            self.asset_type = asset_type
            self.source_status = source_status
            self.warnings = []
            self.provenance = {"asset_type": asset_type}

    async def fake_list_assets_by_type(asset_type: str):
        source_status = {
            "WARDROBE": "INPUT_SLOT_ONLY",
            "HEADWEAR": "INPUT_SLOT_ONLY",
            "CAMERA_STYLE": "DERIVED_FROM_PRODUCT_DATA",
            "CAMERA_BEHAVIOR": "DERIVED_FROM_PRODUCT_DATA",
            "SCENE_CONTEXT": "DERIVED_FROM_PRODUCT_DATA",
            "STYLE_REFERENCE": "DERIVED_FROM_PRODUCT_DATA",
            "PRODUCT_REFERENCE": "DERIVED_FROM_PRODUCT_DATA",
            "LANGUAGE": "INPUT_SLOT_ONLY",
            "PLATFORM": "INPUT_SLOT_ONLY",
        }[asset_type]
        return FakeRegistryHint(asset_type, source_status)

    monkeypatch.setattr(
        "agent.services.product_asset_generator_service.list_assets_by_type",
        fake_list_assets_by_type,
    )


def _product_row(**overrides):
    payload = {
        "id": "prod-001",
        "source": "FASTMOSS",
        "raw_product_title": "Atlas Bottle Original",
        "product_display_name": "Atlas Bottle",
        "product_short_name": "Atlas",
        "category": "Beauty",
        "subcategory": "Skincare",
        "type": "Bottle",
        "product_type": "Serum",
        "claim_risk_level": "LOW",
        "scene_context": "Premium vanity table.",
        "camera_style": "Medium shot.",
        "camera_behavior": "Slow push-in.",
        "product_scale": "Handheld bottle.",
        "recommended_grip": "Pinch grip at the bottle shoulder.",
        "hand_object_interaction": "Keep fingers clear of the product label.",
        "material_behavior": "Glossy reflective surface.",
        "surface_behavior": "Stable upright placement.",
        "handling_notes": "Avoid covering the front label.",
        "camera_handling_notes": "Keep the hero label square to camera.",
        "image_url": "https://example.com/atlas-bottle.png",
        "section_4_hint": "Hero reveal with clean product framing.",
        "section_9_overlay_hint": "Minimal lower-third.",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_product_id_path_returns_preview_only_suggestions(monkeypatch):
    async def fake_get_product(product_id):
        assert product_id == "prod-001"
        return _product_row()

    monkeypatch.setattr(
        "agent.services.product_asset_generator_service.crud.get_product",
        fake_get_product,
    )

    result = await generate_product_asset_preview(
        {
            "product_id": "prod-001",
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": True,
        }
    )

    assert result.preview_status == "WARN"
    assert result.product_context["product_id"] == "prod-001"
    assert result.execution_allowed is False
    assert result.image_generation_allowed is False
    assert result.flow_execution_allowed is False
    assert result.batch_execution_allowed is False
    assert result.dry_run_only is True


@pytest.mark.asyncio
async def test_product_payload_path_returns_preview_only_suggestions():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(id="inline-prod"),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": True,
        }
    )

    assert result.product_context["product_id"] == "inline-prod"
    assert result.preview_status == "WARN"


@pytest.mark.asyncio
async def test_character_concept_returns_character_card():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "gender": "female",
            "ethnicity": "Malay",
            "age_range": "25-35",
            "dry_run_only": True,
        }
    )

    suggestion = result.prompt_suggestions[0]
    assert suggestion["suggestion_type"] == "character_concept_card"
    assert "female" in suggestion["character_description"]
    assert "CHARACTER_ATTRIBUTES_USER_SUPPLIED_OR_DERIVED_NOT_CANONICAL" in result.warnings


@pytest.mark.asyncio
async def test_character_holding_product_image_prompt_returns_handling_notes():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
            "include_product_in_hand": True,
            "dry_run_only": True,
        }
    )

    suggestion = result.prompt_suggestions[0]
    assert suggestion["suggestion_type"] == "image_prompt"
    assert "holding Atlas Bottle" in suggestion["image_prompt_text"]
    assert result.handling_notes
    assert result.handling_notes[0].startswith("Recommended grip:")


@pytest.mark.asyncio
async def test_product_lifestyle_image_prompt_returns_scene_camera_and_placement_guidance():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "dry_run_only": True,
        }
    )

    suggestion = result.prompt_suggestions[0]
    assert suggestion["suggestion_type"] == "image_prompt"
    assert suggestion["scene_prompt"] == "Premium vanity table."
    assert suggestion["product_scale_prompt"]
    assert result.scene_notes
    assert result.camera_notes


@pytest.mark.asyncio
async def test_ingredients_bundle_returns_subject_product_scene_and_style_bundle_plan():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "INGREDIENTS_ASSET_BUNDLE",
            "dry_run_only": True,
        }
    )

    suggestion = result.prompt_suggestions[0]
    assert suggestion["suggestion_type"] == "ingredients_asset_bundle"
    assert suggestion["subject_character_asset"] == "Atlas Bottle presenter concept"
    assert suggestion["product_reference_asset"] == "Atlas Bottle reference"


@pytest.mark.asyncio
async def test_missing_product_image_emits_warning():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(image_url=None, local_image_path=None, media_id=None),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert "PRODUCT_IMAGE_MISSING" in result.warnings
    assert any(item["asset_role"] == "PRODUCT_IMAGE" for item in result.missing_assets)


@pytest.mark.asyncio
async def test_unverified_dimensions_emit_warning():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(product_scale=None),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert "PRODUCT_DIMENSIONS_NOT_REPO_VERIFIED" in result.warnings
    assert result.truth_status["product_dimensions"] == "NOT_VERIFIED"


@pytest.mark.asyncio
async def test_preview_result_includes_scale_truth_and_camera_lock_fields():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "target_destination_mode": "TEXT_TO_VIDEO",
            "dry_run_only": True,
        }
    )

    assert result.product_context["product_scale_prompt"]
    assert result.product_context["scale_truth_status"] == "DERIVED_RELATIVE_SCALE"
    assert result.product_context["ugc_camera_lock_prompt"]
    assert result.product_context["cinematic_camera_prompt"]
    assert result.product_context["camera_capture_mode"] == "UGC_IPHONE_RAW"


@pytest.mark.asyncio
async def test_text_to_video_readiness_stays_needs_review_when_scale_is_missing():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(
                category="General Goods",
                subcategory="Unknown",
                product_scale=None,
                type=None,
                product_type=None,
                product_type_id=None,
                recommended_grip=None,
                hand_object_interaction=None,
                section_5_product_physics_prompt=None,
                raw_product_title="Mystery artisanal item",
                product_display_name="Mystery artisanal item",
                product_short_name="Mystery artisanal item",
            ),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "target_destination_mode": "TEXT_TO_VIDEO",
            "dry_run_only": True,
        }
    )

    assert result.truth_status["scale_truth_status"] == "SCALE_NOT_FOUND"
    assert result.truth_status["text_to_video_readiness_status"] == "NEEDS_REVIEW"
    assert "PRODUCT_SCALE_PROMPT_MISSING" in result.warnings


@pytest.mark.asyncio
async def test_truth_and_preview_warnings_are_split():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(
                category="Home Supplies",
                subcategory="Home Care Supplies",
                type="Household Cleaners",
                product_type_id="GENERIC_PRODUCT",
                mapping_review_status="BLOCKED",
                raw_product_title="5 LITER/5 KG isi ulang- Sabun Dobi Malaya Liquid detergen",
                product_display_name="Sabun Dobi Malaya Liquid",
                product_short_name="Sabun Dobi Malaya Liquid",
            ),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "target_destination_mode": "TEXT_TO_VIDEO",
            "dry_run_only": True,
        }
    )

    assert "PRODUCT_MAPPING_REVIEW_BLOCKED" in result.truth_warnings
    assert "PREVIEW_ONLY_NOT_GENERATED_ASSET" in result.preview_warnings
    assert "WARDROBE_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED" in result.preview_warnings
    assert result.truth_status["product_mapping_status"] == "NEEDS_REVIEW"
    assert result.truth_status["mapping_review_status"] == "BLOCKED"
    assert result.truth_status["bosmax_product_family"] == "LAUNDRY_DETERGENT_LIQUID_REFILL"


@pytest.mark.asyncio
async def test_claim_gated_detergent_preview_stays_direct_and_needs_review_without_stealth_metaphor():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(
                raw_product_title="Sabun Dobi Liquid Antibakteria Refill 5KG",
                product_display_name="Sabun Dobi Liquid Antibakteria",
                product_short_name="Sabun Dobi Liquid",
                category="Home Supplies",
                subcategory="Home Care Supplies",
                type="Household Cleaners",
                product_type_id="HOUSEHOLD_LAUNDRY_DETERGENT",
                mapping_review_status="AUTO_MAPPED",
                claim_risk_level="LOW",
            ),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "target_destination_mode": "TEXT_TO_VIDEO",
            "language": "Malay",
            "dry_run_only": True,
        }
    )

    assert result.product_context["copy_route"] == "DIRECT"
    assert result.product_context["claim_gate"] == "CLAIM_REVIEW_REQUIRED"
    assert result.truth_status["text_to_video_readiness_status"] == "NEEDS_REVIEW"
    assert result.truth_status["physical_state"] == "liquid"
    assert "STEALTH" not in str(result.product_context.get("dialogue_body", "")).upper()
    assert "pour" in str(result.product_context["product_scale_prompt"]).lower() or "refill" in str(result.product_context["product_scale_prompt"]).lower()


@pytest.mark.asyncio
async def test_preview_includes_generated_copy_signals_for_safe_direct_product():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert result.product_context["hook"]
    assert result.product_context["usp_1"]
    assert result.product_context["cta"]


@pytest.mark.asyncio
async def test_product_claims_not_hard_enforced_emit_warning():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(claim_risk_level="HIGH"),
            "target_asset_intent": "STYLE_REFERENCE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert "PRODUCT_CLAIMS_NOT_HARD_ENFORCED" in result.warnings
    assert result.truth_status["product_claims"] == "NOT_HARD_ENFORCED"


@pytest.mark.asyncio
async def test_dry_run_only_false_fails():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": False,
        }
    )

    assert result.preview_status == "FAIL"
    assert result.errors == ["DRY_RUN_ONLY_FALSE_NOT_ALLOWED"]


@pytest.mark.asyncio
async def test_image_generation_attempt_fails():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": True,
            "image_generation_requested": True,
        }
    )

    assert result.preview_status == "FAIL"
    assert result.errors == ["IMAGE_GENERATION_NOT_ALLOWED_IN_ROUND_10"]


@pytest.mark.asyncio
async def test_flow_extension_batch_queue_persistence_and_canonical_write_attempts_fail():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": True,
            "execute_flow": True,
            "chrome_extension_execution": True,
            "batch_execution": True,
            "create_queue_job": True,
            "persist_output": True,
            "canonical_registry_write": True,
        }
    )

    assert result.preview_status == "FAIL"
    assert result.errors == [
        "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_10",
        "CHROME_EXTENSION_EXECUTION_NOT_ALLOWED_IN_ROUND_10",
        "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_10",
        "QUEUE_CREATION_NOT_ALLOWED_IN_ROUND_10",
        "PERSISTENCE_WRITE_NOT_ALLOWED_IN_ROUND_10",
        "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_10",
    ]


@pytest.mark.asyncio
async def test_dimension_and_claim_invention_attempts_fail():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "CHARACTER_CONCEPT",
            "dry_run_only": True,
            "invent_product_dimensions": True,
            "invent_product_claims": True,
        }
    )

    assert result.preview_status == "FAIL"
    assert result.errors == [
        "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED",
        "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED",
    ]


@pytest.mark.asyncio
async def test_derived_suggestions_are_not_marked_canonical_or_repo_verified():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "SCENE_REFERENCE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert all(item["is_canonical"] is False for item in result.derived_asset_suggestions)
    assert all(item["verified_level"] == "DERIVED_NOT_CANONICAL" for item in result.derived_asset_suggestions)


@pytest.mark.asyncio
async def test_provenance_is_preserved():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "STYLE_REFERENCE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert result.provenance["scope"] == "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY"
    assert result.provenance["preview_only"] is True


@pytest.mark.asyncio
async def test_execution_flags_are_always_false():
    result = await generate_product_asset_preview(
        {
            "product_payload": _product_row(),
            "target_asset_intent": "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
            "dry_run_only": True,
        }
    )

    assert result.execution_allowed is False
    assert result.image_generation_allowed is False
    assert result.flow_execution_allowed is False
    assert result.batch_execution_allowed is False


def test_service_does_not_import_or_call_flow_extension_batch_queue_persistence_or_write_helpers():
    from agent.services import product_asset_generator_service

    source = inspect.getsource(product_asset_generator_service)
    banned_tokens = [
        "upload_product_to_flow",
        "resolve_product_assets",
        "flow_client",
        "batch_executor",
        "chrome.runtime",
        "queue_request",
        "create_request(",
        "update_product(",
        "create_product(",
        "delete_product(",
        "create_character(",
        "dashboard.",
    ]

    for token in banned_tokens:
        assert token not in source
