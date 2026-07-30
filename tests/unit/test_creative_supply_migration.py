from __future__ import annotations

import asyncio
import sqlite3

import pytest

from agent.db import creative_supply_crud as supply_db
from agent.db.schema import close_db, get_db, init_db


async def _seed_product(product_id: str = "p7-product") -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO product (
            id, raw_product_title, product_display_name, product_short_name,
            lifecycle_status
        ) VALUES (?,?,?,?,'ACTIVE')
        """,
        (product_id, "P7 Product", "P7 Product", "P7 Product"),
    )
    await db.commit()


@pytest.mark.asyncio
async def test_p7_additive_tables_and_indexes_are_idempotent():
    await close_db()
    await init_db()
    await close_db()
    await init_db()
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT name, type FROM sqlite_master
         WHERE name LIKE '%creative_supply%'
         ORDER BY name
        """
    )
    objects = {(row[0], row[1]) for row in await cursor.fetchall()}
    assert {
        ("creative_supply_run", "table"),
        ("creative_supply_task", "table"),
        ("creative_supply_review_event", "table"),
        ("idx_creative_supply_run_state", "index"),
        ("idx_creative_supply_task_next", "index"),
        ("idx_creative_supply_task_slot", "index"),
        ("idx_creative_supply_review_product", "index"),
    } <= objects


@pytest.mark.asyncio
async def test_p7_run_and_task_survive_reopen():
    await _seed_product()
    run = await supply_db.create_run(
        mission_id="BOSMAX-P7-MIGRATION",
        roster_sha256="a" * 64,
        cohort_sha256="b" * 64,
        roster=[{"product_id": "p7-product"}],
        angle_plan=[{"product_id": "p7-product", "angle_key": "angle-1"}],
        target_policy={"TOP10": {"components": {"HOOK": 5}}},
        provider_budget_max=120,
        reviewer_id="codex-p7-reviewer",
    )
    task = await supply_db.create_task(
        run_id=str(run["run_id"]),
        product_id="p7-product",
        angle_key="angle-1",
        angle_label="Angle 1",
        component_type="HOOK",
        deficit_round=1,
        target_approved_count=5,
        requested_count=5,
        idempotency_key="p7-idempotency-key",
    )
    await supply_db.update_run(str(run["run_id"]), state="PAUSED", pause_reason="checkpoint")
    await supply_db.update_task(str(task["task_id"]), state="RETRY_ELIGIBLE", transient_failure_proven=1)

    await close_db()
    await init_db()

    reopened_run = await supply_db.get_run(str(run["run_id"]))
    reopened_task = await supply_db.get_task(str(task["task_id"]))
    assert reopened_run is not None
    assert reopened_run["state"] == "PAUSED"
    assert reopened_run["pause_reason"] == "checkpoint"
    assert reopened_task is not None
    assert reopened_task["state"] == "RETRY_ELIGIBLE"
    assert reopened_task["transient_failure_proven"] == 1


@pytest.mark.asyncio
async def test_p7_budget_and_task_idempotency_constraints_are_database_enforced():
    await _seed_product()
    db = await get_db()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            """
            INSERT INTO creative_supply_run (
                run_id, mission_id, roster_sha256, cohort_sha256, roster_json,
                angle_plan_json, target_policy_json, provider_budget_max, reviewer_id
            ) VALUES ('bad-budget','mission',?,?, '[]','[]','{}',121,'reviewer')
            """,
            ("a" * 64, "b" * 64),
        )
    await db.rollback()

    run = await supply_db.create_run(
        mission_id="BOSMAX-P7-CONSTRAINT",
        roster_sha256="a" * 64,
        cohort_sha256="b" * 64,
        roster=[{"product_id": "p7-product"}],
        angle_plan=[],
        target_policy={},
        provider_budget_max=120,
        reviewer_id="codex-p7-reviewer",
    )
    await supply_db.create_task(
        run_id=str(run["run_id"]),
        product_id="p7-product",
        angle_key="angle-1",
        angle_label="Angle 1",
        component_type="HOOK",
        deficit_round=1,
        target_approved_count=5,
        requested_count=5,
        idempotency_key="same-key",
    )
    with pytest.raises(sqlite3.IntegrityError):
        await supply_db.create_task(
            run_id=str(run["run_id"]),
            product_id="p7-product",
            angle_key="angle-1",
            angle_label="Angle 1",
            component_type="HOOK",
            deficit_round=2,
            target_approved_count=5,
            requested_count=5,
            idempotency_key="same-key",
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_p7_task_claim_is_atomic_and_never_returns_the_same_slot_twice():
    await _seed_product()
    run = await supply_db.create_run(
        mission_id="BOSMAX-P7-ATOMIC-CLAIM",
        roster_sha256="a" * 64,
        cohort_sha256="b" * 64,
        roster=[{"product_id": "p7-product"}],
        angle_plan=[],
        target_policy={},
        provider_budget_max=120,
        reviewer_id="codex-p7-reviewer",
    )
    for index, component_type in enumerate(("HOOK", "CTA"), start=1):
        await supply_db.create_task(
            run_id=str(run["run_id"]),
            product_id="p7-product",
            angle_key="angle-1",
            angle_label="Angle 1",
            component_type=component_type,
            deficit_round=1,
            target_approved_count=5,
            requested_count=5,
            idempotency_key=f"atomic-key-{index}",
        )
    first, second = await asyncio.gather(
        supply_db.claim_next_pending_task(str(run["run_id"])),
        supply_db.claim_next_pending_task(str(run["run_id"])),
    )
    assert first is not None and second is not None
    assert first["task_id"] != second["task_id"]
    assert first["state"] == second["state"] == "RUNNING"
    assert first["attempt_count"] == second["attempt_count"] == 1
    assert await supply_db.claim_next_pending_task(str(run["run_id"])) is None
