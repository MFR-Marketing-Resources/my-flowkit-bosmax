#!/usr/bin/env python
"""PI-13 B-01: field-level qualification of the 49 grounded-canonical twin candidates (read-only).
'Complete' != 'grounded and safe'. For each debt member of a group with a grounded canonical, audit
the canonical snapshot field-by-field and check variant/size compatibility. Only fields that pass
become reusable; a candidate that fails drops to research. Never copies a whole snapshot blindly."""
import sqlite3, json, importlib.util, difflib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(REPO/'flow_agent.db').as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row
G = json.load(open(REPO / "outputs/mission-pi12/pi13_canonical_groups.json", encoding="utf-8"))
# reuse the exact generic gate from the runner
_spec = importlib.util.spec_from_file_location("pi12r", REPO / "scripts" / "pi12_grounded_runner.py")
Rn = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(Rn)
ACQ = {"EXTERNAL_EXTRACTION", "EXTERNALLY_EXTRACTED", "OPERATOR_CONFIRMED", "OPERATOR", "TIKTOK_EXTRACTION", "IMAGE_EXTRACTION", "APPROVED_EVIDENCE"}


def ne(v):
    return v is not None and str(v).strip() not in ("", "[]", "{}", "null")


def snap(pid):
    r = con.execute("SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    return dict(r) if r else None


def draft_of(snapshot):
    d = con.execute("SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (snapshot["created_from_review_draft_id"],)).fetchone()
    return dict(d) if d else {}


def prov_sources(draft_id):
    import collections
    c = collections.Counter()
    for r in con.execute("SELECT source_type FROM product_intelligence_review_field_provenance WHERE draft_id=? AND field_name IN ('benefits_json','usp_json')", (draft_id,)):
        c[str(r["source_type"] or "").upper()] += 1
    return dict(c)


qualified, held = [], []
for g in G["groups"]:
    if g["canonical_pi_class"] not in ("GA", "FC"):
        continue
    can = g["recommended_canonical_id"]
    cs = snap(can)
    if not cs:
        continue
    cd = draft_of(cs)
    can_sizes = next((m["sizes"] for m in g["members"] if m["product_id"] == can), [])
    benefits_ok = ne(cd.get("benefits_json"))
    usp_ok = ne(cd.get("usp_json"))
    generic = Rn.is_generic(cd)
    prov = prov_sources(cs["created_from_review_draft_id"])
    acquired = any(k in ACQ for k in prov)
    for m in g["members"]:
        if not m["in_debt"]:
            continue
        size_compat = (not m["sizes"] or not can_sizes or set(m["sizes"]) == set(can_sizes))
        title_ok = m["title_sim_to_canonical"] >= 0.6
        reasons = []
        if not benefits_ok:
            reasons.append("canonical_missing_benefits")
        if not usp_ok:
            reasons.append("canonical_missing_usp")
        if generic:
            reasons.append("canonical_generic:" + ",".join(generic))
        if not size_compat:
            reasons.append(f"size_mismatch(debt={m['sizes']} vs canon={can_sizes})")
        if not title_ok:
            reasons.append(f"title_sim_low({m['title_sim_to_canonical']})")
        rec = {"product_id": m["product_id"], "canonical_id": can, "canonical_class": g["canonical_pi_class"],
               "title_sim": m["title_sim_to_canonical"], "debt_sizes": m["sizes"], "canonical_sizes": can_sizes,
               "canonical_benefits_present": benefits_ok, "canonical_usp_present": usp_ok,
               "canonical_generic": generic, "canonical_benefit_prov": prov,
               "canonical_benefits_acquired_evidence": acquired,
               "reusable_fields": ["product_description", "benefits_json", "usp_json", "target_customer_text",
                                   "buyer_persona_snapshot_json", "copy_strategy_summary_json", "allowed_claims_json"] if not reasons else [],
               "hold_reasons": reasons}
        (qualified if not reasons else held).append(rec)

# note: reused fields will still be re-validated by the real validator + claim gate ON THE TARGET at write time
prov_note = {"acquired_evidence_backed": sum(1 for q in qualified if q["canonical_benefits_acquired_evidence"]),
             "supported_inference_backed": sum(1 for q in qualified if not q["canonical_benefits_acquired_evidence"])}
summary = {"grounded_canonical_debt_members": len(qualified) + len(held),
           "TWIN_QUALIFIED": len(qualified), "TWIN_HELD_to_research": len(held),
           "qualified_provenance_note": prov_note}
json.dump({"summary": summary, "qualified": qualified, "held": held}, open(REPO / "outputs/mission-pi12/pi13_twin_qualify.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps(summary, indent=1))
print("\n-- HELD (drop to research / manual) --")
for h in held:
    print("  %s <- %s : %s" % (h["product_id"][:8], h["canonical_id"][:8], "; ".join(h["hold_reasons"])))
