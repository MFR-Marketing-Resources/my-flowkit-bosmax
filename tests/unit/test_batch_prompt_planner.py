"""Contracts for the Batch Prompt Planner (prompt/production split).

Pure-function tests: mode input law, variation planning determinism,
fingerprints, and anti-redundancy hard blocks / soft warnings.
"""
from agent.services import batch_prompt_planner as planner


# ── Mode law ──────────────────────────────────────────────────────────────


def test_logical_modes_are_the_four_video_modes():
    assert planner.LOGICAL_MODES == ("T2V", "HYBRID", "F2V", "I2V")


def test_hybrid_keeps_logical_identity_but_rides_f2v_engine_lane():
    assert planner.ENGINE_MODES["HYBRID"] == "F2V"
    assert planner.EXECUTION_LANES["HYBRID"] == "PRODUCT_ANCHOR_PRESENTER"


def test_execution_lanes_cover_every_logical_mode():
    assert set(planner.EXECUTION_LANES) == set(planner.LOGICAL_MODES)
    assert set(planner.ENGINE_MODES) == set(planner.LOGICAL_MODES)


# ── Mode input contracts ──────────────────────────────────────────────────

_PRODUCT_WITH_IMAGE = {"image_url": "http://example.com/p.jpg"}


def test_unsupported_mode_is_rejected():
    errors = planner.validate_mode_inputs("IMG")
    assert errors == ["UNSUPPORTED_LOGICAL_MODE:IMG"]


def test_t2v_forbids_image_slots():
    errors = planner.validate_mode_inputs(
        "T2V", character_asset_ids=["a1"], product_row=_PRODUCT_WITH_IMAGE,
    )
    assert "T2V_FORBIDS_IMAGE_SLOTS" in errors


def test_t2v_text_only_is_legal_without_any_assets():
    assert planner.validate_mode_inputs("T2V", product_row=None) == []


def test_hybrid_requires_product_anchor():
    errors = planner.validate_mode_inputs("HYBRID", product_row={})
    assert "HYBRID_REQUIRES_PRODUCT_ANCHOR" in errors
    assert planner.validate_mode_inputs("HYBRID", product_row=_PRODUCT_WITH_IMAGE) == []


def test_f2v_requires_exactly_the_finished_frame_and_no_role_slots():
    errors = planner.validate_mode_inputs("F2V", product_row=_PRODUCT_WITH_IMAGE)
    assert "F2V_REQUIRES_FINISHED_FRAME" in errors
    errors = planner.validate_mode_inputs(
        "F2V",
        finished_frame_asset_id="frame-1",
        character_asset_ids=["a1"],
        product_row=_PRODUCT_WITH_IMAGE,
    )
    assert "F2V_FORBIDS_SEPARATE_ROLE_SLOTS" in errors
    assert planner.validate_mode_inputs(
        "F2V", finished_frame_asset_id="frame-1", product_row=_PRODUCT_WITH_IMAGE,
    ) == []


def test_i2v_requires_avatar_and_product_references():
    errors = planner.validate_mode_inputs("I2V", product_row={})
    assert "I2V_REQUIRES_AVATAR_REFERENCE" in errors
    assert "I2V_REQUIRES_PRODUCT_REFERENCE" in errors
    assert planner.validate_mode_inputs(
        "I2V", character_asset_ids=["a1"], product_row=_PRODUCT_WITH_IMAGE,
    ) == []


def test_quantity_bounds_are_enforced():
    assert "QUANTITY_OUT_OF_RANGE:1-100" in planner.validate_mode_inputs(
        "T2V", quantity=0,
    )
    assert "QUANTITY_OUT_OF_RANGE:1-100" in planner.validate_mode_inputs(
        "T2V", quantity=101,
    )


def test_unknown_variation_strategy_is_rejected():
    errors = planner.validate_mode_inputs("T2V", variation_strategy="RANDOM_CHAOS")
    assert any(e.startswith("UNSUPPORTED_VARIATION_STRATEGY") for e in errors)


# ── Variation planning ────────────────────────────────────────────────────


def _plans(**overrides):
    kwargs = dict(
        logical_mode="HYBRID",
        variation_strategy="SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        quantity=10,
        product_id="prod-1",
        avatar_codes=["BOS_A", "BOS_B", "BOS_C"],
        hook_angles=["hook one", "hook two"],
    )
    kwargs.update(overrides)
    return planner.plan_batch_items(**kwargs)


def test_qty_10_yields_10_item_plans():
    assert len(_plans()) == 10


def test_planning_is_deterministic_for_same_inputs():
    assert _plans() == _plans()


def test_avatar_rotation_is_round_robin_over_the_pool():
    plans = _plans()
    codes = [p["avatar_code"] for p in plans]
    assert set(codes) == {"BOS_A", "BOS_B", "BOS_C"}
    # Fair share: 10 items over 3 avatars → max 4 uses each
    assert max(codes.count(c) for c in set(codes)) <= 4


def test_same_script_strategy_pins_one_hook_for_all_items():
    plans = _plans(variation_strategy="SAME_SCRIPT_DIFF_VISUALS")
    hooks = {p["hook_override"] for p in plans}
    assert len(hooks) == 1


def test_diff_dialogue_strategy_rotates_hooks():
    plans = _plans()
    hooks = {p["hook_override"] for p in plans}
    assert hooks == {"hook one", "hook two"}


def test_i2v_plans_rotate_character_scene_style_slots():
    plans = planner.plan_batch_items(
        logical_mode="I2V",
        variation_strategy="DIFF_SCRIPT_DIFF_VISUALS",
        quantity=4,
        product_id="prod-1",
        character_asset_ids=["c1", "c2"],
        scene_asset_ids=["s1"],
    )
    assert {p["character_asset_id"] for p in plans} == {"c1", "c2"}
    assert all(p["scene_asset_id"] == "s1" for p in plans)


def test_f2v_plans_carry_the_single_finished_frame():
    plans = planner.plan_batch_items(
        logical_mode="F2V",
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=3,
        product_id="prod-1",
        finished_frame_asset_id="frame-9",
    )
    assert all(p["finished_frame_asset_id"] == "frame-9" for p in plans)
    assert all(p["avatar_code"] is None for p in plans if "avatar_code" in p)


# ── Fingerprints ──────────────────────────────────────────────────────────

_PROMPT = """SECTION 1 - ROLE & OBJECTIVE
Role text.
SECTION 6 - SPOKEN DIALOGUE
Wah murahnya minyak ni! Cuba sekali terus jatuh cinta.
SECTION 7 - VOICE & DELIVERY
Calm delivery.
"""


def test_extract_dialogue_pulls_section_6_only():
    dialogue = planner.extract_dialogue(_PROMPT)
    assert "murahnya" in dialogue
    assert "Role text" not in dialogue
    assert "Calm delivery" not in dialogue


def test_prompt_fingerprint_is_whitespace_and_case_insensitive():
    a = planner.compute_fingerprints(
        final_prompt_text="Hello   WORLD", item_plan={},
    )
    b = planner.compute_fingerprints(
        final_prompt_text="hello world", item_plan={},
    )
    assert a["prompt_fingerprint"] == b["prompt_fingerprint"]


def test_fingerprints_include_avatar_scene_hook_and_role_map():
    fp = planner.compute_fingerprints(
        final_prompt_text=_PROMPT,
        item_plan={"avatar_code": "BOS_A", "scene_context_override": "kitchen"},
        resolved_engine_slots={"start_frame": "asset-1", "end_frame": None},
    )
    for key in (
        "prompt_fingerprint", "dialogue_fingerprint", "hook_fingerprint",
        "avatar_fingerprint", "scene_fingerprint", "asset_role_map_fingerprint",
    ):
        assert fp[key], key


# ── Anti-redundancy ───────────────────────────────────────────────────────


def _fp(prompt="p1", avatar="A", scene="S", hook="H"):
    return {
        "prompt_fingerprint": planner._sha1(prompt),
        "dialogue_fingerprint": planner._sha1(prompt + "d"),
        "hook_fingerprint": planner._sha1(hook),
        "avatar_fingerprint": planner._sha1(avatar),
        "scene_fingerprint": planner._sha1(scene),
        "asset_role_map_fingerprint": planner._sha1("{}"),
        "dialogue_text_norm": prompt,
    }


def test_duplicate_prompt_in_history_is_hard_blocked():
    fp = _fp("same prompt")
    hard, _ = planner.check_redundancy(
        fingerprints=fp, batch_seen=[],
        history_fingerprints={fp["prompt_fingerprint"]},
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=10, rotation_pool_size=3,
    )
    assert "DUPLICATE_PROMPT_FINGERPRINT_IN_HISTORY" in hard


def test_duplicate_prompt_in_batch_is_hard_blocked():
    fp = _fp("same prompt")
    hard, _ = planner.check_redundancy(
        fingerprints=fp, batch_seen=[_fp("same prompt")],
        history_fingerprints=set(),
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=10, rotation_pool_size=3,
    )
    assert "DUPLICATE_PROMPT_FINGERPRINT_IN_BATCH" in hard


def test_same_avatar_scene_hook_combo_is_hard_blocked():
    hard, _ = planner.check_redundancy(
        fingerprints=_fp("p2", avatar="A", scene="S", hook="H"),
        batch_seen=[_fp("p1", avatar="A", scene="S", hook="H")],
        history_fingerprints=set(),
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=10, rotation_pool_size=3,
    )
    assert "DUPLICATE_AVATAR_SCENE_HOOK_COMBO_IN_BATCH" in hard


def test_avatar_overuse_yields_soft_warning_not_block():
    seen = [_fp(f"p{i}", avatar="A", scene=f"S{i}", hook=f"H{i}") for i in range(5)]
    hard, soft = planner.check_redundancy(
        fingerprints=_fp("p9", avatar="A", scene="S9", hook="H9"),
        batch_seen=seen,
        history_fingerprints=set(),
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=10, rotation_pool_size=5,
    )
    assert not hard
    assert any(w.startswith("AVATAR_OVERUSED_IN_BATCH") for w in soft)


def test_near_identical_dialogue_warns_when_strategy_demands_difference():
    a = _fp("beli sekarang sebelum habis stok kawan kawan semua")
    b = _fp("beli sekarang sebelum habis stok kawan kawan semua ya")
    b["avatar_fingerprint"] = planner._sha1("B")
    hard, soft = planner.check_redundancy(
        fingerprints=b, batch_seen=[a],
        history_fingerprints=set(),
        variation_strategy="SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        quantity=10, rotation_pool_size=3,
    )
    assert any(w.startswith("DIALOGUE_TOO_SIMILAR") for w in soft)


def test_identical_dialogue_is_fine_under_same_script_strategy():
    a = _fp("dialog sama", avatar="A", scene="S1", hook="H")
    b = _fp("dialog sama beza visual", avatar="B", scene="S2", hook="H")
    _, soft = planner.check_redundancy(
        fingerprints=b, batch_seen=[a],
        history_fingerprints=set(),
        variation_strategy="SAME_SCRIPT_DIFF_VISUALS",
        quantity=10, rotation_pool_size=3,
    )
    assert not any(w.startswith("DIALOGUE_TOO_SIMILAR") for w in soft)
