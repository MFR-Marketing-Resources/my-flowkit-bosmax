from __future__ import annotations

from agent.services.product_strategy_scouting_service import (
    SCOUTING_CLUSTER_ORDER,
    build_product_strategy_scouting_report,
    classify_product_strategy_tag,
    product_strategy_type_registry_seed_entries,
)


def _product(
    product_id: str,
    title: str,
    *,
    category: str,
    product_type: str,
    subcategory: str = "",
    silo: str = "",
) -> dict[str, object]:
    return {
        "id": product_id,
        "raw_product_title": title,
        "product_display_name": title,
        "product_short_name": title,
        "category": category,
        "subcategory": subcategory,
        "type": product_type,
        "product_type": product_type,
        "product_type_id": product_type.upper().replace(" ", "_"),
        "silo": silo,
    }


def _cluster(report: dict[str, object], cluster_name: str) -> dict[str, object]:
    clusters = report["clusters"]
    assert isinstance(clusters, list)
    return next(
        cluster
        for cluster in clusters
        if isinstance(cluster, dict) and cluster["cluster"] == cluster_name
    )


def _groups(cluster: dict[str, object]) -> dict[str, dict[str, object]]:
    product_type_groups = cluster["product_type_groups"]
    assert isinstance(product_type_groups, list)
    return {
        str(group["product_type_group"]): group
        for group in product_type_groups
        if isinstance(group, dict)
    }


def test_beauty_makeup_groups_lip_products_and_separates_mascara() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "lip-1",
                "Velvet Matte Lipstick",
                category="Beauty & Personal Care",
                product_type="Lipstick",
            ),
            _product(
                "lip-2",
                "Water Lip Tint",
                category="Beauty & Personal Care",
                product_type="Lip Tint",
            ),
            _product(
                "mascara-1",
                "Waterproof Mascara",
                category="Beauty & Personal Care",
                product_type="Mascara",
            ),
        ]
    )

    beauty = _cluster(report, "beauty_makeup")
    groups = _groups(beauty)
    assert groups["lipstick_lip_tint"]["product_count"] == 2
    assert groups["lipstick_lip_tint"]["matched_scene_strategy_id"] == "LIP_COLOR"
    assert groups["lipstick_lip_tint"]["coverage_status"] == "COVERED"
    assert groups["mascara"]["product_count"] == 1
    assert groups["mascara"]["matched_scene_strategy_id"] == "BEAUTY_PERSONAL_CARE"
    assert groups["mascara"]["specific_strategy_count"] == 0
    assert groups["mascara"]["coverage_status"] == "PARTIAL"
    assert beauty["next_product_type_group"] == "mascara"


def test_cleanser_and_serum_are_separate_beauty_personal_care_groups() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "cleanser-1",
                "Gentle Facial Cleanser",
                category="Beauty & Personal Care",
                product_type="Cleanser",
            ),
            _product(
                "serum-1",
                "Niacinamide Face Serum",
                category="Beauty & Personal Care",
                product_type="Serum",
            ),
        ]
    )

    groups = _groups(_cluster(report, "beauty_personal_care"))
    assert set(groups) == {"cleanser", "serum"}
    assert groups["cleanser"]["coverage_status"] == "PARTIAL"
    assert groups["serum"]["coverage_status"] == "PARTIAL"


def test_food_cooking_keeps_rempah_sambal_and_sauce_in_clean_type_groups() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "spice-1",
                "Rempah Kari",
                category="Food & Beverage",
                product_type="Rempah",
            ),
            _product(
                "spice-2",
                "Seasoning Powder",
                category="Food & Beverage",
                product_type="Seasoning",
            ),
            _product(
                "sambal-1",
                "Sambal Bilis",
                category="Food & Beverage",
                product_type="Sambal",
            ),
            _product(
                "sauce-1",
                "Tomato Sauce",
                category="Food & Beverage",
                product_type="Sauce",
            ),
            _product(
                "instant-1",
                "Instant Noodle Cup",
                category="Food & Beverage",
                product_type="Instant Food",
            ),
        ]
    )

    groups = _groups(_cluster(report, "food_cooking"))
    assert groups["rempah_seasoning"]["product_count"] == 2
    assert groups["rempah_seasoning"]["matched_scene_strategy_id"] == "SPICE_SEASONING"
    assert groups["sambal"]["matched_scene_strategy_id"] == "PACKAGED_SAUCE_SAMBAL"
    assert groups["sauce"]["matched_scene_strategy_id"] == "PACKAGED_SAUCE_SAMBAL"
    assert all(group["coverage_status"] == "COVERED" for group in groups.values())
    ready_to_eat = _groups(_cluster(report, "food_ready_to_eat"))
    assert ready_to_eat["instant_food"]["matched_scene_strategy_id"] == "PACKAGED_FOOD"


def test_detergent_and_softener_share_laundry_cluster_but_not_type_group() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "detergent-1",
                "Liquid Laundry Detergent",
                category="Household",
                product_type="Detergent",
            ),
            _product(
                "softener-1",
                "Floral Fabric Softener",
                category="Household",
                product_type="Softener",
            ),
        ]
    )

    groups = _groups(_cluster(report, "household_laundry"))
    assert set(groups) == {"detergent", "softener"}
    assert groups["detergent"]["matched_scene_strategy_id"] == "LAUNDRY_DETERGENT"
    assert groups["softener"]["matched_scene_strategy_id"] == "FABRIC_SOFTENER"


def test_vacuum_blender_and_chopper_are_home_equipment_not_cleaning() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "vacuum-1",
                "Cordless Vacuum Cleaner",
                category="Home Appliances",
                product_type="Vacuum",
            ),
            _product(
                "blender-1",
                "Portable Blender",
                category="Home Appliances",
                product_type="Blender",
            ),
            _product(
                "chopper-1",
                "Mini Food Chopper",
                category="Home Appliances",
                product_type="Chopper",
            ),
        ]
    )

    home_equipment = _cluster(report, "home_equipment")
    groups = _groups(home_equipment)
    assert set(groups) == {"vacuum", "blender", "chopper"}
    assert groups["vacuum"]["matched_scene_strategy_id"] == "HOUSEHOLD_CLEANER"
    assert groups["vacuum"]["specific_strategy_count"] == 0
    assert groups["vacuum"]["coverage_status"] == "PARTIAL"
    assert groups["blender"]["matched_scene_strategy_id"] == "ELECTRONICS_SMALL_DEVICE"
    assert groups["chopper"]["matched_scene_strategy_id"] == "PACKAGED_FOOD"
    assert groups["chopper"]["specific_strategy_count"] == 0
    assert groups["chopper"]["coverage_status"] == "PARTIAL"
    assert _cluster(report, "household_cleaning")["product_count"] == 0


def test_sensitive_male_and_female_products_share_fail_closed_cluster() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "male-1",
                "Male Wellness Herbal Oil",
                category="Male Wellness",
                product_type="Male Health",
            ),
            _product(
                "female-1",
                "Female Wellness Herbal Blend",
                category="Female Wellness",
                product_type="Female Health",
            ),
        ]
    )

    groups = _groups(_cluster(report, "sensitive_wellness"))
    assert set(groups) == {"male_wellness", "female_wellness"}
    assert groups["male_wellness"]["matched_scene_strategy_id"] == "SENSITIVE_WELLNESS"
    assert groups["female_wellness"]["matched_scene_strategy_id"] == "SENSITIVE_WELLNESS"
    assert all(group["coverage_status"] == "COVERED" for group in groups.values())


def test_unknown_product_is_generic_and_fallback_only() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "unknown-1",
                "Mystery Item X9",
                category="Miscellaneous",
                product_type="Unknown",
            )
        ]
    )

    groups = _groups(_cluster(report, "generic_unclassified"))
    unknown = groups["unknown_product_type"]
    assert unknown["fallback_count"] == 1
    assert unknown["specific_strategy_count"] == 0
    assert unknown["coverage_status"] == "FALLBACK_ONLY"
    assert unknown["matched_scene_strategy_id"] == "GENERIC_FALLBACK"


def test_report_ranks_cluster_first_and_recommends_exactly_one_next_type() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "lip-1",
                "Velvet Lipstick",
                category="Beauty & Personal Care",
                product_type="Lipstick",
            ),
            _product(
                "mascara-1",
                "Volume Mascara",
                category="Beauty & Personal Care",
                product_type="Mascara",
            ),
            _product(
                "vacuum-1",
                "Robot Vacuum Cleaner",
                category="Home Appliances",
                product_type="Vacuum",
            ),
            _product(
                "sambal-1",
                "Sambal Hijau",
                category="Food & Beverage",
                product_type="Sambal",
            ),
        ]
    )

    assert [cluster["cluster"] for cluster in report["clusters"]] == list(
        SCOUTING_CLUSTER_ORDER
    )
    assert report["recommended_next_work"] == report["ranked_work_queue"][0]
    assert report["recommended_next_work"] == {
        "cluster": "beauty_makeup",
        "product_type_group": "mascara",
        "coverage_status": "PARTIAL",
        "recommended_next_action": (
            "Expand beauty_makeup -> mascara as one scoped strategy; the "
            "current resolver uses BEAUTY_PERSONAL_CARE, but "
            "product-type-specific coverage is 0/1."
        ),
    }
    assert "vacuum" not in report["recommended_next_work"]["recommended_next_action"]
    assert "sambal" not in report["recommended_next_work"]["recommended_next_action"]
    assert all(
        item["recommended_next_action"].count("->") == 1
        for item in report["ranked_work_queue"]
    )


def test_direct_copy_notes_only_come_from_specific_scene_strategy_coverage() -> None:
    report = build_product_strategy_scouting_report(
        [
            _product(
                "lip-1",
                "Velvet Lipstick",
                category="Beauty & Personal Care",
                product_type="Lipstick",
            ),
            _product(
                "mascara-1",
                "Volume Mascara",
                category="Beauty & Personal Care",
                product_type="Mascara",
            ),
        ]
    )

    groups = _groups(_cluster(report, "beauty_makeup"))
    assert "Sekali sapu warna terus naik." in groups["lipstick_lip_tint"][
        "direct_copy_notes"
    ]["hook"]
    assert groups["mascara"]["direct_copy_notes"] == {
        "hook": [],
        "benefit": [],
        "cta": [],
    }


def test_traditional_wellness_seed_rows_are_owner_reviewed_and_manual_only() -> None:
    entries = product_strategy_type_registry_seed_entries()
    by_key = {
        (str(entry["cluster"]), str(entry["product_type_group"])): entry
        for entry in entries
    }

    assert len(by_key) == len(entries)
    assert "traditional_wellness" in SCOUTING_CLUSTER_ORDER
    for key, strategy_id, display_name in (
        (
            ("traditional_wellness", "traditional_herbal_oil"),
            "TRADITIONAL_HERBAL_OIL",
            "Traditional Herbal Oil",
        ),
        (
            ("traditional_wellness", "herbal_roll_on_oil"),
            "HERBAL_ROLL_ON_OIL",
            "Herbal Roll-On Oil",
        ),
    ):
        entry = by_key[key]
        assert entry["display_name"] == display_name
        assert entry["matched_scene_strategy_id"] == strategy_id
        assert entry["scene_coverage_status"] == "COVERED"
        assert entry["registry_status"] == "ACTIVE"
        assert entry["auto_classification_enabled"] is False
        assert entry["reviewer_id"] == "owner:Faris"
        assert "BOSMAX-P5-CANONICAL-CLOSURE" in str(entry["reviewer_note"])


def test_traditional_wellness_rules_do_not_auto_classify_products() -> None:
    tag = classify_product_strategy_tag(
        _product(
            "future-herbal-oil",
            "Traditional Herbal Oil",
            category="Traditional Wellness",
            product_type="Traditional Herbal Oil",
        )
    )

    assert tag["cluster"] == "generic_unclassified"
    assert tag["product_type_group"] == "unknown_product_type"
