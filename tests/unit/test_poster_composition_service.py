import pytest

from agent.services.poster_composition_service import resolve_poster_composition, render_composition_instruction


class Direction:
    def __init__(self, mode): self.mode = mode


@pytest.mark.parametrize("mode", ["PGC_CAMPAIGN", "UGC_AUTHENTIC", "MODEL_AMBASSADOR", "CLEAN_STUDIO_CATALOGUE", "LIFESTYLE_EDITORIAL"])
def test_each_wrna_mode_resolves_a_structured_professional_plan(mode):
    plan = resolve_poster_composition(creative_direction=Direction(mode), recipe_id="wrna_ads_poster_916", frame_ratio="9:16", fields={"hook": "Ringkas", "cta": "Lihat sekarang"})
    assert plan["schema_version"] == "wrna-poster-composition-v1"
    assert plan["creative_mode"] == mode
    assert plan["canvas"]["safe_margin"] == "5%"
    assert plan["product"]["label_visibility"] == "required"
    assert plan["copy"]["cta_zone"]
    assert "no text covering product or face" in plan["quality_negative_rules"]


def test_modes_are_structurally_distinct_and_prompt_is_engine_facing():
    plans = [resolve_poster_composition(creative_direction=Direction(mode), recipe_id="r", frame_ratio="9:16", fields={}) for mode in ("PGC_CAMPAIGN", "UGC_AUTHENTIC", "MODEL_AMBASSADOR", "CLEAN_STUDIO_CATALOGUE", "LIFESTYLE_EDITORIAL")]
    assert len({(p["profile_id"], p["product"]["anchor"], p["scene"]["human_presence"]) for p in plans}) == 5
    prompt = render_composition_instruction(plans[0])
    assert "product anchored" in prompt and "safe margin" in prompt
    assert "profile_id" not in prompt and "schema_version" not in prompt


def test_no_mode_preserves_legacy_empty_plan_and_density_warnings_are_stable():
    assert resolve_poster_composition(creative_direction=None, recipe_id="r", frame_ratio="9:16", fields={}) == {}
    plan = resolve_poster_composition(creative_direction=Direction("PGC_CAMPAIGN"), recipe_id="r", frame_ratio="9:16", fields={"hook": "x" * 49, "cta": "x" * 25})
    assert plan["warnings"] == ["HOOK_DENSITY_EXCEEDS_COMPOSITION_LIMIT", "CTA_DENSITY_EXCEEDS_COMPOSITION_LIMIT"]
