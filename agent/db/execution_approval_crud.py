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
    "manifest_id",
    "manifest_item_key",
    "updated_at",
}


_MANIFEST_UPDATE_COLUMNS = {
    "surface",
    "product_id",
    "logical_mode",
    "run_ref",
    "state",
    "item_count",
    "approved_version",
    "approved_by",
    "approved_at",
    "invalidation_reason",
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


# --------------------------------------------------------------------------- #
# Approved Generation Manifest
# --------------------------------------------------------------------------- #

async def find_approved_manifest_item(
    manifest_id: str,
    execution_envelope_sha256: str,
) -> dict[str, Any] | None:
    """Resolve an APPROVED snapshot that belongs to an APPROVED manifest and whose
    frozen envelope SHA equals the dispatch envelope. This is the ONLY way a
    non-UI dispatch (queue / bulk / scheduler / Montage / Extend) inherits
    approval — by referencing a human-approved manifest item whose hash exactly
    matches. Approval is NEVER manufactured from the dispatch envelope."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT s.* FROM execution_approval_snapshot s "
        "JOIN execution_approval_manifest m ON s.manifest_id = m.manifest_id "
        "WHERE s.manifest_id=? AND s.approved_execution_envelope_sha256=? "
        "AND s.approval_state='APPROVED' AND m.state='APPROVED' "
        "ORDER BY s.approved_at DESC, s.snapshot_id DESC LIMIT 1",
        (manifest_id, execution_envelope_sha256),
    )
    return _dict(await cursor.fetchone())


async def create_manifest(values: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    await db.execute(
        f"INSERT INTO execution_approval_manifest ({','.join(columns)}) "
        f"VALUES ({placeholders})",
        tuple(values[column] for column in columns),
    )
    await db.commit()
    row = await get_manifest(str(values["manifest_id"]))
    assert row is not None
    return row


async def get_manifest(manifest_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM execution_approval_manifest WHERE manifest_id=?",
        (manifest_id,),
    )
    return _dict(await cursor.fetchone())


async def update_manifest(manifest_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _MANIFEST_UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported manifest update columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        assignments = ", ".join(f"{column}=?" for column in values)
        await db.execute(
            f"UPDATE execution_approval_manifest SET {assignments} WHERE manifest_id=?",
            (*values.values(), manifest_id),
        )
        await db.commit()
    row = await get_manifest(manifest_id)
    if row is None:
        raise KeyError(manifest_id)
    return row


async def list_manifest_items(manifest_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM execution_approval_snapshot WHERE manifest_id=? "
        "ORDER BY manifest_item_key ASC, snapshot_id ASC",
        (manifest_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def find_latest_approved_manifest_by_run_ref(
    run_ref: str,
    *,
    surface: str | None = None,
) -> dict[str, Any] | None:
    """Return the most-recently-approved manifest for a run (the dispatch side
    looks its approved manifest up by ``run_ref`` so no run/plan table needs a new
    column). Only APPROVED manifests qualify — a REVIEW_REQUIRED / INVALIDATED one
    never authorises a dispatch."""
    db = await get_db()
    sql = (
        "SELECT * FROM execution_approval_manifest "
        "WHERE run_ref=? AND state='APPROVED'"
    )
    params: list[Any] = [run_ref]
    if surface is not None:
        sql += " AND surface=?"
        params.append(surface)
    sql += " ORDER BY approved_at DESC, manifest_id DESC LIMIT 1"
    cursor = await db.execute(sql, tuple(params))
    return _dict(await cursor.fetchone())


async def list_manifests(
    *,
    run_ref: str | None = None,
    surface: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = await get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if run_ref is not None:
        clauses.append("run_ref=?")
        params.append(run_ref)
    if surface is not None:
        clauses.append("surface=?")
        params.append(surface)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    cursor = await db.execute(
        "SELECT * FROM execution_approval_manifest"
        f"{where} ORDER BY created_at DESC, manifest_id DESC LIMIT ?",
        tuple(params),
    )
    return [dict(row) for row in await cursor.fetchall()]
