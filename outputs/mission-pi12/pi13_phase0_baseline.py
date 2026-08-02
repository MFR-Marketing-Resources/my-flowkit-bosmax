#!/usr/bin/env python
"""PI-13 Phase 0 baseline capture (read-only). Emits pi13_phase0_baseline.json."""
import sqlite3, json, hashlib, subprocess, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "flow_agent.db"


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def product_table_hash(dbpath):
    c = sqlite3.connect(f"file:{Path(dbpath).as_posix()}?mode=ro", uri=True)
    rows = c.execute("SELECT * FROM product ORDER BY id").fetchall(); c.close()
    h = hashlib.sha256()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8", "replace"))
    return h.hexdigest()


con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
REAL = frozen["real_ids"]


def cls(rd, comp):
    if rd == "READY_WITH_GOVERNED_ABSENCE":
        return "APPROVED_WITH_GOVERNED_ABSENCE"
    if comp is not None and comp >= 1.0:
        return "FULLY_COMPLETE"
    return "LEGACY_APPROVED_INCOMPLETE"


pq = collections.Counter()
for pid in REAL:
    r = con.execute("SELECT readiness_status,completeness_score FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    pq[cls(r["readiness_status"], r["completeness_score"]) if r else "MISSING_APPROVED_INTELLIGENCE"] += 1

R = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
ids116 = [x["product_id"] for x in R["incomplete"]] + [x["product_id"] for x in R["review"]]

# copywriting job/row counts for the 116 (product-id-keyed copy tables)
copy_counts = {}
for t in ("copy_set", "copy_component", "batch_variant", "workspace_execution_package",
          "workspace_generation_package", "poster_copy_set", "copy_generation_batch", "batch"):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
    pcol = next((x for x in cols if x in ("product_id", "productId")), None)
    if not pcol:
        continue
    q = ",".join("?" * len(ids116))
    copy_counts[t] = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {pcol} IN ({q})", ids116).fetchone()[0]

out = {
    "captured_git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
    "origin_main": subprocess.run(["git", "rev-parse", "origin/main"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
    "branch": subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
    "db_path": str(DB),
    "db_sha256": sha_file(DB),
    "product_table_hash": product_table_hash(DB),
    "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
    "foreign_key_check": len(con.execute("PRAGMA foreign_key_check").fetchall()),
    "pi_quality": dict(pq),
    "pi_quality_total": sum(pq.values()),
    "residual_116": {"total": len(ids116), "unique": len(set(ids116)),
                     "incomplete": len(R["incomplete"]), "claim": len(R["review"]),
                     "all_resolve_to_db": all(con.execute("SELECT 1 FROM product WHERE id=?", (x,)).fetchone() for x in ids116)},
    "copywriting_rows_for_116": copy_counts,
    "copywriting_rows_for_116_total": sum(copy_counts.values()),
}
con.close()
json.dump(out, open(REPO / "outputs/mission-pi12/pi13_phase0_baseline.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("branch", "captured_git_head", "origin_main", "db_sha256", "product_table_hash",
                                      "integrity_check", "foreign_key_check", "pi_quality", "residual_116",
                                      "copywriting_rows_for_116_total")}, indent=1))
