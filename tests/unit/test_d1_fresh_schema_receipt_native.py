"""Task D1 — fresh-schema receipt-native alignment.

Proves that a brand-new / already-cut-over database initialized under normal
production runtime (COPY_LEGACY_MAINTENANCE_MODE OFF) converges on the canonical
receipt-native legacy-copy shape:

  * five immutable receipt ledger tables exist from first init,
  * historical FKs (creative_variation_group, creative_supply_review_event)
    point at the receipt ledgers, not the active stores,
  * the three legacy stores remain physically present but EMPTY and
    write-denied (nine LEGACY_COPY_STORAGE_DISABLED triggers),
  * init is idempotent,
  * a pre-cutover database with real legacy rows fails closed (never silently
    migrated/erased), and
  * under maintenance mode the alignment is skipped so recovery + the legacy
    maintenance test-suite keep legacy storage writable.

Every test drives its own disposable temp DB and toggles the flag explicitly, so
none passes merely because conftest globally enables maintenance mode.
"""

import importlib.util
import os
import pathlib
import re
import sqlite3

import pytest

import agent  # noqa: F401 - locate repo root
from agent.db import legacy_copy_ledger, schema

RECEIPTS = legacy_copy_ledger.RECEIPT_LEDGER_TABLES
SHELLS = legacy_copy_ledger.WRITE_DENY_STORES
TRIGGERS = legacy_copy_ledger.write_deny_trigger_names()


async def _init_at(path, *, maintenance: bool) -> None:
    """Run schema.init_db() against ``path`` with the maintenance flag forced."""
    prev = os.environ.get("COPY_LEGACY_MAINTENANCE_MODE")
    if maintenance:
        os.environ["COPY_LEGACY_MAINTENANCE_MODE"] = "1"
    else:
        os.environ.pop("COPY_LEGACY_MAINTENANCE_MODE", None)
    old_path = schema.DB_PATH
    schema.DB_PATH = path
    try:
        await schema.init_db()
    finally:
        schema.DB_PATH = old_path
        if prev is None:
            os.environ.pop("COPY_LEGACY_MAINTENANCE_MODE", None)
        else:
            os.environ["COPY_LEGACY_MAINTENANCE_MODE"] = prev


def _conn(path) -> sqlite3.Connection:
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    return c


def _tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _triggers(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}


def _fk_targets(c, table):
    return {
        (r["from"], r["table"], r["to"])
        for r in c.execute(f'PRAGMA foreign_key_list("{table}")')
    }


def _count(c, t):
    return c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]


def _schema_objects(c):
    return sorted(
        (r["type"], r["name"], r["sql"])
        for r in c.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
    )


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").replace('"', "")).strip().upper()


@pytest.mark.asyncio
async def test_fresh_production_init_is_receipt_native(tmp_path):
    db = tmp_path / "fresh_prod.db"
    await _init_at(db, maintenance=False)
    c = _conn(db)
    try:
        tabs = _tables(c)
        for receipt in RECEIPTS:
            assert receipt in tabs, f"missing receipt ledger {receipt}"
        for shell in SHELLS:
            assert shell in tabs, f"missing inert shell {shell}"
            assert _count(c, shell) == 0, f"{shell} should be empty on a fresh DB"

        trg = _triggers(c)
        for name in TRIGGERS:
            assert name in trg, f"missing write-denial trigger {name}"

        # Historical FKs are receipt-native.
        assert (
            "copy_set_id",
            "legacy_copy_set_receipt",
            "legacy_copy_set_id",
        ) in _fk_targets(c, "creative_variation_group")
        assert (
            "component_id",
            "legacy_copy_component_receipt",
            "legacy_component_id",
        ) in _fk_targets(c, "creative_supply_review_event")
        # ...and never point at the retired active stores.
        assert not any(
            tgt in ("copy_set", "copy_component")
            for (_col, tgt, _to) in _fk_targets(c, "creative_variation_group")
        )
        assert not any(
            tgt in ("copy_set", "copy_component")
            for (_col, tgt, _to) in _fk_targets(c, "creative_supply_review_event")
        )
        # creative_treatment.copy_set_id is a free TEXT column (canonical shape).
        ct_fk_cols = {r["from"] for r in c.execute('PRAGMA foreign_key_list("creative_treatment")')}
        assert "copy_set_id" not in ct_fk_cols

        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        c.close()


@pytest.mark.asyncio
async def test_fresh_production_init_is_idempotent(tmp_path):
    db = tmp_path / "idempotent.db"
    await _init_at(db, maintenance=False)
    c = _conn(db)
    # Simulate an already-cut-over marker; it must survive a re-init untouched.
    c.execute(
        "INSERT INTO legacy_copy_migration_receipt (migration_id, migration_version, "
        "applied_at, source_database_path, backup_path, backup_sha256, before_counts_json, "
        "after_counts_json, archive_counts_json, reference_counts_json, source_schema_json, "
        "manifest_sha256, integrity_check, foreign_key_check_json) "
        "VALUES ('m1','v1','t','p','b','s','{}','{}','{}','{}','{}','x','ok','[]')"
    )
    c.commit()
    before = _schema_objects(c)
    before_receipt = _count(c, "legacy_copy_migration_receipt")
    c.close()

    await _init_at(db, maintenance=False)  # re-init on the same file

    c = _conn(db)
    try:
        assert _schema_objects(c) == before, "schema objects drifted on re-init"
        assert _count(c, "legacy_copy_migration_receipt") == before_receipt
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


@pytest.mark.asyncio
async def test_inert_shell_writes_are_denied(tmp_path):
    db = tmp_path / "deny.db"
    await _init_at(db, maintenance=False)
    c = _conn(db)
    try:
        # INSERT is denied on every shell.
        for shell in SHELLS:
            with pytest.raises(sqlite3.Error) as exc:
                c.execute(f'INSERT INTO "{shell}" DEFAULT VALUES')
            assert legacy_copy_ledger.LEGACY_COPY_STORAGE_DISABLED in str(exc.value)
            c.rollback()

        # UPDATE/DELETE are denied too — seed one row past the INSERT guard.
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute("DROP TRIGGER trg_copy_set_v2_only_insert")
        c.execute(
            "INSERT INTO copy_set (copy_set_id, product_id, created_at, updated_at) "
            "VALUES ('cs','p','t','t')"
        )
        c.executescript(legacy_copy_ledger.write_deny_trigger_script())
        c.commit()
        for stmt in ("UPDATE copy_set SET product_id='z'", "DELETE FROM copy_set"):
            with pytest.raises(sqlite3.Error) as exc:
                c.execute(stmt)
            assert legacy_copy_ledger.LEGACY_COPY_STORAGE_DISABLED in str(exc.value)
            c.rollback()
    finally:
        c.close()


@pytest.mark.asyncio
async def test_maintenance_mode_skips_alignment_and_keeps_legacy_writable(tmp_path):
    db = tmp_path / "maintenance.db"
    await _init_at(db, maintenance=True)
    c = _conn(db)
    try:
        # Alignment is skipped: no native receipts, no deny triggers, active FK intact.
        assert "legacy_copy_set_receipt" not in _tables(c)
        assert "trg_copy_set_v2_only_insert" not in _triggers(c)
        assert any(
            tgt == "copy_set" for (_col, tgt, _to) in _fk_targets(c, "creative_variation_group")
        )
        # Legacy storage remains writable for recovery / maintenance-mode tests.
        c.execute("PRAGMA foreign_keys=OFF")
        c.execute(
            "INSERT INTO copy_set (copy_set_id, product_id, created_at, updated_at) "
            "VALUES ('cs','p','t','t')"
        )
        c.commit()
        assert _count(c, "copy_set") == 1
    finally:
        c.close()


@pytest.mark.asyncio
async def test_pre_cutover_data_fails_closed_without_erasing(tmp_path):
    db = tmp_path / "pre_cutover.db"
    # Build the schema with legacy storage writable, then seed a real legacy row.
    await _init_at(db, maintenance=True)
    c = _conn(db)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute(
        "INSERT INTO copy_set (copy_set_id, product_id, created_at, updated_at) "
        "VALUES ('legacy-1','p','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    c.commit()
    c.close()

    # Normal-runtime init must fail closed rather than silently migrate/erase.
    with pytest.raises(legacy_copy_ledger.LegacyCopyCutoverRequiredError):
        await _init_at(db, maintenance=False)

    c = _conn(db)
    try:
        assert _count(c, "copy_set") == 1, "pre-cutover legacy row must be preserved"
        tabs = _tables(c)
        # No hidden cutover: no fabricated archive rows or migration receipt.
        if "legacy_copy_set_receipt" in tabs:
            assert _count(c, "legacy_copy_set_receipt") == 0
        if "legacy_copy_migration_receipt" in tabs:
            assert _count(c, "legacy_copy_migration_receipt") == 0
    finally:
        c.close()


def test_receipt_and_trigger_schema_matches_governed_migration():
    """Anti-drift: the receipt ledger + write-deny triggers that init_db installs
    are structurally identical to what the governed cut-over migration installs."""
    repo_root = pathlib.Path(agent.__file__).resolve().parents[1]
    mig_path = repo_root / "scripts" / "migrate_copy_register_v2_only.py"
    spec = importlib.util.spec_from_file_location("_d1_parity_migration", mig_path)
    mig = importlib.util.module_from_spec(spec)
    import sys as _sys
    _sys.modules[spec.name] = mig  # dataclasses resolves annotations via sys.modules
    spec.loader.exec_module(mig)

    def _dump(build) -> dict:
        conn = sqlite3.connect(":memory:")
        for store in SHELLS:  # triggers need their target tables to exist
            conn.execute(f"CREATE TABLE {store} (x)")
        build(conn)
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type IN ('table','trigger') AND name NOT LIKE 'sqlite_%' AND name != ?",
            (SHELLS[0],),
        ).fetchall()
        out = {
            n: _norm(s)
            for (n, s) in rows
            if n in RECEIPTS or n in TRIGGERS
        }
        conn.close()
        return out

    def _ledger(conn):
        conn.executescript(legacy_copy_ledger.RECEIPT_LEDGER_SCHEMA_SQL)
        conn.executescript(legacy_copy_ledger.write_deny_trigger_script())

    def _migration(conn):
        mig._create_receipt_schema(conn)
        mig._install_write_denial_triggers(conn)

    ledger = _dump(_ledger)
    migration = _dump(_migration)
    assert set(ledger) == set(RECEIPTS) | set(TRIGGERS)
    assert ledger == migration
