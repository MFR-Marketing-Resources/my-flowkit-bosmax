#!/usr/bin/env python
"""PI-FINAL Phase 2: live residual manifest — recomputed directly from the canonical DB.

One row per residual canonical product (LEGACY_APPROVED_INCOMPLETE or
MISSING_APPROVED_INTELLIGENCE) plus the unresolved-claim cases, with the exact missing
REQUIRED_FIELDS, claim state, provenance counts and an assigned recovery lane.
"""
from __future__ import annotations
import json, re, sqlite3, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
DB = REPO / "flow_agent.db"
OUT = Path(__file__).resolve().parent


# mirror predicates (kept in sync with phase0_baseline_backup.py / reporting_service.py)
HAS_APPROVED = ("EXISTS (SELECT 1 FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED')")
LATEST_READY = ("(SELECT s2.readiness_status FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED' ORDER BY s2.version DESC LIMIT 1)")
LATEST_COMPL = ("(SELECT s2.completeness_score FROM product_intelligence_snapshot s2 "
                "WHERE s2.product_id = p.id AND s2.status = 'APPROVED' ORDER BY s2.version DESC LIMIT 1)")
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
LEGACY = (f"({HAS_APPROVED} AND COALESCE({LATEST_READY},'') <> 'READY_WITH_GOVERNED_ABSENCE' "
          f"AND COALESCE({LATEST_COMPL},0) < 1.0)")
MISSING = f"NOT {HAS_APPROVED}"

REQUIRED_FIELDS = ("product_description", "benefits_json", "usp_json", "usage_text",
                   "ingredients_text", "warnings_text", "target_customer_text",
                   "allowed_claims_json", "buyer_persona_snapshot_json",
                   "copy_strategy_summary_json", "source_urls_json", "image_evidence_json",
                   "claim_gate", "claim_risk_level")

REGULATED_RE = re.compile(
    r"supplement|vitamin|health|wellness|herbal|jamu|whiten|anti[- ]?inflammat|hair.?loss|"
    r"weight.?loss|slimming|hormon|libido|pet.?food|pet.?nutrition|pesticide|pest|baby|infant|"
    r"child|therap|disease|medic|collagen|probiotic|detox|serum|treatment|cream|tonic|kkm|"
    r"halal|obat|ubat|kesihatan|kecantikan", re.I)


def empty(v) -> bool:
    return v is None or str(v).strip() in ("", "[]", "{}", "null")


def main() -> int:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = []
    for klass, pred in (("LEGACY_APPROVED_INCOMPLETE", LEGACY), ("MISSING_APPROVED_INTELLIGENCE", MISSING)):
        for p in con.execute(f"SELECT p.* FROM product p WHERE {REAL} AND {pred} ORDER BY p.id"):
            pid = p["id"]
            snap = con.execute(
                "SELECT * FROM product_intelligence_snapshot WHERE product_id=? AND status='APPROVED' "
                "ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
            open_draft = con.execute(
                "SELECT draft_id, review_status, claim_gate, claim_tokens_json, revision_reason "
                "FROM product_intelligence_review_draft WHERE product_id=? "
                "AND review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') LIMIT 1", (pid,)).fetchone()
            latest_term = con.execute(
                "SELECT draft_id, review_status FROM product_intelligence_review_draft WHERE product_id=? "
                "ORDER BY COALESCE(updated_at, created_at) DESC LIMIT 1", (pid,)).fetchone()
            authority = snap if snap else None
            missing = []
            if authority is not None:
                missing = [f for f in REQUIRED_FIELDS if empty(authority[f])]
            else:
                missing = list(REQUIRED_FIELDS)
            prov_n = con.execute(
                "SELECT COUNT(*) FROM product_intelligence_review_field_provenance WHERE product_id=?",
                (pid,)).fetchone()[0]
            title = p["raw_product_title"] or ""
            cat_blob = " ".join(str(p[k] or "") for k in ("category", "subcategory", "type", "product_type", "silo"))
            regulated = bool(REGULATED_RE.search(title + " " + cat_blob))
            copy_sets = con.execute(
                "SELECT COUNT(*) FROM copy_set WHERE product_id=?", (pid,)).fetchone()[0]
            has_url = bool(p["tiktok_product_url"] or p["source_url"])
            if klass == "LEGACY_APPROVED_INCOMPLETE":
                lane = "REGULATED_ACQUIRED_ONLY" if regulated else "LOW_RISK_ACQUIRED_PLUS_INFERENCE"
            else:
                lane = ("EXHAUSTION_CANDIDATE_PENDING_FULL_SEARCH" if not has_url and not title
                        else ("REGULATED_ACQUIRED_ONLY" if regulated else "LOW_RISK_ACQUIRED_PLUS_INFERENCE"))
            rows.append({
                "product_id": pid, "class": klass,
                "raw_product_title": title,
                "display_name": p["product_display_name"] or p["product_short_name"],
                "lifecycle": p["lifecycle_status"], "archived_reason": p["archived_reason"],
                "brand": p["brand"], "shop_name": p["shop_name"],
                "category": p["category"], "subcategory": p["subcategory"], "type": p["type"],
                "product_type": p["product_type"], "silo": p["silo"],
                "size_or_volume_product": None,
                "source_url": p["source_url"], "tiktok_product_url": p["tiktok_product_url"],
                "image_url": p["image_url"], "local_image_path": p["local_image_path"],
                "approved_snapshot_id": snap["snapshot_id"] if snap else None,
                "approved_version": snap["version"] if snap else None,
                "approved_readiness": snap["readiness_status"] if snap else None,
                "approved_completeness": snap["completeness_score"] if snap else None,
                "open_draft": dict(open_draft) if open_draft else None,
                "latest_terminal_draft": dict(latest_term) if latest_term else None,
                "missing_fields": missing,
                "claim_gate": (snap["claim_gate"] if snap else None),
                "claim_tokens": (snap["claim_tokens_json"] if snap else None),
                "claim_risk_product": p["claim_risk_level"],
                "provenance_rows": prov_n,
                "copy_sets": copy_sets,
                "regulated": regulated,
                "lane": lane,
                "evidence_strength": ("STORED_URL" if has_url else "TITLE_ONLY" if title else "NONE"),
                "next_action": "RESEARCH_THEN_REVISION_WRITE",
            })
    # unresolved claim queue: canonical real products whose LATEST approved snapshot gate is not safe
    claim_rows = [dict(r) for r in con.execute(
        f"SELECT p.id AS product_id, p.raw_product_title, p.lifecycle_status, "
        f"{LATEST_READY} AS readiness, "
        f"(SELECT s2.claim_gate FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        f" AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) AS latest_gate, "
        f"(SELECT s2.claim_tokens_json FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        f" AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) AS tokens "
        f"FROM product p WHERE {REAL} AND {HAS_APPROVED} "
        f"AND (SELECT s2.claim_gate FROM product_intelligence_snapshot s2 WHERE s2.product_id=p.id "
        f"     AND s2.status='APPROVED' ORDER BY s2.version DESC LIMIT 1) "
        f"    NOT IN ('CLAIM_SAFE')")]
    # open drafts with unsafe gates on canonical real products (stale open review debris)
    open_unsafe = [dict(r) for r in con.execute(
        f"SELECT d.draft_id, d.product_id, d.review_status, d.claim_gate, p.raw_product_title, "
        f"p.lifecycle_status "
        f"FROM product_intelligence_review_draft d JOIN product p ON p.id=d.product_id "
        f"WHERE d.review_status NOT IN ('APPROVED','REJECTED','SUPERSEDED') "
        f"AND COALESCE(d.claim_gate,'') IN ('CLAIM_BLOCKED','CLAIM_REVIEW_REQUIRED') AND {REAL}")]
    out = {
        "residual_total": len(rows),
        "by_class": {k: sum(1 for r in rows if r["class"] == k)
                     for k in ("LEGACY_APPROVED_INCOMPLETE", "MISSING_APPROVED_INTELLIGENCE")},
        "by_lane": {},
        "claim_queue_latest_approved_unsafe": claim_rows,
        "open_drafts_unsafe_gate": open_unsafe,
        "rows": rows,
    }
    for r in rows:
        out["by_lane"][r["lane"]] = out["by_lane"].get(r["lane"], 0) + 1
    (OUT / "residual_manifest.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("residual_total", "by_class", "by_lane")}, indent=1))
    print("claim_queue_latest_approved_unsafe:", len(claim_rows))
    print("open_drafts_unsafe_gate:", len(open_unsafe))
    return 0


if __name__ == "__main__":
    sys.exit(main())
