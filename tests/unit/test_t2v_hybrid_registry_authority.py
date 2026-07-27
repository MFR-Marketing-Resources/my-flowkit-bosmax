"""Registry authority for T2V/Hybrid: avatar_id beats persona mask; scene override applies."""

from __future__ import annotations

from unittest.mock import patch

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt


def _product():
    return {
        "id": "prod-registry-1",
        "name": "Registry Product",
        "category": "skincare",
        "product_display_name": "Registry Product",
    }


def _approved():
    return {
        "scene_context": "Product package default vanity scene",
        "hook": "Cuba sekarang",
        "cta": "Klik link",
        "usps": ["cepat", "mudah", "halal"],
        "claim_safe_rewrite": "Produk ini mudah digunakan setiap hari.",
    }


def test_t2v_avatar_id_wins_over_persona_variant():
    persona_profile = {
        "avatar_id": "PERSONA_MASK",
        "prose_override": "persona mask office woman in a navy blouse",
    }
    registry_profile = {
        "avatar_code": "BOS_F_TEST_99",
        "skin_tone": "Light-medium",
        "hair_style": "Long wavy",
        "wardrobe": "home casual knit",
        "expression": "Calm friendly",
        "age_band": "Adult (25-34)",
    }

    with (
        patch(
            "agent.services.persona_variant_service.presenter_profile_for_persona",
            return_value=persona_profile,
        ) as persona_mock,
        patch(
            "agent.services.avatar_registry.resolve_presenter",
            return_value=registry_profile,
        ) as avatar_mock,
    ):
        result = compile_ugc_video_prompt(
            product=_product(),
            approved_package=_approved(),
            mode="T2V",
            source_mode="T2V",
            creator_persona="AVATAR_ALYA_OFFICE",
            avatar_id="BOS_F_TEST_99",
            duration_seconds=8,
        )

    avatar_mock.assert_called()
    persona_mock.assert_not_called()
    assert result.get("avatar_id") == "BOS_F_TEST_99"
    text = result["final_compiled_prompt_text"]
    assert "home casual knit" in text
    assert "persona mask office woman" not in text


def test_hybrid_scene_context_override_from_registry():
    # HYBRID lineage uses mode=F2V + source_mode=HYBRID (SUPPORTED_MODES).
    with patch(
        "agent.services.avatar_registry.resolve_presenter",
        return_value={
            "avatar_code": "BOS_F_SEED_01",
            "skin_tone": "Light",
            "hair_style": "Short neat",
            "wardrobe": "casual tee",
            "expression": "Warm",
            "age_band": "Adult (25-34)",
        },
    ):
        result = compile_ugc_video_prompt(
            product=_product(),
            approved_package=_approved(),
            mode="F2V",
            source_mode="HYBRID",
            creator_persona="DEFAULT_CREATOR",
            scene_context_override="Background: Raya kampung courtyard with pelita lamps",
            duration_seconds=8,
        )

    assert result.get("scene_context_override_applied") is True
    assert result.get("source_mode") == "HYBRID"
    text = result["final_compiled_prompt_text"]
    assert "Raya kampung" in text or "pelita" in text


def test_t2v_without_avatar_id_still_allows_persona_optional_path():
    persona_profile = {
        "avatar_id": "AVATAR_ALYA_OFFICE",
        "prose_override": "alya office persona in smart navy wear at a desk",
    }
    with (
        patch(
            "agent.services.persona_variant_service.presenter_profile_for_persona",
            return_value=persona_profile,
        ),
        patch("agent.services.avatar_registry.resolve_presenter") as avatar_mock,
    ):
        result = compile_ugc_video_prompt(
            product=_product(),
            approved_package=_approved(),
            mode="T2V",
            source_mode="T2V",
            creator_persona="AVATAR_ALYA_OFFICE",
            avatar_id=None,
            duration_seconds=8,
        )
    avatar_mock.assert_not_called()
    text = result["final_compiled_prompt_text"]
    assert "alya office persona" in text
    assert result.get("avatar_id") is None
