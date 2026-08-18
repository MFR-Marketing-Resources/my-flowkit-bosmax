"""Regression coverage for the All Products "Freshness" roll-up.

The badge is DISPLAY-ONLY. ``intelligence_status`` is a live, title-driven
auto-recompute whose confidence the ProductTruth reconciliation caps to LOW for
FastMoss rows without a verified raw source anchor — so it reports NEEDS_REVIEW
even for products an operator has fully reviewed. A human VERIFIED taxonomy plus a
resolved creative mapping (mapping_status READY) is the authoritative review
signal and must not be shown STALE. These tests pin that override and its
fail-closed edges without touching the intelligence ``confidence`` the copy /
generation gates consume.
"""

import pytest

from agent.api.products import _freshness_of, _operator_verified_ready


def _row(intelligence_status, review_status=None, mapping_status=None):
    row = {"intelligence_status": intelligence_status}
    if review_status is not None:
        row["strategy_taxonomy"] = {"review_status": review_status}
    if mapping_status is not None:
        row["mapping_status"] = mapping_status
    return row


@pytest.mark.parametrize(
    "row, expected",
    [
        # READY auto-intelligence is always FRESH, override or not.
        (_row("READY"), "FRESH"),
        # The fix: operator VERIFIED the taxonomy AND mapping resolved -> not stale.
        (_row("NEEDS_REVIEW", "VERIFIED", "READY"), "FRESH"),
        (_row("MISSING", "VERIFIED", "READY"), "FRESH"),
        # Genuine gaps survive the override: verified taxonomy but mapping incomplete.
        (_row("NEEDS_REVIEW", "VERIFIED", "BLOCKED"), "STALE"),
        (_row("NEEDS_REVIEW", "VERIFIED", "NEEDS_REVIEW"), "STALE"),
        # Taxonomy not yet human-verified -> still stale even with mapping READY.
        (_row("NEEDS_REVIEW", "REVIEW_REQUIRED", "READY"), "STALE"),
        # Fail-closed: a bounded row missing either signal never fabricates FRESH.
        (_row("NEEDS_REVIEW", None, "READY"), "STALE"),
        (_row("NEEDS_REVIEW", "VERIFIED", None), "STALE"),
        # Unknown auto-status stays UNKNOWN (override only rescues NEEDS_REVIEW/MISSING).
        (_row(""), "UNKNOWN"),
    ],
)
def test_freshness_of_honors_operator_verification(row, expected):
    assert _freshness_of(row) == expected


def test_operator_verified_ready_requires_both_signals():
    assert _operator_verified_ready(
        {"strategy_taxonomy": {"review_status": "VERIFIED"}, "mapping_status": "READY"}
    )
    # Case-insensitive / whitespace tolerant, mirroring the badge's normalization.
    assert _operator_verified_ready(
        {"strategy_taxonomy": {"review_status": " verified "}, "mapping_status": " ready "}
    )
    assert not _operator_verified_ready(
        {"strategy_taxonomy": {"review_status": "VERIFIED"}, "mapping_status": "BLOCKED"}
    )
    assert not _operator_verified_ready({"mapping_status": "READY"})
    assert not _operator_verified_ready({})
