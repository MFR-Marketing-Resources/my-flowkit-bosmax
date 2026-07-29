from __future__ import annotations

import pytest

from agent.authority.catalog_product_type_truth import (
    CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS,
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
