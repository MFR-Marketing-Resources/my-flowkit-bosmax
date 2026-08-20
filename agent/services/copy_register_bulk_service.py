"""Lapis 2 Phase 1 — bulk DRAFT copy generation over a product cohort.

Drives the EXISTING per-product Copy Register V2 generate flow
(`generate_angle_options` -> top angle -> `generate_blueprint`) across many products,
so the ~600-product catalog can be seeded with grounded copy without a human authoring
one at a time. It is a DEDICATED, credit-free lane (text-assist only, `credit_spend:0`)
that never touches the credit-gated video bulk engine.

Hard governance guarantees (do not weaken):
  * It only ever produces DRAFT blueprints. It NEVER approves and NEVER activates —
    human batch-approval (Phase 2) stays the sole path to production-valid copy.
  * Formula is always EXPLICIT: chosen per product by `copy_formula_recommender` and
    re-validated by `generate_blueprint`'s `_require_formula` (fails closed on unknown).
  * Idempotent: a product that already has a blueprint is SKIPPED, never duplicated.
  * Serial + paced: the text-assist provider has a ~30s ceiling per call and rate-limits
    under load, so items run one at a time with a small inter-item delay.

The run/item state lives in two self-contained additive tables created on first use;
this lane owns them and never migrates core schema.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from agent.db.schema import get_db
from agent.services import copy_register_v2_service as v2
from agent.services.copy_formula_recommender import recommend_formula

# Text-assist objective mirrors the proven Copy Authority console client contract
# (CopywritingSourceSelector): a single "conversion" objective + grounded next step.
_OBJECTIVE_ID = "conversion"
_OBJECTIVE_DEFINITION = "Help a qualified buyer choose a grounded next step."

# Serial pacing: a small gap between products on top of the provider's own latency.
_PACE_SECONDS = 1.5

_RUN_TABLE = "copy_bulk_run"
_ITEM_TABLE = "copy_bulk_item"

# In-process handle on live worker tasks so they are not garbage-collected mid-run.
_tasks: dict[str, asyncio.Task] = {}

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {_RUN_TABLE} (
    run_id          TEXT PRIMARY KEY,
    label           TEXT,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    total_expected  INTEGER NOT NULL DEFAULT 0,
    drafted         INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    requested_json  TEXT,
    error_log_json  TEXT,
    provenance_json TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE TABLE IF NOT EXISTS {_ITEM_TABLE} (
    item_id            TEXT PRIMARY KEY,
    run_id             TEXT NOT NULL,
    product_id         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'QUEUED',
    formula_id         TEXT,
    formula_rationale  TEXT,
    angle_id           TEXT,
    blueprint_id       TEXT,
    blueprint_revision INTEGER,
    error_code         TEXT,
    error_detail       TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_copy_bulk_item_run ON {_ITEM_TABLE}(run_id, status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_tables(db) -> None:
    await db.executescript(_SCHEMA_SQL)
    await db.commit()


async def _run_row(db, run_id: str) -> Optional[dict[str, Any]]:
    cur = await db.execute(f"SELECT * FROM {_RUN_TABLE} WHERE run_id = ?", (run_id,))
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def _items(db, run_id: str) -> list[dict[str, Any]]:
    cur = await db.execute(
        f"SELECT * FROM {_ITEM_TABLE} WHERE run_id = ? ORDER BY created_at, item_id",
        (run_id,),
    )
    rows = await cur.fetchall()
    await cur.close()
    return [dict(r) for r in rows]


def _run_payload(run: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_id": run["run_id"],
        "label": run.get("label"),
        "status": run["status"],
        "total_expected": run["total_expected"],
        "drafted": run["drafted"],
        "skipped": run["skipped"],
        "failed": run["failed"],
        "queued": sum(1 for i in items if i["status"] == "QUEUED"),
        "running": sum(1 for i in items if i["status"] == "RUNNING"),
        "credit_spend": 0,
        "created_at": run.get("created_at"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "items": [
            {
                "product_id": i["product_id"],
                "status": i["status"],
                "formula_id": i.get("formula_id"),
                "formula_rationale": i.get("formula_rationale"),
                "angle_id": i.get("angle_id"),
                "blueprint_id": i.get("blueprint_id"),
                "blueprint_revision": i.get("blueprint_revision"),
                "error_code": i.get("error_code"),
                "error_detail": i.get("error_detail"),
            }
            for i in items
        ],
    }


async def create_run(product_ids: list[str], label: str | None = None) -> dict[str, Any]:
    """Create a bulk copy run over an explicit product cohort.

    Every requested id becomes an item: eligible active products are QUEUED; products
    that already hold a blueprint (idempotency) or are missing/inactive are recorded
    SKIPPED with a reason, never generated. No generation happens here.
    """
    if not product_ids:
        raise ValueError("COPY_BULK_EMPTY_COHORT: at least one product_id is required")
    db = await get_db()
    await _ensure_tables(db)

    run_id = "cbr_" + uuid.uuid4().hex[:20]
    now = _now()
    seen: set[str] = set()
    queued = 0
    skipped = 0

    await db.execute(
        f"INSERT INTO {_RUN_TABLE} (run_id, label, status, total_expected, drafted, "
        f"skipped, failed, requested_json, created_at, updated_at) "
        f"VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, label, "PENDING", 0, 0, 0, 0, json.dumps(product_ids), now, now),
    )

    for product_id in product_ids:
        pid = (product_id or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        item_id = "cbi_" + uuid.uuid4().hex[:20]
        status, error_code, error_detail = "QUEUED", None, None

        cur = await db.execute(
            "SELECT id FROM product WHERE id = ? AND lifecycle_status = 'ACTIVE'", (pid,)
        )
        exists = await cur.fetchone()
        await cur.close()
        if not exists:
            status, error_code = "SKIPPED", "PRODUCT_NOT_ACTIVE"
        else:
            try:
                existing = await v2.list_blueprints(pid)
            except Exception:  # noqa: BLE001 - treat lookup failure as "unknown, generate"
                existing = []
            if existing:
                status, error_code = "SKIPPED", "EXISTING_BLUEPRINT"

        if status == "QUEUED":
            queued += 1
        else:
            skipped += 1
        await db.execute(
            f"INSERT INTO {_ITEM_TABLE} (item_id, run_id, product_id, status, "
            f"error_code, error_detail, attempts, created_at, updated_at) "
            f"VALUES (?,?,?,?,?,?,?,?,?)",
            (item_id, run_id, pid, status, error_code, error_detail, 0, now, now),
        )

    await db.execute(
        f"UPDATE {_RUN_TABLE} SET total_expected = ?, skipped = ?, updated_at = ? "
        f"WHERE run_id = ?",
        (len(seen), skipped, _now(), run_id),
    )
    await db.commit()
    run = await _run_row(db, run_id)
    return _run_payload(run, await _items(db, run_id))


async def _generate_one(db, item: dict[str, Any]) -> None:
    """Generate ONE DRAFT for a queued item. Fails closed, never approves/activates."""
    pid = item["product_id"]
    now = _now()
    await db.execute(
        f"UPDATE {_ITEM_TABLE} SET status='RUNNING', attempts=attempts+1, updated_at=? "
        f"WHERE item_id=?",
        (now, item["item_id"]),
    )
    await db.commit()

    cur = await db.execute("SELECT * FROM product WHERE id = ?", (pid,))
    prow = await cur.fetchone()
    await cur.close()
    product = dict(prow) if prow else {}
    rec = recommend_formula(product)
    formula_id = rec["formula_id"]

    angle_res = await v2.generate_angle_options(pid, formula_id, _OBJECTIVE_ID)
    angles = angle_res.get("angles") or []
    if not angles:
        raise v2.CopyRegisterV2Error(
            "COPY_BULK_NO_ANGLES", "Angle generation returned no options."
        )
    top = angles[0]
    blueprint = await v2.generate_blueprint(
        product_id=pid,
        formula_id=formula_id,
        objective_id=_OBJECTIVE_ID,
        objective_definition=_OBJECTIVE_DEFINITION,
        angle_id=top["angle_id"],
        angle_definition=top["definition"],
        evidence_fact_ids=list(top.get("evidence_fact_ids") or []),
    )
    await db.execute(
        f"UPDATE {_ITEM_TABLE} SET status='DRAFTED', formula_id=?, formula_rationale=?, "
        f"angle_id=?, blueprint_id=?, blueprint_revision=?, error_code=NULL, "
        f"error_detail=NULL, updated_at=? WHERE item_id=?",
        (
            formula_id,
            rec["rationale"],
            top["angle_id"],
            blueprint.blueprint_id,
            blueprint.revision,
            _now(),
            item["item_id"],
        ),
    )
    await db.commit()


async def _run_loop(run_id: str) -> None:
    db = await get_db()
    try:
        while True:
            run = await _run_row(db, run_id)
            if not run or run["status"] == "CANCELLED":
                break
            cur = await db.execute(
                f"SELECT * FROM {_ITEM_TABLE} WHERE run_id=? AND status='QUEUED' "
                f"ORDER BY created_at, item_id LIMIT 1",
                (run_id,),
            )
            row = await cur.fetchone()
            await cur.close()
            if not row:
                break
            item = dict(row)
            try:
                await _generate_one(db, item)
                await db.execute(
                    f"UPDATE {_RUN_TABLE} SET drafted=drafted+1, updated_at=? "
                    f"WHERE run_id=?",
                    (_now(), run_id),
                )
            except v2.CopyRegisterV2Error as exc:
                await _fail_item(db, run_id, item["item_id"], exc.code, str(exc))
            except Exception as exc:  # noqa: BLE001 - isolate per-item failure
                await _fail_item(db, run_id, item["item_id"], "UNEXPECTED", str(exc))
            await db.commit()
            await asyncio.sleep(_PACE_SECONDS)
        await _finalize(db, run_id)
    except Exception as exc:  # noqa: BLE001 - never leave a run wedged in RUNNING
        await db.execute(
            f"UPDATE {_RUN_TABLE} SET status='FAILED', error_log_json=?, "
            f"finished_at=?, updated_at=? WHERE run_id=?",
            (json.dumps({"loop_error": str(exc)}), _now(), _now(), run_id),
        )
        await db.commit()
    finally:
        _tasks.pop(run_id, None)


async def _fail_item(db, run_id: str, item_id: str, code: str, detail: str) -> None:
    await db.execute(
        f"UPDATE {_ITEM_TABLE} SET status='FAILED', error_code=?, error_detail=?, "
        f"updated_at=? WHERE item_id=?",
        (code, detail[:2000], _now(), item_id),
    )
    await db.execute(
        f"UPDATE {_RUN_TABLE} SET failed=failed+1, updated_at=? WHERE run_id=?",
        (_now(), run_id),
    )


async def _finalize(db, run_id: str) -> None:
    run = await _run_row(db, run_id)
    if not run or run["status"] == "CANCELLED":
        return
    if run["failed"] == 0:
        status = "COMPLETED"
    elif run["drafted"] > 0:
        status = "PARTIAL_FAILED"
    else:
        status = "FAILED"
    await db.execute(
        f"UPDATE {_RUN_TABLE} SET status=?, finished_at=?, updated_at=? WHERE run_id=?",
        (status, _now(), _now(), run_id),
    )
    await db.commit()


async def start_run(run_id: str) -> dict[str, Any]:
    """Begin generating DRAFTs for a PENDING run (background, serial, credit-free)."""
    db = await get_db()
    await _ensure_tables(db)
    run = await _run_row(db, run_id)
    if not run:
        raise ValueError(f"COPY_BULK_RUN_NOT_FOUND: {run_id}")
    if run["status"] != "PENDING":
        raise ValueError(f"COPY_BULK_RUN_NOT_PENDING: {run_id} is {run['status']}")
    now = _now()
    await db.execute(
        f"UPDATE {_RUN_TABLE} SET status='RUNNING', started_at=?, updated_at=? "
        f"WHERE run_id=?",
        (now, now, run_id),
    )
    await db.commit()
    _tasks[run_id] = asyncio.create_task(_run_loop(run_id))
    return _run_payload(await _run_row(db, run_id), await _items(db, run_id))


async def cancel_run(run_id: str) -> dict[str, Any]:
    """Request cancellation; the loop stops before the next item."""
    db = await get_db()
    await _ensure_tables(db)
    run = await _run_row(db, run_id)
    if not run:
        raise ValueError(f"COPY_BULK_RUN_NOT_FOUND: {run_id}")
    if run["status"] in ("RUNNING", "PENDING"):
        await db.execute(
            f"UPDATE {_RUN_TABLE} SET status='CANCELLED', finished_at=?, updated_at=? "
            f"WHERE run_id=?",
            (_now(), _now(), run_id),
        )
        await db.commit()
    return _run_payload(await _run_row(db, run_id), await _items(db, run_id))


async def get_run(run_id: str) -> dict[str, Any]:
    db = await get_db()
    await _ensure_tables(db)
    run = await _run_row(db, run_id)
    if not run:
        raise ValueError(f"COPY_BULK_RUN_NOT_FOUND: {run_id}")
    return _run_payload(run, await _items(db, run_id))


async def list_runs(limit: int = 50) -> dict[str, Any]:
    db = await get_db()
    await _ensure_tables(db)
    cur = await db.execute(
        f"SELECT * FROM {_RUN_TABLE} ORDER BY created_at DESC LIMIT ?", (int(limit),)
    )
    rows = await cur.fetchall()
    await cur.close()
    return {
        "runs": [
            {
                "run_id": r["run_id"],
                "label": r["label"],
                "status": r["status"],
                "total_expected": r["total_expected"],
                "drafted": r["drafted"],
                "skipped": r["skipped"],
                "failed": r["failed"],
                "created_at": r["created_at"],
            }
            for r in (dict(x) for x in rows)
        ]
    }


__all__ = [
    "create_run",
    "start_run",
    "cancel_run",
    "get_run",
    "list_runs",
]
