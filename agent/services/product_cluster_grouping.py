"""SSOT cluster grouping accessor.

Projects the AUTHORITATIVE strategy taxonomy cluster (VOCAB B, the 40 stored,
human-reviewed, fail-closed clusters) onto the creative avatar/scene bucket
(VOCAB A, the 12 from creative_category_cluster_map.json) via a static crosswalk.

Resolve-on-read: nothing is re-derived from product.category, and a stored
cluster that has no crosswalk entry NEVER silently falls back to a real bucket
(it returns UNMAPPED_STRATEGY_CLUSTER and a CI invariant test hard-fails). This
is the single place consumers ask "which creative bucket is this product in".
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from agent.config import BASE_DIR

_CROSSWALK_PATH = BASE_DIR / "agent" / "authority" / "creative_cluster_crosswalk.json"
_GENERIC = "generic_unclassified"

# grouping statuses
RESOLVED = "RESOLVED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"                       # sentinel / no taxonomy
UNMAPPED_STRATEGY_CLUSTER = "UNMAPPED_STRATEGY_CLUSTER"   # stored cluster absent from the crosswalk (a build break)


@lru_cache(maxsize=1)
def _crosswalk() -> dict[str, str | None]:
    data = json.loads(_CROSSWALK_PATH.read_text(encoding="utf-8"))
    return dict(data["strategy_to_creative"])


def crosswalk_domain() -> set[str]:
    """Strategy clusters the crosswalk maps (invariant-tested == the 40 union)."""
    return set(_crosswalk().keys())


def crosswalk_range() -> set[str]:
    """Creative buckets the crosswalk targets (subset of the 12), sans the null sentinel."""
    return {v for v in _crosswalk().values() if v}


def resolve_creative_cluster(strategy_cluster: str | None) -> str | None:
    """The creative bucket for a stored strategy cluster, or None when it is the
    review sentinel, unmapped, or absent. Callers needing to distinguish those
    cases use ``resolve_product_grouping``."""
    if not strategy_cluster:
        return None
    return _crosswalk().get(strategy_cluster)


def resolve_product_grouping(
    strategy_cluster: str | None,
    *,
    product_type_group: str | None = None,
    taxonomy_status: str | None = None,
) -> dict[str, Any]:
    """One SSOT read — strategy cluster (authority) -> creative bucket (projection),
    never silently mis-grouped.

    - no strategy cluster / ``generic_unclassified`` -> REVIEW_REQUIRED, creative None.
    - stored cluster present but not in the crosswalk -> UNMAPPED_STRATEGY_CLUSTER,
      creative None (the invariant test hard-fails, so this cannot ship silently).
    - otherwise -> RESOLVED with the creative bucket.
    """
    sc = (strategy_cluster or "").strip() or None
    grouping: dict[str, Any] = {
        "strategy_cluster": sc,
        "product_type_group": product_type_group,
        "creative_cluster": None,
        "grouping_status": REVIEW_REQUIRED,
        "taxonomy_status": taxonomy_status,
    }
    if sc is None or sc == _GENERIC:
        return grouping
    crosswalk = _crosswalk()
    if sc not in crosswalk:
        grouping["grouping_status"] = UNMAPPED_STRATEGY_CLUSTER
        return grouping
    target = crosswalk[sc]
    if target is None:  # explicit sentinel mapped to review
        return grouping
    grouping["creative_cluster"] = target
    grouping["grouping_status"] = RESOLVED
    return grouping
