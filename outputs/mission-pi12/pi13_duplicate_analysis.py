#!/usr/bin/env python
"""PI-13 exact-URL duplicate/canonical analysis for the 116 (read-only).
Groups ALL real products by exact product URL; for each debt product finds partners sharing the URL
and classifies the disposition path (copy-from-grounded / canonical-merge / genuine-research)."""
import sqlite3, json, collections
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
R = json.load(open(REPO / "outputs/mission-pi12/residual_reasons.json", encoding="utf-8"))
debt = set([x["product_id"] for x in R["incomplete"]] + [x["product_id"] for x in R["review"]])
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
REAL = frozen["real_ids"]


def pi_class(pid):
    r = con.execute("SELECT readiness_status,completeness_score FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    if not r:
        return "MISSING"
    if r["readiness_status"] == "READY_WITH_GOVERNED_ABSENCE":
        return "GA"
    if r["completeness_score"] and r["completeness_score"] >= 1.0:
        return "FC"
    return "LEGACY"


rows = {r["id"]: dict(r) for r in con.execute("SELECT id,product_display_name,source_url,tiktok_product_url FROM product WHERE id IN (%s)" % ",".join("?" * len(REAL)), REAL)}
by_src = collections.defaultdict(list); by_tt = collections.defaultdict(list)
for pid, r in rows.items():
    if r["source_url"]:
        by_src[r["source_url"]].append(pid)
    if r["tiktok_product_url"]:
        by_tt[r["tiktok_product_url"]].append(pid)

disp = collections.Counter(); detail = []
for pid in debt:
    r = rows[pid]
    partners = set()
    for idx in (by_src.get(r["source_url"], []) if r["source_url"] else []):
        partners.add(idx)
    for idx in (by_tt.get(r["tiktok_product_url"], []) if r["tiktok_product_url"] else []):
        partners.add(idx)
    partners.discard(pid)
    if not partners:
        d = "GENUINE_UNIQUE_NEEDS_RESEARCH"
    else:
        pcls = {p: pi_class(p) for p in partners}
        grounded = [p for p, cl in pcls.items() if cl in ("GA", "FC")]
        debt_partners = [p for p in partners if p in debt]
        if grounded:
            d = "COPY_FROM_GROUNDED_TWIN"
        elif debt_partners:
            d = "CANONICAL_MERGE_BOTH_DEBT"
        else:
            d = "PARTNER_LEGACY_OR_OTHER"
        detail.append({"product_id": pid, "name": (r["product_display_name"] or "")[:40],
                       "shared_url": r["source_url"] or r["tiktok_product_url"],
                       "partners": [{"id": p, "class": pcls[p], "in_debt": p in debt} for p in partners]})
    disp[d] += 1

print("=== disposition distribution for 116 (exact-URL based) ===")
for k, v in disp.most_common():
    print("  %3d  %s" % (v, k))
print("\ntotal:", sum(disp.values()))
grounded_twin = [d for d in detail if any(p["class"] in ("GA", "FC") for p in d["partners"])]
print("\n=== COPY_FROM_GROUNDED_TWIN candidates (recover w/o research) ===", len(grounded_twin))
for d in grounded_twin[:40]:
    tw = [p for p in d["partners"] if p["class"] in ("GA", "FC")]
    print("  %s %-38s <- twin %s [%s]" % (d["product_id"][:8], d["name"], tw[0]["id"][:8], tw[0]["class"]))
out = {"disposition_distribution": dict(disp), "collision_detail": detail,
       "copy_from_grounded_twin_ids": [d["product_id"] for d in grounded_twin]}
json.dump(out, open(REPO / "outputs/mission-pi12/pi13_duplicate_analysis.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("\nwrote pi13_duplicate_analysis.json")
