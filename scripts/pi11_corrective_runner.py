#!/usr/bin/env python
"""PI-11 CORRECTIVE runner — RESTORE-ONLY (B-604-01..10). No DeepSeek. No fabrication.

Supersedes the rejected `pi11_stored_evidence_runner.py`. This runner NEVER manufactures generic
filler and NEVER promotes prose as evidence. It restores ONLY provenance-supported prior fields and
lets the AUTHORITATIVE validator (`_evaluate_validation_payload`) decide approvability — a lone
surviving description can never complete an otherwise-empty product.

Decision model (per product):
  * restore source = the last VALID pre-PI-11 snapshot (else best non-PI-11 draft);
  * a field is RESTORABLE only if the prior snapshot carries a SUPPORTED field-provenance row
    (verification_status approved/verified AND a source_url or external source_type) AND the value
    is non-placeholder AND not CLAIM_BLOCKED — otherwise it is absent (B-604-02/03/06);
  * disposition-eligible knowledge (usage/ingredients/warnings) unsupported -> SOURCE_UNAVAILABLE;
  * allowed claims kept only when claim-SAFE AND SUPPORTED (identity-grounded in the product's own
    taxonomy); everything else is retained in blocked, never deleted (B-604-04);
  * persona/strategy sanitized against the claim gate (B-604-05, single-eval);
  * the REAL validator decides readiness/blockers (B-604-05/07). RESTORE_APPROVE only when it is
    approvable (no MISSING_REQUIRED_FIELDS / REQUIRES_EXTERNAL_EVIDENCE / CLAIM_BLOCKED); else
    LEAVE_INCOMPLETE, carrying the validator's own blockers as the reason.

Modes:
  --dry-run (DEFAULT): compute plans for the WHOLE affected cohort. WRITES NOTHING to any DB.
  --apply            : genuine restore-only lifecycle (corrective review draft -> field
                       dispositions -> validate -> approve immutable vNext snapshot; historical
                       snapshots are NEVER updated or deleted). HARD-GATED: refuses unless
                       PI11_CORRECTIVE_APPLY_APPROVED=1. Cleans up its draft on failure so a failed
                       product leaves no partial draft/provenance/snapshot. NOT run in this phase.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, hashlib, urllib.error, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = str(REPO / "flow_agent.db")
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-owner-delegated-pi11-corrective"
APPLY_ENV = "PI11_CORRECTIVE_APPLY_APPROVED"
sys.path.insert(0, str(REPO))
from agent.services.product_intelligence_claim_safety_service import evaluate_claim_safety  # noqa: E402
from agent.services.product_intelligence_review_draft_service import (  # noqa: E402
    _evaluate_validation_payload, REQUIRED_FIELDS, DISPOSITION_ELIGIBLE_FIELDS,
    READINESS_GOVERNED_ABSENCE,
)

# ── generic-template / placeholder detection (what the REJECTED runner emitted) ──────────────
GENERIC_MARKERS = (
    "This description is a neutral, identity-based summary",
    "Used for its stated everyday purpose.",
    "product for everyday use",
    "Follow the usage guidance printed on the product packaging",
    "General consumers looking for a",
    "Category-level SUPPORTED_INFERENCE",
    "A packaged food product.",
)
PLACEHOLDER_RE = re.compile(
    r"(?i)\b(assume[d ]|not provided|not stated|not specified|unknown|n/?a|placeholder|"
    r"tidak dinyatakan|standard\s+\w+\s+base|not intended to diagnose)\b")

# B-604 correction 1: a field is EVIDENCE only when its provenance proves real ACQUISITION —
# NOT a reviewer/workflow status. REVIEW_DRAFT / AI_PREPARE_LANE are authoring lanes, never
# acquisition, and a source_url attached to AI/review prose is NOT acquired evidence. Support
# requires an acquisition source_type AND an approved/verified status AND a source reference AND an
# extraction method (field-level lineage).
ACQUISITION_SOURCE_TYPES = {"EXTERNAL_EXTRACTION", "EXTERNALLY_EXTRACTED", "OPERATOR_CONFIRMED",
                            "OPERATOR", "TIKTOK_EXTRACTION", "IMAGE_EXTRACTION", "APPROVED_EVIDENCE"}
SUPPORT_VERIFY = {"VERIFIED", "EXTERNALLY_VERIFIED", "OPERATOR_CONFIRMED", "APPROVED"}

# fields the validator hard-requires that we may RESTORE from a supported prior (non-disposition)
RESTORABLE_REQUIRED = ("product_description", "benefits_json", "usp_json", "target_customer_text",
                       "buyer_persona_snapshot_json", "copy_strategy_summary_json",
                       "source_urls_json", "image_evidence_json")
CLAIM_TEXT_FIELDS = ("product_description", "benefits_json", "usp_json", "usage_text",
                     "ingredients_text", "warnings_text", "target_customer_text")


def ne(v):
    return v not in (None, "", "[]", "{}", "null")


def jload(v):
    if not ne(v):
        return None
    try:
        return json.loads(v) if isinstance(v, str) else v
    except Exception:
        return None


def is_generic_or_placeholder(text):
    if not ne(text):
        return True
    s = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return any(m in s for m in GENERIC_MARKERS) or bool(PLACEHOLDER_RE.search(s))


def claim_gate_of(field_name, value):
    if not ne(value):
        return "CLAIM_SAFE"
    return evaluate_claim_safety({field_name: value}).get("claim_gate", "CLAIM_SAFE")


def provenance_supports(prov_row):
    """B-604 correction 1: a field is EVIDENCE only when its field-level provenance proves real
    acquisition — an ACQUISITION source_type AND an approved/verified status AND a source reference
    (URL or immutable local evidence ref) AND an extraction method. A REVIEWED_APPROVED status or a
    source_url on AI/review prose is NOT acquired evidence."""
    if not prov_row:
        return False
    st = str(prov_row.get("source_type") or "").upper()
    vs = str(prov_row.get("verification_status") or "").upper()
    has_ref = bool(prov_row.get("source_url")) or bool(prov_row.get("evidence_ref")) \
        or bool(prov_row.get("normalized_value"))
    has_method = bool(prov_row.get("extraction_method"))
    return st in ACQUISITION_SOURCE_TYPES and vs in SUPPORT_VERIFY and has_ref and has_method


def restorable_value(field_name, prior_value, prov_row):
    """Return (value_or_None, status). A prior value is restored ONLY if it is provenance-supported,
    non-placeholder/non-generic, and not CLAIM_BLOCKED."""
    if not ne(prior_value):
        return None, "ABSENT"
    if is_generic_or_placeholder(prior_value):
        return None, "REJECTED_GENERIC_OR_PLACEHOLDER"
    if not provenance_supports(prov_row):
        return None, "UNSUPPORTED_NO_PROVENANCE"
    if field_name in CLAIM_TEXT_FIELDS and claim_gate_of(field_name, prior_value) == "CLAIM_BLOCKED":
        return None, "REJECTED_CLAIM_BLOCKED"
    return prior_value, "RESTORED_SUPPORTED"


def claim_is_supported(claim, product):
    """B-604-04: a claim is SUPPORTED only when factually grounded in the product's own identity
    (its taxonomy). Size/efficacy/marketing claims without field-level provenance are unsupported."""
    low = str(claim).lower()
    for f in ("category", "subcategory", "type", "product_type"):
        v = str((product or {}).get(f) or "").strip().lower()
        if v and v in low:
            return True
    return False


def reconcile_claims(prior_allowed, prior_blocked, product):
    """allowed = claim-SAFE AND factually-SUPPORTED. Everything else is retained in blocked
    (quarantine, never deleted). A linguistically safe but unsupported claim is NOT allowed."""
    allowed, quarantined = [], []
    for c in (prior_allowed or []):
        c = str(c).strip()
        if not c:
            continue
        safe = evaluate_claim_safety({"allowed_claims_json": [c]}).get("claim_gate") == "CLAIM_SAFE"
        if safe and claim_is_supported(c, product):
            allowed.append(c)
        else:
            quarantined.append(c)
    blocked = list(dict.fromkeys([*(str(x).strip() for x in (prior_blocked or []) if str(x).strip()),
                                  *quarantined]))
    return allowed, blocked, quarantined


def sanitize_planning(obj):
    """B-604-05: drop persona/strategy entries whose text trips the claim gate. Each value is
    evaluated EXACTLY ONCE (no double clean_val call)."""
    removed = []

    def clean_val(v):
        if isinstance(v, str):
            if ne(v) and evaluate_claim_safety({"paste_anything_summary": v}).get("claim_gate") != "CLAIM_SAFE":
                removed.append(v)
                return None
            return v
        if isinstance(v, list):
            out = []
            for x in v:
                cv = clean_val(x)
                if cv is not None:
                    out.append(cv)
            return out
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                cv = clean_val(x)
                if cv is not None:
                    out[k] = cv
            return out
        return v

    return (clean_val(obj) if obj else obj), removed


def author_identity_claim(product):
    """DISABLED by owner decision (default off). A single DETERMINISTIC identity claim from the
    product's OWN taxonomy (not DeepSeek, not prose). It may satisfy ONLY `allowed_claims_json` and
    NEVER provides support for description/benefits/usp/usage/target/persona/strategy — those come
    only from acquisition-supported provenance. If ever re-enabled it additionally requires a
    non-stale taxonomy/registry fingerprint, immutable field provenance on the taxonomy fields, no
    fallback/generic taxonomy, and a claim-safe result. Returns None if no taxonomy or not safe."""
    parts = [(product or {}).get("category"), (product or {}).get("subcategory"), (product or {}).get("type")]
    ident = " / ".join(x for x in parts if x)
    if not ident:
        return None
    claim = f"Product type: {ident} (source: product identity)."
    if evaluate_claim_safety({"allowed_claims_json": [claim]}).get("claim_gate") != "CLAIM_SAFE":
        return None
    return claim


def build_correction_plan(product, current_pi11, prior_snap, prior_prov, assert_identity_claims=False):
    """PURE decision function. Restore-only, provenance-gated, validated by the REAL contract.

    assert_identity_claims (owner-authorizable, OFF by default): when the restored allowed-claim set
    is empty, assert ONE deterministic identity claim from the product's own taxonomy so a fully
    restored product is not blocked solely on the required allowed_claims_json. Never authors prose."""
    product = product or {}
    prior = prior_snap or {}
    fields, status = {}, {}
    payload = {}

    # 1. restore hard-required copy/evidence fields only when provenance-supported
    for f in RESTORABLE_REQUIRED:
        v, s = restorable_value(f, prior.get(f), (prior_prov or {}).get(f))
        fields[f], status[f] = v, s
        if v is not None:
            payload[f] = jload(v) if f.endswith("_json") else v

    # 2. disposition-eligible knowledge: restore if supported else SOURCE_UNAVAILABLE governed absence
    dispositions = {}
    for f in ("usage_text", "ingredients_text", "warnings_text"):
        v, s = restorable_value(f, prior.get(f), (prior_prov or {}).get(f))
        fields[f], status[f] = v, s
        if v is not None:
            payload[f] = v
        else:
            dispositions[f] = {"disposition": "SOURCE_UNAVAILABLE"}

    # 3. claims (B-604-04): safe AND supported only
    prior_allowed = jload(prior.get("allowed_claims_json")) or []
    prior_blocked = jload(prior.get("blocked_claims_json")) or []
    allowed, blocked, quarantined = reconcile_claims(prior_allowed, prior_blocked, product)
    identity_claim_added = None
    if not allowed and assert_identity_claims:
        ic = author_identity_claim(product)
        if ic:
            allowed = [ic]
            identity_claim_added = ic
    payload["allowed_claims_json"] = allowed
    payload["blocked_claims_json"] = blocked

    # 4. persona/strategy sanitation (B-604-05)
    persona, p_rm = sanitize_planning(jload(prior.get("buyer_persona_snapshot_json")) or {})
    strategy, s_rm = sanitize_planning(jload(prior.get("copy_strategy_summary_json")) or {})
    if "buyer_persona_snapshot_json" in payload:
        payload["buyer_persona_snapshot_json"] = persona
    if "copy_strategy_summary_json" in payload:
        payload["copy_strategy_summary_json"] = strategy

    # 5. AUTHORITATIVE validator decides (B-604-05/07) — never a hand-rolled >=1-fact gate
    verdict = _evaluate_validation_payload(dict(payload), product, dispositions)
    blockers = verdict.get("approval_blockers") or []
    gate = verdict.get("claim_gate")
    hard = [b for b in blockers if str(b).startswith(("MISSING_REQUIRED_FIELDS",
                                                      "REQUIRES_EXTERNAL_EVIDENCE", "CLAIM_BLOCKED"))]
    # B-604 correction 2: only CLAIM_SAFE may enter unattended corrective approval. Any
    # CLAIM_REVIEW_REQUIRED becomes LEAVE_INCOMPLETE_HUMAN_REVIEW — NEVER auto-acknowledged.
    if hard:
        decision = "LEAVE_INCOMPLETE"
    elif gate != "CLAIM_SAFE":
        decision = "LEAVE_INCOMPLETE_HUMAN_REVIEW"
    else:
        decision = "RESTORE_APPROVE"

    return {
        "product_id": product.get("id"),
        "decision": decision,
        "restored_fields": sorted(k for k, s in status.items() if s == "RESTORED_SUPPORTED"),
        "field_status": status,
        "dispositions": sorted(dispositions.keys()),
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "claims_quarantined": quarantined,
        "persona_removed": p_rm,
        "strategy_removed": s_rm,
        "identity_claim_added": identity_claim_added,
        "readiness_status": verdict.get("readiness_status"),
        "claim_gate": gate,
        "completeness_score": verdict.get("completeness_score"),
        "approval_blockers": blockers,
        "governed_absent_fields": verdict.get("governed_absent_fields"),
        "reason": ("APPROVABLE_CLAIM_SAFE_VIA_REAL_VALIDATOR" if decision == "RESTORE_APPROVE"
                   else ("CLAIM_REVIEW_REQUIRED:human review (never auto-acknowledged)"
                         if decision == "LEAVE_INCOMPLETE_HUMAN_REVIEW" else "; ".join(hard))),
        "payload": payload,
        "disposition_map": dispositions,
    }


def plan_digest(plan):
    key = json.dumps({k: plan.get(k) for k in ("decision", "restored_fields", "dispositions",
                                               "allowed_claims", "blocked_claims", "readiness_status")},
                     sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()


# ── I/O layer ────────────────────────────────────────────────────────────────────────────────
FIXTURE_SQL = (
    "(LOWER(TRIM(COALESCE(raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(id,'')) LIKE 'fixture|_%' ESCAPE '|')"
)


def prov_map(con, snapshot_id):
    if not snapshot_id:
        return {}
    return {r["field_name"]: dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_field_provenance WHERE snapshot_id=?", (snapshot_id,))}


def load_context(con, pid, reviewer_prefix="claude-owner-delegated-pi11"):
    p = con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone()
    if p is None:
        return None
    p = dict(p)
    cur = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND approved_by LIKE ? "
                      "ORDER BY version DESC LIMIT 1", (pid, reviewer_prefix + "%")).fetchone()
    cur = dict(cur) if cur else None
    prior = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? "
                        "AND (approved_by IS NULL OR approved_by NOT LIKE ?) "
                        "ORDER BY (status='APPROVED') DESC, version DESC LIMIT 1",
                        (pid, reviewer_prefix + "%")).fetchone()
    prior = dict(prior) if prior else None
    if prior is None:
        d = con.execute("SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
                        "AND COALESCE(reviewed_by,'') NOT LIKE ? AND COALESCE(approved_by,'') NOT LIKE ? "
                        "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1",
                        (pid, reviewer_prefix + "%", reviewer_prefix + "%")).fetchone()
        prior = dict(d) if d else None
    prior_prov = prov_map(con, (prior or {}).get("snapshot_id"))
    corrective = con.execute("SELECT 1 FROM product_intelligence_snapshot WHERE product_id=? "
                             "AND approved_by LIKE 'claude-owner-delegated-pi11-corrective%' "
                             "AND status='APPROVED' LIMIT 1", (pid,)).fetchone()
    return {"product": p, "current_pi11": cur, "prior": prior, "prior_prov": prior_prov,
            "already_corrected": bool(corrective)}


def affected_ids(con):
    """Every REAL product whose latest approved snapshot was written by the rejected PI-11 run.
    Test fixtures are excluded (B-604-08)."""
    rows = con.execute(
        "SELECT DISTINCT s.product_id FROM product_intelligence_snapshot s "
        "JOIN product p ON p.id = s.product_id "
        "WHERE s.approved_by LIKE 'claude-owner-delegated-pi11%' "
        f"AND s.approved_by NOT LIKE 'claude-owner-delegated-pi11-corrective%' AND NOT {FIXTURE_SQL}").fetchall()
    return [r[0] for r in rows]


def dry_run(con, ids, assert_identity_claims=False):
    out = []
    for pid in ids:
        ctx = load_context(con, pid)
        if ctx is None:
            out.append({"product_id": pid, "decision": "SKIP", "reason": "PRODUCT_NOT_FOUND"})
            continue
        plan = build_correction_plan(ctx["product"], ctx["current_pi11"], ctx["prior"], ctx["prior_prov"],
                                     assert_identity_claims=assert_identity_claims)
        cur = ctx["current_pi11"] or {}
        plan["digest"] = plan_digest(plan)
        plan["before"] = {
            "pi11_description": (cur.get("product_description") or "")[:150],
            "pi11_readiness": cur.get("readiness_status"),
        }
        plan["after_preview"] = {
            "description": (plan["payload"].get("product_description") or "<<MISSING - defer to grounded generation>>")[:150],
            "restored": plan["restored_fields"],
            "dispositions": plan["dispositions"],
            "allowed": len(plan["allowed_claims"]),
            "blocked": len(plan["blocked_claims"]),
        }
        plan.pop("payload", None)
        plan.pop("disposition_map", None)
        out.append(plan)
    return out


# ── genuine restore-only apply lifecycle (HARD-GATED; not run in the dry-run phase) ───────────
class _UrllibClient:
    def request(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or "{}")
            except Exception:
                return e.code, {}


def apply_one(client, pid, plan, already_corrected=False):
    """Restore-only lifecycle for ONE product: corrective review draft -> field dispositions ->
    validate -> approve immutable vNext. NEVER updates/deletes historical snapshots. On any failure
    the corrective draft is rejected (cleanup) so no partial draft/provenance/snapshot survives.
    Idempotent: a product already carrying a corrective snapshot is skipped."""
    if already_corrected:
        return {"product_id": pid, "result": "SKIPPED_ALREADY_CORRECTED"}
    if plan["decision"] != "RESTORE_APPROVE":
        return {"product_id": pid, "result": "SKIPPED_NOT_APPROVABLE", "reason": plan["reason"]}
    st, r = client.request("POST", f"/products/{pid}/intelligence/review-drafts", {})
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "create_draft", "http": st, "detail": r}
    did = r["draft_id"]
    try:
        patch = dict(plan["payload"])
        patch["reviewed_by"] = REVIEWER
        patch["reviewer_note"] = "PI-11 restore-only correction: provenance-supported prior fields only."
        st, r = client.request("PATCH", f"/product-intelligence/review-drafts/{did}", patch)
        if st != 200:
            raise RuntimeError(f"patch {st} {r}")
        for fld in plan["disposition_map"]:
            st, r = client.request("POST", f"/product-intelligence/review-drafts/{did}/field-dispositions",
                                   {"field_name": fld, "disposition": "SOURCE_UNAVAILABLE",
                                    "reviewed_by": REVIEWER,
                                    "reviewer_note": "No provenance-supported prior value; governed supply gap."})
            if st != 200:
                raise RuntimeError(f"dispose {fld} {st} {r}")
        st, v = client.request("POST", f"/product-intelligence/review-drafts/{did}/validate")
        if st != 200:
            raise RuntimeError(f"validate {st} {v}")
        blockers = [b for b in (v.get("approval_blockers") or [])
                    if str(b).startswith(("MISSING_REQUIRED_FIELDS", "REQUIRES_EXTERNAL_EVIDENCE", "CLAIM_BLOCKED"))]
        if blockers:
            raise RuntimeError(f"validator_blocked {blockers}")
        # B-604 correction 2: NEVER auto-acknowledge a claim review. Only CLAIM_SAFE approves.
        if v.get("claim_gate") != "CLAIM_SAFE":
            raise RuntimeError(f"claim_gate_not_safe:{v.get('claim_gate')} -> human review required")
        body = {"approved_by": REVIEWER,
                "approval_note": "PI-11 restore-only corrective vNext (CLAIM_SAFE, owner-authorized)."}
        st, a = client.request("POST", f"/product-intelligence/review-drafts/{did}/approve", body)
        if st != 200:
            raise RuntimeError(f"approve {st} {a}")
        return {"product_id": pid, "result": "APPROVED", "snapshot_id": a.get("snapshot_id"),
                "version": a.get("version"), "readiness": a.get("readiness_status")}
    except Exception as exc:
        # cleanup: reject the corrective draft so no partial approved snapshot / open draft survives
        client.request("POST", f"/product-intelligence/review-drafts/{did}/reject",
                       {"rejected_by": REVIEWER, "reviewer_note": f"corrective apply aborted: {exc}"})
        return {"product_id": pid, "result": "FAIL", "stage": "apply", "detail": str(exc)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--all", action="store_true", help="all products touched by the rejected PI-11 run")
    ap.add_argument("--identity-claims", action="store_true",
                    help="owner-authorizable: assert one deterministic identity claim from the "
                         "product's own taxonomy when the restored allowed-claim set is empty")
    ap.add_argument("--out", default="dryrun_full.json")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{Path(DB).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ids = affected_ids(con) if a.all else [x.strip() for x in a.ids.split(",") if x.strip()]

    if a.apply:
        if os.environ.get(APPLY_ENV) != "1":
            print(f"REFUSED: --apply is hard-gated. Set {APPLY_ENV}=1 only under explicit owner "
                  "authorization (canonical writes).")
            sys.exit(2)
        client = _UrllibClient()
        results = []
        for pid in ids:
            ctx = load_context(con, pid)
            plan = build_correction_plan(ctx["product"], ctx["current_pi11"], ctx["prior"], ctx["prior_prov"],
                                         assert_identity_claims=a.identity_claims)
            results.append(apply_one(client, pid, plan, already_corrected=ctx.get("already_corrected", False)))
        from collections import Counter
        print("APPLY results:", dict(Counter(r["result"] for r in results)))
        return

    res = dry_run(con, ids, assert_identity_claims=a.identity_claims)
    con.close()
    out = REPO / "outputs" / "mission-pi11" / "audit" / a.out
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, default=str)
    from collections import Counter
    print("DRY-RUN (no canonical writes). decisions:", dict(Counter(r["decision"] for r in res)))
    print("report ->", out)


if __name__ == "__main__":
    main()
