"""Avatar Fit service — product-category to avatar mapping.

Lets operators and downstream selectors answer "which avatars are
suitable for this product?" without guessing.

Phase 1 foundation:
- Normalise product category strings.
- Read explicit avatar / category mappings from ``avatar_product_fit``.
- Return suitable avatars ordered by fit_score.
- Safe fallback when no explicit mapping exists: returns ALL registered
  avatars with a default fit_score (1.0).

This service READS the avatar pool and the fit table but NEVER:
- Changes ``resolve_presenter()`` in ``avatar_registry.py``.
- Changes ``presenter_prose()``.
- Changes the canonical prompt compiler.
"""

from __future__ import annotations

import re
from typing import Any

from agent.db import crud
from agent.services import avatar_registry


def normalise_category(category: str | None) -> str:
    """Normalise a raw product category string into a stable key.

    Strips whitespace, uppercases, and collapses common separators so
    "Beauty & Personal Care" → "BEAUTY_PERSONAL_CARE".
    """
    raw = str(category or "").strip()
    if not raw:
        return "UNCATEGORISED"
    # Collapse: & / - / spaces → single underscore
    key = re.sub(r"[&,/\-]+", "_", raw)
    key = re.sub(r"\s+", "_", key)
    key = re.sub(r"_+", "_", key).strip("_").upper()
    return key or "UNCATEGORISED"


async def get_suitable_avatars(
    product_category: str,
    *,
    include_all_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Return avatars suitable for a product category.

    Returns explicit ``avatar_product_fit`` rows ordered by
    ``fit_score`` descending.  When ``include_all_fallback`` is True and
    no explicit mappings exist, falls back to ALL registered avatars
    with a default fit_score of 1.0.
    """
    norm = normalise_category(product_category)
    fits = await crud.list_avatar_product_fits(product_category=norm)
    if fits:
        # Enrich with avatar pool profiles
        enriched: list[dict[str, Any]] = []
        for fit in fits:
            try:
                profile = avatar_registry.resolve_presenter(
                    avatar_id=fit["avatar_code"],
                )
            except ValueError:
                continue
            enriched.append({
                **profile,
                "fit_score": fit.get("fit_score", 1.0),
                "suitability_notes": fit.get("suitability_notes"),
            })
        enriched.sort(key=lambda x: -x["fit_score"])
        return enriched

    if not include_all_fallback:
        return []

    # Safe fallback: all registered avatars
    all_avatars = avatar_registry.list_pool()
    return [
        {**a, "fit_score": 1.0, "suitability_notes": "fallback — no explicit category mapping"}
        for a in all_avatars
    ]


async def get_avatar_fit_summary(
    product_category: str,
) -> dict[str, Any]:
    """Return a summary of avatar availability for a product category."""
    suitable = await get_suitable_avatars(product_category, include_all_fallback=False)
    has_explicit = len(suitable) > 0

    return {
        "product_category": normalise_category(product_category),
        "has_explicit_mappings": has_explicit,
        "explicit_match_count": len(suitable),
        "suitable_avatars": suitable,
        "fallback_available": not has_explicit,
    }
