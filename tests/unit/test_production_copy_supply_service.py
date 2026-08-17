"""Macro Round 3 P3 — Approved Landbank materialization status + actions.

Zero provider calls, zero credit, disposable DB.  Proves truthful landbank status
(NOT_MATERIALIZED -> MATERIALIZED -> STALE), no materialization on read, bounded
bulk with partial success, and fail-closed bulk limit.
"""

from __future__ import annotations

import pytest

from agent.db.schema import get_db
from agent.services import production_copy_supply_service as supply
from agent.services.storyboard_landbank_v3_materializer import MaterializationError
from tests.unit.test_storyboard_landbank_v3_materializer import (
    _approved_supply,
    _first_projection_id,
)


async def _enriched_landbank(svc, product_id: str) -> dict:
    payload = await svc.copy_register_landbank(product_id, status="APPROVED")
    return await supply.enrich_landbank_payload(payload)


def _projection_statuses(payload: dict) -> list[str]:
    statuses: list[str] = []
    for item in payload["items"]:
        for projection in item["projections"]:
            statuses.append(projection["materialization"]["status"])
    return statuses


@pytest.mark.asyncio
async def test_landbank_reports_not_materialized_and_does_not_materialize_on_read(monkeypatch):
    svc, result, _approval = await _approved_supply(monkeypatch, "p3-status")
    before = await _enriched_landbank(svc, "p3-status")

    assert before["items"]
    assert all(s == "NOT_MATERIALIZED" for s in _projection_statuses(before))
    assert before["items"][0]["v2_materialization"] == "NOT_MATERIALIZED"
    # Reading the landbank must NOT create any V2 blueprint or link.
    db = await get_db()
    blueprints = (await (await db.execute("SELECT COUNT(*) FROM copy_blueprint_v2")).fetchone())[0]
    links = (await (await db.execute("SELECT COUNT(*) FROM materialization_link_v3")).fetchone())[0]
    assert blueprints == 0 and links == 0


@pytest.mark.asyncio
async def test_landbank_status_becomes_materialized_after_explicit_materialize(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "p3-materialize")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(result["master"]["entity_id"])

    outcome = await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
    assert outcome["status"] == "MATERIALIZED"
    assert outcome["blueprint_status"] == "PRODUCTION_VALID"

    after = await _enriched_landbank(svc, "p3-materialize")
    assert "MATERIALIZED" in _projection_statuses(after)


@pytest.mark.asyncio
async def test_landbank_status_becomes_stale_after_product_truth_drift(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "p3-stale")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(result["master"]["entity_id"])
    await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)

    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('p3-stale-snap2','p3-stale',2,'APPROVED','Newer.', "
        "'[\"newer benefit\"]','[\"newer usp\"]','newer customer','[\"newer claim\"]','{\"a\":1}','{\"f\":\"PAS\"}', "
        "'CLAIM_SAFE','LOW','2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()

    after = await _enriched_landbank(svc, "p3-stale")
    assert "STALE" in _projection_statuses(after)


@pytest.mark.asyncio
async def test_materialize_bulk_is_bounded_and_partial_success(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "p3-bulk")
    receipt_id = approval["receipt"]["receipt_id"]
    projection_id = await _first_projection_id(result["master"]["entity_id"])

    outcome = await supply.materialize_bulk(
        [
            {"projection_id": projection_id, "receipt_id": receipt_id},
            {"projection_id": projection_id, "receipt_id": "receipt-does-not-exist"},
        ]
    )
    assert outcome["requested"] == 2
    assert outcome["materialized_count"] == 1
    assert outcome["blocked_count"] == 1
    assert outcome["blocked"][0]["code"] == "MATERIALIZATION_RECEIPT_NOT_FOUND"


@pytest.mark.asyncio
async def test_materialize_bulk_rejects_over_limit():
    requests = [
        {"projection_id": f"proj-{index}", "receipt_id": "receipt"}
        for index in range(supply.MAX_BULK_MATERIALIZE + 1)
    ]
    with pytest.raises(MaterializationError) as excinfo:
        await supply.materialize_bulk(requests)
    assert excinfo.value.code == "MATERIALIZATION_BULK_LIMIT_EXCEEDED"


@pytest.mark.asyncio
async def test_production_capacity_reports_four_tiers(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "cap-4tier")
    receipt_id = approval["receipt"]["receipt_id"]

    before = await supply.production_capacity("cap-4tier")
    assert before["semantic_capacity"] >= 1           # approved master(s)
    assert before["projection_capacity"] == 3          # 8/16/24s approved projections
    assert before["executable_copy_capacity"] == 0     # nothing materialized yet
    assert before["production_capacity"] == 0

    projection_id = await _first_projection_id(result["master"]["entity_id"])
    await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
    after = await supply.production_capacity("cap-4tier")
    assert after["executable_copy_capacity"] == 1
    assert after["production_capacity"] == 1            # NOT a Cartesian blow-up

    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        "VALUES ('cap-4tier-snap2','cap-4tier',2,'APPROVED','Newer.', "
        "'[\"nb\"]','[\"nu\"]','nc','[\"ncl\"]','{\"a\":1}','{\"f\":\"PAS\"}','CLAIM_SAFE','LOW', "
        "'2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()
    stale = await supply.production_capacity("cap-4tier")
    assert stale["executable_copy_capacity"] == 0      # materialization went stale
    assert stale["stale_copy_count"] == 1
