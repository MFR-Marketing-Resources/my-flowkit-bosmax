"""Invariants for the SSOT cluster crosswalk (strategy 40 -> creative 12).

These are the guardrails that let avatar/scene/copy project off the stored
strategy cluster without ever silently mis-grouping. If someone adds a new
strategy cluster to the code authority without a crosswalk entry, the domain
test hard-fails — a loud build break, never a runtime fallback.
"""
from __future__ import annotations

import json

from agent.services.product_cluster_grouping import (
    RESOLVED,
    REVIEW_REQUIRED,
    UNMAPPED_STRATEGY_CLUSTER,
    crosswalk_domain,
    crosswalk_range,
    resolve_creative_cluster,
    resolve_product_grouping,
)


def _code_domain() -> set[str]:
    """The authoritative 40-cluster union straight from the code sources."""
    from agent.authority.catalog_product_type_truth import (
        CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS,
        P58_PRODUCT_TRUTH_OVERRIDES,
    )
    from agent.services.product_strategy_scouting_service import SCOUTING_CLUSTER_ORDER

    def cl(m):
        return getattr(m, "cluster", None) or (m[0] if isinstance(m, (tuple, list)) else None)

    domain = set(SCOUTING_CLUSTER_ORDER)
    domain |= {cl(m) for m in CATALOG_PRODUCT_TYPE_TRUTH_MAPPINGS}
    domain |= {cl(m) for m in P58_PRODUCT_TRUTH_OVERRIDES.values()}
    return {c for c in domain if c}


def _creative_12() -> set[str]:
    from agent.config import BASE_DIR

    data = json.loads(
        (BASE_DIR / "agent" / "authority" / "creative_category_cluster_map.json").read_text(
            encoding="utf-8"
        )
    )
    return set(data["clusters"])


def test_domain_equals_the_40_code_union_exactly():
    # A new stored cluster with no crosswalk entry (or a stale entry) fails HERE.
    assert crosswalk_domain() == _code_domain()


def test_range_is_a_subset_of_the_12_creative_clusters():
    assert crosswalk_range() <= _creative_12()


def test_every_cluster_maps_to_a_valid_bucket_or_the_review_sentinel():
    twelve = _creative_12()
    for cluster in crosswalk_domain():
        target = resolve_creative_cluster(cluster)
        assert target is None or target in twelve, f"{cluster} -> {target}"


def test_generic_unclassified_is_the_review_sentinel():
    assert resolve_creative_cluster("generic_unclassified") is None
    g = resolve_product_grouping("generic_unclassified")
    assert g["grouping_status"] == REVIEW_REQUIRED and g["creative_cluster"] is None


def test_unknown_cluster_is_unmapped_never_a_fallback():
    g = resolve_product_grouping("totally_made_up_cluster")
    assert g["grouping_status"] == UNMAPPED_STRATEGY_CLUSTER
    assert g["creative_cluster"] is None  # never Home & Living or any real bucket


def test_missing_taxonomy_is_review_required():
    assert resolve_product_grouping(None)["grouping_status"] == REVIEW_REQUIRED
    assert resolve_product_grouping("")["grouping_status"] == REVIEW_REQUIRED


def test_resolved_happy_path_and_passthrough():
    g = resolve_product_grouping("fashion_apparel", product_type_group="modestwear", taxonomy_status="VERIFIED")
    assert g["grouping_status"] == RESOLVED
    assert g["creative_cluster"] == "Fashion"
    assert g["product_type_group"] == "modestwear"
    assert g["taxonomy_status"] == "VERIFIED"


def test_bosmax_flagship_wellness_maps_to_beauty():
    # BOSMAX core products (MWCB 6483d624, Bosmax Herbs 90349f8c) are herbal/
    # traditional wellness; no Wellness/Health bucket exists in the 12, so Beauty
    # is the ratified target. Pinned so a crosswalk edit is a conscious choice.
    assert resolve_creative_cluster("traditional_wellness") == "Beauty"
    assert resolve_creative_cluster("sensitive_wellness") == "Beauty"
