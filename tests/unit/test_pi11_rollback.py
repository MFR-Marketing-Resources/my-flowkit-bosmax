"""Mutation-proving tests for the PI-11 PRE_PI11 rollback, against disposable real SQLite copies
(temp live + backup DBs). Proves exact restoration, return-to-missing, skip of legitimate post-run
changes, CAS fail-closed (no partial state), idempotence, fixture exclusion, and lifecycle safety.
"""
import importlib.util
import os
import sqlite3
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("pi11rb", REPO / "scripts" / "pi11_rollback_runner.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

PI11 = "claude-owner-delegated-pi11"
_SCHEMA = """
CREATE TABLE product(id TEXT PRIMARY KEY, raw_product_title TEXT, lifecycle_status TEXT);
CREATE TABLE product_intelligence_snapshot(
  snapshot_id TEXT PRIMARY KEY, product_id TEXT, version INTEGER, status TEXT, approved_by TEXT,
  product_description TEXT, readiness_status TEXT, completeness_score REAL,
  created_at TEXT, updated_at TEXT);
"""


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript(_SCHEMA)
    con.row_factory = sqlite3.Row
    return path, con


def _snap(con, sid, pid, ver, status, by, desc="content"):
    con.execute("INSERT INTO product_intelligence_snapshot(snapshot_id,product_id,version,status,approved_by,"
                "product_description,readiness_status,completeness_score) VALUES(?,?,?,?,?,?,?,?)",
                (sid, pid, ver, status, by, desc, "READY_FOR_APPROVAL", 1.0))


def _status(con, sid):
    return con.execute("SELECT status FROM product_intelligence_snapshot WHERE snapshot_id=?", (sid,)).fetchone()[0]


def _pair():
    lp, live = _db()
    bp, bak = _db()
    return (lp, live), (bp, bak)


def _cleanup(*paths_cons):
    for p, c in paths_cons:
        c.close()
        os.unlink(p)


def test_exact_pre_pi11_snapshot_restoration():
    (lp, live), (bp, bak) = _pair()
    try:
        _snap(live, "s1", "P", 1, "SUPERSEDED", "Faris", "genuine legacy")
        _snap(live, "s2", "P", 2, "APPROVED", PI11, "gamed generic")
        _snap(bak, "s1", "P", 1, "APPROVED", "Faris", "genuine legacy")
        live.commit(); bak.commit()
        res = R.apply_one_rollback(live, bak, "P")
        assert res["result"] == "RESTORE_PRE_PI11"
        assert _status(live, "s1") == "APPROVED"      # pre-PI11 restored to authoritative
        assert _status(live, "s2") == "SUPERSEDED"    # bad PI-11 retracted, retained as history
    finally:
        _cleanup((lp, live), (bp, bak))


def test_no_prior_product_returns_to_missing():
    (lp, live), (bp, bak) = _pair()
    try:
        _snap(live, "s1", "P", 1, "APPROVED", PI11, "gamed generic")
        live.commit(); bak.commit()  # backup has NO snapshot for P
        res = R.apply_one_rollback(live, bak, "P")
        assert res["result"] == "RETURN_TO_MISSING"
        assert _status(live, "s1") == "SUPERSEDED"
        approved = live.execute("SELECT COUNT(*) FROM product_intelligence_snapshot WHERE product_id='P' "
                                "AND status='APPROVED'").fetchone()[0]
        assert approved == 0  # product truthfully returns to MISSING_APPROVED_INTELLIGENCE
    finally:
        _cleanup((lp, live), (bp, bak))


def test_legitimate_post_run_change_is_preserved():
    (lp, live), (bp, bak) = _pair()
    try:
        _snap(live, "s1", "P", 1, "SUPERSEDED", "Faris")
        _snap(live, "s2", "P", 2, "SUPERSEDED", PI11)
        _snap(live, "s3", "P", 3, "APPROVED", "later-legit-reviewer")  # authoritative AFTER the bad run
        _snap(bak, "s1", "P", 1, "APPROVED", "Faris")
        live.commit(); bak.commit()
        res = R.apply_one_rollback(live, bak, "P")
        assert res["result"] == "SKIP_POST_PI11_LEGITIMATE_CHANGE"
        assert _status(live, "s3") == "APPROVED"  # preserved untouched
    finally:
        _cleanup((lp, live), (bp, bak))


def test_cas_mismatch_fails_closed_no_partial():
    (lp, live), (bp, bak) = _pair()
    try:
        _snap(live, "s1", "P", 1, "SUPERSEDED", "Faris", "genuine")
        _snap(live, "s2", "P", 2, "APPROVED", PI11, "gamed")
        _snap(bak, "s1", "P", 1, "APPROVED", "Faris", "genuine")
        live.commit(); bak.commit()
        plan = R.classify_rollback(R.snapshots(live, "P"), R.snapshots(bak, "P"))
        # DRIFT: the bad snapshot's content changes after the plan was computed
        live.execute("UPDATE product_intelligence_snapshot SET product_description='drifted' WHERE snapshot_id='s2'")
        live.commit()
        res = R.apply_one_rollback(live, bak, "P", plan=plan)
        assert res["result"] == "CONFLICT"
        # no partial state: statuses unchanged from before apply
        assert _status(live, "s2") == "APPROVED"
        assert _status(live, "s1") == "SUPERSEDED"
    finally:
        _cleanup((lp, live), (bp, bak))


def test_rollback_is_idempotent():
    (lp, live), (bp, bak) = _pair()
    try:
        _snap(live, "s1", "P", 1, "SUPERSEDED", "Faris", "genuine")
        _snap(live, "s2", "P", 2, "APPROVED", PI11, "gamed")
        _snap(bak, "s1", "P", 1, "APPROVED", "Faris", "genuine")
        live.commit(); bak.commit()
        assert R.apply_one_rollback(live, bak, "P")["result"] == "RESTORE_PRE_PI11"
        # rerun: authoritative is now the non-PI11 s1 -> SKIP, no further change
        res2 = R.apply_one_rollback(live, bak, "P")
        assert res2["result"] == "SKIP_POST_PI11_LEGITIMATE_CHANGE"
        assert _status(live, "s1") == "APPROVED" and _status(live, "s2") == "SUPERSEDED"
    finally:
        _cleanup((lp, live), (bp, bak))


def test_fixtures_excluded_from_cohort():
    lp, live = _db()
    try:
        live.execute("INSERT INTO product(id,raw_product_title) VALUES('real-1','Real Product')")
        live.execute("INSERT INTO product(id,raw_product_title) VALUES('fix-1','test product')")
        _snap(live, "sr", "real-1", 1, "APPROVED", PI11)
        _snap(live, "sf", "fix-1", 1, "APPROVED", PI11)
        live.commit()
        ids = R.cohort(live)
        assert "real-1" in ids and "fix-1" not in ids  # fixture excluded
    finally:
        live.close(); os.unlink(lp)


def test_lifecycle_and_product_row_untouched():
    (lp, live), (bp, bak) = _pair()
    try:
        live.execute("INSERT INTO product(id,raw_product_title,lifecycle_status) VALUES('P','X','ARCHIVED')")
        _snap(live, "s1", "P", 1, "SUPERSEDED", "Faris", "genuine")
        _snap(live, "s2", "P", 2, "APPROVED", PI11, "gamed")
        _snap(bak, "s1", "P", 1, "APPROVED", "Faris", "genuine")
        live.commit(); bak.commit()
        R.apply_one_rollback(live, bak, "P")
        life = live.execute("SELECT lifecycle_status FROM product WHERE id='P'").fetchone()[0]
        assert life == "ARCHIVED"  # product/lifecycle never written by status-only rollback
    finally:
        _cleanup((lp, live), (bp, bak))
