import pytest
from agent.services.product_registration_service import create_registration_review_draft
from agent.models.product_knowledge import ProductKnowledgeCompleteResponse, ModeReadiness

def test_create_review_draft_basic():
    completion = ProductKnowledgeCompleteResponse(
        completion_status="COMPLETION_READY",
        input_quality_status="SUFFICIENT",
        declared_evidence_summary="Name: Test Product",
        extracted_product_facts={"product_name": "Test Product", "price": 10.0},
        suggested_normalized_name="Test Product",
        suggested_category="Electronics",
        claim_gate="CLAIM_SAFE",
        claim_risk_level="LOW",
        readiness_by_mode={
            "registration": ModeReadiness(status="READY", detail="Ready")
        }
    )
    
    draft = create_registration_review_draft(completion)
    
    assert draft.review_status == "REVIEW_READY"
    assert draft.canonical_candidate_fields["normalized_name"] == "Test Product"
    assert draft.canonical_candidate_fields["category"] == "Electronics"
    assert draft.declared_evidence_fields["product_name"] == "Test Product"
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
