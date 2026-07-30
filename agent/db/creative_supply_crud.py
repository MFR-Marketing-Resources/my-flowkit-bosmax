"""Durable CRUD for the P7 creative-supply state machine.

This module is intentionally separate from the generic column-whitelist CRUD:
every transition names its columns explicitly and writes through the shared
SQLite lock. Product Truth and P6 production tables are read-only here.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from agent.db import schema
from agent.db.schema import _db_lock, get_db


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _hydrate_run(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    for key in ("roster_json", "angle_plan_json", "target_policy_json"):
        item[key.removesuffix("_json")] = decode(item.get(key), [] if key != "target_policy_json" else {})
    return item


def _hydrate_task(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["provider_receipt"] = decode(item.get("provider_receipt_json"), {})
    item["result"] = decode(item.get("result_json"), {})
    return item


async def create_run(
    *,
    mission_id: str,
    roster_sha256: str,
    cohort_sha256: str,
    roster: list[dict[str, Any]],
    angle_plan: list[dict[str, Any]],
    target_policy: dict[str, Any],
    provider_budget_max: int,
    reviewer_id: str,
) -> dict[str, Any]:
    db = await get_db()
    run_id = new_id("csr")
    now = utc_now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO creative_supply_run (
                run_id, mission_id, roster_sha256, cohort_sha256, roster_json,
                angle_plan_json, target_policy_json, state, provider_budget_max,
                provider_calls_used, reviewer_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,'READY',?,0,?,?,?)
            """,
            (
                run_id,
                mission_id,
                roster_sha256,
                cohort_sha256,
                encode(roster),
                encode(angle_plan),
                encode(target_policy),
                provider_budget_max,
                reviewer_id,
                now,
                now,
            ),
        )
        await db.commit()
    return (await get_run(run_id)) or {}


async def get_run(run_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM creative_supply_run WHERE run_id=?", (run_id,))
    return _hydrate_run(await cursor.fetchone())


async def list_runs() -> list[dict[str, Any]]:
    database_uri = f"{Path(schema.DB_PATH).resolve().as_uri()}?mode=ro"
    async with aiosqlite.connect(database_uri, uri=True) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA query_only=ON")
        await db.execute("PRAGMA busy_timeout=5000")
        cursor = await db.execute(
            """
            SELECT
                run_id,
                mission_id,
                roster_sha256,
                cohort_sha256,
                state,
                provider_budget_max,
                provider_calls_used,
                reviewer_id,
                pause_reason,
                last_error,
                created_at,
                updated_at
            FROM creative_supply_run
            ORDER BY created_at DESC, run_id DESC
            """
        )
        return [dict(row) for row in await cursor.fetchall()]


async def update_run(run_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "state",
        "provider_calls_used",
        "pause_reason",
        "last_error",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return await get_run(run_id)
    values["updated_at"] = utc_now()
    sets = ", ".join(f"{key}=?" for key in values)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"UPDATE creative_supply_run SET {sets} WHERE run_id=?",
            (*values.values(), run_id),
        )
        await db.commit()
    return await get_run(run_id)


async def increment_provider_calls(run_id: str, count: int) -> dict[str, Any] | None:
    if count <= 0:
        return await get_run(run_id)
    db = await get_db()
    now = utc_now()
    async with _db_lock:
        await db.execute(
            """
            UPDATE creative_supply_run
               SET provider_calls_used=provider_calls_used+?, updated_at=?
             WHERE run_id=?
            """,
            (count, now, run_id),
        )
        await db.commit()
    return await get_run(run_id)


async def create_task(
    *,
    run_id: str,
    product_id: str,
    angle_key: str,
    angle_label: str,
    component_type: str,
    deficit_round: int,
    target_approved_count: int,
    requested_count: int,
    idempotency_key: str,
    task_kind: str = "AUTHOR_DEFICIT",
    state: str = "PENDING",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db = await get_db()
    task_id = new_id("cst")
    now = utc_now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO creative_supply_task (
                task_id, run_id, product_id, angle_key, angle_label,
                component_type, task_kind, deficit_round, target_approved_count,
                requested_count, state, idempotency_key, result_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                task_id,
                run_id,
                product_id,
                angle_key,
                angle_label,
                component_type,
                task_kind,
                deficit_round,
                target_approved_count,
                requested_count,
                state,
                idempotency_key,
                encode(result or {}),
                now,
                now,
            ),
        )
        await db.commit()
    return (await get_task(task_id)) or {}


async def get_task(task_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_supply_task WHERE task_id=?", (task_id,)
    )
    return _hydrate_task(await cursor.fetchone())


async def list_tasks(run_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM creative_supply_task
         WHERE run_id=?
         ORDER BY created_at, product_id, angle_key, component_type, deficit_round
        """,
        (run_id,),
    )
    return [_hydrate_task(row) or {} for row in await cursor.fetchall()]


async def next_pending_task(run_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM creative_supply_task
         WHERE run_id=? AND state='PENDING'
         ORDER BY created_at, product_id, angle_key, component_type, deficit_round
         LIMIT 1
        """,
        (run_id,),
    )
    return _hydrate_task(await cursor.fetchone())


async def claim_next_pending_task(run_id: str) -> dict[str, Any] | None:
    """Atomically claim one task across threads and worker processes."""
    db = await get_db()
    now = utc_now()
    async with _db_lock:
        cursor = await db.execute(
            """
            UPDATE creative_supply_task
               SET state='RUNNING',
                   attempt_count=attempt_count+1,
                   updated_at=?
             WHERE task_id=(
                 SELECT task_id FROM creative_supply_task
                  WHERE run_id=? AND state='PENDING'
                  ORDER BY created_at, product_id, angle_key,
                           component_type, deficit_round
                  LIMIT 1
             )
               AND state='PENDING'
            RETURNING *
            """,
            (now, run_id),
        )
        row = await cursor.fetchone()
        await db.commit()
    return _hydrate_task(row)


async def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {
        "state",
        "attempt_count",
        "provider_call_count",
        "transient_failure_proven",
        "provider_receipt_json",
        "result_json",
        "last_error",
    }
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return await get_task(task_id)
    values["updated_at"] = utc_now()
    sets = ", ".join(f"{key}=?" for key in values)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"UPDATE creative_supply_task SET {sets} WHERE task_id=?",
            (*values.values(), task_id),
        )
        await db.commit()
    return await get_task(task_id)


async def create_review_event(
    *,
    run_id: str,
    task_id: str,
    component_id: str,
    product_id: str,
    angle_key: str,
    component_type: str,
    decision: str,
    reviewed_content_sha256: str,
    reasons: list[str],
    safety: dict[str, Any],
    provider_provenance: dict[str, Any],
    reviewer_id: str,
) -> dict[str, Any]:
    db = await get_db()
    event_id = new_id("csre")
    reviewed_at = utc_now()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO creative_supply_review_event (
                event_id, run_id, task_id, component_id, product_id, angle_key,
                component_type, decision, reviewed_content_sha256, reasons_json,
                safety_json, provider_provenance_json, reviewer_id, reviewed_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id,
                run_id,
                task_id,
                component_id,
                product_id,
                angle_key,
                component_type,
                decision,
                reviewed_content_sha256,
                encode(reasons),
                encode(safety),
                encode(provider_provenance),
                reviewer_id,
                reviewed_at,
            ),
        )
        await db.commit()
    cursor = await db.execute(
        "SELECT * FROM creative_supply_review_event WHERE event_id=?", (event_id,)
    )
    row = await cursor.fetchone()
    item = dict(row)
    item["reasons"] = decode(item.get("reasons_json"), [])
    item["safety"] = decode(item.get("safety_json"), {})
    item["provider_provenance"] = decode(item.get("provider_provenance_json"), {})
    return item


async def record_review_and_update_component(
    *,
    run_id: str,
    task_id: str,
    component: dict[str, Any],
    decision: str,
    reviewed_content_sha256: str,
    reasons: list[str],
    safety: dict[str, Any],
    provider_provenance: dict[str, Any],
    reviewer_id: str,
    expected_statuses: tuple[str, ...] = ("COMPONENT_REVIEW_REQUIRED",),
) -> dict[str, Any]:
    """Atomically persist the review event and component state transition."""
    db = await get_db()
    event_id = new_id("csre")
    reviewed_at = utc_now()
    component_id = str(component["component_id"])
    target_status = "COMPONENT_APPROVED" if decision == "APPROVED" else "COMPONENT_REJECTED"
    reviewer_note = "; ".join(reasons)
    if not expected_statuses:
        raise ValueError("EXPECTED_COMPONENT_STATUS_REQUIRED")
    status_placeholders = ",".join("?" for _ in expected_statuses)
    async with _db_lock:
        try:
            await db.execute(
                f"""
                UPDATE copy_component
                   SET status=?, claim_review_json=?, provenance_json=?,
                       reviewer_note=?, approved_at=?, approved_by=?, updated_at=?
                 WHERE component_id=? AND status IN ({status_placeholders})
                """,
                (
                    target_status,
                    encode({"safety": safety, "decision": decision, "reasons": reasons}),
                    encode(provider_provenance),
                    reviewer_note,
                    reviewed_at if decision == "APPROVED" else None,
                    reviewer_id if decision == "APPROVED" else None,
                    reviewed_at,
                    component_id,
                    *expected_statuses,
                ),
            )
            changed = await db.execute("SELECT changes()")
            if int((await changed.fetchone())[0]) != 1:
                raise ValueError("COMPONENT_NOT_REVIEW_REQUIRED")
            await db.execute(
                """
                INSERT INTO creative_supply_review_event (
                    event_id, run_id, task_id, component_id, product_id, angle_key,
                    component_type, decision, reviewed_content_sha256, reasons_json,
                    safety_json, provider_provenance_json, reviewer_id, reviewed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    run_id,
                    task_id,
                    component_id,
                    str(component["product_id"]),
                    str(component["angle_key"]),
                    str(component["component_type"]),
                    decision,
                    reviewed_content_sha256,
                    encode(reasons),
                    encode(safety),
                    encode(provider_provenance),
                    reviewer_id,
                    reviewed_at,
                ),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    cursor = await db.execute(
        "SELECT * FROM creative_supply_review_event WHERE event_id=?", (event_id,)
    )
    row = await cursor.fetchone()
    item = dict(row)
    item["reasons"] = decode(item.get("reasons_json"), [])
    item["safety"] = decode(item.get("safety_json"), {})
    item["provider_provenance"] = decode(item.get("provider_provenance_json"), {})
    return item


async def list_review_events(run_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM creative_supply_review_event
         WHERE run_id=?
         ORDER BY reviewed_at, event_id
        """,
        (run_id,),
    )
    items = []
    for row in await cursor.fetchall():
        item = dict(row)
        item["reasons"] = decode(item.get("reasons_json"), [])
        item["safety"] = decode(item.get("safety_json"), {})
        item["provider_provenance"] = decode(item.get("provider_provenance_json"), {})
        items.append(item)
    return items
