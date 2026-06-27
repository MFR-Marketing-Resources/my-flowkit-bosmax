"""Compiler-level WPS chaining + enforcement integration tests.

Proves that the existing ``compile_ugc_video_prompt`` enforces the WPS Blocking
Template when the new engine-duration params are supplied, exposes the required
enforcement metadata, never lets actual spoken words exceed budget, and leaves
the legacy SINGLE/EXTEND paths unchanged.
"""

import pytest

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
from agent.services.wps_chaining_policy_service import (
    GOOGLE_FLOW,
    GROK,
    WPS_STATUS_PASS,
    WPS_STATUS_SILENT,
)
from tests.unit.test_wps_chaining_policy_service import (
    GOOGLE_FLOW_ROWS,
    GROK_ROWS,
)


def _product():
    return {
        "id": "prod-wps",
        "raw_product_title": "WPS Product",
        "product_display_name": "WPS Product",
    }


def _package():
    return {"mode": "F2V", "claim_safe_rewrite": "Produk ini selesa digunakan setiap hari."}


def _compile(engine, total, **kwargs):
    params = dict(
        product=_product(),
        approved_package=_package(),
        mode="F2V",
        generation_mode="EXTEND",
        target_language="BM_MS",
        engine_duration_target=engine,
        requested_total_duration_seconds=total,
        safe_hook_angles=["Cuba produk ini sekarang."],
        safe_cta_angles=["Dapatkan sekarang."],
    )
    params.update(kwargs)
    return compile_ugc_video_prompt(**params)


# ── Every template row resolves to the right block chain via the compiler ────
@pytest.mark.parametrize("total, expected_chain", GROK_ROWS)
def test_grok_rows_resolve_chain_and_durations(total, expected_chain):
    result = _compile(GROK, total)
    assert result["resolved_block_chain"] == expected_chain
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == expected_chain
    assert result["total_duration_seconds"] == total
    assert result["engine_duration_target"] == GROK
    assert result["requested_total_duration_seconds"] == total
    assert result["resolved_block_chain_source"] == "ENGINE_DURATION_POLICY"


@pytest.mark.parametrize("total, expected_chain", GOOGLE_FLOW_ROWS)
def test_google_flow_rows_resolve_chain_and_durations(total, expected_chain):
    result = _compile(GOOGLE_FLOW, total)
    assert result["resolved_block_chain"] == expected_chain
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == expected_chain
    assert result["total_duration_seconds"] == total


# ── Three-plus block chains are enforced AND flagged for the 2-block UI ───────
def test_three_block_chain_emits_unsupported_ui_blocker():
    result = _compile(GOOGLE_FLOW, 24)  # [8, 8, 8] — 3 blocks
    assert len(result["prompt_blocks"]) == 3
    assert any(
        b.startswith("CHAIN_REQUIRES_MULTI_BLOCK_UI") for b in result["blockers"]
    )


def test_two_block_chain_has_no_unsupported_ui_blocker():
    result = _compile(GROK, 12)  # [6, 6] — 2 blocks, fits legacy UI
    assert len(result["prompt_blocks"]) == 2
    assert not any(
        b.startswith("CHAIN_REQUIRES_MULTI_BLOCK_UI") for b in result["blockers"]
    )


# ── Actual spoken word count never exceeds the per-block budget ──────────────
@pytest.mark.parametrize("total, _chain", GROK_ROWS + GOOGLE_FLOW_ROWS)
def test_actual_word_count_never_exceeds_budget(total, _chain):
    engine = GROK if (total, _chain) in GROK_ROWS else GOOGLE_FLOW
    result = _compile(engine, total)
    budgets = result["dialogue_word_budget_per_block"]
    actuals = result["actual_dialogue_word_count_per_block"]
    statuses = result["wps_status_per_block"]
    assert len(budgets) == len(actuals) == len(statuses) == len(result["prompt_blocks"])
    for actual, budget in zip(actuals, budgets):
        assert actual <= budget
    assert all(s in (WPS_STATUS_PASS, WPS_STATUS_SILENT) for s in statuses)
    # Hard contract: enforcement never emits an over-budget blocker.
    assert not any(b.startswith("WPS_OVER_BUDGET") for b in result["blockers"])


def test_fallback_dialogue_does_not_exceed_budget():
    # No safe copy + empty rewrite forces the BM_MS fallback path.
    result = _compile(
        GOOGLE_FLOW,
        24,
        approved_package={"mode": "F2V", "claim_safe_rewrite": ""},
        claim_safe_rewrite="",
        safe_hook_angles=[],
        safe_cta_angles=[],
    )
    for actual, budget in zip(
        result["actual_dialogue_word_count_per_block"],
        result["dialogue_word_budget_per_block"],
    ):
        assert actual <= budget
    assert all(
        s in (WPS_STATUS_PASS, WPS_STATUS_SILENT)
        for s in result["wps_status_per_block"]
    )


def test_dialogue_disabled_is_silent_with_zero_budget():
    result = _compile(GROK, 12, dialogue_enabled=False)
    assert result["dialogue_word_budget_per_block"] == [0, 0]
    assert result["actual_dialogue_word_count_per_block"] == [0, 0]
    assert result["wps_status_per_block"] == [WPS_STATUS_SILENT, WPS_STATUS_SILENT]


# ── Invalid engine/duration is rejected at the compiler boundary ─────────────
def test_invalid_total_for_engine_raises():
    with pytest.raises(ValueError, match="UNSUPPORTED_ENGINE_DURATION"):
        _compile(GROK, 8)  # 8s is Google-Flow-only


def test_unknown_engine_raises():
    with pytest.raises(ValueError, match="INVALID_ENGINE_DURATION_TARGET"):
        _compile("SORA", 10)


# ── Required existing output structure is preserved ──────────────────────────
def test_compiler_output_structure_preserved_under_chaining():
    result = _compile(GOOGLE_FLOW, 16)
    for key in (
        "final_compiled_prompt_text",
        "prompt_blocks",
        "shot_plan",
        "warnings",
        "blockers",
        "runtime_config_snapshot",
    ):
        assert key in result
    assert isinstance(result["final_compiled_prompt_text"], str)
    assert result["final_compiled_prompt_text"]


# ── Legacy SINGLE / EXTEND paths unchanged when new params absent ────────────
def test_legacy_single_block_unchanged():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=12,
        target_language="BM_MS",
    )
    assert len(result["prompt_blocks"]) == 1
    assert result["prompt_blocks"][0]["shot_count"] == 3
    assert result["dialogue_word_budget_per_block"] == [20]
    # New metadata is present but inert on the legacy path.
    assert result["engine_duration_target"] is None
    assert result["requested_total_duration_seconds"] is None
    assert result["resolved_block_chain_source"] == "LEGACY_BLOCKS"
    assert result["resolved_block_chain"] == [12]


def test_legacy_extend_two_block_unchanged():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_package(),
        mode="F2V",
        generation_mode="EXTEND",
        duration_seconds=8,
        blocks=[
            {"block_index": 1, "duration_seconds": 15},
            {"block_index": 2, "duration_seconds": 6},
        ],
        target_language="EN_US",
    )
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [15, 6]
    assert [b["shot_count"] for b in result["prompt_blocks"]] == [4, 1]
    assert result["total_duration_seconds"] == 21
    assert result["engine_duration_target"] is None
    assert result["resolved_block_chain"] == [15, 6]
    assert result["resolved_block_chain_source"] == "LEGACY_BLOCKS"
