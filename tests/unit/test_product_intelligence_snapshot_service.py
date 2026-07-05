import pytest

from agent.db.schema import _db_lock, get_db
from agent.services import product_intelligence_snapshot_service as svc
from agent.db import crud


@pytest.mark.asyncio
async def test_snapshot_service_normalizes_invalid_json_to_safe_defaults():
    product = await crud.create_product(
        raw_product_title="Bosmax Corrupt Snapshot",
        source="MANUAL",
        product_display_name="Bosmax Corrupt Snapshot",
        product_short_name="Bosmax Corrupt",
    )
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """
            INSERT INTO product_intelligence_snapshot (
                snapshot_id, product_id, version, status, benefits_json, source_urls_json,
                image_evidence_json, claim_tokens_json, allowed_claims_json, blocked_claims_json,
                buyer_persona_snapshot_json, copy_strategy_summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snap-corrupt-001",
                product["id"],
                1,
                "APPROVED",
                "{bad",
                "[]",
                "{bad",
                '{"not":"a list"}',
                "{bad",
                "[]",
                "[]",
                "{bad",
                "2026-07-05T00:00:00Z",
                "2026-07-05T00:00:00Z",
            ),
        )
        await db.commit()

    snapshot = await svc.get_snapshot_by_id("snap-corrupt-001")
    assert snapshot is not None
    assert snapshot.benefits_json == []
    assert snapshot.source_urls_json == {}
    assert snapshot.image_evidence_json == {}
    assert snapshot.claim_tokens_json == []
    assert snapshot.allowed_claims_json == []
    assert snapshot.blocked_claims_json == []
    assert snapshot.buyer_persona_snapshot_json == {}
    assert snapshot.copy_strategy_summary_json == {}


@pytest.mark.asyncio
async def test_latest_snapshot_response_returns_empty_state_without_approved_snapshot():
    product = await crud.create_product(
        raw_product_title="Bosmax Empty Snapshot State",
        source="MANUAL",
        product_display_name="Bosmax Empty Snapshot State",
        product_short_name="Bosmax Empty",
    )

    response = await svc.get_latest_snapshot_response(product["id"])

    assert response.product_id == product["id"]
    assert response.latest_snapshot is None
    assert response.status == "NO_APPROVED_SNAPSHOT"
    assert response.provenance_summary.total_snapshots == 0
    assert response.provenance_summary.approved_snapshot_count == 0
