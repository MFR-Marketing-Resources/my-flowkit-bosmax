"""Unit tests: SAFE import soft-field reconciliation eligibility + close."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.services import product_truth_import_soft_reconciliation as svc


def _snap(**over):
    base = {
        "snapshot_id": "snap-1",
        "version": 3,
        "status": "APPROVED",
        "approved_at": "2026-01-01T00:00:00Z",
        "product_description": "Core desc",
        "benefits_json": '["a"]',
        "usp_json": '["u"]',
        "usage_text": "use",
        "ingredients_text": "ing",
        "warnings_text": "warn",
        "target_customer_text": "adults",
        "allowed_claims_json": '["ok"]',
        "blocked_claims_json": "[]",
        "claim_gate": "CLAIM_SAFE",
        "claim_risk_level": "LOW",
        "size_or_volume": "100ml",
        "product_form_factor": "bottle",
        "packaging_description": "box",
        "buyer_persona_snapshot_json": '{"audience":"A"}',
        "hook_angles_json": '["h1"]',
        "cta_angles_json": '["c1"]',
        "pain_points_json": '["p1"]',
        "subhook_json": "[]",
    }
    base.update(over)
    return base


def _draft(**over):
    base = {
        "draft_id": "d1",
        "product_id": "p1",
        "created_by": "codex-aa-ah-import",
        "review_status": "READY_FOR_REVIEW",
        "claim_gate": "CLAIM_SAFE",
        "readiness_status": "READY_FOR_APPROVAL",
        "revision_of_snapshot_id": "snap-1",
        "product_description": "Core desc",
        "benefits_json": '["a"]',
        "usp_json": '["u"]',
        "usage_text": "use",
        "ingredients_text": "ing",
        "warnings_text": "warn",
        "target_customer_text": "adults",
        "allowed_claims_json": '["ok"]',
        "blocked_claims_json": "[]",
        "claim_risk_level": "LOW",
        "size_or_volume": "100ml",
        "product_form_factor": "bottle",
        "packaging_description": "box",
        "buyer_persona_snapshot_json": '{"audience":"B"}',
        "hook_angles_json": "[]",
        "cta_angles_json": "[]",
        "pain_points_json": "[]",
        "subhook_json": "[]",
    }
    base.update(over)
    return base


def test_safe_when_core_equal_claim_safe():
    b, why = svc.classify_candidate(_draft(), _snap())
    assert b == "SAFE"
    assert why.startswith("CORE_EQUAL")


def test_ineligible_when_core_differs():
    b, why = svc.classify_candidate(
        _draft(product_description="CHANGED"), _snap()
    )
    assert b == "INELIGIBLE"
    assert why == "CORE_PRODUCT_TRUTH_DIFFERS"


def test_review_required_when_claim_gate_elevated():
    b, why = svc.classify_candidate(
        _draft(claim_gate="CLAIM_REVIEW_REQUIRED", review_status="NEEDS_REVISION"),
        _snap(),
    )
    assert b == "REVIEW_REQUIRED"


def test_ineligible_hub_created_by():
    b, _ = svc.classify_candidate(
        _draft(created_by="copywriting_hub_rev2_import"), _snap()
    )
    assert b == "INELIGIBLE"


def test_ineligible_stale_revision_lineage():
    b, why = svc.classify_candidate(
        _draft(revision_of_snapshot_id="old-snap"), _snap()
    )
    assert b == "INELIGIBLE"
    assert why == "REVISION_NOT_CURRENT_APPROVED"


def test_needs_revision_not_safe():
    b, _ = svc.classify_candidate(
        _draft(review_status="NEEDS_REVISION", claim_gate="CLAIM_SAFE"),
        _snap(),
    )
    assert b == "REVIEW_REQUIRED"


def test_snapshot_identity_stable_for_same_payload():
    a = svc.snapshot_identity(_snap())
    b = svc.snapshot_identity(_snap())
    assert a["digest"] == b["digest"]
    c = svc.snapshot_identity(_snap(product_description="x"))
    assert a["digest"] != c["digest"]


@pytest.mark.asyncio
async def test_close_requires_confirm_phrase(monkeypatch):
    with pytest.raises(ValueError, match="CONFIRMATION_REQUIRED"):
        await svc.close_safe_import_soft_revisions(confirm=False)
    with pytest.raises(ValueError, match="CONFIRM_PHRASE_MISMATCH"):
        await svc.close_safe_import_soft_revisions(
            confirm=True, confirm_phrase="wrong"
        )


@pytest.mark.asyncio
async def test_close_aborts_on_count_mismatch(monkeypatch, tmp_path):
    async def fake_preview():
        return {
            "safe_candidates": [{"product_id": "p1", "draft_id": "d1"}],
            "safe_candidate_count": 1,
            "review_required_count": 0,
            "hub_claim_conflict_open_count": 0,
            "ineligible_count": 0,
            "matches_expected_safe_count": False,
            "policy": {},
        }

    monkeypatch.setattr(svc, "preview_import_soft_reconciliation", fake_preview)
    out = await svc.close_safe_import_soft_revisions(
        confirm=True,
        confirm_phrase="CLOSE SAFE IMPORT REVISIONS",
        expected_count=549,
    )
    assert out["status"] == "ABORTED_COUNT_MISMATCH"
    assert out["mutations"] == 0


@pytest.mark.asyncio
async def test_close_batch_supersedes_and_preserves_snapshot(
    monkeypatch, tmp_path
):
    db_file = tmp_path / "t.db"
    db_file.write_bytes(b"sqlite-placeholder")
    monkeypatch.setattr(svc, "resolve_db_path", lambda: db_file)
    monkeypatch.setattr(svc, "resolve_receipt_dir", lambda: tmp_path / "receipts")
    (tmp_path / "receipts").mkdir()

    snap = _snap()
    draft = _draft()
    state = {
        "draft": dict(draft),
        "snap": dict(snap),
        "updated": False,
    }

    class FakeCur:
        def __init__(self, row=None, rowcount=1):
            self._row = row
            self.rowcount = rowcount

        async def fetchone(self):
            return self._row

        async def fetchall(self):
            return []

        async def close(self):
            return None

    class FakeRow(dict):
        def __getitem__(self, k):
            return dict.get(self, k)

    class FakeDB:
        async def execute(self, sql, params=()):
            s = " ".join(sql.split())
            if s.startswith("SELECT * FROM product_intelligence_review_draft WHERE draft_id"):
                if state["draft"].get("review_status") == "SUPERSEDED" and state["updated"]:
                    return FakeCur(FakeRow(state["draft"]))
                return FakeCur(FakeRow(state["draft"]))
            if s.startswith("UPDATE product_intelligence_review_draft"):
                # only if still actionable
                if state["draft"]["review_status"] in (
                    "DRAFT",
                    "READY_FOR_REVIEW",
                    "NEEDS_REVISION",
                ):
                    state["draft"]["review_status"] = "SUPERSEDED"
                    state["draft"]["reviewer_note"] = params[0]
                    state["updated"] = True
                    return FakeCur(rowcount=1)
                return FakeCur(rowcount=0)
            if "SELECT review_status FROM product_intelligence_review_draft" in s:
                return FakeCur(FakeRow({"review_status": state["draft"]["review_status"]}))
            return FakeCur()

        async def commit(self):
            return None

    async def fake_get_db():
        return FakeDB()

    async def fake_preview():
        return {
            "safe_candidates": [
                {
                    "product_id": "p1",
                    "draft_id": "d1",
                    "snapshot_identity": svc.snapshot_identity(snap),
                }
            ],
            "safe_candidate_count": 1,
            "review_required_count": 6,
            "hub_claim_conflict_open_count": 20,
            "ineligible_count": 0,
            "matches_expected_safe_count": True,
            "policy": {"default_action": "KEEP"},
        }

    async def fake_approved():
        return {"p1": state["snap"]}

    monkeypatch.setattr(svc, "get_db", fake_get_db)
    monkeypatch.setattr(svc, "preview_import_soft_reconciliation", fake_preview)
    monkeypatch.setattr(svc, "_latest_approved_by_product", fake_approved)

    # classify uses live draft dict — patch classify to always SAFE after load
    monkeypatch.setattr(
        svc,
        "classify_candidate",
        lambda d, a: (
            ("INELIGIBLE", "DONE")
            if str(d.get("review_status")) == "SUPERSEDED"
            else ("SAFE", "CORE_EQUAL_CLAIM_SAFE")
        ),
    )

    out = await svc.close_safe_import_soft_revisions(
        confirm=True,
        confirm_phrase="CLOSE SAFE IMPORT REVISIONS",
        expected_count=1,
        actor="tester",
        implementation_sha="deadbeef",
    )
    assert out["success_count"] == 1
    assert out["failure_count"] == 0
    assert state["draft"]["review_status"] == "SUPERSEDED"
    assert "SAFE_IMPORT_SOFT_FIELD_RECONCILIATION" in (state["draft"].get("reviewer_note") or "")
    assert out["snapshot_identity_mismatches"] == []
    assert Path(out["receipt_path"]).is_file()
    # idempotent second run: draft already superseded → classify fails → failure or skip
    out2 = await svc.close_safe_import_soft_revisions(
        confirm=True,
        confirm_phrase="CLOSE SAFE IMPORT REVISIONS",
        expected_count=1,
        actor="tester",
    )
    # preview still returns candidate but revalidation sees SUPERSEDED
    assert out2["success_count"] == 0
    assert out2["idempotent_skip_count"] + out2["failure_count"] >= 1
