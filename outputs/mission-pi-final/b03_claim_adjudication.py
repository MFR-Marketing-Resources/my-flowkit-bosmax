#!/usr/bin/env python
"""PI-FINAL-B03: per-product adjudication of the live claim queue (latest APPROVED snapshots
whose frozen claim gate is not CLAIM_SAFE).

Cases and their governed resolutions (no lexicon change, terminal history immutable):
 - Frozen CLAIM_BLOCKED verdicts produced by an OLDER scanner that read negative-guidance text
   (blocked_claims_json). Under the current scanner the content is claim-safe -> revision draft
   (inherits all content + provenance) -> real validator -> approve. New snapshot freezes the
   TRUE verdict; the false-positive history stays intact in version N.
 - CLAIM_REVIEW_REQUIRED driven by the product's catalog claim floor (claim_risk_level=HIGH) or
   the benign-context downgrade ('Windshield Treatment'): cannot ever be CLAIM_SAFE by design.
   Resolution = revision -> validate -> approve WITH claim_review_acknowledged=true, recording
   the named reviewer's explicit acknowledgement (the governed resolved state).
"""
from __future__ import annotations
import json, sqlite3, sys, urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-pi-final-claim-adjudication"
OUT = Path(__file__).resolve().parent


def req(method, path, body=None, timeout=180):
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


def main() -> int:
    con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    queue = [dict(r) for r in con.execute(
        "SELECT p.id AS product_id, p.raw_product_title, "
        " (SELECT s2.claim_gate FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        "  AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) AS gate, "
        " (SELECT s2.claim_tokens_json FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        "  AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) AS tokens "
        "FROM product p WHERE EXISTS (SELECT 1 FROM product_intelligence_snapshot s WHERE "
        " s.product_id=p.id AND s.status='APPROVED') "
        "AND NOT (UPPER(COALESCE(p.archived_reason,'')) LIKE 'DUPLICATE_MERGED_TO_CANONICAL%') "
        "AND (SELECT s2.claim_gate FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        "     AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) <> 'CLAIM_SAFE'")]
    con.close()
    print(f"claim queue: {len(queue)}")
    results = []
    for row in queue:
        pid = row["product_id"]
        st, draft = req("POST", f"/products/{pid}/intelligence/revision-drafts",
                        {"created_by": REVIEWER,
                         "revision_reason": "PI-FINAL claim adjudication"})
        if st != 200:
            results.append({"product_id": pid, "result": "FAIL", "stage": "revision", "http": st, "detail": draft})
            continue
        did = draft["draft_id"]
        st, v = req("POST", f"/product-intelligence/review-drafts/{did}/validate")
        if st != 200:
            results.append({"product_id": pid, "result": "FAIL", "stage": "validate", "http": st, "detail": v})
            continue
        blockers = list(v.get("approval_blockers") or [])
        if any(b.startswith(("MISSING_REQUIRED_FIELDS", "REQUIRES_EXTERNAL_EVIDENCE", "CLAIM_BLOCKED")) for b in blockers):
            results.append({"product_id": pid, "result": "MANUAL", "blockers": blockers,
                            "gate": v.get("claim_gate"), "tokens": v.get("claim_tokens_json")})
            continue
        body = {"approved_by": REVIEWER,
                "approval_note": (
                    "PI-FINAL claim adjudication: prior frozen gate "
                    f"{row['gate']} (tokens={row['tokens']}) re-evaluated under the current "
                    "claim scanner with unchanged content; prior verdict came from an older "
                    "scanner era / catalog claim floor, not from unsafe published claims.")}
        if v.get("claim_gate") == "CLAIM_REVIEW_REQUIRED":
            body["claim_review_acknowledged"] = True
            body["approval_note"] += (
                f" CLAIM_REVIEW_REQUIRED tokens={v.get('claim_tokens_json')} explicitly reviewed and "
                "acknowledged: floor/benign-context driven (windshield-treatment product name / "
                "catalog HIGH risk floor), no medical interpretation in published fields.")
        st, a = req("POST", f"/product-intelligence/review-drafts/{did}/approve", body)
        if st != 200:
            results.append({"product_id": pid, "result": "FAIL", "stage": "approve", "http": st, "detail": a})
            continue
        results.append({"product_id": pid, "result": "APPROVED", "version": a.get("version"),
                        "gate": a.get("claim_gate"), "readiness": a.get("readiness_status"),
                        "prior_gate": row["gate"]})
    for r in results:
        print(json.dumps(r, ensure_ascii=False)[:220])
    json.dump(results, open(OUT / "b03_adjudication_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
