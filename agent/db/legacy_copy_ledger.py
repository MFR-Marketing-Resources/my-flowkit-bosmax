"""Shared receipt-native legacy-copy ledger schema (Task D1).

Single source of truth for the *shape* a receipt-native database has once the
Copy Register V2-only cutover is represented in schema:

* the five immutable receipt ledger tables (history for the retired
  ``copy_set`` / ``copy_component`` / ``poster_copy_set`` stores),
* the nine write-denial triggers that keep those three stores inert, and
* the historical foreign-key repoint (active store -> receipt ledger).

``scripts/migrate_copy_register_v2_only.py`` remains the governed one-shot
cutover for databases that still hold real legacy rows.  This module lets a
brand-new / already-cut-over database converge on the *same* receipt-native
shape at ``init_db`` time WITHOUT re-running that migration.  The DDL text here
is intentionally byte-identical to the migration's; ``tests`` assert parity so
the two producers can never drift.

This module imports only the standard library, so it is safe to import from the
low-level ``agent.db.schema`` bootstrap without any circular dependency.
"""

from __future__ import annotations

import re

# The three retired active stores, kept as empty write-denied shells until the
# owner-gated physical removal (Task D5).
WRITE_DENY_STORES: tuple[str, ...] = ("copy_set", "copy_component", "poster_copy_set")

# Stable fail-closed error contract already used at the DB layer.
LEGACY_COPY_STORAGE_DISABLED = "LEGACY_COPY_STORAGE_DISABLED"

# Task D5 — final physical retirement. The governed physical-retirement migration
# records a receipt row with this migration_version; its presence marks a database
# whose transitional shells are permanently retired, so init_db removes any shell
# the (untouched) base schema transiently recreates on restart.
PHYSICAL_RETIREMENT_MIGRATION_VERSION = "copy-register-physical-retirement-v1"


def drop_legacy_active_store_script() -> str:
    """Return an executescript body that removes the three retired active stores
    (and, implicitly, their indexes and write-denial triggers). Safe to run only
    after their historical FK owners have been repointed to the receipt ledgers."""

    return "".join(f'DROP TABLE IF EXISTS "{store}";\n' for store in WRITE_DENY_STORES)

# Immutable receipt ledger substrate.  Verbatim mirror of
# migrate_copy_register_v2_only.py::_create_receipt_schema so a fresh init and a
# governed cutover yield the exact same receipt tables.
RECEIPT_LEDGER_SCHEMA_SQL = """
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

RECEIPT_LEDGER_TABLES: tuple[str, ...] = (
    "legacy_copy_migration_receipt",
    "legacy_copy_set_receipt",
    "legacy_copy_component_receipt",
    "legacy_poster_copy_set_receipt",
    "legacy_copy_reference_receipt",
)

# Historical foreign-key owners that must point at the immutable receipt ledger
# rather than the retired active store.  Mirrors the migration's REBUILD_TABLES
# (creative_treatment is intentionally excluded: schema.py's existing V2-native
# rebuild already drops that FK entirely, leaving copy_set_id a free TEXT
# column, which is the canonical cut-over shape).
RECEIPT_FK_REPOINTS: dict[str, tuple[str, str]] = {
    "creative_variation_group": (
        r"REFERENCES\s+copy_set\s*\(\s*copy_set_id\s*\)",
        "REFERENCES legacy_copy_set_receipt(legacy_copy_set_id)",
    ),
    "creative_supply_review_event": (
        r"REFERENCES\s+copy_component\s*\(\s*component_id\s*\)",
        "REFERENCES legacy_copy_component_receipt(legacy_component_id)",
    ),
}


class LegacyCopyCutoverRequiredError(RuntimeError):
    """Raised when a database still holds real legacy copy rows but has not been
    put through the governed cut-over migration.  ``init_db`` fails closed rather
    than silently archiving, rewriting, or erasing that data."""


def write_deny_trigger_script() -> str:
    """Return an executescript body creating the nine ``trg_<store>_v2_only_<op>``
    BEFORE INSERT/UPDATE/DELETE triggers that fail closed with
    ``LEGACY_COPY_STORAGE_DISABLED``.  Byte-compatible with the migration's
    ``_install_write_denial_triggers``."""

    statements: list[str] = []
    for table in WRITE_DENY_STORES:
        for operation in ("INSERT", "UPDATE", "DELETE"):
            trigger = f"trg_{table}_v2_only_{operation.lower()}"
            statements.append(
                f"CREATE TRIGGER IF NOT EXISTS {trigger}\n"
                f"BEFORE {operation} ON {table}\n"
                "BEGIN\n"
                f"    SELECT RAISE(ABORT, '{LEGACY_COPY_STORAGE_DISABLED}');\n"
                "END;"
            )
    return "\n".join(statements) + "\n"


def write_deny_trigger_names() -> tuple[str, ...]:
    return tuple(
        f"trg_{table}_v2_only_{op}"
        for table in WRITE_DENY_STORES
        for op in ("insert", "update", "delete")
    )


def repoint_table_sql(original_sql: str, table: str, temp_table: str) -> str:
    """Return the CREATE TABLE text for ``temp_table`` derived from ``table``'s
    live schema with its active-store FK swapped for the receipt-ledger FK.

    Pure string transform (no DB access), ported verbatim from the governed
    migration's ``_temporary_table_sql`` so the rebuilt topology is identical.
    """

    rename_pattern = re.compile(
        rf"^(\s*CREATE\s+TABLE\s+)(?:\"{re.escape(table)}\"|{re.escape(table)})",
        re.IGNORECASE,
    )
    transformed, replacements = rename_pattern.subn(
        rf'\1"{temp_table}"', original_sql, count=1
    )
    if replacements != 1:
        raise LegacyCopyCutoverRequiredError(f"TABLE_SQL_TRANSFORM_FAILED:{table}")

    reference_pattern, replacement = RECEIPT_FK_REPOINTS[table]
    transformed, count = re.subn(
        reference_pattern, replacement, transformed, flags=re.IGNORECASE
    )
    if count < 1:
        raise LegacyCopyCutoverRequiredError(f"FK_SQL_TRANSFORM_FAILED:{table}")

    # Keep any self-referential constraint valid while the temp table exists.
    transformed = re.sub(
        rf"REFERENCES\s+(?:\"{re.escape(table)}\"|{re.escape(table)})\s*\(",
        f'REFERENCES "{temp_table}"(',
        transformed,
        flags=re.IGNORECASE,
    )
    return transformed


def has_active_store_fk(table_sql: str, table: str) -> bool:
    """True when ``table``'s live schema still references the retired active
    store (i.e. a fresh/pre-cutover shape that must be repointed)."""

    reference_pattern, _replacement = RECEIPT_FK_REPOINTS[table]
    return re.search(reference_pattern, table_sql or "", flags=re.IGNORECASE) is not None
