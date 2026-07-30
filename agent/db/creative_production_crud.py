"""Persistence boundary for the durable P6 creative production control plane."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agent.db.schema import get_db


def _dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


async def create_plan(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    await db.execute(
        f"INSERT INTO creative_production_plan ({','.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )
    await db.commit()
    row = await get_plan(str(values["plan_id"]))
    assert row is not None
    return row


async def get_plan(plan_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_plan WHERE plan_id=?",
        (plan_id,),
    )
    return _dict(await cursor.fetchone())


async def get_plan_by_request_id(request_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_plan WHERE request_id=?",
        (request_id,),
    )
    return _dict(await cursor.fetchone())


async def list_plans(limit: int = 50) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_plan "
        "ORDER BY created_at DESC, plan_id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in await cursor.fetchall()]


_PLAN_UPDATE_COLUMNS = {
    "name",
    "campaign_key",
    "target_video_count",
    "target_image_count",
    "target_poster_count",
    "operating_window_hours",
    "allocation_strategy",
    "variation_strategy",
    "logical_mode",
    "model_keys_json",
    "duration_seconds_json",
    "pool_snapshot_json",
    "execution_policy_json",
    "capacity_snapshot_json",
    "compile_snapshot_json",
    "blockers_json",
    "status",
    "control_action",
    "control_version",
    "approved_by",
    "approved_at",
    "updated_at",
}


async def update_plan(plan_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _PLAN_UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported plan update columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        assignments = ", ".join(f"{column}=?" for column in values)
        await db.execute(
            f"UPDATE creative_production_plan SET {assignments} WHERE plan_id=?",
            (*values.values(), plan_id),
        )
        await db.commit()
    row = await get_plan(plan_id)
    if row is None:
        raise KeyError(plan_id)
    return row


async def insert_items(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    db = await get_db()
    columns = tuple(items[0])
    if any(tuple(item) != columns for item in items):
        raise ValueError("item insert columns must be identical")
    placeholders = ",".join("?" for _ in columns)
    try:
        await db.execute("BEGIN IMMEDIATE")
        await db.executemany(
            f"INSERT INTO creative_production_item ({','.join(columns)}) "
            f"VALUES ({placeholders})",
            [tuple(item[column] for column in columns) for item in items],
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def get_item(item_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_item WHERE item_id=?",
        (item_id,),
    )
    return _dict(await cursor.fetchone())


async def list_items(
    plan_id: str,
    *,
    statuses: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    db = await get_db()
    params: list[Any] = [plan_id]
    query = "SELECT * FROM creative_production_item WHERE plan_id=?"
    normalized = list(statuses or [])
    if normalized:
        query += f" AND status IN ({','.join('?' for _ in normalized)})"
        params.extend(normalized)
    query += " ORDER BY item_ordinal, item_id"
    cursor = await db.execute(query, tuple(params))
    return [dict(row) for row in await cursor.fetchall()]


async def list_historical_dna(
    product_ids: list[str],
    dna_hashes: list[str],
) -> set[str]:
    if not product_ids or not dna_hashes:
        return set()
    db = await get_db()
    product_marks = ",".join("?" for _ in product_ids)
    dna_marks = ",".join("?" for _ in dna_hashes)
    cursor = await db.execute(
        "SELECT DISTINCT creative_dna_sha256 FROM creative_production_item "
        f"WHERE product_id IN ({product_marks}) "
        f"AND creative_dna_sha256 IN ({dna_marks}) "
        "AND status NOT IN ('CANCELLED','SUPERSEDED')",
        (*product_ids, *dna_hashes),
    )
    return {str(row[0]) for row in await cursor.fetchall()}


_ITEM_UPDATE_COLUMNS = {
    "wave_id",
    "production_batch_id",
    "creative_dimensions_json",
    "creative_dna_sha256",
    "dedupe_guard_key",
    "controlled_reuse_reason",
    "prompt_fingerprint",
    "workspace_generation_package_id",
    "prompt_package_json",
    "execution_policy_json",
    "status",
    "output_media_id",
    "replacement_for_item_id",
    "replaced_by_item_id",
    "updated_at",
}


async def update_item(item_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _ITEM_UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported item update columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        assignments = ", ".join(f"{column}=?" for column in values)
        await db.execute(
            f"UPDATE creative_production_item SET {assignments} WHERE item_id=?",
            (*values.values(), item_id),
        )
        await db.commit()
    row = await get_item(item_id)
    if row is None:
        raise KeyError(item_id)
    return row


async def bulk_update_item_status(
    plan_id: str,
    *,
    from_statuses: list[str],
    to_status: str,
    updated_at: str,
) -> int:
    if not from_statuses:
        return 0
    db = await get_db()
    marks = ",".join("?" for _ in from_statuses)
    cursor = await db.execute(
        "UPDATE creative_production_item SET status=?, updated_at=? "
        f"WHERE plan_id=? AND status IN ({marks})",
        (to_status, updated_at, plan_id, *from_statuses),
    )
    await db.commit()
    return int(cursor.rowcount)


async def replace_plan_allocations(
    plan_id: str,
    waves: list[dict[str, Any]],
    batches: list[dict[str, Any]],
    assignments: list[tuple[str, str, str, str]],
) -> None:
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            "DELETE FROM creative_production_batch WHERE plan_id=?",
            (plan_id,),
        )
        await db.execute(
            "DELETE FROM creative_production_wave WHERE plan_id=?",
            (plan_id,),
        )
        await db.executemany(
            "INSERT INTO creative_production_wave "
            "(wave_id,plan_id,wave_ordinal,name,scheduled_at,status) "
            "VALUES (?,?,?,?,?,'APPROVED')",
            [
                (
                    row["wave_id"],
                    row["plan_id"],
                    row["wave_ordinal"],
                    row["name"],
                    row.get("scheduled_at"),
                )
                for row in waves
            ],
        )
        await db.executemany(
            "INSERT INTO creative_production_batch "
            "(production_batch_id,plan_id,wave_id,batch_ordinal,label,status) "
            "VALUES (?,?,?,?,?,'APPROVED')",
            [
                (
                    row["production_batch_id"],
                    row["plan_id"],
                    row["wave_id"],
                    row["batch_ordinal"],
                    row["label"],
                )
                for row in batches
            ],
        )
        await db.executemany(
            "UPDATE creative_production_item "
            "SET wave_id=?, production_batch_id=?, status='WAVE_ASSIGNED', updated_at=? "
            "WHERE item_id=?",
            assignments,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def list_waves(plan_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_wave WHERE plan_id=? "
        "ORDER BY wave_ordinal",
        (plan_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def list_batches(plan_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_batch WHERE plan_id=? "
        "ORDER BY batch_ordinal",
        (plan_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_attempt_by_action(
    item_id: str,
    action_request_id: str,
) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_generation_attempt "
        "WHERE item_id=? AND action_request_id=?",
        (item_id, action_request_id),
    )
    return _dict(await cursor.fetchone())


async def create_attempt(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    try:
        await db.execute(
            f"INSERT INTO creative_generation_attempt ({','.join(columns)}) "
            f"VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        existing = await get_attempt_by_action(
            str(values["item_id"]),
            str(values["action_request_id"]),
        )
        if existing is not None:
            return existing
        raise
    cursor = await db.execute(
        "SELECT * FROM creative_generation_attempt WHERE attempt_id=?",
        (values["attempt_id"],),
    )
    row = _dict(await cursor.fetchone())
    assert row is not None
    return row


async def get_attempt(attempt_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_generation_attempt WHERE attempt_id=?",
        (attempt_id,),
    )
    return _dict(await cursor.fetchone())


async def list_attempts(plan_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT a.* FROM creative_generation_attempt a "
        "JOIN creative_production_item i ON i.item_id=a.item_id "
        "WHERE i.plan_id=? ORDER BY i.item_ordinal,a.attempt_number",
        (plan_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def list_attempts_for_reconciliation(
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_generation_attempt "
        "WHERE attempt_state='PROVIDER_JOB_KNOWN' "
        "ORDER BY updated_at, attempt_id LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in await cursor.fetchall()]


_ATTEMPT_UPDATE_COLUMNS = {
    "lane_id",
    "attempt_state",
    "credit_confirmation",
    "last_actor_id",
    "last_action_request_id",
    "provider_job_id",
    "provider_project_id",
    "provider_correlation_id",
    "provider_snapshot_json",
    "provider_snapshot_updated_at",
    "artifact_media_id",
    "failure_stage",
    "failure_code",
    "recovery_class",
    "submission_started_at",
    "provider_known_at",
    "generated_at",
    "retrieved_at",
    "registered_at",
    "completed_at",
    "updated_at",
}


async def update_attempt(attempt_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _ATTEMPT_UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported attempt update columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        assignments = ", ".join(f"{column}=?" for column in values)
        await db.execute(
            f"UPDATE creative_generation_attempt SET {assignments} WHERE attempt_id=?",
            (*values.values(), attempt_id),
        )
        await db.commit()
    row = await get_attempt(attempt_id)
    if row is None:
        raise KeyError(attempt_id)
    return row


async def list_lanes() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_execution_lane ORDER BY lane_id"
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_lane(lane_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_execution_lane WHERE lane_id=?",
        (lane_id,),
    )
    return _dict(await cursor.fetchone())


async def patch_lane(
    lane_id: str,
    *,
    health_status: str,
    enabled: bool,
    runtime_proof_status: str,
    evidence_reference: str,
    updated_at: str,
) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        "UPDATE creative_execution_lane SET health_status=?,enabled=?,"
        "runtime_proof_status=?,evidence_reference=?,updated_at=? WHERE lane_id=?",
        (
            health_status,
            int(enabled),
            runtime_proof_status,
            evidence_reference,
            updated_at,
            lane_id,
        ),
    )
    await db.commit()
    row = await get_lane(lane_id)
    if row is None:
        raise KeyError(lane_id)
    return row


async def record_lane_outcome(
    lane_id: str,
    *,
    succeeded: bool,
    completed_at: str,
    next_available_at: str,
) -> dict[str, Any]:
    db = await get_db()
    success_assignment = "last_success_at=?" if succeeded else "last_failure_at=?"
    await db.execute(
        "UPDATE creative_execution_lane SET "
        f"{success_assignment},"
        "completed_job_count=completed_job_count+1,"
        "next_available_at=?,updated_at=? WHERE lane_id=?",
        (completed_at, next_available_at, completed_at, lane_id),
    )
    await db.commit()
    row = await get_lane(lane_id)
    if row is None:
        raise KeyError(lane_id)
    return row


async def acquire_lease(
    *,
    lane_id: str,
    attempt_id: str,
    lease_id: str,
    lease_token: str,
    owner_instance_id: str,
    acquired_at: str,
    expires_at: str,
) -> dict[str, Any] | None:
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await db.execute(
            "UPDATE creative_execution_lane_lease "
            "SET released_at=?,release_reason='LEASE_EXPIRED' "
            "WHERE lane_id=? AND released_at IS NULL AND expires_at<=?",
            (acquired_at, lane_id, acquired_at),
        )
        cursor = await db.execute(
            "SELECT verified_max_inflight FROM creative_execution_lane "
            "WHERE lane_id=? AND enabled=1 AND runtime_proof_status='VERIFIED' "
            "AND health_status='HEALTHY' "
            "AND (next_available_at IS NULL OR next_available_at<=?)",
            (lane_id, acquired_at),
        )
        lane = await cursor.fetchone()
        if lane is None:
            await db.rollback()
            return None
        cursor = await db.execute(
            "SELECT lease_slot FROM creative_execution_lane_lease "
            "WHERE lane_id=? AND released_at IS NULL ORDER BY lease_slot",
            (lane_id,),
        )
        occupied = {int(row[0]) for row in await cursor.fetchall()}
        slot = next(
            (
                candidate
                for candidate in range(int(lane[0]))
                if candidate not in occupied
            ),
            None,
        )
        if slot is None:
            await db.rollback()
            return None
        await db.execute(
            "INSERT INTO creative_execution_lane_lease "
            "(lease_id,lane_id,attempt_id,lease_slot,lease_token,"
            "owner_instance_id,acquired_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                lease_id,
                lane_id,
                attempt_id,
                slot,
                lease_token,
                owner_instance_id,
                acquired_at,
                expires_at,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    cursor = await db.execute(
        "SELECT * FROM creative_execution_lane_lease WHERE lease_id=?",
        (lease_id,),
    )
    return _dict(await cursor.fetchone())


async def release_lease(
    attempt_id: str,
    *,
    released_at: str,
    release_reason: str,
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE creative_execution_lane_lease "
        "SET released_at=?,release_reason=? "
        "WHERE attempt_id=? AND released_at IS NULL",
        (released_at, release_reason, attempt_id),
    )
    await db.commit()


async def list_leases(*, active_only: bool = False) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM creative_execution_lane_lease"
    if active_only:
        query += " WHERE released_at IS NULL"
    query += " ORDER BY acquired_at"
    cursor = await db.execute(query)
    return [dict(row) for row in await cursor.fetchall()]


async def upsert_qa(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        "INSERT INTO creative_output_qa "
        "(qa_id,item_id,attempt_id,artifact_media_id,status,checklist_json,"
        "reviewer_id,reviewer_note,reviewed_at,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(item_id,attempt_id,artifact_media_id) DO UPDATE SET "
        "status=excluded.status,checklist_json=excluded.checklist_json,"
        "reviewer_id=excluded.reviewer_id,reviewer_note=excluded.reviewer_note,"
        "reviewed_at=excluded.reviewed_at,updated_at=excluded.updated_at",
        (
            values["qa_id"],
            values["item_id"],
            values["attempt_id"],
            values["artifact_media_id"],
            values["status"],
            values["checklist_json"],
            values.get("reviewer_id"),
            values.get("reviewer_note"),
            values.get("reviewed_at"),
            values["created_at"],
            values["updated_at"],
        ),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM creative_output_qa "
        "WHERE item_id=? AND attempt_id=? AND artifact_media_id=?",
        (
            values["item_id"],
            values["attempt_id"],
            values["artifact_media_id"],
        ),
    )
    row = _dict(await cursor.fetchone())
    assert row is not None
    return row


async def list_qa(plan_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT q.* FROM creative_output_qa q "
        "JOIN creative_production_item i ON i.item_id=q.item_id "
        "WHERE i.plan_id=? ORDER BY q.created_at",
        (plan_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def record_audit_event(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        "INSERT INTO creative_production_audit_event "
        "(event_id,plan_id,item_id,attempt_id,request_id,actor_id,action,"
        "source_state,target_state,evidence_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(plan_id,request_id,action) DO NOTHING",
        (
            values["event_id"],
            values["plan_id"],
            values.get("item_id"),
            values.get("attempt_id"),
            values["request_id"],
            values["actor_id"],
            values["action"],
            values.get("source_state"),
            values.get("target_state"),
            values.get("evidence_json", "{}"),
            values["created_at"],
        ),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM creative_production_audit_event "
        "WHERE plan_id=? AND request_id=? AND action=?",
        (values["plan_id"], values["request_id"], values["action"]),
    )
    row = _dict(await cursor.fetchone())
    assert row is not None
    return row


async def list_audit_events(plan_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_production_audit_event WHERE plan_id=? "
        "ORDER BY created_at,event_id",
        (plan_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def get_generated_artifact_by_job_id(
    job_id: str,
) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM generated_artifact WHERE job_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (job_id,),
    )
    return _dict(await cursor.fetchone())
