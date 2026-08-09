#!/usr/bin/env python3
"""Governed BOSMAX catalog decontamination and visual-coverage audit.

This is deliberately a mission-scoped SQLite mechanism.  It is not a general
product merge service and it does not infer deletion authority from similarity.
The only destructive cohort accepted by ``--apply`` is the current, digest-locked
set of historical PI-13 ``MERGE_PROVEN`` aliases, after the same external listing
identity and variant guards have been re-proven against the live database.

The mechanism is synchronous so it can operate against a live SQLite database
without importing the application's async connection pool.  A consistent SQLite
backup is created before the first write.  Alias product rows are physically
removed only after their complete product/dependency pre-images have been stored
in the mission tombstone tables inside the same transaction.

Provider operations are intentionally absent from this module.  Visual coverage
is an evidence-only read of the existing Product Truth / reference authorities;
it never creates a cutout, reference pack, creative asset, or generation job.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MISSION_ID = "product-catalog-decontamination-20260809"
AUTHORIZATION_TOKEN = "PURGE_REPROVEN_48_MERGE_PROVEN"
EXPECTED_HISTORICAL_COHORT = 48
TOMBSTONE_TABLE = "product_catalog_alias_tombstone"
TOMBSTONE_CHILD_TABLE = "product_catalog_alias_tombstone_child"

FAIL_DUPLICATE_DRIFT = "DUPLICATE_COHORT_DRIFT"
FAIL_CANONICAL_MISSING = "CANONICAL_SURVIVOR_MISSING"
FAIL_IDENTITY_CONTRADICTION = "EXTERNAL_IDENTITY_CONTRADICTION"
FAIL_VARIANT_AMBIGUITY = "VARIANT_AMBIGUITY"
FAIL_BACKUP = "BACKUP_FAILED"
FAIL_BACKUP_INTEGRITY = "BACKUP_INTEGRITY_FAILED"
FAIL_PLAN_DIGEST = "PURGE_PLAN_DIGEST_MISMATCH"
FAIL_DEPENDENCY_POLICY = "PURGE_DEPENDENCY_POLICY_UNRESOLVED"
FAIL_FOREIGN_KEY = "FOREIGN_KEY_VIOLATION"
FAIL_POST_INTEGRITY = "POST_PURGE_INTEGRITY_FAILURE"
FAIL_CANONICAL_MUTATION = "CANONICAL_PRODUCT_MUTATED_UNEXPECTEDLY"

CLASSIFICATIONS = (
    "KEEP_CANONICAL",
    "ARCHIVED_ALREADY",
    "MERGE_PROVEN_EXACT_DUPLICATE",
    "DUPLICATE_EXACT_NEW_CANDIDATE",
    "DUPLICATE_NEAR_CANDIDATE",
    "SUPERSEDED_OUTDATED_CANDIDATE",
    "DELETE_TEST_JUNK_CANDIDATE",
    "BROKEN_INTAKE_CANDIDATE",
    "ORPHAN_RECORD_CANDIDATE",
    "REVIEW_REQUIRED",
)

VISUAL_STATES = (
    "APPROVED_CANONICAL_CUTOUT",
    "CANONICAL_REFERENCE_FALLBACK",
    "CUTOUT_PENDING_REVIEW",
    "BLOCKED_NO_TRUSTED_PRODUCT_MEDIA",
    "REVIEW_REQUIRED_VISUAL_IDENTITY",
)

PLATFORM_ID_RE = re.compile(r"/(?:product|detail)/(\d{6,})(?:[/?#]|$)", re.IGNORECASE)
SIZE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(ml|l|g|gram|gm|kg|mg|oz|tablet|tablets|pcs|helai|set|bottle|bottles|sachet|capsule|caps|pack|pair)\b",
    re.IGNORECASE,
)
VARIANT_RE = re.compile(
    r"\b(flavou?r|rasa|colour|color|warna|sku|variant|jenis|model)\s*[:#-]?\s*([a-z0-9][a-z0-9 +/&-]{1,40})",
    re.IGNORECASE,
)

TOMBSTONE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TOMBSTONE_TABLE} (
    alias_product_id       TEXT PRIMARY KEY,
    canonical_product_id   TEXT NOT NULL,
    platform_product_id    TEXT NOT NULL,
    product_row_json       TEXT NOT NULL,
    lifecycle_provenance   TEXT,
    dependency_summary_json TEXT NOT NULL DEFAULT '{{}}',
    plan_digest            TEXT NOT NULL,
    created_at             TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS {TOMBSTONE_CHILD_TABLE} (
    tombstone_child_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    alias_product_id       TEXT NOT NULL,
    table_name             TEXT NOT NULL,
    row_locator            TEXT NOT NULL,
    row_json               TEXT NOT NULL,
    handling               TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    UNIQUE(alias_product_id, table_name, row_locator)
);
CREATE INDEX IF NOT EXISTS idx_product_catalog_tombstone_canonical
    ON {TOMBSTONE_TABLE}(canonical_product_id);
CREATE INDEX IF NOT EXISTS idx_product_catalog_tombstone_child_alias
    ON {TOMBSTONE_CHILD_TABLE}(alias_product_id);
"""


class GateError(RuntimeError):
    """A named fail-closed mission gate."""

    def __init__(self, code: str, detail: str, *, payload: dict[str, Any] | None = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.payload = payload or {}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> str:
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=json_default)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=json_default) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError(f"unsafe SQLite identifier: {identifier}")
    return f'"{identifier}"'


def open_connection(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    db_path = db_path.resolve()
    if read_only:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=60)
    else:
        connection = sqlite3.connect(str(db_path), timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    connection.execute("PRAGMA foreign_keys=ON")
    if read_only:
        connection.execute("PRAGMA query_only=ON")
    return connection


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def table_info(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()]


def table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(item["name"]) for item in table_info(connection, table)]


def foreign_keys(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"PRAGMA foreign_key_list({quote_identifier(table)})").fetchall()]


def integrity_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
    integrity = [str(row[0]) for row in integrity_rows]
    foreign_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
    data_version = int(connection.execute("PRAGMA data_version").fetchone()[0])
    return {
        "integrity_check": integrity,
        "integrity_ok": integrity == ["ok"],
        "foreign_key_check": foreign_rows,
        "foreign_key_check_count": len(foreign_rows),
        "data_version": data_version,
    }


def product_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute("SELECT * FROM product ORDER BY id").fetchall()]


def product_row(connection: sqlite3.Connection, product_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM product WHERE id=?", (product_id,)).fetchone()
    return row_dict(row)


def marker_for(canonical_id: str) -> str:
    return f"DUPLICATE_MERGED_TO_CANONICAL:{canonical_id}"


def _is_test_product(row: dict[str, Any]) -> bool:
    """Use the shared Product Intelligence fixture authority when importable."""

    try:
        from agent.services.product_intelligence import is_test_product

        return bool(is_test_product(row))
    except Exception:
        product_id = str(row.get("id") or row.get("product_id") or "").lower()
        short_name = str(row.get("product_short_name") or "").strip().lower()
        raw_title = str(row.get("raw_product_title") or "").strip().lower()
        return (
            product_id.startswith(("test_", "fixture_"))
            or short_name in {"test product", "test item", "fixture product"}
            or raw_title in {"test product", "test item", "fixture product"}
            or short_name.startswith(("test product", "smoke ", "codex pi "))
            or raw_title.startswith(("test product", "smoke ", "codex pi "))
        )


def lifecycle_status(row: dict[str, Any]) -> str:
    return str(row.get("lifecycle_status") or "ACTIVE").upper()


def platform_ids(row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for field in ("tiktok_product_url", "source_url"):
        for match in PLATFORM_ID_RE.findall(str(row.get(field) or "")):
            values.add(str(match))
    return values


def normalized_url_identity(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return raw.casefold()


def normalized_size_tokens(row: dict[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    for field in ("raw_product_title", "product_display_name", "product_short_name"):
        for amount, unit in SIZE_RE.findall(str(row.get(field) or "")):
            number = str(float(amount)).rstrip("0").rstrip(".")
            values.add(f"{number}{unit.lower()}")
    for field in ("pack_size_ml", "size_ml", "volume_ml"):
        if row.get(field) not in (None, ""):
            values.add(f"{str(row[field]).strip()}ml")
    return tuple(sorted(values))


def normalized_variant_tokens(row: dict[str, Any]) -> tuple[str, ...]:
    values: set[str] = set()
    text = " ".join(str(row.get(field) or "") for field in ("raw_product_title", "product_display_name", "product_short_name"))
    for key, value in VARIANT_RE.findall(text):
        normalized_value = re.sub(r"\s+", " ", value.casefold()).strip(" -")
        values.add(f"{key.casefold()}={normalized_value}")
    return tuple(sorted(values))


def variant_compatible(duplicate: dict[str, Any], canonical: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    duplicate_sizes = normalized_size_tokens(duplicate)
    canonical_sizes = normalized_size_tokens(canonical)
    duplicate_variants = normalized_variant_tokens(duplicate)
    canonical_variants = normalized_variant_tokens(canonical)
    size_ok = not duplicate_sizes or not canonical_sizes or set(duplicate_sizes) == set(canonical_sizes)
    variant_ok = not duplicate_variants or not canonical_variants or set(duplicate_variants) == set(canonical_variants)
    return size_ok and variant_ok, {
        "duplicate_size_tokens": list(duplicate_sizes),
        "canonical_size_tokens": list(canonical_sizes),
        "duplicate_variant_tokens": list(duplicate_variants),
        "canonical_variant_tokens": list(canonical_variants),
        "size_compatible": size_ok,
        "variant_compatible": variant_ok,
    }


def seller_compatible(duplicate: dict[str, Any], canonical: dict[str, Any]) -> bool:
    left = str(duplicate.get("shop_name") or "").strip().casefold()
    right = str(canonical.get("shop_name") or "").strip().casefold()
    return left == right or not left or not right


def title_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_text = str(left.get("raw_product_title") or left.get("product_display_name") or "").casefold().strip()
    right_text = str(right.get("raw_product_title") or right.get("product_display_name") or "").casefold().strip()
    return difflib.SequenceMatcher(None, left_text, right_text).ratio()


def load_historical_pairs(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    pairs = payload.get("merge_proven") if isinstance(payload, dict) else None
    if not isinstance(pairs, list):
        raise GateError(FAIL_DUPLICATE_DRIFT, f"historical evidence has no merge_proven list: {path}")
    normalized: list[dict[str, Any]] = []
    for item in pairs:
        if not isinstance(item, dict):
            raise GateError(FAIL_DUPLICATE_DRIFT, "historical merge_proven entry is not an object")
        duplicate_id = str(item.get("product_id") or "").strip()
        canonical_id = str(item.get("canonical_id") or "").strip()
        if not duplicate_id or not canonical_id or duplicate_id == canonical_id:
            raise GateError(FAIL_DUPLICATE_DRIFT, f"invalid historical pair: {item}")
        signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
        normalized.append(
            {
                "duplicate_product_id": duplicate_id,
                "canonical_survivor_product_id": canonical_id,
                "historical_platform_product_id": str(signals.get("platform_product_id") or "") or None,
                "historical_signals": signals,
            }
        )
    normalized.sort(key=lambda item: (item["duplicate_product_id"], item["canonical_survivor_product_id"]))
    return normalized


def cohort_digest(entries: Iterable[dict[str, Any]]) -> str:
    compact = [
        {
            "duplicate_product_id": item["duplicate_product_id"],
            "canonical_survivor_product_id": item["canonical_survivor_product_id"],
            "platform_product_id": item.get("platform_product_id") or item.get("historical_platform_product_id"),
        }
        for item in entries
    ]
    compact.sort(key=lambda item: (item["duplicate_product_id"], item["canonical_survivor_product_id"]))
    return sha256_bytes(canonical_json(compact).encode("utf-8"))


def prove_historical_cohort(
    connection: sqlite3.Connection,
    historical_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    current_proven: list[dict[str, Any]] = []
    purged_tombstones: list[dict[str, Any]] = []

    tombstone_available = TOMBSTONE_TABLE in table_names(connection)
    for pair in historical_pairs:
        duplicate_id = pair["duplicate_product_id"]
        canonical_id = pair["canonical_survivor_product_id"]
        duplicate = product_row(connection, duplicate_id)
        canonical = product_row(connection, canonical_id)
        tombstone = None
        if tombstone_available:
            tombstone = row_dict(
                connection.execute(
                    f"SELECT * FROM {quote_identifier(TOMBSTONE_TABLE)} WHERE alias_product_id=?",
                    (duplicate_id,),
                ).fetchone()
            )

        if duplicate is None and tombstone is not None and canonical is not None:
            results.append(
                {
                    **pair,
                    "status": "PURGED_TOMBSTONE",
                    "canonical_survivor_present": True,
                    "tombstone_present": True,
                }
            )
            purged_tombstones.append({**pair, "platform_product_id": tombstone.get("platform_product_id")})
            continue

        entry: dict[str, Any] = {
            **pair,
            "status": "REPROVEN" if duplicate is not None and canonical is not None else "FAILED",
            "duplicate_present": duplicate is not None,
            "canonical_survivor_present": canonical is not None,
            "canonical_survivor_is_merged_alias": bool(
                canonical and str(canonical.get("archived_reason") or "").upper().startswith("DUPLICATE_MERGED_TO_CANONICAL")
            ),
        }
        entry_failures: list[str] = []
        if duplicate is None:
            entry_failures.append("DUPLICATE_PRODUCT_MISSING")
        if canonical is None:
            entry_failures.append(FAIL_CANONICAL_MISSING)
        if canonical is not None and entry["canonical_survivor_is_merged_alias"]:
            entry_failures.append(FAIL_CANONICAL_MISSING)
        if duplicate is not None and str(duplicate.get("archived_reason") or "") != marker_for(canonical_id):
            entry_failures.append("DUPLICATE_LINEAGE_MARKER_MISMATCH")
        if duplicate is not None and lifecycle_status(duplicate) != "ARCHIVED":
            entry_failures.append("DUPLICATE_NOT_ARCHIVED")
        if duplicate is not None and canonical is not None:
            duplicate_ids = platform_ids(duplicate)
            canonical_ids = platform_ids(canonical)
            expected_platform_id = pair.get("historical_platform_product_id")
            ids_match = len(duplicate_ids) == 1 and duplicate_ids == canonical_ids and (
                expected_platform_id is None or expected_platform_id in duplicate_ids
            )
            entry["duplicate_platform_ids"] = sorted(duplicate_ids)
            entry["canonical_platform_ids"] = sorted(canonical_ids)
            entry["platform_id_match"] = ids_match
            if len(duplicate_ids) > 1 or len(canonical_ids) > 1:
                entry_failures.append(FAIL_IDENTITY_CONTRADICTION)
            elif not ids_match:
                entry_failures.append("PLATFORM_ID_DISAGREEMENT")
            similarity = title_similarity(duplicate, canonical)
            entry["title_similarity"] = round(similarity, 6)
            if similarity < 0.85:
                entry_failures.append("TITLE_SIMILARITY_BELOW_0_85")
            variant_ok, variant_detail = variant_compatible(duplicate, canonical)
            entry["variant_comparison"] = variant_detail
            if not variant_ok:
                entry_failures.append(FAIL_VARIANT_AMBIGUITY)
            entry["seller_compatible"] = seller_compatible(duplicate, canonical)
            if not entry["seller_compatible"]:
                entry_failures.append("SELLER_CONTRADICTION")
            entry["url_comparison"] = {
                "duplicate_source_url": normalized_url_identity(duplicate.get("source_url")),
                "canonical_source_url": normalized_url_identity(canonical.get("source_url")),
                "duplicate_tiktok_product_url": normalized_url_identity(duplicate.get("tiktok_product_url")),
                "canonical_tiktok_product_url": normalized_url_identity(canonical.get("tiktok_product_url")),
            }
            entry["asset_hash_evidence"] = {
                "image_url_equal": bool(duplicate.get("image_url") and duplicate.get("image_url") == canonical.get("image_url")),
                "media_id_equal": bool(duplicate.get("media_id") and duplicate.get("media_id") == canonical.get("media_id")),
            }
            entry["lifecycle_evidence"] = {
                "duplicate_lifecycle_status": lifecycle_status(duplicate),
                "duplicate_archived_reason": duplicate.get("archived_reason"),
                "canonical_lifecycle_status": lifecycle_status(canonical),
                "canonical_archived_reason": canonical.get("archived_reason"),
            }
        if entry_failures:
            entry["failures"] = entry_failures
            failures.append({"duplicate_product_id": duplicate_id, "canonical_survivor_product_id": canonical_id, "failures": entry_failures})
        else:
            entry["failures"] = []
            current_proven.append({
                **pair,
                "platform_product_id": (sorted(platform_ids(duplicate))[0] if duplicate else pair.get("historical_platform_product_id")),
            })
        results.append(entry)

    active_entries = [
        {
            "duplicate_product_id": item["duplicate_product_id"],
            "canonical_survivor_product_id": item["canonical_survivor_product_id"],
            "platform_product_id": item.get("platform_product_id") or item.get("historical_platform_product_id"),
        }
        for item in current_proven
    ]
    purged_entries = [
        {
            "duplicate_product_id": item["duplicate_product_id"],
            "canonical_survivor_product_id": item["canonical_survivor_product_id"],
            "platform_product_id": item.get("platform_product_id") or item.get("historical_platform_product_id"),
        }
        for item in purged_tombstones
    ]
    return {
        "mission_id": MISSION_ID,
        "historical_cohort_count": len(historical_pairs),
        "current_reproven_count": len(current_proven),
        "purged_tombstone_count": len(purged_tombstones),
        "drifted_count": len(failures),
        "canonical_survivor_count": len({item["canonical_survivor_product_id"] for item in current_proven + purged_tombstones}),
        "cohort_digest": cohort_digest(active_entries or purged_entries),
        "failures": failures,
        "entries": results,
        "current_reproven_entries": active_entries,
        "purged_tombstone_entries": purged_entries,
    }


def _platform_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ids = platform_ids(row)
        if len(ids) == 1:
            groups[next(iter(ids))].append(row)
    return groups


def classify_products(
    rows: list[dict[str, Any]],
    historical_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    historical_by_alias = {item["duplicate_product_id"]: item for item in historical_pairs}
    rows_by_id = {str(row.get("id")): row for row in rows}
    groups = _platform_groups(rows)
    new_exact_pairs: list[dict[str, Any]] = []
    near_pairs: list[dict[str, Any]] = []

    for platform_id, members in groups.items():
        if len(members) < 2:
            continue
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                pair_key = {str(left.get("id")), str(right.get("id"))}
                if any(alias_id in pair_key for alias_id in historical_by_alias):
                    continue
                compatible, variant_detail = variant_compatible(left, right)
                similarity = title_similarity(left, right)
                if compatible and similarity >= 0.85 and seller_compatible(left, right):
                    new_exact_pairs.append(
                        {
                            "platform_product_id": platform_id,
                            "product_ids": sorted(pair_key),
                            "title_similarity": round(similarity, 6),
                            "variant_comparison": variant_detail,
                        }
                    )

    # A bounded title-near scan provides a review cohort without ever becoming a
    # delete authority.  901 rows is intentionally small enough for a complete
    # pairwise check, and the output retains both IDs and the comparison.
    for index, left in enumerate(rows):
        left_id = str(left.get("id") or "")
        if not left_id:
            continue
        for right in rows[index + 1 :]:
            right_id = str(right.get("id") or "")
            if not right_id or platform_ids(left) & platform_ids(right):
                continue
            similarity = title_similarity(left, right)
            if similarity >= 0.92:
                near_pairs.append(
                    {
                        "product_ids": sorted((left_id, right_id)),
                        "title_similarity": round(similarity, 6),
                        "variant_comparison": variant_compatible(left, right)[1],
                    }
                )

    exact_member_ids = {pid for pair in new_exact_pairs for pid in pair["product_ids"]}
    near_member_ids = {pid for pair in near_pairs for pid in pair["product_ids"]}
    classifications: list[dict[str, Any]] = []
    for row in rows:
        product_id = str(row.get("id") or "")
        lifecycle = lifecycle_status(row)
        reason = ""
        primary = "KEEP_CANONICAL"
        historical = historical_by_alias.get(product_id)
        if historical is not None and str(row.get("archived_reason") or "") == marker_for(historical["canonical_survivor_product_id"]):
            primary = "MERGE_PROVEN_EXACT_DUPLICATE"
            reason = "historical MERGE_PROVEN pair with current lineage marker"
        elif _is_test_product(row):
            primary = "DELETE_TEST_JUNK_CANDIDATE"
            reason = "shared Product Intelligence test-fixture predicate"
        elif len(platform_ids(row)) > 1:
            primary = "REVIEW_REQUIRED"
            reason = FAIL_IDENTITY_CONTRADICTION
        elif not str(row.get("product_display_name") or row.get("raw_product_title") or "").strip():
            primary = "BROKEN_INTAKE_CANDIDATE"
            reason = "missing product name"
        elif product_id in exact_member_ids:
            primary = "DUPLICATE_EXACT_NEW_CANDIDATE"
            reason = "same external platform ID, compatible variant, title similarity >= 0.85; not historically authorized"
        elif product_id in near_member_ids:
            primary = "DUPLICATE_NEAR_CANDIDATE"
            reason = "high title similarity without authoritative shared platform ID; review only"
        elif lifecycle == "ARCHIVED" and "REPLAC" in str(row.get("archived_reason") or "").upper():
            primary = "SUPERSEDED_OUTDATED_CANDIDATE"
            reason = "archived lifecycle provenance indicates replacement"
        elif lifecycle == "ARCHIVED":
            primary = "ARCHIVED_ALREADY"
            reason = "archived lifecycle row retained for history"
        elif not (
            platform_ids(row)
            or row.get("source_url")
            or row.get("tiktok_product_url")
            or row.get("image_url")
            or row.get("local_image_path")
            or row.get("media_id")
        ):
            primary = "ORPHAN_RECORD_CANDIDATE"
            reason = "active row has no external identity or trusted media pointer"
        if primary not in CLASSIFICATIONS:
            raise RuntimeError(f"unknown product classification: {primary}")
        classifications.append(
            {
                "product_id": product_id,
                "primary_classification": primary,
                "lifecycle_status": lifecycle,
                "source": row.get("source"),
                "product_display_name": row.get("product_display_name"),
                "platform_product_ids": sorted(platform_ids(row)),
                "reason": reason,
                "new_exact_group_ids": sorted(pid for pid in exact_member_ids if pid == product_id),
            }
        )

    counts = Counter(item["primary_classification"] for item in classifications)
    return {
        "mission_id": MISSION_ID,
        "row_count": len(rows),
        "classification_counts": {key: int(counts.get(key, 0)) for key in CLASSIFICATIONS},
        "new_exact_duplicate_candidates": new_exact_pairs,
        "near_duplicate_review": near_pairs,
        "rows": classifications,
    }


def population_counts(rows: list[dict[str, Any]], classifications: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = len(rows)
    active = sum(lifecycle_status(row) == "ACTIVE" for row in rows)
    archived = sum(lifecycle_status(row) == "ARCHIVED" for row in rows)
    merged = sum(str(row.get("archived_reason") or "").upper().startswith("DUPLICATE_MERGED_TO_CANONICAL") for row in rows)
    fixtures = sum(_is_test_product(row) for row in rows)
    real = raw - merged - fixtures
    real_active = sum(
        lifecycle_status(row) == "ACTIVE"
        and not _is_test_product(row)
        and not str(row.get("archived_reason") or "").upper().startswith("DUPLICATE_MERGED_TO_CANONICAL")
        for row in rows
    )
    production_eligible = sum(
        lifecycle_status(row) == "ACTIVE"
        and not _is_test_product(row)
        and not str(row.get("archived_reason") or "").upper().startswith("DUPLICATE_MERGED_TO_CANONICAL")
        and bool(str(row.get("id") or "").strip())
        and bool(str(row.get("product_display_name") or row.get("raw_product_title") or "").strip())
        and len(platform_ids(row)) <= 1
        for row in rows
    )
    source_counts = Counter(str(row.get("source") or "MISSING_SOURCE") for row in rows)
    source_counts.setdefault("MISSING_SOURCE", 0)
    return {
        "raw_product_rows": raw,
        "active_rows": active,
        "archived_rows": archived,
        "merged_historical_aliases": merged,
        "test_fixture_rows": fixtures,
        "real_canonical_products": real,
        "real_active_canonical_products": real_active,
        "real_archived_canonical_products": real - real_active,
        "production_eligible_products": production_eligible,
        "source_counts": dict(sorted(source_counts.items())),
        "missing_name_rows": sum(not str(row.get("product_display_name") or row.get("raw_product_title") or "").strip() for row in rows),
        "missing_url_rows": sum(not (row.get("source_url") or row.get("tiktok_product_url")) for row in rows),
        "arithmetic": {
            "raw_equals_active_plus_archived": raw == active + archived,
            "raw_equals_real_plus_aliases_plus_fixtures": raw == real + merged + fixtures,
            "real_equals_real_active_plus_real_archived": real == real_active + (real - real_active),
        },
        "count_semantics": {
            "raw_product_rows": "SELECT COUNT(*) FROM product; includes archived rows, test fixtures, and historical aliases.",
            "active_rows": "lifecycle_status = ACTIVE; not a canonical or production KPI by itself.",
            "archived_rows": "lifecycle_status = ARCHIVED; includes legitimate history and merged aliases.",
            "merged_historical_aliases": "archived_reason begins DUPLICATE_MERGED_TO_CANONICAL; not an independent product.",
            "real_canonical_products": "product rows excluding shared test-fixture authority and merged-alias lineage.",
            "production_eligible_products": "active real canonical rows with a non-empty identity and no external-ID contradiction; visual media readiness is measured separately.",
        },
        "classification_counts": (classifications or {}).get("classification_counts", {}),
    }


def baseline_document(
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    snapshot_sha256: str,
    historical_pairs: list[dict[str, Any]],
    reproof: dict[str, Any],
    classifications: dict[str, Any],
) -> dict[str, Any]:
    rows = product_rows(connection)
    snapshot = integrity_snapshot(connection)
    counts = population_counts(rows, classifications)
    return {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "database": {
            "absolute_path": str(db_path.resolve()),
            "consistent_snapshot_sha256": snapshot_sha256,
            "sha256_method": "SQLITE_ONLINE_BACKUP",
            "data_version": snapshot["data_version"],
            "integrity_check": snapshot["integrity_check"],
            "foreign_key_check": snapshot["foreign_key_check"],
        },
        "counts": counts,
        "historical_merge_proven_count": len(historical_pairs),
        "current_reproof": {
            "current_reproven_count": reproof["current_reproven_count"],
            "purged_tombstone_count": reproof["purged_tombstone_count"],
            "drifted_count": reproof["drifted_count"],
        },
        "merged_alias_ids": sorted(
            row["product_id"] for row in classifications["rows"] if row["primary_classification"] == "MERGE_PROVEN_EXACT_DUPLICATE"
        ),
        "test_fixture_ids": sorted(
            row["product_id"] for row in classifications["rows"] if row["primary_classification"] == "DELETE_TEST_JUNK_CANDIDATE"
        ),
        "missing_canonical_ids": sorted(
            {
                item["canonical_survivor_product_id"]
                for item in reproof["entries"]
                if not item.get("canonical_survivor_present", False)
            }
        ),
    }


def row_locator(connection: sqlite3.Connection, table: str, row: dict[str, Any]) -> str:
    info = table_info(connection, table)
    primary_keys = [str(item["name"]) for item in sorted(info, key=lambda item: int(item["pk"])) if int(item["pk"] or 0) > 0]
    if primary_keys:
        return canonical_json({key: row.get(key) for key in primary_keys})
    return canonical_json({"row": row})


def dependency_policy(table: str, column: str, on_delete: str | None) -> str:
    table_lower = table.casefold()
    column_lower = column.casefold()
    if table_lower == "fastmoss_bulk_draft_status" and column_lower == "committed_product_id":
        return "REPOINT_TO_CANONICAL"
    if table_lower == "request_telemetry":
        return "PRESERVE_WITH_TOMBSTONE"
    if table_lower.startswith("product_intelligence_"):
        return "PRESERVE_WITH_TOMBSTONE"
    if table_lower in {"product_visual_truth_lock", "product_reference_pack", "product_source_media", "product_treatment_factory_plan"}:
        return "PRESERVE_WITH_TOMBSTONE"
    if table_lower in {
        "copy_set",
        "copy_component",
        "copy_generation_batch",
        "poster_copy_set",
        "poster_deliverable",
        "workspace_execution_package",
        "workspace_generation_package",
        "batch",
        "batch_variant",
        "product_strategy_taxonomy",
        "product_treatment_factory_task",
        "content_combination",
        "creative_product_selection",
    }:
        return "DELETE_STALE_ALIAS_CHILD"
    if table_lower in {"creative_asset", "image_generation_operation"}:
        return "PRESERVE_WITH_TOMBSTONE"
    return "PURGE_BLOCKED_HISTORY"


def scan_dependencies(connection: sqlite3.Connection, alias_ids: set[str]) -> dict[str, Any]:
    if not alias_ids:
        return {"tables": [], "per_alias": {}, "unresolved_policy": [], "foreign_key_edges": []}
    aliases = sorted(alias_ids)
    table_docs: dict[tuple[str, str, str], dict[str, Any]] = {}
    per_alias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    foreign_key_edges: list[dict[str, Any]] = []
    ignored = {"product", TOMBSTONE_TABLE, TOMBSTONE_CHILD_TABLE}

    for table in table_names(connection):
        if table in ignored:
            continue
        columns = table_columns(connection, table)
        if not columns:
            continue
        fk_rows = foreign_keys(connection, table)
        fk_by_column: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fk in fk_rows:
            if str(fk.get("table") or "") == "product":
                fk_by_column[str(fk.get("from") or "")].append(fk)
                foreign_key_edges.append({"table": table, **fk})
        direct_columns = [
            column
            for column in columns
            if column.casefold() in {
                "product_id",
                "productid",
                "target_product_id",
                "committed_product_id",
                "linked_product_id",
                "reviewed_via_product_id",
            }
        ]
        logical_columns = [
            column
            for column in columns
            if column not in direct_columns
            and any(token in column.casefold() for token in ("product", "lineage", "evidence", "asset", "payload", "reference", "json"))
        ]
        if not direct_columns and not logical_columns:
            continue
        try:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {quote_identifier(table)}").fetchall()]
        except sqlite3.DatabaseError:
            continue
        for row in rows:
            row_string = {column: str(row.get(column) or "") for column in logical_columns}
            row_aliases: dict[str, set[str]] = defaultdict(set)
            for column in direct_columns:
                value = str(row.get(column) or "")
                if value in alias_ids:
                    row_aliases[value].add(column)
            for column, value in row_string.items():
                for alias_id in aliases:
                    if alias_id in value:
                        row_aliases[alias_id].add(column)
            if not row_aliases:
                continue
            locator = row_locator(connection, table, row)
            for alias_id, matched_columns in row_aliases.items():
                for column in sorted(matched_columns):
                    fk = fk_by_column.get(column, [])
                    on_delete = str(fk[0].get("on_delete") or "NO ACTION").upper() if fk else None
                    policy = dependency_policy(table, column, on_delete)
                    table_key = (table, column, policy)
                    document = table_docs.setdefault(
                        table_key,
                        {
                            "table": table,
                            "column": column,
                            "policy": policy,
                            "on_delete": on_delete,
                            "foreign_key": bool(fk),
                            "row_count": 0,
                            "alias_ids": set(),
                            "row_locators": [],
                        },
                    )
                    document["row_count"] += 1
                    document["alias_ids"].add(alias_id)
                    if locator not in document["row_locators"]:
                        document["row_locators"].append(locator)
                    per_alias[alias_id].append(
                        {
                            "table": table,
                            "column": column,
                            "policy": policy,
                            "on_delete": on_delete,
                            "foreign_key": bool(fk),
                            "row_locator": locator,
                            "row": row,
                        }
                    )

    unresolved = [
        {
            "table": doc["table"],
            "column": doc["column"],
            "row_count": doc["row_count"],
            "alias_ids": sorted(doc["alias_ids"]),
            "reason": "no explicit mission policy",
        }
        for doc in table_docs.values()
        if doc["policy"] == "PURGE_BLOCKED_HISTORY"
    ]
    tables = []
    for doc in sorted(table_docs.values(), key=lambda item: (item["table"], item["column"])):
        tables.append(
            {
                **{key: value for key, value in doc.items() if key not in {"alias_ids"}},
                "alias_ids": sorted(doc["alias_ids"]),
            }
        )
    return {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "alias_count": len(alias_ids),
        "tables": tables,
        "per_alias": {
            alias_id: [
                item
                for item in sorted(entries, key=lambda item: (item["table"], item["column"], item["row_locator"]))
            ]
            for alias_id, entries in sorted(per_alias.items())
        },
        "rows_by_alias": {alias_id: len(entries) for alias_id, entries in sorted(per_alias.items())},
        "unresolved_policy": unresolved,
        "foreign_key_edges": foreign_key_edges,
        "policy_counts": dict(Counter(item["policy"] for item in tables)),
    }


def compact_dependency_manifest(dependency: dict[str, Any]) -> dict[str, Any]:
    """Drop row payloads from the committed blast-radius manifest.

    Full child pre-images are read again immediately before apply and written to
    the SQLite tombstone inside the guarded transaction. Keeping them only in
    the durable tombstone prevents the evidence JSON from duplicating potentially
    large request/authority payloads while retaining every table, column, policy,
    alias, and row locator needed for audit.
    """

    return {
        "mission_id": dependency.get("mission_id", MISSION_ID),
        "alias_count": dependency.get("alias_count", 0),
        "tables": dependency.get("tables", []),
        "per_alias": {
            alias_id: [
                {key: value for key, value in item.items() if key != "row"}
                for item in entries
            ]
            for alias_id, entries in sorted((dependency.get("per_alias") or {}).items())
        },
        "rows_by_alias": dependency.get("rows_by_alias", {}),
        "unresolved_policy": dependency.get("unresolved_policy", []),
        "foreign_key_edges": dependency.get("foreign_key_edges", []),
        "policy_counts": dependency.get("policy_counts", {}),
    }


def _dependency_rows_for_alias(dependency: dict[str, Any], alias_id: str) -> list[dict[str, Any]]:
    return list(dependency.get("per_alias", {}).get(alias_id, []))


def build_purge_plan(
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    historical_pairs: list[dict[str, Any]],
    reproof: dict[str, Any],
    dependency: dict[str, Any],
    snapshot_sha256: str,
) -> dict[str, Any]:
    if len(historical_pairs) != EXPECTED_HISTORICAL_COHORT:
        raise GateError(FAIL_DUPLICATE_DRIFT, f"historical cohort contains {len(historical_pairs)} pairs, expected {EXPECTED_HISTORICAL_COHORT}")
    if reproof["current_reproven_count"] != EXPECTED_HISTORICAL_COHORT:
        raise GateError(FAIL_DUPLICATE_DRIFT, f"current reproof contains {reproof['current_reproven_count']} pairs, expected {EXPECTED_HISTORICAL_COHORT}", payload=reproof)
    if reproof["failures"]:
        raise GateError(FAIL_DUPLICATE_DRIFT, "current reproof contains failed entries", payload={"failures": reproof["failures"]})
    if reproof["canonical_survivor_count"] != EXPECTED_HISTORICAL_COHORT:
        raise GateError(FAIL_CANONICAL_MISSING, f"canonical survivor count is {reproof['canonical_survivor_count']}")
    if dependency.get("unresolved_policy"):
        raise GateError(FAIL_DEPENDENCY_POLICY, "dependency policy is unresolved", payload={"unresolved": dependency["unresolved_policy"]})

    aliases = sorted(item["duplicate_product_id"] for item in reproof["current_reproven_entries"])
    survivors = sorted({item["canonical_survivor_product_id"] for item in reproof["current_reproven_entries"]})
    products = {str(row["id"]): row for row in product_rows(connection)}
    if set(aliases) & set(survivors):
        raise GateError(FAIL_CANONICAL_MISSING, "duplicate and canonical cohorts overlap")
    if any(alias not in products for alias in aliases):
        raise GateError(FAIL_DUPLICATE_DRIFT, "one or more current duplicate rows disappeared while planning")
    if any(survivor not in products for survivor in survivors):
        raise GateError(FAIL_CANONICAL_MISSING, "one or more canonical survivors disappeared while planning")

    pre_counts = population_counts(list(products.values()))
    plan_core = {
        "mission_id": MISSION_ID,
        "authorization_token": AUTHORIZATION_TOKEN,
        "database_path": str(db_path.resolve()),
        "source_snapshot_sha256": snapshot_sha256,
        "source_data_version": integrity_snapshot(connection)["data_version"],
        "cohort_digest": reproof["cohort_digest"],
        "aliases": aliases,
        "canonical_survivors": survivors,
        "dependency_policy": compact_dependency_manifest(dependency),
        "before_counts": pre_counts,
        "guards": [
            "historical evidence list contains exactly 48 pairs",
            "current reproof count equals 48",
            "same authoritative platform product ID on both rows",
            "title similarity >= 0.85 plus compatible size/variant tokens",
            "duplicate lifecycle is ARCHIVED with exact canonical lineage marker",
            "canonical survivor exists and is not a merged alias",
            "all dependency tables have explicit policy",
            "all product and dependency pre-images are tombstoned before delete",
            "one BEGIN IMMEDIATE transaction with rollback on invariant failure",
        ],
    }
    plan_digest = sha256_bytes(canonical_json(plan_core).encode("utf-8"))
    return {**plan_core, "plan_digest": plan_digest, "created_at": utc_now()}


def consistent_backup(db_path: Path, backup_path: Path) -> dict[str, Any]:
    backup_path = backup_path.resolve()
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        backup_path.unlink()
    source = None
    destination = None
    try:
        source = open_connection(db_path, read_only=True)
        destination = sqlite3.connect(str(backup_path), timeout=60)
        source.backup(destination, pages=1000, sleep=0.05)
        destination.commit()
        destination.close()
        destination = None
        with open_connection(backup_path, read_only=True) as check:
            checks = integrity_snapshot(check)
            product_count = int(check.execute("SELECT COUNT(*) FROM product").fetchone()[0])
            counts = population_counts(product_rows(check))
        if not checks["integrity_ok"] or checks["foreign_key_check_count"] != 0:
            raise GateError(FAIL_BACKUP_INTEGRITY, "consistent backup integrity or foreign-key check failed", payload=checks)
        return {
            "path": str(backup_path),
            "size_bytes": int(backup_path.stat().st_size),
            "sha256": sha256_file(backup_path),
            "integrity_check": checks["integrity_check"],
            "foreign_key_check": checks["foreign_key_check"],
            "data_version": checks["data_version"],
            "product_count": product_count,
            "counts": counts,
            "readable": True,
        }
    except GateError:
        raise
    except Exception as exc:
        raise GateError(FAIL_BACKUP, f"could not create or verify SQLite backup: {exc}") from exc
    finally:
        if source is not None:
            source.close()
        if destination is not None:
            destination.close()


def _safe_path(raw: Any, media_root: Path) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = media_root / path
    try:
        return path.resolve()
    except OSError:
        return None


def _image_meta(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            return {
                "path": str(path),
                "sha256": sha256_file(path),
                "width": int(image.width),
                "height": int(image.height),
                "format": str(image.format or "").upper(),
                "has_alpha": image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info,
                "alpha_bbox": list(alpha.getbbox()) if alpha.getbbox() else None,
            }
    except Exception:
        return None


def _trusted_product_reference(
    connection: sqlite3.Connection,
    product: dict[str, Any],
    *,
    media_root: Path,
) -> dict[str, Any] | None:
    product_id = str(product.get("id"))
    truth = row_dict(connection.execute("SELECT * FROM product_visual_truth_lock WHERE product_id=?", (product_id,)).fetchone()) if "product_visual_truth_lock" in table_names(connection) else None
    if truth:
        source_path = _safe_path(truth.get("canonical_source_path"), media_root)
        source_meta = _image_meta(source_path)
        if source_meta and str(truth.get("canonical_sha256") or "").lower() == source_meta["sha256"]:
            return {"source_type": "PRODUCT_TRUTH_LOCK_SOURCE", "media_id": truth.get("canonical_media_id"), "meta": source_meta}

    if "product_reference_pack" in table_names(connection):
        pack = row_dict(connection.execute("SELECT * FROM product_reference_pack WHERE product_id=?", (product_id,)).fetchone())
        if pack and str(pack.get("pack_status") or "").upper() == "APPROVED":
            try:
                references = json.loads(pack.get("references_json") or "[]")
            except (TypeError, ValueError):
                references = []
            for item in references if isinstance(references, list) else []:
                if not isinstance(item, dict) or item.get("role") != "PRODUCT_CANONICAL" or not item.get("approved"):
                    continue
                evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
                if evidence.get("requires_human_review"):
                    continue
                path = _safe_path(item.get("local_file_path") or item.get("local_path"), media_root)
                meta = _image_meta(path)
                if meta and (not item.get("sha256") or str(item.get("sha256")).lower() == meta["sha256"]):
                    return {"source_type": "PRODUCT_REFERENCE_PACK_CANONICAL", "media_id": item.get("media_id") or item.get("asset_id"), "meta": meta}

    if "creative_asset" in table_names(connection):
        assets = connection.execute(
            "SELECT * FROM creative_asset WHERE product_id=? AND semantic_role='PRODUCT_REFERENCE' AND status='ACTIVE' AND review_status='APPROVED' ORDER BY updated_at DESC",
            (product_id,),
        ).fetchall()
        for asset_row in assets:
            asset = dict(asset_row)
            meta = _image_meta(_safe_path(asset.get("local_file_path") or asset.get("local_path"), media_root))
            if meta:
                return {"source_type": "CREATIVE_ASSET_PRODUCT_REFERENCE", "media_id": asset.get("media_id") or asset.get("asset_id"), "meta": meta}

    local_meta = _image_meta(_safe_path(product.get("local_image_path"), media_root))
    if local_meta:
        return {"source_type": "PRODUCT_ROW_LOCAL_PATH", "media_id": product.get("media_id"), "meta": local_meta}

    if "product_source_media" in table_names(connection):
        media_rows = connection.execute(
            "SELECT * FROM product_source_media WHERE product_id=? AND kind='image' ORDER BY updated_at DESC, created_at DESC",
            (product_id,),
        ).fetchall()
        for media_row in media_rows:
            media = dict(media_row)
            if str(media.get("status") or "").upper() not in {"STORED", "APPROVED"}:
                continue
            meta = _image_meta(_safe_path(media.get("local_path"), media_root))
            if meta:
                return {"source_type": "PRODUCT_SOURCE_MEDIA", "media_id": media.get("media_id"), "meta": meta}

    media_id = str(product.get("media_id") or "").strip()
    if media_id and "request" in table_names(connection):
        request = row_dict(connection.execute("SELECT * FROM request WHERE media_id=? OR request_id=? LIMIT 1", (media_id, media_id)).fetchone())
        if request:
            meta = _image_meta(_safe_path(request.get("output_url") or request.get("local_path"), media_root))
            if meta:
                return {"source_type": "PRODUCT_ROW_MEDIA_ID", "media_id": media_id, "meta": meta}
        for extension in (".jpg", ".jpeg", ".png", ".webp"):
            meta = _image_meta(media_root / "output" / "retrieved" / f"{media_id}{extension}")
            if meta:
                return {"source_type": "PRODUCT_ROW_MEDIA_ID", "media_id": media_id, "meta": meta}

    image_url = str(product.get("image_url") or "").strip()
    if image_url.startswith("http"):
        return {"source_type": "PRODUCT_ROW_IMAGE_URL", "media_id": product.get("media_id"), "image_url": image_url}
    return None


def build_visual_coverage(
    connection: sqlite3.Connection,
    cohort_rows: list[dict[str, Any]],
    *,
    media_root: Path,
    purged_ids: set[str],
    classification_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    classification_by_id = classification_by_id or {}
    rows: list[dict[str, Any]] = []
    for product in sorted(cohort_rows, key=lambda item: str(item.get("id") or "")):
        product_id = str(product.get("id") or "")
        if product_id in purged_ids:
            raise GateError("PURGED_ALIAS_VISUAL_TARGET", f"visual cohort includes purged alias {product_id}")
        if classification_by_id.get(product_id, {}).get("primary_classification") == "REVIEW_REQUIRED":
            state = "REVIEW_REQUIRED_VISUAL_IDENTITY"
            reason = "catalog identity classification requires review"
            authority = None
        else:
            authority = None
            truth = row_dict(connection.execute("SELECT * FROM product_visual_truth_lock WHERE product_id=?", (product_id,)).fetchone()) if "product_visual_truth_lock" in table_names(connection) else None
            if truth and str(truth.get("review_status") or "").upper() == "APPROVED":
                cutout_meta = _image_meta(_safe_path(truth.get("canonical_cutout_path"), media_root))
                if cutout_meta and str(truth.get("canonical_cutout_sha256") or "").lower() == cutout_meta["sha256"] and cutout_meta.get("has_alpha") and cutout_meta.get("alpha_bbox"):
                    state = "APPROVED_CANONICAL_CUTOUT"
                    reason = "approved Product Truth Lock cutout is present and byte-valid"
                    authority = {"source_type": "PRODUCT_TRUTH_LOCK_CUTOUT", "media_id": truth.get("canonical_cutout_media_id"), "meta": cutout_meta}
                else:
                    authority = _trusted_product_reference(connection, product, media_root=media_root)
                    state = "CANONICAL_REFERENCE_FALLBACK" if authority else "BLOCKED_NO_TRUSTED_PRODUCT_MEDIA"
                    reason = "approved cutout failed byte validation; canonical reference fallback used" if authority else "approved cutout exists but no valid canonical reference fallback"
            else:
                authority = _trusted_product_reference(connection, product, media_root=media_root)
                if authority:
                    state = "CANONICAL_REFERENCE_FALLBACK"
                    reason = "same canonical product trusted source precedes any unapproved cutout candidate"
                else:
                    pending_candidate = False
                    if "product_reference_pack" in table_names(connection):
                        pack = row_dict(connection.execute("SELECT * FROM product_reference_pack WHERE product_id=?", (product_id,)).fetchone())
                        if pack:
                            try:
                                references = json.loads(pack.get("references_json") or "[]")
                            except (TypeError, ValueError):
                                references = []
                            pending_candidate = any(
                                isinstance(item, dict)
                                and item.get("role") == "PRODUCT_CUTOUT"
                                and not item.get("approved")
                                for item in references if isinstance(references, list)
                            )
                    state = "CUTOUT_PENDING_REVIEW" if pending_candidate else "BLOCKED_NO_TRUSTED_PRODUCT_MEDIA"
                    reason = "deterministic cutout candidate exists but requires human review" if pending_candidate else "no trusted canonical product media is readable"
        rows.append(
            {
                "product_id": product_id,
                "product_display_name": product.get("product_display_name") or product.get("raw_product_title"),
                "visual_state": state,
                "reason": reason,
                "authority": authority,
                "same_product_fallback": bool(state == "CANONICAL_REFERENCE_FALLBACK" and authority),
                "provider_operations": 0,
            }
        )

    state_counts = Counter(row["visual_state"] for row in rows)
    if set(state_counts) - set(VISUAL_STATES):
        raise RuntimeError(f"unknown visual state: {set(state_counts) - set(VISUAL_STATES)}")
    total = len(rows)
    if sum(state_counts.values()) != total:
        raise RuntimeError("visual coverage arithmetic does not reconcile")

    visual_refs_to_purged: list[dict[str, Any]] = []
    for table in ("product_visual_truth_lock", "product_reference_pack", "creative_asset", "image_generation_operation"):
        if table not in table_names(connection):
            continue
        columns = table_columns(connection, table)
        for column in ("product_id", "target_product_id"):
            if column not in columns:
                continue
            placeholders = ",".join("?" for _ in purged_ids)
            if not placeholders:
                continue
            for row in connection.execute(
                f"SELECT {quote_identifier(column)} FROM {quote_identifier(table)} WHERE {quote_identifier(column)} IN ({placeholders})",
                sorted(purged_ids),
            ).fetchall():
                visual_refs_to_purged.append({"table": table, "column": column, "product_id": row[0]})
    return {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "cohort_count": total,
        "state_counts": {state: int(state_counts.get(state, 0)) for state in VISUAL_STATES},
        "visual_grounding_available": int(state_counts.get("APPROVED_CANONICAL_CUTOUT", 0) + state_counts.get("CANONICAL_REFERENCE_FALLBACK", 0)),
        "exact_commerce_cutout_ready": int(state_counts.get("APPROVED_CANONICAL_CUTOUT", 0)),
        "coverage_arithmetic": {
            "sum_states": int(sum(state_counts.values())),
            "equals_cohort_count": sum(state_counts.values()) == total,
        },
        "provider_operations": 0,
        "purged_ids_receiving_visual_work": visual_refs_to_purged,
        "rows": rows,
    }


def canonical_survivor_snapshot(connection: sqlite3.Connection, survivor_ids: list[str]) -> dict[str, dict[str, Any]]:
    return {product_id: product_row(connection, product_id) or {} for product_id in survivor_ids}


def assert_active_external_id_uniqueness(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in product_rows(connection):
        if lifecycle_status(row) != "ACTIVE":
            continue
        for platform_id in platform_ids(row):
            groups[platform_id].append(str(row.get("id")))
    return [
        {"platform_product_id": platform_id, "product_ids": sorted(product_ids)}
        for platform_id, product_ids in sorted(groups.items())
        if len(set(product_ids)) > 1
    ]


def delete_stale_no_fk_children(connection: sqlite3.Connection, dependency: dict[str, Any], aliases: list[str]) -> int:
    deleted = 0
    for table_doc in dependency.get("tables", []):
        if table_doc.get("policy") != "DELETE_STALE_ALIAS_CHILD":
            continue
        table = str(table_doc["table"])
        column = str(table_doc["column"])
        if table_doc.get("foreign_key"):
            continue
        if column.casefold() not in {"product_id", "productid", "target_product_id", "linked_product_id"}:
            continue
        placeholders = ",".join("?" for _ in aliases)
        cursor = connection.execute(
            f"DELETE FROM {quote_identifier(table)} WHERE {quote_identifier(column)} IN ({placeholders})",
            aliases,
        )
        deleted += int(cursor.rowcount if cursor.rowcount >= 0 else 0)
    return deleted


def repoint_and_null_lineage(connection: sqlite3.Connection, aliases: list[str], survivor_by_alias: dict[str, str]) -> tuple[int, int]:
    repointed = 0
    detached_lineage = 0
    if "fastmoss_bulk_draft_status" in table_names(connection):
        for alias_id, canonical_id in survivor_by_alias.items():
            cursor = connection.execute(
                "UPDATE fastmoss_bulk_draft_status SET committed_product_id=? WHERE committed_product_id=?",
                (canonical_id, alias_id),
            )
            repointed += int(cursor.rowcount if cursor.rowcount >= 0 else 0)
    if "request_telemetry" in table_names(connection):
        placeholders = ",".join("?" for _ in aliases)
        cursor = connection.execute(
            f"UPDATE request_telemetry SET product_id=NULL WHERE product_id IN ({placeholders})",
            aliases,
        )
        detached_lineage += int(cursor.rowcount if cursor.rowcount >= 0 else 0)
    return repointed, detached_lineage


def insert_tombstones(
    connection: sqlite3.Connection,
    *,
    plan: dict[str, Any],
    dependency: dict[str, Any],
    product_by_id: dict[str, dict[str, Any]],
    survivor_by_alias: dict[str, str],
) -> int:
    now = utc_now()
    child_count = 0
    for alias_id in sorted(survivor_by_alias):
        row = product_by_id[alias_id]
        platform_id = sorted(platform_ids(row))[0]
        alias_dependencies = _dependency_rows_for_alias(dependency, alias_id)
        connection.execute(
            f"INSERT INTO {quote_identifier(TOMBSTONE_TABLE)} (alias_product_id, canonical_product_id, platform_product_id, product_row_json, lifecycle_provenance, dependency_summary_json, plan_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alias_id,
                survivor_by_alias[alias_id],
                platform_id,
                canonical_json(row),
                row.get("lifecycle_provenance"),
                canonical_json({"references": [{key: value for key, value in item.items() if key != "row"} for item in alias_dependencies]}),
                plan["plan_digest"],
                now,
            ),
        )
        for item in alias_dependencies:
            tombstone_locator = f"{item['column']}|{item['row_locator']}"
            connection.execute(
                f"INSERT INTO {quote_identifier(TOMBSTONE_CHILD_TABLE)} (alias_product_id, table_name, row_locator, row_json, handling, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    alias_id,
                    item["table"],
                    tombstone_locator,
                    canonical_json(item["row"]),
                    item["policy"],
                    now,
                ),
            )
            child_count += 1
    return child_count


def verify_no_alias_references(connection: sqlite3.Connection, alias_ids: set[str]) -> list[dict[str, Any]]:
    if not alias_ids:
        return []
    dependencies = scan_dependencies(connection, alias_ids)
    unresolved_refs: list[dict[str, Any]] = []
    for table in dependencies.get("tables", []):
        table_name = str(table.get("table"))
        if table_name in {TOMBSTONE_TABLE, TOMBSTONE_CHILD_TABLE}:
            continue
        # Tombstoned request lineage intentionally keeps an immutable textual
        # alias reference; it is resolved by product_catalog_alias_tombstone.
        if table.get("policy") == "PRESERVE_WITH_TOMBSTONE" and str(table.get("column")) not in {
            "product_id",
            "productId",
            "target_product_id",
            "committed_product_id",
            "linked_product_id",
            "reviewed_via_product_id",
        }:
            continue
        unresolved_refs.append(table)
    return unresolved_refs


def apply_purge(
    db_path: Path,
    *,
    plan: dict[str, Any],
    dependency: dict[str, Any],
    evidence_dir: Path,
    backup_path: Path | None,
) -> dict[str, Any]:
    if plan.get("authorization_token") != AUTHORIZATION_TOKEN:
        raise GateError(FAIL_PLAN_DIGEST, "plan authorization token is not the required mission token")
    recomputed_plan_core = {key: plan[key] for key in plan if key not in {"plan_digest", "created_at"}}
    if sha256_bytes(canonical_json(recomputed_plan_core).encode("utf-8")) != plan.get("plan_digest"):
        raise GateError(FAIL_PLAN_DIGEST, "purge plan digest does not match its content")

    # The plan stores sorted aliases and survivors separately.  The authoritative
    # pair relation is retained in the reproof artifact and loaded below.
    reproof_path = evidence_dir / "merge-proven-48-reproof.json"
    if not reproof_path.exists():
        raise GateError(FAIL_PLAN_DIGEST, f"missing reproof artifact: {reproof_path}")
    reproof = read_json(reproof_path)
    current_entries = reproof.get("current_reproven_entries") or []
    if sorted(item.get("duplicate_product_id") for item in current_entries) != sorted(plan.get("aliases") or []):
        raise GateError(FAIL_PLAN_DIGEST, "reproof aliases differ from the locked purge plan")
    if cohort_digest(current_entries) != plan.get("cohort_digest"):
        raise GateError(FAIL_PLAN_DIGEST, "current reproof cohort digest differs from purge plan")
    survivor_by_alias = {
        str(item["duplicate_product_id"]): str(item["canonical_survivor_product_id"])
        for item in current_entries
    }
    aliases = sorted(survivor_by_alias)
    survivors = sorted(set(survivor_by_alias.values()))

    with open_connection(db_path, read_only=True) as current:
        current_reproof = prove_historical_cohort(current, [
            {
                "duplicate_product_id": alias_id,
                "canonical_survivor_product_id": survivor_by_alias[alias_id],
                "historical_platform_product_id": next(
                    (item.get("platform_product_id") for item in current_entries if item["duplicate_product_id"] == alias_id),
                    None,
                ),
                "historical_signals": {},
            }
            for alias_id in aliases
        ])
        already_applied = (
            current_reproof["current_reproven_count"] == 0
            and current_reproof["purged_tombstone_count"] == len(aliases)
            and not current_reproof["failures"]
        )
        if already_applied:
            return {
                "mission_id": MISSION_ID,
                "status": "IDEMPOTENT_NOOP",
                "physical_duplicate_deletes": 0,
                "canonical_survivor_deletes": 0,
                "tombstones_created": 0,
                "child_records_migrated": 0,
                "child_records_safely_retired": 0,
                "before": population_counts(product_rows(current)),
                "after": population_counts(product_rows(current)),
                "cohort_digest": plan["cohort_digest"],
            }
        if current_reproof["current_reproven_count"] != len(aliases) or current_reproof["failures"]:
            raise GateError(FAIL_DUPLICATE_DRIFT, "live database cohort no longer matches the locked plan", payload=current_reproof)
        live_dependency = scan_dependencies(current, set(aliases))
        if live_dependency.get("unresolved_policy"):
            raise GateError(
                FAIL_DEPENDENCY_POLICY,
                "live dependency policy is unresolved immediately before apply",
                payload={"unresolved": live_dependency["unresolved_policy"]},
            )
        if compact_dependency_manifest(live_dependency) != plan.get("dependency_policy"):
            raise GateError(
                FAIL_PLAN_DIGEST,
                "live dependency blast radius differs from the digest-locked plan",
                payload={
                    "planned": plan.get("dependency_policy"),
                    "current": compact_dependency_manifest(live_dependency),
                },
            )
        # The live scan is authoritative for child pre-images. The compact JSON
        # manifest is only the plan/readback contract.
        dependency = live_dependency
        current_rows = {str(row["id"]): row for row in product_rows(current)}
        canonical_before = canonical_survivor_snapshot(current, survivors)
        before_counts = population_counts(list(current_rows.values()))
        source_snapshot = integrity_snapshot(current)
        if source_snapshot["integrity_ok"] is not True or source_snapshot["foreign_key_check_count"] != 0:
            raise GateError(FAIL_FOREIGN_KEY, "live database is not clean before purge", payload=source_snapshot)

    backup_directory = (backup_path or Path(tempfile.gettempdir()) / MISSION_ID / "backups").resolve()
    if backup_path is None:
        backup_directory.mkdir(parents=True, exist_ok=True)
        backup_path = backup_directory / f"flow_agent.pre-purge-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    backup = consistent_backup(db_path, backup_path)
    backup["aliases"] = aliases
    backup["canonical_survivors"] = survivors
    backup["source_data_version"] = source_snapshot["data_version"]
    before_document = {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "plan_digest": plan["plan_digest"],
        "cohort_digest": plan["cohort_digest"],
        "backup": backup,
        "database": {"path": str(db_path.resolve()), **source_snapshot},
        "counts": before_counts,
        "aliases": aliases,
        "canonical_survivors": survivors,
    }
    write_json(evidence_dir / "purge-before.json", before_document)

    child_records = 0
    repointed = 0
    detached_lineage = 0
    retired = 0
    deleted = 0
    connection = None
    try:
        connection = open_connection(db_path, read_only=False)
        connection.execute("BEGIN IMMEDIATE")
        # sqlite3.Connection.executescript() implicitly commits an open
        # transaction. Execute the small, static DDL statements individually so
        # tombstone creation and product deletion remain one rollback boundary.
        for statement in TOMBSTONE_DDL.split(";"):
            if statement.strip():
                connection.execute(statement)
        tombstone_existing = {
            str(row["alias_product_id"])
            for row in connection.execute(f"SELECT alias_product_id FROM {quote_identifier(TOMBSTONE_TABLE)} WHERE alias_product_id IN ({','.join('?' for _ in aliases)})", aliases).fetchall()
        }
        if tombstone_existing:
            raise GateError(FAIL_PLAN_DIGEST, f"unexpected partial tombstones already exist: {sorted(tombstone_existing)}")
        locked_rows = {str(row["id"]): dict(row) for row in connection.execute("SELECT * FROM product WHERE id IN (" + ",".join("?" for _ in aliases + survivors) + ")", aliases + survivors).fetchall()}
        if any(alias not in locked_rows for alias in aliases) or any(survivor not in locked_rows for survivor in survivors):
            raise GateError(FAIL_DUPLICATE_DRIFT, "compare-and-swap product rows disappeared before write")
        for alias_id in aliases:
            if locked_rows[alias_id].get("archived_reason") != marker_for(survivor_by_alias[alias_id]) or lifecycle_status(locked_rows[alias_id]) != "ARCHIVED":
                raise GateError(FAIL_DUPLICATE_DRIFT, f"alias state changed before write: {alias_id}")
            if len(platform_ids(locked_rows[alias_id])) != 1 or platform_ids(locked_rows[alias_id]) != platform_ids(locked_rows[survivor_by_alias[alias_id]]):
                raise GateError(FAIL_IDENTITY_CONTRADICTION, f"external identity changed before write: {alias_id}")
        child_records = insert_tombstones(
            connection,
            plan=plan,
            dependency=dependency,
            product_by_id=locked_rows,
            survivor_by_alias=survivor_by_alias,
        )
        repointed, detached_lineage = repoint_and_null_lineage(connection, aliases, survivor_by_alias)
        retired = delete_stale_no_fk_children(connection, dependency, aliases)
        for alias_id in aliases:
            cursor = connection.execute(
                "DELETE FROM product WHERE id=? AND lifecycle_status='ARCHIVED' AND archived_reason=?",
                (alias_id, marker_for(survivor_by_alias[alias_id])),
            )
            if cursor.rowcount != 1:
                raise GateError(FAIL_DUPLICATE_DRIFT, f"compare-and-swap delete did not delete exactly one alias: {alias_id}")
            deleted += 1

        post_snapshot = integrity_snapshot(connection)
        if not post_snapshot["integrity_ok"]:
            raise GateError(FAIL_POST_INTEGRITY, "post-delete integrity_check failed inside transaction", payload=post_snapshot)
        if post_snapshot["foreign_key_check_count"] != 0:
            raise GateError(FAIL_FOREIGN_KEY, "post-delete foreign_key_check failed inside transaction", payload=post_snapshot)
        for alias_id in aliases:
            if product_row(connection, alias_id) is not None:
                raise GateError(FAIL_POST_INTEGRITY, f"alias still present inside transaction: {alias_id}")
        for survivor_id, before_row in canonical_before.items():
            after_row = product_row(connection, survivor_id)
            if after_row is None or after_row != before_row:
                raise GateError(FAIL_CANONICAL_MUTATION, f"canonical survivor changed inside transaction: {survivor_id}")
        unresolved_refs = verify_no_alias_references(connection, set(aliases))
        if unresolved_refs:
            raise GateError(FAIL_DEPENDENCY_POLICY, "alias references remain after dependency handling", payload={"references": unresolved_refs})
        duplicate_active_ids = assert_active_external_id_uniqueness(connection)
        if duplicate_active_ids:
            raise GateError(FAIL_POST_INTEGRITY, "active rows still share an authoritative platform ID", payload={"duplicates": duplicate_active_ids})
        connection.commit()
        post_backup_path = backup_path.with_name(f"{backup_path.stem}.post-purge{backup_path.suffix}")
        post_backup = consistent_backup(db_path, post_backup_path)
        post_counts = population_counts(product_rows(connection))
        after_document = {
            "mission_id": MISSION_ID,
            "captured_at": utc_now(),
            "status": "APPLIED",
            "plan_digest": plan["plan_digest"],
            "cohort_digest": plan["cohort_digest"],
            "database": {
                "path": str(db_path.resolve()),
                "consistent_snapshot_sha256": post_backup["sha256"],
                **integrity_snapshot(connection),
            },
            "backup": backup,
            "post_backup": post_backup,
            "counts": post_counts,
            "exact_arithmetic": {
                "raw_product_rows_before": before_counts["raw_product_rows"],
                "raw_product_rows_after": post_counts["raw_product_rows"],
                "physical_deletes": deleted,
                "raw_after_equals_before_minus_deletes": post_counts["raw_product_rows"] == before_counts["raw_product_rows"] - deleted,
            },
            "canonical_survivor_deletes": 0,
            "unauthorized_deletes": 0,
            "aliases_absent": all(product_row(connection, alias_id) is None for alias_id in aliases),
            "canonical_survivors_unchanged": all(product_row(connection, survivor_id) == before_row for survivor_id, before_row in canonical_before.items()),
            "duplicate_active_platform_ids": assert_active_external_id_uniqueness(connection),
            "child_records_migrated": repointed,
            "lineage_records_detached": detached_lineage,
            "child_records_safely_retired": retired,
            "tombstones_created": deleted,
            "tombstone_child_records": child_records,
            "provider_operations": 0,
        }
        write_json(evidence_dir / "purge-after.json", after_document)
        return {
            "mission_id": MISSION_ID,
            "status": "APPLIED",
            "physical_duplicate_deletes": deleted,
            "canonical_survivor_deletes": 0,
            "tombstones_created": deleted,
            "child_records_migrated": repointed,
            "lineage_records_detached": detached_lineage,
            "child_records_safely_retired": retired,
            "tombstone_child_records": child_records,
            "before": before_counts,
            "after": post_counts,
            "backup": backup,
            "cohort_digest": plan["cohort_digest"],
        }
    except BaseException:
        if connection is not None:
            connection.rollback()
        raise
    finally:
        if connection is not None:
            connection.close()


def build_cohort_document(
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    classifications: dict[str, Any],
    origin_main_sha: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = {str(row["product_id"]): row for row in classifications["rows"]}
    rows = product_rows(connection)
    cohort = [
        row
        for row in rows
        if lifecycle_status(row) == "ACTIVE"
        and by_id.get(str(row.get("id") or ""), {}).get("primary_classification") == "KEEP_CANONICAL"
        and str(row.get("id") or "").strip()
        and str(row.get("product_display_name") or row.get("raw_product_title") or "").strip()
    ]
    cohort.sort(key=lambda row: str(row.get("id") or ""))
    ids = [str(row["id"]) for row in cohort]
    ids_sha = sha256_bytes(canonical_json(ids).encode("utf-8"))
    snapshot = integrity_snapshot(connection)
    document = {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "database": {
            "absolute_path": str(db_path.resolve()),
            "data_version": snapshot["data_version"],
        },
        "origin_main_sha": origin_main_sha,
        "count": len(ids),
        "product_ids": ids,
        "sorted_cohort_sha256": ids_sha,
        "selection_rules": [
            "product.lifecycle_status = ACTIVE",
            "classification is KEEP_CANONICAL after the 48-row purge",
            "shared Product Intelligence test-fixture rows excluded",
            "DUPLICATE_MERGED_TO_CANONICAL aliases excluded",
            "identity must have a non-empty product id and name",
            "visual audit consumes this exact sorted ID list and does not broaden it",
        ],
    }
    return document, cohort


def git_sha(ref: str, *, cwd: Path = REPO) -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", ref], cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def branch_name(*, cwd: Path = REPO) -> str | None:
    try:
        result = subprocess.run(["git", "branch", "--show-current"], cwd=cwd, capture_output=True, text=True, check=True)
        return result.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def capture_runtime_proof(db_path: Path, *, runtime_url: str = "http://127.0.0.1:8100") -> dict[str, Any]:
    import urllib.error
    import urllib.request

    def get_json(path: str) -> dict[str, Any]:
        with urllib.request.urlopen(runtime_url.rstrip("/") + path, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    endpoints: dict[str, Any] = {}
    failures: list[str] = []
    for name, path in (("health", "/health"), ("version", "/api/local-agent/version-proof"), ("storage", "/api/operator/runtime-storage-status")):
        try:
            endpoints[name] = get_json(path)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            endpoints[name] = None
            failures.append(f"{name}:{exc}")
    version = endpoints.get("version") or {}
    storage = endpoints.get("storage") or {}
    runtime_pid = version.get("pid")
    port_owner_pid = None
    if os.name == "nt":
        try:
            command = "(Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)"
            result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, check=False)
            value = result.stdout.strip()
            port_owner_pid = int(value) if value.isdigit() else None
        except (OSError, ValueError):
            pass
    return {
        "mission_id": MISSION_ID,
        "captured_at": utc_now(),
        "runtime_url": runtime_url,
        "health_http_200": bool(endpoints.get("health")),
        "runtime_loaded_sha": version.get("git_head"),
        "runtime_branch": version.get("git_branch"),
        "runtime_pid": runtime_pid,
        "port_8100_owner_pid": port_owner_pid,
        "runtime_route_count": version.get("route_count"),
        "dashboard_bundle": version.get("dashboard_bundle"),
        "source_stale_since_start": version.get("source_stale_since_start"),
        "runtime_db_absolute_path": storage.get("effective_db_path"),
        "expected_canonical_db_absolute_path": str(db_path.resolve()),
        "runtime_storage_matches_expected": storage.get("effective_db_path") == str(db_path.resolve()),
        "runtime_storage_status": storage,
        "endpoint_payloads": endpoints,
        "failures": failures,
    }


def audit_database(
    db_path: Path,
    *,
    evidence_dir: Path,
    historical_path: Path,
    media_root: Path,
    write_evidence: bool = True,
) -> dict[str, Any]:
    historical_pairs = load_historical_pairs(historical_path)
    if len(historical_pairs) != EXPECTED_HISTORICAL_COHORT:
        raise GateError(FAIL_DUPLICATE_DRIFT, f"historical evidence count is {len(historical_pairs)}, expected {EXPECTED_HISTORICAL_COHORT}")
    snapshot_path = Path(tempfile.gettempdir()) / MISSION_ID / "audit-snapshots" / f"audit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.db"
    snapshot = consistent_backup(db_path, snapshot_path)
    with open_connection(db_path, read_only=True) as connection:
        reproof = prove_historical_cohort(connection, historical_pairs)
        aliases = {item["duplicate_product_id"] for item in historical_pairs if product_row(connection, item["duplicate_product_id"]) is not None}
        dependency = scan_dependencies(connection, aliases)
        classifications = classify_products(product_rows(connection), historical_pairs)
        baseline = baseline_document(
            connection,
            db_path=db_path,
            snapshot_sha256=snapshot["sha256"],
            historical_pairs=historical_pairs,
            reproof=reproof,
            classifications=classifications,
        )
        plan = None
        if reproof["current_reproven_count"] == EXPECTED_HISTORICAL_COHORT and not reproof["failures"] and not dependency.get("unresolved_policy"):
            plan = build_purge_plan(
                connection,
                db_path=db_path,
                historical_pairs=historical_pairs,
                reproof=reproof,
                dependency=dependency,
                snapshot_sha256=snapshot["sha256"],
            )
    if write_evidence:
        write_json(evidence_dir / "c0-baseline.json", baseline)
        write_json(evidence_dir / "c0-classification.json", classifications)
        write_json(evidence_dir / "merge-proven-48-reproof.json", reproof)
        write_json(evidence_dir / "dependency-blast-radius.json", {"captured_at": utc_now(), **compact_dependency_manifest(dependency)})
        if plan is not None:
            write_json(evidence_dir / "purge-plan.json", plan)
    return {
        "historical_pairs": historical_pairs,
        "reproof": reproof,
        "dependency": dependency,
        "classifications": classifications,
        "baseline": baseline,
        "plan": plan,
        "snapshot": snapshot,
    }


def write_final_report(
    evidence_dir: Path,
    *,
    audit: dict[str, Any],
    after: dict[str, Any] | None,
    cohort: dict[str, Any] | None,
    visual: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    verdict: str,
    next_decision: str,
    engineering: dict[str, Any] | None = None,
) -> None:
    before_counts = audit["baseline"]["counts"]
    after_counts = (after or {}).get("counts") or before_counts
    reproven = audit["reproof"].get("current_reproven_count", 0)
    drifted = audit["reproof"].get("drifted_count", 0)
    classification_counts = (audit.get("classifications") or {}).get("classification_counts") or {}
    state_counts = (visual or {}).get("state_counts") or {}
    not_verified_lines = [f"- {item}" for item in ((engineering or {}).get("not_verified") or [])] or ["NONE"]
    risks_lines = [f"- {item}" for item in ((engineering or {}).get("risks") or [])] or ["NONE"]
    lines = [
        "# BOSMAX Catalog Decontamination — 2026-08-09",
        "",
        "## VERDICT",
        "",
        verdict,
        "",
        "## WHY IT MATTERS",
        "",
        "The catalog denominator now distinguishes raw rows, lifecycle populations, historical aliases, real canonical products, and production visual onboarding. The authorized exact-duplicate cohort is governed by external listing identity, variant compatibility, transaction guards, and durable tombstone evidence; visual coverage remains anchored to the same canonical product without provider spend.",
        "",
        "## NEXT ACTION",
        "",
        "NONE — MISSION COMPLETE" if next_decision == "CATALOG_AND_VISUAL_CLOSURE_COMPLETE" else "Owner review is required for the unresolved evidence listed below.",
        "",
        "## STATUS",
        "",
        f"origin/main: {(engineering or {}).get('origin_main_sha')}",
        f"implementation commit: {(engineering or {}).get('implementation_commit')}",
        f"PR: {(engineering or {}).get('pr')}",
        f"merge SHA: {(engineering or {}).get('merge_sha')}",
        f"runtime SHA: {(runtime or {}).get('runtime_loaded_sha')}",
        f"runtime PID: {(runtime or {}).get('runtime_pid')}",
        f"canonical DB: {audit['baseline']['database']['absolute_path']}",
        f"DB SHA before: {audit['baseline']['database']['consistent_snapshot_sha256']}",
        f"DB SHA after: {(after or {}).get('database', {}).get('consistent_snapshot_sha256')}",
        f"integrity: {(after or {}).get('database', {}).get('integrity_check') or audit['baseline']['database']['integrity_check']}",
        f"foreign keys: {(after or {}).get('database', {}).get('foreign_key_check_count', 0)}",
        "provider operations: 0",
        "",
        "## RAW CATALOG — BEFORE",
        "",
        f"RAW_PRODUCT_ROWS = {before_counts.get('raw_product_rows')}",
        f"ACTIVE_ROWS = {before_counts.get('active_rows')}",
        f"ARCHIVED_ROWS = {before_counts.get('archived_rows')}",
        f"MERGED_ALIAS_ROWS = {before_counts.get('merged_historical_aliases')}",
        f"REAL_CANONICAL_PRODUCTS = {before_counts.get('real_canonical_products')}",
        "",
        "## 48 MERGE_PROVEN REPROOF",
        "",
        "historical cohort = 48",
        f"re-proven = {reproven}",
        f"drifted = {drifted}",
        f"canonical survivors = {audit['reproof'].get('canonical_survivor_count')}",
        "",
        "## PURGE RESULT",
        "",
        f"physical duplicate deletes = {(after or {}).get('exact_arithmetic', {}).get('physical_deletes', 0)}",
        "canonical survivor deletes = 0",
        "unauthorized deletes = 0",
        f"child records migrated = {(after or {}).get('child_records_migrated', 0)}",
        f"child records safely retired = {(after or {}).get('child_records_safely_retired', 0)}",
        f"tombstones created = {(after or {}).get('tombstones_created', 0)}",
        "blocked aliases = 0",
        "",
        "## RAW CATALOG — AFTER",
        "",
        f"RAW_PRODUCT_ROWS = {after_counts.get('raw_product_rows')}",
        f"ACTIVE_ROWS = {after_counts.get('active_rows')}",
        f"ARCHIVED_ROWS = {after_counts.get('archived_rows')}",
        f"MERGED_ALIAS_ROWS = {after_counts.get('merged_historical_aliases')}",
        f"REAL_CANONICAL_PRODUCTS = {after_counts.get('real_canonical_products')}",
        f"Arithmetic: {before_counts.get('raw_product_rows')} - {(after or {}).get('exact_arithmetic', {}).get('physical_deletes', 0)} = {after_counts.get('raw_product_rows')}",
        "",
        "## DECONTAMINATION REMAINDER",
        "",
        f"NEW_EXACT_DUPLICATE_CANDIDATES = {len((audit.get('classifications') or {}).get('new_exact_duplicate_candidates') or [])}",
        f"NEAR_DUPLICATE_REVIEW = {len((audit.get('classifications') or {}).get('near_duplicate_review') or [])}",
        f"SUPERSEDED_OUTDATED = {classification_counts.get('SUPERSEDED_OUTDATED_CANDIDATE', 0)}",
        f"TEST_JUNK = {classification_counts.get('DELETE_TEST_JUNK_CANDIDATE', 0)}",
        f"BROKEN_ORPHAN = {classification_counts.get('BROKEN_INTAKE_CANDIDATE', 0) + classification_counts.get('ORPHAN_RECORD_CANDIDATE', 0)}",
        f"REVIEW_REQUIRED = {classification_counts.get('REVIEW_REQUIRED', 0)}",
        "",
        "## CANONICAL VISUAL COVERAGE",
        "",
        f"CANONICAL_PRODUCTION_PRODUCTS = {(visual or {}).get('cohort_count', (cohort or {}).get('count'))}",
        f"APPROVED_CUTOUT = {state_counts.get('APPROVED_CANONICAL_CUTOUT', 0)}",
        f"CANONICAL_REFERENCE_FALLBACK = {state_counts.get('CANONICAL_REFERENCE_FALLBACK', 0)}",
        f"CUTOUT_PENDING_REVIEW = {state_counts.get('CUTOUT_PENDING_REVIEW', 0)}",
        f"BLOCKED_NO_TRUSTED_PRODUCT_MEDIA = {state_counts.get('BLOCKED_NO_TRUSTED_PRODUCT_MEDIA', 0)}",
        f"REVIEW_REQUIRED_VISUAL_IDENTITY = {state_counts.get('REVIEW_REQUIRED_VISUAL_IDENTITY', 0)}",
        f"VISUAL_GROUNDING_AVAILABLE = {(visual or {}).get('visual_grounding_available', 0)}",
        f"EXACT_COMMERCE_CUTOUT_READY = {(visual or {}).get('exact_commerce_cutout_ready', 0)}",
        "",
        "## REMOTE PROOF",
        "",
        f"branch = {(engineering or {}).get('branch')}",
        f"commit SHA = {(engineering or {}).get('implementation_commit')}",
        f"PR number = {(engineering or {}).get('pr_number')}",
        f"PR URL = {(engineering or {}).get('pr_url')}",
        f"CI = {(engineering or {}).get('ci')}",
        f"merge SHA = {(engineering or {}).get('merge_sha')}",
        f"current remote main SHA = {(engineering or {}).get('current_remote_main_sha')}",
        f"merge ancestry verified = {(engineering or {}).get('merge_ancestry_verified')}",
        "",
        "## DATABASE PROOF",
        "",
        f"backup path = {(after or {}).get('backup', {}).get('path')}",
        f"backup SHA-256 = {(after or {}).get('backup', {}).get('sha256')}",
        f"pre integrity_check = {audit['baseline']['database']['integrity_check']}",
        f"post integrity_check = {(after or {}).get('database', {}).get('integrity_check')}",
        f"pre foreign_key_check = {audit['baseline']['database'].get('foreign_key_check')}",
        f"post foreign_key_check = {(after or {}).get('database', {}).get('foreign_key_check')}",
        f"pre data_version = {audit['baseline']['database'].get('data_version')}",
        f"post data_version = {(after or {}).get('database', {}).get('data_version')}",
        "",
        "## TESTS",
        "",
        f"{(engineering or {}).get('tests', 'Evidence populated by the mission runner; see repository validation report.')}",
        "",
        "## NOT VERIFIED",
        "",
        *not_verified_lines,
        "",
        "## RISKS",
        "",
        *risks_lines,
        "",
        "## NEXT DECISION",
        "",
        next_decision,
        "",
    ]
    (evidence_dir / "FINAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    modes = cli.add_mutually_exclusive_group(required=True)
    modes.add_argument("--audit", action="store_true")
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--apply", action="store_true")
    modes.add_argument("--verify", action="store_true")
    cli.add_argument("--db", type=Path, default=REPO / "flow_agent.db")
    cli.add_argument("--evidence-dir", type=Path, default=REPO / "docs" / "evidence" / "product-catalog-decontamination-20260809")
    cli.add_argument("--historical-evidence", type=Path, default=REPO / "outputs" / "mission-pi12" / "pi13_merge_candidates.json")
    cli.add_argument("--media-root", type=Path, default=REPO)
    cli.add_argument("--backup-path", type=Path)
    cli.add_argument("--authorize")
    cli.add_argument("--runtime-proof", action="store_true")
    cli.add_argument("--runtime-url", default="http://127.0.0.1:8100")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    db_path = args.db.resolve()
    evidence_dir = args.evidence_dir.resolve()
    historical_path = args.historical_evidence.resolve()
    media_root = args.media_root.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.audit or args.plan:
            audit = audit_database(db_path, evidence_dir=evidence_dir, historical_path=historical_path, media_root=media_root)
            if args.plan and audit.get("plan") is None:
                if audit["reproof"]["current_reproven_count"] != EXPECTED_HISTORICAL_COHORT or audit["reproof"]["failures"]:
                    raise GateError(FAIL_DUPLICATE_DRIFT, "plan cannot be created because current reproof is not exactly the authorized 48", payload=audit["reproof"])
                if audit["dependency"].get("unresolved_policy"):
                    raise GateError(FAIL_DEPENDENCY_POLICY, "plan cannot be created because dependency policy is unresolved", payload={"unresolved": audit["dependency"]["unresolved_policy"]})
                raise GateError(FAIL_DUPLICATE_DRIFT, "plan cannot be created because a required safety gate is not green")
            print(json.dumps({
                "mode": "audit" if args.audit else "plan",
                "db": str(db_path),
                "historical_count": len(audit["historical_pairs"]),
                "current_reproven": audit["reproof"]["current_reproven_count"],
                "drifted": audit["reproof"]["drifted_count"],
                "unresolved_dependency_policy": len(audit["dependency"].get("unresolved_policy") or []),
                "plan_digest": (audit.get("plan") or {}).get("plan_digest"),
            }, indent=2))
            return 0
        if args.apply:
            if args.authorize != AUTHORIZATION_TOKEN:
                raise GateError(FAIL_PLAN_DIGEST, f"--apply requires --authorize {AUTHORIZATION_TOKEN}")
            plan_path = evidence_dir / "purge-plan.json"
            dependency_path = evidence_dir / "dependency-blast-radius.json"
            if not plan_path.exists() or not dependency_path.exists():
                raise GateError(FAIL_PLAN_DIGEST, "--apply requires current purge-plan.json and dependency-blast-radius.json")
            plan = read_json(plan_path)
            dependency = read_json(dependency_path)
            result = apply_purge(db_path, plan=plan, dependency=dependency, evidence_dir=evidence_dir, backup_path=args.backup_path)
            print(json.dumps(result, indent=2, default=json_default))
            return 0
        if args.verify:
            audit = audit_database(
                db_path,
                evidence_dir=evidence_dir,
                historical_path=historical_path,
                media_root=media_root,
                write_evidence=False,
            )
            if (
                audit["reproof"]["current_reproven_count"] != 0
                or audit["reproof"]["purged_tombstone_count"] != EXPECTED_HISTORICAL_COHORT
                or audit["reproof"].get("failures")
            ):
                raise GateError(FAIL_DUPLICATE_DRIFT, "verify requires all 48 aliases absent and tombstoned", payload=audit["reproof"])
            with open_connection(db_path, read_only=True) as connection:
                classification = classify_products(product_rows(connection), audit["historical_pairs"])
                cohort_document, cohort_rows = build_cohort_document(
                    connection,
                    db_path=db_path,
                    classifications=classification,
                    origin_main_sha=git_sha("origin/main"),
                )
                purged_ids = {item["duplicate_product_id"] for item in audit["historical_pairs"]}
                visual = build_visual_coverage(
                    connection,
                    cohort_rows,
                    media_root=media_root,
                    purged_ids=purged_ids,
                    classification_by_id={item["product_id"]: item for item in classification["rows"]},
                )
                post_snapshot = integrity_snapshot(connection)
                after = read_json(evidence_dir / "purge-after.json") if (evidence_dir / "purge-after.json").exists() else {
                    "counts": population_counts(product_rows(connection)),
                    "database": post_snapshot,
                }
            write_json(evidence_dir / "c0-classification-after.json", classification)
            write_json(evidence_dir / "canonical-survivor-cohort.json", cohort_document)
            write_json(evidence_dir / "visual-coverage.json", visual)
            if args.runtime_proof:
                runtime = capture_runtime_proof(db_path, runtime_url=args.runtime_url)
                write_json(evidence_dir / "runtime-proof.json", runtime)
            else:
                runtime = read_json(evidence_dir / "runtime-proof.json") if (evidence_dir / "runtime-proof.json").exists() else None
            write_final_report(
                evidence_dir,
                audit=audit,
                after=after,
                cohort=cohort_document,
                visual=visual,
                runtime=runtime,
                verdict="PASS_WITH_REVIEW_ITEMS" if (visual["state_counts"].get("BLOCKED_NO_TRUSTED_PRODUCT_MEDIA", 0) or visual["state_counts"].get("CUTOUT_PENDING_REVIEW", 0)) else "PASS",
                next_decision="OWNER_REVIEW_REQUIRED" if (visual["state_counts"].get("BLOCKED_NO_TRUSTED_PRODUCT_MEDIA", 0) or visual["state_counts"].get("CUTOUT_PENDING_REVIEW", 0)) else "CATALOG_AND_VISUAL_CLOSURE_COMPLETE",
                engineering={"origin_main_sha": git_sha("origin/main"), "implementation_commit": git_sha("HEAD"), "branch": branch_name()},
            )
            print(json.dumps({
                "mode": "verify",
                "reproof": audit["reproof"],
                "cohort_count": cohort_document["count"],
                "visual_state_counts": visual["state_counts"],
                "visual_grounding_available": visual["visual_grounding_available"],
                "exact_commerce_cutout_ready": visual["exact_commerce_cutout_ready"],
                "provider_operations": 0,
            }, indent=2, default=json_default))
            return 0
    except GateError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code, "detail": exc.detail, "payload": exc.payload}, indent=2, default=json_default), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(json.dumps({"status": "ERROR", "error": str(exc)}, indent=2, default=json_default), file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
