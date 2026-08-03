#!/usr/bin/env python
"""PI-13 C3: canonical merge / alias lane (NO deletion).

For each MERGE_PROVEN duplicate (same globally-unique platform product id as a grounded canonical),
transition the duplicate to lifecycle_status='MERGED' with a full alias/tombstone provenance event
(canonical_product_id, platform id, reason, downstream ref counts). The row + its own PI history are
preserved (audit). Downstream copy/package refs are recorded and left with the alias, which the
COPY_ELIGIBLE gate (C5) marks ineligible — they are NOT migrated onto the canonical (they are stale).
Reporting (separately patched) excludes MERGED from the real-product cohort and the debt classes.

Usage:
  python scripts/pi13_canonical_merge.py --dry-run           # report, no writes
  python scripts/pi13_canonical_merge.py --ids a,b --apply   # merge specific duplicates
  python scripts/pi13_canonical_merge.py --apply             # merge all MERGE_PROVEN
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "flow_agent.db"
MC = json.load(open(REPO / "outputs/mission-pi12/pi13_merge_candidates.json", encoding="utf-8"))
MERGED = "MERGED"
ACTOR = "claude-pi13-canonical-merge"
# downstream consumer tables to COUNT for audit (never migrated; stale, C5 marks ineligible)
DOWNSTREAM = ("copy_set", "copy_component", "poster_copy_set", "workspace_execution_package",
              "workspace_generation_package", "batch", "batch_variant", "copy_generation_batch")
# the alias keeps its own PI history — never touch these:
PI_OWNED = ("product_intelligence_snapshot", "product_intelligence_review_draft",
            "product_intelligence_review_field_provenance", "product_intelligence_field_provenance")


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def downstream_refs(con, pid):
    out = {}
    for t in DOWNSTREAM:
        cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
        pcol = next((x for x in cols if x in ("product_id", "productId")), None)
        if not pcol:
            continue
        n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {pcol}=?", (pid,)).fetchone()[0]
        if n:
            out[t] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ids", default="")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        print("specify --dry-run or --apply"); sys.exit(2)

    pairs = MC["merge_proven"]
    if a.ids:
        want = {x.strip() for x in a.ids.split(",") if x.strip()}
        pairs = [p for p in pairs if p["product_id"] in want]
    con = sqlite3.connect(str(DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    results = []
    for p in pairs:
        dup, can = p["product_id"], p["canonical_id"]
        drow = con.execute("SELECT id,lifecycle_status,archived_reason,lifecycle_provenance,updated_at,source FROM product WHERE id=?", (dup,)).fetchone()
        crow = con.execute("SELECT id,lifecycle_status FROM product WHERE id=?", (can,)).fetchone()
        if not drow or not crow:
            results.append({"duplicate": dup, "result": "SKIP_NOT_FOUND"}); continue
        if str(drow["archived_reason"] or "").upper().startswith("DUPLICATE_MERGED_TO_CANONICAL"):
            results.append({"duplicate": dup, "result": "ALREADY_MERGED"}); continue
        refs = downstream_refs(con, dup)
        event = {"timestamp": utcnow(), "action": "MERGE_TO_CANONICAL", "actor": ACTOR,
                 "from_status": str(drow["lifecycle_status"] or "ACTIVE").upper(), "to_status": MERGED,
                 "canonical_product_id": can, "platform_product_id": p["signals"].get("platform_product_id"),
                 "reason": "exact duplicate import (same platform product id + matching title/variant); "
                           "structural dedup only — canonical PI still requires its own evidence revalidation",
                 "downstream_refs_left_with_alias": refs, "source": str(drow["source"] or "")}
        if a.dry_run:
            results.append({"duplicate": dup, "canonical": can, "result": "WOULD_MERGE", "downstream_refs": refs})
            continue
        prov = json.loads(drow["lifecycle_provenance"]) if drow["lifecycle_provenance"] and str(drow["lifecycle_provenance"]).strip().startswith("[") else []
        prov.append(event)
        con.execute("BEGIN IMMEDIATE")
        # schema CHECK allows only ACTIVE/ARCHIVED; the merge is an ARCHIVED state with a
        # distinctive archived_reason marker that reporting excludes from real/debt.
        con.execute("UPDATE product SET lifecycle_status='ARCHIVED', archived_at=?, archived_reason=?, archived_by=?, "
                    "lifecycle_provenance=?, updated_at=? WHERE id=?",
                    (utcnow(), f"DUPLICATE_MERGED_TO_CANONICAL:{can}", ACTOR,
                     json.dumps(prov, ensure_ascii=True), utcnow(), dup))
        con.commit()
        results.append({"duplicate": dup, "canonical": can, "result": "MERGED", "downstream_refs": refs})
    # reconcile
    frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
    real = frozen["real_ids"]
    q = ",".join("?" * len(real))
    merged_now = con.execute(f"SELECT COUNT(*) FROM product WHERE id IN ({q}) AND UPPER(COALESCE(archived_reason,'')) LIKE 'DUPLICATE_MERGED_TO_CANONICAL%'", real).fetchone()[0]
    con.close()
    from collections import Counter
    tally = Counter(r["result"] for r in results)
    print(json.dumps({"mode": "dry-run" if a.dry_run else "apply", "pairs": len(pairs),
                      "tally": dict(tally), "merged_in_cohort_now": merged_now,
                      "active_canonical_real": len(real) - merged_now}, indent=1))
    for r in results[:60]:
        print("  ", r["duplicate"][:8], "->", r.get("canonical", "")[:8], r["result"], r.get("downstream_refs", ""))


if __name__ == "__main__":
    main()
