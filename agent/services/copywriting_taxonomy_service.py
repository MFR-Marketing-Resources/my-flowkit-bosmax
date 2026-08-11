"""Workbook-backed copywriting taxonomy registry and read-only resolver.

The registry is an authority lookup for copywriting dependencies. It does not
rewrite Product Truth, the existing scene-strategy taxonomy, copy sets, or
copywriting components. Product matching is deliberately exact-or-fail-closed:
an explicit workbook code wins; otherwise the category/subcategory/type triple
must resolve to one active registry row.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.db import crud
from agent.db.schema import _db_lock, get_db


AUTHORITY_PATH = (
    Path(__file__).resolve().parents[1]
    / "authority"
    / "copywriting_taxonomy_registry.json"
)
SCHEMA_VERSION = "copywriting-taxonomy-v1"
SEED_CONFIRMATION = "SEED_COPYWRITING_TAXONOMY_REGISTRY"
REGISTRY_TABLE = "copywriting_taxonomy_registry"

_AUTHORITY_FIELDS = (
    "cluster_name",
    "product_type_code",
    "display_name",
    "category",
    "subcategory",
    "type",
    "copywriting_angle",
    "source_row",
)
_SOURCE_FIELDS = (
    "cluster_name",
    "display_name",
    "category",
    "subcategory",
    "type",
    "copywriting_angle",
    "source_workbook",
    "source_sheet",
    "source_row",
)
_CODE_FIELDS = (
    "copywriting_product_type_code",
    "product_type_code",
    "type_code",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _authority_error(message: str) -> ValueError:
    return ValueError(f"COPYWRITING_TAXONOMY_AUTHORITY_INVALID: {message}")


def load_authority_payload() -> dict[str, Any]:
    """Load and validate the committed workbook-derived authority file."""

    if not AUTHORITY_PATH.is_file():
        raise _authority_error(f"missing file: {AUTHORITY_PATH}")
    try:
        payload = json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _authority_error(str(exc)) from exc
    if not isinstance(payload, dict):
        raise _authority_error("root must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise _authority_error("unsupported schema_version")
    records = payload.get("records")
    if not isinstance(records, list):
        raise _authority_error("records must be a list")
    if payload.get("record_count") != len(records):
        raise _authority_error("record_count does not match records")

    seen_codes: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise _authority_error(f"record {index} must be an object")
        for field in _AUTHORITY_FIELDS[:-1]:
            if not _text(record.get(field)):
                raise _authority_error(f"record {index} missing {field}")
        code = _text(record.get("product_type_code"))
        if code in seen_codes:
            raise _authority_error(f"duplicate product_type_code: {code}")
        seen_codes.add(code)
        try:
            source_row = int(record.get("source_row"))
        except (TypeError, ValueError) as exc:
            raise _authority_error(f"record {index} source_row is invalid") from exc
        if source_row < 3:
            raise _authority_error(f"record {index} source_row must be >= 3")

    return payload


def load_authority_records() -> list[dict[str, Any]]:
    """Return normalized authority records ready for database seeding."""

    payload = load_authority_payload()
    source_workbook = _text(payload.get("source_workbook"))
    source_sheet = _text(payload.get("source_sheet"))
    if not source_workbook or not source_sheet:
        raise _authority_error("source metadata is incomplete")

    records: list[dict[str, Any]] = []
    for record in payload["records"]:
        normalized = {
            "cluster_name": _text(record["cluster_name"]),
            "product_type_code": _text(record["product_type_code"]),
            "display_name": _text(record["display_name"]),
            "category": _text(record["category"]),
            "subcategory": _text(record["subcategory"]),
            "type": _text(record["type"]),
            "copywriting_angle": _text(record["copywriting_angle"]),
            "source_workbook": source_workbook,
            "source_sheet": source_sheet,
            "source_row": int(record["source_row"]),
        }
        records.append(normalized)
    return records


def _entry(row: Any) -> dict[str, Any]:
    return dict(row)


def _metadata() -> dict[str, str]:
    payload = load_authority_payload()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_workbook": _text(payload["source_workbook"]),
        "source_sheet": _text(payload["source_sheet"]),
    }


async def list_copywriting_taxonomy_entries(
    *,
    cluster_name: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    type_name: str | None = None,
    product_type_code: str | None = None,
    registry_status: str | None = None,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List registered mappings with bounded, parameterized filters."""

    where: list[str] = []
    params: list[Any] = []
    exact_filters = (
        ("cluster_name", cluster_name),
        ("category", category),
        ("subcategory", subcategory),
        ("type", type_name),
        ("product_type_code", product_type_code),
        ("registry_status", registry_status),
    )
    for column, value in exact_filters:
        normalized = _text(value)
        if normalized:
            if column == "registry_status" and normalized not in {
                "ACTIVE",
                "REVIEW_REQUIRED",
            }:
                raise ValueError("INVALID_COPYWRITING_TAXONOMY_REGISTRY_STATUS")
            where.append(f"{column}=?")
            params.append(normalized)
    normalized_query = _text(query)
    if normalized_query:
        like = f"%{normalized_query}%"
        where.append(
            "(product_type_code LIKE ? COLLATE NOCASE "
            "OR display_name LIKE ? COLLATE NOCASE "
            "OR cluster_name LIKE ? COLLATE NOCASE "
            "OR category LIKE ? COLLATE NOCASE "
            "OR subcategory LIKE ? COLLATE NOCASE "
            "OR type LIKE ? COLLATE NOCASE "
            "OR copywriting_angle LIKE ? COLLATE NOCASE)"
        )
        params.extend([like] * 7)

    where_sql = f" WHERE {' AND '.join(where)}" if where else ""
    bounded_limit = min(max(int(limit), 1), 1000)
    bounded_offset = max(int(offset), 0)
    db = await get_db()
    count_cursor = await db.execute(
        f"SELECT COUNT(*) AS total FROM {REGISTRY_TABLE}{where_sql}",
        params,
    )
    total = int((await count_cursor.fetchone())["total"])
    cursor = await db.execute(
        f"SELECT * FROM {REGISTRY_TABLE}{where_sql} "
        "ORDER BY cluster_name, product_type_code LIMIT ? OFFSET ?",
        [*params, bounded_limit, bounded_offset],
    )
    items = [_entry(row) for row in await cursor.fetchall()]
    return {
        **_metadata(),
        "items": items,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
        "filters": {
            "cluster_name": _text(cluster_name) or None,
            "category": _text(category) or None,
            "subcategory": _text(subcategory) or None,
            "type": _text(type_name) or None,
            "product_type_code": _text(product_type_code) or None,
            "registry_status": _text(registry_status) or None,
            "query": normalized_query or None,
        },
    }


async def get_copywriting_taxonomy_entry(
    product_type_code: str,
    *,
    cluster_name: str | None = None,
    active_only: bool = False,
) -> dict[str, Any] | None:
    code = _text(product_type_code)
    if not code:
        return None
    db = await get_db()
    clauses = ["product_type_code=?"]
    params: list[Any] = [code]
    if _text(cluster_name):
        clauses.append("cluster_name=?")
        params.append(_text(cluster_name))
    if active_only:
        clauses.append("registry_status='ACTIVE'")
    cursor = await db.execute(
        f"SELECT * FROM {REGISTRY_TABLE} WHERE {' AND '.join(clauses)}",
        params,
    )
    row = await cursor.fetchone()
    return _entry(row) if row else None


async def get_copywriting_taxonomy_rollup() -> dict[str, Any]:
    """Return deterministic counts for the complete registered dependency map."""

    db = await get_db()
    total_cursor = await db.execute(
        f"SELECT COUNT(*) AS total_product_types, "
        "COUNT(DISTINCT cluster_name) AS cluster_count, "
        "COUNT(DISTINCT category) AS category_count, "
        "COUNT(DISTINCT subcategory) AS subcategory_count, "
        "COUNT(DISTINCT type) AS type_count, "
        "COUNT(DISTINCT copywriting_angle) AS angle_count "
        f"FROM {REGISTRY_TABLE}"
    )
    totals = dict(await total_cursor.fetchone())
    cluster_cursor = await db.execute(
        f"SELECT cluster_name, COUNT(*) AS product_type_count, "
        "COUNT(DISTINCT category) AS category_count, "
        "COUNT(DISTINCT subcategory) AS subcategory_count, "
        "COUNT(DISTINCT type) AS type_count, "
        "COUNT(DISTINCT copywriting_angle) AS angle_count "
        f"FROM {REGISTRY_TABLE} GROUP BY cluster_name ORDER BY cluster_name"
    )
    clusters = [_entry(row) for row in await cluster_cursor.fetchall()]
    return {
        **_metadata(),
        **{key: int(value) for key, value in totals.items()},
        "clusters": clusters,
    }


def _source_changed(record: dict[str, Any], existing: dict[str, Any]) -> bool:
    return any(
        (int(existing[field]) if field == "source_row" else _text(existing[field]))
        != record[field]
        for field in _SOURCE_FIELDS
    )


def _status_counts(existing_rows: list[dict[str, Any]], records: list[dict[str, Any]]) -> tuple[int, int]:
    status_by_code = {
        _text(row["product_type_code"]): _text(row["registry_status"]) or "ACTIVE"
        for row in existing_rows
    }
    for record in records:
        status_by_code.setdefault(record["product_type_code"], "ACTIVE")
    active = sum(1 for status in status_by_code.values() if status == "ACTIVE")
    review = sum(
        1 for status in status_by_code.values() if status == "REVIEW_REQUIRED"
    )
    return active, review


async def seed_copywriting_taxonomy_registry(
    *,
    dry_run: bool = True,
    confirm_apply: str | None = None,
) -> dict[str, Any]:
    """Plan or apply the 313-row authority seed without touching products."""

    records = load_authority_records()
    db = await get_db()
    cursor = await db.execute(f"SELECT * FROM {REGISTRY_TABLE}")
    existing_rows = [_entry(row) for row in await cursor.fetchall()]
    existing_by_code = {
        _text(row["product_type_code"]): row for row in existing_rows
    }
    inserts = [
        record
        for record in records
        if record["product_type_code"] not in existing_by_code
    ]
    updates = [
        record
        for record in records
        if record["product_type_code"] in existing_by_code
        and _source_changed(record, existing_by_code[record["product_type_code"]])
    ]
    unchanged_count = len(records) - len(inserts) - len(updates)

    if not dry_run and confirm_apply != SEED_CONFIRMATION:
        raise ValueError(f"COPYWRITING_TAXONOMY_CONFIRMATION_REQUIRED:{SEED_CONFIRMATION}")

    mutation_performed = False
    if not dry_run and (inserts or updates):
        now = _now()
        sql = f"""
INSERT INTO {REGISTRY_TABLE} (
    product_type_code, cluster_name, display_name, category, subcategory, type,
    copywriting_angle, source_workbook, source_sheet, source_row,
    registry_status, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?, 'ACTIVE', ?, ?)
ON CONFLICT(product_type_code) DO UPDATE SET
    cluster_name=excluded.cluster_name,
    display_name=excluded.display_name,
    category=excluded.category,
    subcategory=excluded.subcategory,
    type=excluded.type,
    copywriting_angle=excluded.copywriting_angle,
    source_workbook=excluded.source_workbook,
    source_sheet=excluded.source_sheet,
    source_row=excluded.source_row,
    updated_at=excluded.updated_at
"""
        async with _db_lock:
            try:
                await db.execute("BEGIN IMMEDIATE")
                for record in [*inserts, *updates]:
                    await db.execute(
                        sql,
                        (
                            record["product_type_code"],
                            record["cluster_name"],
                            record["display_name"],
                            record["category"],
                            record["subcategory"],
                            record["type"],
                            record["copywriting_angle"],
                            record["source_workbook"],
                            record["source_sheet"],
                            record["source_row"],
                            now,
                            now,
                        ),
                    )
                await db.commit()
                mutation_performed = True
            except Exception:
                await db.rollback()
                raise

    if mutation_performed:
        active_count, review_required_count = await _current_status_counts(db)
    else:
        active_count, review_required_count = _status_counts(existing_rows, records)
    return {
        "dry_run": dry_run,
        "mutation_performed": mutation_performed,
        "seed_count": len(records),
        "planned_insert_count": len(inserts),
        "planned_update_count": len(updates),
        "unchanged_count": unchanged_count,
        "active_count": active_count,
        "review_required_count": review_required_count,
        "confirmation_required": None if not dry_run else SEED_CONFIRMATION,
    }


async def _current_status_counts(db: Any) -> tuple[int, int]:
    cursor = await db.execute(
        f"SELECT registry_status, COUNT(*) AS count FROM {REGISTRY_TABLE} "
        "GROUP BY registry_status"
    )
    counts = {_text(row["registry_status"]): int(row["count"]) for row in await cursor.fetchall()}
    return counts.get("ACTIVE", 0), counts.get("REVIEW_REQUIRED", 0)


def _first_text(product: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = _text(product.get(field))
        if value:
            return value
    return ""


async def resolve_product_taxonomy_record(
    product: dict[str, Any],
) -> dict[str, Any]:
    """Resolve a product against active mappings using exact evidence only."""

    product_id = _first_text(product, ("id", "product_id"))
    product_name = _first_text(product, ("product_display_name", "raw_product_title"))
    code = _first_text(product, _CODE_FIELDS)
    cluster = _first_text(product, ("copywriting_cluster", "cluster_name", "cluster"))
    category = _text(product.get("category"))
    subcategory = _text(product.get("subcategory"))
    type_name = _text(product.get("type"))
    product_fields = {
        "product_type_code": code or None,
        "cluster_name": cluster or None,
        "category": category or None,
        "subcategory": subcategory or None,
        "type": type_name or None,
        "product_type_id": _text(product.get("product_type_id")) or None,
    }

    if code:
        code_match = await get_copywriting_taxonomy_entry(code, active_only=True)
        if code_match is None or (
            cluster and code_match["cluster_name"] != cluster
        ):
            # An explicit but unknown/conflicting code must not silently fall
            # through to a weaker field match. The caller gets the evidence it
            # supplied back as UNMATCHED and can review it in round two.
            return {
                "product_id": product_id,
                "product_display_name": product_name,
                "match_status": "UNMATCHED",
                "matched_by": "PRODUCT_TYPE_CODE",
                "product_fields": product_fields,
                "match": None,
                "candidates": [code_match] if code_match else [],
            }
        return {
            "product_id": product_id,
            "product_display_name": product_name,
            "match_status": "EXACT_CODE",
            "matched_by": "PRODUCT_TYPE_CODE",
            "product_fields": product_fields,
            "match": code_match,
            "candidates": [code_match],
        }

    if category and subcategory and type_name:
        db = await get_db()
        clauses = [
            "category=?",
            "subcategory=?",
            "type=?",
            "registry_status='ACTIVE'",
        ]
        params: list[Any] = [category, subcategory, type_name]
        if cluster:
            clauses.append("cluster_name=?")
            params.append(cluster)
        cursor = await db.execute(
            f"SELECT * FROM {REGISTRY_TABLE} WHERE {' AND '.join(clauses)} "
            "ORDER BY product_type_code",
            params,
        )
        candidates = [_entry(row) for row in await cursor.fetchall()]
        if len(candidates) == 1:
            return {
                "product_id": product_id,
                "product_display_name": product_name,
                "match_status": "EXACT_TAXONOMY",
                "matched_by": "CATEGORY_SUBCATEGORY_TYPE",
                "product_fields": product_fields,
                "match": candidates[0],
                "candidates": candidates,
            }
        if len(candidates) > 1:
            return {
                "product_id": product_id,
                "product_display_name": product_name,
                "match_status": "AMBIGUOUS",
                "matched_by": "CATEGORY_SUBCATEGORY_TYPE",
                "product_fields": product_fields,
                "match": None,
                "candidates": candidates,
            }

    return {
        "product_id": product_id,
        "product_display_name": product_name,
        "match_status": "UNMATCHED",
        "matched_by": None,
        "product_fields": product_fields,
        "match": None,
        "candidates": [],
    }


async def resolve_product_taxonomy(product_id: str) -> dict[str, Any] | None:
    product = await crud.get_product(product_id)
    if product is None:
        return None
    return await resolve_product_taxonomy_record(product)
