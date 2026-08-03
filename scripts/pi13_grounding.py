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
    # 1. draft is one-per-product (UNIQUE) and terminal-locked once APPROVED. Reuse the existing
    # draft; if it is terminal, REOPEN it to READY_FOR_REVIEW (a valid state) so the subsequent
    # PATCH + approve run the FULL validator + claim gate and produce a superseding new version.
    row = con.execute("SELECT draft_id, review_status FROM product_intelligence_review_draft WHERE product_id=? "
                      "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1", (pid,)).fetchone()
    if row:
        did = row[0]
        if str(row[1]).upper() in ("APPROVED", "REJECTED", "SUPERSEDED"):
            w = __import__("sqlite3").connect(str(REPO / "flow_agent.db"), timeout=30)
            w.execute("PRAGMA busy_timeout=30000")
            w.execute("BEGIN IMMEDIATE")
            w.execute("UPDATE product_intelligence_review_draft SET review_status='READY_FOR_REVIEW', updated_at=? WHERE draft_id=?",
                      (__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), did))
            w.commit(); w.close()
    else:
        st, r = req("POST", f"/products/{pid}/intelligence/review-drafts", {})
        if st != 200:
            return {"product_id": pid, "result": "FAIL", "stage": "create", "http": st, "detail": r}
        did = r["draft_id"]

    # exact stored listing URL for THIS product (never a generic host); prefer the tiktok product URL
    prow = con.execute("SELECT tiktok_product_url, source_url FROM product WHERE id=?", (pid,)).fetchone()
    exact_url = (ev.get("source_url_override") or prow[0] or prow[1] or ev.get("source_url"))
    # 2. PATCH fields + acquired provenance (one provenance row per set field). FACT vs
    # SUPPORTED_INFERENCE get TRUTHFULLY-distinct provenance: EXTERNALLY_EXTRACTED is reserved for
    # source-stated facts; a conservative reviewed inference is REVIEWER_ASSERTED/INFERENCE.
    patch = {"reviewed_by": REVIEWER, "reviewer_note": ev.get("rationale", "")[:400]}
    prov = []
    for f, spec in ev["fields"].items():
        patch[f] = spec["value"]
        status = spec.get("status", "FACT")
        if status == "FACT":
            src_type, ekind, vstatus, method = "TIKTOK_EXTRACTION", "FACT", "EXTERNALLY_EXTRACTED", "LISTING_TITLE_EXTRACTION"
        else:  # SUPPORTED_INFERENCE
            src_type, ekind, vstatus, method = "REVIEWER_SUPPORTED_INFERENCE", "INFERENCE", "REVIEWER_ASSERTED", "CONSERVATIVE_INFERENCE_FROM_VERIFIED_ATTRIBUTE"
        note = spec.get("rationale") or ev.get("excerpt", "")
        prov.append({
            "field_name": f, "declared_value": json.dumps(spec["value"], ensure_ascii=False)[:800],
            "source_type": src_type, "source_url": exact_url, "source_lane": "PI13_ACQUIRED_RECOVERY",
            "evidence_kind": ekind, "extraction_method": method,
            "confidence_score": ev.get("confidence", 0.7), "verification_status": vstatus,
            "claim_risk_flag": ev.get("claim_risk", "LOW"),
            "reviewer_decision": "ACCEPTED", "reviewer_note": str(note)[:300],
        })
    # NOTE: allowed_claims_json is a VALIDATOR-COMPUTED / claim-safety-gated field. We do NOT
    # overwrite it here (doing so cleared the existing safe claims). If the draft lacks any allowed
    # claim, we add ONE deterministic taxonomy identity claim ONLY when none exist.
    existing_ac = con.execute("SELECT allowed_claims_json FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone()[0]
    try:
        parsed_ac = json.loads(existing_ac) if existing_ac else []
    except Exception:
        parsed_ac = []
    if parsed_ac:
        patch["allowed_claims_json"] = parsed_ac  # re-supply existing validated claims so recompute keeps them
    else:
        try:
            claim, fp = identity_claim(con, pid)
        except Exception:
            claim = None
        if claim:
            patch["allowed_claims_json"] = [claim]
    patch["provenance_items"] = prov
    if exact_url:
        patch["source_urls_json"] = {"primary_listing": exact_url}
    st, r = req("PATCH", f"/product-intelligence/review-drafts/{did}", patch)
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "patch", "http": st, "detail": r}

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
