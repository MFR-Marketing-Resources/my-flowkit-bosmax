"""Creative Intelligence — Round 1: product/category -> recommended AI avatar.

READ-FIRST, non-generative, review/config-only. This service:
  * resolves a raw product category into one of the 12 canonical creative
    clusters (from the workbook CATEGORY_MAP + keyword fallback + a deterministic
    ``Home & Living`` fallback);
  * seeds the EXISTING ``avatar_product_fit`` table from a curated, pool-validated
    cluster -> ``BOS_`` avatar crosswalk (idempotent, provenance in the notes);
  * returns recommended avatars for a product/category by REUSING the existing
    ``avatar_fit_service`` (no new recommendation engine).

Safety: it never writes Product Truth, Copy Sets, Copy Registry, Copy
Intelligence, or any generation/asset table. Every seeded ``avatar_code`` is
validated against the live ``avatar_registry`` pool before insertion; workbook
``AV01-AV08`` codes are never used (they are not in the live pool).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import avatar_fit_service
from agent.services import avatar_registry

_AUTHORITY = Path(__file__).resolve().parents[1] / "authority"
_CATEGORY_MAP_FILE = _AUTHORITY / "creative_category_cluster_map.json"
_CROSSWALK_FILE = _AUTHORITY / "creative_avatar_cluster_crosswalk.json"

CROSSWALK_SOURCE = "CREATIVE_AVATAR_CROSSWALK_v1"


@lru_cache(maxsize=1)
def _category_map() -> dict[str, Any]:
    return json.loads(_CATEGORY_MAP_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _crosswalk() -> dict[str, Any]:
    return json.loads(_CROSSWALK_FILE.read_text(encoding="utf-8"))


def canonical_clusters() -> list[str]:
    return list(_category_map().get("clusters", []))


def fallback_cluster() -> str:
    return str(_category_map().get("fallback_cluster") or "Home & Living")


def resolve_cluster(category: str | None) -> dict[str, str]:
    """Resolve a raw product category into a canonical cluster.

    Deterministic order: exact CATEGORY_MAP match -> first-segment match ->
    keyword rule -> fallback cluster. Returns ``{"cluster", "cluster_source"}``.
    """
    cfg = _category_map()
    table: dict[str, str] = cfg.get("category_to_cluster", {})
    raw = str(category or "").strip()
    if not raw:
        return {"cluster": fallback_cluster(), "cluster_source": "FALLBACK_EMPTY"}

    key = avatar_fit_service.normalise_category(raw)
    if key in table:
        return {"cluster": table[key], "cluster_source": "EXACT"}

    first = avatar_fit_service.normalise_category(raw.split(">")[0])
    if first in table:
        return {"cluster": table[first], "cluster_source": "PREFIX"}

    for rule in cfg.get("keyword_rules", []):
        tokens = rule.get("any", [])
        cluster = rule.get("cluster")
        if cluster and any(tok in key for tok in tokens):
            return {"cluster": cluster, "cluster_source": "KEYWORD"}

    return {"cluster": fallback_cluster(), "cluster_source": "FALLBACK"}


def _live_avatar_codes() -> set[str]:
    return {str(a.get("avatar_code")) for a in avatar_registry.list_pool()}


async def seed_avatar_product_fit(*, dry_run: bool = True) -> dict[str, Any]:
    """Populate ``avatar_product_fit`` from the pool-validated crosswalk.

    Idempotent (``upsert`` keyed on avatar_code+product_category). Every code is
    re-validated against the live avatar pool before insertion; unresolvable codes
    are skipped and reported (never inserted). ``dry_run`` writes nothing.
    """
    from agent.db import crud

    live = _live_avatar_codes()
    crosswalk = _crosswalk().get("crosswalk", {})
    written = 0
    skipped_invalid: list[dict[str, str]] = []
    per_cluster: dict[str, int] = {}

    for cluster, rows in crosswalk.items():
        product_category = avatar_fit_service.normalise_category(cluster)
        count = 0
        for row in rows:
            code = str(row.get("avatar_code") or "")
            if code not in live:
                skipped_invalid.append({"cluster": cluster, "avatar_code": code})
                continue
            count += 1
            if dry_run:
                continue
            await crud.upsert_avatar_product_fit(
                avatar_code=code,
                product_category=product_category,
                fit_score=row.get("fit_score", 0.8),
                suitability_notes=row.get("suitability_notes")
                or f"{cluster} [src:{CROSSWALK_SOURCE}]",
            )
            written += 1
        per_cluster[cluster] = count

    return {
        "dry_run": dry_run,
        "source": CROSSWALK_SOURCE,
        "clusters": len(crosswalk),
        "mappings_valid": sum(per_cluster.values()),
        "written": 0 if dry_run else written,
        "skipped_invalid": skipped_invalid,
        "per_cluster": per_cluster,
    }


async def recommend_avatars_for_category(category: str | None) -> dict[str, Any]:
    """Read-only avatar recommendation for a raw category. Never mutates."""
    resolved = resolve_cluster(category)
    cluster = resolved["cluster"]
    avatars = await avatar_fit_service.get_suitable_avatars(
        cluster, include_all_fallback=True
    )
    return {
        "category": category,
        "cluster": cluster,
        "cluster_source": resolved["cluster_source"],
        "avatar_count": len(avatars),
        "avatars": avatars,
    }


async def recommend_avatars_for_product(product_id: str) -> dict[str, Any]:
    """Read-only avatar recommendation for a product (manual or imported)."""
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    result = await recommend_avatars_for_category(product.get("category"))
    result["product_id"] = product_id
    result["product_name"] = (
        product.get("product_display_name") or product.get("raw_product_title")
    )
    return result
