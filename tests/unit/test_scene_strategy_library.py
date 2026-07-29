from __future__ import annotations

import pytest

from agent.services import variation_matrix
from agent.services.scene_strategy_library import (
    SCENE_STRATEGIES,
    build_scene_strategy_context,
    resolve_scene_strategy,
)
from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)
from agent.services.workspace_generation_package_service import (
    _compiler_product_context,
)


def _product(name: str, **fields: object) -> dict[str, object]:
    return {
        "id": f"product-{name.casefold().replace(' ', '-')}",
        "name": name,
        "raw_product_title": name,
        **fields,
    }


def _compile(
    product: dict[str, object],
    *,
    copy_intelligence: dict[str, object] | None = None,
    scene_context_override: str | None = None,
) -> dict[str, object]:
    return compile_ugc_video_prompt(
        product=product,
        approved_package={},
        mode="F2V",
        source_mode="HYBRID",
        generation_mode="SINGLE",
        duration_seconds=8,
        character_presence="FACELESS",
        target_language="BM_MS",
        copy_intelligence=copy_intelligence,
        scene_context_override=scene_context_override,
    )


def test_library_entries_are_complete_and_direct_buyer_facing() -> None:
    required_fields = {
        "product_family",
        "product_type",
        "use_case",
        "allowed_scene_strategy",
        "allowed_actions",
        "forbidden_actions",
        "scene_contexts",
        "camera_routes",
        "avatar_hints",
        "wardrobe_hints",
        "direct_script_slots",
        "sensitive_handling_rules",
    }
    banned_fluff = (
        "confidence-led",
        "routine-led",
        "trust-led",
        "appetite context",
    )

    for strategy_id, entry in SCENE_STRATEGIES.items():
        assert set(entry) == required_fields, strategy_id
        for field in (
            "use_case",
            "allowed_scene_strategy",
            "allowed_actions",
            "forbidden_actions",
            "scene_contexts",
            "camera_routes",
            "avatar_hints",
            "wardrobe_hints",
        ):
            assert entry[field], f"{strategy_id}:{field}"
        scripts = entry["direct_script_slots"]
        assert scripts["hook"] and scripts["benefit"] and scripts["cta"]
        rendered_scripts = " ".join(
            [*scripts["hook"], *scripts["benefit"], *scripts["cta"]]
        ).casefold()
        assert not any(phrase in rendered_scripts for phrase in banned_fluff)


def test_lipstick_maps_to_lip_mirror_swatch_and_handbag_usage_grammar() -> None:
    strategy = resolve_scene_strategy(
        _product(
            "Velvet Lip Tint",
            category="Beauty & Personal Care",
            type="Lip Makeup",
        )
    )

    combined = " ".join(
        [
            *strategy["allowed_scene_strategy"],
            *strategy["allowed_actions"],
            *strategy["scene_contexts"],
        ]
    ).casefold()
    assert strategy["strategy_id"] == "LIP_COLOR"
    assert strategy["fallback_used"] is False
    assert "lip application" in combined
    assert "mirror" in combined
    assert "swatch" in combined
    assert "handbag" in combined
    assert "Sekali sapu warna terus naik." in strategy["direct_script_slots"]["hook"]


def test_rempah_maps_to_cooking_prep_pan_sprinkle_and_plated_finish() -> None:
    strategy = resolve_scene_strategy(
        _product(
            "Rempah Ayam Berempah",
            category="Food & Beverage",
            type="Seasoning",
        )
    )

    combined = " ".join(
        [
            *strategy["allowed_scene_strategy"],
            *strategy["allowed_actions"],
            *strategy["scene_contexts"],
        ]
    ).casefold()
    assert strategy["strategy_id"] == "SPICE_SEASONING"
    assert "ingredient counter" in combined
    assert "sprinkle" in combined
    assert "pan" in combined
    assert "plated dish" in combined
    assert "Tabur sikit, bau masakan terus naik." in strategy["direct_script_slots"]["hook"]


def test_fragrance_maps_to_scent_and_social_ready_finishing_scenes() -> None:
    strategy = resolve_scene_strategy(
        _product(
            "Elianto Body Mist",
            category="Beauty & Personal Care",
            type="Fragrance",
        )
    )

    combined = " ".join(
        [
            *strategy["allowed_scene_strategy"],
            *strategy["allowed_actions"],
            *strategy["scene_contexts"],
        ]
    ).casefold()
    assert strategy["strategy_id"] == "FRAGRANCE"
    assert "spritz" in combined
    assert "social-ready" in combined
    assert "handbag" in combined
    assert "spray toward eyes" in " ".join(strategy["forbidden_actions"])


def test_detergent_maps_to_measured_laundry_use() -> None:
    strategy = resolve_scene_strategy(
        _product(
            "Sabun Dobi Cecair Refill",
            category="Home & Living",
            type="Laundry Detergent",
        )
    )

    combined = " ".join(
        [
            *strategy["allowed_scene_strategy"],
            *strategy["allowed_actions"],
            *strategy["scene_contexts"],
        ]
    ).casefold()
    assert strategy["strategy_id"] == "LAUNDRY_DETERGENT"
    assert "laundry" in combined
    assert "measure" in combined
    assert "washer" in combined
    assert "mix detergent" in " ".join(strategy["forbidden_actions"])


@pytest.mark.parametrize(
    ("name", "expected_strategy"),
    [
        ("Baby Wet Wipes", "BABY_WIPES"),
        ("Premium Baby Diaper", "BABY_DIAPER"),
        ("Jubah Modestwear", "MODESTWEAR"),
        ("Quick Dry Jersi Sportswear", "SPORTSWEAR"),
        ("All Purpose Household Cleaner", "HOUSEHOLD_CLEANER"),
        ("Drawer Storage Organizer", "HOUSEHOLD_STORAGE"),
        ("USB Cable Charger", "ELECTRONICS_ACCESSORY"),
        ("Mini Wireless Device", "ELECTRONICS_SMALL_DEVICE"),
        ("Mini Chopper", "ELECTRONICS_SMALL_DEVICE"),
        ("Daily Face Serum", "BEAUTY_PERSONAL_CARE"),
        ("Sambal Ikan Bilis", "PACKAGED_SAUCE_SAMBAL"),
    ],
)
def test_required_product_groups_have_specific_strategies(
    name: str,
    expected_strategy: str,
) -> None:
    strategy = resolve_scene_strategy(_product(name))

    assert strategy["strategy_id"] == expected_strategy
    assert strategy["fallback_used"] is False
    assert strategy["allowed_actions"]
    assert strategy["camera_routes"]
    assert strategy["direct_script_slots"]["benefit"]


@pytest.mark.parametrize(
    ("fields", "expected_strategy"),
    (
        (
            {
                "name": "Female Wellness Comfort Pants",
                "category": "Fashion",
                "subcategory": "Bottoms",
                "type": "Pants",
            },
            "BOTTOM_APPAREL",
        ),
        (
            {
                "name": "Household Detergent Style Cleaner",
                "category": "Household",
                "type": "Household Cleaners",
            },
            "HOUSEHOLD_CLEANER",
        ),
        (
            {
                "name": "Compact Vacuum Kitchen Device",
                "category": "Home Appliances",
                "type": "Vacuum Sealers",
            },
            "VACUUM_SEALER",
        ),
    ),
)
def test_exact_product_truth_mapping_precedes_title_keywords(
    fields,
    expected_strategy,
) -> None:
    name = str(fields["name"])
    strategy = resolve_scene_strategy(
        _product(name, **{key: value for key, value in fields.items() if key != "name"})
    )

    assert strategy["strategy_id"] == expected_strategy
    assert strategy["resolution_source"].startswith(
        "product_truth_source_type:"
    )
    assert strategy["fallback_used"] is False


@pytest.mark.parametrize(
    "name",
    [
        "Herba Tahan Lama Lelaki",
        "Jamu Intim Wanita",
    ],
)
def test_sensitive_products_block_explicit_application_ingestion_and_body_actions(
    name: str,
) -> None:
    strategy = resolve_scene_strategy(_product(name))
    forbidden = " ".join(strategy["forbidden_actions"]).casefold()
    context = build_scene_strategy_context(strategy).casefold()

    assert strategy["strategy_id"] == "SENSITIVE_WELLNESS"
    assert strategy["sensitive_handling_rules"]
    assert "ingest" in forbidden
    assert "intimate areas" in forbidden
    assert "body-part close-ups" in forbidden
    assert "medical-style proof" in forbidden
    assert "product-only" in context
    assert "no ingestion" in context


def test_unknown_product_uses_stable_generic_fallback_without_crashing() -> None:
    strategy = resolve_scene_strategy(_product("Opaque Novelty Object 742"))

    assert strategy["strategy_id"] == "GENERIC_FALLBACK"
    assert strategy["fallback_used"] is True
    assert strategy["scene_contexts"] == [
        "Modern minimalist kitchen",
        "Bright living room",
        "Professional studio",
    ]


def test_workspace_package_preserves_product_type_for_opaque_brand_names() -> None:
    context = _compiler_product_context(
        "product-opaque",
        "MagicMix X1",
        {
            "raw_product_title": "MagicMix X1",
            "category": "Food & Beverage",
            "subcategory": "Cooking Ingredients",
            "type": "Seasoning",
            "product_type": "Packaged Food",
            "product_type_id": "FOOD_PACKAGED_GOODS",
        },
    )
    strategy = resolve_scene_strategy(context)

    assert context["type"] == "Seasoning"
    assert context["product_type_id"] == "FOOD_PACKAGED_GOODS"
    assert strategy["strategy_id"] == "SPICE_SEASONING"


@pytest.mark.asyncio
async def test_variation_planner_emits_product_actions_and_direct_buyer_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _brief(_: str) -> dict[str, object]:
        return {
            "brief_id": "brief-lip",
            "product_intelligence": {
                "product_short_name": "Velvet Lip Tint",
                "raw_product_title": "Velvet Lip Tint",
                "category": "Beauty & Personal Care",
                "subcategory": "Makeup",
                "type": "Lip Makeup",
            },
            "copywriting_route": {
                "product_type": "Beauty",
                "product_type_id": "BEAUTY_PERSONAL_CARE",
                "silo": "Beauty",
                "formula": "PAS",
            },
            "creative_mapping": {
                "scene_context_recommendations": [],
                "camera_recommendations": [],
            },
            "readiness": {"Frames": "READY"},
            "missing_fields": [],
        }

    monkeypatch.setattr(variation_matrix, "get_creative_brief", _brief)
    variations = await variation_matrix.generate_variation_plan(
        "product-lip",
        quantity=4,
    )

    combined = " ".join(
        str(item["scene_context"]) + " " + str(item["allowed_action"])
        for item in variations
    ).casefold()
    assert {item["scene_strategy_id"] for item in variations} == {"LIP_COLOR"}
    assert "lip" in combined
    assert "mirror" in combined
    assert "swatch" in combined
    assert all(
        str(item["hook_angle"]).startswith(("Sekali", "Nak"))
        for item in variations
    )
    assert all("confidence framing" not in str(item).casefold() for item in variations)


def test_production_compiler_uses_strategy_but_preserves_explicit_copy() -> None:
    product = _product(
        "Velvet Lip Tint",
        category="Beauty & Personal Care",
        type="Lip Makeup",
    )
    first = _compile(
        product,
        copy_intelligence={
            "hook": "Shade merah ni memang terus nampak.",
            "usps": ["Warna ini dipilih untuk gaya malam."],
            "cta": "Semak shade merah ini.",
        },
        scene_context_override="operator-selected dressing room",
    )
    second = _compile(
        product,
        copy_intelligence={
            "hook": "Shade nude ni senang masuk gaya harian.",
            "usps": ["Warna ini dipilih untuk gaya siang."],
            "cta": "Semak shade nude ini.",
        },
        scene_context_override="operator-selected dressing room",
    )

    assert first["scene_strategy"]["strategy_id"] == "LIP_COLOR"
    assert second["scene_strategy"]["strategy_id"] == "LIP_COLOR"
    assert first["scene_strategy"] == second["scene_strategy"]
    assert first["prompt_blocks"][0]["exact_dialogue_slice"] != second[
        "prompt_blocks"
    ][0]["exact_dialogue_slice"]
    assert "operator-selected dressing room" in first["final_compiled_prompt_text"]
    assert "Allowed product action: apply one clean pass to the lips." in first[
        "final_compiled_prompt_text"
    ]


def test_production_compiler_adds_sensitive_fail_closed_constraints() -> None:
    result = _compile(
        _product("Premium Male Wellness Tahan Lama"),
        scene_context_override="discreet premium shelf",
    )
    final_prompt = str(result["final_compiled_prompt_text"]).casefold()

    assert result["scene_strategy"]["strategy_id"] == "SENSITIVE_WELLNESS"
    assert "discreet premium shelf" in final_prompt
    assert "forbidden actions:" in final_prompt
    assert "apply the product to intimate areas" in final_prompt
    assert "sensitive handling rules:" in final_prompt


@pytest.mark.parametrize(
    ("product", "expected_strategy", "expected_action"),
    (
        (
            _product(
                "Minyak Warisan Cap Burung 25ml",
                product_type="TRADITIONAL_HERBAL_OIL",
                product_physics="TRADITIONAL_HERBAL_OIL_BOTTLE",
            ),
            "TRADITIONAL_HERBAL_OIL",
            "apply a small amount to an adult forearm or wrist",
        ),
        (
            _product(
                "Bosmax Herbs 5 ML",
                category="Male Health",
                type="Herbal Oil Roll On",
            ),
            "HERBAL_ROLL_ON_OIL",
            "roll a small amount onto an adult wrist",
        ),
    ),
)
def test_traditional_wellness_strategies_are_specific_and_claim_safe(
    product: dict[str, object],
    expected_strategy: str,
    expected_action: str,
) -> None:
    strategy = resolve_scene_strategy(product)
    allowed = " ".join(strategy["allowed_actions"]).casefold()
    forbidden = " ".join(strategy["forbidden_actions"]).casefold()
    scripts = " ".join(
        [
            *strategy["direct_script_slots"]["hook"],
            *strategy["direct_script_slots"]["benefit"],
            *strategy["direct_script_slots"]["cta"],
        ]
    ).casefold()

    assert strategy["strategy_id"] == expected_strategy
    assert strategy["fallback_used"] is False
    assert expected_action in allowed
    assert "label-forward" in allowed
    assert "store" in allowed
    assert "intimate areas" in forbidden
    assert "demonstrate use on a child" in forbidden
    assert "invent ingredients" in forbidden
    assert not any(term in scripts for term in ("cure", "rawat", "sembuh", "ubat"))
