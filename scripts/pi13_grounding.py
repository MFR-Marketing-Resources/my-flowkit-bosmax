#!/usr/bin/env python
"""PI-13 LANE 2: acquired-evidence grounding writer (NO DeepSeek, NO fabrication).

Consumes an evidence file where every field value is either extracted from an ACQUIRED source
(the stored marketplace-listing raw_product_title / source_url) or a conservative SUPPORTED_INFERENCE
from a verified objective attribute (low-risk categories only). Writes via the product-intelligence
API: create draft -> PATCH fields + acquired provenance_items -> deterministic identity claim ->
governed absences for still-empty strict fields -> real validator -> claim gate -> approve.

Evidence file schema (list): {product_id, risk, source_url, source_type, excerpt, confidence,
  fields:{field:{value,status}}, governed_absent:[...], rationale}
status: FACT (source states it) | SUPPORTED_INFERENCE (verified attribute, low-risk only).
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-pi13-acquired-grounding"
OBJECT_FIELDS = {"buyer_persona_snapshot_json", "copy_strategy_summary_json"}
LIST_FIELDS = {"benefits_json", "usp_json"}
STRICT_ABSENT = ("ingredients_text", "warnings_text", "usage_text")


def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


def identity_claim(con, pid):
    """Reuse the PI-12 deterministic taxonomy identity claim (claim-safe, fingerprinted)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pi12r", REPO / "scripts" / "pi12_grounded_runner.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    p = dict(con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone())
    return m.identity_claim(p)


def process(con, ev):
    import sqlite3
    pid = ev["product_id"]
    # 1. reuse open draft or create
    row = con.execute("SELECT draft_id FROM product_intelligence_review_draft WHERE product_id=? "
                      "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') "
                      "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1", (pid,)).fetchone()
    if row:
        did = row[0]
    else:
        st, r = req("POST", f"/products/{pid}/intelligence/review-drafts", {})
        if st != 200:
            return {"product_id": pid, "result": "FAIL", "stage": "create", "http": st}
        did = r["draft_id"]

    # 2. PATCH fields + acquired provenance (one provenance row per set field)
    patch = {"reviewed_by": REVIEWER, "reviewer_note": ev.get("rationale", "")[:400]}
    prov = []
    ekind = {"FACT": "FACT", "SUPPORTED_INFERENCE": "INFERENCE"}
    for f, spec in ev["fields"].items():
        patch[f] = spec["value"]
        prov.append({
            "field_name": f, "declared_value": json.dumps(spec["value"], ensure_ascii=False)[:800],
            "source_type": ev.get("source_type", "EXTERNAL_EXTRACTION"),
            "source_url": ev.get("source_url"), "source_lane": "PI13_ACQUIRED_RECOVERY",
            "evidence_kind": ekind.get(spec.get("status", "FACT"), "FACT"),
            "extraction_method": "LISTING_TITLE_EXTRACTION",
            "confidence_score": ev.get("confidence", 0.7),
            "verification_status": "EXTERNALLY_EXTRACTED",
            "claim_risk_flag": ev.get("claim_risk", "LOW"),
            "reviewer_decision": "ACCEPTED", "reviewer_note": ev.get("excerpt", "")[:300],
        })
    patch["provenance_items"] = prov
    st, r = req("PATCH", f"/product-intelligence/review-drafts/{did}", patch)
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "patch", "http": st, "detail": r}

    # 3. deterministic identity claim (taxonomy identity, claim-safe)
    try:
        claim, fp = identity_claim(con, pid)
        if claim:
            req("PATCH", f"/product-intelligence/review-drafts/{did}",
                {"allowed_claims_json": [claim], "reviewed_by": REVIEWER,
                 "reviewer_note": f"PI-13 deterministic taxonomy identity claim ({fp})."})
    except Exception:
        pass

    # 4. governed absences for still-empty strict fields
    for fld in ev.get("governed_absent", STRICT_ABSENT):
        cur = con.execute(f"SELECT {fld} FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone()[0]
        if cur is None or str(cur).strip() in ("", "[]", "{}", "null"):
            req("POST", f"/product-intelligence/review-drafts/{did}/field-dispositions",
                {"field_name": fld, "disposition": "SOURCE_UNAVAILABLE", "reviewed_by": REVIEWER,
                 "reviewer_note": "PI-13: no acquired evidence for this field; governed absence."})

    # 5. validate
    st, v = req("POST", f"/product-intelligence/review-drafts/{did}/validate")
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "validate", "http": st, "detail": v}
    blockers = [b for b in (v.get("approval_blockers") or []) if str(b).startswith("MISSING_REQUIRED_FIELDS")]
    if blockers:
        return {"product_id": pid, "result": "INCOMPLETE", "reason": ";".join(blockers)}
    gate = v.get("claim_gate")
    if gate != "CLAIM_SAFE":
        return {"product_id": pid, "result": "REVIEW", "reason": gate, "tokens": v.get("claim_tokens_json")}

    # 6. approve
    st, a = req("POST", f"/product-intelligence/review-drafts/{did}/approve",
                {"approved_by": REVIEWER,
                 "approval_note": "PI-13 acquired-evidence grounding: benefits/USP from stored listing "
                                  "title (marketplace acquired) with field provenance; governed absences; "
                                  "validated CLAIM_SAFE by the real validator."})
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "approve", "http": st, "detail": a}
    return {"product_id": pid, "result": "APPROVED", "readiness": a.get("readiness_status"),
            "completeness": a.get("completeness_score")}


def main():
    import sqlite3, collections
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    a = ap.parse_args()
    evs = json.load(open(REPO / a.evidence, encoding="utf-8"))
    con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True)
    tally = collections.Counter(); rows = []
    for ev in evs:
        con.close(); con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True)
        r = process(con, ev); rows.append(r); tally[r["result"]] += 1
        print(f"  {r['product_id'][:8]} -> {r['result']} {r.get('reason') or r.get('readiness') or ''}")
    print("SUMMARY:", dict(tally))
    json.dump(rows, open(REPO / "outputs/mission-pi12/pi13_grounding_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
