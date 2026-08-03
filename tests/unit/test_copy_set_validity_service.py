"""COPY-CORRECTIVE-B02/B03 — FAIL-CLOSED copy set validity authority unit tests.

Strict contract: a Copy Set is valid ONLY when every applicable piece of evidence
is PRESENT and passes — completeness, safety, semantic-review receipt, PI lineage,
non-generic, and any open formula/sales gate cleared or per-gate overridden.
"""
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
    CLASS_APPROVED_COPY_GENERIC,
    CLASS_APPROVED_COPY_INCOMPLETE,
    CLASS_APPROVED_COPY_INVALID_LINEAGE,
    CLASS_APPROVED_COPY_MISSING_REVIEW,
    CLASS_APPROVED_COPY_STALE,
    CLASS_APPROVED_COPY_UNSAFE,
    CLASS_APPROVED_COPY_VALID,
    CLASS_COPY_REVIEW_REQUIRED_ONLY,
    CLASS_DRAFT_COPY_ONLY,
    CLASS_MISSING_COPY,
    CLASS_REJECTED_COPY_ONLY,
    classify_product_copy,
    detect_generic_copy,
    evaluate_copy_set_validity,
    validate_semantic_review_receipt,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _receipt(**kw):
    r = {
        "reviewer": "corrective-mission-coordinator",
        "reviewed_at": _now(),
        "decision": "APPROVED",
        "rationale": "Product-specific angle/hook grounded on current PI; USPs mapped.",
        "pi_snapshot_id": "snap-1",
        "authority_digest": "digest-1",
        # COPY-CORRECTIVE-B1: real grounding evidence + genericness verdict.
        "genericness": {"generic": False, "hits": []},
        "grounding": {
            "grounded": True,
            "overlap_count": 3,
            "hook_grounded": True,
            "usp_grounding": [{"usp": "x", "grounded": True}],
        },
    }
    r.update(kw)
    return r


def _na(route="TEST_DETERMINISTIC"):
    """A durable NOT_APPLICABLE formula/sales verdict (B2)."""
    return {"applicable": False, "reason": "deterministic lane", "route": route,
            "evaluator": "test", "evaluated_at": _now()}


def _base_set(**kw):
    """A fully-valid strict set: approved, complete, safe, reviewed, grounded."""
    claim = {
        "completeness": {"complete": True},
        "safety": {"safe": True},
        "semantic_review": _receipt(),
        "formula_validation": _na(),
        "sales_clarity": _na(),
    }
    if "claim_review" in kw:
        claim = kw.pop("claim_review")
    row = {
        "copy_set_id": "cs-1",
        "product_id": "p1",
        "status": STATUS_COPY_APPROVED,
        "archived": 0,
        "pi_eligibility_status": None,
        "hook": "Kulit lembap sepanjang hari tanpa rasa berminyak",
        "subhook": "Formula ringan menyerap cepat untuk kulit kombinasi",
        "cta": "Dapatkan sekarang",
        "usp_set": ["Menyerap dalam 10 saat", "Untuk kulit kombinasi", "Tanpa alkohol"],
        "claim_review": claim,
        "pi_snapshot_id": "snap-1",
        "pi_snapshot_version": 1,
        "pi_grounding_digest": "digest-1",
    }
    row.update(kw)
    return row


def _eval(cs, **kw):
    args = dict(
        copy_set=cs,
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
        product_name="Serum X",
    )
    args.update(kw)
    return evaluate_copy_set_validity(**args)


# ── Status / quarantine gates ────────────────────────────────────────────────
def test_draft_does_not_count_as_valid():
    v = _eval(_base_set(status=STATUS_DRAFT_COPY))
    assert v["valid"] is False
    assert any("STATUS_NOT_APPROVED" in r for r in v["reasons"])


def test_review_required_does_not_count():
    assert _eval(_base_set(status=STATUS_COPY_REVIEW_REQUIRED))["valid"] is False


def test_rejected_does_not_count():
    assert _eval(_base_set(status=STATUS_COPY_REJECTED))["valid"] is False


def test_pi_ineligible_does_not_count():
    v = _eval(_base_set(pi_eligibility_status="PI_INELIGIBLE"))
    assert v["valid"] is False
    assert any("QUARANTINED" in r for r in v["reasons"])


def test_needs_revalidation_does_not_count():
    assert _eval(_base_set(pi_eligibility_status="NEEDS_REVALIDATION"))["valid"] is False


def test_blocked_does_not_count():
    assert _eval(_base_set(pi_eligibility_status="BLOCKED"))["valid"] is False


# ── FAIL-CLOSED evidence gates (missing evidence must fail) ───────────────────
def test_valid_current_approved_closes():
    v = _eval(_base_set())
    assert v["valid"] is True, v["reasons"]
    assert v["reasons"] == []


def test_missing_completeness_verdict_fails_closed():
    v = _eval(_base_set(claim_review={"safety": {"safe": True}, "semantic_review": _receipt()}))
    assert v["valid"] is False
    assert any("MISSING_COMPLETENESS_VERDICT" in r for r in v["reasons"])


def test_missing_safety_verdict_fails_closed():
    v = _eval(_base_set(claim_review={"completeness": {"complete": True}, "semantic_review": _receipt()}))
    assert v["valid"] is False
    assert any("MISSING_SAFETY_VERDICT" in r for r in v["reasons"])


def test_incomplete_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": False}, "safety": {"safe": True}, "semantic_review": _receipt(),
    }))
    assert v["valid"] is False
    assert "INCOMPLETE" in v["reasons"]


def test_unsafe_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": False}, "semantic_review": _receipt(),
    }))
    assert v["valid"] is False
    assert "UNSAFE" in v["reasons"]


def test_missing_semantic_review_fails_closed():
    v = _eval(_base_set(claim_review={"completeness": {"complete": True}, "safety": {"safe": True}}))
    assert v["valid"] is False
    assert any("SEMANTIC_REVIEW_MISSING" in r for r in v["reasons"])


def test_semantic_review_missing_reviewer_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(reviewer=""),
    }))
    assert v["valid"] is False
    assert any("NO_REVIEWER" in r for r in v["reasons"])


def test_semantic_review_stale_lineage_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(pi_snapshot_id="old-snap"),
    }))
    assert v["valid"] is False
    assert any("SEMANTIC_REVIEW_STALE_LINEAGE" in r for r in v["reasons"])


# ── Generic / synthetic detector ─────────────────────────────────────────────
def test_generic_filler_hook_fails():
    v = _eval(_base_set(hook="Identiti jelas Serum X", subhook="Nilai yang mudah difahami"))
    assert v["valid"] is False
    assert any(r.startswith("GENERIC") for r in v["reasons"])


def test_numbered_synthetic_usp_fails():
    v = _eval(_base_set(usp_set=["Kelebihan Serum X #1", "Kelebihan Serum X #2", "Kelebihan Serum X #3"]))
    assert v["valid"] is False
    assert any(r.startswith("GENERIC") for r in v["reasons"])


def test_product_name_only_usp_fails():
    v = _eval(_base_set(usp_set=["Serum X", "Serum X.", "Serum X #1"]), product_name="Serum X")
    assert v["valid"] is False
    assert any(r.startswith("GENERIC") for r in v["reasons"])


def test_detect_generic_is_explainable():
    d = detect_generic_copy(hook="dibina untuk keperluan sebenar", usp_list=["Sesuai untuk rutin harian"])
    assert d["generic"] is True
    assert d["hits"]


def test_specific_copy_not_generic():
    d = detect_generic_copy(
        hook="Kulit lembap 12 jam",
        usp_list=["SPF 30", "Vitamin C 10%", "Untuk kulit sensitif"],
        product_name="Serum X",
    )
    assert d["generic"] is False


# ── Override scoping (defect #4): per-gate only, never bypasses safety ────────
def _claim_open_formula_sales(**over):
    return {
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(),
        "formula_validation": {"valid": False},
        "sales_clarity": {"clear": False},
        "approval_override": over or {},
    }


def test_formula_override_bypasses_formula_only():
    v = _eval(_base_set(claim_review=_claim_open_formula_sales(
        formula_review_overridden=True, reason="operator reviewed", by="faris")))
    assert "FORMULA_MISSING_OR_OPEN" not in v["reasons"]
    # sales gate still open (not overridden)
    assert "SALES_CLARITY_MISSING_OR_OPEN" in v["reasons"]


def test_formula_override_does_not_bypass_safety():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": False},
        "semantic_review": _receipt(),
        "formula_validation": {"valid": False},
        "approval_override": {"formula_review_overridden": True, "reason": "x", "by": "faris"},
    }))
    assert "UNSAFE" in v["reasons"]


def test_bare_override_object_does_not_bypass_any_gate():
    # A non-empty approval_override that lacks the exact flag / reason / by must NOT bypass.
    v = _eval(_base_set(claim_review=_claim_open_formula_sales(some_unrelated_flag=True)))
    assert "FORMULA_MISSING_OR_OPEN" in v["reasons"]
    assert "SALES_CLARITY_MISSING_OR_OPEN" in v["reasons"]


def test_override_without_reason_is_rejected():
    v = _eval(_base_set(claim_review=_claim_open_formula_sales(
        formula_review_overridden=True, by="faris")))  # no reason
    assert "FORMULA_MISSING_OR_OPEN" in v["reasons"]


def test_sales_override_bypasses_sales_only():
    v = _eval(_base_set(claim_review=_claim_open_formula_sales(
        sales_clarity_overridden=True, reason="clear enough", by="faris")))
    assert "SALES_CLARITY_MISSING_OR_OPEN" not in v["reasons"]
    assert "FORMULA_MISSING_OR_OPEN" in v["reasons"]


# ── Lineage ──────────────────────────────────────────────────────────────────
def test_missing_lineage_is_invalid_lineage():
    v = _eval(_base_set(pi_snapshot_id=None, pi_grounding_digest=None))
    assert v["valid"] is False
    assert any("MISSING_PI_LINEAGE" in r for r in v["reasons"])
    c = classify_product_copy(
        product_eligible=True, product_eligibility_reasons=[],
        set_verdicts=[v], raw_sets=[{"status": STATUS_COPY_APPROVED, "archived": 0, "copy_set_id": "cs-1"}],
    )
    assert c["classification"] == CLASS_APPROVED_COPY_INVALID_LINEAGE


def test_stale_snapshot_mismatch():
    v = _eval(_base_set(pi_snapshot_id="old"))
    assert v["valid"] is False
    assert any("PI_SNAPSHOT_MISMATCH" in r for r in v["reasons"])


# ── Reason-aware classification (defect #7) ──────────────────────────────────
def _raw(cid="cs-1", status=STATUS_COPY_APPROVED, archived=0):
    return {"copy_set_id": cid, "status": status, "archived": archived}


def test_unsafe_classified_unsafe_not_stale():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": False}, "semantic_review": _receipt(),
    }))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw()])
    assert c["classification"] == CLASS_APPROVED_COPY_UNSAFE


def test_generic_classified_generic():
    v = _eval(_base_set(hook="Identiti jelas Serum X"))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw()])
    assert c["classification"] == CLASS_APPROVED_COPY_GENERIC


def test_incomplete_classified_incomplete():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": False}, "safety": {"safe": True}, "semantic_review": _receipt(),
    }))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw()])
    assert c["classification"] == CLASS_APPROVED_COPY_INCOMPLETE


def test_missing_review_classified_missing_review():
    v = _eval(_base_set(claim_review={"completeness": {"complete": True}, "safety": {"safe": True}}))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw()])
    assert c["classification"] == CLASS_APPROVED_COPY_MISSING_REVIEW


def test_one_valid_set_closes_product_despite_invalid_rows():
    good = _eval(_base_set(copy_set_id="good"))
    generic = _eval(_base_set(copy_set_id="bad", hook="Identiti jelas Serum X"))
    c = classify_product_copy(
        product_eligible=True, product_eligibility_reasons=[],
        set_verdicts=[generic, good],
        raw_sets=[_raw("bad"), _raw("good")],
    )
    assert c["classification"] == CLASS_APPROVED_COPY_VALID
    assert c["valid_copy_set_id"] == "good"


def test_review_only_classification():
    v = _eval(_base_set(status=STATUS_COPY_REVIEW_REQUIRED))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw(status=STATUS_COPY_REVIEW_REQUIRED)])
    assert c["classification"] == CLASS_COPY_REVIEW_REQUIRED_ONLY


def test_draft_only_classification():
    v = _eval(_base_set(status=STATUS_DRAFT_COPY))
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[v], raw_sets=[_raw(status=STATUS_DRAFT_COPY)])
    assert c["classification"] == CLASS_DRAFT_COPY_ONLY


def test_rejected_only_and_missing():
    c = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                              set_verdicts=[], raw_sets=[_raw(status=STATUS_COPY_REJECTED)])
    assert c["classification"] == CLASS_REJECTED_COPY_ONLY
    c2 = classify_product_copy(product_eligible=True, product_eligibility_reasons=[],
                               set_verdicts=[], raw_sets=[])
    assert c2["classification"] == CLASS_MISSING_COPY


# ── Semantic review receipt validator (unit) ─────────────────────────────────
def test_receipt_validator_requires_fields():
    assert validate_semantic_review_receipt(None, current_snapshot_id="s", current_authority_digest="d")["ok"] is False
    ok = validate_semantic_review_receipt(
        _receipt(pi_snapshot_id="s", authority_digest="d"),
        current_snapshot_id="s", current_authority_digest="d",
    )
    assert ok["ok"] is True


# ── COPY-CORRECTIVE B1: grounding evidence in the receipt ─────────────────────
def test_receipt_without_grounding_evidence_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "formula_validation": _na(), "sales_clarity": _na(),
        "semantic_review": _receipt(grounding={}),
    }))
    assert v["valid"] is False
    assert any("SEMANTIC_REVIEW_NOT_GROUNDED" in r for r in v["reasons"])


def test_receipt_genericness_unverified_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "formula_validation": _na(), "sales_clarity": _na(),
        "semantic_review": _receipt(genericness={}),
    }))
    assert v["valid"] is False
    assert any("GENERICNESS_UNVERIFIED" in r for r in v["reasons"])


def test_receipt_validator_requires_grounding_and_genericness():
    from agent.services.copy_set_validity_service import validate_semantic_review_receipt
    ok = validate_semantic_review_receipt(
        _receipt(pi_snapshot_id="s", authority_digest="d"),
        current_snapshot_id="s", current_authority_digest="d")
    assert ok["ok"] is True
    bad = validate_semantic_review_receipt(
        _receipt(pi_snapshot_id="s", authority_digest="d", grounding={"grounded": False}),
        current_snapshot_id="s", current_authority_digest="d")
    assert bad["ok"] is False


# ── COPY-CORRECTIVE B2: formula / sales-clarity presence ──────────────────────
def test_missing_formula_verdict_fails_closed():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(), "sales_clarity": _na(),
    }))
    assert v["valid"] is False
    assert "FORMULA_MISSING_OR_OPEN" in v["reasons"]


def test_missing_sales_verdict_fails_closed():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(), "formula_validation": _na(),
    }))
    assert v["valid"] is False
    assert "SALES_CLARITY_MISSING_OR_OPEN" in v["reasons"]


def test_durable_not_applicable_passes_and_passing_verdicts_pass():
    assert _eval(_base_set())["valid"] is True  # base uses durable NOT_APPLICABLE
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(),
        "formula_validation": {"valid": True, "review_required": False},
        "sales_clarity": {"clear": True, "review_required": False},
    }))
    assert v["valid"] is True, v["reasons"]


def test_malformed_not_applicable_fails():
    v = _eval(_base_set(claim_review={
        "completeness": {"complete": True}, "safety": {"safe": True},
        "semantic_review": _receipt(),
        "formula_validation": {"applicable": False},  # missing evaluator/route/reason
        "sales_clarity": _na(),
    }))
    assert v["valid"] is False
    assert "FORMULA_MISSING_OR_OPEN" in v["reasons"]
