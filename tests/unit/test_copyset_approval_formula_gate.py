"""Approval-side Formula-Driven Copywriting Engine gate.

A Copy Set must not become COPY_APPROVED when its stored formula-validation /
sales-clarity verdict is failing or review-required, unless an explicit + auditable
override is supplied. Approval must also PRESERVE the verdict (never strip it) so
readiness + provenance can read it downstream. Safety + completeness still gate
first. No Google Flow / queue / prompt-compiler / DB-migration touched.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services import copy_set_service as svc

_PHRASE = models.APPROVAL_PHRASE
_PASS = {"valid": True, "review_required": False, "violations": []}
_FAIL = {"valid": False, "review_required": True, "violations": [{"code": "SLOT_MISSING_DESIRE"}]}
_CLEAR = {"clear": True, "review_required": False, "gaps": []}
_GAPS = {"clear": False, "review_required": True, "gaps": ["NO_TRIGGER"]}


async def _make_product() -> str:
    product = await crud.create_product(raw_product_title="Serum Test 5ML", source="MANUAL")
    from tests.conftest import make_product_copy_eligible
    await make_product_copy_eligible(product["id"])
    return product["id"]


async def _make_review_set(
    pid: str,
    *,
    formula_validation=None,
    sales_clarity=None,
    cta: str = "Cuba masukkan dalam rutin kau hari ni.",
) -> str:
    claim_review = {
        "route_type": "DIRECT",
        "formula_id": "PAS_STANDARD",
        "formula_definition_status": "DEFINED",
        "ai_generated": True,
    }
    if formula_validation is not None:
        claim_review["formula_validation"] = formula_validation
    if sales_clarity is not None:
        claim_review["sales_clarity"] = sales_clarity
    row = await crud.create_copy_set(
        pid,
        angle="Segar sepanjang hari",
        hook="Nak kulit nampak segar sepanjang hari?",
        subhook="Rutin ringkas untuk semua",
        usp_set_json=json.dumps(
            ["Sesuai rutin harian", "Mudah digunakan", "Formula ringan"]
        ),
        cta=cta,
        platform="TIKTOK",
        language="BM_MS",
        route_type="DIRECT",
        formula_family="PAS",
        status=models.STATUS_COPY_REVIEW_REQUIRED,
        dedupe_key=f"test-{pid}",
        claim_review_json=json.dumps(claim_review),
    )
    return row["copy_set_id"]



@pytest.fixture(autouse=True)
def _b04_eligibility_pass(monkeypatch):
    """PI-FINAL-B04: non-DB/mocked product paths pass the gate."""
    async def _ok(product_id: str = '', *a, **k):
        return {"product_id": product_id, "eligible": True, "reasons": []}
    monkeypatch.setattr("agent.services.copy_eligibility_service.assert_copy_eligible", _ok)
    monkeypatch.setattr("agent.services.copy_eligibility_service.copy_eligibility", _ok)

@pytest.mark.asyncio
async def test_approve_allows_formula_pass_and_clarity_clear():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_PASS, sales_clarity=_CLEAR)
    approved = await svc.approve_copy_set(
        cid, {"approval_phrase": _PHRASE, "approved_by": "faris"}
    )
    assert approved["status"] == models.STATUS_COPY_APPROVED
    # Verdict must be preserved (never stripped) so readiness reads real status.
    assert approved["claim_review"]["formula_validation"] == _PASS
    assert approved["claim_review"]["sales_clarity"] == _CLEAR
    assert approved["claim_review"]["formula_id"] == "PAS_STANDARD"
    assert "approval_override" not in approved["claim_review"]


@pytest.mark.asyncio
async def test_approve_blocks_formula_review_required():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_FAIL, sales_clarity=_CLEAR)
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE})
    assert exc.value.code == "COPY_SET_FORMULA_REVIEW_REQUIRED"
    assert exc.value.detail["formula_review_required"] is True
    stored = await svc.get_copy_set(cid)
    assert stored["status"] != models.STATUS_COPY_APPROVED


@pytest.mark.asyncio
async def test_approve_blocks_sales_clarity_gaps():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_PASS, sales_clarity=_GAPS)
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE})
    assert exc.value.code == "COPY_SET_FORMULA_REVIEW_REQUIRED"
    assert exc.value.detail["clarity_review_required"] is True


@pytest.mark.asyncio
async def test_approve_override_allows_and_records_audit():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_FAIL, sales_clarity=_CLEAR)
    approved = await svc.approve_copy_set(
        cid,
        {
            "approval_phrase": _PHRASE,
            "approved_by": "faris",
            "override_formula_review": True,
            "override_reason": "Owner accepted after manual review",
        },
    )
    assert approved["status"] == models.STATUS_COPY_APPROVED
    ovr = approved["claim_review"]["approval_override"]
    assert ovr["formula_review_overridden"] is True
    assert ovr["reason"] == "Owner accepted after manual review"
    assert ovr["by"] == "faris"
    # Verdict preserved even under override (audit truth is not rewritten).
    assert approved["claim_review"]["formula_validation"] == _FAIL


@pytest.mark.asyncio
async def test_approve_override_requires_reason():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_FAIL, sales_clarity=_CLEAR)
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(
            cid, {"approval_phrase": _PHRASE, "override_formula_review": True}
        )
    assert exc.value.code == "OVERRIDE_REASON_REQUIRED"


@pytest.mark.asyncio
async def test_approve_unsafe_precedes_formula_gate():
    pid = await _make_product()
    # Formula PASS, but the CTA carries a cure/guarantee claim → safety blocks first.
    cid = await _make_review_set(
        pid,
        formula_validation=_PASS,
        sales_clarity=_CLEAR,
        cta="This will cure you and results are guaranteed",
    )
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE})
    assert exc.value.code == "COPY_SET_UNSAFE"


@pytest.mark.asyncio
async def test_approve_deterministic_no_verdict_still_approves():
    pid = await _make_product()
    # Deterministic-lane set: no formula verdict in claim_review → not formula-
    # applicable, approves on safety + completeness alone (no false block).
    cid = await _make_review_set(pid, formula_validation=None, sales_clarity=None)
    approved = await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE})
    assert approved["status"] == models.STATUS_COPY_APPROVED
    assert "formula_validation" not in approved["claim_review"]


# ── COPY-CORRECTIVE-B02/B03: atomic grounding + generic gate + fail-closed ────
@pytest.mark.asyncio
async def test_approve_writes_semantic_receipt_and_grounds_atomically():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_PASS, sales_clarity=_CLEAR)
    approved = await svc.approve_copy_set(
        cid, {"approval_phrase": _PHRASE, "approved_by": "faris"}
    )
    assert approved["status"] == models.STATUS_COPY_APPROVED
    sr = approved["claim_review"]["semantic_review"]
    assert sr["decision"] == "APPROVED"
    assert sr["reviewer"] == "faris"
    assert sr["pi_snapshot_id"]
    # The single write also grounded PI lineage on the same row (no second txn).
    stored = await svc.get_copy_set(cid)
    assert stored["pi_snapshot_id"] == sr["pi_snapshot_id"]
    assert stored["grounded_at"]
    # The strict validity authority now recognises it as valid, end to end.
    from agent.services.copy_set_validity_service import evaluate_copy_set_id

    v = await evaluate_copy_set_id(cid)
    assert v["valid"] is True, v["reasons"]


@pytest.mark.asyncio
async def test_approve_blocks_generic_filler():
    pid = await _make_product()
    cid = await _make_review_set(pid, formula_validation=_PASS, sales_clarity=_CLEAR)
    # Inject the exact synthetic-filler family the holdout scripts emitted.
    await crud.update_copy_set(
        cid,
        usp_set_json=json.dumps(["Kelebihan Serum Test #1", "Kelebihan Serum Test #2"]),
    )
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE, "approved_by": "faris"})
    assert exc.value.code == "COPY_SET_GENERIC"
    stored = await svc.get_copy_set(cid)
    assert stored["status"] != models.STATUS_COPY_APPROVED


@pytest.mark.asyncio
async def test_approve_fails_closed_without_pi_snapshot():
    # Eligibility is mocked True by the autouse fixture, but atomic approval must
    # STILL refuse to ground copy when there is no approved PI snapshot - the row
    # can never reach COPY_APPROVED without lineage.
    from agent.db import crud as _crud

    product = await _crud.create_product(raw_product_title="No Snapshot 5ML", source="MANUAL")
    pid = product["id"]
    cid = await _make_review_set(pid, formula_validation=_PASS, sales_clarity=_CLEAR)
    with pytest.raises(svc.CopySetError) as exc:
        await svc.approve_copy_set(cid, {"approval_phrase": _PHRASE, "approved_by": "faris"})
    assert exc.value.code == "COPY_SET_NO_PI_SNAPSHOT"
    stored = await svc.get_copy_set(cid)
    assert stored["status"] != models.STATUS_COPY_APPROVED
