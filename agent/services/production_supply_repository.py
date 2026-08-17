"""Persistence for the Macro Round 3 production-integration tables.

Row<->model mapping and idempotent inserts for materialization_link_v3 (P2),
production_copy_supply_manifest_v3 + manifest_item_v3 (P4), and the append-only
landbank_usage_v3 ledger (P5).  These records add no authority of their own; they
bind approved V3 supply to existing V2 production authority and to P6 allocation.
"""

from __future__ import annotations

from agent.db.schema import _db_lock, get_db
from agent.models.storyboard_landbank_v3_round3 import MaterializationLinkV3

_LINK_COLUMNS = (
    "link_id",
    "revision",
    "product_id",
    "master_id",
    "master_revision",
    "master_exact_content_digest",
    "projection_id",
    "projection_revision",
    "projection_exact_digest",
    "derivation_source",
    "approval_receipt_id",
    "approval_receipt_digest",
    "v2_blueprint_id",
    "v2_blueprint_revision",
    "v2_approval_snapshot_id",
    "product_truth_snapshot_id",
    "product_truth_snapshot_version",
    "product_truth_snapshot_digest",
    "formula_id",
    "formula_version",
    "evidence_digest",
    "target_duration_seconds",
    "materializer_version",
    "materialization_digest",
    "status",
    "source",
    "supersedes_link_id",
    "supersedes_link_revision",
    "created_at",
    "created_by",
)


def _link_from_row(row: dict) -> MaterializationLinkV3:
    return MaterializationLinkV3(**{column: row[column] for column in _LINK_COLUMNS})


async def insert_materialization_link(link: MaterializationLinkV3) -> None:
    db = await get_db()
    data = link.model_dump(mode="python")
    placeholders = ", ".join("?" for _ in _LINK_COLUMNS)
    async with _db_lock:
        await db.execute(
            f"INSERT INTO materialization_link_v3 ({', '.join(_LINK_COLUMNS)}) "
            f"VALUES ({placeholders})",
            tuple(data[column] for column in _LINK_COLUMNS),
        )
        await db.commit()


async def get_materialization_link(
    link_id: str, revision: int | None = None
) -> MaterializationLinkV3 | None:
    db = await get_db()
    if revision is None:
        cursor = await db.execute(
            "SELECT * FROM materialization_link_v3 WHERE link_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (link_id,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM materialization_link_v3 WHERE link_id=? AND revision=?",
            (link_id, revision),
        )
    row = await cursor.fetchone()
    return _link_from_row(dict(row)) if row is not None else None


async def get_link_for_blueprint(
    v2_blueprint_id: str, v2_blueprint_revision: int
) -> MaterializationLinkV3 | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM materialization_link_v3 "
        "WHERE v2_blueprint_id=? AND v2_blueprint_revision=? LIMIT 1",
        (v2_blueprint_id, v2_blueprint_revision),
    )
    row = await cursor.fetchone()
    return _link_from_row(dict(row)) if row is not None else None


async def list_links_for_product(
    product_id: str, *, status: str | None = None, limit: int = 200, offset: int = 0
) -> list[MaterializationLinkV3]:
    db = await get_db()
    query = "SELECT * FROM materialization_link_v3 WHERE product_id=?"
    params: list = [product_id]
    if status is not None:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC, link_id ASC LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    cursor = await db.execute(query, tuple(params))
    rows = await cursor.fetchall()
    return [_link_from_row(dict(row)) for row in rows]
