#!/usr/bin/env python
"""PI-13 B-03 (corrected): consistent logical backup via VACUUM INTO + a real logical restore test
(open the restored DB, PRAGMA integrity_check + foreign_key_check, verify product/residual counts,
product-table hash, WAL-free). Updates pi13_backup_manifest.json. Read-only w.r.t. the live DB."""
import sqlite3, json, hashlib, os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "flow_agent.db"
OUT = REPO / ".ai" / "backups" / "flow_agent_PRE_PI13_LOGICAL.db"
OUT.parent.mkdir(parents=True, exist_ok=True)
if OUT.exists():
    OUT.unlink()


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def ptable_hash(dbpath):
    c = sqlite3.connect(f"file:{Path(dbpath).as_posix()}?mode=ro", uri=True)
    rows = c.execute("SELECT * FROM product ORDER BY id").fetchall(); c.close()
    h = hashlib.sha256()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8", "replace"))
    return h.hexdigest()


# 1) consistent backup via VACUUM INTO (reads live, writes a clean standalone file, no WAL)
src = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True)
src.execute("VACUUM INTO ?", (str(OUT),))
src.close()

# 2) logical restore test on the produced file
r = sqlite3.connect(f"file:{OUT.as_posix()}?mode=ro", uri=True); r.row_factory = sqlite3.Row
integrity = r.execute("PRAGMA integrity_check").fetchone()[0]
fk = len(r.execute("PRAGMA foreign_key_check").fetchall())
jmode = r.execute("PRAGMA journal_mode").fetchone()[0]
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
REAL = frozen["real_ids"]
n_products = r.execute("SELECT COUNT(*) FROM product").fetchone()[0]
n_real_present = r.execute("SELECT COUNT(*) FROM product WHERE id IN (%s)" % ",".join("?" * len(REAL)), REAL).fetchone()[0]
Rj = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
ids116 = [x["product_id"] for x in Rj["incomplete"]] + [x["product_id"] for x in Rj["review"]]
n_residual = r.execute("SELECT COUNT(*) FROM product WHERE id IN (%s)" % ",".join("?" * len(ids116)), ids116).fetchone()[0]
n_snap = r.execute("SELECT COUNT(*) FROM product_intelligence_snapshot WHERE status='APPROVED'").fetchone()[0]
restored_ptable = ptable_hash(OUT)
r.close()

live_ptable = ptable_hash(LIVE)
manifest = json.load(open(REPO / "outputs/mission-pi12/pi13_backup_manifest.json", encoding="utf-8"))
logical = {
    "logical_backup_path": str(OUT),
    "logical_backup_method": "VACUUM INTO (consistent, standalone, no WAL)",
    "logical_backup_sha256": sha(OUT),
    "logical_backup_size_bytes": os.stat(OUT).st_size,
    "restore_test": {
        "integrity_check": integrity,
        "foreign_key_check": fk,
        "journal_mode": jmode,
        "product_count": n_products,
        "real_ids_present": f"{n_real_present}/{len(REAL)}",
        "residual_116_present": f"{n_residual}/{len(ids116)}",
        "approved_snapshots": n_snap,
        "restored_product_table_hash": restored_ptable,
        "matches_live_product_table_hash": restored_ptable == live_ptable,
        "PASS": integrity == "ok" and fk == 0 and n_real_present == len(REAL) and n_residual == len(ids116) and restored_ptable == live_ptable,
    },
}
manifest["logical_backup"] = logical
json.dump(manifest, open(REPO / "outputs/mission-pi12/pi13_backup_manifest.json", "w", encoding="utf-8"), indent=1)
print(json.dumps(logical, indent=1))
