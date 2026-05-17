import pytest
from agent.services.product_registration_service import create_registration_review_draft
from agent.models.product_knowledge import ProductKnowledgeCompleteResponse, ModeReadiness

def test_create_review_draft_basic():
    completion = ProductKnowledgeCompleteResponse(
        completion_status="COMPLETION_READY",
        input_quality_status="SUFFICIENT",
        declared_evidence_summary="Name: Test Product",
        declared_input_fields={
            "product_name": "Test Product",
            "source_lane": "OWNED",
            "size_or_volume": "5 ML",
            "image_url": "https://example.com/product.jpg",
            "product_url": "https://example.com/product",
            "price": 10.0,
            "currency": "MYR",
            "commission_amount": 1.5,
            "commission_rate": "15%",
        },
        extracted_product_facts={"product_name": "Test Product", "price": 10.0},
        suggested_normalized_name="Test Product",
        suggested_size_or_volume="5 ML",
        suggested_category="Electronics",
        claim_gate="CLAIM_SAFE",
        claim_risk_level="LOW",
        image_analysis_status="VISION_PROVIDER_NOT_CONFIGURED",
        image_analysis_provider="not_configured",
        image_analysis_visual_confidence="NOT_VERIFIED",
        image_analysis_warnings=["SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"],
        image_analysis_image_url="https://example.com/product.jpg",
        readiness_by_mode={
            "registration": ModeReadiness(status="READY", detail="Ready")
        }
    )
    
    draft = create_registration_review_draft(completion)
    
    assert draft.review_status == "REVIEW_READY"
    assert draft.canonical_candidate_fields["normalized_name"] == "Test Product"
    assert draft.canonical_candidate_fields["size_or_volume"] == "5 ML"
    assert draft.canonical_candidate_fields["category"] == "Electronics"
    assert draft.declared_evidence_fields["product_name"] == "Test Product"
    assert draft.declared_evidence_fields["image_url"] == "https://example.com/product.jpg"
    assert draft.declared_evidence_fields["product_url"] == "https://example.com/product"
    assert draft.declared_evidence_fields["currency"] == "MYR"
    assert draft.system_inferred_fields["image_analysis_status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert draft.source_lane == "OWNED"
    assert draft.write_back_allowed is False
    assert draft.write_back_status == "READ_ONLY_REVIEW_PREVIEW"

def test_create_review_draft_risky_claim():
    completion = ProductKnowledgeCompleteResponse(
        completion_status="NEEDS_REVIEW",
        input_quality_status="PARTIAL",
        declared_evidence_summary="Name: Risky Tea",
        extracted_product_facts={"product_name": "Risky Tea"},
        suggested_normalized_name="Risky Tea",
        claim_gate="CLAIM_BLOCKED",
        claim_tokens=["cure"],
        claim_risk_level="CRITICAL",
        blocked_fields=["claims"],
        human_review_fields=["ingredients"],
        readiness_by_mode={}
    )
    
    draft = create_registration_review_draft(completion)
    
    assert draft.review_status == "BLOCKED"
    assert draft.claim_gate == "CLAIM_BLOCKED"
    assert "claims" in draft.blocked_fields
    assert "ingredients" in draft.human_review_fields

def test_create_review_draft_affiliate_lane():
    completion = ProductKnowledgeCompleteResponse(
        completion_status="COMPLETION_READY",
        input_quality_status="SUFFICIENT",
        declared_evidence_summary="Name: Affiliate Product",
        extracted_product_facts={"product_name": "Affiliate Product"},
        suggested_normalized_name="Affiliate Product",
        claim_gate="CLAIM_SAFE",
        warnings=["AFFILIATE_LANE_CONTAMINATION_RISK"],
        readiness_by_mode={}
    )
    
    draft = create_registration_review_draft(completion)
    
    assert draft.review_status == "NEEDS_HUMAN_REVIEW"
    assert draft.source_lane == "AFFILIATE_CONTAMINATED"
    assert "AFFILIATE_LANE_CONTAMINATION_RISK" in draft.warnings

def test_create_review_draft_missing_evidence():
    completion = ProductKnowledgeCompleteResponse(
        completion_status="NEEDS_REVIEW",
        input_quality_status="PARTIAL",
        declared_evidence_summary="Name: Incomplete",
        extracted_product_facts={"product_name": "Incomplete"},
        missing_required_evidence=["SIZE_OR_VOLUME_EVIDENCE"],
        readiness_by_mode={}
    )
    
    draft = create_registration_review_draft(completion)
    
    assert draft.review_status == "NEEDS_HUMAN_REVIEW"
    assert "SIZE_OR_VOLUME_EVIDENCE" in draft.missing_required_evidence
    assert draft.scale_truth_status == "NEEDS_REVIEW"
