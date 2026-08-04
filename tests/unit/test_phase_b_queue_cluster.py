"""SSOT Phase B — the FastMoss queue row must carry the creative taxonomy
(cluster + product_type_group) so the list can show it, not just the commerce
category. sync_queue_row_from_draft copies it from the draft's strategy_taxonomy,
and must NOT wipe an existing value when a draft has no taxonomy.
"""
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.services.fastmoss_bulk_promotion_service import sync_queue_row_from_draft


def _draft(did, title, *, cluster=None, product_type_group=None):
    strategy = (
        SimpleNamespace(cluster=cluster, product_type_group=product_type_group)
        if (cluster or product_type_group)
        else None
    )
    return SimpleNamespace(
        review_draft_id=did,
        declared_evidence_fields={
            "product_name": title,
            "image_url": "https://x/i.jpg",
            "tiktok_product_url": None,
        },
        claim_risk_level="LOW",
        missing_required_evidence=[],
        claim_tokens=[],
        claim_gate="CLAIM_SAFE",
        strategy_taxonomy=strategy,
    )


@pytest.mark.asyncio
async def test_sync_populates_cluster_and_product_type_from_draft():
    ref, did = "fastmoss-ref:clustersync", "draft-clustersync"
    await crud.create_bulk_queue_row(
        ref, "Anna Fabric Curtain",
        promotion_status="PENDING_DRAFT", draft_id=did,
        claim_risk_level="LOW", image_readiness="IMAGE_REFERENCE_READY",
    )
    updated = await sync_queue_row_from_draft(
        _draft(did, "Anna Fabric Curtain",
               cluster="home_textiles", product_type_group="curtain")
    )
    assert updated["cluster"] == "home_textiles"
    assert updated["product_type_group"] == "curtain"


@pytest.mark.asyncio
async def test_sync_without_taxonomy_does_not_wipe_existing():
    ref, did = "fastmoss-ref:noclobber", "draft-noclobber"
    await crud.create_bulk_queue_row(
        ref, "Seluar",
        promotion_status="PENDING_DRAFT", draft_id=did,
        claim_risk_level="LOW", image_readiness="IMAGE_REFERENCE_READY",
        cluster="fashion_apparel", product_type_group="bottom_apparel",
    )
    # a draft with no strategy_taxonomy must leave the existing values intact
    updated = await sync_queue_row_from_draft(_draft(did, "Seluar"))
    assert updated["cluster"] == "fashion_apparel"
    assert updated["product_type_group"] == "bottom_apparel"
