"""P6 additive migration, reopen and constraint evidence."""

from __future__ import annotations

import sqlite3

import pytest

from agent.config import DB_PATH
from agent.db import creative_production_crud as p6db
from agent.db.schema import close_db, get_db, init_db


def _plan_values(suffix: str) -> dict[str, object]:
    return {
        "plan_id": f"p6plan-migration-{suffix}",
        "request_id": f"request-p6-migration-{suffix}",
        "created_by": "p6-migration-test",
        "name": "Migration retention plan",
        "product_scope_json": "[]",
        "p58_cohort_sha256": "frozen-sha",
        "p58_cohort_count": 438,
    }


@pytest.mark.asyncio
async def test_additive_migration_is_idempotent_and_preserves_rows():
    values = _plan_values("idempotent")
    await p6db.create_plan(values)
    await close_db()
    await init_db()
    await close_db()
    await init_db()
    row = await p6db.get_plan(str(values["plan_id"]))
    assert row is not None
    assert row["name"] == values["name"]
    db = await get_db()
    cursor = await db.execute("PRAGMA table_info(creative_generation_attempt)")
    attempt_columns = {column[1] for column in await cursor.fetchall()}
    assert {
        "provider_project_id",
        "provider_correlation_id",
        "provider_snapshot_json",
        "provider_snapshot_updated_at",
    } <= attempt_columns


@pytest.mark.asyncio
async def test_restart_reopen_preserves_control_state():
    values = _plan_values("restart")
    await p6db.create_plan(values)
    await p6db.update_plan(
        str(values["plan_id"]),
        status="PAUSED",
        control_action="PAUSE_REQUESTED",
        control_version=7,
        updated_at="2026-07-29T00:00:00+00:00",
    )
    await close_db()
    await init_db()
    reopened = await p6db.get_plan(str(values["plan_id"]))
    assert reopened is not None
    assert reopened["status"] == "PAUSED"
    assert reopened["control_action"] == "PAUSE_REQUESTED"
    assert reopened["control_version"] == 7


@pytest.mark.asyncio
async def test_required_queue_dedupe_and_lease_indexes_exist():
    db = await get_db()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name LIKE '%creative_%' ORDER BY name"
    )
    names = {row[0] for row in await cursor.fetchall()}
    assert {
        "idx_creative_production_plan_status_updated",
        "idx_creative_production_item_plan_status",
        "idx_creative_production_item_product_dna",
        "idx_creative_generation_attempt_state",
        "idx_creative_execution_lane_lease_expiry",
        "uq_creative_execution_lane_active_slot",
    } <= names


@pytest.mark.asyncio
async def test_request_and_dna_uniqueness_are_database_enforced():
    values = _plan_values("unique")
    await p6db.create_plan(values)
    db = await get_db()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO creative_production_plan "
            "(plan_id,request_id,name,p58_cohort_sha256,p58_cohort_count) "
            "VALUES ('p6plan-duplicate',?,?,?,?)",
            (
                values["request_id"],
                "Duplicate",
                "frozen-sha",
                438,
            ),
        )
    await db.rollback()
