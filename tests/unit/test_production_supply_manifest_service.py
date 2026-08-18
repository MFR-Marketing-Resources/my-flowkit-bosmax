"""Macro Round 3 P4 — Production Copy Supply Manifest coverage.

Zero provider, zero credit, disposable DB.  Proves a manifest is built ONLY from
materialized + production-valid + current supply, that stale supply is blocked
(never silently dropped), that a frozen manifest + its item set are immutable, and
that changed supply yields a new revision rather than a mutation.
"""

from __future__ import annotations

import sqlite3

import pytest

from agent.db.schema import get_db
from agent.services import production_supply_manifest_service as manifest_service
from agent.services import production_copy_supply_service as supply
from agent.services.production_supply_manifest_service import ManifestError
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


async def _materialize_all(master_id: str, receipt_id: str) -> int:
    count = 0
    for projection_id in await _approved_projection_ids(master_id):
        await supply.materialize(projection_id=projection_id, receipt_id=receipt_id)
        count += 1
    return count


async def _drift_truth(product_id: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, product_description, benefits_json, usp_json, "
        "target_customer_text, allowed_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json, "
        "claim_gate, claim_risk_level, created_at, updated_at) "
        f"VALUES ('{product_id}-snap2','{product_id}',2,'APPROVED','Newer.', "
        "'[\"newer benefit\"]','[\"newer usp\"]','newer customer','[\"newer claim\"]','{\"a\":1}','{\"f\":\"PAS\"}', "
        "'CLAIM_SAFE','LOW','2026-08-18T00:00:00Z','2026-08-18T00:00:00Z')",
    )
    await db.commit()


@pytest.mark.asyncio
async def test_build_manifest_includes_only_materialized_supply(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "man-build")
    receipt_id = approval["receipt"]["receipt_id"]
    materialized = await _materialize_all(result["master"]["entity_id"], receipt_id)
    assert materialized == 3  # 8/16/24s

    outcome = await manifest_service.build_manifest(
        "man-build", requested_capacity=5, actor_id="op"
    )
    manifest = outcome["manifest"]
    assert manifest.status == "DRAFT"
    assert outcome["selected_count"] == 3
    assert outcome["blocked_count"] == 0
    assert outcome["shortfall"] == 2  # requested 5, only 3 clean assets
    assert len(manifest.manifest_digest) == 64
    # Every item points to a real PRODUCTION_VALID blueprint + approval snapshot.
    for item in outcome["items"]:
        assert item.v2_blueprint_id and item.v2_approval_snapshot_id
        assert item.materialization_link_id
        assert item.approval_receipt_id == receipt_id


@pytest.mark.asyncio
async def test_build_manifest_blocks_stale_supply(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "man-stale")
    receipt_id = approval["receipt"]["receipt_id"]
    await _materialize_all(result["master"]["entity_id"], receipt_id)
    await _drift_truth("man-stale")

    outcome = await manifest_service.build_manifest(
        "man-stale", requested_capacity=5, actor_id="op"
    )
    assert outcome["selected_count"] == 0
    assert outcome["blocked_count"] == 3
    assert all(b["reason"] == "PRODUCT_TRUTH_ADVANCED" for b in outcome["blocked"])


@pytest.mark.asyncio
async def test_freeze_makes_manifest_and_items_immutable(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "man-freeze")
    receipt_id = approval["receipt"]["receipt_id"]
    await _materialize_all(result["master"]["entity_id"], receipt_id)
    built = await manifest_service.build_manifest("man-freeze", requested_capacity=3, actor_id="op")
    manifest = built["manifest"]

    frozen = await manifest_service.freeze_manifest(
        manifest.manifest_id, manifest.revision, actor_id="op"
    )
    assert frozen["manifest"].status == "FROZEN"

    db = await get_db()
    # Header immutable.
    with pytest.raises(sqlite3.IntegrityError, match="PRODUCTION_COPY_SUPPLY_MANIFEST_V3_IMMUTABLE"):
        await db.execute(
            "UPDATE production_copy_supply_manifest_v3 SET requested_capacity=9 "
            "WHERE manifest_id=? AND revision=?",
            (manifest.manifest_id, manifest.revision),
        )
    await db.rollback()
    # Existing items immutable.
    with pytest.raises(sqlite3.IntegrityError, match="MANIFEST_ITEM_V3_IMMUTABLE"):
        await db.execute(
            "DELETE FROM manifest_item_v3 WHERE manifest_id=? AND manifest_revision=?",
            (manifest.manifest_id, manifest.revision),
        )
    await db.rollback()
    # A frozen manifest cannot gain a new item either.
    with pytest.raises(sqlite3.IntegrityError, match="MANIFEST_ITEM_V3_IMMUTABLE"):
        await db.execute(
            "INSERT INTO manifest_item_v3 (item_id, manifest_id, manifest_revision, item_index, "
            "product_id, master_id, master_revision, projection_id, projection_revision, "
            "projection_exact_digest, approval_receipt_id, materialization_link_id, "
            "materialization_link_revision, v2_blueprint_id, v2_blueprint_revision, "
            "v2_approval_snapshot_id, product_truth_snapshot_digest, formula_id, formula_version, "
            "duration_seconds, item_digest, created_at, created_by) VALUES "
            "('rogue', ?, ?, 99, 'man-freeze', 'm', 1, 'p', 1, ?, 'r', 'l', 1, 'b', 3, 'a', ?, 'PAS', 'fv', 8, ?, 'now', 'x')",
            (manifest.manifest_id, manifest.revision, "a" * 64, "a" * 64, "a" * 64),
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_freeze_refuses_when_an_item_went_stale(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "man-freezestale")
    receipt_id = approval["receipt"]["receipt_id"]
    await _materialize_all(result["master"]["entity_id"], receipt_id)
    built = await manifest_service.build_manifest("man-freezestale", requested_capacity=3, actor_id="op")
    manifest = built["manifest"]

    await _drift_truth("man-freezestale")  # items now stale
    with pytest.raises(ManifestError) as excinfo:
        await manifest_service.freeze_manifest(manifest.manifest_id, manifest.revision, actor_id="op")
    assert excinfo.value.code == "MANIFEST_ITEM_STALE"
    # Manifest stays DRAFT (not frozen) so it can be rebuilt.
    reloaded = await manifest_service.get_manifest_view(manifest.manifest_id, manifest.revision)
    assert reloaded["manifest"].status == "DRAFT"


@pytest.mark.asyncio
async def test_rebuild_creates_new_revision(monkeypatch):
    svc, result, approval = await _approved_supply(monkeypatch, "man-rev")
    receipt_id = approval["receipt"]["receipt_id"]
    await _materialize_all(result["master"]["entity_id"], receipt_id)

    first = await manifest_service.build_manifest("man-rev", requested_capacity=3, actor_id="op")
    second = await manifest_service.build_manifest("man-rev", requested_capacity=3, actor_id="op")
    assert first["manifest"].manifest_id == second["manifest"].manifest_id
    assert first["manifest"].revision == 1
    assert second["manifest"].revision == 2


@pytest.mark.asyncio
async def test_manifest_insert_rolls_back_on_partial_item_failure():
    """A mid-transaction item INSERT failure must roll back the whole manifest —
    never leave a committed header whose counts overstate persisted items."""
    from agent.models.storyboard_landbank_v3_round3 import (
        ManifestItemV3,
        ProductionCopySupplyManifestV3,
    )
    from agent.services import production_supply_repository as repo

    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name, lifecycle_status) "
        "VALUES ('rollback-prod','t','d','s','ACTIVE')"
    )
    await db.commit()
    d = "a" * 64
    now = "2026-08-18T00:00:00Z"
    manifest = ProductionCopySupplyManifestV3(
        manifest_id="rollback-man", revision=1, product_id="rollback-prod",
        recipe_policy_version="p", source_authority_digest=d, manifest_digest=d,
        status="DRAFT", source="t", created_at=now, created_by="t",
    )
    # Non-existent materialization_link + receipt FK targets -> item INSERT aborts.
    bad_item = ManifestItemV3(
        item_id="rollback-item", manifest_id="rollback-man", manifest_revision=1,
        item_index=0, product_id="rollback-prod", master_id="m", master_revision=1,
        projection_id="p", projection_revision=1, projection_exact_digest=d,
        approval_receipt_id="nonexistent-receipt", materialization_link_id="nonexistent-link",
        materialization_link_revision=1, v2_blueprint_id="b", v2_blueprint_revision=1,
        v2_approval_snapshot_id="s", product_truth_snapshot_digest=d, formula_id="PAS",
        formula_version="fv", duration_seconds=8, item_digest=d, created_at=now, created_by="t",
    )
    with pytest.raises(sqlite3.IntegrityError):
        await repo.insert_manifest_with_items(manifest, [bad_item])
    # Rolled back: the header is not left committed on the shared connection.
    assert await repo.get_manifest("rollback-man", 1) is None
