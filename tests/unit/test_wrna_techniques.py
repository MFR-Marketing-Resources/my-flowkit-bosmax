"""WRNA techniques (Phase C): poster recipe + IMG presets + category adapt."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.models.img_asset_factory import ImgFastlanePromptPreviewRequest
from agent.services.img_asset_factory_service import (
    IMG_FASTLANE_PRESETS,
    compile_img_fastlane_prompt_preview,
)
from agent.services.creative_direction_service import resolve_creative_direction
from agent.services.img_category_adapt_service import resolve_category_adapt
from agent.services.poster_recipe_service import get_recipe, list_recipes
from agent.services.poster_template_service import template_contract


# ── category adapt resolver ──────────────────────────────────────────────────
def test_category_adapt_matches_and_defaults():
    beauty = resolve_category_adapt({"category": "Beauty & Personal Care"})
    assert "vanity" in beauty["background"]
    assert "approved avatar" in beauty["model"]
    assert "hijab" not in beauty["model"]

    food = resolve_category_adapt({"category": "Food & Beverages"})
    assert "kitchen" in food["background"]

    unknown = resolve_category_adapt({"category": "Something Nobody Mapped"})
    assert "studio" in unknown["background"]  # fail-closed default

    assert "studio" in resolve_category_adapt(None)["background"]


@pytest.mark.parametrize(
    ("category", "expected_background"),
    [
        ("Food & Beverages", "kitchen"),
        ("Haircare", "bathroom"),
        ("Baby & Kids", "nursery"),
        ("Automotive", "garage"),
    ],
)
def test_category_adapt_does_not_assign_fixed_gender_or_role(category, expected_background):
    model = resolve_category_adapt({"category": category})["model"].lower()

    assert expected_background in resolve_category_adapt({"category": category})["background"]
    assert "neutral adult presenter" in model
    assert "woman" not in model
    assert " man " not in f" {model} "
    assert "mother" not in model
    assert "father" not in model


def test_category_adapt_matches_on_name_when_category_missing():
    adapt = resolve_category_adapt({"product_display_name": "Langsir KKBS Curtain"})
    assert "living space" in adapt["background"]


# ── poster recipe ─────────────────────────────────────────────────────────────
def test_wrna_ads_recipe_loads_and_validates():
    recipe = get_recipe("wrna_ads_poster_916")
    assert recipe is not None
    assert recipe.archetype == "ADS_PREMIUM"
    assert recipe.max_chips == 3
    assert {z.role for z in recipe.zones} == {"HEADLINE", "SUBHEADLINE", "CHIP", "CTA"}
    assert recipe.safety_posture == "STANDARD"


def test_wrna_ads_recipe_has_a_complete_production_template_contract():
    contract = template_contract("wrna_ads_poster_916")
    assert contract["product_safe_region"] == {"x": 14, "y": 30, "w": 72, "h": 40}
    assert contract["palette"]
    assert contract["background_constraints"]


def test_existing_recipe_ids_unchanged():
    ids = [r.recipe_id for r in list_recipes()]
    assert ids[:6] == [
        "product_hero_night_routine", "product_scale_portability",
        "heritage_infographic", "routine_use", "offer_promo",
        "problem_aware_safe",
    ]
    assert "wrna_ads_poster_916" in ids


def test_guided_goal_archetype_matches_recipe_archetype():
    # Cross-file equality (a PORTABILITY-style mismatch silently breaks the
    # guided flow): the TS goal card must carry the recipe's exact archetype.
    guided = Path("dashboard/src/poster/guided/posterGuided.ts").read_text(
        encoding="utf-8"
    )
    recipe = get_recipe("wrna_ads_poster_916")
    assert f'archetype: "{recipe.archetype}"' in guided


# ── IMG presets ───────────────────────────────────────────────────────────────
def _fake_product(category: str):
    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-x",
            "product_display_name": "Produk Ujian",
            "raw_product_title": "Produk Ujian",
            "category": category,
            "media_id": "media-x",
        }

    return fake_get_product


def test_presets_registered_with_no_text_lanes():
    by_id = {p["preset_id"]: p for p in IMG_FASTLANE_PRESETS}
    cgi = by_id["WRNA_CGI_COMMERCIAL_FLOAT"]
    ecom = by_id["WRNA_ECOM_LIFESTYLE"]
    assert cgi["lane_id"] == "PRODUCT_ONLY_HERO"
    assert ecom["lane_id"] == "AVATAR_PRODUCT_SCENE_COMPOSITE"


def test_cgi_float_preview_category_adaptive_no_humans(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Beauty & Personal Care"))
    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="WRNA_CGI_COMMERCIAL_FLOAT",
                route="INGREDIENTS",
                ingredient_role="PRODUCT_REFERENCE",
                product_id="prod-x",
            )
        )
    )
    text = preview.prompt_text
    assert "hyper-realistic CGI render" in text
    assert "smooth gradients, glass textures" in text  # beauty float elements
    assert "No humans in frame" in text
    assert "zero distortion" in text
    # clean-frame no-text law stays active on this lane
    assert "PRODUCT_ONLY_HERO" in text or preview.engine_prompt_text


def test_ecom_lifestyle_preview_adapts_model_and_background(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Food & Beverages"))
    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="WRNA_ECOM_LIFESTYLE",
                route="FRAMES",
                product_id="prod-x",
            )
        )
    )
    text = preview.prompt_text
    assert "Malaysian home kitchen" in text
    assert "85mm portrait look" in text
    assert "60-70 percent" in text
    assert "max 3 units" in text


def test_ecom_lifestyle_unknown_category_uses_default(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Mystery Category"))
    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="WRNA_ECOM_LIFESTYLE",
                route="FRAMES",
                product_id="prod-x",
            )
        )
    )
    assert "neutral premium studio surface" in preview.prompt_text


def test_img_fastlane_explicit_creative_modes_are_distinct_and_versioned(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Food & Beverages"))
    outputs = {}
    for mode in (
        "PGC_CAMPAIGN", "UGC_AUTHENTIC", "MODEL_AMBASSADOR",
        "CLEAN_STUDIO_CATALOGUE", "LIFESTYLE_EDITORIAL",
    ):
        preview = asyncio.run(compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="WRNA_ECOM_LIFESTYLE", route="FRAMES",
                product_id="prod-x", creative_mode=mode,
            )
        ))
        outputs[mode] = preview
        assert preview.creative_direction["mode"] == mode
        assert preview.creative_direction["authority_version"] == "creative-direction-modes-v1"
        assert preview.creative_direction["representation_policy_version"] == "malaysian-representation-policy-v1"
    assert len({item.engine_prompt_text for item in outputs.values()}) == 5


def test_img_fastlane_absent_mode_is_legacy_and_invalid_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Food & Beverages"))
    legacy = asyncio.run(compile_img_fastlane_prompt_preview(
        ImgFastlanePromptPreviewRequest(
            preset_id="WRNA_ECOM_LIFESTYLE", route="FRAMES", product_id="prod-x",
        )
    ))
    assert legacy.creative_direction == {}
    with pytest.raises(ValueError, match="UNSUPPORTED_CREATIVE_MODE"):
        asyncio.run(compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="WRNA_ECOM_LIFESTYLE", route="FRAMES", product_id="prod-x",
                creative_mode="UNSAFE_MODE",
            )
        ))


def test_img_fastlane_precedence_suppresses_identity_and_preset_conflicts(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Food & Beverages"))
    preview = asyncio.run(compile_img_fastlane_prompt_preview(
        ImgFastlanePromptPreviewRequest(
            preset_id="WRNA_ECOM_LIFESTYLE", route="FRAMES", product_id="prod-x",
            character_reference_asset_id="ca-approved-avatar",
            creative_mode="MODEL_AMBASSADOR",
        )
    ))
    direction = resolve_creative_direction("MODEL_AMBASSADOR", product={"category": "Food & Beverages"})
    assert f"Composition: {direction.composition_direction}" not in preview.prompt_text
    assert f"Framing: {direction.camera_framing}" not in preview.prompt_text
    assert "Human presence:" not in preview.prompt_text
    assert f"Props: {direction.props}" not in preview.prompt_text
    assert f"Lighting: {direction.lighting}" not in preview.prompt_text
    assert f"Environment: {direction.environment}" not in preview.prompt_text


def test_product_only_cgi_preset_suppresses_ugc_conflicts_but_keeps_safe_negative(monkeypatch):
    monkeypatch.setattr(crud, "get_product", _fake_product("Beauty & Personal Care"))
    preview = asyncio.run(compile_img_fastlane_prompt_preview(
        ImgFastlanePromptPreviewRequest(
            preset_id="WRNA_CGI_COMMERCIAL_FLOAT",
            route="INGREDIENTS",
            ingredient_role="PRODUCT_REFERENCE",
            product_id="prod-x",
            creative_mode="UGC_AUTHENTIC",
        )
    ))
    direction = resolve_creative_direction("UGC_AUTHENTIC", product={"category": "Beauty & Personal Care"})
    assert "dramatic cinematic lighting" in preview.prompt_text
    assert "No humans in frame — product is the only hero." in preview.negative_rules
    assert f"Lighting: {direction.lighting}" not in preview.prompt_text
    assert f"Environment: {direction.environment}" not in preview.prompt_text
    assert f"Composition: {direction.composition_direction}" not in preview.prompt_text
    assert "Human presence:" not in preview.prompt_text
    assert "cinematic grade" not in preview.negative_rules
    assert "product distortion" in preview.negative_rules
