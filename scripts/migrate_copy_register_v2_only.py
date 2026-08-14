#!/usr/bin/env python3
"""Archive and retire the three pre-V2 copy stores without losing history.

The migration is intentionally conservative:

* ``dry-run`` creates and migrates a SQLite backup copy; the source is untouched.
* ``apply`` refuses to run while the configured backend port is listening.
* every legacy row and every known historical reference is serialized into an
  immutable SHA-256 receipt before active rows are removed;
* historical FK owners are rebuilt to reference the receipt ledgers;
* active legacy tables remain empty and are protected by write-denial triggers;
* Copy Register V2 and Product Truth rows are never updated or deleted.

No provider, generation, approval, or production-queue action exists here.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import socket
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


MIGRATION_VERSION = "copy-register-v2-only-cutover-v1"
ACTIVE_STORES = {
    "copy_set": ("copy_set_id", "legacy_copy_set_receipt", "legacy_copy_set_id"),
    "copy_component": (
        "component_id",
        "legacy_copy_component_receipt",
        "legacy_component_id",
    ),
    "poster_copy_set": (
        "poster_copy_set_id",
        "legacy_poster_copy_set_receipt",
        "legacy_poster_copy_set_id",
    ),
}
REFERENCE_COLUMNS = {
    ("content_combination", "copy_set_id", "combination_id", "COPY_SET"),
    ("creative_treatment", "copy_set_id", "treatment_id", "COPY_SET"),
    ("creative_variation_group", "copy_set_id", "group_id", "COPY_SET"),
    (
        "creative_supply_review_event",
        "component_id",
        "event_id",
        "COPY_COMPONENT",
    ),
    (
        "poster_deliverable",
        "poster_copy_set_id",
        "poster_deliverable_id",
        "POSTER_COPY_SET",
    ),
}
# These two columns had no FK and were historically used by active selection
# paths.  Their original values are preserved in legacy_copy_reference_receipt,
# then cleared so post-cutover runtime cannot treat them as live legacy
# authority.  FK-backed historical owners below are instead retargeted to the
# immutable receipt tables.
NONRELATIONAL_REFERENCE_CLEAR_VALUES = {
    ("content_combination", "copy_set_id"): None,
    ("poster_deliverable", "poster_copy_set_id"): "",
}
REBUILD_TABLES = {
    "creative_variation_group": {
        "references": {
            r"REFERENCES\s+copy_set\s*\(\s*copy_set_id\s*\)": (
                "REFERENCES legacy_copy_set_receipt(legacy_copy_set_id)"
            ),
        },
    },
    "creative_treatment": {
        "references": {
            r"REFERENCES\s+copy_set\s*\(\s*copy_set_id\s*\)": (
                "REFERENCES legacy_copy_set_receipt(legacy_copy_set_id)"
            ),
        },
    },
    "creative_supply_review_event": {
        "references": {
            r"REFERENCES\s+copy_component\s*\(\s*component_id\s*\)": (
                "REFERENCES legacy_copy_component_receipt(legacy_component_id)"
            ),
        },
    },
}
V2_TABLES = {
    "copy_blueprint_v2",
    "copy_angle_candidate_v2",
    "copy_evidence_fact_v2",
    "copy_execution_binding_v2",
    "copy_execution_authority_v2",
}


class CutoverError(RuntimeError):
    """Stable fail-closed migration error."""


@dataclass(frozen=True)
class CutoverResult:
    migration_id: str
    database_path: str
    backup_path: str
    receipt_path: str
    manifest_sha256: str
    before_counts: dict[str, int]
    after_counts: dict[str, int]
    archive_counts: dict[str, int]
    reference_counts: dict[str, int]
    cleared_reference_counts: dict[str, int]
    unresolved_active_reference_counts: dict[str, int]
    integrity_check: str
    foreign_key_violations: list[list[Any]]
    already_applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "migration_version": MIGRATION_VERSION,
            "migration_id": self.migration_id,
            "database_path": self.database_path,
            "backup_path": self.backup_path,
            "receipt_path": self.receipt_path,
            "manifest_sha256": self.manifest_sha256,
            "before_counts": self.before_counts,
            "after_counts": self.after_counts,
            "archive_counts": self.archive_counts,
            "reference_counts": self.reference_counts,
            "cleared_reference_counts": self.cleared_reference_counts,
            "unresolved_active_reference_counts": self.unresolved_active_reference_counts,
            "integrity_check": self.integrity_check,
            "foreign_key_violations": self.foreign_key_violations,
            "already_applied": self.already_applied,
            "provider_calls": 0,
            "credit_spend": False,
            "product_truth_mutations": 0,
            "copy_v2_mutations": 0,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _row_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0])


def _counts(connection: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    existing = _table_names(connection)
    return {
        table: _row_count(connection, table) if table in existing else -1
        for table in tables
    }


def _schema_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row or not row[0]:
        raise CutoverError(f"LEGACY_SCHEMA_MISSING:{table}")
    return str(row[0])


def _schema_digest(connection: sqlite3.Connection, table: str) -> str:
    return _sha256_text(_schema_sql(connection, table))


def _assert_expected_reference_columns(connection: sqlite3.Connection) -> None:
    found: set[tuple[str, str, str, str]] = set()
    active = set(ACTIVE_STORES)
    for table in sorted(_table_names(connection)):
        if table in active or table.startswith("legacy_"):
            continue
        columns = list(connection.execute(f"PRAGMA table_info({_quote(table)})"))
        names = {str(column[1]) for column in columns}
        id_column = next((str(column[1]) for column in columns if int(column[5]) > 0), "")
        for column, target in (
            ("copy_set_id", "COPY_SET"),
            ("component_id", "COPY_COMPONENT"),
            ("poster_copy_set_id", "POSTER_COPY_SET"),
        ):
            if column in names:
                found.add((table, column, id_column, target))
    if found != REFERENCE_COLUMNS:
        raise CutoverError(
            "LEGACY_REFERENCE_SURFACE_CHANGED:"
            + _canonical_json(
                {
                    "expected": sorted(REFERENCE_COLUMNS),
                    "found": sorted(found),
                    "missing": sorted(REFERENCE_COLUMNS - found),
                    "unexpected": sorted(found - REFERENCE_COLUMNS),
                }
            )
        )


def _create_receipt_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
CREATE TABLE IF NOT EXISTS legacy_copy_migration_receipt (
    migration_id          TEXT PRIMARY KEY,
    migration_version     TEXT NOT NULL,
    applied_at            TEXT NOT NULL,
    source_database_path  TEXT NOT NULL,
    backup_path           TEXT NOT NULL,
    backup_sha256         TEXT NOT NULL,
    before_counts_json    TEXT NOT NULL,
    after_counts_json     TEXT NOT NULL,
    archive_counts_json   TEXT NOT NULL,
    reference_counts_json TEXT NOT NULL,
    source_schema_json    TEXT NOT NULL,
    manifest_sha256       TEXT NOT NULL,
    integrity_check       TEXT NOT NULL,
    foreign_key_check_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_copy_set_receipt (
    legacy_copy_set_id TEXT PRIMARY KEY,
    migration_id       TEXT NOT NULL,
    product_id         TEXT NOT NULL,
    row_json           TEXT NOT NULL,
    row_sha256         TEXT NOT NULL CHECK(length(row_sha256) = 64),
    source_schema_sha256 TEXT NOT NULL CHECK(length(source_schema_sha256) = 64),
    archived_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_copy_component_receipt (
    legacy_component_id TEXT PRIMARY KEY,
    migration_id         TEXT NOT NULL,
    product_id           TEXT NOT NULL,
    row_json             TEXT NOT NULL,
    row_sha256           TEXT NOT NULL CHECK(length(row_sha256) = 64),
    source_schema_sha256 TEXT NOT NULL CHECK(length(source_schema_sha256) = 64),
    archived_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_poster_copy_set_receipt (
    legacy_poster_copy_set_id TEXT PRIMARY KEY,
    migration_id              TEXT NOT NULL,
    product_id                TEXT NOT NULL,
    row_json                  TEXT NOT NULL,
    row_sha256                TEXT NOT NULL CHECK(length(row_sha256) = 64),
    source_schema_sha256      TEXT NOT NULL CHECK(length(source_schema_sha256) = 64),
    archived_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_copy_reference_receipt (
    source_table      TEXT NOT NULL,
    source_row_id     TEXT NOT NULL,
    source_column     TEXT NOT NULL,
    target_kind       TEXT NOT NULL,
    legacy_id         TEXT NOT NULL,
    migration_id      TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL CHECK(length(source_row_sha256) = 64),
    archived_at       TEXT NOT NULL,
    PRIMARY KEY (source_table, source_row_id, source_column, legacy_id)
);
"""
    )


def _archive_store(
    connection: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    receipt_table: str,
    receipt_id_column: str,
    migration_id: str,
    archived_at: str,
) -> int:
    schema_sha = _schema_digest(connection, table)
    rows = connection.execute(f"SELECT * FROM {_quote(table)}").fetchall()
    for row in rows:
        payload = {key: row[key] for key in row.keys()}
        row_json = _canonical_json(payload)
        connection.execute(
            f"""
            INSERT INTO {_quote(receipt_table)}
                ({_quote(receipt_id_column)}, migration_id, product_id, row_json,
                 row_sha256, source_schema_sha256, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload[id_column]),
                migration_id,
                str(payload.get("product_id") or ""),
                row_json,
                _sha256_text(row_json),
                schema_sha,
                archived_at,
            ),
        )
    return len(rows)


def _archive_references(
    connection: sqlite3.Connection,
    *,
    migration_id: str,
    archived_at: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, column, row_id_column, target_kind in sorted(REFERENCE_COLUMNS):
        rows = connection.execute(
            f"""
            SELECT source.* FROM {_quote(table)} AS source
            WHERE TRIM(COALESCE(source.{_quote(column)}, '')) <> ''
            """
        ).fetchall()
        for row in rows:
            payload = {key: row[key] for key in row.keys()}
            row_json = _canonical_json(payload)
            connection.execute(
                """
                INSERT INTO legacy_copy_reference_receipt
                    (source_table, source_row_id, source_column, target_kind,
                     legacy_id, migration_id, source_row_sha256, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    table,
                    str(payload[row_id_column]),
                    column,
                    target_kind,
                    str(payload[column]),
                    migration_id,
                    _sha256_text(row_json),
                    archived_at,
                ),
            )
        counts[f"{table}.{column}"] = len(rows)
    return counts


def _active_nonrelational_reference_counts(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    return {
        f"{table}.{column}": int(
            connection.execute(
                f"SELECT COUNT(*) FROM {_quote(table)} "
                f"WHERE TRIM(COALESCE({_quote(column)}, '')) <> ''"
            ).fetchone()[0]
        )
        for table, column in sorted(NONRELATIONAL_REFERENCE_CLEAR_VALUES)
    }


def _clear_nonrelational_active_references(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    """Clear only references whose original value is already receipt-backed."""

    before = _active_nonrelational_reference_counts(connection)
    for (table, column), replacement in sorted(
        NONRELATIONAL_REFERENCE_CLEAR_VALUES.items()
    ):
        connection.execute(
            f"UPDATE {_quote(table)} SET {_quote(column)}=? "
            f"WHERE TRIM(COALESCE({_quote(column)}, '')) <> ''",
            (replacement,),
        )
    after = _active_nonrelational_reference_counts(connection)
    if any(after.values()):
        raise CutoverError(
            "UNRESOLVED_ACTIVE_LEGACY_REFERENCES:" + _canonical_json(after)
        )
    return before


def _capture_schema_objects(
    connection: sqlite3.Connection, table: str
) -> list[tuple[str, str, str]]:
    return [
        (str(row[0]), str(row[1]), str(row[2]))
        for row in connection.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE tbl_name=? AND type IN ('index','trigger') AND sql IS NOT NULL
            ORDER BY type, name
            """,
            (table,),
        )
    ]


def _temporary_table_sql(table: str, sql: str, temp_table: str) -> str:
    pattern = re.compile(
        rf"^(\s*CREATE\s+TABLE\s+)(?:\"{re.escape(table)}\"|{re.escape(table)})",
        re.IGNORECASE,
    )
    transformed, replacements = pattern.subn(
        rf'\1"{temp_table}"', sql, count=1
    )
    if replacements != 1:
        raise CutoverError(f"TABLE_SQL_TRANSFORM_FAILED:{table}")
    for reference_pattern, replacement in REBUILD_TABLES[table]["references"].items():
        transformed, count = re.subn(
            reference_pattern, replacement, transformed, flags=re.IGNORECASE
        )
        if count < 1:
            raise CutoverError(f"FK_SQL_TRANSFORM_FAILED:{table}:{reference_pattern}")
    # Keep self-referential constraints valid while the temporary table exists.
    transformed = re.sub(
        rf"REFERENCES\s+(?:\"{re.escape(table)}\"|{re.escape(table)})\s*\(",
        f'REFERENCES "{temp_table}"(',
        transformed,
        flags=re.IGNORECASE,
    )
    return transformed


def _rebuild_historical_reference_tables(connection: sqlite3.Connection) -> None:
    captured: dict[str, list[tuple[str, str, str]]] = {}
    temporary: dict[str, str] = {}
    for table in REBUILD_TABLES:
        temp_table = f"__v2_cutover_{table}"
        if temp_table in _table_names(connection):
            raise CutoverError(f"TEMP_TABLE_ALREADY_EXISTS:{temp_table}")
        captured[table] = _capture_schema_objects(connection, table)
        sql = _temporary_table_sql(table, _schema_sql(connection, table), temp_table)
        connection.execute(sql)
        columns = [
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({_quote(table)})")
        ]
        column_sql = ", ".join(_quote(column) for column in columns)
        connection.execute(
            f"INSERT INTO {_quote(temp_table)} ({column_sql}) "
            f"SELECT {column_sql} FROM {_quote(table)}"
        )
        temporary[table] = temp_table

    # The copies are complete before any source table is dropped.
    for table in ("creative_treatment", "creative_variation_group", "creative_supply_review_event"):
        connection.execute(f"DROP TABLE {_quote(table)}")
    for table in ("creative_variation_group", "creative_treatment", "creative_supply_review_event"):
        connection.execute(
            f"ALTER TABLE {_quote(temporary[table])} RENAME TO {_quote(table)}"
        )
    for table in REBUILD_TABLES:
        for _object_type, _name, sql in captured[table]:
            connection.execute(sql)


def _install_write_denial_triggers(connection: sqlite3.Connection) -> None:
    for table in ACTIVE_STORES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            trigger = f"trg_{table}_v2_only_{operation.lower()}"
            connection.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {_quote(trigger)}
                BEFORE {operation} ON {_quote(table)}
                BEGIN
                    SELECT RAISE(ABORT, 'LEGACY_COPY_STORAGE_DISABLED');
                END
                """
            )


def _verify_archive_digests(connection: sqlite3.Connection) -> None:
    for receipt_table in (
        "legacy_copy_set_receipt",
        "legacy_copy_component_receipt",
        "legacy_poster_copy_set_receipt",
    ):
        for row in connection.execute(
            f"SELECT row_json, row_sha256 FROM {_quote(receipt_table)}"
        ):
            if _sha256_text(str(row[0])) != str(row[1]):
                raise CutoverError(f"ARCHIVE_DIGEST_MISMATCH:{receipt_table}")


def _already_applied(connection: sqlite3.Connection) -> bool:
    tables = _table_names(connection)
    if "legacy_copy_migration_receipt" not in tables:
        return False
    active_counts = _counts(connection, ACTIVE_STORES)
    receipt_count = _row_count(connection, "legacy_copy_migration_receipt")
    return receipt_count > 0 and all(count == 0 for count in active_counts.values())


def perform_cutover(
    database_path: Path,
    *,
    backup_path: Path,
    backup_sha256: str,
) -> CutoverResult:
    """Apply the archive/purge transaction to ``database_path``."""

    database_path = database_path.resolve()
    migration_id = f"legacy-copy-archive:{uuid4()}"
    applied_at = _utc_now()
    connection = _connect(database_path)
    try:
        if _already_applied(connection):
            row = connection.execute(
                "SELECT * FROM legacy_copy_migration_receipt ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            assert row is not None
            return CutoverResult(
                migration_id=str(row["migration_id"]),
                database_path=str(database_path),
                backup_path=str(row["backup_path"]),
                receipt_path="",
                manifest_sha256=str(row["manifest_sha256"]),
                before_counts=json.loads(str(row["before_counts_json"])),
                after_counts=json.loads(str(row["after_counts_json"])),
                archive_counts=json.loads(str(row["archive_counts_json"])),
                reference_counts=json.loads(str(row["reference_counts_json"])),
                cleared_reference_counts={
                    key: 0 for key in _active_nonrelational_reference_counts(connection)
                },
                unresolved_active_reference_counts=(
                    _active_nonrelational_reference_counts(connection)
                ),
                integrity_check=str(row["integrity_check"]),
                foreign_key_violations=json.loads(str(row["foreign_key_check_json"])),
                already_applied=True,
            )

        required = set(ACTIVE_STORES) | set(REBUILD_TABLES) | V2_TABLES
        missing = sorted(required - _table_names(connection))
        if missing:
            raise CutoverError("CUTOVER_SCHEMA_MISSING:" + ",".join(missing))
        _assert_expected_reference_columns(connection)

        before_counts = _counts(connection, ACTIVE_STORES)
        v2_before = _counts(connection, V2_TABLES)
        source_schema = {
            table: _schema_digest(connection, table) for table in ACTIVE_STORES
        }

        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            _create_receipt_schema(connection)
            archive_counts: dict[str, int] = {}
            for table, (id_column, receipt_table, receipt_id_column) in ACTIVE_STORES.items():
                archive_counts[receipt_table] = _archive_store(
                    connection,
                    table=table,
                    id_column=id_column,
                    receipt_table=receipt_table,
                    receipt_id_column=receipt_id_column,
                    migration_id=migration_id,
                    archived_at=applied_at,
                )
            for table, (_id, receipt_table, _receipt_id) in ACTIVE_STORES.items():
                if archive_counts[receipt_table] != before_counts[table]:
                    raise CutoverError(
                        f"ARCHIVE_COUNT_MISMATCH:{table}:"
                        f"{archive_counts[receipt_table]}!={before_counts[table]}"
                    )
            reference_counts = _archive_references(
                connection, migration_id=migration_id, archived_at=applied_at
            )
            _verify_archive_digests(connection)
            _rebuild_historical_reference_tables(connection)
            cleared_reference_counts = _clear_nonrelational_active_references(
                connection
            )
            for key, cleared_count in cleared_reference_counts.items():
                if reference_counts.get(key) != cleared_count:
                    raise CutoverError(
                        f"REFERENCE_RECEIPT_COUNT_MISMATCH:{key}:"
                        f"{reference_counts.get(key, 0)}!={cleared_count}"
                    )
            unresolved_active_reference_counts = (
                _active_nonrelational_reference_counts(connection)
            )
            for table in ACTIVE_STORES:
                connection.execute(f"DELETE FROM {_quote(table)}")
            _install_write_denial_triggers(connection)

            after_counts = _counts(connection, ACTIVE_STORES)
            if any(after_counts.values()):
                raise CutoverError("LEGACY_ACTIVE_ROWS_REMAIN:" + _canonical_json(after_counts))
            v2_after = _counts(connection, V2_TABLES)
            if v2_before != v2_after:
                raise CutoverError(
                    "COPY_V2_TABLE_MUTATION_DETECTED:"
                    + _canonical_json({"before": v2_before, "after": v2_after})
                )

            manifest_base = {
                "migration_version": MIGRATION_VERSION,
                "migration_id": migration_id,
                "applied_at": applied_at,
                "source_database_path": str(database_path),
                "backup_path": str(backup_path),
                "backup_sha256": backup_sha256,
                "before_counts": before_counts,
                "after_counts": after_counts,
                "archive_counts": archive_counts,
                "reference_counts": reference_counts,
                "cleared_reference_counts": cleared_reference_counts,
                "unresolved_active_reference_counts": (
                    unresolved_active_reference_counts
                ),
                "source_schema_sha256": source_schema,
                "product_truth_mutations": 0,
                "copy_v2_mutations": 0,
                "provider_calls": 0,
                "credit_spend": False,
            }
            manifest_sha = _sha256_text(_canonical_json(manifest_base))
            connection.execute(
                """
                INSERT INTO legacy_copy_migration_receipt
                    (migration_id, migration_version, applied_at,
                     source_database_path, backup_path, backup_sha256,
                     before_counts_json, after_counts_json, archive_counts_json,
                     reference_counts_json, source_schema_json, manifest_sha256,
                     integrity_check, foreign_key_check_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', '[]')
                """,
                (
                    migration_id,
                    MIGRATION_VERSION,
                    applied_at,
                    str(database_path),
                    str(backup_path),
                    backup_sha256,
                    _canonical_json(before_counts),
                    _canonical_json(after_counts),
                    _canonical_json(archive_counts),
                    _canonical_json(reference_counts),
                    _canonical_json(source_schema),
                    manifest_sha,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

        connection.execute("PRAGMA foreign_keys=ON")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        fk_rows = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
        if integrity.lower() != "ok":
            raise CutoverError(f"SQLITE_INTEGRITY_FAILED:{integrity}")
        if fk_rows:
            raise CutoverError("SQLITE_FOREIGN_KEY_FAILED:" + _canonical_json(fk_rows))
        connection.execute(
            """
            UPDATE legacy_copy_migration_receipt
            SET integrity_check=?, foreign_key_check_json=?
            WHERE migration_id=?
            """,
            (integrity, _canonical_json(fk_rows), migration_id),
        )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return CutoverResult(
            migration_id=migration_id,
            database_path=str(database_path),
            backup_path=str(backup_path),
            receipt_path="",
            manifest_sha256=manifest_sha,
            before_counts=before_counts,
            after_counts=after_counts,
            archive_counts=archive_counts,
            reference_counts=reference_counts,
            cleared_reference_counts=cleared_reference_counts,
            unresolved_active_reference_counts=unresolved_active_reference_counts,
            integrity_check=integrity,
            foreign_key_violations=fk_rows,
        )
    finally:
        connection.close()


def backup_database(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise CutoverError(f"BACKUP_ALREADY_EXISTS:{destination}")
    source_connection = _connect(source)
    destination_connection = _connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    return _sha256_file(destination)


def initialize_repository_schema(database_path: Path) -> None:
    """Run the repository's additive schema initializer against one exact DB."""

    from agent import config as agent_config
    from agent.db import schema

    old_config_path = agent_config.DB_PATH
    old_schema_path = schema.DB_PATH
    agent_config.DB_PATH = database_path
    schema.DB_PATH = database_path
    try:
        asyncio.run(schema.init_db())
    finally:
        schema.DB_PATH = old_schema_path
        agent_config.DB_PATH = old_config_path


def _runtime_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.75):
            return True
    except OSError:
        return False


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _status(database_path: Path) -> dict[str, Any]:
    connection = _connect(database_path)
    try:
        tables = _table_names(connection)
        return {
            "database_path": str(database_path.resolve()),
            "active_counts": _counts(connection, ACTIVE_STORES),
            "unresolved_active_legacy_references": (
                _active_nonrelational_reference_counts(connection)
            ),
            "v2_counts": _counts(connection, V2_TABLES),
            "receipt_counts": _counts(
                connection,
                {
                    "legacy_copy_migration_receipt",
                    "legacy_copy_set_receipt",
                    "legacy_copy_component_receipt",
                    "legacy_poster_copy_set_receipt",
                    "legacy_copy_reference_receipt",
                },
            ),
            "cutover_applied": _already_applied(connection),
            "tables_present": sorted(tables & (set(ACTIVE_STORES) | V2_TABLES)),
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--mode", choices=("dry-run", "apply", "status"), required=True)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, default=8100)
    parser.add_argument(
        "--skip-schema-init",
        action="store_true",
        help="Test-only: target already contains the repository V2 schema.",
    )
    args = parser.parse_args(argv)
    source = args.db.resolve()
    if not source.is_file():
        raise CutoverError(f"DATABASE_NOT_FOUND:{source}")
    if args.mode == "status":
        print(json.dumps(_status(source), ensure_ascii=False, indent=2))
        return 0

    artifact_dir = (
        args.artifact_dir.resolve()
        if args.artifact_dir
        else source.parent / "backups" / "copy-register-v2-only"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    source_file_sha256_before = _sha256_file(source)
    if args.mode == "apply" and _runtime_listening(args.runtime_host, args.runtime_port):
        raise CutoverError(
            f"RUNTIME_STILL_LISTENING:{args.runtime_host}:{args.runtime_port}"
        )

    if args.mode == "dry-run":
        target = artifact_dir / f"{source.stem}.v2-cutover-dry-run.{stamp}.db"
        backup_path = artifact_dir / f"{source.stem}.pre-v2-cutover-dry-run.{stamp}.db"
    else:
        target = source
        backup_path = artifact_dir / f"{source.stem}.pre-v2-cutover.{stamp}.db"

    backup_sha = backup_database(source, backup_path)
    if args.mode == "dry-run":
        # Work only on a second copy.  The immutable pre-cutover backup remains
        # byte-addressable for restore proof instead of being mutated in place.
        backup_database(backup_path, target)
    if not args.skip_schema_init:
        initialize_repository_schema(target)
    result = perform_cutover(
        target,
        backup_path=backup_path,
        backup_sha256=backup_sha,
    )
    receipt_path = artifact_dir / f"copy-register-v2-only-{args.mode}-{stamp}.json"
    source_file_sha256_after = _sha256_file(source)
    payload = {
        **result.as_dict(),
        "mode": args.mode,
        "source_database_path": str(source),
        "source_database_mutated": args.mode == "apply",
        "working_database_path": str(target),
        "working_database_sha256": _sha256_file(target),
        "backup_sha256": backup_sha,
        "source_file_sha256_before": source_file_sha256_before,
        "source_file_sha256_after": source_file_sha256_after,
        "source_file_unchanged": (
            source_file_sha256_before == source_file_sha256_after
        ),
        "completed_at": _utc_now(),
        "receipt_path": str(receipt_path),
    }
    _write_receipt(receipt_path, payload)
    payload["receipt_sha256"] = _sha256_file(receipt_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CutoverError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2) from exc
