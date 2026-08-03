"""COPY-CORRECTIVE-B02/B05 (defect #6): a newly APPROVED Product Intelligence
snapshot durably quarantines older grounded copy, and never fails silently.
"""
import json

import pytest

from agent.db import crud
from agent.models import copy_set as models
from agent.services import copy_set_service as svc
from agent.services.copy_set_validity_service import evaluate_copy_set_id


async def _eligible_product() -> tuple[str, str]:
    from tests.conftest import make_product_copy_eligible

    product = await crud.create_product(raw_product_title="Stale Test Serum 5ML", source="MANUAL")
    pid = product["id"]
    snap = await make_product_copy_eligible(pid)
    return pid, snap


async def _approve_a_copy_set(pid: str) -> str:
    row = await crud.create_copy_set(
        pid,
        angle="Segar sepanjang hari",
        hook="Nak kulit nampak segar sepanjang hari?",
        subhook="Rutin ringkas tanpa leceh",
        usp_set_json=json.dumps(
            ["Menyerap dalam 10 saat", "Untuk kulit kombinasi", "Tanpa pewangi"]
        ),
        cta="Cuba masukkan dalam rutin kau hari ni.",
        platform="TIKTOK",
        language="BM_MS",
        route_type="DIRECT",
        formula_family="HSO",
        dedupe_key="stale-" + pid,
        status=models.STATUS_COPY_REVIEW_REQUIRED,
        claim_review_json=json.dumps({"completeness": {"complete": True}, "safety": {"safe": True}}),
    )
    cid = row["copy_set_id"]
    await svc.approve_copy_set(
        cid, {"approval_phrase": models.APPROVAL_PHRASE, "approved_by": "faris"}
    )
    return cid


@pytest.mark.asyncio
async def test_new_pi_snapshot_durably_quarantines_old_copy():
    from tests.conftest import make_product_copy_eligible

    pid, snap1 = await _eligible_product()
    cid = await _approve_a_copy_set(pid)

    # Strict-valid before the new snapshot.
    before = await evaluate_copy_set_id(cid)
    assert before["valid"] is True, before["reasons"]

    # Approving a NEW PI snapshot (version 2) invalidates the older grounded copy.
    snap2 = await make_product_copy_eligible(pid)
    assert snap2 != snap1

    stored = await svc.get_copy_set(cid)
    assert stored["pi_eligibility_status"] == "NEEDS_REVALIDATION"  # durable quarantine

    after = await evaluate_copy_set_id(cid)
    assert after["valid"] is False
    assert any("QUARANTINED" in r or "PI_SNAPSHOT_MISMATCH" in r for r in after["reasons"])


@pytest.mark.asyncio
async def test_stale_sweep_failure_is_visible_not_silent(monkeypatch):
    pid, snap1 = await _eligible_product()
    await _approve_a_copy_set(pid)

    async def _boom(*a, **k):
        raise RuntimeError("sweep boom")

    # Force the durable sweep to fail. The PI approval must STILL succeed (never
    # rolled back for a copy side-effect); the failure is logged, not swallowed.
    monkeypatch.setattr(
        "agent.services.copy_set_validity_service.mark_stale_copy_sets_for_product", _boom
    )
    from tests.conftest import make_product_copy_eligible

    snap2 = await make_product_copy_eligible(pid)
    assert snap2 and snap2 != snap1
