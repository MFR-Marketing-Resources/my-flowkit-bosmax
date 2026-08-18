"""Fresh-schema receipt-native alignment + final physical-retirement shape.

Task D1 made new databases receipt-native. Task D5 finalizes the retirement: a
fresh / final-era database ends with the three legacy stores (copy_set,
copy_component, poster_copy_set) PHYSICALLY ABSENT, while a database cut over from
real legacy rows keeps them as empty, write-denied transitional shells until the
governed physical-retirement migration records its receipt.

init_db converges toward this shape at startup (the untouched base schema still
transiently creates the shells; the maintenance-OFF align then repoints historical
FKs to the receipt ledgers and either drops the shells (final era / retired) or
keeps them inert (transitional)). Every test drives its own disposable temp DB and
toggles COPY_LEGACY_MAINTENANCE_MODE explicitly, so none passes merely because
conftest globally enables maintenance mode.
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


def _seed_cutover_marker(path, *, retired: bool) -> None:
    """Turn a maintenance-ON-inited DB (shells present, no receipts) into a
    cut-over-shaped DB: create the receipt ledgers and insert a migration receipt
    (plain cut-over, or the physical-retirement marker)."""
    c = _conn(path)
    try:
        c.executescript(legacy_copy_ledger.RECEIPT_LEDGER_SCHEMA_SQL)
        version = (
            legacy_copy_ledger.PHYSICAL_RETIREMENT_MIGRATION_VERSION
            if retired
            else "copy-register-v2-only-cutover-v1"
        )
        c.execute(
            "INSERT INTO legacy_copy_migration_receipt (migration_id, migration_version, "
            "applied_at, source_database_path, backup_path, backup_sha256, before_counts_json, "
            "after_counts_json, archive_counts_json, reference_counts_json, source_schema_json, "
            "manifest_sha256, integrity_check, foreign_key_check_json) VALUES "
            "(?, ?, 't','p','b','s','{}','{}','{}','{}','{}','x','ok','[]')",
            (f"m-{version}", version),
        )
        c.commit()
    finally:
        c.close()


@pytest.mark.asyncio
async def test_fresh_final_init_has_no_legacy_tables(tmp_path):
    db = tmp_path / "fresh_final.db"
    await _init_at(db, maintenance=False)
    c = _conn(db)
    try:
        tabs = _tables(c)
        # The three legacy stores are physically ABSENT on a fresh final-era DB.
        for shell in SHELLS:
            assert shell not in tabs, f"legacy store {shell} must not exist on a fresh DB"
        # ...and no write-denial triggers linger (nothing to protect).
        assert not (set(TRIGGERS) & _triggers(c))
        # Receipt ledgers are native.
        for receipt in RECEIPTS:
            assert receipt in tabs, f"missing receipt ledger {receipt}"
        # Historical FKs are receipt-native and never point at an active store.
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
        assert not any(
            tgt in SHELLS for (_c, tgt, _t) in _fk_targets(c, "creative_variation_group")
        )
        assert not any(
            tgt in SHELLS for (_c, tgt, _t) in _fk_targets(c, "creative_supply_review_event")
        )
        ct_fk_cols = {r["from"] for r in c.execute('PRAGMA foreign_key_list("creative_treatment")')}
        assert "copy_set_id" not in ct_fk_cols
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        c.close()


@pytest.mark.asyncio
async def test_fresh_final_init_is_idempotent(tmp_path):
    db = tmp_path / "fresh_idem.db"
    await _init_at(db, maintenance=False)
    c = _conn(db)
    before = _schema_objects(c)
    c.close()
    await _init_at(db, maintenance=False)  # restart: base recreates shells, align re-drops
    c = _conn(db)
    try:
        assert _schema_objects(c) == before, "schema drifted on re-init"
        for shell in SHELLS:
            assert shell not in _tables(c)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


@pytest.mark.asyncio
async def test_transitional_cutover_db_keeps_inert_shells(tmp_path):
    """A DB cut over from real legacy rows (migration receipt present, no
    physical-retirement marker) keeps the empty shells inert until the governed
    physical-retirement migration runs — the safe D6 pre-migration checkpoint."""
    db = tmp_path / "transitional.db"
    await _init_at(db, maintenance=True)  # base creates shells; align skipped
    _seed_cutover_marker(db, retired=False)
    await _init_at(db, maintenance=False)  # normal runtime, not yet retired
    c = _conn(db)
    try:
        tabs = _tables(c)
        for shell in SHELLS:
            assert shell in tabs, f"transitional shell {shell} must be kept"
            assert _count(c, shell) == 0
        for name in TRIGGERS:
            assert name in _triggers(c), f"missing write-denial trigger {name}"
        assert (
            "copy_set_id", "legacy_copy_set_receipt", "legacy_copy_set_id",
        ) in _fk_targets(c, "creative_variation_group")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()


@pytest.mark.asyncio
async def test_inert_shell_writes_are_denied(tmp_path):
    db = tmp_path / "deny.db"
    await _init_at(db, maintenance=True)
    _seed_cutover_marker(db, retired=False)
    await _init_at(db, maintenance=False)  # transitional: shells present + triggers
    c = _conn(db)
    try:
        for shell in SHELLS:
            with pytest.raises(sqlite3.Error) as exc:
                c.execute(f'INSERT INTO "{shell}" DEFAULT VALUES')
            assert legacy_copy_ledger.LEGACY_COPY_STORAGE_DISABLED in str(exc.value)
            c.rollback()
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
async def test_physical_retirement_marker_drops_shells(tmp_path):
    """Once the governed physical-retirement receipt is present, init_db removes
    any shell the base schema recreates on restart (stays absent across restarts)."""
    db = tmp_path / "retired.db"
    await _init_at(db, maintenance=True)  # base creates shells
    _seed_cutover_marker(db, retired=True)  # physical-retirement marker
    await _init_at(db, maintenance=False)
    c = _conn(db)
    try:
        for shell in SHELLS:
            assert shell not in _tables(c), f"{shell} must be dropped once retired"
        # Receipts preserved.
        assert _count(c, "legacy_copy_migration_receipt") == 1
        for receipt in RECEIPTS:
            assert receipt in _tables(c)
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        c.close()


@pytest.mark.asyncio
async def test_maintenance_mode_skips_alignment_and_keeps_legacy_writable(tmp_path):
    db = tmp_path / "maintenance.db"
    await _init_at(db, maintenance=True)
    c = _conn(db)
    try:
        assert "legacy_copy_set_receipt" not in _tables(c)
        assert "trg_copy_set_v2_only_insert" not in _triggers(c)
        assert "copy_set" in _tables(c)
        assert any(
            tgt == "copy_set" for (_c, tgt, _t) in _fk_targets(c, "creative_variation_group")
        )
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
    await _init_at(db, maintenance=True)
    c = _conn(db)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute(
        "INSERT INTO copy_set (copy_set_id, product_id, created_at, updated_at) "
        "VALUES ('legacy-1','p','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    c.commit()
    c.close()
    with pytest.raises(legacy_copy_ledger.LegacyCopyCutoverRequiredError):
        await _init_at(db, maintenance=False)
    c = _conn(db)
    try:
        assert _count(c, "copy_set") == 1, "pre-cutover legacy row must be preserved"
        tabs = _tables(c)
        if "legacy_copy_set_receipt" in tabs:
            assert _count(c, "legacy_copy_set_receipt") == 0
    finally:
        c.close()


def test_receipt_and_trigger_schema_matches_governed_migration():
    repo_root = pathlib.Path(agent.__file__).resolve().parents[1]
    mig_path = repo_root / "scripts" / "migrate_copy_register_v2_only.py"
    spec = importlib.util.spec_from_file_location("_d1_parity_migration", mig_path)
    mig = importlib.util.module_from_spec(spec)
    import sys as _sys
    _sys.modules[spec.name] = mig
    spec.loader.exec_module(mig)

    def _dump(build) -> dict:
        conn = sqlite3.connect(":memory:")
        for store in SHELLS:
            conn.execute(f"CREATE TABLE {store} (x)")
        build(conn)
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type IN ('table','trigger') AND name NOT LIKE 'sqlite_%' AND name != ?",
            (SHELLS[0],),
        ).fetchall()
        out = {n: _norm(s) for (n, s) in rows if n in RECEIPTS or n in TRIGGERS}
        conn.close()
        return out

    ledger = _dump(lambda conn: (
        conn.executescript(legacy_copy_ledger.RECEIPT_LEDGER_SCHEMA_SQL),
        conn.executescript(legacy_copy_ledger.write_deny_trigger_script()),
    ))
    migration = _dump(lambda conn: (
        mig._create_receipt_schema(conn),
        mig._install_write_denial_triggers(conn),
    ))
    assert set(ledger) == set(RECEIPTS) | set(TRIGGERS)
    assert ledger == migration
