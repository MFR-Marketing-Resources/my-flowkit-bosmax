from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services.product_intelligence_service import (
    resolve_product_intelligence_profile,
)
from agent.services.product_physics import resolve_product_physics
from agent.services.registration_consistency_service import (
    evaluate_registration_consistency,
)
from agent.services.registration_evidence_quality_service import (
    audit_registration_evidence,
)


def _request_from_product(product: dict[str, Any]) -> ProductKnowledgeCompleteRequest:
    return ProductKnowledgeCompleteRequest(
        product_name=(
            product.get("raw_product_title")
            or product.get("product_display_name")
            or product.get("product_short_name")
        ),
        product_knowledge_text=(
            product.get("product_knowledge_text")
            or product.get("product_knowledge")
            or product.get("description")
        ),
        benefits_text=product.get("benefits_text") or product.get("benefits"),
        usage_text=product.get("usage_text") or product.get("usage"),
        target_customer_text=(
            product.get("target_customer_text")
            or product.get("target_customer")
        ),
        ingredients_text=(
            product.get("ingredients_text")
            or product.get("ingredients")
        ),
        warnings_text=product.get("warnings_text") or product.get("warnings"),
        size_or_volume=product.get("size_or_volume"),
        package_notes=product.get("package_notes"),
        image_url=product.get("image_url"),
        local_image_path=product.get("local_image_path"),
        category=product.get("category"),
        subcategory=product.get("subcategory"),
        type=product.get("type"),
        product_type=product.get("product_type"),
        product_type_id=product.get("product_type_id"),
        materials_text=product.get("materials_text"),
        source_lane=str(product.get("source") or "UNKNOWN"),
    )


def audit_catalog(connection: sqlite3.Connection) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM product ORDER BY id"
        ).fetchall()
    ]
    audited: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for product in rows:
        product["allow_live_image_analysis"] = False
        intelligence = resolve_product_intelligence_profile(product)
        physics_seed = {
            **product,
            "bosmax_product_family": intelligence.get(
                "bosmax_product_family"
            ),
        }
        physics = resolve_product_physics(product=physics_seed)
        evidence = audit_registration_evidence(
            _request_from_product(product),
            product_family=str(
                intelligence.get("bosmax_product_family") or ""
            ),
        )
        consistency = evaluate_registration_consistency(
            {
                "category": product.get("category"),
                "subcategory": product.get("subcategory"),
                "type": product.get("type"),
                "bosmax_product_family": intelligence.get(
                    "bosmax_product_family"
                ),
                "physical_state": intelligence.get("physical_state"),
                "physics_class": physics.get("physics_class"),
                "copy_formula": intelligence.get("copy_formula"),
            }
        )
        issue_codes = list(
            dict.fromkeys(
                evidence.issue_codes
                + consistency.issue_codes
                + list(intelligence.get("warnings") or [])
            )
        )
        severe = consistency.status == "BLOCKED_REVIEW_REQUIRED"
        review_required = bool(issue_codes) or str(
            intelligence.get("intelligence_status") or ""
        ) == "NEEDS_REVIEW"
        status = (
            "BLOCKED_EXCEPTION"
            if severe
            else "REVIEW_REQUIRED"
            if review_required
            else "CLEAN"
        )
        family = str(
            intelligence.get("bosmax_product_family")
            or "UNKNOWN_REVIEW_REQUIRED"
        )
        family_counts[family] += 1
        status_counts[status] += 1
        audited.append(
            {
                "product_id": str(product.get("id") or ""),
                "title": str(
                    product.get("raw_product_title")
                    or product.get("product_display_name")
                    or ""
                ),
                "status": status,
                "family": family,
                "physical_state": intelligence.get("physical_state"),
                "physics_class": physics.get("physics_class"),
                "copy_formula": intelligence.get("copy_formula"),
                "evidence_quality_status": evidence.status,
                "consistency_status": consistency.status,
                "image_analysis_status": (
                    intelligence.get("image_analysis") or {}
                ).get("status"),
                "issue_codes": issue_codes,
            }
        )

    return {
        "audit_version": "smart_registration_catalog_audit_v1",
        "summary": {
            "total_products": len(audited),
            "status_counts": dict(sorted(status_counts.items())),
            "family_counts": dict(sorted(family_counts.items())),
            "provider_calls": 0,
            "write_operations": 0,
            "database_mode": "READ_ONLY",
        },
        "products": audited,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    database_uri = f"file:{args.db.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        report = audit_catalog(connection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                **report["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
