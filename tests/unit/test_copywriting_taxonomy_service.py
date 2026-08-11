from __future__ import annotations

import pytest

from agent.services.copywriting_taxonomy_service import (
    CopywritingTaxonomySelectionError,
    get_copywriting_taxonomy_tree,
    load_authority_records,
    resolve_product_taxonomy_record,
    seed_copywriting_taxonomy_registry,
    validate_taxonomy_selection,
)


@pytest.mark.asyncio
async def test_authority_seed_is_313_rows_file_wins_and_idempotent():
    records = load_authority_records()
    assert len(records) == 313
    assert len({record["product_type_code"] for record in records}) == 313
    assert any(
        record["source_category"] == "Health"
        and record["category"] == "Health & Personal Care"
        for record in records
    )
    assert all(record["source_workbook"].endswith(".xlsx") for record in records)
    assert all(record["source_sheet"] == "Database" for record in records)

    first = await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    second = await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )

    assert first["seed_count"] == 313
    assert first["planned_insert_count"] == 313
    assert first["mutation_performed"] is True
    assert second["planned_insert_count"] == 0
    assert second["planned_update_count"] == 0
    assert second["unchanged_count"] == 313
    assert second["mutation_performed"] is False


@pytest.mark.asyncio
async def test_tree_shape_is_canonical_and_collision_winner_is_explicit():
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    tree = await get_copywriting_taxonomy_tree()

    assert set(tree) == {
        "categories",
        "subcategoriesByCategory",
        "typesBySubcategory",
        "recordByType",
    }
    assert "Health" not in tree["categories"]
    assert "Health & Personal Care" in tree["categories"]
    assert "Sports & Outdoor" not in tree["categories"]
    assert len(tree["recordByType"]) == 312
    collision = tree["recordByType"][
        "Beauty & Personal Care::Facial Cleansing::Brightening Facial Soap"
    ]
    assert collision["product_type_code"] == "facial_cleansing_soap"
    assert set(collision) >= {
        "copywriting_angle",
        "product_type_code",
        "cluster",
        "display_name",
    }


@pytest.mark.asyncio
async def test_validation_rejects_unknown_or_conflicting_combinations():
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )

    with pytest.raises(CopywritingTaxonomySelectionError) as unknown:
        await validate_taxonomy_selection(
            category="Kitchenware",
            subcategory="Not in SSOT",
            type_name="Invalid",
        )
    assert unknown.value.detail["error_code"] == (
        "COPYWRITING_TAXONOMY_SELECTION_INVALID"
    )

    with pytest.raises(CopywritingTaxonomySelectionError) as conflict:
        await validate_taxonomy_selection(
            category="Toys & Games",
            subcategory="Creative Play",
            type_name="3D Scene Sticker Books",
            product_type_code="acne_treatment_medicine",
        )
    assert conflict.value.detail["reason"] == (
        "PRODUCT_TYPE_CODE_CONFLICTS_WITH_TAXONOMY"
    )


@pytest.mark.asyncio
async def test_legacy_product_resolution_is_needs_reconciliation_with_nearest_match():
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    resolution = await resolve_product_taxonomy_record(
        {
            "id": "legacy-1",
            "product_display_name": "Legacy product",
            "category": "Kitchenware",
            "subcategory": "Kitchen Utensils & Gadgets",
            "type": "Specialty Kitchen Utensils",
            "copywriting_angle": "legacy",
        }
    )
    assert resolution["needs_reconciliation"] is True
    assert resolution["match_status"] == "NEEDS_RECONCILIATION"
    assert resolution["match"] is None
    assert resolution["nearest_match"] is not None
    assert resolution["current"]["category"] == "Kitchenware"
