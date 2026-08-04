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


@pytest.mark.asyncio
async def test_list_bulk_queue_filters_by_cluster_and_product_type():
    """The queue filter is the operator's work surface: pick one cluster, then one
    product type within it, then update that batch. Unique cluster names isolate
    this from other tests sharing the in-memory DB."""
    for ref, title, cl, ptg in [
        ("filt-a1", "A1", "cluster_alpha", "type_x"),
        ("filt-a2", "A2", "cluster_alpha", "type_y"),
        ("filt-b1", "B1", "cluster_beta", "type_x"),
    ]:
        await crud.create_bulk_queue_row(
            ref, title, cluster=cl, product_type_group=ptg,
            claim_risk_level="LOW", image_readiness="IMAGE_MISSING",
        )
    await crud.create_bulk_queue_row(  # no cluster -> unclassified
        "filt-un", "UN", claim_risk_level="LOW", image_readiness="IMAGE_MISSING")

    alpha = await crud.list_bulk_queue(cluster="cluster_alpha", page_size=None)
    assert {r["reference_id"] for r in alpha} == {"filt-a1", "filt-a2"}

    alpha_x = await crud.list_bulk_queue(
        cluster="cluster_alpha", product_type_group="type_x", page_size=None)
    assert {r["reference_id"] for r in alpha_x} == {"filt-a1"}

    assert await crud.count_bulk_queue(cluster="cluster_alpha") == 2

    unclassified = await crud.list_bulk_queue(cluster="__UNCLASSIFIED__", page_size=None)
    refs = {r["reference_id"] for r in unclassified}
    assert "filt-un" in refs and "filt-a1" not in refs
