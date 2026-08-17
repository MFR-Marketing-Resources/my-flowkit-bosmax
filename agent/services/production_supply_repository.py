"""Persistence for the Macro Round 3 production-integration tables.

Row<->model mapping and idempotent inserts for materialization_link_v3 (P2),
production_copy_supply_manifest_v3 + manifest_item_v3 (P4), and the append-only
landbank_usage_v3 ledger (P5).  These records add no authority of their own; they
bind approved V3 supply to existing V2 production authority and to P6 allocation.
"""

from __future__ import annotations

from agent.db.schema import _db_lock, get_db
from agent.models.storyboard_landbank_v3_round3 import (
    LandbankUsageV3,
    ManifestItemV3,
    MaterializationLinkV3,
    ProductionCopySupplyManifestV3,
)

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


# --------------------------------------------------------------------------- #
# production_copy_supply_manifest_v3 + manifest_item_v3 (P4)
# --------------------------------------------------------------------------- #
_MANIFEST_COLUMNS = (
    "manifest_id",
    "revision",
    "product_id",
    "production_plan_id",
    "campaign_key",
    "recipe_policy_version",
    "reuse_policy_json",
    "requested_capacity",
    "duration_mix_json",
    "language_profile",
    "source_authority_digest",
    "item_count",
    "valid_item_count",
    "blocked_item_count",
    "manifest_digest",
    "status",
    "source",
    "supersedes_manifest_id",
    "supersedes_manifest_revision",
    "created_at",
    "created_by",
    "frozen_at",
)

_ITEM_COLUMNS = (
    "item_id",
    "manifest_id",
    "manifest_revision",
    "item_index",
    "product_id",
    "master_id",
    "master_revision",
    "projection_id",
    "projection_revision",
    "projection_exact_digest",
    "approval_receipt_id",
    "materialization_link_id",
    "materialization_link_revision",
    "v2_blueprint_id",
    "v2_blueprint_revision",
    "v2_approval_snapshot_id",
    "product_truth_snapshot_digest",
    "formula_id",
    "formula_version",
    "duration_seconds",
    "item_digest",
    "created_at",
    "created_by",
)


def _manifest_from_row(row: dict) -> ProductionCopySupplyManifestV3:
    return ProductionCopySupplyManifestV3(
        **{column: row[column] for column in _MANIFEST_COLUMNS}
    )


def _item_from_row(row: dict) -> ManifestItemV3:
    return ManifestItemV3(**{column: row[column] for column in _ITEM_COLUMNS})


async def next_manifest_revision(manifest_id: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "SELECT MAX(revision) FROM production_copy_supply_manifest_v3 WHERE manifest_id=?",
        (manifest_id,),
    )
    row = await cursor.fetchone()
    return int(row[0]) + 1 if row and row[0] is not None else 1


async def insert_manifest_with_items(
    manifest: ProductionCopySupplyManifestV3, items: list[ManifestItemV3]
) -> None:
    db = await get_db()
    manifest_data = manifest.model_dump(mode="python")
    manifest_placeholders = ", ".join("?" for _ in _MANIFEST_COLUMNS)
    item_placeholders = ", ".join("?" for _ in _ITEM_COLUMNS)
    async with _db_lock:
        await db.execute(
            f"INSERT INTO production_copy_supply_manifest_v3 "
            f"({', '.join(_MANIFEST_COLUMNS)}) VALUES ({manifest_placeholders})",
            tuple(manifest_data[column] for column in _MANIFEST_COLUMNS),
        )
        for item in items:
            item_data = item.model_dump(mode="python")
            await db.execute(
                f"INSERT INTO manifest_item_v3 ({', '.join(_ITEM_COLUMNS)}) "
                f"VALUES ({item_placeholders})",
                tuple(item_data[column] for column in _ITEM_COLUMNS),
            )
        await db.commit()


async def get_manifest(
    manifest_id: str, revision: int | None = None
) -> ProductionCopySupplyManifestV3 | None:
    db = await get_db()
    if revision is None:
        cursor = await db.execute(
            "SELECT * FROM production_copy_supply_manifest_v3 WHERE manifest_id=? "
            "ORDER BY revision DESC LIMIT 1",
            (manifest_id,),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM production_copy_supply_manifest_v3 "
            "WHERE manifest_id=? AND revision=?",
            (manifest_id, revision),
        )
    row = await cursor.fetchone()
    return _manifest_from_row(dict(row)) if row is not None else None


async def list_manifest_items(
    manifest_id: str, manifest_revision: int
) -> list[ManifestItemV3]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM manifest_item_v3 WHERE manifest_id=? AND manifest_revision=? "
        "ORDER BY item_index ASC",
        (manifest_id, manifest_revision),
    )
    rows = await cursor.fetchall()
    return [_item_from_row(dict(row)) for row in rows]


async def set_manifest_frozen(
    manifest_id: str, revision: int, *, frozen_at: str
) -> None:
    """DRAFT/VALIDATED -> FROZEN.  The DB trigger keeps a FROZEN row immutable."""

    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE production_copy_supply_manifest_v3 SET status='FROZEN', frozen_at=? "
            "WHERE manifest_id=? AND revision=? AND status IN ('DRAFT','VALIDATED')",
            (frozen_at, manifest_id, revision),
        )
        await db.commit()


# --------------------------------------------------------------------------- #
# landbank_usage_v3 — append-only production usage ledger (P5)
# --------------------------------------------------------------------------- #
_USAGE_COLUMNS = (
    "usage_id",
    "product_id",
    "master_id",
    "master_revision",
    "projection_id",
    "projection_revision",
    "v2_blueprint_id",
    "v2_blueprint_revision",
    "v2_approval_snapshot_id",
    "materialization_link_id",
    "materialization_link_revision",
    "manifest_id",
    "manifest_revision",
    "manifest_item_id",
    "p6_plan_id",
    "p6_item_id",
    "duration_seconds",
    "campaign_key",
    "usage_type",
    "outcome_status",
    "reason_code",
    "authority_digest",
    "event_digest",
    "created_at",
    "created_by",
)


def _usage_from_row(row: dict) -> LandbankUsageV3:
    return LandbankUsageV3(**{column: row[column] for column in _USAGE_COLUMNS})


async def insert_usage_event(event: LandbankUsageV3) -> None:
    db = await get_db()
    data = event.model_dump(mode="python")
    placeholders = ", ".join("?" for _ in _USAGE_COLUMNS)
    async with _db_lock:
        await db.execute(
            f"INSERT INTO landbank_usage_v3 ({', '.join(_USAGE_COLUMNS)}) "
            f"VALUES ({placeholders})",
            tuple(data[column] for column in _USAGE_COLUMNS),
        )
        await db.commit()


async def list_usage_for_plan(p6_plan_id: str) -> list[LandbankUsageV3]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM landbank_usage_v3 WHERE p6_plan_id=? ORDER BY created_at ASC, usage_id ASC",
        (p6_plan_id,),
    )
    rows = await cursor.fetchall()
    return [_usage_from_row(dict(row)) for row in rows]


async def list_usage_for_manifest_item(manifest_item_id: str) -> list[LandbankUsageV3]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM landbank_usage_v3 WHERE manifest_item_id=? "
        "ORDER BY created_at ASC, usage_id ASC",
        (manifest_item_id,),
    )
    rows = await cursor.fetchall()
    return [_usage_from_row(dict(row)) for row in rows]
