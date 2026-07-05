from agent.models.product_intelligence_snapshot import (
    ProductIntelligenceLatestSnapshotResponse,
    ProductIntelligenceSnapshot,
)


def test_product_intelligence_snapshot_model_defaults_are_structured():
    snapshot = ProductIntelligenceSnapshot(
        snapshot_id="snap-001",
        product_id="prod-001",
        version=1,
        status="DRAFT",
        created_at="2026-07-05T00:00:00Z",
        updated_at="2026-07-05T00:00:00Z",
    )

    assert snapshot.benefits_json == []
    assert snapshot.usp_json == []
    assert snapshot.source_urls_json == {}
    assert snapshot.image_evidence_json == {}
    assert snapshot.claim_tokens_json == []
    assert snapshot.allowed_claims_json == []
    assert snapshot.blocked_claims_json == []
    assert snapshot.buyer_persona_snapshot_json == {}
    assert snapshot.copy_strategy_summary_json == {}


def test_latest_snapshot_response_allows_empty_state():
    response = ProductIntelligenceLatestSnapshotResponse(
        product_id="prod-001",
        latest_snapshot=None,
        status="NO_APPROVED_SNAPSHOT",
    )

    assert response.product_id == "prod-001"
    assert response.latest_snapshot is None
    assert response.provenance_summary.total_snapshots == 0
