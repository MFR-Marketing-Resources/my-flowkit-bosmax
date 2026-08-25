"""CRUD boundary for the Benefit-Centric Creative Factory (Round 1).

This module is the ONLY place that issues SQL for the creative-factory tables
(``product_benefit``, ``creative_angle/hook/body/cta``,
``creative_atom_compatibility``, ``creative_build_receipt``,
``product_benefit_review``). It follows the house conventions:

* reads are lock-free; writes run inside ``async with _db_lock: ... commit()``;
* ids are ``<PREFIX>_<uuid hex>``; timestamps are TEXT ISO-8601-Z (SQL default on
  insert, explicit ``strftime`` on update);
* JSON columns are TEXT encoded with sorted keys / compact separators.

The ATOMIC build commit (amendment 6) supersedes a benefit's prior ACTIVE atoms
and inserts the complete new build inside a single transaction — so a failed
build never disturbs the previous good ACTIVE build, and a good build is never
half-applied.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from agent.db.schema import _db_lock, get_db

_ATOM_TABLES = ("creative_angle", "creative_hook", "creative_body", "creative_cta")
_ATOM_TABLE_BY_KIND = {
    "angle": "creative_angle",
    "hook": "creative_hook",
    "body": "creative_body",
    "cta": "creative_cta",
}


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


# --------------------------------------------------------------------------
# product_benefit
# --------------------------------------------------------------------------
async def create_benefit(row: Mapping[str, Any]) -> dict[str, Any]:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO product_benefit (
                benefit_id, product_id, canonical_text, text_digest, usage_hint,
                status, pi_snapshot_id, pi_snapshot_version, pi_check_json,
                provenance_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["benefit_id"],
                row["product_id"],
                row["canonical_text"],
                row["text_digest"],
                row.get("usage_hint"),
                row.get("status", "DRAFT"),
                row.get("pi_snapshot_id"),
                row.get("pi_snapshot_version"),
                encode(row.get("pi_check_json") or {}),
                encode(row.get("provenance_json") or {}),
            ),
        )
        await db.commit()
    result = await get_benefit(row["benefit_id"])
    assert result is not None
    return result


async def get_benefit(benefit_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_benefit WHERE benefit_id=?", (benefit_id,)
    )
    return _dict(await cur.fetchone())


async def list_benefits(
    product_id: str, *, statuses: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM product_benefit WHERE product_id=?"
    params: list[Any] = [product_id]
    if statuses:
        placeholders = ",".join("?" * len(statuses))
        query += f" AND status IN ({placeholders})"
        params.extend(statuses)
    query += " ORDER BY created_at ASC, benefit_id ASC"
    cur = await db.execute(query, params)
    return [dict(r) for r in await cur.fetchall()]


async def update_benefit(benefit_id: str, fields: Mapping[str, Any]) -> dict[str, Any] | None:
    """Update an allow-listed subset of columns and bump ``updated_at``."""
    allowed = {
        "canonical_text",
        "text_digest",
        "usage_hint",
        "status",
        "pi_snapshot_id",
        "pi_snapshot_version",
        "pi_check_json",
        "provenance_json",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"update_benefit: column not writable: {key}")
        if key in ("pi_check_json", "provenance_json"):
            value = encode(value or {})
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return await get_benefit(benefit_id)
    sets.append("updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')")
    params.append(benefit_id)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"UPDATE product_benefit SET {', '.join(sets)} WHERE benefit_id=?", params
        )
        await db.commit()
    return await get_benefit(benefit_id)


async def delete_benefit(benefit_id: str) -> None:
    """Hard-delete. The service only calls this for a benefit with zero atoms."""
    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM product_benefit WHERE benefit_id=?", (benefit_id,))
        await db.commit()


# --------------------------------------------------------------------------
# atoms (angle / hook / body / cta)
# --------------------------------------------------------------------------
async def count_atoms_for_benefit(
    benefit_id: str, *, statuses: Sequence[str] | None = None
) -> int:
    db = await get_db()
    total = 0
    for table in _ATOM_TABLES:
        query = f"SELECT COUNT(*) FROM {table} WHERE benefit_id=?"
        params: list[Any] = [benefit_id]
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        cur = await db.execute(query, params)
        total += int((await cur.fetchone())[0])
    return total


async def get_benefit_atoms(benefit_id: str, *, status: str = "ACTIVE") -> dict[str, list]:
    db = await get_db()
    out: dict[str, list] = {}
    for kind, table in _ATOM_TABLE_BY_KIND.items():
        cur = await db.execute(
            f"SELECT * FROM {table} WHERE benefit_id=? AND status=? "
            "ORDER BY ordinal ASC, created_at ASC",
            (benefit_id, status),
        )
        out[kind] = [dict(r) for r in await cur.fetchall()]
    return out


async def mark_benefit_atoms_stale(benefit_id: str) -> None:
    """Flip this benefit's ACTIVE atoms → STALE (used on a material benefit edit).

    Only touches ``benefit_id`` — a change to Benefit A never stales Benefit B.
    """
    db = await get_db()
    async with _db_lock:
        for table in _ATOM_TABLES:
            await db.execute(
                f"UPDATE {table} SET status='STALE' WHERE benefit_id=? AND status='ACTIVE'",
                (benefit_id,),
            )
        await db.commit()


async def list_compatibility(angle_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not angle_ids:
        return []
    db = await get_db()
    placeholders = ",".join("?" * len(angle_ids))
    cur = await db.execute(
        f"SELECT * FROM creative_atom_compatibility WHERE angle_id IN ({placeholders})",
        list(angle_ids),
    )
    return [dict(r) for r in await cur.fetchall()]


# --------------------------------------------------------------------------
# build receipts + atomic build commit (amendment 6)
# --------------------------------------------------------------------------
def _receipt_insert(db, receipt: Mapping[str, Any]):
    return db.execute(
        """
        INSERT INTO creative_build_receipt (
            build_id, product_id, benefit_id, benefit_digest, pi_snapshot_id,
            pi_snapshot_version, input_digest, status, provider, model_key,
            provider_operation_id, output_digest, credit_delta, runtime_sha,
            receipt_json, token_usage_json, provider_calls, failure_code,
            failure_detail
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            receipt["build_id"],
            receipt["product_id"],
            receipt["benefit_id"],
            receipt["benefit_digest"],
            receipt.get("pi_snapshot_id"),
            receipt.get("pi_snapshot_version"),
            receipt["input_digest"],
            receipt["status"],
            receipt.get("provider"),
            receipt.get("model_key"),
            receipt.get("provider_operation_id"),
            receipt.get("output_digest"),
            receipt.get("credit_delta"),
            receipt.get("runtime_sha"),
            encode(receipt.get("receipt_json") or {}),
            encode(receipt.get("token_usage_json") or {}),
            int(receipt.get("provider_calls") or 0),
            receipt.get("failure_code"),
            receipt.get("failure_detail"),
        ),
    )


def _angle_insert(db, a: Mapping[str, Any]):
    return db.execute(
        """
        INSERT INTO creative_angle (
            angle_id, benefit_id, product_id, build_id, ordinal, angle_text,
            angle_digest, source_benefit_digest, status, provenance_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            a["angle_id"], a["benefit_id"], a["product_id"], a["build_id"],
            a["ordinal"], a["angle_text"], a["angle_digest"],
            a["source_benefit_digest"], a.get("status", "ACTIVE"),
            encode(a.get("provenance_json") or {}),
        ),
    )


def _atom_insert(db, table: str, id_col: str, row: Mapping[str, Any]):
    return db.execute(
        f"""
        INSERT INTO {table} (
            {id_col}, angle_id, benefit_id, build_id, ordinal, atom_text,
            text_digest, source_benefit_digest, status, provenance_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            row[id_col], row["angle_id"], row["benefit_id"], row["build_id"],
            row["ordinal"], row["atom_text"], row["text_digest"],
            row["source_benefit_digest"], row.get("status", "ACTIVE"),
            encode(row.get("provenance_json") or {}),
        ),
    )


async def commit_successful_build(
    *,
    receipt: Mapping[str, Any],
    angles: Sequence[Mapping[str, Any]],
    hooks: Sequence[Mapping[str, Any]],
    bodies: Sequence[Mapping[str, Any]],
    ctas: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Atomically supersede the benefit's prior ACTIVE atoms and insert the new
    COMPLETED build. All-or-nothing: any failure rolls back and the prior good
    ACTIVE build is left intact."""
    benefit_id = receipt["benefit_id"]
    db = await get_db()
    async with _db_lock:
        try:
            # 1) supersede prior ACTIVE atoms for THIS benefit only
            for table in _ATOM_TABLES:
                await db.execute(
                    f"UPDATE {table} SET status='SUPERSEDED' "
                    "WHERE benefit_id=? AND status='ACTIVE'",
                    (benefit_id,),
                )
            # 2) insert the new build (angles first for FK, then atoms)
            for a in angles:
                await _angle_insert(db, a)
            for h in hooks:
                await _atom_insert(db, "creative_hook", "hook_id", h)
            for b in bodies:
                await _atom_insert(db, "creative_body", "body_id", b)
            for c in ctas:
                await _atom_insert(db, "creative_cta", "cta_id", c)
            # 3) durable COMPLETED receipt
            await _receipt_insert(db, receipt)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return dict(receipt)


async def record_failed_build(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a FAILED build receipt with diagnostics and commit ZERO atoms."""
    db = await get_db()
    async with _db_lock:
        await _receipt_insert(db, {**receipt, "status": "FAILED"})
        await db.commit()
    return dict(receipt)


async def get_latest_build_receipt(benefit_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM creative_build_receipt WHERE benefit_id=? "
        "ORDER BY created_at DESC, build_id DESC LIMIT 1",
        (benefit_id,),
    )
    return _dict(await cur.fetchone())


async def list_build_receipts(benefit_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM creative_build_receipt WHERE benefit_id=? "
        "ORDER BY created_at DESC, build_id DESC",
        (benefit_id,),
    )
    return [dict(r) for r in await cur.fetchall()]


# --------------------------------------------------------------------------
# product_benefit_review (append-only audit — amendment 9)
# --------------------------------------------------------------------------
async def insert_review(row: Mapping[str, Any]) -> dict[str, Any]:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO product_benefit_review (
                review_id, benefit_id, product_id, action, from_status, to_status,
                reviewer_id, reviewer_note, pi_snapshot_id, pi_snapshot_version,
                decision_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["review_id"], row["benefit_id"], row["product_id"],
                row["action"], row["from_status"], row["to_status"],
                row["reviewer_id"], row.get("reviewer_note", ""),
                row.get("pi_snapshot_id"), row.get("pi_snapshot_version"),
                encode(row.get("decision_json") or {}),
            ),
        )
        await db.commit()
    return dict(row)


async def list_reviews(benefit_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_benefit_review WHERE benefit_id=? "
        "ORDER BY created_at ASC, review_id ASC",
        (benefit_id,),
    )
    return [dict(r) for r in await cur.fetchall()]
