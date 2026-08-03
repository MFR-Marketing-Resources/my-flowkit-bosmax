#!/usr/bin/env python
"""PI-FINAL Phase 0: live baseline capture + NEW current-state logical backup + restore test.

Read-only against the canonical flow_agent.db except for `VACUUM INTO` (which only reads the
source). Replicates the EXACT reporting_service predicates so the baseline reconciles 1:1 with
GET /api/reporting/pi-quality.
"""
from __future__ import annotations
import hashlib, json, shutil, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "flow_agent.db"
OUT = REPO / "outputs" / "mission-pi-final"
OUT.mkdir(parents=True, exist_ok=True)
TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

# ── exact SQL mirrors of agent/services/reporting_service.py ──────────────────
HAS_APPROVED = ("EXISTS (SELECT 1 FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED')")
LATEST_READY = ("(SELECT s2.readiness_status FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED' "
                "ORDER BY s2.version DESC LIMIT 1)")
LATEST_COMPL = ("(SELECT s2.completeness_score FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED' "
                "ORDER BY s2.version DESC LIMIT 1)")
CLASSES = {
    "MISSING_APPROVED_INTELLIGENCE": f"NOT {HAS_APPROVED}",
    "APPROVED_WITH_GOVERNED_ABSENCE": (f"({HAS_APPROVED} AND {LATEST_READY} = 'READY_WITH_GOVERNED_ABSENCE')"),
    "FULLY_COMPLETE": (f"({HAS_APPROVED} AND COALESCE({LATEST_READY},'') <> 'READY_WITH_GOVERNED_ABSENCE' "
                       f"AND COALESCE({LATEST_COMPL},0) >= 1.0)"),
    "LEGACY_APPROVED_INCOMPLETE": (f"({HAS_APPROVED} AND COALESCE({LATEST_READY},'') <> 'READY_WITH_GOVERNED_ABSENCE' "
                                   f"AND COALESCE({LATEST_COMPL},0) < 1.0)"),
}
FIXTURE = ("(LOWER(TRIM(COALESCE(p.raw_product_title,''))) IN ('test product','test item','fixture product')"
           " OR LOWER(TRIM(COALESCE(p.product_short_name,''))) IN ('test product','test item','fixture product')"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'test product%'"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'smoke %'"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke approve%'"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke reject%'"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE '%smoke claim review%'"
           " OR LOWER(COALESCE(p.raw_product_title,'')) LIKE 'codex pi %verification%'"
           " OR LOWER(COALESCE(p.id,'')) LIKE 'test|_%' ESCAPE '|'"
           " OR LOWER(COALESCE(p.id,'')) LIKE 'fixture|_%' ESCAPE '|')")
ALIAS = "UPPER(COALESCE(p.archived_reason,'')) LIKE 'DUPLICATE_MERGED_TO_CANONICAL%'"
REAL = f"NOT {FIXTURE} AND NOT {ALIAS}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_hash(con: sqlite3.Connection, table: str, order: str = "1") -> str:
    h = hashlib.sha256()
    for row in con.execute(f"SELECT * FROM {table} ORDER BY {order}"):
        h.update(json.dumps([str(x) for x in row], ensure_ascii=False).encode())
    return h.hexdigest()


def capture(con: sqlite3.Connection) -> dict:
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    s = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    base: dict = {"captured": TS, "db_path": str(DB)}
    base["physical_rows"] = s("SELECT COUNT(*) FROM product p")
    base["test_fixtures"] = s(f"SELECT COUNT(*) FROM product p WHERE {FIXTURE}")
    base["merged_aliases"] = s(f"SELECT COUNT(*) FROM product p WHERE {ALIAS}")
    base["canonical_real"] = s(f"SELECT COUNT(*) FROM product p WHERE {REAL}")
    base["lifecycle"] = {r[0]: r[1] for r in q(
        f"SELECT COALESCE(p.lifecycle_status,'NULL'), COUNT(*) FROM product p WHERE {REAL} GROUP BY 1")}
    base["classes"] = {}
    for name, pred in CLASSES.items():
        rows = q(f"SELECT COALESCE(p.lifecycle_status,'NULL'), COUNT(*) FROM product p "
                 f"WHERE {REAL} AND {pred} GROUP BY 1")
        base["classes"][name] = {"total": sum(r[1] for r in rows), "by_lifecycle": {r[0]: r[1] for r in rows}}
    # residual IDs
    for name in ("LEGACY_APPROVED_INCOMPLETE", "MISSING_APPROVED_INTELLIGENCE"):
        base[f"ids_{name}"] = [r[0] for r in q(
            f"SELECT p.id FROM product p WHERE {REAL} AND {CLASSES[name]} ORDER BY p.id")]
    base["draft_status_dist"] = {r[0]: r[1] for r in q(
        "SELECT review_status, COUNT(*) FROM product_intelligence_review_draft GROUP BY 1")}
    base["open_drafts"] = [dict(zip(("draft_id", "product_id", "review_status", "created_by"), r)) for r in q(
        "SELECT draft_id, product_id, review_status, created_by FROM product_intelligence_review_draft "
        "WHERE review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED')")]
    base["snapshot_status_dist"] = {r[0]: r[1] for r in q(
        "SELECT status, COUNT(*) FROM product_intelligence_snapshot GROUP BY 1")}
    base["snapshot_claim_gate_latest_approved"] = {str(r[0]): r[1] for r in q(
        "SELECT claim_gate, COUNT(*) FROM product_intelligence_snapshot s WHERE s.status='APPROVED' "
        "AND s.version = (SELECT MAX(version) FROM product_intelligence_snapshot s3 "
        "WHERE s3.product_id=s.product_id AND s3.status='APPROVED') GROUP BY 1")}
    base["draft_claim_gate_open"] = {str(r[0]): r[1] for r in q(
        "SELECT claim_gate, COUNT(*) FROM product_intelligence_review_draft "
        "WHERE review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') GROUP BY 1")}
    # copy assets tied to residual (ineligible) products
    residual = set(base["ids_LEGACY_APPROVED_INCOMPLETE"]) | set(base["ids_MISSING_APPROVED_INTELLIGENCE"])
    marks = ",".join("?" * len(residual))
    if residual:
        base["copy_sets_on_residual"] = s(
            f"SELECT COUNT(*) FROM copy_set WHERE product_id IN ({marks})", *residual)
    else:
        base["copy_sets_on_residual"] = 0
    base["copy_set_total"] = s("SELECT COUNT(*) FROM copy_set")
    base["hashes"] = {
        "product": table_hash(con, "product", "p.id" if False else "id"),
        "product_intelligence_snapshot": table_hash(con, "product_intelligence_snapshot", "snapshot_id"),
        "product_intelligence_review_draft": table_hash(con, "product_intelligence_review_draft", "draft_id"),
    }
    base["table_counts"] = {t: s(f"SELECT COUNT(*) FROM {t}") for t in (
        "product", "product_intelligence_snapshot", "product_intelligence_review_draft",
        "product_intelligence_review_field_provenance", "product_intelligence_field_provenance", "copy_set")}
    return base


def main() -> int:
    free = shutil.disk_usage(DB.parent).free
    src_size = DB.stat().st_size
    if free < src_size * 2:
        print(f"FATAL: insufficient disk: free={free} need~{src_size*2}"); return 2

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    baseline = capture(con)

    backup_dir = REPO / ".ai" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"flow_agent_PRE_PIFINAL_{TS}.db"
    con.execute("VACUUM INTO ?", (backup.as_posix(),))
    con.close()

    bcon = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    integrity = bcon.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(bcon.execute("PRAGMA foreign_key_check").fetchall())
    bl2 = capture(bcon)
    bcon.close()

    restore_test = {
        "integrity_check": integrity,
        "foreign_key_check_violations": fk,
        "physical_rows_match": bl2["physical_rows"] == baseline["physical_rows"],
        "canonical_real_match": bl2["canonical_real"] == baseline["canonical_real"],
        "alias_match": bl2["merged_aliases"] == baseline["merged_aliases"],
        "residual_ids_match": (bl2["ids_LEGACY_APPROVED_INCOMPLETE"] == baseline["ids_LEGACY_APPROVED_INCOMPLETE"]
                               and bl2["ids_MISSING_APPROVED_INTELLIGENCE"] == baseline["ids_MISSING_APPROVED_INTELLIGENCE"]),
        "product_hash_match": bl2["hashes"]["product"] == baseline["hashes"]["product"],
    }
    manifest = {
        "live_db": {"path": str(DB), "size": src_size},
        "backup": {"path": str(backup), "size": backup.stat().st_size, "sha256": sha256_file(backup)},
        "timestamp": TS,
        "method": "sqlite VACUUM INTO (logical snapshot of committed state)",
        "restore_method": "stop runtime; copy backup over flow_agent.db (delete -wal/-shm); restart runtime",
        "restore_test": restore_test,
    }
    (OUT / "phase0_baseline.json").write_text(json.dumps(baseline, indent=1), encoding="utf-8")
    (OUT / "rollback_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    ok = integrity == "ok" and fk == 0 and all(v is True for k, v in restore_test.items() if k.endswith("_match"))
    print(json.dumps({"baseline_summary": {k: baseline[k] for k in (
        "physical_rows", "test_fixtures", "merged_aliases", "canonical_real")},
        "classes": {k: v["total"] for k, v in baseline["classes"].items()},
        "restore_test": restore_test, "backup": manifest["backup"], "OK": ok}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
