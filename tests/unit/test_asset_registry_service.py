import inspect

import pytest

from agent.services.asset_registry_service import (
    SUPPORTED_ASSET_TYPES,
    compatibility_check,
    get_asset_by_id,
    get_asset_catalog,
    list_assets_by_type,
    resolve_asset_selection,
)


@pytest.mark.asyncio
async def test_catalog_returns_supported_asset_types(monkeypatch):
    async def fake_list_characters():
        return []

    async def fake_list_products(*args, **kwargs):
        return []

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_characters", fake_list_characters)
    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    result = await get_asset_catalog()

    assert [entry.asset_type for entry in result.catalog] == SUPPORTED_ASSET_TYPES
    assert result.provenance["scope"] == "ROUND_8_ASSET_REGISTRY_API_ONLY"


@pytest.mark.asyncio
async def test_asset_type_list_returns_dropdown_ready_response_shape():
    result = await list_assets_by_type("COPYWRITING_FORMULA")

    assert result.asset_type == "COPYWRITING_FORMULA"
    assert result.source_status == "REPO_VERIFIED"
    assert result.options
    option = result.options[0]
    assert option.asset_id
    assert option.asset_type == "COPYWRITING_FORMULA"
    assert option.label
    assert isinstance(option.metadata, dict)
    assert isinstance(option.compatibility_tags, list)
    assert option.source_file
    assert option.source_path
    assert option.verified_level == "REPO_RULE_SURFACE"


@pytest.mark.asyncio
async def test_missing_repo_proven_dataset_returns_empty_not_verified_with_warning(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return []

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    result = await list_assets_by_type("PRODUCT_REFERENCE")

    assert result.asset_type == "PRODUCT_REFERENCE"
    assert result.source_status == "EMPTY_NOT_VERIFIED"
    assert result.options == []
    assert "NO_REPO_PRODUCT_ROWS_FOUND" in result.warnings
    assert result.empty_reason


@pytest.mark.asyncio
async def test_character_asset_type_exists_as_category_even_without_rows(monkeypatch):
    async def fake_list_characters():
        return []

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_characters", fake_list_characters)

    result = await get_asset_catalog()
    character_entry = next(entry for entry in result.catalog if entry.asset_type == "CHARACTER")

    assert character_entry.asset_type == "CHARACTER"
    assert character_entry.source_status == "EMPTY_NOT_VERIFIED"
    assert character_entry.item_count == 0
    assert character_entry.empty_reason


@pytest.mark.asyncio
async def test_camera_style_and_camera_behavior_are_flagged_conservatively_when_no_repo_values_exist(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return []

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    camera_style = await list_assets_by_type("CAMERA_STYLE")
    camera_behavior = await list_assets_by_type("CAMERA_BEHAVIOR")

    assert camera_style.source_status == "INPUT_SLOT_ONLY"
    assert camera_style.options == []
    assert "INPUT_SLOT_ONLY_NO_REPO_DERIVED_VALUES_FOUND" in camera_style.warnings
    assert camera_behavior.source_status == "INPUT_SLOT_ONLY"
    assert camera_behavior.options == []
    assert "INPUT_SLOT_ONLY_NO_REPO_DERIVED_VALUES_FOUND" in camera_behavior.warnings


@pytest.mark.asyncio
async def test_wardrobe_and_headwear_are_not_falsely_marked_repo_verified():
    wardrobe = await list_assets_by_type("WARDROBE")
    headwear = await list_assets_by_type("HEADWEAR")

    assert wardrobe.source_status == "INPUT_SLOT_ONLY"
    assert headwear.source_status == "INPUT_SLOT_ONLY"
    assert wardrobe.options == []
    assert headwear.options == []


@pytest.mark.asyncio
async def test_formula_scene_context_product_handling_and_product_physics_use_only_repo_proven_or_derived_surfaces(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return [
            {
                "id": "prod-001",
                "scene_context": "Premium vanity table.",
                "camera_style": "Medium shot.",
                "camera_behavior": "Slow push-in.",
                "section_9_overlay_hint": "Minimal lower-third.",
                "product_display_name": "Atlas Bottle",
                "product_short_name": "Atlas",
                "raw_product_title": "Atlas Bottle",
                "category": "Beauty",
                "type": "Bottle",
            }
        ]

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    formula = await list_assets_by_type("COPYWRITING_FORMULA")
    scene_context = await list_assets_by_type("SCENE_CONTEXT")
    handling = await list_assets_by_type("PRODUCT_HANDLING")
    physics = await list_assets_by_type("PRODUCT_PHYSICS")

    assert formula.source_status == "REPO_VERIFIED"
    assert scene_context.source_status == "DERIVED_FROM_PRODUCT_DATA"
    assert scene_context.options[0].source_status == "DERIVED_FROM_PRODUCT_DATA"
    assert handling.source_status == "REPO_VERIFIED"
    assert physics.source_status == "REPO_VERIFIED"


@pytest.mark.asyncio
async def test_product_reference_exposes_product_derived_metadata_without_claiming_canonical_registry_truth(monkeypatch):
    async def fake_list_products(*args, **kwargs):
        return [
            {
                "id": "prod-001",
                "product_display_name": "Atlas Bottle",
                "product_short_name": "Atlas",
                "raw_product_title": "Atlas Bottle Original",
                "category": "Beauty",
                "subcategory": "Skincare",
                "type": "Bottle",
                "product_type": "Serum",
                "claim_risk_level": "LOW",
                "scene_context": "Premium vanity table.",
                "camera_style": "Medium shot.",
                "camera_behavior": "Slow push-in.",
            }
        ]

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    result = await list_assets_by_type("PRODUCT_REFERENCE")

    assert result.source_status == "DERIVED_FROM_PRODUCT_DATA"
    assert result.options[0].source_status == "DERIVED_FROM_PRODUCT_DATA"
    assert result.options[0].is_canonical is False
    assert result.options[0].verified_level == "DERIVED_NOT_CANONICAL"


@pytest.mark.asyncio
async def test_resolve_selection_returns_warn_for_input_slot_only_selection():
    result = await resolve_asset_selection(
        {
            "selected_assets": {
                "LANGUAGE": "language:Malay",
            }
        }
    )

    assert result.selection_status == "WARN"
    assert "ASSET_SELECTION_NOT_REPO_VERIFIED:language:Malay" in result.warnings
    assert "FULL_TUPLE_LEGALITY_NOT_PROVEN" in result.warnings


@pytest.mark.asyncio
async def test_resolve_selection_fails_on_canonical_registry_write_attempt():
    result = await resolve_asset_selection(
        {
            "selected_assets": {"LANGUAGE": "language:Malay"},
            "canonical_registry_write": True,
        }
    )

    assert result.selection_status == "FAIL"
    assert result.errors == ["CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_8"]


@pytest.mark.asyncio
async def test_resolve_selection_fails_when_external_truth_is_marked_verified():
    result = await resolve_asset_selection(
        {
            "selected_assets": {"LANGUAGE": "language:Malay"},
            "mark_external_asset_verified": True,
        }
    )

    assert result.selection_status == "FAIL"
    assert result.errors == ["UNVERIFIED_ASSET_TRUTH_CANNOT_BE_MARKED_VERIFIED"]


@pytest.mark.asyncio
async def test_compatibility_check_returns_not_verified_when_tuple_legality_matrix_is_not_proven():
    result = await compatibility_check(
        {
            "selected_assets": {
                "LANGUAGE": "language:Malay",
                "PLATFORM": "platform:TikTok",
            }
        }
    )

    assert result.compatibility_status == "NOT_VERIFIED"
    assert "FULL_TUPLE_LEGALITY_NOT_PROVEN" in result.warnings
    assert "CANONICAL_VS_PREVIEW_ISOLATION_NOT_PROVEN" in result.warnings


@pytest.mark.asyncio
async def test_compatibility_check_does_not_invent_compatibility_rules():
    result = await compatibility_check(
        {
            "selected_assets": {
                "LANGUAGE": "language:English",
                "ENGINE_PROFILE": "engine:VEO_3_1",
                "PLATFORM": "platform:TikTok",
            }
        }
    )

    assert result.compatibility_status == "NOT_VERIFIED"
    assert "FULL_TUPLE_LEGALITY_NOT_PROVEN" in result.warnings


@pytest.mark.asyncio
async def test_get_asset_by_id_returns_detail_for_repo_rule_surface():
    formulas = await list_assets_by_type("COPYWRITING_FORMULA")
    detail = await get_asset_by_id(formulas.options[0].asset_id)

    assert detail is not None
    assert detail.asset.asset_type == "COPYWRITING_FORMULA"
    assert detail.asset.source_status == "REPO_VERIFIED"


def test_service_does_not_import_or_call_db_writes_flow_dom_batch_extension_ui_or_runtime_modules():
    from agent.services import asset_registry_service

    source = inspect.getsource(asset_registry_service)
    banned_tokens = [
        "flow_client",
        "batch_executor",
        "chrome.runtime",
        "simulateFileUpload",
        "agent.api.operator",
        "queue_request",
        "create_request(",
        "update_product(",
        "create_product(",
        "runtime_orchestrator",
        "dashboard.",
    ]

    for token in banned_tokens:
        assert token not in source


def test_asset_registry_router_is_registered_once_in_main():
    from agent import main

    source = inspect.getsource(main)
    assert source.count("asset_registry_router") == 2
    assert 'app.include_router(asset_registry_router, prefix="/api")' in source
