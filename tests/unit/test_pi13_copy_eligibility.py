"""PI-13 C5 regression tests: the COPY_ELIGIBLE gate fails closed for every ineligible state,
and only an active, non-alias, accepted, claim-safe, copy-complete product is eligible."""
from agent.services.copy_eligibility_service import evaluate_copy_eligibility, COPY_CRITICAL_FIELDS

_ALL_PRESENT = {f: True for f in COPY_CRITICAL_FIELDS}


def _eval(**kw):
    base = dict(lifecycle_status="ACTIVE", archived_reason=None, has_approved_snapshot=True,
                claim_gate="CLAIM_SAFE", copy_critical_present=dict(_ALL_PRESENT))
    base.update(kw)
    return evaluate_copy_eligibility(**base)


def test_fully_eligible():
    r = _eval()
    assert r["eligible"] is True and r["reasons"] == []


def test_merged_alias_fails_closed():
    r = _eval(lifecycle_status="ARCHIVED", archived_reason="DUPLICATE_MERGED_TO_CANONICAL:abc123")
    assert r["eligible"] is False and "MERGED_ALIAS" in r["reasons"]


def test_not_active_fails_closed():
    assert _eval(lifecycle_status="ARCHIVED")["eligible"] is False
    assert "NOT_ACTIVE" in _eval(lifecycle_status="ARCHIVED")["reasons"]


def test_no_snapshot_fails_closed():
    r = _eval(has_approved_snapshot=False)
    assert r["eligible"] is False and "NO_ACCEPTED_SNAPSHOT" in r["reasons"]


def test_claim_not_safe_fails_closed():
    for gate in ("CLAIM_BLOCKED", "CLAIM_REVIEW_REQUIRED", None, ""):
        r = _eval(claim_gate=gate)
        assert r["eligible"] is False
        assert any(x.startswith("CLAIM_NOT_SAFE") for x in r["reasons"])


def test_missing_copy_critical_fails_closed():
    r = _eval(copy_critical_present={"product_description": True, "benefits_json": False, "usp_json": True})
    assert r["eligible"] is False
    assert any(x.startswith("MISSING_COPY_CRITICAL") and "benefits_json" in x for x in r["reasons"])


def test_multiple_reasons_accumulate():
    r = _eval(lifecycle_status="ARCHIVED", archived_reason="DUPLICATE_MERGED_TO_CANONICAL:x",
              has_approved_snapshot=False, claim_gate="CLAIM_BLOCKED",
              copy_critical_present={f: False for f in COPY_CRITICAL_FIELDS})
    assert r["eligible"] is False and len(r["reasons"]) >= 4
