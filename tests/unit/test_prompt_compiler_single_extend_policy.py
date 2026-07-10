import pytest

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt


def _product():
    return {
        "id": "prod-policy",
        "raw_product_title": "Policy Product",
        "product_display_name": "Policy Product",
    }


def _package():
    return {
        "mode": "F2V",
        "claim_safe_rewrite": "Safe policy rewrite",
    }


def test_single_mode_uses_one_block_and_deterministic_shot_policy():
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
    # Workspace entrypoint defaults to SweetWPS for final polished output
    # (Malay SweetWPS 2.7 x 12s = 32 words), not the legacy 1.7 or SafeWPS path.
    assert result["dialogue_word_budget_per_block"] == [32]


def test_extend_manual_block_plan_blocked_in_production():
    # The invalid [15,8]-class raw manual plan must NOT pass as production EXTEND —
    # production EXTEND is total + route-authority driven. Fail closed, no prompt.
    with pytest.raises(ValueError) as exc:
        compile_ugc_video_prompt(
            product=_product(),
            approved_package=_package(),
            mode="F2V",
            generation_mode="EXTEND",
            duration_seconds=8,
            blocks=[
                {"block_index": 1, "duration_seconds": 15},
                {"block_index": 2, "duration_seconds": 8},
            ],
            target_language="EN_US",
        )
    assert "EXTEND_MANUAL_BLOCK_PLAN_BLOCKED_IN_PRODUCTION" in str(exc.value)


def test_extend_manual_block_plan_allowed_under_dev_override():
    # DEV/ADVANCED ONLY: an explicit override honors a raw per-block plan.
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
        allow_manual_block_plan=True,
    )

    assert [block["duration_seconds"] for block in result["prompt_blocks"]] == [15, 6]
    assert result["total_duration_seconds"] == 21


# ── BLOCK-SPLIT fix: a requested TOTAL derives the chain from the workbook
# authority (all video modes share this compiler path), fail-closed on unsupported.

def _extend_total(total: int):
    return compile_ugc_video_prompt(
        product=_product(),
        approved_package=_package(),
        mode="F2V",
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=total,
        target_language="BM_MS",
    )


def test_extend_google_flow_16_emits_two_blocks_8_8():
    result = _extend_total(16)
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8]
    assert result["prompt_blocks"][0]["block_role"] == "ANCHOR"
    assert result["prompt_blocks"][1]["block_role"] == "CONTINUATION"
    assert result["total_duration_seconds"] == 16


def test_extend_google_flow_24_emits_three_blocks_8_8_8():
    result = _extend_total(24)
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8, 8]
    assert result["total_duration_seconds"] == 24


def test_extend_google_flow_32_emits_four_blocks_8_8_8_8():
    result = _extend_total(32)
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8, 8, 8]
    assert result["total_duration_seconds"] == 32


def test_extend_google_flow_15_fails_closed():
    with pytest.raises(ValueError) as exc:
        _extend_total(15)
    assert "UNSUPPORTED_EXTEND_TOTAL_DURATION_15" in str(exc.value)


def test_requested_total_overrides_raw_blocks():
    # Raw blocks[] must NOT win over the workbook authority when a total is given
    # (this is exactly the cap-at-2-blocks bug: the UI always sent 2 raw blocks).
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_package(),
        mode="F2V",
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        blocks=[
            {"block_index": 1, "duration_seconds": 10},
            {"block_index": 2, "duration_seconds": 10},
        ],
        target_language="BM_MS",
    )
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8]


# ── ROUTE-AWARE authority: production block plans come from an AUTHORIZED route;
# routes without captured runtime evidence fail closed (owner decision 2026-07-10).

def test_extend_route_missing_authority_fails_closed():
    # GOOGLE_FLOW_VEO_EXTEND (public-API 8+7n) has NO captured Flow runtime evidence.
    with pytest.raises(ValueError) as exc:
        compile_ugc_video_prompt(
            product=_product(),
            approved_package=_package(),
            mode="F2V",
            generation_mode="EXTEND",
            route="GOOGLE_FLOW_VEO_EXTEND",
            engine_duration_target="GOOGLE_FLOW",
            requested_total_duration_seconds=16,
            target_language="BM_MS",
        )
    assert "ROUTE_DURATION_AUTHORITY_MISSING" in str(exc.value)
    assert "GOOGLE_FLOW_VEO_EXTEND" in str(exc.value)


@pytest.mark.parametrize(
    "mode,source_mode",
    [("F2V", None), ("T2V", None), ("F2V", "HYBRID"), ("I2V", None)],
)
def test_all_video_modes_share_route_planner_total_16(mode, source_mode):
    # F2V / T2V / HYBRID (compiles as an F2V job) / I2V all derive the SAME
    # authority-backed plan from the SAME route planner.
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_package(),
        mode=mode,
        source_mode=source_mode,
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        target_language="BM_MS",
    )
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8]


def test_extend_blocks_carry_storyboard_timeline_and_final_flag():
    result = _extend_total(24)
    blocks = result["prompt_blocks"]
    assert [(b["start_s"], b["end_s"]) for b in blocks] == [(0, 8), (8, 16), (16, 24)]
    assert [b["is_final"] for b in blocks] == [False, False, True]
