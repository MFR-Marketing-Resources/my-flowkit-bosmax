from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent.services.product_intelligence import enrich_product


FASTMOSS_REFERENCE_ID_PREFIX = "fastmoss-ref:"
FASTMOSS_REFERENCE_LANE = "FASTMOSS_REFERENCE"
FASTMOSS_REFERENCE_LABEL = "FastMoss Reference"
FASTMOSS_REFERENCE_BLOCKER = "REFERENCE_ONLY_PRODUCT"
FASTMOSS_REFERENCE_REASON = (
    "FastMoss latest reference is visible for review only. "
    "Use Smart Registration to convert it into product truth before package load."
)
_REFERENCE_CACHE_SIGNATURE: str | None = None
_REFERENCE_CACHE_ITEMS: list[dict[str, Any]] = []
# The row-count the cache was BUILT from (not len(items)). When the workbook
# holds fewer rows than the requested limit, len(items) < limit would defeat a
# len-based guard and re-enrich every call — this tracks the load cap instead.
_REFERENCE_CACHE_LOADED_LIMIT: int = 0


def is_fastmoss_reference_product_id(product_id: str | None) -> bool:
    return str(product_id or "").startswith(FASTMOSS_REFERENCE_ID_PREFIX)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(*parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _reference_product_id(*, raw_product_title: str, source_url: str, tiktok_product_url: str) -> str:
    return (
        f"{FASTMOSS_REFERENCE_ID_PREFIX}"
        f"{_fingerprint(raw_product_title, source_url, tiktok_product_url)}"
    )


def _reference_seed(operator_product: Any) -> dict[str, Any]:
    raw_product_title = _clean(
        getattr(operator_product, "raw_product_title", None)
        or getattr(operator_product, "product_name", None)
    )
    product_display_name = _clean(
        getattr(operator_product, "product_display_name", None) or raw_product_title
    )
    product_short_name = _clean(
        getattr(operator_product, "product_short_name", None)
        or product_display_name
        or raw_product_title
    )
    source_url = _clean(getattr(operator_product, "source_url", None))
    tiktok_product_url = _clean(getattr(operator_product, "tiktok_product_url", None))

    return {
        "id": _reference_product_id(
            raw_product_title=raw_product_title,
            source_url=source_url,
            tiktok_product_url=tiktok_product_url,
        ),
        "product_id": None,
        "source": "FASTMOSS",
        "source_lane": FASTMOSS_REFERENCE_LANE,
        "source_label": FASTMOSS_REFERENCE_LABEL,
        "reference_only": True,
        "catalog_blockers": [FASTMOSS_REFERENCE_BLOCKER],
        "catalog_visibility_reason": FASTMOSS_REFERENCE_REASON,
        "raw_product_title": raw_product_title,
        "product_display_name": product_display_name,
        "product_short_name": product_short_name,
        "category": getattr(operator_product, "category", None),
        "subcategory": getattr(operator_product, "sub_category", None),
        "type": getattr(operator_product, "type_angle", None),
        "product_type": getattr(operator_product, "product_type", None),
        "silo": getattr(operator_product, "silo_id", None),
        "trigger_id": getattr(operator_product, "trigger_id", None),
        "formula": getattr(operator_product, "submode_formula", None),
        "mode_recommendations": list(
            getattr(operator_product, "mode_recommendations", None) or []
        ),
        "copywriting_angle": getattr(operator_product, "copywriting_angle", None),
        "claim_risk_level": getattr(operator_product, "claim_risk_level", None),
        "mapping_source": getattr(operator_product, "mapping_source", None),
        "mapping_confidence": getattr(operator_product, "mapping_confidence", None),
        "shop_name": getattr(operator_product, "shop_name", None),
        "price": getattr(operator_product, "avg_price_rm", None),
        "currency": "MYR",
        "commission_amount": getattr(operator_product, "commission_amount", None),
        "commission_rate": getattr(operator_product, "commission_rate", None),
        "image_url": getattr(operator_product, "image_url", None),
        "source_url": source_url or None,
        "tiktok_product_url": tiktok_product_url or None,
        "fastmoss_source_file": "FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx",
        "lifecycle_status": "ACTIVE",
        "asset_status": "UNRESOLVED",
        "image_asset_status": "UNRESOLVED",
    }


async def list_fastmoss_reference_products(limit: int = 500) -> list[dict[str, Any]]:
    global _REFERENCE_CACHE_ITEMS, _REFERENCE_CACHE_SIGNATURE, _REFERENCE_CACHE_LOADED_LIMIT
    from agent.api.operator import _load_products, _pack_file

    workbook_path = Path(_pack_file("FASTMOSS_COMBINED_10_FILES_WORKBOOK.xlsx"))
    if not workbook_path.exists():
        _REFERENCE_CACHE_SIGNATURE = None
        _REFERENCE_CACHE_ITEMS = []
        _REFERENCE_CACHE_LOADED_LIMIT = 0
        return []

    signature = f"{workbook_path.stat().st_mtime_ns}:{workbook_path.stat().st_size}"
    # Hit on the load cap, not len(items): if the workbook has fewer rows than the
    # requested limit, the cache already holds ALL of them and is still complete.
    if signature == _REFERENCE_CACHE_SIGNATURE and _REFERENCE_CACHE_LOADED_LIMIT >= limit:
        return _REFERENCE_CACHE_ITEMS[:limit]

    load_cap = max(limit, len(_REFERENCE_CACHE_ITEMS), 500)
    operator_products = _load_products(limit=load_cap)
    items: list[dict[str, Any]] = []
    for operator_product in operator_products:
        enriched = await enrich_product(_reference_seed(operator_product), persist=False)
        enriched["source_lane"] = FASTMOSS_REFERENCE_LANE
        enriched["source_label"] = FASTMOSS_REFERENCE_LABEL
        enriched["reference_only"] = True
        enriched["catalog_blockers"] = [FASTMOSS_REFERENCE_BLOCKER]
        enriched["catalog_visibility_reason"] = FASTMOSS_REFERENCE_REASON
        items.append(enriched)
    _REFERENCE_CACHE_SIGNATURE = signature
    _REFERENCE_CACHE_ITEMS = items
    _REFERENCE_CACHE_LOADED_LIMIT = load_cap
    return items[:limit]


async def get_fastmoss_reference_product(product_id: str) -> dict[str, Any] | None:
    for product in await list_fastmoss_reference_products(limit=1000):
        if product.get("id") == product_id:
            return product
    return None
