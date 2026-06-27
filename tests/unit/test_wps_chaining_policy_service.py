"""Tests for the deterministic WPS Blocking Template chaining policy.

Covers every row of the uploaded WPS Blocking Template, invalid combinations,
and the DIALOG SCRIPT word-count / WPS-status helpers.
"""

import pytest

from agent.services.wps_chaining_policy_service import (
    GOOGLE_FLOW,
    GROK,
    WPS_STATUS_OVER_BUDGET,
    WPS_STATUS_PASS,
    WPS_STATUS_SILENT,
    count_dialogue_words,
    evaluate_block_wps,
    evaluate_wps_status,
    list_supported_total_durations,
    normalize_engine_duration_target,
    resolve_block_chain,
    resolve_block_chains,
)


# ── Every row of the WPS Blocking Template ───────────────────────────────────
GROK_ROWS = [
    (6, [6]),
    (10, [10]),
    (12, [6, 6]),
    (16, [10, 6]),
    (18, [6, 6, 6]),
    (20, [10, 10]),
    (30, [10, 10, 10]),
]

GOOGLE_FLOW_ROWS = [
    (8, [8]),
    (10, [10]),
    (16, [8, 8]),
    (20, [10, 10]),
    (24, [8, 8, 8]),
    (30, [10, 10, 10]),
    (32, [8, 8, 8, 8]),
    (40, [10, 10, 10, 10]),
    (48, [8, 8, 8, 8, 8, 8]),
    (50, [10, 10, 10, 10, 10]),
    (56, [8, 8, 8, 8, 8, 8, 8]),
    (60, [10, 10, 10, 10, 10, 10]),
]


@pytest.mark.parametrize("total, expected_chain", GROK_ROWS)
def test_grok_template_row_resolves_to_expected_chain(total, expected_chain):
    assert resolve_block_chain(GROK, total) == expected_chain
    assert sum(expected_chain) == total


@pytest.mark.parametrize("total, expected_chain", GOOGLE_FLOW_ROWS)
def test_google_flow_template_row_resolves_to_expected_chain(total, expected_chain):
    assert resolve_block_chain(GOOGLE_FLOW, total) == expected_chain
    assert sum(expected_chain) == total


def test_google_flow_40s_documents_both_alternate_chains():
    chains = resolve_block_chains(GOOGLE_FLOW, 40)
    assert chains[0] == [10, 10, 10, 10]  # deterministic primary
    assert [8, 8, 8, 8, 8] in chains      # documented alternate
    assert all(sum(chain) == 40 for chain in chains)


def test_primary_chain_is_first_alternate():
    assert resolve_block_chain(GOOGLE_FLOW, 40) == resolve_block_chains(GOOGLE_FLOW, 40)[0]


# ── Invalid engine / duration combinations are rejected ──────────────────────
def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="INVALID_ENGINE_DURATION_TARGET"):
        resolve_block_chain("SORA", 10)


def test_unsupported_total_for_engine_is_rejected():
    with pytest.raises(ValueError, match="UNSUPPORTED_ENGINE_DURATION"):
        resolve_block_chain(GROK, 7)


def test_grok_only_total_rejected_on_google_flow():
    # 6s is a Grok row but not a Google Flow row.
    with pytest.raises(ValueError, match="UNSUPPORTED_ENGINE_DURATION"):
        resolve_block_chain(GOOGLE_FLOW, 6)


def test_google_flow_only_total_rejected_on_grok():
    # 8s is a Google Flow row but not a Grok row.
    with pytest.raises(ValueError, match="UNSUPPORTED_ENGINE_DURATION"):
        resolve_block_chain(GROK, 8)


def test_non_integer_total_is_rejected():
    with pytest.raises(ValueError, match="INVALID_TOTAL_DURATION_SECONDS"):
        resolve_block_chain(GROK, "not-a-number")


# ── Normalization / aliases ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw", ["grok", "GROK", " xAI ", "x-ai"])
def test_grok_aliases_normalize(raw):
    assert normalize_engine_duration_target(raw) == GROK


@pytest.mark.parametrize("raw", ["google flow", "GOOGLE_FLOW", "flow", "veo", "google"])
def test_google_flow_aliases_normalize(raw):
    assert normalize_engine_duration_target(raw) == GOOGLE_FLOW


def test_list_supported_total_durations_is_sorted_and_complete():
    assert list_supported_total_durations(GROK) == [6, 10, 12, 16, 18, 20, 30]
    assert list_supported_total_durations(GOOGLE_FLOW) == [
        8, 10, 16, 20, 24, 30, 32, 40, 48, 50, 56, 60
    ]


# ── DIALOG SCRIPT word counting ──────────────────────────────────────────────
def test_count_dialogue_words_sums_quoted_shot_lines_only():
    engine_text = (
        "Vertical 9:16 handheld. MCU to CU framing.\n"
        "DIALOG SCRIPT (BM_MS):\n"
        '  Shot 1: "Cuba produk ini sekarang"\n'
        "  Shot 2: (visual beat — no spoken line)\n"
        '  Shot 3: "Memang berbaloi"\n'
        "Shot 3: Tight product close-up with premium handling."
    )
    # 4 words (shot 1) + 0 (visual beat) + 2 words (shot 3) = 6
    assert count_dialogue_words(engine_text) == 6


def test_count_dialogue_words_empty_text_is_zero():
    assert count_dialogue_words("") == 0
    assert count_dialogue_words("AUDIO: Silent — no spoken dialogue.") == 0


# ── WPS status grading ───────────────────────────────────────────────────────
def test_evaluate_wps_status_pass_silent_and_over_budget():
    assert evaluate_wps_status(5, 10) == WPS_STATUS_PASS
    assert evaluate_wps_status(10, 10) == WPS_STATUS_PASS  # boundary inclusive
    assert evaluate_wps_status(0, 0) == WPS_STATUS_SILENT
    assert evaluate_wps_status(11, 10) == WPS_STATUS_OVER_BUDGET


def test_evaluate_block_wps_reports_overage():
    record = evaluate_block_wps(
        engine_prompt_text='DIALOG SCRIPT (BM_MS):\n  Shot 1: "satu dua tiga empat lima"',
        dialogue_word_budget=3,
    )
    assert record["actual_dialogue_word_count"] == 5
    assert record["wps_status"] == WPS_STATUS_OVER_BUDGET
    assert record["overage_words"] == 2
