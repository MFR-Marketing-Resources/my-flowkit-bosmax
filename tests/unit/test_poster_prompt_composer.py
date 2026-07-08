"""PR B1: recipe composer + legacy byte-identical routing.

Proves that build_draft WITHOUT a recipe_id runs the UNCHANGED legacy assembler
(byte-identical poster_prompt, null specs), and WITH a recipe_id runs the composer
(structured poster_spec/overlay_spec, recipe-shaped prompt). Reuses the readiness
fixture + crud.get_product mock pattern of test_poster_prompt_draft_service.
"""

import pytest

from agent.models.poster_recipe import PosterRecipe
from agent.services import poster_recipe_service
from agent.services import poster_prompt_draft_service as svc
from agent.services.poster_prompt_composer import compose_recipe_poster
from agent.services.poster_prompt_draft_service import PosterPromptDraftService
from tests.unit.test_poster_prompt_draft_service import _full_request
from tests.unit.test_poster_readiness_service import _ready_base


def _mock_product(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    monkeypatch.setattr(
        "agent.services.poster_prompt_draft_service.crud.get_product", fake_get
    )


# ── Pure composer unit ────────────────────────────────────────────────────────


def test_compose_recipe_poster_builds_spec_and_overlay():
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    fields = {
        "hook": "Malam lebih tenang",
        "subhook": "Rutin mudah setiap malam",
        "usp_1": "Saiz kecil",
        "usp_2": "Mudah dibawa",
        "usp_3": "Formula warisan",
        "cta": "Dapatkan sekarang",
        "frame_ratio": "9:16",
        "operator_notes": "",
    }
    prompt, spec, overlay = compose_recipe_poster(
        fields=fields,
        recipe=recipe,
        product_truth_lock="LOCK",
        visual_instruction="VISUAL",
        text_overlay_instruction="OVERLAY",
        safety_guardrails=["Follow product truth lock; no unapproved claims."],
        restricted_mode=False,
    )
    assert "=== POSTER RECIPE ===" in prompt
    assert "=== COPY SLOTS ===" in prompt
    assert "Malam lebih tenang" in prompt
    assert spec.recipe_id == "product_hero_night_routine"
    assert spec.archetype == "PRODUCT_HERO"
    # Overlay is a deterministic FOUNDATION only.
    assert overlay.renderer == "NONE_PHASE_2"
    assert overlay.frame_ratio == "9:16"
    headline = [z for z in overlay.zones if z.zone_id == "headline"][0]
    assert headline.text == "Malam lebih tenang"  # filled from hook
    # Unfilled source-less zones fall back to the neutral placeholder.
    # (product_scale has no footer; hero has no source-less zone, so verify heritage.)


def test_overlay_zone_uses_placeholder_when_unfilled():
    heritage = poster_recipe_service.get_recipe("heritage_infographic")
    _, _, overlay = compose_recipe_poster(
        fields={"hook": "Tajuk", "cta": "Beli", "frame_ratio": "9:16"},
        recipe=heritage,
        product_truth_lock="LOCK",
        visual_instruction="V",
        text_overlay_instruction="O",
        safety_guardrails=[],
        restricted_mode=False,
    )
    footer = [z for z in overlay.zones if z.zone_id == "footer"][0]
    assert footer.text == "[Barisan warisan]"  # source_field="" → placeholder


# ── build_draft routing (legacy byte-identical vs recipe) ─────────────────────


@pytest.mark.asyncio
async def test_no_recipe_runs_unchanged_legacy_assembler(monkeypatch):
    _mock_product(monkeypatch)
    # Sentinel proves the LEGACY assembler is what runs when no recipe is given.
    monkeypatch.setattr(
        svc, "_assemble_poster_prompt", lambda **kw: "LEGACY_SENTINEL_PROMPT"
    )
    result = await PosterPromptDraftService.build_draft(_full_request())
    assert result.poster_prompt == "LEGACY_SENTINEL_PROMPT"
    assert result.poster_spec is None
    assert result.overlay_spec is None


@pytest.mark.asyncio
async def test_recipe_path_uses_composer_not_legacy(monkeypatch):
    _mock_product(monkeypatch)
    # If the legacy assembler were (wrongly) used, the prompt would be the sentinel.
    monkeypatch.setattr(
        svc, "_assemble_poster_prompt", lambda **kw: "LEGACY_SENTINEL_PROMPT"
    )
    result = await PosterPromptDraftService.build_draft(
        _full_request(poster_recipe_id="product_hero_night_routine")
    )
    assert result.poster_prompt != "LEGACY_SENTINEL_PROMPT"
    assert "=== POSTER RECIPE ===" in result.poster_prompt
    assert result.poster_spec is not None
    assert result.poster_spec.recipe_id == "product_hero_night_routine"
    assert result.overlay_spec is not None
    assert result.overlay_spec.renderer == "NONE_PHASE_2"


@pytest.mark.asyncio
async def test_unknown_recipe_fails_closed(monkeypatch):
    _mock_product(monkeypatch)
    with pytest.raises(svc.PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(poster_recipe_id="nope_not_a_recipe")
        )
    assert any("Unknown poster recipe" in e for e in exc.value.field_errors)


@pytest.mark.asyncio
async def test_recipe_negative_prompt_additions_appended(monkeypatch):
    _mock_product(monkeypatch)
    recipe = poster_recipe_service.get_recipe("product_hero_night_routine")
    result = await PosterPromptDraftService.build_draft(
        _full_request(poster_recipe_id="product_hero_night_routine")
    )
    for extra in recipe.negative_prompt_additions:
        assert extra in result.negative_prompt


@pytest.mark.asyncio
async def test_recipe_path_still_rejects_unsafe_slot_copy(monkeypatch):
    # The recipe path must NOT bypass the unsafe-claim scan on operator copy.
    _mock_product(monkeypatch)
    with pytest.raises(svc.PosterPromptDraftValidationError) as exc:
        await PosterPromptDraftService.build_draft(
            _full_request(
                poster_recipe_id="product_hero_night_routine",
                hook="This will cure your pain",
            )
        )
    assert any("cure" in e for e in exc.value.field_errors)


def test_recipe_model_roundtrip():
    # The authority YAML validates cleanly into the PosterRecipe model.
    for r in poster_recipe_service.list_recipes():
        assert isinstance(r, PosterRecipe)
