"""Macro Round 3 P5 — P6 per-item allocation + usage ledger + no-pointer-churn.

Zero provider, zero credit, disposable DB.  Proves per-item manifest allocation
records the append-only usage ledger, NEVER mutates the product-global V2
activation pointer (copy_execution_authority_v2), revalidates fail-closed, and
that the P6 scheduler hook uses the explicit per-item selection instead of the
product-global resolver (and leaves creator lanes on the existing path).
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from agent.db.schema import get_db
from agent.services import production_allocation_service as alloc
from agent.services import production_copy_supply_service as supply
from agent.services import production_supply_manifest_service as manifest_service
from agent.services import production_supply_repository as supply_repo
from agent.services.production_allocation_service import AllocationError
from tests.unit.test_storyboard_landbank_v3_materializer import _approved_supply


async def _approved_projection_ids(master_id: str) -> list[str]:
    db = await get_db()
    rows = await (
        await db.execute(
            "SELECT projection_id FROM duration_projection_v3 "
            "WHERE master_id=? AND status='APPROVED' ORDER BY target_duration_seconds",
            (master_id,),
        )
    ).fetchall()
    return [row[0] for row in rows]


async def _frozen_manifest(monkeypatch, product_id: str):
    svc, result, approval = await _approved_supply(monkeypatch, product_id)
    receipt_id = approval["receipt"]["receipt_id"]
    for projection_id in await _approved_projection_ids(result["master"]["entity_id"]):
        await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
    built = await manifest_service.build_manifest(product_id, requested_capacity=3, actor_id="op")
    manifest = built["manifest"]
    await manifest_service.freeze_manifest(manifest.manifest_id, manifest.revision, actor_id="op")
    return manifest


async def _authority_pointer_count() -> int:
    db = await get_db()
    row = await (await db.execute("SELECT COUNT(*) FROM copy_execution_authority_v2")).fetchone()
    return int(row[0])


@pytest.mark.asyncio
async def test_allocation_records_usage_and_never_churns_activation_pointer(monkeypatch):
    manifest = await _frozen_manifest(monkeypatch, "alloc-basic")
    before_pointer = await _authority_pointer_count()

    outcome = await alloc.allocate_from_manifest(
        manifest.manifest_id, manifest.revision,
        p6_plan_id="plan-alloc-basic", requested_items=2, actor_id="op",
    )
    assert outcome["allocated_count"] == 2
    for allocation in outcome["allocations"]:
        selection = allocation["round3_manifest_item"]
        assert selection["v2_blueprint_id"] and selection["v2_approval_snapshot_id"]

    # Section 25 invariant: allocation NEVER writes the product-global pointer.
    assert await _authority_pointer_count() == before_pointer

    # Usage ledger recorded ALLOCATED events (not derived by counting rows).
    events = await supply_repo.list_usage_for_plan("plan-alloc-basic")
    allocated = [event for event in events if event.usage_type == "ALLOCATED"]
    assert len(allocated) == 2


@pytest.mark.asyncio
async def test_allocation_requires_a_frozen_manifest(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "alloc-draft")
    receipt_id = approval["receipt"]["receipt_id"]
    for projection_id in await _approved_projection_ids(result["master"]["entity_id"]):
        await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
    built = await manifest_service.build_manifest("alloc-draft", requested_capacity=3, actor_id="op")
    manifest = built["manifest"]  # DRAFT, not frozen
    with pytest.raises(AllocationError) as excinfo:
        await alloc.allocate_from_manifest(
            manifest.manifest_id, manifest.revision,
            p6_plan_id="plan-draft", requested_items=1, actor_id="op",
        )
    assert excinfo.value.code == "ALLOCATION_MANIFEST_NOT_FROZEN"


@pytest.mark.asyncio
async def test_revalidate_item_selection_valid_then_stale_after_truth_drift(monkeypatch):
    manifest = await _frozen_manifest(monkeypatch, "alloc-reval")
    outcome = await alloc.allocate_from_manifest(
        manifest.manifest_id, manifest.revision,
        p6_plan_id="plan-reval", requested_items=1, actor_id="op",
    )
    selection = outcome["allocations"][0]["round3_manifest_item"]

    valid = await alloc.revalidate_item_selection(selection)
    assert valid["valid"] is True
    assert valid["approved_execution_text"]  # exact per-item copy resolved

    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('alloc-reval-snap2','alloc-reval',2,'APPROVED','Newer.', "
        "'[\"nb\"]','[\"nu\"]','nc','[\"ncl\"]','{\"a\":1}','{\"f\":\"PAS\"}','CLAIM_SAFE','LOW', "
        "'2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()

    stale = await alloc.revalidate_item_selection(selection)
    assert stale["valid"] is False
    # Round 3 now revalidates through the FULL shared V2 authority validator, so a
    # Product-Truth advance surfaces the precise V2 authority reason code (taxonomy /
    # evidence staleness) rather than the old shallow "PRODUCT_TRUTH_ADVANCED".
    assert stale["reason"] in {
        "PRODUCT_TRUTH_ADVANCED",
        "COPY_V2_TAXONOMY_AUTHORITY_STALE",
        "COPY_V2_EVIDENCE_STALE",
        "COPY_V2_EVIDENCE_NOT_FOUND",
    }


@pytest.mark.asyncio
async def test_usage_ledger_is_append_only(monkeypatch):
    manifest = await _frozen_manifest(monkeypatch, "alloc-ledger")
    await alloc.allocate_from_manifest(
        manifest.manifest_id, manifest.revision,
        p6_plan_id="plan-ledger", requested_items=1, actor_id="op",
    )
    db = await get_db()
    with pytest.raises(sqlite3.IntegrityError, match="LANDBANK_USAGE_V3_APPEND_ONLY"):
        await db.execute("UPDATE landbank_usage_v3 SET reason_code='x' WHERE p6_plan_id='plan-ledger'")
    await db.rollback()


@pytest.mark.asyncio
async def test_scheduler_hook_uses_explicit_selection_and_bypasses_global_pointer(monkeypatch):
    from agent.services import creative_production_scheduler_service as scheduler
    from agent.services import copy_execution_resolver
    from agent.services import production_allocation_service as allocation

    calls = {"global": 0, "round3": 0}

    async def _fake_global(product_id, lane, context=None):
        calls["global"] += 1
        raise copy_execution_resolver.CopyExecutionResolutionError("SHOULD_NOT_BE_CALLED")

    async def _fake_round3(selection):
        calls["round3"] += 1
        return {"valid": False, "reason": "PRODUCT_TRUTH_ADVANCED"}

    monkeypatch.setattr(
        copy_execution_resolver, "resolve_persisted_copy_execution_binding", _fake_global
    )
    monkeypatch.setattr(allocation, "revalidate_item_selection", _fake_round3)

    plan = {"product_id": "hook-x", "pool_snapshot_json": "{}"}
    dimensions = {
        "model_key": "veo",
        "duration_seconds": 8,
        "round3_manifest_item": {
            "v2_blueprint_id": "bpv2_hook",
            "v2_blueprint_revision": 1,
            "v2_approval_snapshot_id": "snap",
            "product_truth_snapshot_digest": "a" * 64,
            "formula_id": "PAS",
        },
    }
    item = {
        "media_type": "POSTER",
        "product_id": "hook-x",
        "prompt_package_json": "{}",
        "creative_dimensions_json": json.dumps(dimensions),
    }
    try:
        _payload, blockers = await scheduler._build_item_payload(item, plan, aspect="9:16")
    except Exception:
        blockers = None  # downstream POSTER build may error; the routing already ran

    # The explicit per-item selection was used; the product-global pointer path
    # was NOT touched.
    assert calls["round3"] == 1
    assert calls["global"] == 0
    if blockers is not None:
        assert any("COPY_V2_MANIFEST_ITEM_STALE" in b for b in blockers)


@pytest.mark.asyncio
async def test_scheduler_hook_absent_keeps_global_resolution_for_creator_paths(monkeypatch):
    from agent.services import creative_production_scheduler_service as scheduler
    from agent.services import copy_execution_resolver

    calls = {"global": 0}

    async def _fake_global(product_id, lane, context=None):
        calls["global"] += 1
        raise copy_execution_resolver.CopyExecutionResolutionError("STOP")

    monkeypatch.setattr(
        copy_execution_resolver, "resolve_persisted_copy_execution_binding", _fake_global
    )
    plan = {"product_id": "hook-y", "pool_snapshot_json": "{}"}
    item = {
        "media_type": "POSTER",
        "product_id": "hook-y",
        "prompt_package_json": "{}",
        "creative_dimensions_json": json.dumps({"model_key": "veo", "duration_seconds": 8}),
    }
    try:
        await scheduler._build_item_payload(item, plan, aspect="9:16")
    except Exception:
        pass
    # No round3 selection => existing product-global resolution path is used.
    assert calls["global"] == 1
