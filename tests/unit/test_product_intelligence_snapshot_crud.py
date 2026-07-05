import pytest

from agent.db import crud


@pytest.mark.asyncio
async def test_product_intelligence_snapshot_crud_round_trip_and_latest_approved():
    product = await crud.create_product(
        raw_product_title="Bosmax Snapshot Test",
        source="MANUAL",
        product_display_name="Bosmax Snapshot Test",
        product_short_name="Bosmax Snapshot",
    )

    draft = await crud.create_product_intelligence_snapshot(
        product_id=product["id"],
        version=1,
        status="DRAFT",
        benefits_json='["calm routine"]',
        source_urls_json='{"source_url":"https://example.com/source"}',
    )
    approved_v2 = await crud.create_product_intelligence_snapshot(
        product_id=product["id"],
        version=2,
        status="APPROVED",
        benefits_json='["calm routine","portable use"]',
        approved_at="2026-07-05T10:00:00Z",
        created_by="architect",
    )
    approved_v3 = await crud.create_product_intelligence_snapshot(
        product_id=product["id"],
        version=3,
        status="APPROVED",
        benefits_json='["portable use"]',
        approved_at="2026-07-05T11:00:00Z",
        created_by="architect",
    )

    loaded = await crud.get_product_intelligence_snapshot(approved_v3["snapshot_id"])
    assert loaded is not None
    assert loaded["product_id"] == product["id"]
    assert loaded["version"] == 3

    rows = await crud.list_product_intelligence_snapshots(product_id=product["id"], limit=None)
    assert [row["version"] for row in rows] == [3, 2, 1]

    approved_rows = await crud.list_product_intelligence_snapshots(
        product_id=product["id"], status="APPROVED", limit=None
    )
    assert [row["version"] for row in approved_rows] == [3, 2]

    latest = await crud.get_latest_approved_product_intelligence_snapshot(product["id"])
    assert latest is not None
    assert latest["snapshot_id"] == approved_v3["snapshot_id"]
    assert latest["version"] == 3
    assert draft["status"] == "DRAFT"
    assert approved_v2["status"] == "APPROVED"
