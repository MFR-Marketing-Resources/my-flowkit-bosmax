"""Persistence boundary for the Final Prompt Approval Gate (execution_approval_snapshot).

Thin, explicit CRUD over the per-dispatch approval snapshot table. Follows the
same idiom as ``creative_production_crud`` (aiosqlite ``get_db`` + column-
whitelisted updates)."""

from __future__ import annotations

from typing import Any

from agent.db.schema import get_db


def _dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


_UPDATE_COLUMNS = {
    "final_prompt_text",
    "prompt_sha256",
    "execution_envelope_json",
    "execution_envelope_sha256",
    "approval_state",
    "edited",
    "scan_clean",
    "scan_json",
    "approved_version",
    "approved_by",
    "approved_at",
    "approved_prompt_sha256",
    "approved_execution_envelope_sha256",
    "invalidation_reason",
    "dispatched_prompt_sha256",
    "dispatched_execution_envelope_sha256",
    "provider_job_id",
    "dispatched_at",
    "updated_at",
}


async def create_snapshot(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    await db.execute(
        f"INSERT INTO execution_approval_snapshot ({','.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )
    await db.commit()
    row = await get_snapshot(str(values["snapshot_id"]))
    assert row is not None
    return row


async def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM execution_approval_snapshot WHERE snapshot_id=?",
        (snapshot_id,),
    )
    return _dict(await cursor.fetchone())


async def update_snapshot(snapshot_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported snapshot update columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        assignments = ", ".join(f"{column}=?" for column in values)
        await db.execute(
            f"UPDATE execution_approval_snapshot SET {assignments} WHERE snapshot_id=?",
            (*values.values(), snapshot_id),
        )
        await db.commit()
    row = await get_snapshot(snapshot_id)
    if row is None:
        raise KeyError(snapshot_id)
    return row


async def find_approved_by_envelope(
    execution_envelope_sha256: str,
    *,
    snapshot_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the most recently APPROVED snapshot whose frozen approved envelope
    SHA equals the given dispatch envelope SHA. When ``snapshot_id`` is supplied
    the match is additionally pinned to that snapshot (a caller that knows which
    approval it expects), so a stale approval for a *different* item can never
    satisfy the check.

    Only APPROVED snapshots qualify: REVIEW_REQUIRED / EDITED / INVALIDATED /
    DISPATCHED all fail closed (a DISPATCHED snapshot is single-use)."""
    db = await get_db()
    sql = (
        "SELECT * FROM execution_approval_snapshot "
        "WHERE approved_execution_envelope_sha256=? AND approval_state='APPROVED'"
    )
    params: list[Any] = [execution_envelope_sha256]
    if snapshot_id is not None:
        sql += " AND snapshot_id=?"
        params.append(snapshot_id)
    sql += " ORDER BY approved_at DESC, snapshot_id DESC LIMIT 1"
    cursor = await db.execute(sql, tuple(params))
    return _dict(await cursor.fetchone())


async def list_snapshots(
    *,
    product_id: str | None = None,
    surface: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = await get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if product_id is not None:
        clauses.append("product_id=?")
        params.append(product_id)
    if surface is not None:
        clauses.append("surface=?")
        params.append(surface)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    cursor = await db.execute(
        "SELECT * FROM execution_approval_snapshot"
        f"{where} ORDER BY created_at DESC, snapshot_id DESC LIMIT ?",
        tuple(params),
    )
    return [dict(row) for row in await cursor.fetchall()]
