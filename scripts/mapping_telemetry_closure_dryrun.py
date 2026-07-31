#!/usr/bin/env python
"""BOSMAX-MAPPING-TELEMETRY-CLOSURE-01 — NULL-cohort read-only dry-run.

Selects ONLY active products whose stored mapping_status IS NULL and runs the canonical
enrich_product(..., persist=False) — it does NOT call the unbounded bulk endpoint and
writes NOTHING to the DB. For each product it records the stored-before value, the
proposed-after value, the exact field-level diff, the evaluator classification
(READY / NEEDS_REVIEW / BLOCKED — never APPROVED, which is a human state), the mapping
confidence/source, and — critically — any EXISTING non-empty field the enrichment would
change (the overwrite-risk set the unbounded endpoint would silently apply).

Evidence: docs/evidence/mapping-telemetry-closure-01/null_cohort_dryrun.json
Prove zero writes by re-running mapping_telemetry_closure_audit.py afterwards and
confirming db_integrity hashes are unchanged.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # allow `python scripts/...` to import the agent package

from agent.db import crud  # noqa: E402
from agent.services.product_intelligence import enrich_product  # noqa: E402
DB = REPO / "flow_agent.db"
OUT = REPO / "docs" / "evidence" / "mapping-telemetry-closure-01"

# Authority fields the mapping/enrich pipeline can fill. Diffed before→after; a change to
# a currently NON-EMPTY one is an overwrite risk (flagged separately).
AUTHORITY_FIELDS = [
    "category", "subcategory", "type", "product_type", "product_type_id", "silo",
    "trigger_id", "formula", "claim_risk_level", "physics_class", "recommended_grip",
    "scene_context", "camera_style", "camera_behavior", "camera_shot",
]
STATUS_FIELDS = ["mapping_status", "mapping_confidence", "mapping_source",
                 "prompt_readiness_status"]


def _norm(v):
    return "" if v is None else str(v)


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=10)
    cohort_ids = [r[0] for r in con.execute(
        "SELECT id FROM product WHERE lifecycle_status='ACTIVE' AND mapping_status IS NULL ORDER BY id")]
    con.close()

    per_product = []
    by_status = Counter()
    by_category = Counter()
    by_claim = Counter()
    overwrite_rows = 0
    unexpected_approved = 0

    for pid in cohort_ids:
        stored = await crud.get_product(pid)
        proposed = await enrich_product(stored, persist=False)
        status = proposed.get("mapping_status")
        by_status[status] += 1
        by_category[_norm(stored.get("category"))] += 1
        by_claim[_norm(proposed.get("claim_risk_level")) or "(none)"] += 1
        if status == "APPROVED":
            unexpected_approved += 1  # evaluator must never emit APPROVED

        diff = {}
        would_overwrite = []
        for f in AUTHORITY_FIELDS:
            b, a = _norm(stored.get(f)), _norm(proposed.get(f))
            if b != a:
                diff[f] = {"before": stored.get(f), "after": proposed.get(f)}
                if b != "":  # existing non-empty value would change → overwrite risk
                    would_overwrite.append(f)
        if would_overwrite:
            overwrite_rows += 1

        per_product.append({
            "product_id": pid,
            "title": (stored.get("product_display_name") or "")[:80],
            "stored_before": {f: stored.get(f) for f in ["mapping_status", *AUTHORITY_FIELDS]},
            "proposed_after_status": {f: proposed.get(f) for f in STATUS_FIELDS},
            "proposed_classification": status,
            "mapping_missing_fields_after": proposed.get("mapping_missing_fields") or [],
            "field_diff": diff,
            "would_overwrite_existing": would_overwrite,
        })

    summary = {
        "cohort_definition": "lifecycle_status='ACTIVE' AND mapping_status IS NULL",
        "cohort_size": len(cohort_ids),
        "proposed_status_counts": dict(by_status),
        "unexpected_APPROVED_from_evaluator": unexpected_approved,
        "rows_that_would_overwrite_existing_nonempty_fields": overwrite_rows,
        "by_category": dict(by_category.most_common()),
        "by_proposed_claim_risk": dict(by_claim.most_common()),
    }
    OUT.joinpath("null_cohort_dryrun.json").write_text(
        json.dumps({"mission": "BOSMAX-MAPPING-TELEMETRY-CLOSURE-01",
                    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "persist": False, "wrote_to_db": False,
                    "summary": summary, "products": per_product}, indent=2),
        encoding="utf-8")

    print("DRY-RUN COMPLETE (persist=False, zero writes)")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
