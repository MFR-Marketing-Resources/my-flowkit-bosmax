from __future__ import annotations

from agent.services.product_cluster_grouping import crosswalk_domain
from agent.services.product_strategy_scouting_service import (
    SCOUTING_CLUSTER_ORDER,
    _TIKTOK_CATEGORY_FALLBACK,
    _TIKTOK_CATEGORY_FALLBACK_RAW,
    _normalize,
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
    assert groups["mascara"]["matched_scene_strategy_id"] == "MASCARA"
    assert groups["mascara"]["specific_strategy_count"] == 1
    assert groups["mascara"]["coverage_status"] == "COVERED"
    assert beauty["next_product_type_group"] is None


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
    assert groups["cleanser"]["matched_scene_strategy_id"] == "CLEANSER"
    assert groups["cleanser"]["coverage_status"] == "COVERED"
    assert groups["serum"]["matched_scene_strategy_id"] == "SERUM"
    assert groups["serum"]["coverage_status"] == "COVERED"


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
    assert groups["vacuum"]["matched_scene_strategy_id"] == "VACUUM_CLEANER"
    assert groups["vacuum"]["specific_strategy_count"] == 1
    assert groups["vacuum"]["coverage_status"] == "COVERED"
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


def test_report_has_no_recommended_work_when_all_groups_are_covered() -> None:
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
    assert report["ranked_work_queue"] == []
    assert report["recommended_next_work"] is None


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
    assert groups["mascara"]["direct_copy_notes"]["hook"] == [
        "Tengok bentuk berus maskara ni."
    ]
    assert groups["mascara"]["direct_copy_notes"]["benefit"] == [
        "Tunjuk berus dan satu sapuan terkawal pada bulu mata."
    ]
    assert groups["mascara"]["direct_copy_notes"]["cta"] == [
        "Semak jenis berus sebelum pilih."
    ]


def test_product_truth_source_type_outranks_misleading_title_and_family() -> None:
    cases = (
        (
            _product(
                "pants-1",
                "Female Wellness Comfort Pants",
                category="Fashion",
                subcategory="Bottoms",
                product_type="Pants",
            ),
            ("fashion_apparel", "bottom_apparel", "BOTTOM_APPAREL"),
        ),
        (
            _product(
                "wipes-1",
                "Perfumed Baby Wipes",
                category="Beauty",
                product_type="Baby Wipes",
            ),
            ("baby_care", "baby_wipes", "BABY_WIPES"),
        ),
        (
            _product(
                "sealer-1",
                "Compact Vacuum Kitchen Device",
                category="Home Appliances",
                product_type="Vacuum Sealers",
            ),
            ("home_equipment", "vacuum_sealer", "VACUUM_SEALER"),
        ),
    )

    for product, expected in cases:
        tag = classify_product_strategy_tag(product)
        assert (
            tag["cluster"],
            tag["product_type_group"],
            tag["matched_scene_strategy_id"],
        ) == expected
        assert tag["fallback_used"] is False
        assert tag["specific_strategy"] is True


def test_only_broad_and_unknown_types_remain_review_only_without_p4() -> None:
    by_key = {
        (str(entry["cluster"]), str(entry["product_type_group"])): entry
        for entry in product_strategy_type_registry_seed_entries()
    }

    for key in (
        ("beauty_personal_care", "beauty_personal_care_other"),
        ("home_equipment", "home_appliance"),
        ("generic_unclassified", "unknown_product_type"),
    ):
        entry = by_key[key]
        assert entry["registry_status"] == "REVIEW_REQUIRED"
        assert entry["scene_coverage_status"] == "FALLBACK_ONLY"

    review_keys = {
        key
        for key, entry in by_key.items()
        if entry["registry_status"] == "REVIEW_REQUIRED"
    }
    assert review_keys == {
        ("beauty_personal_care", "beauty_personal_care_other"),
        ("home_equipment", "home_appliance"),
        ("generic_unclassified", "unknown_product_type"),
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


# --- Category-aware last-resort layer (TikTok category coverage) -------------
# These products carry a real TikTok category but a TITLE with no proven-rule
# keyword, so before this layer they fell through to generic_unclassified.

def _bare(category: str, title: str = "Assorted Item ZZ") -> dict[str, object]:
    """A product whose title/type carry NO proven-rule keyword, so only the
    category-aware last-resort layer can classify it."""
    return _product(
        f"cat-{abs(hash((category, title))) % 100000}",
        title,
        category=category,
        product_type="Misc",
    )


def test_category_fallback_maps_known_categories_to_real_clusters() -> None:
    # the unambiguous mappings — a neutral title falls to the coarse category map
    expected = {
        "Pet Supplies": "pet_care",
        "Baby & Maternity": "baby_care",
        "Textiles & Soft Furnishings": "home_textiles",
        "Books, Magazines & Audio": "books_media",
        "Home Improvement": "home_improvement",
        "Tools & Hardware": "home_improvement",
        # "Home Supplies" is intentionally omitted: a fully-neutral title is
        # intercepted by the proven household default before the category layer;
        # its real titles (wall hooks) DO reach the layer (see the 57-draft run).
        "Automotive & Motorcycle": "automotive_accessory",
        "Sports & Outdoor": "outdoor_equipment",
        "Luggage & Bags": "fashion_accessory",
        "Computers & Office Equipment": "stationery",
        "Collectibles": "stationery",
    }
    for category, cluster in expected.items():
        tag = classify_product_strategy_tag(_bare(category))
        assert tag["cluster"] == cluster, (category, tag["cluster"])
        assert tag["product_type_group"] != "unknown_product_type", category


def test_every_category_fallback_cluster_is_a_real_strategy_cluster() -> None:
    """No fallback may invent a cluster outside the 40-cluster domain."""
    domain = crosswalk_domain()
    for cluster, product_type_group in _TIKTOK_CATEGORY_FALLBACK.values():
        assert cluster in domain, cluster
        assert product_type_group and product_type_group != "unknown_product_type"


def test_precise_title_keyword_wins_over_a_noisy_category() -> None:
    """A wardrobe dehumidifier / a raincoat mis-filed under Automotive must map
    to what the TITLE says, not to the noisy category."""
    dehum = classify_product_strategy_tag(
        _bare("Automotive & Motorcycle", "Dehumidifier Box Almari Pakaian Moisture Absorber")
    )
    assert dehum["cluster"] == "home_equipment"
    assert dehum["product_type_group"] == "dehumidifier"

    rain = classify_product_strategy_tag(
        _bare("Automotive & Motorcycle", "FOXDRY Raincoat Baju Hujan Waterproof")
    )
    assert rain["cluster"] == "fashion_apparel"

    # a genuine car item in the same category still gets the automotive cluster
    car = classify_product_strategy_tag(_bare("Automotive & Motorcycle", "Universal Car Cover Waterproof"))
    assert car["cluster"] == "automotive_accessory"


def test_supplement_and_fishing_titles_map_by_keyword() -> None:
    supp = classify_product_strategy_tag(_bare("Health", "Glutathione 6000mg Whitening Kapsul"))
    assert supp["cluster"] == "traditional_wellness"
    assert supp["product_type_group"] == "wellness_supplement"

    reel = classify_product_strategy_tag(_bare("Sports & Outdoor", "DAIWA Spinning Reel Pancing"))
    assert reel["cluster"] == "outdoor_equipment"
    assert reel["product_type_group"] == "fishing_gear"


def test_aromatherapy_oil_is_fragrance_not_flagship_wellness() -> None:
    """De-pollute the flagship: a scent oil filed under Health must map to
    fragrance, never traditional_wellness (adversarial review)."""
    tag = classify_product_strategy_tag(_bare("Health", "Aromatherapy Oil Jungle Girl 10 ML"))
    assert tag["cluster"] == "fragrance"


def test_blank_category_without_keyword_stays_generic() -> None:
    """The layer must NOT over-reach: no category signal + no keyword => honest
    generic_unclassified (never a guessed cluster)."""
    tag = classify_product_strategy_tag(_bare("", "Panadol Regular Coated"))
    assert tag["cluster"] == "generic_unclassified"
    assert tag["product_type_group"] == "unknown_product_type"


def test_proven_rule_is_unchanged_by_the_category_layer() -> None:
    """A product a proven rule already classifies must be byte-identical — the
    new layer is only reached AFTER every proven rule has missed."""
    lip = classify_product_strategy_tag(
        _product("lip-x", "Velvet Matte Lipstick", category="Automotive & Motorcycle", product_type="Lipstick")
    )
    assert lip["cluster"] == "beauty_makeup"          # NOT automotive
    assert lip["product_type_group"] == "lipstick_lip_tint"


def test_raw_and_normalized_category_fallback_maps_never_drift() -> None:
    assert _TIKTOK_CATEGORY_FALLBACK == {
        _normalize(raw): value for raw, value in _TIKTOK_CATEGORY_FALLBACK_RAW.items()
    }
