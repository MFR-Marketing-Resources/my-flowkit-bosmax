import pytest
from fastapi.testclient import TestClient
from agent.main import app

client = TestClient(app)

def test_api_review_draft_create():
    completion_payload = {
        "completion_status": "COMPLETION_READY",
        "input_quality_status": "SUFFICIENT",
        "declared_evidence_summary": "Name: API Test",
        "declared_input_fields": {
            "product_name": "API Test",
            "image_url": "https://example.com/api.jpg",
            "product_url": "https://example.com/api",
            "currency": "MYR",
            "commission_amount": 2.4,
            "commission_rate": "12%",
        },
        "extracted_product_facts": {"product_name": "API Test"},
        "suggested_normalized_name": "API Test",
        "suggested_category": "Test Category",
        "claim_gate": "CLAIM_SAFE",
        "claim_risk_level": "LOW",
        "image_analysis_status": "VISION_PROVIDER_NOT_CONFIGURED",
        "image_analysis_provider": "not_configured",
        "image_analysis_visual_confidence": "NOT_VERIFIED",
        "readiness_by_mode": {}
    }
    
    response = client.post("/api/product-registration/review-draft", json=completion_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["review_status"] == "REVIEW_READY"
    assert data["canonical_candidate_fields"]["normalized_name"] == "API Test"
    assert data["declared_evidence_fields"]["image_url"] == "https://example.com/api.jpg"
    assert data["system_inferred_fields"]["image_analysis_status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert data["write_back_allowed"] is False

def test_api_review_draft_malformed():
    # Empty payload or missing required fields should fail validation
    response = client.post("/api/product-registration/review-draft", json={})
    assert response.status_code == 422
