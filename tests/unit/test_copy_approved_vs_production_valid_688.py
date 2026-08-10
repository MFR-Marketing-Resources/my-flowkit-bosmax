"""Issue #688 — Approved workflow status vs production-valid contract.

UI/API must never treat COPY_APPROVED alone as production-valid.
Shared authority: copy_set_validity_service.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.models.copy_set import STATUS_COPY_APPROVED, STATUS_COPY_REVIEW_REQUIRED
from agent.services.copy_set_validity_service import (
    CLASS_APPROVED_COPY_INVALID_LINEAGE,
    CLASS_APPROVED_COPY_MISSING_REVIEW,
    CLASS_APPROVED_COPY_STALE,
    CLASS_APPROVED_COPY_UNSAFE,
    CLASS_APPROVED_COPY_VALID,
    build_validity_contract,
    classify_product_copy,
    evaluate_copy_set_validity,
    merge_validity_contract,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _receipt(**kw):
    r = {
        "reviewer": "test-reviewer",
        "reviewed_at": _now(),
        "decision": "APPROVED",
        "rationale": "Grounded on current PI with field-level evidence.",
        "pi_snapshot_id": "snap-1",
        "authority_digest": "digest-1",
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


def _na():
    return {
        "applicable": False,
        "reason": "deterministic lane",
        "route": "TEST",
        "evaluator": "test",
        "evaluated_at": _now(),
    }


def _base_set(**kw):
    claim = {
        "completeness": {"complete": True},
        "safety": {"safe": True},
        "semantic_review": _receipt(),
        "formula_validation": _na(),
        "sales_clarity": _na(),
    }
    if "claim_review" in kw:
        claim = kw.pop("claim_review")
    cs = {
        "copy_set_id": "cs-1",
        "product_id": "p-1",
        "status": STATUS_COPY_APPROVED,
        "archived": 0,
        "angle": "Pain",
        "hook": "Anak malam susah tidur, perut rasa kembung?",
        "subhook": "Ibu tak perlu panik — urut perlahan dengan minyak warisan.",
        "usp_set": ["Formula tradisional", "Saiz 25ml mudah dibawa", "Sesuai seisi keluarga"],
        "cta": "Klik keranjang Shopee sekarang",
        "platform": "TIKTOK",
        "language": "BM_MS",
        "route_type": "DIRECT",
        "formula_family": "PAS",
        "pi_snapshot_id": "snap-1",
        "pi_snapshot_version": 1,
        "pi_grounding_digest": "digest-1",
        "claim_review": claim,
        "provenance": {
            "pi_lineage": {
                "snapshot_id": "snap-1",
                "version": 1,
                "authority_digest": "digest-1",
            }
        },
    }
    cs.update(kw)
    return cs


def _eval(cs, **kwargs):
    defaults = dict(
        product_eligible=True,
        product_eligibility_reasons=[],
        current_snapshot_id="snap-1",
        current_snapshot_version=1,
        current_authority_digest="digest-1",
        product_name="Minyak Warisan Cap Burung 25ml",
    )
    defaults.update(kwargs)
    return evaluate_copy_set_validity(copy_set=cs, **defaults)


def test_approved_with_valid_review_is_production_valid():
    v = _eval(_base_set())
    assert v["valid"] is True
    contract = build_validity_contract(copy_set=_base_set(), verdict=v)
    assert contract["workflow_status"] == STATUS_COPY_APPROVED
    assert contract["production_valid"] is True
    assert contract["validity_class"] == CLASS_APPROVED_COPY_VALID
    assert contract["recommended_action"] == "READY"
    merged = merge_validity_contract(_base_set(), v)
    assert merged["production_valid"] is True
    assert merged["status"] == STATUS_COPY_APPROVED


def test_approved_missing_semantic_review_not_production_valid():
    cs = _base_set(
        claim_review={
            "completeness": {"complete": True},
            "safety": {"safe": True},
            "formula_validation": _na(),
            "sales_clarity": _na(),
        }
    )
    v = _eval(cs)
    assert v["valid"] is False
    assert v["primary_reason"] == "MISSING_REVIEW"
    contract = build_validity_contract(copy_set=cs, verdict=v)
    assert contract["workflow_status"] == STATUS_COPY_APPROVED
    assert contract["production_valid"] is False
    assert contract["validity_class"] == CLASS_APPROVED_COPY_MISSING_REVIEW


def test_approved_stale_pi_lineage_classifies_stale_not_missing_review():
    cs = _base_set(
        pi_snapshot_id="snap-old",
        pi_snapshot_version=5,
        pi_grounding_digest="digest-old",
        claim_review={
            "completeness": {"complete": True},
            "safety": {"safe": True},
            "formula_validation": _na(),
            "sales_clarity": _na(),
            "semantic_review": _receipt(
                pi_snapshot_id="snap-old", authority_digest="digest-old"
            ),
        },
        provenance={
            "pi_lineage": {
                "snapshot_id": "snap-old",
                "version": 5,
                "authority_digest": "digest-old",
            }
        },
    )
    v = _eval(
        cs,
        current_snapshot_id="snap-new",
        current_snapshot_version=7,
        current_authority_digest="digest-new",
    )
    assert v["valid"] is False
    assert v["stale"] is True
    # Must not mislabel stale receipt as pure MISSING_REVIEW (#688).
    assert v["primary_reason"] == "STALE"
    contract = build_validity_contract(copy_set=cs, verdict=v)
    assert contract["production_valid"] is False
    assert contract["validity_class"] == CLASS_APPROVED_COPY_STALE


def test_approved_invalid_grounding_fail_closed():
    cs = _base_set(
        claim_review={
            "completeness": {"complete": True},
            "safety": {"safe": True},
            "formula_validation": _na(),
            "sales_clarity": _na(),
            "semantic_review": _receipt(
                grounding={"grounded": False, "reasons": ["NO_OVERLAP"]}
            ),
        }
    )
    v = _eval(cs)
    assert v["valid"] is False
    assert any("SEMANTIC_REVIEW_NOT_GROUNDED" in r for r in v["reasons"])


def test_mixed_product_counts_raw_vs_valid():
    good = _eval(_base_set(copy_set_id="good"))
    bad_missing = _eval(
        _base_set(
            copy_set_id="bad",
            claim_review={
                "completeness": {"complete": True},
                "safety": {"safe": True},
                "formula_validation": _na(),
                "sales_clarity": _na(),
            },
        )
    )
    raw = [
        {"copy_set_id": "good", "status": STATUS_COPY_APPROVED, "archived": 0},
        {"copy_set_id": "bad", "status": STATUS_COPY_APPROVED, "archived": 0},
        {"copy_set_id": "draft", "status": STATUS_COPY_REVIEW_REQUIRED, "archived": 0},
    ]
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[good, bad_missing],
        raw_sets=raw,
    )
    assert c["classification"] == CLASS_APPROVED_COPY_VALID
    assert c["valid_copy_set_id"] == "good"
    assert c["valid_approved_count"] == 1
    assert c["raw_approved_count"] == 2


def test_all_raw_approved_invalid_not_ready_class():
    bad = _eval(
        _base_set(
            claim_review={
                "completeness": {"complete": True},
                "safety": {"safe": True},
                "formula_validation": _na(),
                "sales_clarity": _na(),
            }
        )
    )
    c = classify_product_copy(
        product_eligible=True,
        product_eligibility_reasons=[],
        set_verdicts=[bad],
        raw_sets=[{"copy_set_id": "cs-1", "status": STATUS_COPY_APPROVED, "archived": 0}],
    )
    assert c["classification"] == CLASS_APPROVED_COPY_MISSING_REVIEW
    assert c["valid_approved_count"] == 0
    assert c["raw_approved_count"] == 1
    assert c["valid_copy_set_id"] is None


def test_invalid_approved_cannot_present_as_valid_contract():
    v = _eval(
        _base_set(
            claim_review={
                "completeness": {"complete": True},
                "safety": {"safe": False, "violations": ["X"]},
                "formula_validation": _na(),
                "sales_clarity": _na(),
                "semantic_review": _receipt(),
            }
        )
    )
    contract = build_validity_contract(copy_set=_base_set(), verdict=v)
    assert contract["production_valid"] is False
    assert contract["validity_class"] == CLASS_APPROVED_COPY_UNSAFE
    assert contract["workflow_status"] == STATUS_COPY_APPROVED


def test_missing_pi_lineage_invalid_lineage_class():
    cs = _base_set(
        pi_snapshot_id=None,
        pi_snapshot_version=None,
        pi_grounding_digest=None,
        provenance={},
        claim_review={
            "completeness": {"complete": True},
            "safety": {"safe": True},
            "formula_validation": _na(),
            "sales_clarity": _na(),
            # receipt without lineage also fails review path
            "semantic_review": _receipt(pi_snapshot_id="", authority_digest=""),
        },
    )
    v = _eval(cs, current_snapshot_id="snap-1", current_authority_digest="digest-1")
    assert v["valid"] is False
    # Either invalid lineage or missing review tokens — never valid.
    contract = build_validity_contract(copy_set=cs, verdict=v)
    assert contract["production_valid"] is False


@pytest.mark.asyncio
async def test_list_enrichment_exposes_contract(monkeypatch):
    """list_copy_sets must attach production_valid without UI-side predicates."""
    from agent.services import copy_set_service as svc

    rows = [
        {
            "copy_set_id": "good",
            "product_id": "p1",
            "angle": "a",
            "hook": "hook product specific oil belly",
            "subhook": "sub",
            "usp_set_json": '["u1","u2","u3"]',
            "cta": "cta cart",
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": "DIRECT",
            "formula_family": "PAS",
            "status": STATUS_COPY_APPROVED,
            "dedupe_key": "d1",
            "source": "OPERATOR",
            "provenance_json": "{}",
            "claim_review_json": "{}",
            "archived": 0,
        }
    ]

    async def fake_list(pid):
        return rows

    async def fake_enrich(pid, sets):
        out = []
        for s in sets:
            out.append(
                {
                    **s,
                    "workflow_status": s["status"],
                    "production_valid": s["copy_set_id"] == "good",
                    "validity_class": CLASS_APPROVED_COPY_VALID,
                    "validity_class_label": "VALID",
                    "validity_reasons": [],
                    "recommended_action": "READY",
                    "validity_primary_reason": None,
                    "validity_stale": False,
                }
            )
        return out

    monkeypatch.setattr(svc.crud, "list_copy_sets_for_product", fake_list)
    monkeypatch.setattr(
        "agent.services.copy_set_validity_service.enrich_copy_sets_with_validity",
        fake_enrich,
    )
    items = await svc.list_copy_sets("p1")
    assert items[0]["production_valid"] is True
    assert items[0]["validity_class"] == CLASS_APPROVED_COPY_VALID


@pytest.mark.asyncio
async def test_binding_rejects_invalid_approved(monkeypatch):
    from agent.services import copy_binding_service as bind
    from agent.services.copy_binding_service import CopyBindingError

    async def fake_get(cid):
        return {
            "copy_set_id": cid,
            "product_id": "p1",
            "status": STATUS_COPY_APPROVED,
            "hook": "h",
            "usp_set_json": '["a"]',
            "cta": "c",
            "angle": "a",
            "subhook": "s",
            "dedupe_key": "d",
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": "DIRECT",
            "formula_family": "PAS",
            "claim_review_json": "{}",
            "provenance_json": "{}",
            "archived": 0,
        }

    async def fake_eval(cid, **kw):
        return {
            "valid": False,
            "reasons": ["SEMANTIC_REVIEW_MISSING"],
            "primary_reason": "MISSING_REVIEW",
        }

    monkeypatch.setattr(bind.crud, "get_copy_set", fake_get)
    monkeypatch.setattr(
        "agent.services.copy_set_validity_service.evaluate_copy_set_id", fake_eval
    )
    with pytest.raises(CopyBindingError) as ei:
        await bind.resolve_compiler_copy_intelligence("p1", "bad-cs")
    assert ei.value.code == "COPY_SET_INVALID"


@pytest.mark.asyncio
async def test_binding_accepts_valid_approved(monkeypatch):
    from agent.services import copy_binding_service as bind

    async def fake_get(cid):
        return {
            "copy_set_id": cid,
            "product_id": "p1",
            "status": STATUS_COPY_APPROVED,
            "hook": "hook text",
            "usp_set_json": '["a","b"]',
            "cta": "cta text",
            "angle": "angle",
            "subhook": "sub",
            "dedupe_key": "d",
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": "DIRECT",
            "formula_family": "PAS",
            "claim_review_json": "{}",
            "provenance_json": "{}",
            "archived": 0,
        }

    async def fake_eval(cid, **kw):
        return {"valid": True, "reasons": [], "primary_reason": None}

    monkeypatch.setattr(bind.crud, "get_copy_set", fake_get)
    monkeypatch.setattr(
        "agent.services.copy_set_validity_service.evaluate_copy_set_id", fake_eval
    )
    out = await bind.resolve_compiler_copy_intelligence("p1", "good-cs")
    assert out["copy_intelligence"] is not None
    assert out["lineage"]["copy_set_id"] == "good-cs"
