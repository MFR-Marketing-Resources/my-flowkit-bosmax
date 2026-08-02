#!/usr/bin/env python
"""PI-13 B-04: map ALL copy/package/batch artifacts tied to the 116 (direct + indirect) and define
the fail-close plan. These assets were produced while the products were NOT PI-complete -> they are
downstream debt: preserve rows, mark PI_INELIGIBLE, exclude from production selection, revalidate
after PI recovery. Read-only mapping."""
import sqlite3, json, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
R = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
ids = set([x["product_id"] for x in R["incomplete"]] + [x["product_id"] for x in R["review"]])
q = ",".join("?" * len(ids)); params = list(ids)

tabs = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
direct = {}
for t in tabs:
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
    if not any(k in t.lower() for k in ("copy", "caption", "angle", "hook", "package", "batch", "poster", "queue", "generation")):
        continue
    pcol = next((x for x in cols if x in ("product_id", "productId")), None)
    if pcol:
        rows = [dict(r) for r in con.execute(f"SELECT rowid,{pcol} pid FROM {t} WHERE {pcol} IN ({q})", params)]
        if rows:
            direct[t] = {"col": pcol, "count": len(rows), "sample_rowids": [r["rowid"] for r in rows[:5]]}

# indirect: copy_component via copy_set (copy_component.copy_set_id -> copy_set.id where product_id in 116)
indirect = {}
cc_cols = [c[1] for c in con.execute("PRAGMA table_info(copy_component)")]
cs_cols = [c[1] for c in con.execute("PRAGMA table_info(copy_set)")]
link = next((x for x in cc_cols if "copy_set" in x.lower() or x == "set_id"), None)
cs_id = "id" if "id" in cs_cols else None
if link and cs_id:
    n = con.execute(f"SELECT COUNT(*) FROM copy_component cc JOIN copy_set cs ON cc.{link}=cs.{cs_id} WHERE cs.product_id IN ({q})", params).fetchone()[0]
    indirect["copy_component_via_copy_set"] = {"link_col": link, "count": n}

total_direct = sum(v["count"] for v in direct.values())
out = {
    "cohort_116": len(ids),
    "direct_copy_artifacts": direct,
    "direct_total": total_direct,
    "indirect_copy_artifacts": indirect,
    "fail_close_plan": {
        "principle": "These assets were generated while PI was incomplete -> STALE. Do NOT delete.",
        "actions": [
            "1. Add/confirm a COPY_ELIGIBLE gate: a product is copy-eligible ONLY with an accepted, claim-safe PI snapshot.",
            "2. Any of the 116 is COPY_INELIGIBLE until its PI recovery is approved.",
            "3. Existing stale copy rows for the 116 are preserved but flagged (needs_revalidation) and excluded from production selection/queue.",
            "4. After a product's PI is recovered+approved, its stale copy must be revalidated/regenerated before use.",
            "5. Prove zero NEW copy rows/jobs/packages created for the 116 during remediation (baseline=%d must not grow)." % total_direct,
        ],
        "enforcement": "Phase 7: audit UI/API/bulk/batch/queue/scheduled/retry entrypoints; fail-closed; regression tests.",
    },
}
json.dump(out, open(REPO / "outputs/mission-pi12/pi13_stale_copy_map.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("direct copy artifacts for 116:", {k: v["count"] for k, v in direct.items()}, "total:", total_direct)
print("indirect:", indirect)
