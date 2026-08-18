"""Task D5 — disposable proofs for the physical-retirement migration
(scripts/retire_legacy_copy_stores.py). No canonical DB is ever touched."""

import importlib.util
import os
import pathlib
import sqlite3

import pytest

import agent  # noqa: F401
from agent.db import legacy_copy_ledger, schema

SHELLS = legacy_copy_ledger.WRITE_DENY_STORES


def _load_migration():
    path = pathlib.Path(agent.__file__).resolve().parents[1] / "scripts" / "retire_legacy_copy_stores.py"
    spec = importlib.util.spec_from_file_location("_d5_retire", path)
    mod = importlib.util.module_from_spec(spec)
    import sys as _sys
    _sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def _init_at(path, *, maintenance):
    prev = os.environ.get("COPY_LEGACY_MAINTENANCE_MODE")
    if maintenance:
        os.environ["COPY_LEGACY_MAINTENANCE_MODE"] = "1"
    else:
        os.environ.pop("COPY_LEGACY_MAINTENANCE_MODE", None)
    old = schema.DB_PATH
    schema.DB_PATH = path
    try:
        await schema.init_db()
    finally:
        schema.DB_PATH = old
        if prev is None:
            os.environ.pop("COPY_LEGACY_MAINTENANCE_MODE", None)
        else:
            os.environ["COPY_LEGACY_MAINTENANCE_MODE"] = prev


def _seed_cutover_receipt(path):
    c = sqlite3.connect(str(path))
    try:
        c.executescript(legacy_copy_ledger.RECEIPT_LEDGER_SCHEMA_SQL)
        c.execute(
            "INSERT INTO legacy_copy_migration_receipt (migration_id, migration_version, "
            "applied_at, source_database_path, backup_path, backup_sha256, before_counts_json, "
            "after_counts_json, archive_counts_json, reference_counts_json, source_schema_json, "
            "manifest_sha256, integrity_check, foreign_key_check_json) VALUES "
            "('m1','copy-register-v2-only-cutover-v1','t','p','b','s','{}','{}','{}','{}','{}','x','ok','[]')"
        )
        c.commit()
    finally:
        c.close()


async def _canonical_shape_db(tmp_path, name):
    """Build a receipt-native, empty-shell, cut-over-shaped DB (the canonical D1 shape)."""
    db = tmp_path / name
    await _init_at(db, maintenance=True)   # base creates shells + cvg->copy_set active FK
    _seed_cutover_receipt(db)
    await _init_at(db, maintenance=False)  # align repoints FKs->receipt, keeps inert shells + triggers
    return db


def _tables(path):
    c = sqlite3.connect(str(path))
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


@pytest.mark.asyncio
async def test_scenario1_cutover_shape_drops_stores(tmp_path):
    mig = _load_migration()
    db = await _canonical_shape_db(tmp_path, "s1.db")
    before = _tables(db)
    for s in SHELLS:
        assert s in before
    backup = tmp_path / "s1.bak.db"
    sha = mig.backup_database(db, backup)
    result = mig.perform_retirement(db, backup_path=backup, backup_sha256=sha)
    assert result.status == "APPLIED"
    after = _tables(db)
    for s in SHELLS:
        assert s not in after, f"{s} must be dropped"
    for r in legacy_copy_ledger.RECEIPT_LEDGER_TABLES:
        assert r in after, f"receipt {r} must be preserved"
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        # marker receipt written
        assert c.execute(
            "SELECT COUNT(*) FROM legacy_copy_migration_receipt WHERE migration_version=?",
            (legacy_copy_ledger.PHYSICAL_RETIREMENT_MIGRATION_VERSION,),
        ).fetchone()[0] == 1
    finally:
        c.close()
    assert result.provider_calls == 0 and result.credit_spend == 0


@pytest.mark.asyncio
async def test_scenario2_idempotent_already_applied(tmp_path):
    mig = _load_migration()
    db = await _canonical_shape_db(tmp_path, "s2.db")
    b1 = tmp_path / "s2a.bak.db"
    r1 = mig.perform_retirement(db, backup_path=b1, backup_sha256=mig.backup_database(db, b1))
    assert r1.status == "APPLIED"
    # second run: already retired -> no-op
    r2 = mig.perform_retirement(db, backup_path=tmp_path / "unused.db", backup_sha256="x")
    assert r2.status == "ALREADY_APPLIED"


def test_scenario3_pre_cutover_rows_fail_closed(tmp_path):
    mig = _load_migration()
    db = tmp_path / "s3.db"
    # Pre-cutover shape built directly (maintenance mode retired): a legacy store
    # with a real row and no cut-over receipt.
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE copy_set (copy_set_id TEXT PRIMARY KEY, product_id TEXT NOT NULL)")
    c.execute("INSERT INTO copy_set (copy_set_id, product_id) VALUES ('x','p')")
    c.commit()
    c.close()
    with pytest.raises(mig.RetirementError) as exc:
        mig.perform_retirement(db, backup_path=tmp_path / "s3.bak.db",
                               backup_sha256=mig.backup_database(db, tmp_path / "s3.bak.db"))
    assert "PREFLIGHT_FAILED" in str(exc.value)
    assert "ACTIVE_STORE_NOT_EMPTY" in str(exc.value)
    # row preserved
    c = sqlite3.connect(str(db))
    try:
        assert c.execute("SELECT COUNT(*) FROM copy_set").fetchone()[0] == 1
    finally:
        c.close()


@pytest.mark.asyncio
async def test_scenario5_historical_receipt_data_preserved(tmp_path):
    mig = _load_migration()
    db = await _canonical_shape_db(tmp_path, "s5.db")
    # Seed receipt-backed history: a component receipt + a review event referencing it.
    c = sqlite3.connect(str(db))
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute(
        "INSERT INTO legacy_copy_component_receipt (legacy_component_id, migration_id, product_id, "
        "row_json, row_sha256, source_schema_sha256, archived_at) VALUES "
        "('comp-1','m1','prod-1','{}', ?, ?, 't')",
        ("a" * 64, "b" * 64),
    )
    c.execute("INSERT OR IGNORE INTO product (id, raw_product_title, product_display_name, product_short_name, created_at, updated_at) VALUES ('prod-1','t','t','t','t','t')")
    c.execute(
        "INSERT INTO creative_supply_run (run_id, mission_id, roster_sha256, cohort_sha256, roster_json, "
        "angle_plan_json, target_policy_json, reviewer_id) VALUES ('run-1','m','x','y','[]','[]','{}','rv')"
    )
    c.execute(
        "INSERT INTO creative_supply_task (task_id, run_id, product_id, angle_key, angle_label, "
        "component_type, target_approved_count, requested_count, idempotency_key) VALUES "
        "('task-1','run-1','prod-1','a','A','HOOK',1,1,'idem-1')"
    )
    c.execute(
        "INSERT INTO creative_supply_review_event (event_id, run_id, task_id, component_id, product_id, "
        "angle_key, component_type, decision, reviewed_content_sha256, reasons_json, safety_json, "
        "provider_provenance_json, reviewer_id, reviewed_at) VALUES "
        "('ev-1','run-1','task-1','comp-1','prod-1','a','HOOK','APPROVED','h','[]','{}','{}','rv','t')"
    )
    c.execute("PRAGMA foreign_keys=ON")
    c.commit()
    c.close()

    backup = tmp_path / "s5.bak.db"
    result = mig.perform_retirement(db, backup_path=backup, backup_sha256=mig.backup_database(db, backup))
    assert result.status == "APPLIED"
    c = sqlite3.connect(str(db))
    try:
        # historical review event + its receipt-backed component survive with a valid FK
        assert c.execute("SELECT component_id FROM creative_supply_review_event WHERE event_id='ev-1'").fetchone()[0] == "comp-1"
        assert c.execute("SELECT COUNT(*) FROM legacy_copy_component_receipt WHERE legacy_component_id='comp-1'").fetchone()[0] == 1
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        c.close()
