"""Macro Round 3 P7 — scale, boundedness, concurrency, invalidation, recovery.

Zero provider, zero credit, disposable DB.  Proves the production-integration
chain is deterministic and BOUNDED: it never eager-materializes a Cartesian
opportunity space, converges under concurrency, and fails closed on any authority
drift.  The product-global V2 activation pointer is never written.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.db.schema import get_db
from agent.services import production_allocation_service as alloc
from agent.services import production_copy_supply_service as supply
from agent.services import production_supply_manifest_service as manifest_service
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


async def _count(table: str) -> int:
    db = await get_db()
    return (await (await db.execute(f"SELECT COUNT(*) FROM {table}")).fetchone())[0]


async def _drift_truth(product_id: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        f"VALUES ('{product_id}-snap2','{product_id}',2,'APPROVED','Newer.', "
        "'[\"nb\"]','[\"nu\"]','nc','[\"ncl\"]','{\"a\":1}','{\"f\":\"PAS\"}','CLAIM_SAFE','LOW', "
        "'2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()


@pytest.mark.asyncio
async def test_materialization_is_deterministic_unique_and_no_dup_on_rerun(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "scale-det")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_ids = await _approved_projection_ids(result["master"]["entity_id"])
    assert len(projection_ids) == 3

    async def _materialize_all() -> list[str]:
        return [
            (await supply.materialize(projection_id=pid, receipt_id=receipt_id))["link_id"]
            for pid in projection_ids
        ]

    first = await _materialize_all()
    second = await _materialize_all()  # rerun must be a no-op (idempotent)
    assert first == second                       # deterministic link ids
    assert len(set(first)) == 3                   # one unique link per projection
    assert await _count("copy_blueprint_v2") == 3  # no duplicate blueprint rows
    assert await _count("materialization_link_v3") == 3


@pytest.mark.asyncio
async def test_opportunity_space_is_bounded_and_never_eager_materialized(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "scale-10k")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_ids = await _approved_projection_ids(result["master"]["entity_id"])
    for pid in projection_ids:
        await supply.materialize(projection_id=pid, receipt_id=receipt_id)

    # A realistic BOSMAX opportunity space: copy x avatar x scene x choreography x
    # opening x treatment x camera.  Simulate >= 10,000 unique-video opportunities.
    copy_supply = len(projection_ids)  # 3 executable copies
    avatars, scenes, choreo, openings, treatments, cameras = 12, 8, 4, 3, 4, 3
    opportunity_space = copy_supply * avatars * scenes * choreo * openings * treatments * cameras
    assert opportunity_space >= 10_000

    # The system materializes ONLY the copy dimension (3), never the 10k space.
    assert await _count("copy_blueprint_v2") == copy_supply
    capacity = await supply.production_capacity("scale-10k")
    assert capacity["executable_copy_capacity"] == copy_supply
    assert capacity["production_capacity"] == copy_supply  # not the 10k Cartesian

    # A manifest is bounded by requested capacity, not the supply or the space.
    built = await manifest_service.build_manifest("scale-10k", requested_capacity=2, actor_id="op")
    assert built["selected_count"] == 2
    assert await _count("manifest_item_v3") == 2
    # Reading capacity/landbank created no new blueprints (no eager materialization).
    assert await _count("copy_blueprint_v2") == copy_supply


@pytest.mark.asyncio
async def test_concurrent_materialization_converges_to_one_canonical_row(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "scale-concurrent")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = (await _approved_projection_ids(result["master"]["entity_id"]))[0]

    results = await asyncio.gather(
        *[supply.materialize(projection_id=projection_id, receipt_id=receipt_id) for _ in range(4)]
    )
    assert all(r["status"] == "MATERIALIZED" for r in results)
    assert len({r["blueprint_id"] for r in results}) == 1  # one canonical blueprint
    assert len({r["link_id"] for r in results}) == 1        # one canonical link
    assert await _count("copy_blueprint_v2") == 1
    assert await _count("materialization_link_v3") == 1


@pytest.mark.asyncio
async def test_invalidation_matrix_fails_closed_and_never_churns_pointer(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "scale-inval")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_ids = await _approved_projection_ids(result["master"]["entity_id"])
    for pid in projection_ids:
        await supply.materialize(projection_id=pid, receipt_id=receipt_id)
    built = await manifest_service.build_manifest("scale-inval", requested_capacity=3, actor_id="op")
    manifest = built["manifest"]
    await manifest_service.freeze_manifest(manifest.manifest_id, manifest.revision, actor_id="op")
    allocation = await alloc.allocate_from_manifest(
        manifest.manifest_id, manifest.revision,
        p6_plan_id="plan-inval", requested_items=1, actor_id="op",
    )
    selection = allocation["allocations"][0]["round3_manifest_item"]

    # Section 25/26: nothing above ever wrote the product-global activation pointer.
    assert await _count("copy_execution_authority_v2") == 0

    # Now advance Product Truth: every downstream authority check must fail closed.
    await _drift_truth("scale-inval")

    # capacity: executable drops to 0
    capacity = await supply.production_capacity("scale-inval")
    assert capacity["executable_copy_capacity"] == 0

    # landbank status: STALE
    payload = await svc.copy_register_landbank("scale-inval", status="APPROVED")
    enriched = await supply.enrich_landbank_payload(payload)
    statuses = [
        proj["materialization"]["status"]
        for item in enriched["items"]
        for proj in item["projections"]
    ]
    assert "STALE" in statuses

    # manifest freeze on a fresh rebuild: refuses stale items
    rebuilt = await manifest_service.build_manifest("scale-inval", requested_capacity=3, actor_id="op")
    assert rebuilt["selected_count"] == 0  # all stale, none selected

    # queue/start revalidation on the earlier allocation: fails closed
    reval = await alloc.revalidate_item_selection(selection)
    assert reval["valid"] is False
    # Round 3 now revalidates via the full shared V2 authority validator, which
    # surfaces the precise V2 authority reason (taxonomy/evidence staleness) on a
    # Product-Truth advance rather than the old shallow "PRODUCT_TRUTH_ADVANCED".
    assert reval["reason"] in {
        "PRODUCT_TRUTH_ADVANCED",
        "COPY_V2_TAXONOMY_AUTHORITY_STALE",
        "COPY_V2_EVIDENCE_STALE",
        "COPY_V2_EVIDENCE_NOT_FOUND",
    }

    # still no pointer churn after all of this.
    assert await _count("copy_execution_authority_v2") == 0
