from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraft,
)


def test_product_intelligence_review_draft_model_defaults_are_structured():
    draft = ProductIntelligenceReviewDraft(
        draft_id="draft-001",
        product_id="prod-001",
        review_status="DRAFT",
        created_at="2026-07-06T00:00:00Z",
        updated_at="2026-07-06T00:00:00Z",
    )

    assert draft.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert draft.claim_risk_level == "MEDIUM"
    assert draft.benefits_json == []
    assert draft.usp_json == []
    assert draft.source_urls_json == {}
    assert draft.image_evidence_json == {}
    assert draft.allowed_claims_json == []
    assert draft.blocked_claims_json == []
    assert draft.buyer_persona_snapshot_json == {}
    assert draft.copy_strategy_summary_json == {}
    assert draft.provenance_items == []
