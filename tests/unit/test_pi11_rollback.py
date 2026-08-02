"""Mutation-proving tests for the hardened PI-11 PRE_PI11 rollback (owner defects 1-8), against
DISPOSABLE databases built from the REAL application schema (extracted from the live DB's
sqlite_master). Covers: semantic-field drift fails CAS, restore-status drift, rowcount guard,
whole-cohort atomicity (one failure rolls back all), idempotent rerun, legitimate-later-approval
preserved, backup SHA/integrity refusal, fixture exclusion, and product/lifecycle safety.
"""
import importlib.util
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi11rb", REPO / "scripts" / "pi11_rollback_runner.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)
PI11 = "claude-owner-delegated-pi11"


def _real_ddl():
    live = sqlite3.connect(f"file:{(REPO / 'flow_agent.db').as_posix()}?mode=ro", uri=True)
    ddl = [r[0] for r in live.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name IN "
        "('product','product_intelligence_snapshot') AND sql IS NOT NULL")]
    live.close()
    return ddl


_DDL = _real_ddl()


def _mkdb():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    for sql in _DDL:
        con.execute(sql)
    con.row_factory = sqlite3.Row
    return path, con


def _ins_product(con, pid, title="Real Product", lifecycle="ACTIVE"):
    con.execute("INSERT INTO product(id, raw_product_title, product_display_name, product_short_name, "
                "lifecycle_status) VALUES(?,?,?,?,?)", (pid, title, title, title[:40], lifecycle))


def _ins_snap(con, sid, pid, ver, status, by, **over):
    row = {"snapshot_id": sid, "product_id": pid, "version": ver, "status": status, "approved_by": by,
           "product_description": f"desc-{sid}", "readiness_status": "READY_FOR_APPROVAL",
           "completeness_score": 1.0, "created_at": "2026-08-01T00:00:00", "updated_at": "2026-08-01T00:00:00"}
    row.update(over)
    keys = ",".join(row)
    con.execute(f"INSERT INTO product_intelligence_snapshot({keys}) VALUES({','.join('?' * len(row))})",
                tuple(row.values()))


def _cols(con):
    return R.semantic_cols(con)


def _frozen(live, backup, cols, ids):
    return {pid: {**R.classify_rollback(R.snapshots(live, pid), R.snapshots(backup, pid), cols),
                  "product_id": pid} for pid in ids}


def _expect(plans):
    return dict(Counter(p["decision"] for p in plans.values())), R.cohort_digest(plans)


def _status(con, sid):
    return con.execute("SELECT status FROM product_intelligence_snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0]


def _restore_pair(desc="genuine"):
    lp, live = _mkdb()
    bp, bak = _mkdb()
    _ins_product(live, "P")
    _ins_snap(live, "s1", "P", 1, "SUPERSEDED", "Faris", product_description=desc, size_or_volume="30ml")
    _ins_snap(live, "s2", "P", 2, "APPROVED", PI11, product_description="gamed", size_or_volume=None)
    _ins_snap(bak, "s1", "P", 1, "APPROVED", "Faris", product_description=desc, size_or_volume="30ml")
    live.commit(); bak.commit()
    return (lp, live), (bp, bak)


def _cleanup(*pcs):
    for p, c in pcs:
        c.close()
        os.unlink(p)


# ── defect 7: exact restoration on the real schema ───────────────────────────────────────────
def test_exact_pre_pi11_restoration_real_schema():
    (lp, live), (bp, bak) = _restore_pair()
    try:
        cols = _cols(live)
        fz = _frozen(live, bak, cols, ["P"])
        ec, ed = _expect(fz)
        committed, ledger = R.execute_cohort(live, bak, cols, ["P"], fz, ec, ed, "t1")
        assert committed
        assert _status(live, "s1") == "APPROVED" and _status(live, "s2") == "SUPERSEDED"
    finally:
        _cleanup((lp, live), (bp, bak))


# ── defect 2/3: drift in every semantic field fails CAS ──────────────────────────────────────
@pytest.mark.parametrize("field", ["size_or_volume", "package_notes", "product_form_factor",
                                   "packaging_description", "source_urls_json", "image_evidence_json",
                                   "allowed_claims_json", "product_description"])
def test_semantic_field_drift_fails_cas(field):
    (lp, live), (bp, bak) = _restore_pair()
    try:
        cols = _cols(live)
        fz = _frozen(live, bak, cols, ["P"])
        ec, ed = _expect(fz)
        # DRIFT the field on the bad PI-11 snapshot AFTER the plan was authorized
        live.execute(f"UPDATE product_intelligence_snapshot SET {field}='DRIFTED' WHERE snapshot_id='s2'")
        live.commit()
        committed, ledger = R.execute_cohort(live, bak, cols, ["P"], fz, ec, ed, "t")
        assert not committed  # drift detected -> whole cohort rolled back
        assert _status(live, "s2") == "APPROVED" and _status(live, "s1") == "SUPERSEDED"
    finally:
        _cleanup((lp, live), (bp, bak))


# ── restore-status drift fails CAS ───────────────────────────────────────────────────────────
def test_restore_status_drift_fails_cas():
    (lp, live), (bp, bak) = _restore_pair()
    try:
        cols = _cols(live)
        fz = _frozen(live, bak, cols, ["P"])
        ec, ed = _expect(fz)
        # the pre-PI-11 snapshot is no longer SUPERSEDED as the plan expects
        live.execute("UPDATE product_intelligence_snapshot SET status='REJECTED' WHERE snapshot_id='s1'")
        live.commit()
        committed, _ = R.execute_cohort(live, bak, cols, ["P"], fz, ec, ed, "t")
        assert not committed
        assert _status(live, "s2") == "APPROVED"  # nothing applied
    finally:
        _cleanup((lp, live), (bp, bak))


# ── rowcount guard fires when the conditional precondition is not met ─────────────────────────
def test_rowcount_guard_detects_non_matching_update():
    lp, live = _mkdb()
    try:
        _ins_snap(live, "s2", "P", 2, "APPROVED", PI11)
        live.commit()
        wrong = live.execute("UPDATE product_intelligence_snapshot SET status='SUPERSEDED' "
                             "WHERE snapshot_id='s2' AND product_id='P' AND version=99 AND status='APPROVED' "
                             "AND approved_by LIKE ?", (PI11 + "%",)).rowcount
        right = live.execute("UPDATE product_intelligence_snapshot SET status='SUPERSEDED' "
                             "WHERE snapshot_id='s2' AND product_id='P' AND version=2 AND status='APPROVED' "
                             "AND approved_by LIKE ?", (PI11 + "%",)).rowcount
        assert wrong == 0 and right == 1  # execute_cohort raises on any rowcount != 1
    finally:
        live.close(); os.unlink(lp)


# ── defect 4: one failure rolls back ALL ─────────────────────────────────────────────────────
def test_whole_cohort_atomic_one_failure_rolls_back_all():
    lp, live = _mkdb(); bp, bak = _mkdb()
    try:
        for pid in ("A", "B", "C"):
            _ins_product(live, pid)
            _ins_snap(live, f"{pid}1", pid, 1, "SUPERSEDED", "Faris")
            _ins_snap(live, f"{pid}2", pid, 2, "APPROVED", PI11, product_description="gamed")
            _ins_snap(bak, f"{pid}1", pid, 1, "APPROVED", "Faris")
        live.commit(); bak.commit()
        cols = _cols(live); ids = ["A", "B", "C"]
        fz = _frozen(live, bak, cols, ids); ec, ed = _expect(fz)
        # product C drifts after authorization -> the ENTIRE cohort must roll back
        live.execute("UPDATE product_intelligence_snapshot SET product_description='X' WHERE snapshot_id='C2'")
        live.commit()
        committed, _ = R.execute_cohort(live, bak, cols, ids, fz, ec, ed, "t")
        assert not committed
        for pid in ("A", "B", "C"):  # NONE applied
            assert _status(live, f"{pid}2") == "APPROVED" and _status(live, f"{pid}1") == "SUPERSEDED"
    finally:
        _cleanup((lp, live), (bp, bak))


# ── defect 5: idempotent rerun is a clean no-op ──────────────────────────────────────────────
def test_return_to_missing_rerun_is_clean_noop():
    lp, live = _mkdb(); bp, bak = _mkdb()
    try:
        _ins_product(live, "P")
        _ins_snap(live, "s1", "P", 1, "APPROVED", PI11)  # backup has none -> RETURN_TO_MISSING
        live.commit(); bak.commit()
        cols = _cols(live); ids = ["P"]
        fz = _frozen(live, bak, cols, ids); ec, ed = _expect(fz)
        assert R.execute_cohort(live, bak, cols, ids, fz, ec, ed, "t1")[0] is True
        assert _status(live, "s1") == "SUPERSEDED"
        # rerun: reclassify -> SKIPPED_ALREADY_ROLLED_BACK, zero CONFLICT, zero writes
        fz2 = _frozen(live, bak, cols, ids)
        assert fz2["P"]["decision"] == "SKIPPED_ALREADY_ROLLED_BACK"
        ec2, ed2 = _expect(fz2)
        committed2, ledger2 = R.execute_cohort(live, bak, cols, ids, fz2, ec2, ed2, "t2")
        assert committed2 and all(r.get("cas_result") == "SKIP" for r in ledger2 if "cas_result" in r)
        assert _status(live, "s1") == "SUPERSEDED"  # unchanged
    finally:
        _cleanup((lp, live), (bp, bak))


# ── legitimate later approval preserved ──────────────────────────────────────────────────────
def test_legitimate_post_run_change_preserved():
    lp, live = _mkdb(); bp, bak = _mkdb()
    try:
        _ins_product(live, "P")
        _ins_snap(live, "s1", "P", 1, "SUPERSEDED", "Faris")
        _ins_snap(live, "s2", "P", 2, "SUPERSEDED", PI11)
        _ins_snap(live, "s3", "P", 3, "APPROVED", "later-legit")
        _ins_snap(bak, "s1", "P", 1, "APPROVED", "Faris")
        live.commit(); bak.commit()
        cols = _cols(live); ids = ["P"]
        fz = _frozen(live, bak, cols, ids)
        assert fz["P"]["decision"] == "SKIP_POST_PI11_LEGITIMATE_CHANGE"
        ec, ed = _expect(fz)
        assert R.execute_cohort(live, bak, cols, ids, fz, ec, ed, "t")[0] is True
        assert _status(live, "s3") == "APPROVED"  # preserved untouched
    finally:
        _cleanup((lp, live), (bp, bak))


# ── defect 1: backup verification refuses on SHA / integrity ─────────────────────────────────
def test_backup_sha_mismatch_refuses():
    bp, bak = _mkdb(); bak.close()
    try:
        with pytest.raises(RuntimeError, match="DB_SHA_MISMATCH"):
            R.verify_db(bp, expect_sha="0" * 64)
    finally:
        os.unlink(bp)


def test_corrupted_backup_refuses():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.write(fd, b"this is not a valid sqlite database file at all")
    os.close(fd)
    try:
        with pytest.raises(Exception):
            R.verify_db(path)  # not a DB -> integrity/open fails closed
    finally:
        os.unlink(path)


# ── fixtures excluded + product/lifecycle untouched ──────────────────────────────────────────
def test_fixtures_excluded_from_cohort():
    lp, live = _mkdb()
    try:
        _ins_product(live, "real-1", title="Real Product")
        _ins_product(live, "fix-1", title="test product")
        _ins_snap(live, "sr", "real-1", 1, "APPROVED", PI11)
        _ins_snap(live, "sf", "fix-1", 1, "APPROVED", PI11)
        live.commit()
        ids = R.cohort(live)
        assert "real-1" in ids and "fix-1" not in ids
    finally:
        live.close(); os.unlink(lp)


def test_product_row_and_lifecycle_untouched():
    (lp, live), (bp, bak) = _restore_pair()
    try:
        live.execute("UPDATE product SET lifecycle_status='ARCHIVED' WHERE id='P'")
        live.commit()
        cols = _cols(live); fz = _frozen(live, bak, cols, ["P"]); ec, ed = _expect(fz)
        R.execute_cohort(live, bak, cols, ["P"], fz, ec, ed, "t")
        assert live.execute("SELECT lifecycle_status FROM product WHERE id='P'").fetchone()[0] == "ARCHIVED"
    finally:
        _cleanup((lp, live), (bp, bak))


# ── defect 2: schema fail-closed on an unclassified column ───────────────────────────────────
def test_schema_fail_closed_on_unknown_column():
    lp, live = _mkdb()
    try:
        live.execute("ALTER TABLE product_intelligence_snapshot ADD COLUMN surprise_col TEXT")
        with pytest.raises(RuntimeError, match="SCHEMA_FAIL_CLOSED"):
            R.semantic_cols(live)
    finally:
        live.close(); os.unlink(lp)
