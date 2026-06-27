"""Deterministic engine duration → block-chain policy + WPS enforcement helpers.

This module is the single source of truth for the WPS Blocking Template chaining
rules. It is intentionally pure-Python and deterministic — no LLM, no I/O, no
randomness — so the compiler can resolve a requested *total* video duration into
an exact ordered chain of per-block durations for a given video engine, and so
the compiler can verify the *actual* spoken DIALOG SCRIPT word count against the
reusable WPS budget.

Concepts (kept distinct on purpose):
  * ``engine_duration_target`` — the video ENGINE VENDOR (Grok / Google Flow).
    This is NOT the same as the compiler's existing ``engine_target`` field,
    which carries the engine MODE (F2V / T2V / I2V / IMG). The two must not be
    conflated; this module never touches ``engine_target``.
  * ``total duration`` — the requested length of the whole video. Resolved into
    a chain of per-block durations.
  * ``block duration`` — one segment in the chain. Every block duration produced
    here is a member of the compiler's ALLOWED_BLOCK_DURATIONS_SECONDS set
    (only 6 / 8 / 10 are used by the template), so per-block validation reuses
    ``validate_duration_seconds`` unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from agent.services.prompt_compiler_runtime_config_service import (
    validate_duration_seconds,
)


# Engine vendor identifiers (distinct from engine MODE F2V/T2V/I2V/IMG).
GROK = "GROK"
GOOGLE_FLOW = "GOOGLE_FLOW"
SUPPORTED_ENGINE_DURATION_TARGETS = (GROK, GOOGLE_FLOW)

# Hard ceiling on blocks the *current* operator UI can represent/feed.
# Chains longer than this are still resolved + enforced at the backend, but the
# compiler flags them with a blocker for the unsupported UI path.
LEGACY_UI_MAX_BLOCKS = 2

# WPS status codes emitted per block.
WPS_STATUS_SILENT = "SILENT"          # dialogue disabled — no budget to enforce
WPS_STATUS_PASS = "PASS"              # actual spoken words within budget
WPS_STATUS_OVER_BUDGET = "OVER_BUDGET"  # actual spoken words exceed budget


# WPS Blocking Template — engine → requested total seconds → ordered chains.
# The FIRST chain in each list is the deterministic primary; any further entries
# are documented alternates (only Google Flow 40s has one).
ENGINE_DURATION_CHAINING_POLICY: dict[str, dict[int, list[list[int]]]] = {
    GROK: {
        6: [[6]],
        10: [[10]],
        12: [[6, 6]],
        16: [[10, 6]],
        18: [[6, 6, 6]],
        20: [[10, 10]],
        30: [[10, 10, 10]],
    },
    GOOGLE_FLOW: {
        8: [[8]],
        10: [[10]],
        16: [[8, 8]],
        20: [[10, 10]],
        24: [[8, 8, 8]],
        30: [[10, 10, 10]],
        32: [[8, 8, 8, 8]],
        40: [[10, 10, 10, 10], [8, 8, 8, 8, 8]],
        48: [[8, 8, 8, 8, 8, 8]],
        50: [[10, 10, 10, 10, 10]],
        56: [[8, 8, 8, 8, 8, 8, 8]],
        60: [[10, 10, 10, 10, 10, 10]],
    },
}


def normalize_engine_duration_target(value: str | None) -> str:
    """Normalize an engine vendor identifier, accepting common aliases."""
    candidate = str(value or "").strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "GROK": GROK,
        "XAI": GROK,
        "X_AI": GROK,
        "GOOGLE_FLOW": GOOGLE_FLOW,
        "GOOGLEFLOW": GOOGLE_FLOW,
        "FLOW": GOOGLE_FLOW,
        "GOOGLE": GOOGLE_FLOW,
        "VEO": GOOGLE_FLOW,
    }
    resolved = aliases.get(candidate)
    if resolved is None:
        raise ValueError(f"INVALID_ENGINE_DURATION_TARGET:{candidate}")
    return resolved


def list_supported_total_durations(engine_duration_target: str) -> list[int]:
    """Return the sorted list of valid total durations for an engine."""
    engine = normalize_engine_duration_target(engine_duration_target)
    return sorted(ENGINE_DURATION_CHAINING_POLICY[engine].keys())


def resolve_block_chains(
    engine_duration_target: str,
    requested_total_duration_seconds: int,
) -> list[list[int]]:
    """Return every allowed chain for (engine, total). First entry is primary.

    Raises ``ValueError`` for an unknown engine or an unsupported total.
    """
    engine = normalize_engine_duration_target(engine_duration_target)
    try:
        total = int(requested_total_duration_seconds)
    except (TypeError, ValueError):
        raise ValueError(
            f"INVALID_TOTAL_DURATION_SECONDS:{requested_total_duration_seconds}"
        )
    table = ENGINE_DURATION_CHAINING_POLICY[engine]
    if total not in table:
        raise ValueError(
            f"UNSUPPORTED_ENGINE_DURATION:{engine}:{total}"
        )
    return [list(chain) for chain in table[total]]


def resolve_block_chain(
    engine_duration_target: str,
    requested_total_duration_seconds: int,
) -> list[int]:
    """Resolve (engine, total) → the deterministic primary block chain.

    Every block duration in the returned chain is validated against the
    compiler's ALLOWED_BLOCK_DURATIONS_SECONDS, and the chain is guaranteed to
    sum back to the requested total (defence against a malformed table edit).
    """
    primary = resolve_block_chains(
        engine_duration_target, requested_total_duration_seconds
    )[0]
    for block_duration in primary:
        validate_duration_seconds(block_duration)
    total = int(requested_total_duration_seconds)
    if sum(primary) != total:
        raise ValueError(
            f"CHAIN_SUM_MISMATCH:{engine_duration_target}:{total}:{primary}"
        )
    return primary


# DIALOG SCRIPT lines look like:  Shot 1: "spoken copy here"
# Visual-beat lines (no quote) are intentionally not matched, so they count 0.
_DIALOG_LINE_RE = re.compile(r'Shot\s+\d+:\s*"([^"]*)"')


def count_dialogue_words(engine_prompt_text: str) -> int:
    """Count actual spoken words in the DIALOG SCRIPT of an engine prompt.

    Parses every ``Shot N: "..."`` quoted line and sums the whitespace-split
    word counts. Visual-beat lines and structural text contribute nothing.
    """
    if not engine_prompt_text:
        return 0
    total = 0
    for spoken in _DIALOG_LINE_RE.findall(engine_prompt_text):
        total += len(spoken.split())
    return total


def evaluate_wps_status(actual_word_count: int, dialogue_word_budget: int) -> str:
    """Classify a block's actual spoken word count against its WPS budget.

    ``dialogue_word_budget == 0`` means dialogue is disabled → SILENT.
    """
    if dialogue_word_budget <= 0:
        return WPS_STATUS_SILENT
    if actual_word_count <= dialogue_word_budget:
        return WPS_STATUS_PASS
    return WPS_STATUS_OVER_BUDGET


def evaluate_block_wps(
    *,
    engine_prompt_text: str,
    dialogue_word_budget: int,
) -> dict[str, Any]:
    """Return the per-block WPS enforcement record for one compiled block."""
    actual = count_dialogue_words(engine_prompt_text)
    status = evaluate_wps_status(actual, dialogue_word_budget)
    overage = max(0, actual - dialogue_word_budget) if dialogue_word_budget > 0 else 0
    return {
        "dialogue_word_budget": dialogue_word_budget,
        "actual_dialogue_word_count": actual,
        "wps_status": status,
        "overage_words": overage,
    }
