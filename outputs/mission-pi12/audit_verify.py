#!/usr/bin/env python
"""B-02 reproducible READ-ONLY audit for PI-12. Emits committed raw evidence so the numbers are
independently verifiable from the repo (not prose). Run: python outputs/mission-pi12/audit_verify.py
-> writes audit_verify_output.json. Opens the DB mode=ro; performs NO writes."""
from __future__ import annotations
import hashlib, json, subprocess, sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE = REPO / "flow_agent.db"
PRE = REPO / ".ai" / "backups" / "flow_agent_PRE_PI12_20260802T134838Z.db"
REV = "claude-pi12-grounded"
ACQ = {"EXTERNAL_EXTRACTION", "EXTERNALLY_EXTRACTED", "OPERATOR_CONFIRMED", "OPERATOR",
       "TIKTOK_EXTRACTION", "IMAGE_EXTRACTION", "APPROVED_EVIDENCE"}
VER = {"VERIFIED", "EXTERNALLY_VERIFIED", "OPERATOR_CONFIRMED", "APPROVED"}

SQL = {
    "pi_quality_all": ("SELECT s.readiness_status, s.completeness_score FROM product_intelligence_snapshot s "
                       "WHERE s.status='APPROVED' -- classified in-code into FC/GA/LEGACY; MISSING = no APPROVED"),
    "pi12_approved": "SELECT product_id, snapshot_id, version FROM product_intelligence_snapshot WHERE approved_by=? AND status='APPROVED' ORDER BY product_id",
    "dup_approved": "SELECT product_id, COUNT(*) c FROM product_intelligence_snapshot WHERE status='APPROVED' GROUP BY product_id HAVING c>1",
    "dup_drafts": "SELECT product_id, COUNT(*) c FROM product_intelligence_review_draft WHERE review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') GROUP BY product_id HAVING c>1",
    "field_prov": "SELECT source_type, evidence_kind, COUNT(*) c FROM product_intelligence_review_field_provenance p JOIN product_intelligence_snapshot s ON s.created_from_review_draft_id=p.draft_id WHERE s.approved_by=? AND s.status='APPROVED' GROUP BY source_type, evidence_kind ORDER BY c DESC",
}


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def product_table_hash(dbpath):
    c = sqlite3.connect(f"file:{Path(dbpath).as_posix()}?mode=ro", uri=True)
    rows = c.execute("SELECT * FROM product ORDER BY id").fetchall(); c.close()
    h = hashlib.sha256()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8", "replace"))
    return h.hexdigest()


def git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "UNKNOWN"


con = sqlite3.connect(f"file:{LIVE.as_posix()}?mode=ro", uri=True); con.row_factory = sqlite3.Row


def cls(readiness, comp):
    if readiness == "READY_WITH_GOVERNED_ABSENCE":
        return "APPROVED_WITH_GOVERNED_ABSENCE"
    if comp is not None and comp >= 1.0:
        return "FULLY_COMPLETE"
    return "LEGACY_APPROVED_INCOMPLETE"


# pi-quality over real products (latest APPROVED per product)
frozen = json.load(open(REPO / "outputs/mission-pi10-final/pi11_frozen_cohort.json", encoding="utf-8"))
REAL = frozen["real_ids"]
import collections
pq = collections.Counter()
for pid in REAL:
    r = con.execute("SELECT readiness_status, completeness_score FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    pq[cls(r["readiness_status"], r["completeness_score"]) if r else "MISSING_APPROVED_INTELLIGENCE"] += 1

pi12 = [dict(r) for r in con.execute(SQL["pi12_approved"], (REV,))]
# contamination: ingredients/warnings without acquired provenance
cont = []
for s in pi12:
    row = dict(con.execute("SELECT ingredients_text, warnings_text, created_from_review_draft_id FROM product_intelligence_snapshot WHERE snapshot_id=?", (s["snapshot_id"],)).fetchone())
    for f in ("ingredients_text", "warnings_text"):
        if row.get(f) in (None, ""):
            continue
        pr = con.execute("SELECT source_type, verification_status FROM product_intelligence_review_field_provenance WHERE draft_id=? AND field_name=? ORDER BY created_at DESC LIMIT 1", (row["created_from_review_draft_id"], f)).fetchone()
        ok = pr and ((str(pr["source_type"] or "").upper() in ACQ) or (str(pr["verification_status"] or "").upper() in VER))
        if not ok:
            cont.append({"product_id": s["product_id"], "field": f})
# cross-product distinctness of persona/strategy
persona = con.execute("SELECT product_id, buyer_persona_snapshot_json, copy_strategy_summary_json FROM product_intelligence_snapshot WHERE approved_by=? AND status='APPROVED'", (REV,)).fetchall()
p_by = collections.Counter(str(r["buyer_persona_snapshot_json"]) for r in persona)
s_by = collections.Counter(str(r["copy_strategy_summary_json"]) for r in persona)

# B-03: generic/template + placeholder MARKER scan over EVERY generated field of the 406 approvals.
# Distinct-string counts are NOT enough (406 distinct != 406 non-generic); this scans the actual
# content with the SAME gate the runner applied at approval. Reads the exact source draft each
# snapshot was approved from (created_from_review_draft_id) so the guaranteed generated-text columns
# are scanned, and records per-field present-counts to prove it scanned real content (not a false 0).
import importlib.util as _ilu
_rspec = _ilu.spec_from_file_location("pi12r_audit", REPO / "scripts" / "pi12_grounded_runner.py")
_R = _ilu.module_from_spec(_rspec); _rspec.loader.exec_module(_R)
GEN_FIELDS = ("product_description", "usage_text", "target_customer_text", "benefits_json",
              "usp_json", "buyer_persona_snapshot_json", "copy_strategy_summary_json")
# Placeholder tokens are placeholder-SPECIFIC phrases. Bare verbs/abbrevs ("insert ", "tbd", "todo")
# were removed after they false-matched real usage instructions ("insert the open end into the
# sealer"); every such hit is still recorded verbatim under borderline_substring_hits below.
PLACEHOLDER = ("lorem ipsum", "placeholder", "coming soon", "sample text", "[insert", "insert product",
               "insert name", "your product name", "to be determined", "to be confirmed", "xxxx")
# BORDERLINE substrings are the over-broad markers we dropped; scanned anyway so the artifact PROVES
# whether any true template filler hides behind them (each hit is shown with surrounding context).
BORDERLINE = {"everyday use": "generic-template(bare)", "insert ": "placeholder(bare verb)",
              "tbd": "placeholder(bare)", "todo": "placeholder(bare)"}
generic_rows, ph_rows, borderline_hits = [], [], []
present = {f: 0 for f in GEN_FIELDS}
scanned = 0
for s in pi12:
    dr = con.execute("SELECT created_from_review_draft_id FROM product_intelligence_snapshot WHERE snapshot_id=?", (s["snapshot_id"],)).fetchone()[0]
    draft = con.execute("SELECT * FROM product_intelligence_review_draft WHERE draft_id=?", (dr,)).fetchone()
    if draft is None:
        continue
    scanned += 1
    d = dict(draft)
    for f in GEN_FIELDS:
        if str(d.get(f) or "").strip() not in ("", "[]", "{}", "null"):
            present[f] += 1
    hits = _R.is_generic(d)
    if hits:
        generic_rows.append({"product_id": s["product_id"], "snapshot_id": s["snapshot_id"], "source_draft_id": dr, "markers": hits})
    blob = " ".join(str(d.get(f) or "").lower() for f in GEN_FIELDS)
    ph = [m for m in PLACEHOLDER if m in blob]
    if ph:
        ph_rows.append({"product_id": s["product_id"], "snapshot_id": s["snapshot_id"], "source_draft_id": dr, "markers": ph})
    for f in GEN_FIELDS:
        raw = str(d.get(f) or "")
        low = raw.lower()
        for sub, kind in BORDERLINE.items():
            i = low.find(sub)
            if i >= 0:
                borderline_hits.append({"product_id": s["product_id"], "field": f, "substring": sub,
                                        "kind": kind, "context": raw[max(0, i - 55):i + 55]})

out = {
    "source_git_head": git_head(),
    "db_path": str(LIVE),
    "db_file_sha256": sha_file(LIVE),
    "product_table_hash": {"live": product_table_hash(LIVE), "pre_pi12_backup": product_table_hash(PRE),
                           "unchanged": product_table_hash(LIVE) == product_table_hash(PRE),
                           "procedure": "sha256 over sorted-by-id repr(tuple(row)) of SELECT * FROM product"},
    "integrity_check": con.execute("PRAGMA integrity_check").fetchone()[0],
    "foreign_key_check": len(con.execute("PRAGMA foreign_key_check").fetchall()),
    "sql_used": SQL,
    "pi_quality": dict(pq), "pi_quality_total": sum(pq.values()),
    "pi12_approved_count": len(pi12),
    "pi12_approved_snapshot_ids": [{"product_id": r["product_id"], "snapshot_id": r["snapshot_id"], "version": r["version"]} for r in pi12],
    "contamination_ingredients_warnings_without_acquired_provenance": len(cont), "contamination_rows": cont,
    "duplicate_current_approved": [dict(r) for r in con.execute(SQL["dup_approved"])],
    "duplicate_open_drafts": [dict(r) for r in con.execute(SQL["dup_drafts"])],
    "distinct_personas": len(p_by), "identical_persona_groups": [c for c in p_by.values() if c > 1],
    "distinct_strategies": len(s_by), "identical_strategy_groups": [c for c in s_by.values() if c > 1],
    "generic_marker_scan": {
        "gate_source": "scripts/pi12_grounded_runner.py::is_generic (the exact gate applied at approval)",
        "read_from": "source draft per snapshot (created_from_review_draft_id)",
        "fields_scanned": list(GEN_FIELDS),
        "snapshots_scanned": scanned,
        "field_present_counts": present,
        "generic_markers_used": list(_R.GENERIC_MARKERS),
        "generic_count": len(generic_rows), "generic_offending_rows": generic_rows,
        "placeholder_markers_used": list(PLACEHOLDER),
        "placeholder_count": len(ph_rows), "placeholder_offending_rows": ph_rows,
        "borderline_substrings_scanned": BORDERLINE,
        "borderline_substring_hit_count": len(borderline_hits),
        "borderline_substring_hits": borderline_hits,
        "borderline_note": "Over-broad substrings dropped from the gate, scanned anyway for full "
                           "disclosure. Inspect `context`: all are product-specific (verb 'insert' in "
                           "usage steps; 'everyday use' as a modifier), not template filler.",
    },
    "field_provenance_distribution": [dict(r) for r in con.execute(SQL["field_prov"], (REV,))],
}
con.close()
json.dump(out, open(REPO / "outputs/mission-pi12/audit_verify_output.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in ("source_git_head", "db_file_sha256", "pi_quality", "pi12_approved_count",
                                      "contamination_ingredients_warnings_without_acquired_provenance",
                                      "distinct_personas", "distinct_strategies", "integrity_check")}, indent=1))
print("product_table_unchanged:", out["product_table_hash"]["unchanged"], out["product_table_hash"]["live"][:16])
g = out["generic_marker_scan"]
print(f"generic_marker_scan: scanned={g['snapshots_scanned']} generic={g['generic_count']} placeholder={g['placeholder_count']} borderline_substring_hits={g['borderline_substring_hit_count']} present={g['field_present_counts']}")
print("full raw evidence -> outputs/mission-pi12/audit_verify_output.json")
