"""PR-3 cross-surface SSOT invariant.

One VERIFIED product resolves to the SAME creative cluster across every
product-first surface (direction / setup / avatar / scene / camera / suitability),
driven by its stored strategy taxonomy — NOT re-derived from the product's
(deliberately divergent) category. This is the end-to-end complement to the
static crosswalk pin in ``test_creative_cluster_crosswalk.py``.
"""
from __future__ import annotations

import pytest

from agent.db import crud
from agent.models.creative_direction import CreativeMode
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomyReviewRequest,
    ProductStrategyTypeRegistrySeedRequest,
)
from agent.services import product_strategy_taxonomy_service as service
from agent.services.creative_avatar_recommendation_service import (
    recommend_avatars_for_product,
)
from agent.services.creative_camera_preset_service import (
    recommend_camera_presets_for_product,
)
from agent.services.creative_direction_service import resolve_creative_direction
from agent.services.creative_scene_prompt_service import (
    recommend_scene_prompts_for_product,
)
from agent.services.creative_setup_service import save_creative_selection
from agent.services.product_cluster_grouping import resolve_creative_cluster
from agent.services.product_scene_suitability_service import (
    recommend_scene_suitability_for_product,
)


async def _seed_registry() -> None:
    await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=service.REGISTRY_SEED_CONFIRMATION,
        )
    )


@pytest.mark.asyncio
async def test_verified_product_resolves_to_one_creative_cluster_across_surfaces():
    await _seed_registry()
    # Category deliberately DIVERGES from the verified cluster: the legacy
    # derivation would route this product to a Food & Beverage bucket, so any
    # surface that still re-derived from category (pre-PR-3) would disagree.
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Velvet Lip Tint",
        product_display_name="Velvet Lip Tint",
        product_short_name="Velvet Lip Tint",
        category="Food & Beverages",
        subcategory="Makeup",
        type="Lipstick",
        product_type="Lipstick",
        product_type_id="LIPSTICK",
    )
    pid = product["id"]
    await service.review_product_strategy_taxonomy(
        pid,
        ProductStrategyTaxonomyReviewRequest(
            expected_product_fingerprint=service.product_strategy_fingerprint(product),
            cluster="beauty_makeup",
            product_type_group="lipstick_lip_tint",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            review_status="VERIFIED",
            reviewer_id="admin-1",
            reviewer_note="Cross-surface SSOT test.",
        ),
    )

    expected = resolve_creative_cluster("beauty_makeup")  # SSOT projection
    assert expected == "Beauty"

    # core surfaces
    direction = resolve_creative_direction(CreativeMode.UGC_AUTHENTIC, product=product)
    assert direction.canonical_cluster == expected
    assert direction.cluster_source == "STRATEGY_CLUSTER_VERIFIED"

    saved = await save_creative_selection(pid)
    assert saved["cluster"] == expected

    # recommendation surfaces
    assert (await recommend_avatars_for_product(pid))["cluster"] == expected
    assert (await recommend_scene_prompts_for_product(pid))["cluster"] == expected
    assert (await recommend_camera_presets_for_product(pid))["cluster"] == expected
    assert (await recommend_scene_suitability_for_product(pid))["cluster"] == expected


def test_flagship_wellness_clusters_project_to_beauty():
    # The BOSMAX flagship (MWCB / Bosmax Herbs): both wellness strategy clusters
    # crosswalk to the single Beauty creative bucket.
    assert resolve_creative_cluster("traditional_wellness") == "Beauty"
    assert resolve_creative_cluster("sensitive_wellness") == "Beauty"
    assert resolve_creative_cluster("beauty_makeup") == "Beauty"
