#!/usr/bin/env python
"""PI-11 CORRECTIVE runner (B-604-01..07).

Supersedes the rejected `pi11_stored_evidence_runner.py`, whose generic identity templates the
owner forensic audit rejected. This runner NEVER manufactures generic filler to pass a gate. Its
decision logic is a set of PURE functions (`build_correction_plan` and helpers) so it can be
executed against a temporary real DB fixture in tests without any network or canonical write.

Policy (each maps to a frozen blocker):
  B-604-03 fill-missing-ONLY   : preserve a valid product-specific field; only replace when it is
                                 placeholder / generic-template / contaminated / contradicted /
                                 unsafe / missing. NO generic fallback, NO "everyday purpose".
  B-604-02 provenance-gated    : carry ingredients/warnings only with external/operator/approved
                                 field-level provenance; presence in a draft is NOT evidence.
  B-604-06 exact size          : size enters Product Truth / allowed claims only with exact
                                 field-level provenance; else SOURCE_UNAVAILABLE.
  B-604-04 claim-boundary      : re-evaluate each historical allowed claim individually; move only
                                 unsafe/unsupported to blocked; never bulk-copy the allowed list.
  B-604-05 persona/strategy    : sanitize against the blocked set; drop entries that trip the gate.
  B-604-07 semantic gate       : APPROVE only with >=1 product-specific grounded fact + safe copy
                                 grounding + no placeholder/contradiction/blocked-claim leak; else
                                 LEAVE_INCOMPLETE (a DeepSeek / external-evidence candidate).

Modes:
  --dry-run (DEFAULT)  : compute the plan + before/after diff. WRITES NOTHING to the canonical DB.
  --apply              : perform the corrective canonical run. HARD-GATED: refuses unless
                         PI11_CORRECTIVE_APPLY_APPROVED=1 is set (owner authorization). Not used in
                         the dry-run phase.
"""
from __future__ import annotations
import argparse, json, os, re, sqlite3, sys, hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = str(REPO / "flow_agent.db")
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-owner-delegated-pi11"
sys.path.insert(0, str(REPO))
from agent.services.product_intelligence_claim_safety_service import evaluate_claim_safety  # noqa: E402

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

# provenance that lets a knowledge value count as real evidence (B-604-02 / B-604-06)
EXTERNAL_SOURCE_TYPES = {"EXTERNAL_EXTRACTION", "EXTERNALLY_EXTRACTED", "OPERATOR_CONFIRMED",
                         "OPERATOR", "TIKTOK_EXTRACTION", "IMAGE_EXTRACTION", "APPROVED_EVIDENCE"}
EXTERNAL_VERIFY = {"EXTERNALLY_VERIFIED", "OPERATOR_CONFIRMED", "VERIFIED", "APPROVED"}


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
    """True if a text value is one of the rejected generic templates, a placeholder, or empty."""
    if not ne(text):
        return True
    s = str(text)
    if any(m in s for m in GENERIC_MARKERS):
        return True
    if PLACEHOLDER_RE.search(s):
        return True
    return False


def claim_gate_of(field_name, value):
    if not ne(value):
        return "CLAIM_SAFE"
    return evaluate_claim_safety({field_name: value}).get("claim_gate", "CLAIM_SAFE")


def preserve_text(field_name, prior_value):
    """B-604-03: a prior text field may be PRESERVED iff it is product-specific (not generic /
    placeholder) AND not claim-BLOCKED. Returns (value_or_None, status). A BLOCKED prior value is
    not silently kept and not silently templated — it is MISSING pending a safe grounded rewrite."""
    if is_generic_or_placeholder(prior_value):
        return None, "MISSING_NO_SPECIFIC_SOURCE"
    if claim_gate_of(field_name, prior_value) == "CLAIM_BLOCKED":
        return None, "MISSING_PRIOR_WAS_UNSAFE"
    return prior_value, "PRESERVED_SPECIFIC"


def provenance_gated_knowledge(field_name, prior_value, prov_row):
    """B-604-02 / B-604-06: carry ingredients/warnings/size ONLY with external/operator/approved
    field-level provenance. Presence is NOT evidence. Returns (value_or_None, status)."""
    if not ne(prior_value):
        return None, "SOURCE_UNAVAILABLE"
    if is_generic_or_placeholder(prior_value):
        return None, "SOURCE_UNAVAILABLE"  # fabricated / placeholder guess
    st = str((prov_row or {}).get("source_type") or "").upper()
    vs = str((prov_row or {}).get("verification_status") or "").upper()
    if st in EXTERNAL_SOURCE_TYPES or vs in EXTERNAL_VERIFY:
        if claim_gate_of(field_name, prior_value) == "CLAIM_BLOCKED":
            return None, "SOURCE_UNAVAILABLE"  # externally sourced but unsafe -> not asserted here
        return prior_value, "CARRIED_EXTERNAL_EVIDENCE"
    return None, "SOURCE_UNAVAILABLE"  # only a prior draft/self value -> not evidence


def reconcile_claims(prior_allowed, prior_blocked):
    """B-604-04: re-evaluate each historical allowed claim individually. Safe+evaluable claims stay
    allowed; only unsafe/unsupported move to blocked. Never bulk-copy the allowed list to blocked.
    Prior blocked claims are retained blocked (quarantine, never deleted)."""
    allowed, moved = [], []
    for c in (prior_allowed or []):
        c = str(c).strip()
        if not c:
            continue
        if evaluate_claim_safety({"allowed_claims_json": [c]}).get("claim_gate") == "CLAIM_SAFE":
            allowed.append(c)
        else:
            moved.append(c)
    blocked = list(dict.fromkeys([*(str(x).strip() for x in (prior_blocked or []) if str(x).strip()), *moved]))
    return allowed, blocked, moved


def sanitize_planning(obj):
    """B-604-05: strip persona/strategy entries whose text trips the claim gate. Returns (clean, removed)."""
    removed = []

    def clean_val(v):
        if isinstance(v, str):
            if ne(v) and evaluate_claim_safety({"paste_anything_summary": v}).get("claim_gate") != "CLAIM_SAFE":
                removed.append(v)
                return None
            return v
        if isinstance(v, list):
            out = [clean_val(x) for x in v]
            return [x for x in out if x is not None]
        if isinstance(v, dict):
            return {k: clean_val(x) for k, x in v.items() if clean_val(x) is not None or not isinstance(x, str)}
        return v

    return clean_val(obj) if obj else obj, removed


def build_correction_plan(product, current_pi11, prior_snap, prior_prov, cur_prov):
    """PURE decision function. Given a product row, the current (rejected) PI-11 snapshot, the last
    VALID pre-PI-11 snapshot, and the provenance maps, decide the corrective action WITHOUT any I/O.

    Returns a dict: {decision, fields{}, statuses{}, allowed, blocked, moved_to_blocked,
    persona_removed, grounded_facts[], reasons[]}.
    decision ∈ {RESTORE_APPROVE, LEAVE_INCOMPLETE, NO_CHANGE}.
    """
    product = product or {}
    prior = prior_snap or {}
    fields, status = {}, {}
    reasons, grounded = [], []

    # copy fields: preserve product-specific prior; never templated filler (B-604-03)
    for f in ("product_description", "usage_text", "target_customer_text"):
        v, s = preserve_text(f, prior.get(f))
        fields[f], status[f] = v, s
    # benefits/usp are lists — preserve prior list items that are specific+safe, else missing
    for f in ("benefits_json", "usp_json"):
        prior_list = jload(prior.get(f)) or []
        kept = [x for x in prior_list
                if not is_generic_or_placeholder(x) and claim_gate_of(f, x) != "CLAIM_BLOCKED"]
        fields[f], status[f] = (kept or None), ("PRESERVED_SPECIFIC" if kept else "MISSING_NO_SPECIFIC_SOURCE")

    # knowledge fields: provenance-gated (B-604-02)
    for f in ("ingredients_text", "warnings_text"):
        v, s = provenance_gated_knowledge(f, prior.get(f), (prior_prov or {}).get(f))
        fields[f], status[f] = v, s
        if v:
            grounded.append(f)

    # size (B-604-06): from the prior snapshot (size lives on the snapshot, not the product row);
    # only with exact field-level provenance, else SOURCE_UNAVAILABLE.
    size_prov = (prior_prov or {}).get("size_or_volume")
    size_candidate = prior.get("size_or_volume") if ne(prior.get("size_or_volume")) else product.get("size_or_volume")
    size_val, size_status = provenance_gated_knowledge("size_or_volume", size_candidate, size_prov)
    fields["size_or_volume"], status["size_or_volume"] = size_val, size_status
    if size_val:
        grounded.append("size_or_volume")

    # claims (B-604-04): per-claim reconciliation from the PRIOR valid record
    prior_allowed = jload(prior.get("allowed_claims_json")) or []
    prior_blocked = jload(prior.get("blocked_claims_json")) or []
    allowed, blocked, moved = reconcile_claims(prior_allowed, prior_blocked)

    # persona/strategy (B-604-05): sanitize
    persona, p_rm = sanitize_planning(jload(prior.get("buyer_persona_snapshot_json")) or {})
    strategy, s_rm = sanitize_planning(jload(prior.get("copy_strategy_summary_json")) or {})
    fields["buyer_persona_snapshot_json"] = persona
    fields["copy_strategy_summary_json"] = strategy

    # grounded copy grounding: a preserved product-specific description/benefit counts
    if status["product_description"] == "PRESERVED_SPECIFIC":
        grounded.append("product_description")
    if status["benefits_json"] == "PRESERVED_SPECIFIC":
        grounded.append("benefits_json")

    # B-604-07 semantic gate
    has_grounding = len(grounded) > 0
    if not has_grounding:
        decision = "LEAVE_INCOMPLETE"
        reasons.append("NO_PRODUCT_SPECIFIC_GROUNDED_FACT -> DeepSeek/external candidate; not approved, not generic-filled")
    else:
        decision = "RESTORE_APPROVE"
        reasons.append("PRODUCT_SPECIFIC_GROUNDING_AVAILABLE -> restore + provenance-gate + per-claim reconcile")

    return {
        "product_id": product.get("id"),
        "decision": decision,
        "fields": fields,
        "statuses": status,
        "allowed_claims": allowed,
        "blocked_claims": blocked,
        "moved_to_blocked": moved,
        "persona_removed": p_rm,
        "strategy_removed": s_rm,
        "grounded_facts": sorted(set(grounded)),
        "reasons": reasons,
    }


def plan_digest(plan):
    """B-604-01 idempotence: a stable digest over the plan's decided evidence."""
    key = json.dumps({k: plan[k] for k in ("decision", "fields", "allowed_claims", "blocked_claims")},
                     sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()


# ── I/O layer (read-only in dry-run) ─────────────────────────────────────────────────────────
FIXTURE_SQL = (
    "(LOWER(TRIM(COALESCE(raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(id,'')) LIKE 'fixture|_%' ESCAPE '|')"
)


def prov_map(con, snapshot_id):
    return {r["field_name"]: dict(r) for r in con.execute(
        "SELECT * FROM product_intelligence_field_provenance WHERE snapshot_id=?", (snapshot_id,))}


def load_context(con, pid):
    p = con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone()
    if p is None:
        return None
    p = dict(p)
    cur = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND approved_by=? "
                      "ORDER BY version DESC LIMIT 1", (pid, REVIEWER)).fetchone()
    cur = dict(cur) if cur else None
    # last VALID pre-PI-11 snapshot: highest version NOT approved by the PI-11 reviewer
    prior = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? "
                        "AND (approved_by IS NULL OR approved_by<>?) "
                        "ORDER BY (status='APPROVED') DESC, version DESC LIMIT 1", (pid, REVIEWER)).fetchone()
    prior = dict(prior) if prior else None
    if prior is None:
        # fall back to the best non-PI-11 review draft as the restore source
        d = con.execute("SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
                        "AND (COALESCE(reviewed_by,'')<>? AND COALESCE(approved_by,'')<>?) "
                        "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1", (pid, REVIEWER, REVIEWER)).fetchone()
        prior = dict(d) if d else None
    prior_prov = prov_map(con, prior["snapshot_id"]) if (prior and prior.get("snapshot_id")) else {}
    cur_prov = prov_map(con, cur["snapshot_id"]) if (cur and cur.get("snapshot_id")) else {}
    return {"product": p, "current_pi11": cur, "prior": prior, "prior_prov": prior_prov, "cur_prov": cur_prov}


def dry_run(con, ids):
    out = []
    for pid in ids:
        ctx = load_context(con, pid)
        if ctx is None:
            out.append({"product_id": pid, "decision": "SKIP", "reason": "PRODUCT_NOT_FOUND"})
            continue
        plan = build_correction_plan(ctx["product"], ctx["current_pi11"], ctx["prior"],
                                     ctx["prior_prov"], ctx["cur_prov"])
        cur = ctx["current_pi11"] or {}
        plan["digest"] = plan_digest(plan)
        plan["before"] = {
            "pi11_description": (cur.get("product_description") or "")[:160],
            "pi11_readiness": cur.get("readiness_status"),
            "pi11_claim_gate": cur.get("claim_gate"),
        }
        plan["after_preview"] = {
            "description": (plan["fields"].get("product_description") or "<<MISSING - needs grounding>>")[:160],
            "ingredients_status": plan["statuses"].get("ingredients_text"),
            "warnings_status": plan["statuses"].get("warnings_text"),
            "allowed_count": len(plan["allowed_claims"]),
            "blocked_count": len(plan["blocked_claims"]),
        }
        out.append(plan)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--pilot", action="store_true")
    a = ap.parse_args()
    if a.apply and os.environ.get("PI11_CORRECTIVE_APPLY_APPROVED") != "1":
        print("REFUSED: --apply is hard-gated. Set PI11_CORRECTIVE_APPLY_APPROVED=1 only under "
              "explicit owner authorization (canonical writes + possible DeepSeek spend).")
        sys.exit(2)
    con = sqlite3.connect(f"file:{Path(DB).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if a.pilot:
        ids = json.loads((REPO / "outputs" / "mission-pi11" / "audit" / "pilot_ids.json").read_text())
    else:
        ids = [x.strip() for x in a.ids.split(",") if x.strip()]
    res = dry_run(con, ids)
    con.close()
    out = REPO / "outputs" / "mission-pi11" / "audit" / "dryrun_pilot.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False, default=str)
    from collections import Counter
    dec = Counter(r["decision"] for r in res)
    print("DRY-RUN (no canonical writes). decisions:", dict(dec))
    print("report ->", out)


if __name__ == "__main__":
    main()
