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


def test_extend_mode_allows_different_durations_per_block():
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

    assert [block["duration_seconds"] for block in result["prompt_blocks"]] == [15, 6]
    assert [block["shot_count"] for block in result["prompt_blocks"]] == [4, 1]
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
