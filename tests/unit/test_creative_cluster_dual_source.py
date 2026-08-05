"""PR-3 dual-source cluster resolver.

A product's creative cluster is projected from its stored, VERIFIED strategy
taxonomy; only an unverified/absent taxonomy falls back to the legacy category
derivation — and that fallback is tagged, never silent.
"""
from __future__ import annotations

import pytest

from agent.services import creative_avatar_recommendation_service as svc


class _StubTaxonomy:
    """Minimal stand-in for ProductStrategyTaxonomy (only ``.cluster`` is read)."""

    def __init__(self, cluster: str) -> None:
        self.cluster = cluster


def test_verified_projects_flagship_wellness_to_beauty():
    out = svc._project_dual_source(_StubTaxonomy("traditional_wellness"), "Food & Beverages")
    assert out["cluster"] == "Beauty"
    assert out["cluster_source"] == "STRATEGY_CLUSTER_VERIFIED"
    assert out["cluster_provenance"] == "STRATEGY_CLUSTER_VERIFIED"


def test_verified_but_unmapped_fails_closed_never_legacy():
    # ``generic_unclassified`` maps to the null sentinel in the crosswalk -> a
    # verified product must fail closed, NOT silently revert to its category.
    out = svc._project_dual_source(
        _StubTaxonomy("generic_unclassified"), "Beauty & Personal Care"
    )
    assert out["cluster"] is None
    assert out["cluster_source"] == "STRATEGY_CLUSTER_UNMAPPED"
    assert out["cluster_provenance"] == "STRATEGY_CLUSTER_VERIFIED"


@pytest.mark.parametrize(
    "category",
    ["Beauty & Personal Care", "Food & Beverages", "Totally Unknown Thing", "", None],
)
def test_unverified_is_exactly_legacy_plus_provenance_tag(category):
    legacy = svc.resolve_cluster(category, allow_fallback=False)
    out = svc._project_dual_source(None, category)
    # cluster + cluster_source are preserved byte-for-byte from the legacy resolver
    # (so callers asserting EXACT / REVIEW_REQUIRED_* sources keep working); only the
    # additive provenance records that the fallback lane was taken.
    assert out["cluster"] == legacy["cluster"]
    assert out["cluster_source"] == legacy["cluster_source"]
    assert out["cluster_provenance"] == "LEGACY_CATEGORY_DERIVATION"


@pytest.mark.asyncio
async def test_async_resolver_without_product_id_uses_legacy():
    out = await svc.resolve_product_cluster("", "Totally Unknown Thing")
    assert out["cluster"] is None
    assert out["cluster_source"] == "REVIEW_REQUIRED_UNKNOWN_CATEGORY"
    assert out["cluster_provenance"] == "LEGACY_CATEGORY_DERIVATION"


def test_sync_resolver_without_product_id_uses_legacy():
    out = svc.resolve_product_cluster_sync({}, "Totally Unknown Thing")
    assert out["cluster"] is None
    assert out["cluster_source"] == "REVIEW_REQUIRED_UNKNOWN_CATEGORY"
    assert out["cluster_provenance"] == "LEGACY_CATEGORY_DERIVATION"
