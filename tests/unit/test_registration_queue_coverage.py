"""Registration-queue coverage metric — surfaces the PRE-COMMIT cluster /
product-type backlog that the committed-product KPIs cannot see.

Context: the Command Centre 'missing_cluster' KPI counts committed products (all
of which have a cluster) → 0, which reads as "all clustered" while N registration
drafts still await one. This metric makes that unambiguous.
"""
from __future__ import annotations

import uuid

import pytest

from agent.db import crud
from agent.services.reporting_service import registration_queue_coverage


@pytest.mark.asyncio
async def test_pending_uncommitted_no_cluster_draft_is_backlog():
    before = await registration_queue_coverage()
    ref = "test-cov-" + uuid.uuid4().hex[:12]
    await crud.create_bulk_queue_row(
        ref, "ZZ Coverage Fixture", claim_risk_level="LOW", promotion_status="PENDING_DRAFT",
    )
    after = await registration_queue_coverage()
    assert after["pending_drafts"] == before["pending_drafts"] + 1
    assert after["pending_missing_cluster"] == before["pending_missing_cluster"] + 1
    # accounting reconciles by construction
    assert after["committed"] + after["pending_drafts"] == after["total_queue_rows"]
    assert after["pending_missing_cluster"] <= after["pending_drafts"]


@pytest.mark.asyncio
async def test_generic_unclassified_pending_draft_counts_as_missing():
    # generic_unclassified is "not usefully classified" — must stay in the backlog,
    # not silently drop off it (matches the product missing_cluster predicate).
    before = await registration_queue_coverage()
    ref = "test-cov-" + uuid.uuid4().hex[:12]
    await crud.create_bulk_queue_row(
        ref, "ZZ Generic Draft", claim_risk_level="LOW",
        cluster="generic_unclassified", product_type_group="unknown_product_type",
        promotion_status="PENDING_DRAFT",
    )
    after = await registration_queue_coverage()
    assert after["pending_missing_cluster"] == before["pending_missing_cluster"] + 1
    assert after["pending_missing_product_type"] == before["pending_missing_product_type"] + 1


@pytest.mark.asyncio
async def test_a_clustered_pending_draft_is_not_counted_missing():
    before = await registration_queue_coverage()
    ref = "test-cov-" + uuid.uuid4().hex[:12]
    await crud.create_bulk_queue_row(
        ref, "ZZ Coverage Clustered", claim_risk_level="LOW",
        cluster="beauty_makeup", promotion_status="PENDING_DRAFT",
    )
    after = await registration_queue_coverage()
    assert after["pending_drafts"] == before["pending_drafts"] + 1
    assert after["pending_missing_cluster"] == before["pending_missing_cluster"]
