from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.db import crud
from agent.services.product_intelligence import enrich_product, normalize_currency_amount


BABY_WIPES_KEYWORDS = [
    "baby wipes",
    "newborn wet wipes",
    "wet wipes",
    "wet tissue",
    "baby wet tissue",
    "tisu basah",
    "tisu basah baby",
    "baby tissue",
    "wipes newborn",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit product display normalization defects.")
    parser.add_argument("--use-stored-values", action="store_true", help="Audit raw stored DB values instead of enriched display values.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Maximum number of sample conflicts to print.")
    return parser.parse_args()


def _parse_rate(rate: str | None) -> float | None:
    if not rate:
        return None
    try:
        return float(str(rate).replace('%', '').strip())
    except ValueError:
        return None


def _has_baby_wipes_keywords(product: dict[str, Any]) -> bool:
    haystack = f"{product.get('product_short_name') or ''} {product.get('raw_product_title') or ''}".lower()
    return any(keyword in haystack for keyword in BABY_WIPES_KEYWORDS)


def _taxonomy_conflict(product: dict[str, Any]) -> bool:
    taxonomy = " > ".join(
        part for part in [product.get("category") or "", product.get("subcategory") or "", product.get("type") or ""] if part
    ).lower()
    if _has_baby_wipes_keywords(product):
        if "baby care" not in taxonomy or "fragrance" in taxonomy or "body mist" in taxonomy:
            return True
    if ("diaper" in taxonomy or "lampin" in taxonomy or "wipes" in taxonomy) and ("fragrance" in taxonomy or "body mist" in taxonomy):
        return True
    return False


def _bad_price_format(product: dict[str, Any]) -> bool:
    price = product.get("price")
    if price in {None, ""}:
        return False
    normalized = normalize_currency_amount(price)
    if normalized is None:
        return True
    return abs(float(price) - normalized) > 1e-9


def _commission_calc_missing(product: dict[str, Any]) -> bool:
    price = normalize_currency_amount(product.get("price"))
    rate = _parse_rate(product.get("commission_rate"))
    amount = normalize_currency_amount(product.get("commission_amount"))
    return price is not None and rate is not None and amount is None


async def main() -> None:
    args = parse_args()
    stored_products = await crud.list_products(limit=10000)
    products = stored_products if args.use_stored_values else [await enrich_product(product, persist=False) for product in stored_products]

    bad_price_format_count = 0
    commission_calc_missing_count = 0
    taxonomy_conflict_count = 0
    sample_conflicts: list[dict[str, Any]] = []

    for product in products:
        if _bad_price_format(product):
            bad_price_format_count += 1
            if len(sample_conflicts) < args.sample_limit:
                sample_conflicts.append({
                    "id": product.get("id"),
                    "issue": "bad_price_format",
                    "title": product.get("product_short_name") or product.get("raw_product_title"),
                    "price": product.get("price"),
                })

        if _commission_calc_missing(product):
            commission_calc_missing_count += 1
            if len(sample_conflicts) < args.sample_limit:
                sample_conflicts.append({
                    "id": product.get("id"),
                    "issue": "commission_calc_missing",
                    "title": product.get("product_short_name") or product.get("raw_product_title"),
                    "price": product.get("price"),
                    "commission_rate": product.get("commission_rate"),
                })

        if _taxonomy_conflict(product):
            taxonomy_conflict_count += 1
            if len(sample_conflicts) < args.sample_limit:
                sample_conflicts.append({
                    "id": product.get("id"),
                    "issue": "taxonomy_conflict",
                    "title": product.get("product_short_name") or product.get("raw_product_title"),
                    "taxonomy": " > ".join(
                        part for part in [product.get("category") or "", product.get("subcategory") or "", product.get("type") or ""] if part
                    ),
                })

    print(json.dumps({
        "total_products_checked": len(products),
        "bad_price_format_count": bad_price_format_count,
        "commission_calc_missing_count": commission_calc_missing_count,
        "taxonomy_conflict_count": taxonomy_conflict_count,
        "sample_conflicts": sample_conflicts,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())