from __future__ import annotations

from collections import Counter
from typing import Any

from agent.services.product_intelligence import is_test_product, json_load_list


CANONICAL_FATIMA_PRODUCT_ID = "8ea29ec2-3e38-4d35-a5dc-16e0be4bc317"
CANONICAL_FATIMA_SHORT_NAME = "fatima instant sarung syria"
CANONICAL_FATIMA_TITLES = {
    "fatima instant sarung syria ~ hq moscrepe premium",
    "fatima instant sarung syria ~ hq moscrepe premium ~ ironless & stretchable hijab untuk wanita muslimah bahan elastik sesuai kesalaman dan gaya",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _stringify_counter(counter: Counter[str]) -> dict[str, int]:
    return {
        key: counter[key]
        for key in sorted(counter, key=lambda item: (-counter[item], item))
    }


def _mapping_missing_fields(product: dict[str, Any]) -> list[str]:
    return [field for field in json_load_list(product.get("mapping_missing_fields")) if field]


def _is_noncanonical_fatima_duplicate(product: dict[str, Any]) -> bool:
    product_id = str(product.get("id") or "").strip()
    short_name = _normalize_text(product.get("product_short_name"))
    raw_title = _normalize_text(product.get("raw_product_title"))
    if product_id == CANONICAL_FATIMA_PRODUCT_ID:
        return False
    return short_name == CANONICAL_FATIMA_SHORT_NAME or raw_title in CANONICAL_FATIMA_TITLES


def classify_catalog_pollution(product: dict[str, Any]) -> str:
    mapping_status = str(product.get("mapping_status") or "").strip()

    if is_test_product(product):
        return "LEAKED_TEST_FIXTURE"
    if _is_noncanonical_fatima_duplicate(product):
        return "STALE_DUPLICATE"
    if not mapping_status:
        return "VALID_PRODUCT_NEEDS_BACKFILL"
    return "UNKNOWN_REQUIRES_REVIEW"


def _cleanup_snapshot(product: dict[str, Any], classification: str, action: str) -> dict[str, Any]:
    return {
        "id": product.get("id"),
        "source": product.get("source"),
        "product_short_name": product.get("product_short_name"),
        "raw_product_title": product.get("raw_product_title"),
        "mapping_status": product.get("mapping_status"),
        "mapping_missing_fields": _mapping_missing_fields(product),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
        "classification": classification,
        "action": action,
    }


def build_cleanup_plan(products: list[dict[str, Any]]) -> dict[str, Any]:
    null_mapping_rows: list[dict[str, Any]] = []
    test_fixture_rows: list[dict[str, Any]] = []
    stale_duplicate_rows: list[dict[str, Any]] = []
    valid_backfill_rows: list[dict[str, Any]] = []
    unknown_rows: list[dict[str, Any]] = []

    for product in products:
        classification = classify_catalog_pollution(product)
        status = str(product.get("mapping_status") or "").strip()
        snapshot = _cleanup_snapshot(
            product,
            classification=classification,
            action="DELETE" if classification in {"LEAKED_TEST_FIXTURE", "STALE_DUPLICATE"} else "KEEP",
        )

        if not status:
            null_mapping_rows.append(snapshot)

        if classification == "LEAKED_TEST_FIXTURE":
            test_fixture_rows.append(snapshot)
        elif classification == "STALE_DUPLICATE":
            stale_duplicate_rows.append(snapshot)
        elif classification == "VALID_PRODUCT_NEEDS_BACKFILL":
            valid_backfill_rows.append(snapshot)
        else:
            unknown_rows.append(snapshot)

    return {
        "null_mapping_status_before": len(null_mapping_rows),
        "test_fixture_rows_found": len(test_fixture_rows),
        "stale_duplicate_rows_found": len(stale_duplicate_rows),
        "valid_product_needs_backfill_rows": len(valid_backfill_rows),
        "unknown_requires_review_rows": len(unknown_rows),
        "null_mapping_rows": null_mapping_rows,
        "rows_to_delete": test_fixture_rows + stale_duplicate_rows,
        "test_fixture_rows": test_fixture_rows,
        "stale_duplicate_rows": stale_duplicate_rows,
        "valid_product_needs_backfill": valid_backfill_rows,
        "unknown_requires_review": unknown_rows,
    }


def build_mapping_summary(
    raw_products: list[dict[str, Any]],
    enriched_products: list[dict[str, Any]],
    *,
    sample_limit: int = 30,
) -> dict[str, Any]:
    ready = 0
    needs_review = 0
    blocked = 0
    blocked_by_reason: Counter[str] = Counter()
    blocked_by_source: Counter[str] = Counter()
    blocked_by_category: Counter[str] = Counter()
    blocked_by_missing_field: Counter[str] = Counter()
    blocked_by_image_readiness: Counter[str] = Counter()
    blocked_by_mapping_source: Counter[str] = Counter()
    sample_blocked_products: list[dict[str, Any]] = []

    for raw_product, enriched_product in zip(raw_products, enriched_products):
        status = str(enriched_product.get("mapping_status") or "").strip().upper()
        if status == "READY":
            ready += 1
            continue
        if status == "NEEDS_REVIEW":
            needs_review += 1
            continue

        blocked += 1
        source = str(enriched_product.get("source") or raw_product.get("source") or "UNKNOWN")
        category = str(enriched_product.get("category") or "UNMAPPED")
        subcategory = str(enriched_product.get("subcategory") or "UNMAPPED")
        missing_fields = [field for field in (enriched_product.get("mapping_missing_fields") or []) if field]
        image_readiness = str(enriched_product.get("image_readiness_status") or "UNKNOWN")
        mapping_source = str(enriched_product.get("mapping_source") or "UNKNOWN")
        reason = "|".join(missing_fields) if missing_fields else "UNSPECIFIED_BLOCKER"

        blocked_by_reason[reason] += 1
        blocked_by_source[source] += 1
        blocked_by_category[f"{category} / {subcategory}"] += 1
        blocked_by_image_readiness[image_readiness] += 1
        blocked_by_mapping_source[mapping_source] += 1
        for field in missing_fields:
            blocked_by_missing_field[field] += 1

        sample_blocked_products.append(
            {
                "id": enriched_product.get("id") or raw_product.get("id"),
                "source": source,
                "product_short_name": enriched_product.get("product_short_name"),
                "raw_product_title": enriched_product.get("raw_product_title"),
                "category": enriched_product.get("category"),
                "subcategory": enriched_product.get("subcategory"),
                "type": enriched_product.get("type"),
                "mapping_source": enriched_product.get("mapping_source"),
                "mapping_status": enriched_product.get("mapping_status"),
                "mapping_missing_fields": missing_fields,
                "image_readiness_status": image_readiness,
                "updated_at": enriched_product.get("updated_at") or raw_product.get("updated_at"),
            }
        )

    sample_blocked_products.sort(
        key=lambda product: (
            -len(product.get("mapping_missing_fields") or []),
            product.get("updated_at") or "",
            str(product.get("product_short_name") or ""),
        ),
        reverse=True,
    )

    cleanup_plan = build_cleanup_plan(raw_products)
    return {
        "total_products": len(raw_products),
        "ready": ready,
        "needs_review": needs_review,
        "blocked": blocked,
        "null_mapping_status": cleanup_plan["null_mapping_status_before"],
        "blocked_by_reason": _stringify_counter(blocked_by_reason),
        "blocked_by_source": _stringify_counter(blocked_by_source),
        "blocked_by_category": _stringify_counter(blocked_by_category),
        "blocked_by_missing_field": _stringify_counter(blocked_by_missing_field),
        "blocked_by_image_readiness": _stringify_counter(blocked_by_image_readiness),
        "blocked_by_mapping_source": _stringify_counter(blocked_by_mapping_source),
        "sample_blocked_products": sample_blocked_products[:sample_limit],
        "null_mapping_rows": cleanup_plan["null_mapping_rows"],
    }