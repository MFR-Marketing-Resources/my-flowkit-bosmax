from __future__ import annotations

import pytest

from agent.authority.catalog_product_type_truth import (
    CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS,
    catalog_product_type_truth_provenance,
    iter_catalog_product_type_truth_registry_entries,
    resolve_catalog_product_type_truth,
)
from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_KEYS,
)
from agent.services.product_strategy_scouting_service import (
    product_strategy_type_registry_seed_entries,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES


@pytest.mark.parametrize(
    ("product", "expected"),
    (
        (
            {
                "type": "Pants",
                "category": "Baby Care",
                "subcategory": "Diaper",
            },
            ("baby_care", "baby_diaper", "BABY_DIAPER"),
        ),
        (
            {
                "type": "Pants",
                "category": "Fashion",
                "subcategory": "Bottoms",
            },
            ("fashion_apparel", "bottom_apparel", "BOTTOM_APPAREL"),
        ),
        (
            {"type": "Baby Wipes", "category": "Beauty"},
            ("baby_care", "baby_wipes", "BABY_WIPES"),
        ),
        (
            {"type": "Household Cleaners", "category": "Household"},
            (
                "household_cleaning",
                "household_cleaner",
                "HOUSEHOLD_CLEANER",
            ),
        ),
        (
            {"type": "Vacuum Sealers", "category": "Home Appliances"},
            ("home_equipment", "vacuum_sealer", "VACUUM_SEALER"),
        ),
    ),
)
def test_exact_source_authority_resolves_ambiguous_catalog_types(
    product,
    expected,
) -> None:
    mapping = resolve_catalog_product_type_truth(product)

    assert mapping is not None
    assert (
        mapping.cluster,
        mapping.product_type_group,
        mapping.specific_scene_strategy_id,
    ) == expected


@pytest.mark.parametrize(
    ("product_type_code", "source_type", "expected"),
    (
        (
            "artificial_flowers",
            "Artificial Flower Bouquets",
            ("home_decor", "artificial_plant", "HOME_DECOR"),
        ),
        (
            "crossbody_bag",
            "Crossbody Bags",
            ("fashion_accessory", "bag", "FASHION_ACCESSORY"),
        ),
        (
            "bidet_spray_set",
            "Bidet Spray Sets",
            ("home_improvement", "bathroom_fixture", "WALL_COVERING"),
        ),
        (
            "hydrocolloid_acne_patch",
            "Acne Patches",
            ("beauty_skincare", "medicated_patch", "FACE_MASK"),
        ),
        (
            "3d_sticker_book",
            "3D Scene Sticker Books",
            ("stationery", "sticker", "STATIONERY"),
        ),
    ),
)
def test_copywriting_hub_product_type_code_bridges_to_existing_p4_lane(
    product_type_code,
    source_type,
    expected,
) -> None:
    mapping = resolve_catalog_product_type_truth(
        {
            "copywriting_product_type_code": product_type_code,
            "category": "Home & Living"
            if product_type_code in {"artificial_flowers", "bidet_spray_set"}
            else "Fashion"
            if product_type_code == "crossbody_bag"
            else "Beauty & Personal Care"
            if product_type_code == "hydrocolloid_acne_patch"
            else "Toys & Games",
            "subcategory": "Home Decor"
            if product_type_code == "artificial_flowers"
            else "Bathroom Fixtures"
            if product_type_code == "bidet_spray_set"
            else "Bags"
            if product_type_code == "crossbody_bag"
            else "Skincare"
            if product_type_code == "hydrocolloid_acne_patch"
            else "Creative Play",
            "type": source_type,
        }
    )

    assert mapping is not None
    assert (
        mapping.cluster,
        mapping.product_type_group,
        mapping.specific_scene_strategy_id,
    ) == expected
    assert expected in PRODUCT_TYPE_COPY_STRATEGY_KEYS


def test_copywriting_hub_code_fails_closed_when_source_fields_disagree() -> None:
    assert resolve_catalog_product_type_truth(
        {
            "copywriting_product_type_code": "artificial_flowers",
            "category": "Fashion",
            "subcategory": "Bags",
            "type": "Crossbody Bags",
        }
    ) is None


def test_exact_copywriting_hub_code_precedes_historical_product_id_override() -> None:
    product = {
        # This ID has a historical Books & Media override; the current
        # workbook selection must win when its full source triple agrees.
        "id": "867bd162-ef79-46ef-a7aa-97fb2387c058",
        "copywriting_product_type_code": "3d_sticker_book",
        "category": "Toys & Games",
        "subcategory": "Creative Play",
        "type": "3D Scene Sticker Books",
    }
    mapping = resolve_catalog_product_type_truth(product)

    assert mapping is not None
    assert (
        mapping.cluster,
        mapping.product_type_group,
        mapping.specific_scene_strategy_id,
    ) == ("stationery", "sticker", "STATIONERY")
    assert catalog_product_type_truth_provenance(product) == "SOURCE_TAXONOMY"


def test_every_activated_product_truth_type_has_specific_scene_and_p4() -> None:
    registry_entries = iter_catalog_product_type_truth_registry_entries()
    seeded = {
        (str(entry["cluster"]), str(entry["product_type_group"])): entry
        for entry in product_strategy_type_registry_seed_entries()
    }

    assert registry_entries
    for mapping in registry_entries:
        scene_strategy_id = mapping.specific_scene_strategy_id
        assert scene_strategy_id is not None
        assert scene_strategy_id in SCENE_STRATEGIES
        assert (
            mapping.cluster,
            mapping.product_type_group,
            scene_strategy_id,
        ) in PRODUCT_TYPE_COPY_STRATEGY_KEYS
        seed = seeded[(mapping.cluster, mapping.product_type_group)]
        assert seed["registry_status"] == "ACTIVE"
        assert seed["scene_coverage_status"] == "COVERED"


def test_unknown_and_broad_beauty_have_no_product_truth_or_p4_strategy() -> None:
    assert resolve_catalog_product_type_truth(
        {
            "type": None,
            "category": "Beauty",
            "raw_product_title": "Opaque Beauty Listing",
        }
    ) is None
    assert not any(
        mapping.product_type_group
        in {"unknown_product_type", "beauty_personal_care_other"}
        for mapping in CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS
    )
    assert not any(
        key[1] in {"unknown_product_type", "beauty_personal_care_other"}
        for key in PRODUCT_TYPE_COPY_STRATEGY_KEYS
    )


def test_car_cover_override_uses_exact_accessory_authority() -> None:
    mapping = resolve_catalog_product_type_truth(
        {
            "id": "0ff37782-a1d7-49db-9d33-575f2e7ae351",
            "raw_product_title": "3 Layers PVC + Cotton Universal Car Cover",
            "category": None,
            "subcategory": None,
            "type": None,
        }
    )

    assert mapping is not None
    assert (
        mapping.cluster,
        mapping.product_type_group,
        mapping.specific_scene_strategy_id,
    ) == ("automotive_accessory", "car_cover", "AUTOMOTIVE_ACCESSORY")
    assert (
        mapping.cluster,
        mapping.product_type_group,
        mapping.specific_scene_strategy_id,
    ) in PRODUCT_TYPE_COPY_STRATEGY_KEYS
