#!/usr/bin/env python
"""Build truthful ACTIVE copy-gap manifest (read-only)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "outputs" / "mission-copy-final"
OUT.mkdir(parents=True, exist_ok=True)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main():
    from agent.db import get_db
    from agent.services.copy_set_validity_service import product_copy_classification

    db = await get_db()
    cur = await db.execute(
        """
        SELECT p.id, p.product_display_name, p.product_short_name, p.raw_product_title,
               p.lifecycle_status, p.category, p.product_type, p.silo,
               p.archived_reason
        FROM product p
        WHERE UPPER(COALESCE(p.lifecycle_status,'')) = 'ACTIVE'
                    AND UPPER(COALESCE(p.archived_reason,'')) NOT LIKE 'DUPLICATE_MERGED_TO_CANONICAL%'
        ORDER BY p.id
        """
    )
    products = [dict(r) for r in await cur.fetchall()]
    await cur.close()

    rows = []
    buckets = {}
    for i, p in enumerate(products, 1):
        c = await product_copy_classification(p["id"])
        cls = c.get("classification")
        buckets[cls] = buckets.get(cls, 0) + 1
        rows.append(
            {
                "product_id": p["id"],
                "product_name": p.get("product_display_name")
                or p.get("product_short_name")
                or p.get("raw_product_title"),
                "lifecycle": p.get("lifecycle_status"),
                "canonical": True,
                "cluster": p.get("category"),
                "product_type": p.get("product_type"),
                "latest_approved_pi_snapshot_id": c.get("current_pi_snapshot_id"),
                "pi_snapshot_version": c.get("current_pi_version"),
                "pi_authority_digest": c.get("current_pi_authority_digest"),
                "claim_gate": c.get("current_claim_gate"),
                "copy_eligible": c.get("copy_eligible"),
                "copy_eligibility_reasons": c.get("copy_eligibility_reasons"),
                "total_copy_sets": c.get("total_copy_sets"),
                "copy_sets_by_status": c.get("copy_sets_by_status"),
                "copy_sets_by_quarantine": c.get("copy_sets_by_quarantine"),
                "classification": cls,
                "recommended_next_action": c.get("recommended_next_action"),
                "valid_copy_set_id": c.get("valid_copy_set_id"),
            }
        )
        if i % 50 == 0:
            print(f"classified {i}/{len(products)}", flush=True)

    manifest = {
        "built_at": _now(),
        "cohort_total": len(products),
        "classification_counts": buckets,
        "products_with_valid_approved_copy": buckets.get("APPROVED_COPY_VALID", 0),
        "products_without_valid_approved_copy": len(products)
        - buckets.get("APPROVED_COPY_VALID", 0),
        "rows": rows,
    }
    path = OUT / "copy_gap_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    (OUT / "copy_gap_manifest.sha256").write_text(h + "\n", encoding="utf-8")
    # lightweight xlsx via openpyxl if available else csv
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "copy_gap"
        headers = [
            "product_id",
            "product_name",
            "classification",
            "recommended_next_action",
            "copy_eligible",
            "valid_copy_set_id",
            "total_copy_sets",
            "pi_snapshot_version",
            "claim_gate",
            "cluster",
            "product_type",
        ]
        ws.append(headers)
        for r in rows:
            ws.append([r.get(h) for h in headers])
        xlsx = OUT / "copy_gap_manifest.xlsx"
        wb.save(xlsx)
        (OUT / "copy_gap_manifest.xlsx.sha256").write_text(
            hashlib.sha256(xlsx.read_bytes()).hexdigest() + "\n", encoding="utf-8"
        )
        print("xlsx", xlsx)
    except Exception as e:
        print("xlsx skip", e)
    print(json.dumps({k: manifest[k] for k in manifest if k != "rows"}, indent=2))
    print("sha256", h)


if __name__ == "__main__":
    asyncio.run(main())
