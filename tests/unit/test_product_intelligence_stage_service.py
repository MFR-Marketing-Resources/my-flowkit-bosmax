"""Contract tests for the derived Product-Intelligence stage.

The headline predicate ("no approved snapshot") is deliberately NOT changed by this
module, so the tests below pin two things: the ladder itself, and the fact that stage
derivation never invents a state that the underlying draft/snapshot rows do not support.
"""
from __future__ import annotations

import json

import pytest

from agent.services.product_intelligence_stage_service import (
    INTELLIGENCE_STAGES,
    REQUIRED_FIELDS,
    STAGE_APPROVED_SNAPSHOT,
    STAGE_CLAIM_BLOCKED,
    STAGE_CLAIM_REVIEW_REQUIRED,
    STAGE_DRAFT_INCOMPLETE,
    STAGE_NO_DRAFT,
    STAGE_READY_FOR_REVIEW,
    blocked_claim_reasons,
    evaluate_intelligence_stage,
    missing_required_fields,
    stage_sql_case,
)


def _complete_draft(**over):
    draft = {f: "value" for f in REQUIRED_FIELDS}
    draft.update({
        "draft_id": "d1",
        "review_status": "DRAFT",
        "benefits_json": json.dumps(["b"]),
        "usp_json": json.dumps(["u"]),
        "allowed_claims_json": json.dumps(["a"]),
        "buyer_persona_snapshot_json": json.dumps({"k": "v"}),
        "copy_strategy_summary_json": json.dumps({"k": "v"}),
        "source_urls_json": json.dumps({"src": "x"}),
        "image_evidence_json": json.dumps({"img": "x"}),
        "blocked_claims_json": "[]",
        "claim_gate": "PASS",
        "claim_risk_level": "LOW",
    })
    draft.update(over)
    return draft


def test_no_draft_is_the_stage_when_no_draft_row_exists():
    r = evaluate_intelligence_stage(None)
    assert r["intelligence_stage"] == STAGE_NO_DRAFT
    assert r["missing_fields"] == list(REQUIRED_FIELDS)
    assert r["copy_blocked"] is True


def test_approved_snapshot_outranks_every_draft_state():
    # even a blocked draft is not "blocked" once an approved snapshot exists
    r = evaluate_intelligence_stage(
        _complete_draft(claim_gate="BLOCKED"), has_snapshot=True)
    assert r["intelligence_stage"] == STAGE_APPROVED_SNAPSHOT
    assert r["copy_blocked"] is False


def test_claim_gate_not_the_blocked_list_decides_blocked_vs_review_required():
    """Live data holds CLAIM_REVIEW_REQUIRED drafts that ALSO carry blocked_claims_json.
    Inferring "blocked" from that list mislabels them and would send products to a paid
    rewrite they do not need. `claim_gate` is the authoritative verdict."""
    review = evaluate_intelligence_stage(
        _complete_draft(review_status="NEEDS_REVISION",
                        claim_gate="CLAIM_REVIEW_REQUIRED",
                        blocked_claims_json=json.dumps(["cures acne"])))
    assert review["intelligence_stage"] == STAGE_CLAIM_REVIEW_REQUIRED
    # the list still surfaces as human-readable reasons
    assert review["claim_reasons"] == ["cures acne"]

    blocked = evaluate_intelligence_stage(
        _complete_draft(review_status="NEEDS_REVISION", claim_gate="CLAIM_BLOCKED",
                        blocked_claims_json="[]"))
    assert blocked["intelligence_stage"] == STAGE_CLAIM_BLOCKED


@pytest.mark.parametrize("gate", ["BLOCKED", "blocked", "CLAIM_BLOCKED", "FAIL"])
def test_a_blocking_gate_marks_claim_blocked_case_insensitively(gate):
    assert evaluate_intelligence_stage(
        _complete_draft(claim_gate=gate))["intelligence_stage"] == STAGE_CLAIM_BLOCKED


def test_claim_safe_draft_still_needing_revision_is_incomplete_not_claim_flagged():
    """CLAIM_SAFE + NEEDS_REVISION is a completeness problem, not a claim problem, and
    must not be reported as awaiting a CLAIM ruling."""
    assert evaluate_intelligence_stage(
        _complete_draft(review_status="NEEDS_REVISION", claim_gate="CLAIM_SAFE"),
    )["intelligence_stage"] == STAGE_DRAFT_INCOMPLETE


def test_empty_required_field_is_draft_incomplete():
    r = evaluate_intelligence_stage(_complete_draft(usage_text="   "))
    assert r["intelligence_stage"] == STAGE_DRAFT_INCOMPLETE
    assert r["missing_fields"] == ["usage_text"]


@pytest.mark.parametrize("empty", ["", "   ", None, "[]", "{}"])
def test_empty_json_and_blank_text_both_count_as_missing(empty):
    assert "benefits_json" in missing_required_fields(
        _complete_draft(benefits_json=empty))


def test_complete_clean_draft_is_ready_for_review_but_still_copy_blocked():
    r = evaluate_intelligence_stage(_complete_draft(review_status="READY_FOR_REVIEW"))
    assert r["intelligence_stage"] == STAGE_READY_FOR_REVIEW
    assert r["missing_fields"] == []
    # no approved snapshot yet, so the copy lane would still fail closed
    assert r["copy_blocked"] is True
    assert r["approved_snapshot"] is False


def test_ready_for_review_is_not_an_approval():
    """READY_FOR_REVIEW must never imply the human approval fields were set."""
    r = evaluate_intelligence_stage(_complete_draft(review_status="READY_FOR_REVIEW"))
    assert r["approved_snapshot"] is False
    assert "approved_at" not in r and "approved_by" not in r


def test_blocked_claim_reasons_handles_dicts_lists_and_duplicates():
    draft = _complete_draft(blocked_claims_json=json.dumps([
        {"reason": "medical claim"}, "medical claim", {"claim": "guaranteed"},
    ]))
    assert blocked_claim_reasons(draft) == ["medical claim", "guaranteed"]


def test_malformed_claim_json_does_not_raise():
    assert blocked_claim_reasons(_complete_draft(blocked_claims_json="{not json")) == []


def test_sql_case_covers_every_stage_it_claims_and_is_parameterless():
    sql = stage_sql_case("d", "s")
    for stage in (STAGE_APPROVED_SNAPSHOT, STAGE_NO_DRAFT, STAGE_CLAIM_BLOCKED,
                  STAGE_CLAIM_REVIEW_REQUIRED, STAGE_DRAFT_INCOMPLETE,
                  STAGE_READY_FOR_REVIEW):
        assert f"'{stage}'" in sql
    assert "?" not in sql, "the CASE is inlined into a predicate; it must bind no params"


def test_stage_order_is_worst_to_best_and_complete():
    assert INTELLIGENCE_STAGES[0] == STAGE_NO_DRAFT
    assert INTELLIGENCE_STAGES[-1] == STAGE_APPROVED_SNAPSHOT
    assert len(set(INTELLIGENCE_STAGES)) == len(INTELLIGENCE_STAGES)
