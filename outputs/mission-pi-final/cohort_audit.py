#!/usr/bin/env python
"""PI-FINAL Phase 9: cohort-wide fail-closed audit across all canonical products.

Read-only. Checks for every canonical real product: current accepted snapshot, copy-critical
field presence, claim gate, unresolved review, generic/placeholder text, invalid provenance
status, copy eligibility, lifecycle consistency. Already-accepted products are only REPORTED
here; they are reopened only on a proven concrete defect.
"""
from __future__ import annotations
import asyncio, json, re, sqlite3, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
DB = REPO / "flow_agent.db"
OUT = Path(__file__).resolve().parent

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

PLACEHOLDER = re.compile(r"^\s*(n/?a|none|nil|-{1,2}|tbd|unknown|not available|tiada)\s*$", re.I)
GENERIC = ("lorem ipsum", "placeholder", "todo", "xxx", "sample text", "generic product")
COPY_CRITICAL = ("product_description", "benefits_json", "usp_json", "target_customer_text",
                 "allowed_claims_json", "buyer_persona_snapshot_json",
                 "copy_strategy_summary_json", "claim_gate", "claim_risk_level")


def ne(v):
    return v is not None and str(v).strip() not in ("", "[]", "{}", "null")


async def main() -> int:
    from agent.services.copy_eligibility_service import copy_eligibility
    from agent.db import schema as _schema

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    defects: list[dict] = []
    stats = {"products": 0, "active": 0, "archived": 0, "eligible_active": 0,
             "pi_complete_archived": 0}
    for p in con.execute(f"SELECT p.* FROM product p WHERE {REAL} ORDER BY p.id"):
        pid = p["id"]; stats["products"] += 1
        lifecycle = p["lifecycle_status"] or "ACTIVE"
        stats["active" if lifecycle == "ACTIVE" else "archived"] += 1
        s = con.execute(
            "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
            "ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
        if not s:
            defects.append({"product_id": pid, "defect": "NO_ACCEPTED_SNAPSHOT", "lifecycle": lifecycle})
            continue
        missing = [f for f in COPY_CRITICAL if not ne(s[f])]
        if missing:
            defects.append({"product_id": pid, "defect": "MISSING_COPY_CRITICAL",
                            "fields": missing, "lifecycle": lifecycle})
        gate = str(s["claim_gate"] or "").upper()
        if gate == "CLAIM_BLOCKED":
            defects.append({"product_id": pid, "defect": "CLAIM_BLOCKED_LATEST", "lifecycle": lifecycle})
        blob = " ".join(str(s[f] or "") for f in
                        ("product_description", "usage_text", "target_customer_text",
                         "benefits_json", "usp_json"))
        low = blob.lower()
        gm = [g for g in GENERIC if g in low]
        if gm:
            defects.append({"product_id": pid, "defect": "GENERIC_TEXT", "markers": gm})
        for f in ("product_description", "usage_text", "ingredients_text", "warnings_text",
                  "target_customer_text"):
            if s[f] is not None and PLACEHOLDER.match(str(s[f])):
                defects.append({"product_id": pid, "defect": "PLACEHOLDER_VALUE", "field": f})
        # provenance status sanity on the snapshot
        bad_prov = con.execute(
            "SELECT COUNT(*) FROM product_intelligence_field_provenance WHERE snapshot_id=? "
            "AND (verification_status IS NULL OR TRIM(verification_status)='')",
            (s["snapshot_id"],)).fetchone()[0]
        if bad_prov:
            defects.append({"product_id": pid, "defect": "INVALID_PROVENANCE_STATUS", "rows": bad_prov})
        # copy eligibility truth
        rec = await copy_eligibility(pid)
        if lifecycle == "ACTIVE":
            if rec["eligible"]:
                stats["eligible_active"] += 1
            else:
                defects.append({"product_id": pid, "defect": "ACTIVE_NOT_COPY_ELIGIBLE",
                                "reasons": rec["reasons"]})
        else:
            # archived canonical products must be PI-complete but non-executable
            non_lifecycle_reasons = [r for r in rec["reasons"] if r != "NOT_ACTIVE"]
            if not non_lifecycle_reasons:
                stats["pi_complete_archived"] += 1
            else:
                defects.append({"product_id": pid, "defect": "ARCHIVED_PI_INCOMPLETE",
                                "reasons": non_lifecycle_reasons})
    await _schema.close_db()
    dup_persona = con.execute(
        "SELECT buyer_persona_snapshot_json, COUNT(*) c FROM product_intelligence_snapshot s "
        "JOIN product p ON p.id=s.product_id "
        f"WHERE s.status='APPROVED' AND {REAL} AND s.version=(SELECT MAX(version) FROM "
        "product_intelligence_snapshot s2 WHERE s2.product_id=s.product_id AND s2.status='APPROVED') "
        "GROUP BY 1 HAVING c > 25 ORDER BY c DESC LIMIT 5").fetchall()
    suspicious_personas = [{"count": r[1], "persona": str(r[0])[:120]} for r in dup_persona]
    out = {"stats": stats, "defects": defects, "defect_count": len(defects),
           "suspicious_duplicate_personas_gt25": suspicious_personas}
    (OUT / "cohort_audit.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"stats": stats, "defect_count": len(defects),
                      "defect_kinds": sorted({d['defect'] for d in defects})}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
