"""COPY-FINAL-B01/B02 — copy set validity authority unit tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agent.models.copy_set import (
    APPROVAL_PHRASE,
    STATUS_COPY_APPROVED,
    STATUS_COPY_REJECTED,
    STATUS_COPY_REVIEW_REQUIRED,
    STATUS_DRAFT_COPY,
)
from agent.services.copy_set_validity_service import (
    CLASS_APPROVED_COPY_STALE,
    CLASS_APPROVED_COPY_VALID,
    CLASS_COPY_REVIEW_REQUIRED_ONLY,
    CLASS_DRAFT_COPY_ONLY,
    CLASS_MISSING_COPY,
    CLASS_REJECTED_COPY_ONLY,
    classify_product_copy,
    evaluate_copy_set_validity,
    product_copy_classification,
    stamp_copy_set_pi_lineage,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_set(**kw):
    row = {
        "copy_set_id": "cs-1",
        "product_id": "p1",
        "status": STATUS_COPY_APPROVED,
        "archived": 0,
        "pi_eligibility_status": None,
        "claim_review": {
            "completeness": {"complete": True},
            "safety": {"safe": True},
        },
        "pi_snapshot_id": "snap-1",
        "pi_snapshot_version": 1,
        "pi_grounding_digest": "digest-1",
    }
    row.update(kw)
    return row


def test_draft_does_not_count_as_valid():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(status=STATUS_DRAFT_COPY),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False
    assert any("STATUS_NOT_APPROVED" in r for r in v["reasons"])


def test_review_required_does_not_count():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(status=STATUS_COPY_REVIEW_REQUIRED),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False


def test_rejected_does_not_count():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(status=STATUS_COPY_REJECTED),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False


def test_pi_ineligible_does_not_count():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(pi_eligibility_status="PI_INELIGIBLE"),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False
    assert any("QUARANTINED" in r for r in v["reasons"])


def test_needs_revalidation_does_not_count():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(pi_eligibility_status="NEEDS_REVALIDATION"),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False


def test_blocked_does_not_count():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(pi_eligibility_status="BLOCKED"),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False


def test_valid_current_approved_closes():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is True
    assert v["reasons"] == []


def test_stale_and_valid_prefers_valid():
    valid = evaluate_copy_set_validity(
        copy_set=_base_set(copy_set_id="good"),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    stale = evaluate_copy_set_validity(
        copy_set=_base_set(copy_set_id="stale", pi_snapshot_id="old"),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    raw = [
        {"status": STATUS_COPY_APPROVED, "archived": 0, "copy_set_id": "stale"},
        {"status": STATUS_COPY_APPROVED, "archived": 0, "copy_set_id": "good"},
    ]
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[stale, valid],
        raw_sets=raw,
    )
    assert c["classification"] == CLASS_APPROVED_COPY_VALID
    assert c["valid_copy_set_id"] == "good"


def test_missing_lineage_is_stale():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(pi_snapshot_id=None, pi_grounding_digest=None),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    assert v["valid"] is False
    assert any("MISSING_PI_LINEAGE" in r for r in v["reasons"])
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[v],
        raw_sets=[{"status": STATUS_COPY_APPROVED, "archived": 0}],
    )
    assert c["classification"] == CLASS_APPROVED_COPY_STALE


def test_review_only_classification():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(status=STATUS_COPY_REVIEW_REQUIRED),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[v],
        raw_sets=[{"status": STATUS_COPY_REVIEW_REQUIRED, "archived": 0}],
    )
    assert c["classification"] == CLASS_COPY_REVIEW_REQUIRED_ONLY


def test_draft_only_classification():
    v = evaluate_copy_set_validity(
        copy_set=_base_set(status=STATUS_DRAFT_COPY),
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
    )
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[v],
        raw_sets=[{"status": STATUS_DRAFT_COPY, "archived": 0}],
    )
    assert c["classification"] == CLASS_DRAFT_COPY_ONLY


def test_rejected_only_and_missing():
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[],
        raw_sets=[{"status": STATUS_COPY_REJECTED, "archived": 0}],
    )
    assert c["classification"] == CLASS_REJECTED_COPY_ONLY
    c2 = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[],
        raw_sets=[],
    )
    assert c2["classification"] == CLASS_MISSING_COPY
