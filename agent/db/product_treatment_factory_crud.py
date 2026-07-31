"""Durable CRUD for the universal Product-to-Treatment Factory."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from agent.db.schema import _db_lock, get_db


_PLAN_JSON_FIELDS = {
    "request_json": "request",
    "authority_versions_json": "authority_versions",
    "readiness_summary_json": "readiness_summary",
    "capacity_summary_json": "capacity_summary",
}
_TASK_JSON_FIELDS = {
    "snapshot_json": "snapshot",
    "result_json": "result",
}
_PLAN_UPDATE_FIELDS = {
    "status",
    "readiness_summary_json",
    "capacity_summary_json",
    "failure_count",
    "pause_reason",
    "scanned_at",
    "preparation_started_at",
    "completed_at",
    "updated_at",
}
_TASK_UPDATE_FIELDS = {
    "status",
    "blocker_code",
    "next_action",
    "template_id",
    "template_sha256",
    "treatment_id",
    "treatment_sha256",
    "snapshot_json",
    "result_json",
    "error_code",
    "attempt_count",
    "started_at",
    "satisfied_at",
    "superseded_at",
    "updated_at",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def encode(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode(value: object, default: object) -> object:
    if value is None or value == "":
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _hydrate(
    row: object,
    json_fields: dict[str, str],
) -> dict[str, object] | None:
    if row is None:
        return None
    hydrated = dict(row)
    for source, target in json_fields.items():
        hydrated[target] = decode(hydrated.pop(source, None), {})
    return hydrated


def _hydrate_plan(row: object) -> dict[str, object] | None:
    return _hydrate(row, _PLAN_JSON_FIELDS)


def _hydrate_task(row: object) -> dict[str, object] | None:
    return _hydrate(row, _TASK_JSON_FIELDS)


async def create_or_get_plan(
    *,
    plan_identity_sha256: str,
    cohort_sha256: str,
    context_sha256: str,
    product_count: int,
    request: dict[str, object],
    authority_versions: dict[str, object],
    created_by: str,
) -> tuple[dict[str, object], bool]:
    db = await get_db()
    plan_id = new_id("ptfp")
    now = utc_now()
    async with _db_lock:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO product_treatment_factory_plan (
                plan_id, plan_identity_sha256, cohort_sha256, context_sha256,
                status, product_count, request_json, authority_versions_json,
                readiness_summary_json, capacity_summary_json, failure_count,
                provider_calls_enabled, media_generation_enabled, created_by,
                created_at, updated_at
            ) VALUES (?,?,?,?,'DRAFT',?,?,?,'{}','{}',0,0,0,?,?,?)
            """,
            (
                plan_id,
                plan_identity_sha256,
                cohort_sha256,
                context_sha256,
                product_count,
                encode(request),
                encode(authority_versions),
                created_by,
                now,
                now,
            ),
        )
        created = cursor.rowcount == 1
        await db.commit()
    plan = await get_plan_by_identity(plan_identity_sha256)
    if plan is None:
        raise RuntimeError("FACTORY_PLAN_INSERT_READBACK_FAILED")
    return plan, created


async def get_plan(plan_id: str) -> dict[str, object] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM product_treatment_factory_plan WHERE plan_id=?",
        (plan_id,),
    )
    return _hydrate_plan(await cursor.fetchone())


async def get_plan_by_identity(
    plan_identity_sha256: str,
) -> dict[str, object] | None:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM product_treatment_factory_plan
        WHERE plan_identity_sha256=?
        """,
        (plan_identity_sha256,),
    )
    return _hydrate_plan(await cursor.fetchone())


async def list_plans(
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    db = await get_db()
    if status is None:
        cursor = await db.execute(
            """
            SELECT * FROM product_treatment_factory_plan
            ORDER BY created_at DESC, plan_id DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT * FROM product_treatment_factory_plan
            WHERE status=?
            ORDER BY created_at DESC, plan_id DESC
            LIMIT ?
            """,
            (status, limit),
        )
    return [
        hydrated
        for row in await cursor.fetchall()
        if (hydrated := _hydrate_plan(row)) is not None
    ]


async def update_plan(
    plan_id: str,
    **fields: object,
) -> dict[str, object] | None:
    values = {
        key: value
        for key, value in fields.items()
        if key in _PLAN_UPDATE_FIELDS
    }
    if not values:
        return await get_plan(plan_id)
    values["updated_at"] = values.get("updated_at") or utc_now()
    db = await get_db()
    assignments = ", ".join(f"{key}=?" for key in values)
    async with _db_lock:
        await db.execute(
            f"UPDATE product_treatment_factory_plan SET {assignments} WHERE plan_id=?",
            (*values.values(), plan_id),
        )
        await db.commit()
    return await get_plan(plan_id)


async def create_or_get_task(
    *,
    plan_id: str,
    product_id: str,
    task_type: str,
    status: str,
    task_identity_sha256: str,
    required_authority_sha256: str,
    blocker_code: str | None,
    next_action: str | None,
    template_id: str | None,
    template_sha256: str | None,
    snapshot: dict[str, object],
) -> tuple[dict[str, object], bool]:
    db = await get_db()
    task_id = new_id("ptft")
    now = utc_now()
    async with _db_lock:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO product_treatment_factory_task (
                task_id, plan_id, product_id, task_type, status,
                task_identity_sha256, required_authority_sha256,
                blocker_code, next_action, template_id, template_sha256,
                snapshot_json, result_json, attempt_count, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'{}',0,?,?)
            """,
            (
                task_id,
                plan_id,
                product_id,
                task_type,
                status,
                task_identity_sha256,
                required_authority_sha256,
                blocker_code,
                next_action,
                template_id,
                template_sha256,
                encode(snapshot),
                now,
                now,
            ),
        )
        created = cursor.rowcount == 1
        await db.commit()
    task = await get_task_by_identity(task_identity_sha256)
    if task is None:
        raise RuntimeError("FACTORY_TASK_INSERT_READBACK_FAILED")
    return task, created


async def get_task(task_id: str) -> dict[str, object] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM product_treatment_factory_task WHERE task_id=?",
        (task_id,),
    )
    return _hydrate_task(await cursor.fetchone())


async def get_task_by_identity(
    task_identity_sha256: str,
) -> dict[str, object] | None:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM product_treatment_factory_task
        WHERE task_identity_sha256=?
        """,
        (task_identity_sha256,),
    )
    return _hydrate_task(await cursor.fetchone())


async def list_tasks(plan_id: str) -> list[dict[str, object]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT * FROM product_treatment_factory_task
        WHERE plan_id=?
        ORDER BY product_id, task_type, created_at, task_id
        """,
        (plan_id,),
    )
    return [
        hydrated
        for row in await cursor.fetchall()
        if (hydrated := _hydrate_task(row)) is not None
    ]


async def update_task(
    task_id: str,
    **fields: object,
) -> dict[str, object] | None:
    values = {
        key: value
        for key, value in fields.items()
        if key in _TASK_UPDATE_FIELDS
    }
    if not values:
        return await get_task(task_id)
    for key in ("snapshot_json", "result_json"):
        if key in values and not isinstance(values[key], str):
            values[key] = encode(values[key])
    values["updated_at"] = values.get("updated_at") or utc_now()
    db = await get_db()
    assignments = ", ".join(f"{key}=?" for key in values)
    async with _db_lock:
        await db.execute(
            f"UPDATE product_treatment_factory_task SET {assignments} WHERE task_id=?",
            (*values.values(), task_id),
        )
        await db.commit()
    return await get_task(task_id)


async def claim_ready_task(task_id: str) -> dict[str, object] | None:
    db = await get_db()
    now = utc_now()
    async with _db_lock:
        cursor = await db.execute(
            """
            UPDATE product_treatment_factory_task
            SET status='RUNNING', attempt_count=attempt_count+1,
                started_at=?, updated_at=?
            WHERE task_id=? AND status='READY'
            RETURNING *
            """,
            (now, now, task_id),
        )
        row = await cursor.fetchone()
        await db.commit()
    return _hydrate_task(row)


async def append_event(
    *,
    plan_id: str,
    task_id: str | None,
    event_identity_sha256: str,
    actor_id: str,
    action: str,
    source_state: str | None,
    target_state: str | None,
    evidence: dict[str, object],
) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT OR IGNORE INTO product_treatment_factory_event (
                event_id, plan_id, task_id, event_identity_sha256, actor_id,
                action, source_state, target_state, evidence_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id("ptfe"),
                plan_id,
                task_id,
                event_identity_sha256,
                actor_id,
                action,
                source_state,
                target_state,
                encode(evidence),
                utc_now(),
            ),
        )
        await db.commit()
