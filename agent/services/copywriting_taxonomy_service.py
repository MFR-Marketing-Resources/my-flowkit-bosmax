"""Workbook-backed copywriting taxonomy registry and read-only resolver.

The registry is an authority lookup for copywriting dependencies. It does not
rewrite Product Truth, the existing scene-strategy taxonomy, copy sets, or
copywriting components. Product matching is deliberately exact-or-fail-closed:
an explicit workbook code wins; otherwise the category/subcategory/type triple
must resolve to one active registry row.
"""

from __future__ import annotations

import json
import hashlib
from difflib import SequenceMatcher
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
SCHEMA_VERSION = "copywriting-taxonomy-v2"
SEED_CONFIRMATION = "SEED_COPYWRITING_TAXONOMY_REGISTRY"
REGISTRY_TABLE = "copywriting_taxonomy_registry"

CATEGORY_ALIASES = {
    "Health": "Health & Personal Care",
    "Health & Personal Care": "Health & Personal Care",
    "Sports & Outdoor": "Sports & Outdoors",
    "Sports & Outdoors": "Sports & Outdoors",
}
TYPE_COLLISION_WINNERS = {
    "Beauty & Personal Care::Facial Cleansing::Brightening Facial Soap":
        "facial_cleansing_soap",
}

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
    "source_category",
    "source_subcategory",
    "source_type",
    "canonicalization_rules_json",
    "source_header_row",
    "authority_version",
    "source_sha256",
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


def canonical_category(value: Any) -> str:
    normalized = _text(value)
    return CATEGORY_ALIASES.get(normalized, normalized)


def taxonomy_key(category: Any, subcategory: Any, type_name: Any) -> str:
    return "::".join(
        (canonical_category(category), _text(subcategory), _text(type_name))
    )


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
    if payload.get("source_header_row") != 2:
        raise _authority_error("source_header_row must be 2")

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
        if canonical_category(record.get("category")) != _text(
            record.get("category")
        ):
            raise _authority_error(
                f"record {index} category must already be canonicalized"
            )

    return payload


def load_authority_records() -> list[dict[str, Any]]:
    """Return normalized authority records ready for database seeding."""

    payload = load_authority_payload()
    source_workbook = _text(payload.get("source_workbook"))
    source_sheet = _text(payload.get("source_sheet"))
    if not source_workbook or not source_sheet:
        raise _authority_error("source metadata is incomplete")

    source_sha256 = _text(payload.get("source_sha256"))
    if not source_sha256:
        source_sha256 = hashlib.sha256(AUTHORITY_PATH.read_bytes()).hexdigest()
    source_header_row = int(payload.get("source_header_row", 2))
    records: list[dict[str, Any]] = []
    for record in payload["records"]:
        source_category = _text(record.get("source_category")) or _text(
            record["category"]
        )
        source_subcategory = _text(record.get("source_subcategory")) or _text(
            record["subcategory"]
        )
        source_type = _text(record.get("source_type")) or _text(record["type"])
        canonicalization_rules = record.get("canonicalization_rules") or []
        if not isinstance(canonicalization_rules, list):
            raise _authority_error("canonicalization_rules must be a list")
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
            "source_category": source_category,
            "source_subcategory": source_subcategory,
            "source_type": source_type,
            "canonicalization_rules_json": json.dumps(
                canonicalization_rules, ensure_ascii=False, separators=(",", ":")
            ),
            "source_header_row": source_header_row,
            "authority_version": SCHEMA_VERSION,
            "source_sha256": source_sha256,
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


class CopywritingTaxonomySelectionError(ValueError):
    """Stable fail-closed error for an unmapped product taxonomy selection."""

    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(str(detail))


def _tree_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "copywriting_angle": _text(row.get("copywriting_angle")),
        "product_type_code": _text(row.get("product_type_code")),
        "cluster": _text(row.get("cluster_name")),
        "display_name": _text(row.get("display_name")),
        "category": canonical_category(row.get("category")),
        "subcategory": _text(row.get("subcategory")),
        "type": _text(row.get("type")),
    }


def _nearest_tree_records(
    records: list[dict[str, Any]],
    category: str,
    subcategory: str,
    type_name: str,
) -> list[dict[str, Any]]:
    target = taxonomy_key(category, subcategory, type_name).casefold()
    scored = [
        (
            SequenceMatcher(
                None,
                target,
                taxonomy_key(
                    record["category"], record["subcategory"], record["type"]
                ).casefold(),
            ).ratio(),
            record,
        )
        for record in records
    ]
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1]["category"],
            item[1]["subcategory"],
            item[1]["type"],
            item[1]["product_type_code"],
        )
    )
    return [record for _, record in scored[:3]]


async def get_copywriting_taxonomy_tree() -> dict[str, Any]:
    """Build the canonical, strict Category -> Subcategory -> Type cascade."""

    db = await get_db()
    cursor = await db.execute(
        f"SELECT * FROM {REGISTRY_TABLE} "
        "WHERE registry_status='ACTIVE' "
        "ORDER BY category, subcategory, type, product_type_code"
    )
    rows = [_entry(row) for row in await cursor.fetchall()]
    categories: set[str] = set()
    subcategories: dict[str, set[str]] = {}
    types: dict[str, set[str]] = {}
    record_by_type: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        record = _tree_record(row)
        key = taxonomy_key(record["category"], record["subcategory"], record["type"])
        grouped.setdefault(key, []).append(record)
        categories.add(record["category"])
        subcategories.setdefault(record["category"], set()).add(record["subcategory"])
        types.setdefault(
            f"{record['category']}::{record['subcategory']}", set()
        ).add(record["type"])

    for key, candidates in grouped.items():
        if len(candidates) > 1:
            winner = TYPE_COLLISION_WINNERS.get(key)
            winners = {
                candidate["product_type_code"] for candidate in candidates
            }
            if winner not in winners:
                raise ValueError(
                    "COPYWRITING_TAXONOMY_TREE_COLLISION_UNRESOLVED:"
                    f"{key}"
                )
            selected = next(
                candidate
                for candidate in candidates
                if candidate["product_type_code"] == winner
            )
        else:
            selected = candidates[0]
        record_by_type[key] = selected

    return {
        "categories": sorted(categories),
        "subcategoriesByCategory": {
            category: sorted(values)
            for category, values in sorted(subcategories.items())
        },
        "typesBySubcategory": {
            key: sorted(values) for key, values in sorted(types.items())
        },
        "recordByType": {
            key: record_by_type[key] for key in sorted(record_by_type)
        },
    }


async def validate_taxonomy_selection(
    *,
    category: str | None,
    subcategory: str | None,
    type_name: str | None,
    product_type_code: str | None = None,
) -> dict[str, Any]:
    """Validate a submitted cascade selection against the canonical tree."""

    normalized_category = canonical_category(category)
    normalized_subcategory = _text(subcategory)
    normalized_type = _text(type_name)
    normalized_code = _text(product_type_code)
    tree = await get_copywriting_taxonomy_tree()
    key = taxonomy_key(
        normalized_category, normalized_subcategory, normalized_type
    )
    selected = tree["recordByType"].get(key)
    if selected is None:
        all_records = list(tree["recordByType"].values())
        nearest = _nearest_tree_records(
            all_records,
            normalized_category,
            normalized_subcategory,
            normalized_type,
        )
        raise CopywritingTaxonomySelectionError(
            {
                "error_code": "COPYWRITING_TAXONOMY_SELECTION_INVALID",
                "selection": {
                    "category": category,
                    "subcategory": subcategory,
                    "type": type_name,
                    "product_type_code": product_type_code,
                },
                "nearest_match": nearest[0] if nearest else None,
                "candidates": nearest,
            }
        )
    if normalized_code and normalized_code != selected["product_type_code"]:
        raise CopywritingTaxonomySelectionError(
            {
                "error_code": "COPYWRITING_TAXONOMY_SELECTION_INVALID",
                "reason": "PRODUCT_TYPE_CODE_CONFLICTS_WITH_TAXONOMY",
                "selection": {
                    "category": category,
                    "subcategory": subcategory,
                    "type": type_name,
                    "product_type_code": product_type_code,
                },
                "nearest_match": selected,
                "candidates": [selected],
            }
        )
    return selected


def _source_changed(record: dict[str, Any], existing: dict[str, Any]) -> bool:
    for field in _SOURCE_FIELDS:
        current = existing.get(field)
        if field in {"source_row", "source_header_row"}:
            try:
                current = int(current)
            except (TypeError, ValueError):
                current = None
        else:
            current = _text(current)
        if current != record[field]:
            return True
    return False


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
    source_category, source_subcategory, source_type,
    canonicalization_rules_json, source_header_row, authority_version,
    source_sha256, registry_status, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'ACTIVE', ?, ?)
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
    source_category=excluded.source_category,
    source_subcategory=excluded.source_subcategory,
    source_type=excluded.source_type,
    canonicalization_rules_json=excluded.canonicalization_rules_json,
    source_header_row=excluded.source_header_row,
    authority_version=excluded.authority_version,
    source_sha256=excluded.source_sha256,
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
                            record["source_category"],
                            record["source_subcategory"],
                            record["source_type"],
                            record["canonicalization_rules_json"],
                            record["source_header_row"],
                            record["authority_version"],
                            record["source_sha256"],
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
    """Resolve an existing product without silently dropping legacy values."""

    product_id = _first_text(product, ("id", "product_id"))
    product_name = _first_text(product, ("product_display_name", "raw_product_title"))
    code = _first_text(product, _CODE_FIELDS)
    cluster = _first_text(product, ("copywriting_cluster", "cluster_name", "cluster"))
    raw_category = _text(product.get("category"))
    category = canonical_category(raw_category)
    subcategory = _text(product.get("subcategory"))
    type_name = _text(product.get("type"))
    angle = _text(product.get("copywriting_angle"))
    current = {
        "product_type_code": code or None,
        "cluster_name": cluster or None,
        "category": raw_category or None,
        "subcategory": subcategory or None,
        "type": type_name or None,
        "copywriting_angle": angle or None,
    }
    product_fields = {
        **current,
        "product_type_id": _text(product.get("product_type_id")) or None,
    }

    def result(
        status: str,
        matched_by: str | None,
        match: dict[str, Any] | None,
        candidates: list[dict[str, Any]],
        nearest_match: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "product_id": product_id,
            "product_display_name": product_name,
            "match_status": status,
            "matched_by": matched_by,
            "product_fields": product_fields,
            "needs_reconciliation": status
            in {"UNMATCHED", "AMBIGUOUS", "NEEDS_RECONCILIATION"},
            "current": current,
            "match": match,
            "nearest_match": nearest_match,
            "candidates": candidates,
        }

    tree = await get_copywriting_taxonomy_tree()
    tree_records = list(tree["recordByType"].values())
    if code:
        code_match = await get_copywriting_taxonomy_entry(code, active_only=True)
        if code_match is None:
            nearest = _nearest_tree_records(
                tree_records, category, subcategory, type_name
            )
            return result(
                "NEEDS_RECONCILIATION",
                "PRODUCT_TYPE_CODE",
                None,
                nearest,
                nearest[0] if nearest else None,
            )
        code_record = _tree_record(code_match)
        stored_key = taxonomy_key(category, subcategory, type_name)
        if (
            raw_category
            and subcategory
            and type_name
            and stored_key != taxonomy_key(
                code_record["category"],
                code_record["subcategory"],
                code_record["type"],
            )
        ):
            return result(
                "NEEDS_RECONCILIATION",
                "PRODUCT_TYPE_CODE",
                None,
                [code_record],
                code_record,
            )
        if cluster and code_record["cluster"] != cluster:
            return result(
                "NEEDS_RECONCILIATION",
                "PRODUCT_TYPE_CODE",
                None,
                [code_record],
                code_record,
            )
        if angle and angle != code_record["copywriting_angle"]:
            return result(
                "NEEDS_RECONCILIATION",
                "PRODUCT_TYPE_CODE",
                None,
                [code_record],
                code_record,
            )
        return result("EXACT_CODE", "PRODUCT_TYPE_CODE", code_match, [code_match])

    key = taxonomy_key(category, subcategory, type_name)
    match = tree["recordByType"].get(key)
    if match is not None:
        if angle and angle != match["copywriting_angle"]:
            return result(
                "NEEDS_RECONCILIATION",
                "CATEGORY_SUBCATEGORY_TYPE",
                None,
                [match],
                match,
            )
        return result(
            "EXACT_TAXONOMY",
            "CATEGORY_SUBCATEGORY_TYPE",
            match,
            [match],
        )

    nearest = _nearest_tree_records(
        tree_records, category, subcategory, type_name
    )
    return result(
        "NEEDS_RECONCILIATION",
        None,
        None,
        nearest,
        nearest[0] if nearest else None,
    )


async def resolve_product_taxonomy(product_id: str) -> dict[str, Any] | None:
    product = await crud.get_product(product_id)
    if product is None:
        return None
    return await resolve_product_taxonomy_record(product)
