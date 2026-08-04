"""B+ PR-2 — the product-strategy-type registry must recognize all 40 stored
clusters, not just the 23-tuple SCOUTING_CLUSTER_ORDER.

Before this, 17 clusters that the catalog-truth / P58 authorities legitimately
store (e.g. stationery, health_device, consumer_audio, garden_care) were rejected
by manual register with INVALID_STRATEGY_CLUSTER and were un-selectable in the
FastMoss queue filter dropdown — a stored row that could not be reached.
"""
from __future__ import annotations

import pytest

from agent.services.product_cluster_grouping import crosswalk_domain
from agent.services.product_strategy_scouting_service import SCOUTING_CLUSTER_ORDER
from agent.services.product_strategy_taxonomy_service import (
    SCENE_STRATEGIES,
    ProductStrategyTaxonomyError,
    _registry_clusters,
    _validate_registry_binding,
)

# the 17 previously-rejected, previously-hidden clusters
_PREVIOUSLY_BLOCKED = [
    "stationery", "automotive_care", "health_device", "home_lighting", "garden_care",
    "home_electrical", "kitchen_storage", "home_decor", "kitchen_cookware",
    "kitchen_drinkware", "household_pest_control", "kitchen_tool", "fashion_accessory",
    "outdoor_equipment", "fitness_equipment", "automotive_accessory", "consumer_audio",
]


def test_registry_lists_all_40_with_scouting_order_first():
    clusters = _registry_clusters()
    assert len(clusters) == 40
    assert set(clusters) == crosswalk_domain()
    # curated order preserved at the front (nice FastMoss dropdown UX)
    assert clusters[: len(SCOUTING_CLUSTER_ORDER)] == list(SCOUTING_CLUSTER_ORDER)
    # every previously-blocked cluster is now listed (and thus filterable)
    for c in _PREVIOUSLY_BLOCKED:
        assert c in clusters


def test_previously_blocked_cluster_passes_the_validation_gate():
    sid = next(s for s in SCENE_STRATEGIES if s != "GENERIC_FALLBACK")
    # health_device was rejected before; the cluster gate must now accept it.
    try:
        _validate_registry_binding(
            cluster="health_device",
            product_type_group="massager",
            matched_scene_strategy_id=sid,
            scene_coverage_status="COVERED",
            registry_status="INACTIVE",
        )
    except ProductStrategyTaxonomyError as exc:
        assert str(exc) != "INVALID_STRATEGY_CLUSTER"


def test_a_truly_unknown_cluster_is_still_rejected():
    sid = next(s for s in SCENE_STRATEGIES if s != "GENERIC_FALLBACK")
    with pytest.raises(ProductStrategyTaxonomyError) as exc:
        _validate_registry_binding(
            cluster="not_a_real_cluster",
            product_type_group="whatever",
            matched_scene_strategy_id=sid,
            scene_coverage_status="COVERED",
            registry_status="INACTIVE",
        )
    assert str(exc.value) == "INVALID_STRATEGY_CLUSTER"
