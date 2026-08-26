"""CRUD boundary for the On-Demand Copy Renderer (Round 2).

Sole SQL layer for the copy_render_* tables. House conventions (see
creative_factory_crud): reads lock-free; writes under ``async with _db_lock``;
ids ``<PREFIX>_<hex>``; TEXT ISO-8601-Z timestamps; JSON columns encoded with
sorted keys. The atomic operations here are the crux of the Round-2 laws:

* ``reserve_batch`` — idempotent per (session_id, request_id): a duplicate paid
  request returns the existing batch, never a second one.
* ``commit_shown_batch`` — one txn: (regenerate) unlocked SHOWN→SKIPPED, insert
  new SHOWN candidates, batch→SHOWN. Failure rolls back; locked untouched.
* ``lock_candidate`` — enforces ``locked_count < target_count`` atomically.
* ``finalize_session`` — one txn: session→FINALIZED, all LOCKED→FINALIZED.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from agent.db.schema import _db_lock, get_db


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback


def _dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


_SESSION_COLS = (
    "session_id", "product_id", "benefit_id", "benefit_digest", "pi_snapshot_id",
    "pi_snapshot_version", "atom_build_fingerprint", "lane", "duration_seconds",
    "target_language", "wps_mode", "wps_authority_version", "wps_authority_digest",
    "formula_id", "formula_version", "renderer_prompt_version", "safety_policy_version",
    "word_budget", "target_count", "suggestion_batch_size", "locked_count", "status",
    "lineage_json", "created_by", "avatar_id",
)
# avatar_id is a visual setting (governed presenter identity); it is updatable
# WITHOUT touching any copy-lineage column, so a presenter change never stales copy.
_SESSION_UPDATABLE = {"target_count", "locked_count", "status", "lineage_json", "finalized_at", "avatar_id"}


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------
async def create_session(row: Mapping[str, Any]) -> dict[str, Any]:
    db = await get_db()
    values = []
    for col in _SESSION_COLS:
        v = row.get(col)
        if col == "lineage_json":
            v = encode(v or {})
        values.append(v)
    placeholders = ",".join("?" * len(_SESSION_COLS))
    async with _db_lock:
        await db.execute(
            f"INSERT INTO copy_render_session ({','.join(_SESSION_COLS)}) VALUES ({placeholders})",
            values,
        )
        await db.commit()
    result = await get_session(row["session_id"])
    assert result is not None
    return result


async def get_session(session_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_render_session WHERE session_id=?", (session_id,))
    return _dict(await cur.fetchone())


async def update_session(session_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
    sets, params = [], []
    for key, value in fields.items():
        if key not in _SESSION_UPDATABLE:
            raise ValueError(f"update_session: column not writable: {key}")
        if key == "lineage_json":
            value = encode(value or {})
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return await get_session(session_id)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    params.append(session_id)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"UPDATE copy_render_session SET {', '.join(sets)} WHERE session_id=?", params
        )
        await db.commit()
    return await get_session(session_id)


# --------------------------------------------------------------------------
# batches (idempotent paid actions)
# --------------------------------------------------------------------------
async def reserve_batch(row: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Insert a RESERVED batch. Returns (batch, created). On duplicate
    (session_id, request_id) returns the existing batch with created=False (the
    idempotency guard — no second provider call)."""
    db = await get_db()
    async with _db_lock:
        try:
            await db.execute(
                """
                INSERT INTO copy_render_batch (
                    batch_id, session_id, batch_number, request_id, action, status,
                    recipe_plan_json, requested_recipe_count
                ) VALUES (?,?,?,?,?, 'RESERVED', ?, ?)
                """,
                (
                    row["batch_id"], row["session_id"], row["batch_number"], row["request_id"],
                    row.get("action", "GENERATE"), encode(row.get("recipe_plan") or []),
                    int(row.get("requested_recipe_count") or 0),
                ),
            )
            await db.commit()
            created = True
        except sqlite3.IntegrityError:
            created = False
    if created:
        return (await get_batch(row["batch_id"]), True)  # type: ignore[return-value]
    existing = await get_batch_by_request(row["session_id"], row["request_id"])
    return (existing, False)  # type: ignore[return-value]


async def get_batch(batch_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_render_batch WHERE batch_id=?", (batch_id,))
    return _dict(await cur.fetchone())


async def get_batch_by_request(session_id: str, request_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_render_batch WHERE session_id=? AND request_id=?",
        (session_id, request_id),
    )
    return _dict(await cur.fetchone())


async def get_active_batches(session_id: str) -> list[dict[str, Any]]:
    """RESERVED/RUNNING batches (single-flight + crash-recovery inspection)."""
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_render_batch WHERE session_id=? AND status IN ('RESERVED','RUNNING') "
        "ORDER BY started_at ASC",
        (session_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


async def next_batch_number(session_id: str) -> int:
    db = await get_db()
    cur = await db.execute(
        "SELECT COALESCE(MAX(batch_number),0)+1 FROM copy_render_batch WHERE session_id=?",
        (session_id,),
    )
    return int((await cur.fetchone())[0])


async def update_batch(batch_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
    allowed = {
        "status", "input_digest", "requested_recipe_count", "cache_hit_count",
        "provider_calls", "provider", "model", "provider_receipt_json",
        "token_usage_json", "failure_code", "failure_detail", "provider_started_at",
        "completed_at",
    }
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"update_batch: column not writable: {key}")
        if key in ("provider_receipt_json", "token_usage_json"):
            value = encode(value or {})
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return await get_batch(batch_id)
    params.append(batch_id)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"UPDATE copy_render_batch SET {', '.join(sets)} WHERE batch_id=?", params
        )
        await db.commit()
    return await get_batch(batch_id)


async def list_batches(session_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_render_batch WHERE session_id=? ORDER BY batch_number ASC",
        (session_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


# --------------------------------------------------------------------------
# artifacts (immutable cache)
# --------------------------------------------------------------------------
_ARTIFACT_COLS = (
    "artifact_id", "render_key", "product_id", "benefit_id", "recipe_fingerprint",
    "formula_id", "formula_version", "duration_seconds", "target_language", "wps_mode",
    "wps_authority_version", "wps_authority_digest", "renderer_prompt_version",
    "safety_policy_version", "stage_json", "full_copy_text", "word_count", "text_digest",
    "source_lineage_json", "validation_json", "provider_provenance_json",
)


async def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_render_artifact WHERE artifact_id=?", (artifact_id,))
    return _dict(await cur.fetchone())


async def get_artifact_by_render_key(render_key: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_render_artifact WHERE render_key=?", (render_key,))
    return _dict(await cur.fetchone())


async def get_or_create_artifact(row: Mapping[str, Any]) -> dict[str, Any]:
    """Immutable cache insert; returns the existing artifact on render_key hit."""
    db = await get_db()
    values = []
    for col in _ARTIFACT_COLS:
        v = row.get(col)
        if col in ("stage_json", "source_lineage_json", "validation_json", "provider_provenance_json"):
            v = encode(v or ({} if col != "stage_json" else []))
        values.append(v)
    placeholders = ",".join("?" * len(_ARTIFACT_COLS))
    async with _db_lock:
        await db.execute(
            f"INSERT OR IGNORE INTO copy_render_artifact ({','.join(_ARTIFACT_COLS)}) "
            f"VALUES ({placeholders})",
            values,
        )
        await db.commit()
    existing = await get_artifact_by_render_key(row["render_key"])
    assert existing is not None
    return existing


# --------------------------------------------------------------------------
# candidates + session-used history
# --------------------------------------------------------------------------
async def list_candidates(
    session_id: str, *, statuses: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM copy_render_candidate WHERE session_id=?"
    params: list[Any] = [session_id]
    if statuses:
        query += " AND status IN (%s)" % ",".join("?" * len(statuses))
        params.extend(statuses)
    query += " ORDER BY shown_at ASC, candidate_id ASC"
    cur = await db.execute(query, params)
    return [dict(r) for r in await cur.fetchall()]


async def get_candidate(candidate_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM copy_render_candidate WHERE candidate_id=?", (candidate_id,))
    return _dict(await cur.fetchone())


async def session_used_fingerprints(session_id: str) -> set[str]:
    db = await get_db()
    cur = await db.execute(
        "SELECT DISTINCT recipe_fingerprint FROM copy_render_candidate WHERE session_id=?",
        (session_id,),
    )
    return {r[0] for r in await cur.fetchall()}


async def session_used_text_digests(session_id: str) -> set[str]:
    db = await get_db()
    cur = await db.execute(
        "SELECT DISTINCT text_digest FROM copy_render_candidate WHERE session_id=?",
        (session_id,),
    )
    return {r[0] for r in await cur.fetchall()}


async def commit_shown_batch(
    *,
    session_id: str,
    batch_id: str,
    is_regenerate: bool,
    candidate_rows: Sequence[Mapping[str, Any]],
    batch_updates: Mapping[str, Any],
) -> None:
    """Atomic: (regenerate) unlocked SHOWN→SKIPPED · insert new SHOWN candidates ·
    batch→SHOWN. Rolls back on any failure; LOCKED candidates untouched."""
    db = await get_db()
    async with _db_lock:
        try:
            if is_regenerate:
                await db.execute(
                    "UPDATE copy_render_candidate SET status='SKIPPED', unlocked_at=NULL "
                    "WHERE session_id=? AND status='SHOWN'",
                    (session_id,),
                )
            for c in candidate_rows:
                await db.execute(
                    """
                    INSERT INTO copy_render_candidate (
                        candidate_id, session_id, batch_id, artifact_id, recipe_fingerprint,
                        text_digest, angle_id, hook_id, body_id, cta_id, status
                    ) VALUES (?,?,?,?,?,?,?,?,?,?, 'SHOWN')
                    """,
                    (
                        c["candidate_id"], session_id, batch_id, c["artifact_id"],
                        c["recipe_fingerprint"], c["text_digest"], c["angle_id"],
                        c["hook_id"], c["body_id"], c["cta_id"],
                    ),
                )
            sets = ["status='SHOWN'", "completed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"]
            params: list[Any] = []
            for key in ("input_digest", "requested_recipe_count", "cache_hit_count",
                        "provider_calls", "provider", "model", "provider_receipt_json",
                        "token_usage_json"):
                if key in batch_updates:
                    v = batch_updates[key]
                    if key in ("provider_receipt_json", "token_usage_json"):
                        v = encode(v or {})
                    sets.append(f"{key}=?")
                    params.append(v)
            params.append(batch_id)
            await db.execute(
                f"UPDATE copy_render_batch SET {', '.join(sets)} WHERE batch_id=?", params
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def lock_candidate(candidate_id: str) -> dict[str, Any]:
    """Atomic SHOWN→LOCKED enforcing locked_count < target_count; recomputes
    session locked_count + TARGET_COMPLETE. Returns {candidate, session}."""
    db = await get_db()
    async with _db_lock:
        try:
            cand = _dict(await (await db.execute(
                "SELECT * FROM copy_render_candidate WHERE candidate_id=?", (candidate_id,)
            )).fetchone())
            if cand is None:
                raise _CopyRenderCrudError("CANDIDATE_NOT_FOUND")
            if cand["status"] != "SHOWN":
                raise _CopyRenderCrudError(f"CANDIDATE_NOT_LOCKABLE:{cand['status']}")
            sess = _dict(await (await db.execute(
                "SELECT * FROM copy_render_session WHERE session_id=?", (cand["session_id"],)
            )).fetchone())
            if sess is None:
                raise _CopyRenderCrudError("SESSION_NOT_FOUND")
            if sess["status"] not in ("OPEN", "TARGET_COMPLETE"):
                raise _CopyRenderCrudError(f"SESSION_NOT_MUTABLE:{sess['status']}")
            locked_now = int((await (await db.execute(
                "SELECT COUNT(*) FROM copy_render_candidate WHERE session_id=? AND status='LOCKED'",
                (cand["session_id"],)
            )).fetchone())[0])
            if locked_now >= int(sess["target_count"]):
                raise _CopyRenderCrudError("LOCK_EXCEEDS_TARGET")
            await db.execute(
                "UPDATE copy_render_candidate SET status='LOCKED', "
                "locked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE candidate_id=?",
                (candidate_id,),
            )
            new_locked = locked_now + 1
            new_status = "TARGET_COMPLETE" if new_locked == int(sess["target_count"]) else "OPEN"
            await db.execute(
                "UPDATE copy_render_session SET locked_count=?, status=?, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE session_id=?",
                (new_locked, new_status, cand["session_id"]),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {
        "candidate": await get_candidate(candidate_id),
        "session": await get_session(cand["session_id"]),
    }


async def unlock_candidate(candidate_id: str) -> dict[str, Any]:
    """Atomic LOCKED→SHOWN (pre-FINALIZED); recomputes locked_count + reopens
    TARGET_COMPLETE→OPEN. Fingerprint stays in the USED history."""
    db = await get_db()
    async with _db_lock:
        try:
            cand = _dict(await (await db.execute(
                "SELECT * FROM copy_render_candidate WHERE candidate_id=?", (candidate_id,)
            )).fetchone())
            if cand is None:
                raise _CopyRenderCrudError("CANDIDATE_NOT_FOUND")
            if cand["status"] != "LOCKED":
                raise _CopyRenderCrudError(f"CANDIDATE_NOT_UNLOCKABLE:{cand['status']}")
            sess = _dict(await (await db.execute(
                "SELECT * FROM copy_render_session WHERE session_id=?", (cand["session_id"],)
            )).fetchone())
            if sess is None or sess["status"] not in ("OPEN", "TARGET_COMPLETE"):
                raise _CopyRenderCrudError("SESSION_NOT_MUTABLE")
            await db.execute(
                "UPDATE copy_render_candidate SET status='SHOWN', "
                "unlocked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE candidate_id=?",
                (candidate_id,),
            )
            new_locked = int((await (await db.execute(
                "SELECT COUNT(*) FROM copy_render_candidate WHERE session_id=? AND status='LOCKED'",
                (cand["session_id"],)
            )).fetchone())[0])
            await db.execute(
                "UPDATE copy_render_session SET locked_count=?, status='OPEN', "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE session_id=?",
                (new_locked, cand["session_id"]),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return {
        "candidate": await get_candidate(candidate_id),
        "session": await get_session(cand["session_id"]),
    }


async def finalize_session(session_id: str) -> dict[str, Any]:
    """Atomic: all LOCKED candidates→FINALIZED + session→FINALIZED (+finalized_at)."""
    db = await get_db()
    async with _db_lock:
        try:
            await db.execute(
                "UPDATE copy_render_candidate SET status='FINALIZED', "
                "finalized_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE session_id=? AND status='LOCKED'",
                (session_id,),
            )
            await db.execute(
                "UPDATE copy_render_session SET status='FINALIZED', "
                "finalized_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE session_id=?",
                (session_id,),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return await get_session(session_id)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# candidate → READY package binding (idempotent; NO production/queue)
# --------------------------------------------------------------------------
async def get_or_create_candidate_package(row: Mapping[str, Any]) -> dict[str, Any]:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT OR IGNORE INTO copy_render_candidate_package (
                binding_id, session_id, candidate_id, artifact_id, package_id, lineage_json
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                row["binding_id"], row["session_id"], row["candidate_id"],
                row["artifact_id"], row["package_id"], encode(row.get("lineage_json") or {}),
            ),
        )
        await db.commit()
    cur = await db.execute(
        "SELECT * FROM copy_render_candidate_package WHERE session_id=? AND candidate_id=?",
        (row["session_id"], row["candidate_id"]),
    )
    return _dict(await cur.fetchone())  # type: ignore[return-value]


async def list_candidate_packages(session_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM copy_render_candidate_package WHERE session_id=? ORDER BY created_at ASC",
        (session_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


class _CopyRenderCrudError(Exception):
    """Internal atomic-guard signal; the service maps it to a typed error."""
