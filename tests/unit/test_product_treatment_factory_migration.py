import sqlite3
import uuid

import pytest
import pytest_asyncio

from agent.db import crud
from agent.db import product_treatment_factory_crud as factory_crud
from agent.db.schema import close_db, get_db, init_db


@pytest_asyncio.fixture(autouse=True)
async def _clean_factory_tables():
    await init_db()
    db = await get_db()
    await db.execute("DELETE FROM product_treatment_factory_event")
    await db.execute("DELETE FROM product_treatment_factory_task")
    await db.execute("DELETE FROM product_treatment_factory_plan")
    await db.commit()
    yield
    db = await get_db()
    await db.execute("DELETE FROM product_treatment_factory_event")
    await db.execute("DELETE FROM product_treatment_factory_task")
    await db.execute("DELETE FROM product_treatment_factory_plan")
    await db.commit()


async def _create_plan(identity: str = "a" * 64):
    return await factory_crud.create_or_get_plan(
        plan_identity_sha256=identity,
        cohort_sha256="b" * 64,
        context_sha256="c" * 64,
        product_count=1,
        request={"products": [{"product_id": "migration-product"}]},
        authority_versions={"factory_version": "test-v1"},
        created_by="migration-test",
    )


@pytest.mark.asyncio
async def test_additive_migration_is_idempotent_and_has_no_backfill():
    await init_db()
    await init_db()
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE name LIKE 'product_treatment_factory_%'
           OR name LIKE 'idx_product_treatment_factory_%'
        ORDER BY type, name
        """
    )
    objects = {(row["type"], row["name"]) for row in await cursor.fetchall()}

    assert {
        ("table", "product_treatment_factory_plan"),
        ("table", "product_treatment_factory_task"),
        ("table", "product_treatment_factory_event"),
        ("index", "idx_product_treatment_factory_plan_status"),
        ("index", "idx_product_treatment_factory_task_plan_status"),
        ("index", "idx_product_treatment_factory_task_product_type"),
        ("index", "idx_product_treatment_factory_event_plan"),
    }.issubset(objects)
    for table in (
        "product_treatment_factory_plan",
        "product_treatment_factory_task",
        "product_treatment_factory_event",
    ):
        count = await db.execute_fetchall(f"SELECT COUNT(*) AS count FROM {table}")
        assert count[0]["count"] == 0


@pytest.mark.asyncio
async def test_plan_and_task_survive_database_reopen_without_duplicates():
    plan, plan_created = await _create_plan()
    task, task_created = await factory_crud.create_or_get_task(
        plan_id=str(plan["plan_id"]),
        product_id="migration-product",
        task_type="PRODUCT_TRUTH_REVIEW",
        status="REVIEW_REQUIRED",
        task_identity_sha256="d" * 64,
        required_authority_sha256="e" * 64,
        blocker_code="PRODUCT_TRUTH_REQUIRED",
        next_action="REVIEW_PRODUCT_TRUTH",
        template_id=None,
        template_sha256=None,
        snapshot={"proof": "durable"},
    )
    same_plan, duplicate_plan_created = await _create_plan()
    same_task, duplicate_task_created = await factory_crud.create_or_get_task(
        plan_id=str(plan["plan_id"]),
        product_id="migration-product",
        task_type="PRODUCT_TRUTH_REVIEW",
        status="REVIEW_REQUIRED",
        task_identity_sha256="d" * 64,
        required_authority_sha256="e" * 64,
        blocker_code="PRODUCT_TRUTH_REQUIRED",
        next_action="REVIEW_PRODUCT_TRUTH",
        template_id=None,
        template_sha256=None,
        snapshot={"proof": "durable"},
    )

    await close_db()
    await init_db()
    reopened_plan = await factory_crud.get_plan(str(plan["plan_id"]))
    reopened_task = await factory_crud.get_task(str(task["task_id"]))

    assert plan_created is True
    assert task_created is True
    assert duplicate_plan_created is False
    assert duplicate_task_created is False
    assert same_plan["plan_id"] == plan["plan_id"]
    assert same_task["task_id"] == task["task_id"]
    assert reopened_plan is not None
    assert reopened_task is not None
    assert reopened_task["snapshot"] == {"proof": "durable"}


@pytest.mark.asyncio
async def test_list_plans_supports_optional_status_filter():
    scanned_plan, _ = await _create_plan("1" * 64)
    draft_plan, _ = await _create_plan("2" * 64)
    await factory_crud.update_plan(str(scanned_plan["plan_id"]), status="SCANNED")

    all_plans = await factory_crud.list_plans(limit=10)
    scanned_plans = await factory_crud.list_plans(status="SCANNED", limit=10)
    missing_plans = await factory_crud.list_plans(status="COMPLETED", limit=10)

    assert {row["plan_id"] for row in all_plans} == {
        scanned_plan["plan_id"],
        draft_plan["plan_id"],
    }
    assert [row["plan_id"] for row in scanned_plans] == [scanned_plan["plan_id"]]
    assert missing_plans == []


@pytest.mark.asyncio
async def test_fail_closed_constraints_reject_unsafe_flags_and_invalid_lifecycles():
    plan, _ = await _create_plan()
    task, _ = await factory_crud.create_or_get_task(
        plan_id=str(plan["plan_id"]),
        product_id="migration-product",
        task_type="PRODUCT_TRUTH_REVIEW",
        status="PENDING",
        task_identity_sha256="d" * 64,
        required_authority_sha256="e" * 64,
        blocker_code=None,
        next_action=None,
        template_id=None,
        template_sha256=None,
        snapshot={},
    )
    db = await get_db()

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE product_treatment_factory_plan SET provider_calls_enabled=1 WHERE plan_id=?",
            (plan["plan_id"],),
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE product_treatment_factory_plan SET status='INVALID' WHERE plan_id=?",
            (plan["plan_id"],),
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE product_treatment_factory_task SET task_type='PROVIDER_CALL' WHERE task_id=?",
            (task["task_id"],),
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE product_treatment_factory_task SET status='APPROVED' WHERE task_id=?",
            (task["task_id"],),
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_migration_preserves_existing_product_and_database_integrity():
    marker = f"factory-migration-{uuid.uuid4().hex}"
    product = await crud.create_product(marker, source="MANUAL")

    await init_db()
    await init_db()
    retained = await crud.get_product(str(product["id"]))
    db = await get_db()
    integrity = await db.execute_fetchall("PRAGMA integrity_check")
    foreign_keys = await db.execute_fetchall("PRAGMA foreign_key_check")

    assert retained is not None
    assert retained["raw_product_title"] == marker
    assert integrity[0][0] == "ok"
    assert foreign_keys == []
    await db.execute("DELETE FROM product WHERE id=?", (product["id"],))
    await db.commit()
