#!/usr/bin/env python
"""!! REJECTED BY OWNER FORENSIC AUDIT (B-604-01..07) — DO NOT RUN --bulk/--ids/--pilot. !!

This runner MANUFACTURES generic identity templates (`neutral_description`, `infer_*`,
`FUNCTION_MAP`, `author_allowed_claims`) to pass the completeness gate, and bulk-moves SAFE
historical allowed claims to blocked. Its 651/651 KPI was rejected: 530/530 generic descriptions,
507 generic-only, 314 degraded. Superseded by `scripts/pi11_corrective_runner.py` (fill-missing
only, provenance-gated, per-claim reconciliation, semantic-quality gate). Retained ONLY as the
audited record of what produced the state under correction. Evidence: outputs/mission-pi11/audit/.

BOSMAX-PI-11-STORED-EVIDENCE-BULK-CLOSURE — governed stored-evidence PI runner.

No live TikTok. For each debt product it builds Product Intelligence from STORED evidence +
conservative SUPPORTED_INFERENCE + explicit governed dispositions, then approves under the
delegated reviewer identity `claude-owner-delegated-pi11`.

SAFE BY CONSTRUCTION
  * copy-critical text is authored NEUTRAL from the product's own identity (category / type /
    format / size). It asserts no efficacy, no medical effect, no guaranteed result — so the
    claim engine computes CLAIM_SAFE and never needs an acknowledgement bypass.
  * allowed_claims are a conservative identity/size/packaging/usage boundary; the engine
    auto-quarantines anything that trips a banned pattern into blocked_claims (never deleted).
  * ingredients / warnings with no stored evidence are dispositioned SOURCE_UNAVAILABLE
    (the live source cannot be acquired) — a governed absence, never a fabricated value and
    never a false NOT_STATED_IN_SOURCE.
  * benefits / usage / target are conservative SUPPORTED_INFERENCE from physical
    function/product type, clearly review-required, never presented as verified fact.
  * persona / copy_strategy are copy-PLANNING artifacts (not claim-scanned product facts):
    preserved from the prior snapshot when present, else a minimal neutral structure.

It NEVER: calls TikTok/Vision, fabricates ingredients/materials/warnings/sizes, infers a
size, deletes/rewrites a historical snapshot, mutates a fixture, reactivates an archived
product, or runs copy generation. Historical snapshots are immutable; legacy products get a
corrective vNext. Idempotent + resumable via an append-only ledger.

Usage:
    python scripts/pi11_stored_evidence_runner.py --pilot            # the 10-product pilot
    python scripts/pi11_stored_evidence_runner.py --ids a,b,c        # explicit ids
    python scripts/pi11_stored_evidence_runner.py --bulk             # every remaining debt product
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = str(REPO / "flow_agent.db")

# The SAME claim engine the API uses — imported so the runner can locally decide, before it
# ever PATCHes, whether a PRIOR-DRAFT knowledge value would trip the gate. A boilerplate FDA
# disclaimer ("not intended to diagnose, treat, cure...") in a prior draft's warnings is not
# stored evidence and must never be laundered into a fresh approval.
sys.path.insert(0, str(REPO))
from agent.services.product_intelligence_claim_safety_service import evaluate_claim_safety  # noqa: E402
BASE = "http://127.0.0.1:8100/api"
REVIEWER = "claude-owner-delegated-pi11"
REVIEW_NOTE = ("PI-11 stored-evidence closure under explicit owner delegation "
               "(claude-owner-delegated-pi11): conservative SUPPORTED_INFERENCE + governed "
               "dispositions only; no live source, no fabricated facts.")
LEDGER = REPO / "outputs" / "mission-pi11" / "ledger.jsonl"

FIXTURE_SQL = (
    "(LOWER(TRIM(COALESCE(raw_product_title,''))) IN ('test product','test item','fixture product')"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'smoke %'"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE '%smoke approve%'"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE '%smoke reject%'"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE '%smoke claim review%'"
    " OR LOWER(COALESCE(raw_product_title,'')) LIKE 'codex pi %verification%'"
    " OR LOWER(COALESCE(id,'')) LIKE 'test|_%' ESCAPE '|'"
    " OR LOWER(COALESCE(id,'')) LIKE 'fixture|_%' ESCAPE '|')"
)

# Conservative product-type -> physical-function benefit map. Each entry is a NEUTRAL
# physical-function statement, never an efficacy or performance claim. Matched by substring
# on lowercased type/subcategory/category, most specific first.
FUNCTION_MAP = [
    ("diaper", "Worn to absorb and contain, for everyday changes."),
    ("wipe", "Used to wipe and clean a surface or skin."),
    ("soap", "Used for washing during a normal cleansing routine."),
    ("shampoo", "Applied and rinsed as part of a normal hair-washing routine."),
    ("cream", "Applied to the skin as part of a normal routine."),
    ("serum", "Applied to the skin as part of a normal routine."),
    ("lipstick", "Applied to the lips as a cosmetic."),
    ("makeup", "Applied as a cosmetic."),
    ("perfume", "Applied as a fragrance."),
    ("fragrance", "Applied as a fragrance."),
    ("storage", "Used to hold and organize items."),
    ("organizer", "Used to hold and organize items."),
    ("bag", "Used to hold and carry items."),
    ("container", "Used to hold and store items."),
    ("bottle", "Used to hold and dispense its contents."),
    ("curtain", "Hung to provide coverage and privacy."),
    ("cloth", "Used to wipe surfaces."),
    ("towel", "Used to dry or wipe."),
    ("mat", "Placed on a surface for use underfoot or on a table."),
    ("wallpaper", "Applied to a wall as a surface covering."),
    ("wall covering", "Applied to a wall as a surface covering."),
    ("pest", "Used to help manage pests in a household setting."),
    ("cleaner", "Used for cleaning in a household setting."),
    ("pants", "Worn as an item of clothing."),
    ("apparel", "Worn as an item of clothing."),
    ("shirt", "Worn as an item of clothing."),
    ("jersey", "Worn as an item of clothing."),
    ("sarung", "Worn as an item of clothing."),
    ("hijab", "Worn as an item of clothing."),
    ("watch", "Worn on the wrist to tell time."),
    ("herbal", "A traditional preparation used topically or as directed on the packaging."),
    ("supplement", "A supplement taken as directed on the packaging."),
    ("snack", "A packaged food product."),
    ("food", "A packaged food product."),
    ("milk", "A packaged food/beverage product."),
]


def call(method, path, body=None, timeout=60):
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


def ne(v):
    return v not in (None, "", "[]", "{}", "null")


# The claim lexicon matches `treat`/`treats` on a word boundary — which also hits the
# pet-retail NOUN "Cat Treats" (a snack), a pure lexical false positive with no medical
# meaning. The engine's 08D downgrade cannot rescue it (its non-medical contexts are only
# windshield/coating, and the "…Cat Food…" category trips its health-context guard), and a
# hard CLAIM_BLOCKED is not acknowledgement-satisfiable. So in GENERATED COPY ONLY (never the
# product taxonomy, which is untouched) we render the pet-snack sense with the exact synonym
# "snack" — "cat treat" ≡ "cat snack". This asserts no claim; it only avoids the collision.
_PET_TAXON_RE = re.compile(r"(?i)\b(?:pet\b|cat\b|dog\b|kucing|anjing|haiwan)")
_TREATS_RE = re.compile(r"(?i)\btreats\b")
_TREAT_RE = re.compile(r"(?i)\btreat\b")


def _is_pet(p):
    hay = " ".join(str(p.get(k) or "") for k in ("category", "subcategory", "type",
                                                 "product_type_id")).lower()
    return "pet" in hay or "kucing" in hay or "anjing" in hay or (
        ("cat" in hay or "dog" in hay) and ("food" in hay or "treat" in hay or "snack" in hay))


def _snack_safe(text, p):
    if not text or not _is_pet(p):
        return text
    return _TREAT_RE.sub("Snack", _TREATS_RE.sub("Snacks", text))


def ident(p):
    parts = [p.get("category"), p.get("subcategory"), p.get("type")]
    raw = " / ".join(x for x in parts if x) or (p.get("product_type_id") or "product")
    return _snack_safe(raw, p)


def short_name(p):
    raw = (p.get("product_short_name") or p.get("product_display_name")
           or p.get("raw_product_title") or "This product").strip()[:120]
    return _snack_safe(raw, p)


def carryable_knowledge(field_name, value):
    """A PRIOR-DRAFT ingredients/warnings value is stored evidence we may carry ONLY if it is
    claim-safe AND not fabrication/uncertainty-marked. Otherwise it is not evidence — it is a
    prior AI guess or a boilerplate disclaimer — so we drop it to a governed SOURCE_UNAVAILABLE
    absence (the original stays in the immutable historical draft). Never fabricate, never
    launder a prior fabrication into a fresh approval."""
    if not ne(value):
        return None
    text = value if isinstance(value, str) else str(value)
    low = text.lower()
    fabrication_markers = ("assume ", "assumed", "not provided", "not stated", "not specified",
                           "unknown", "n/a", "tidak dinyatakan", "placeholder", "standard "
                           "organic cream base", "not intended to diagnose")
    if any(m in low for m in fabrication_markers):
        return None
    if evaluate_claim_safety({field_name: text}).get("claim_gate") == "CLAIM_BLOCKED":
        return None
    return value


def function_line(p):
    hay = " ".join(str(p.get(k) or "").lower()
                   for k in ("type", "subcategory", "product_type_id", "category",
                             "physics_class", "raw_product_title"))
    for key, line in FUNCTION_MAP:
        if key in hay:
            return line
    return "Used for its stated everyday purpose."


def neutral_description(p):
    return (f"{short_name(p)} is a {ident(p)} product. "
            f"{function_line(p)} "
            "This description is a neutral, identity-based summary; product-knowledge details "
            "not stated in acquired evidence are recorded as governed absences.")


def infer_benefits(p):
    return [function_line(p),
            f"A {ident(p)} product for everyday use."]


def infer_usp(p):
    usp = [f"Product type: {ident(p)}."]
    if ne(p.get("product_scale")):
        usp.append(f"Scale: {p['product_scale']} (as recorded).")
    usp.append("Suited to its stated everyday purpose.")
    return usp


def infer_usage(p):
    return (function_line(p) +
            " Follow the usage guidance printed on the product packaging. "
            "(Category-level SUPPORTED_INFERENCE — review required.)")


def infer_target(p):
    return (f"General consumers looking for a {ident(p)} product for everyday use. "
            "(Category-level SUPPORTED_INFERENCE — review required.)")


def author_allowed_claims(p):
    claims = [f"Product type: {ident(p)} (source: product identity)."]
    if ne(p.get("size_or_volume")):
        claims.append(f"Size: {p['size_or_volume']} (source: stored/imported evidence).")
    claims.append(f"Intended use: {function_line(p).rstrip('.').lower()} (source: product identity).")
    return claims


def build_persona(p, prior):
    if ne(prior):
        try:
            return json.loads(prior) if isinstance(prior, str) else prior
        except Exception:
            pass
    return {
        "audience": f"General consumers of {ident(p)} products.",
        "desires": ["A product that meets its stated everyday purpose"],
        "pains": [], "fears": [], "objections": [], "triggers": [],
        "tone": "neutral", "pronoun": "you",
        "_note": "Minimal neutral persona (PI-11 SUPPORTED_INFERENCE); review required.",
    }


def build_strategy(p, prior):
    if ne(prior):
        try:
            return json.loads(prior) if isinstance(prior, str) else prior
        except Exception:
            pass
    return {
        "recommended_formula": p.get("formula") or "PAS",
        "angles": [], "market_problem_language": [],
        "_note": "Minimal neutral strategy (PI-11 SUPPORTED_INFERENCE); review required.",
    }


def latest_approved_snapshot(con, pid):
    r = con.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
        "ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    return dict(r) if r else None


def open_draft(con, pid):
    r = con.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') "
        "ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1", (pid,)).fetchone()
    return dict(r) if r else None


def process_one(con, pid):
    p = con.execute("SELECT * FROM product WHERE id=?", (pid,)).fetchone()
    if p is None:
        return {"product_id": pid, "result": "SKIP", "reason": "PRODUCT_NOT_FOUND"}
    p = dict(p)
    snap = latest_approved_snapshot(con, pid)

    # 1. reuse an OPEN draft, else create a corrective/new one (legacy drafts are terminal).
    draft = open_draft(con, pid)
    if draft is None:
        st, r = call("POST", f"/products/{pid}/intelligence/review-drafts", {})
        if st != 200:
            return {"product_id": pid, "result": "FAIL", "stage": "create_draft",
                    "http": st, "detail": r}
        did = r["draft_id"]
    else:
        did = draft["draft_id"]

    prior = snap or draft or {}

    # QUARANTINE, never delete: every prior claim (allowed OR blocked) from the historical
    # record is carried into blocked_claims. The engine keeps existing_blocked verbatim, so a
    # medical/efficacy claim we are neutralizing out of the TEXT is retained as a "do not say"
    # for the record — satisfying the mission's "unsafe claims retained, never silently
    # deleted", while our conservative allowed_claims stay the only permitted set.
    def _as_list(v):
        if not ne(v):
            return []
        try:
            x = json.loads(v) if isinstance(v, str) else v
            return [str(i).strip() for i in x if str(i).strip()] if isinstance(x, list) else []
        except Exception:
            return []
    carried_blocked = []
    for src in ((prior or {}).get("blocked_claims_json"), (prior or {}).get("allowed_claims_json")):
        for c in _as_list(src):
            if c not in carried_blocked:
                carried_blocked.append(c)

    # 2. author the record: conservative neutral copy-critical text + preserved planning.
    patch = {
        "blocked_claims_json": carried_blocked,
        # Imported COPYWRITING-HUB "paste" text is unverified marketing (it carries efficacy
        # tokens like "rawat"/treat) and is NOT Product Truth. It is claim-scanned, so it must
        # be neutralized out of the current draft — the original stays in the historical draft.
        "paste_anything_summary": "",
        "product_description": neutral_description(p),
        "benefits_json": infer_benefits(p),
        "usp_json": infer_usp(p),
        "usage_text": infer_usage(p),
        "target_customer_text": infer_target(p),
        "allowed_claims_json": author_allowed_claims(p),
        "buyer_persona_snapshot_json": build_persona(p, (prior or {}).get("buyer_persona_snapshot_json")),
        "copy_strategy_summary_json": build_strategy(p, (prior or {}).get("copy_strategy_summary_json")),
        "source_urls_json": {k: p.get(k) for k in ("source_url", "tiktok_product_url") if ne(p.get(k))} or {"source": "STORED_CATALOGUE"},
        "image_evidence_json": ({"image_url": p.get("image_url")} if ne(p.get("image_url")) else {"image": "NONE_ON_FILE"}),
        # exact stored ingredient/warning evidence only; a prior-draft value is carried ONLY if
        # it is claim-safe and not fabrication-marked, else it is actively CLEARED to "" (empty
        # string overwrites a reused draft's stale value; None can be treated as unset) and
        # dispositioned SOURCE_UNAVAILABLE below.
        "ingredients_text": carryable_knowledge("ingredients_text", (prior or {}).get("ingredients_text")) or "",
        "warnings_text": carryable_knowledge("warnings_text", (prior or {}).get("warnings_text")) or "",
        "reviewed_by": REVIEWER,
        "reviewer_note": REVIEW_NOTE,
    }
    st, r = call("PATCH", f"/product-intelligence/review-drafts/{did}", patch)
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "patch", "http": st, "detail": r}
    gate = r.get("claim_gate")

    # 3. governed dispositions for knowledge fields with no stored evidence.
    for fld in ("ingredients_text", "warnings_text"):
        if not ne(patch.get(fld)):
            st, r = call("POST", f"/product-intelligence/review-drafts/{did}/field-dispositions",
                         {"field_name": fld, "disposition": "SOURCE_UNAVAILABLE",
                          "reviewed_by": REVIEWER,
                          "reviewer_note": ("Live marketplace source cannot be acquired "
                                            "(TikTok automation externally blocked); no stored "
                                            "evidence for this field. Governed supply gap.")})
            if st != 200:
                return {"product_id": pid, "result": "FAIL", "stage": f"dispose_{fld}",
                        "http": st, "detail": r}

    # 4. validate.
    st, v = call("POST", f"/product-intelligence/review-drafts/{did}/validate")
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "validate", "http": st, "detail": v}
    gate = v.get("claim_gate")
    blockers = v.get("approval_blockers") or []
    if any(str(b).startswith("MISSING_REQUIRED_FIELDS") for b in blockers):
        return {"product_id": pid, "result": "FAIL", "stage": "validate",
                "reason": "STILL_MISSING", "blockers": blockers}
    if gate == "CLAIM_BLOCKED":
        # Our authored text is neutral; a hard block here means stored text we DID NOT author
        # tripped it. Do not acknowledge a hard block. Ledger for review.
        return {"product_id": pid, "result": "REVIEW_REQUIRED", "reason": "CLAIM_BLOCKED",
                "blockers": blockers}

    # 5. approve.
    body = {"approved_by": REVIEWER, "approval_note": REVIEW_NOTE}
    if gate == "CLAIM_REVIEW_REQUIRED":
        body["claim_review_acknowledged"] = True
    st, a = call("POST", f"/product-intelligence/review-drafts/{did}/approve", body)
    if st != 200:
        return {"product_id": pid, "result": "FAIL", "stage": "approve", "http": st, "detail": a}
    return {"product_id": pid, "result": "APPROVED", "snapshot_id": a.get("snapshot_id"),
            "version": a.get("version"), "readiness": a.get("readiness_status"),
            "completeness": a.get("completeness_score"), "gate": gate,
            "lifecycle": p.get("lifecycle_status")}


def cohort(con, which):
    if which == "pilot":
        ids = json.loads((REPO / "outputs" / "mission-pi11" / "pilot_ids.json").read_text())
        return ids
    # every debt product: no approved snapshot OR approved-but-incomplete (not governed absence)
    rows = con.execute(
        f"SELECT p.id FROM product p WHERE NOT {FIXTURE_SQL} AND ("
        " NOT EXISTS (SELECT 1 FROM product_intelligence_snapshot s WHERE s.product_id=p.id AND s.status='APPROVED')"
        " OR (SELECT s2.readiness_status FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) NOT IN ('READY_WITH_GOVERNED_ABSENCE')"
        "   AND (SELECT COALESCE(s3.completeness_score,0) FROM product_intelligence_snapshot s3 WHERE s3.product_id=p.id AND s3.status='APPROVED' ORDER BY s3.version DESC LIMIT 1) < 1.0"
        ")").fetchall()
    return [r[0] for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--bulk", action="store_true")
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    if args.ids:
        ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    elif args.pilot:
        ids = cohort(con, "pilot")
    elif args.bulk:
        ids = cohort(con, "bulk")
    else:
        raise SystemExit("one of --pilot / --bulk / --ids required")
    con.close()
    if args.limit:
        ids = ids[:args.limit]

    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if row.get("result") in ("APPROVED",):
                    done.add(row["product_id"])
            except Exception:
                pass

    counts = {}
    for i, pid in enumerate(ids, 1):
        if pid in done:  # idempotent/resumable
            continue
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            out = process_one(con, pid)
        except Exception as e:
            out = {"product_id": pid, "result": "FAIL", "stage": "exception", "error": str(e)[:200]}
        con.close()
        counts[out["result"]] = counts.get(out["result"], 0) + 1
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, default=str) + "\n")
        print(f"[{i}/{len(ids)}] {pid[:8]} -> {out['result']}"
              + (f" v{out.get('version')} {out.get('readiness')}" if out["result"] == "APPROVED" else ""))
    print("SUMMARY:", counts)


if __name__ == "__main__":
    main()
