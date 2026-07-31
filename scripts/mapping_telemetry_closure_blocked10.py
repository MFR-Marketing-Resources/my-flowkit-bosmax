#!/usr/bin/env python
"""BOSMAX-MAPPING-TELEMETRY-CLOSURE-01 — 10 BLOCKED products decision package.

READ-ONLY. Emits a per-product decision table (JSON + Markdown) for the owner. It
PROPOSES subcategory/type from the product's existing product_type_group and recommends
DURABLE_RULE vs BOUNDED_OVERRIDE. It applies NOTHING — the owner decides. Evidence:
docs/evidence/mapping-telemetry-closure-01/blocked_10_decision.{json,md}
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "flow_agent.db"
OUT = REPO / "docs" / "evidence" / "mapping-telemetry-closure-01"

# Proposed (subcategory, type) per existing canonical product_type_group. PROPOSAL ONLY.
PROPOSAL = {
    "packaged_food": ("Snacks & Biscuits", "Packaged Food"),
    "pull_up_bar": ("Fitness Equipment", "Pull-Up Bar"),
    "wireless_earbuds": ("Audio", "Wireless Earbuds"),
    "household_cleaner": ("Cleaning", "Surface Cleaner"),
    "detergent": ("Laundry", "Laundry Detergent"),
    "trash_bag": ("Household Supplies", "Trash Bag"),
    "baby_diaper": ("Diapering", "Baby Diaper"),
    "modestwear": ("Muslim Fashion", "Hijab / Scarf"),
}
# product_type_group -> the domain its cluster implies; used to detect category collisions.
GROUP_DOMAIN = {
    "packaged_food": "food", "pull_up_bar": "fitness", "wireless_earbuds": "electronics",
    "household_cleaner": "household", "detergent": "household", "trash_bag": "household",
    "baby_diaper": "baby", "modestwear": "fashion",
}
CATEGORY_DOMAIN = {
    "Food & Beverage": "food", "Sports & Outdoors": "fitness",
    "Electronics & Gadgets": "electronics", "Automotive": "automotive",
    "Home & Living": "household", "Baby & Kids": "baby", "Fashion": "fashion",
}


def main():
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT p.id, p.product_display_name, p.category, p.subcategory, p.type, "
        "p.mapping_missing_fields, t.cluster, t.product_type_group, t.authority_source, "
        "t.classification_confidence, t.review_status "
        "FROM product p LEFT JOIN product_strategy_taxonomy t ON t.product_id=p.id "
        "WHERE p.mapping_status='BLOCKED' AND p.product_display_name NOT LIKE '%Smoke%' "
        "ORDER BY p.updated_at DESC"
    ).fetchall()
    con.close()

    table = []
    for r in rows:
        ptg = r["product_type_group"]
        sub, typ = PROPOSAL.get(ptg, ("(needs owner input)", "(needs owner input)"))
        cat_dom = CATEGORY_DOMAIN.get(r["category"] or "", "unknown")
        grp_dom = GROUP_DOMAIN.get(ptg or "", "unknown")
        collision = cat_dom != grp_dom and cat_dom != "unknown" and grp_dom != "unknown"
        # DURABLE only when the product_type_group is a proven reusable family AND there is
        # no category/cluster collision; otherwise a product-specific human override.
        durable = (ptg in PROPOSAL) and not collision
        table.append({
            "product_id": r["id"],
            "title": r["product_display_name"],
            "current": {"category": r["category"], "subcategory": r["subcategory"], "type": r["type"]},
            "missing_fields": json.loads(r["mapping_missing_fields"]) if r["mapping_missing_fields"] else [],
            "product_type_group": ptg,
            "product_type_group_provenance": {
                "cluster": r["cluster"], "authority_source": r["authority_source"],
                "classification_confidence": r["classification_confidence"],
                "review_status": r["review_status"]},
            "proposed_taxonomy": {"subcategory": sub, "type": typ},
            "collision_risk": "HIGH" if collision else "LOW",
            "collision_detail": (f"stored category domain '{cat_dom}' != cluster family domain '{grp_dom}'"
                                 if collision else "category and cluster family agree"),
            "recommendation": "DURABLE_RULE" if durable else "BOUNDED_OVERRIDE",
            "reason": ("reusable non-ambiguous product family (product_type_group) — a category→"
                       "subcategory/type rule serves this + future products"
                       if durable else
                       "category/cluster collision or unmapped family — needs a human-reviewed, "
                       "product-specific override, not a broad rule"),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "blocked_10_decision.json").write_text(
        json.dumps({"mission": "BOSMAX-MAPPING-TELEMETRY-CLOSURE-01", "applied": False,
                    "note": "PROPOSAL ONLY — owner decides; nothing applied.",
                    "count": len(table), "decisions": table}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    md = ["# 10 BLOCKED products — taxonomy decision package (PROPOSAL ONLY, nothing applied)\n",
          "| # | Product | Category | product_type_group | Missing | Proposed subcategory / type | Collision | Recommendation |",
          "|---|---|---|---|---|---|---|---|"]
    for i, d in enumerate(table, 1):
        md.append(
            f"| {i} | {d['title'][:34]} | {d['current']['category']} | {d['product_type_group']} | "
            f"{','.join(d['missing_fields'])} | {d['proposed_taxonomy']['subcategory']} / "
            f"{d['proposed_taxonomy']['type']} | {d['collision_risk']} | **{d['recommendation']}** |")
    (OUT / "blocked_10_decision.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    durable = sum(1 for d in table if d["recommendation"] == "DURABLE_RULE")
    print(f"WROTE blocked_10_decision.json + .md  ({len(table)} products: "
          f"{durable} DURABLE_RULE, {len(table)-durable} BOUNDED_OVERRIDE)")


if __name__ == "__main__":
    main()
