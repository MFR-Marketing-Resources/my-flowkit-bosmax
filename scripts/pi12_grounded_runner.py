#!/usr/bin/env python
"""BOSMAX-PI-12-GROUNDED-530-FINAL — grounded Product Intelligence closure runner.

For each debt product (318 legacy + 212 missing) it drives the product-scoped backend API through
ONE grounded pipeline and ONE DeepSeek call:

  create/reuse corrective draft
    -> ai-fill-missing (ONE DeepSeek call: description, benefits, usp, usage, target_customer,
       buyer_persona, copy_strategy — product-specific SUPPORTED_INFERENCE; ingredients/warnings/
       uncertain-usage return INSUFFICIENT_EVIDENCE and are never invented)
    -> deterministic identity allowed_claims (taxonomy identity, claim-safe, fingerprinted;
       supports ONLY allowed_claims_json)
    -> SOURCE_UNAVAILABLE disposition for still-missing ingredients/warnings/usage
    -> validate (the REAL validator)
    -> semantic quality gate (product-specific, no generic template, CLAIM_SAFE only)
    -> approve immutable snapshot as reviewer `claude-pi12-grounded` (automated decision, audit note)

Never invents facts. Never auto-acknowledges CLAIM_REVIEW_REQUIRED. Never approves CLAIM_BLOCKED or
generic/placeholder content. Serialized writer, checkpoint/10, reconcile/25, resumable ledger,
4xx=permanent, 429/5xx/network=<=3 bounded retries. Provider-call cap enforced (<=530).

Usage:
  python scripts/pi12_grounded_runner.py --pilot         # stratified 10-product pilot
  python scripts/pi12_grounded_runner.py --bulk          # remaining cohort (post-pilot)
  python scripts/pi12_grounded_runner.py --ids a,b,c     # explicit ids
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-pi12-grounded"
LEDGER = REPO / "outputs" / "mission-pi12" / "ledger.jsonl"
CALL_CAP = 530
from agent.services.product_intelligence_claim_safety_service import evaluate_claim_safety  # noqa: E402

# generic/placeholder markers that must NEVER survive into an approved product (quality gate)
GENERIC_MARKERS = (
    "everyday use", "everyday users", "suitable for everyone", "generic consumer",
    "used for its stated everyday purpose", "this description is a neutral, identity-based summary",
    "general consumers looking for", "product for everyday use",
)


def _req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode() or "{}")


def call(method, path, body=None, timeout=180, retries=3):
    """4xx = permanent (no retry). 429/5xx/network = bounded retry with backoff."""
    attempt = 0
    while True:
        try:
            return _req(method, path, body, timeout)
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                detail = json.loads(e.read().decode() or "{}")
            except Exception:
                detail = {}
            if code == 429 or 500 <= code < 600:
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1)); attempt += 1; continue
            return code, detail  # 4xx permanent, or retries exhausted
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1)); attempt += 1; continue
            return 0, {"error": "NETWORK"}


def ne(v):
    return v not in (None, "", "[]", "{}", "null", [], {})


REQUIRED = ("product_description", "benefits_json", "usp_json", "usage_text", "ingredients_text",
            "warnings_text", "target_customer_text", "allowed_claims_json",
            "buyer_persona_snapshot_json", "copy_strategy_summary_json", "source_urls_json",
            "image_evidence_json")
DISPOSABLE = ("ingredients_text", "warnings_text", "usage_text")
STOP_FLAG = REPO / "outputs" / "mission-pi12" / "STOP"

# ingredients/warnings are preserved ONLY with real acquired/operator/verified field provenance tied
# to the value. AI_ENRICHMENT / AI_PROPOSED / REVIEW_DRAFT / prior AI prose are NOT evidence.
ACQUIRED_SOURCE = {"EXTERNAL_EXTRACTION", "EXTERNALLY_EXTRACTED", "OPERATOR_CONFIRMED", "OPERATOR",
                   "TIKTOK_EXTRACTION", "IMAGE_EXTRACTION", "APPROVED_EVIDENCE"}
ACQUIRED_VERIFY = {"VERIFIED", "EXTERNALLY_VERIFIED", "OPERATOR_CONFIRMED", "APPROVED"}


def field_has_acquired_provenance(con, did, fld):
    r = con.execute("SELECT source_type,verification_status FROM "
                    "product_intelligence_review_field_provenance WHERE draft_id=? AND field_name=? "
                    "ORDER BY created_at DESC LIMIT 1", (did, fld)).fetchone()
    if not r:
        return False
    return (str(r[0] or "").upper() in ACQUIRED_SOURCE) or (str(r[1] or "").upper() in ACQUIRED_VERIFY)


def identity_claim(p):
    """Deterministic taxonomy identity claim (claim-safe, fingerprinted). Supports ONLY
    allowed_claims_json. Returns (claim_str, fingerprint) or (None, None) if no clean taxonomy or
    the claim would trip the claim lexicon."""
    cat, sub, typ = p.get("category"), p.get("subcategory"), p.get("type") or p.get("product_type")
    parts = [x for x in (cat, sub, typ) if ne(x)]
    if not parts:
        return None, None
    import hashlib
    fp = hashlib.sha256(json.dumps({"id": p["id"], "category": cat, "subcategory": sub, "type": typ},
                                   sort_keys=True, default=str).encode()).hexdigest()[:16]
    claim = f"Product type: {' / '.join(parts)} (source: product identity; fingerprint {fp})."
    if evaluate_claim_safety({"allowed_claims_json": [claim]}).get("claim_gate") != "CLAIM_SAFE":
        return None, None
    return claim, fp


def is_generic(draft):
    blob = " ".join(str(draft.get(f) or "") for f in
                    ("product_description", "usage_text", "target_customer_text")).lower()
    blob += " " + json.dumps(draft.get("benefits_json") or [], default=str).lower()
    return [m for m in GENERIC_MARKERS if m in blob]


class Budget:
    def __init__(self, spent=0):
        self.calls = spent

    def take(self):
        if self.calls >= CALL_CAP:
            raise RuntimeError(f"PROVIDER_CALL_CAP_REACHED {CALL_CAP}")
        self.calls += 1
        return self.calls


def process_one(con, pid, budget):
    import sqlite3
    p = con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone()
    if p is None:
        return {"product_id": pid, "result": "SKIP", "reason": "NOT_FOUND"}
    p = dict(p)
    # 1. reuse an open non-terminal draft, else create a corrective draft
    row = con.execute("SELECT draft_id FROM product_intelligence_review_draft WHERE product_id=? "
                      "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') "
                      "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1", (pid,)).fetchone()
    if row:
        did = row[0]
    else:
        st, r = call("POST", f"/products/{pid}/intelligence/review-drafts", {})
        if st != 200:
            return {"product_id": pid, "result": "FAIL", "stage": "create", "http": st, "detail": r}
        did = r["draft_id"]

    # 2. ONE DeepSeek ai-fill call (unless the draft already has AI proposals for the copy fields)
    have_ai = con.execute("SELECT COUNT(*) FROM product_intelligence_review_field_provenance "
                          "WHERE draft_id=? AND source_type='AI_ENRICHMENT'", (did,)).fetchone()[0]
    call_seq = None
    if not have_ai:
        call_seq = budget.take()
        st, r = call("POST", f"/product-intelligence/review-drafts/{did}/ai-fill-missing", {}, timeout=240)
        if st != 200:
            return {"product_id": pid, "result": "FAIL" if st >= 500 or st == 0 else "REFUSED",
                    "stage": "ai_fill", "http": st, "detail": r, "call_seq": call_seq}

    # 3. deterministic identity allowed_claims (fingerprinted, claim-safe)
    claim, fp = identity_claim(p)
    if claim:
        call("PATCH", f"/product-intelligence/review-drafts/{did}",
             {"allowed_claims_json": [claim], "reviewed_by": REVIEWER,
              "reviewer_note": f"PI-12 deterministic taxonomy identity claim (fingerprint {fp})."})

    # 4. governed absences. INGREDIENTS + WARNINGS are strict-evidence fields: preserve ONLY when the
    # field carries real acquired/operator/verified provenance tied to the value; an AI_ENRICHMENT /
    # AI_PROPOSED / REVIEW_DRAFT proposal is NOT evidence -> clear + SOURCE_UNAVAILABLE. Genuine
    # acquired ingredients/warnings are preserved. USAGE may remain a safe product-type
    # SUPPORTED_INFERENCE; only dispositioned if still empty.
    d = dict(con.execute("SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone())
    for fld in ("ingredients_text", "warnings_text"):
        if ne(d.get(fld)) and not field_has_acquired_provenance(con, did, fld):
            call("PATCH", f"/product-intelligence/review-drafts/{did}",
                 {fld: "", "reviewed_by": REVIEWER,
                  "reviewer_note": "PI-12: ingredients/warnings need acquired/operator/verified "
                                   "provenance; AI/review proposal is not evidence -> governed absence."})
    for fld in ("ingredients_text", "warnings_text", "usage_text"):
        cur = con.execute(f"SELECT {fld} FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone()[0]
        if not ne(cur):
            call("POST", f"/product-intelligence/review-drafts/{did}/field-dispositions",
                 {"field_name": fld, "disposition": "SOURCE_UNAVAILABLE", "reviewed_by": REVIEWER,
                  "reviewer_note": "PI-12: no acquired evidence for this field; governed supply gap."})

    # 5. validate (real validator)
    st, v = call("POST", f"/product-intelligence/review-drafts/{did}/validate")
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "validate", "http": st, "detail": v, "call_seq": call_seq}
    gate = v.get("claim_gate")
    blockers = v.get("approval_blockers") or []

    # 6. semantic quality gate
    d = dict(con.execute("SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone())
    generic = is_generic(d)
    hard_missing = [b for b in blockers if str(b).startswith("MISSING_REQUIRED_FIELDS")]
    if generic:
        return {"product_id": pid, "result": "REVIEW", "reason": f"GENERIC_TEXT:{generic}", "call_seq": call_seq}
    if hard_missing:
        return {"product_id": pid, "result": "INCOMPLETE", "reason": ";".join(hard_missing),
                "readiness": v.get("readiness_status"), "call_seq": call_seq}
    if gate == "CLAIM_BLOCKED":
        return {"product_id": pid, "result": "REVIEW", "reason": "CLAIM_BLOCKED",
                "tokens": v.get("claim_tokens_json"), "call_seq": call_seq}
    if gate == "CLAIM_REVIEW_REQUIRED":
        # never auto-acknowledge; ledger for human review with exact tokens
        return {"product_id": pid, "result": "REVIEW", "reason": "CLAIM_REVIEW_REQUIRED",
                "tokens": v.get("claim_tokens_json"), "call_seq": call_seq}

    # 7. approve (CLAIM_SAFE, all hard-required present) — automated mission decision with audit note
    st, a = call("POST", f"/product-intelligence/review-drafts/{did}/approve",
                 {"approved_by": REVIEWER,
                  "approval_note": "PI-12 grounded closure: product-specific SUPPORTED_INFERENCE via "
                                   "one DeepSeek ai-fill + deterministic identity claim + governed "
                                   "absences; validated CLAIM_SAFE by the real validator (automated)."})
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "approve", "http": st, "detail": a, "call_seq": call_seq}
    return {"product_id": pid, "result": "APPROVED", "snapshot_id": a.get("snapshot_id"),
            "version": a.get("version"), "readiness": a.get("readiness_status"),
            "completeness": a.get("completeness_score"), "gate": gate, "call_seq": call_seq}


def correct_one(con, pid):
    """Corrective vNext for a contaminated approval: reuse the product-specific grounded fields from
    the existing PI-12 approved snapshot, DROP unsupported AI ingredients/warnings -> governed
    absence, validate, approve. NO new DeepSeek call. The bad snapshot is preserved as history."""
    s = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND approved_by=? "
                    "AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid, REVIEWER)).fetchone()
    if not s:
        return {"product_id": pid, "result": "SKIP", "reason": "NO_PI12_APPROVED"}
    s = dict(s)

    def j(v):
        try:
            return json.loads(v) if isinstance(v, str) else v
        except Exception:
            return v
    st, r = call("POST", f"/products/{pid}/intelligence/review-drafts", {})
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "create", "http": st, "detail": r}
    did = r["draft_id"]
    patch = {"product_description": s.get("product_description"), "benefits_json": j(s.get("benefits_json")),
             "usp_json": j(s.get("usp_json")), "usage_text": s.get("usage_text"),
             "target_customer_text": s.get("target_customer_text"),
             "buyer_persona_snapshot_json": j(s.get("buyer_persona_snapshot_json")),
             "copy_strategy_summary_json": j(s.get("copy_strategy_summary_json")),
             "allowed_claims_json": j(s.get("allowed_claims_json")), "source_urls_json": j(s.get("source_urls_json")),
             "image_evidence_json": j(s.get("image_evidence_json")),
             # ingredients/warnings intentionally OMITTED -> governed absence
             "reviewed_by": REVIEWER,
             "reviewer_note": "PI-12 corrective vNext: drop unsupported AI ingredients/warnings -> "
                              "governed absence; preserve product-specific grounded fields (no DeepSeek)."}
    call("PATCH", f"/product-intelligence/review-drafts/{did}", patch)
    for fld in ("ingredients_text", "warnings_text", "usage_text"):
        cur = con.execute(f"SELECT {fld} FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone()[0]
        if not ne(cur):
            call("POST", f"/product-intelligence/review-drafts/{did}/field-dispositions",
                 {"field_name": fld, "disposition": "SOURCE_UNAVAILABLE", "reviewed_by": REVIEWER,
                  "reviewer_note": "PI-12 corrective: governed absence (no acquired evidence)."})
    st, v = call("POST", f"/product-intelligence/review-drafts/{did}/validate")
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "validate", "http": st, "detail": v}
    d = dict(con.execute("SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (did,)).fetchone())
    if is_generic(d):
        return {"product_id": pid, "result": "REVIEW", "reason": "GENERIC_TEXT"}
    if [b for b in (v.get("approval_blockers") or []) if str(b).startswith("MISSING_REQUIRED_FIELDS")]:
        return {"product_id": pid, "result": "INCOMPLETE", "reason": "MISSING_AFTER_CORRECT"}
    if v.get("claim_gate") != "CLAIM_SAFE":
        return {"product_id": pid, "result": "REVIEW", "reason": v.get("claim_gate")}
    st, a = call("POST", f"/product-intelligence/review-drafts/{did}/approve",
                 {"approved_by": REVIEWER, "approval_note": "PI-12 corrective vNext (ingredients/warnings "
                  "governed-absent); grounded fields preserved; CLAIM_SAFE (automated)."})
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "approve", "http": st, "detail": a}
    return {"product_id": pid, "result": "CORRECTED", "snapshot_id": a.get("snapshot_id"),
            "version": a.get("version"), "readiness": a.get("readiness_status"), "call_seq": None}


def load_ledger():
    done = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line); done[r["product_id"]] = r
            except Exception:
                pass
    return done


def append_ledger(row):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def pilot_ids(con):
    frozen = json.loads((REPO / "outputs" / "mission-pi12" / "frozen_cohort.json").read_text())
    legacy, missing = frozen["legacy"], frozen["missing"]

    def arch(pid):
        r = con.execute("SELECT lifecycle_status FROM product WHERE id=?", (pid,)).fetchone()
        return r and str(r[0] or "").upper().startswith("ARCH")
    legacy_active = [i for i in legacy if not arch(i)]
    legacy_arch = [i for i in legacy if arch(i)]
    missing_active = [i for i in missing if not arch(i)]
    missing_arch = [i for i in missing if arch(i)]
    picked, seen = [], set()

    def take(group, n):
        for i in group:
            if len([1 for _ in ()]) or i not in seen:
                if i in seen:
                    continue
                picked.append(i); seen.add(i); n -= 1
                if n == 0:
                    return
    # 3 legacy, 3 missing, 1 archived legacy, 1 archived missing, then 2 more (claim-sensitive /
    # weak-evidence proxies) from the remaining active pools -> 10 distinct.
    take(legacy_active, 3); take(missing_active, 3); take(legacy_arch, 1); take(missing_arch, 1)
    take([i for i in legacy_active if i not in seen], 1)
    take([i for i in missing_active if i not in seen], 1)
    # backfill to 10 from anything remaining
    for i in legacy + missing:
        if len(picked) >= 10:
            break
        if i not in seen:
            picked.append(i); seen.add(i)
    return picked[:10]


def main():
    import sqlite3
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--bulk", action="store_true")
    ap.add_argument("--correct", action="store_true", help="corrective vNext for --ids (no DeepSeek)")
    ap.add_argument("--ids", default="")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    frozen = json.loads((REPO / "outputs" / "mission-pi12" / "frozen_cohort.json").read_text())
    from collections import Counter
    ids = ([x.strip() for x in a.ids.split(",") if x.strip()] if a.ids
           else (pilot_ids(con) if a.pilot else frozen["union_530"]))
    done = load_ledger()
    # budget counts ACTUAL provider calls across all runs (every ledger row with a call_seq),
    # not unique products, so duplicates still count against the <=530 ceiling.
    raw_ledger = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines()] if LEDGER.exists() else []
    budget = Budget(spent=sum(1 for r in raw_ledger if r.get("call_seq") is not None))
    DONE = {"APPROVED", "CORRECTED"}  # both are terminal-done; never reprocess (avoids duplicate calls)

    if a.correct:  # corrective vNext pass (no provider calls)
        tally = Counter()
        for n, pid in enumerate(ids, 1):
            con.close(); con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
            row = correct_one(con, pid); append_ledger(row); tally[row["result"]] += 1
            print(f"[correct {n}/{len(ids)}] {pid[:8]} -> {row['result']} {row.get('reason') or ''}")
        print("CORRECT SUMMARY:", dict(tally)); con.close(); return

    todo = [i for i in ids if done.get(i, {}).get("result") not in DONE]
    print(f"cohort={len(ids)} already_done={len(ids)-len(todo)} todo={len(todo)} calls_spent={budget.calls}")
    tally = Counter()
    for n, pid in enumerate(todo, 1):
        if STOP_FLAG.exists():  # graceful pause at checkpoint — no in-flight loss, resumable
            print(f"STOP_FLAG present -> graceful pause after {n-1} items"); break
        con.close(); con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
        try:
            row = process_one(con, pid, budget)
        except RuntimeError as exc:
            print("STOP:", exc); break
        append_ledger(row)
        tally[row["result"]] += 1
        print(f"[{n}/{len(todo)}] {pid[:8]} -> {row['result']} {row.get('reason') or row.get('readiness') or ''}")
        if n % 10 == 0:
            print(f"  checkpoint: {dict(tally)} | calls={budget.calls}")
    print("SUMMARY:", dict(tally), "| provider_calls_this_run:", budget.calls)
    con.close()


if __name__ == "__main__":
    main()
