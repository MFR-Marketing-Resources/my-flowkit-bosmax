"""Mascot Montage Creative Grammar V1.1 — duration matrix, model authority,
WPS-from-authority, micro-beats, visual dynamism, lip-sync, per-scene distinctness,
and provider-prompt no-leakage. Pure (provider-free)."""
from __future__ import annotations

import pytest

from agent.services import canonical_prompt_compiler as canonical
from agent.services import montage_mascot_creative_grammar as g
from agent.services.canonical_prompt_compiler import scrub_check
from agent.services.production_prompt_approval_service import scan_prompt_text

# final -> (block_count, atomic_seconds, assembly)
_MATRIX = {
    8: (1, 8, g.SINGLE_FINALIZE),
    10: (1, 10, g.SINGLE_FINALIZE),
    16: (2, 8, g.DISCRETE_MONTAGE),
    20: (2, 10, g.DISCRETE_MONTAGE),
    24: (3, 8, g.DISCRETE_MONTAGE),
    30: (3, 10, g.DISCRETE_MONTAGE),
}


@pytest.mark.parametrize("final,expected", sorted(_MATRIX.items()))
def test_final_duration_matrix_resolves_through_authority(final, expected):
    block_count, atomic, assembly = expected
    plan = g.resolve_final_duration_plan(final)
    assert plan.block_count == block_count
    assert plan.atomic_seconds == atomic
    assert list(plan.block_plan) == [atomic] * block_count
    assert plan.assembly == assembly
    # block plan comes from the canonical authority (never a local table)
    assert list(plan.block_plan) == list(canonical.resolve_block_plan("GOOGLE_FLOW", final))
    # final duration == segment_count × atomic_block_seconds
    assert final == plan.block_count * plan.atomic_seconds


@pytest.mark.parametrize("final", [10, 20, 30])
def test_ten_family_resolves_omni_flash_only(final):
    plan = g.resolve_final_duration_plan(final)
    assert plan.atomic_seconds == 10
    assert plan.models == ("Omni Flash",)
    assert plan.default_model == "Omni Flash"


@pytest.mark.parametrize("final", [8, 16, 24])
def test_eight_family_allows_all_single_models(final):
    plan = g.resolve_final_duration_plan(final)
    assert plan.atomic_seconds == 8
    assert "Omni Flash" in plan.models and "Veo 3.1 - Lite" in plan.models


@pytest.mark.parametrize("final", [20, 30])
def test_twenty_thirty_are_discrete_not_native_extend(final):
    """20/30 must be N discrete Omni Flash 10s SINGLE clips + concat, never a
    native Omni extend (Omni Flash exposes no native extend totals)."""
    from agent.services import video_capability_matrix as cap
    plan = g.resolve_final_duration_plan(final)
    assert plan.assembly == g.DISCRETE_MONTAGE
    assert plan.atomic_seconds == 10
    omni = cap.models_for_single("GOOGLE_FLOW", 10)[0]
    assert omni["key"] == "omni_flash"
    assert not omni.get("extend_totals_s")  # no native extend for Omni Flash


@pytest.mark.parametrize("bad", [5, 12, 14, 32, 40])
def test_unsupported_final_fails_closed(bad):
    with pytest.raises(ValueError) as exc:
        g.resolve_final_duration_plan(bad)
    assert g.ERR_UNSUPPORTED_FINAL_DURATION in str(exc.value)


def test_wps_budget_comes_from_canonical_authority():
    for final, atomic in ((8, 8), (10, 10), (16, 8), (20, 10), (24, 8), (30, 10)):
        plan = g.resolve_final_duration_plan(final)
        expected = canonical.dialogue_word_budget(atomic, "BM_MS", wps_mode="SWEET")
        assert plan.per_block_word_budget == expected
    # diagnostic Malay SWEET anchors (from the authority, not stored here)
    assert canonical.dialogue_word_budget(8, "BM_MS", wps_mode="SWEET") == 22
    assert canonical.dialogue_word_budget(10, "BM_MS", wps_mode="SWEET") == 27


@pytest.mark.parametrize("count", [1, 2, 3])
def test_scene_beats_count_equals_block_count_and_distinct(count):
    beats = g.scene_beats(count)
    assert len(beats) == count
    # every beat's objective + visual_action is distinct
    objectives = [b["objective"] for b in beats]
    actions = [b["visual_action"] for b in beats]
    assert len(set(objectives)) == count
    assert len(set(actions)) == count


@pytest.mark.parametrize("atomic", [8, 10])
def test_micro_beats_four_progressive_scaled(atomic):
    mb = g.micro_beats(atomic)
    assert len(mb) == 4
    # progressive, ends at the atomic duration
    assert mb[0]["start_s"] == 0.0
    assert mb[-1]["end_s"] == float(atomic)
    for i in range(1, 4):
        assert mb[i]["start_s"] >= mb[i - 1]["end_s"] - 0.01


def test_compose_scene_context_contains_grammar_gates():
    ctx = g.compose_scene_context(
        block_index=0, block_count=3, atomic_seconds=8,
        objective="Grab attention and dramatize the problem",
        visual_action="Mascot notices and reacts to camera",
        has_dialogue=True, existing_context="HOOK: energetic. BACKGROUND: kitchen.",
    ).lower()
    # four micro-beats referenced (4 time windows)
    assert ctx.count("s ") >= 4 or ctx.count("–") >= 4
    # >= 3 visual-state changes required
    assert "three" in ctx and "visual" in ctx
    # lip-sync contract present
    assert "mouth" in ctx and "speaker" in ctx and "no frozen smile" in ctx
    # identity lock + product hero + active actor
    assert "packaging" in ctx and "hero" in ctx and "active" in ctx
    # objective + visual action embedded (this is how they reach the compiler)
    assert "dramatize the problem" in ctx
    assert "notices and reacts" in ctx


def test_compose_scene_context_distinct_per_block():
    common = dict(block_count=3, atomic_seconds=8, has_dialogue=True, existing_context="HOOK. BG.")
    beats = g.scene_beats(3)
    ctxs = [
        g.compose_scene_context(block_index=i, objective=beats[i]["objective"],
                                visual_action=beats[i]["visual_action"], **common)
        for i in range(3)
    ]
    assert len(set(ctxs)) == 3  # three materially different prompts


def test_no_dialogue_omits_lipsync_but_keeps_dynamism():
    ctx = g.compose_scene_context(
        block_index=0, block_count=1, atomic_seconds=8,
        objective="arc", visual_action="mascot acts", has_dialogue=False,
    ).lower()
    assert "mouth" not in ctx  # no lip-sync contract when silent
    assert "three" in ctx  # dynamism still required


@pytest.mark.parametrize("block_index,block_count,atomic", [(0, 1, 8), (0, 2, 8), (1, 2, 10), (2, 3, 10)])
def test_compose_scene_context_no_metadata_leakage(block_index, block_count, atomic):
    beats = g.scene_beats(block_count)
    ctx = g.compose_scene_context(
        block_index=block_index, block_count=block_count, atomic_seconds=atomic,
        objective=beats[block_index]["objective"],
        visual_action=beats[block_index]["visual_action"],
        has_dialogue=True, existing_context="HOOK: x. BACKGROUND: y.",
    )
    # canonical leak scrub: no HYBRID/FRAMES/WPS/block_plan/JSON/etc.
    assert scrub_check(ctx) == []
    # metadata scan: no DB columns / product_id / placeholders / enum tokens
    hits = {k: v for k, v in scan_prompt_text(ctx).items() if v}
    assert hits == {}
    # explicit: internal vocabulary never leaks
    low = ctx.lower()
    for banned in ("product_mascot_key_visual", "frames", "start_frame", "source_mode", "wps", "block_plan"):
        assert banned not in low


def test_duration_options_menu_matches_matrix():
    opts = {o["final_seconds"]: o for o in g.duration_options()}
    assert set(opts) == set(_MATRIX)
    assert opts[24]["label"] == "24 seconds · 3 scenes × 8s"
    assert opts[30]["label"] == "30 seconds · 3 scenes × 10s · Omni Flash"
    assert opts[8]["label"] == "8 seconds · 1 scene × 8s"
