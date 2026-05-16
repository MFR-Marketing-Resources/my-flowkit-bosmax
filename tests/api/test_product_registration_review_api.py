import pytest
from fastapi.testclient import TestClient
from agent.main import app

client = TestClient(app)

def test_api_review_draft_create():
    completion_payload = {
        "completion_status": "COMPLETION_READY",
        "input_quality_status": "SUFFICIENT",
        "declared_evidence_summary": "Name: API Test",
        "extracted_product_facts": {"product_name": "API Test"},
        "suggested_normalized_name": "API Test",
        "suggested_category": "Test Category",
        "claim_gate": "CLAIM_SAFE",
        "claim_risk_level": "LOW",
        "readiness_by_mode": {}
    }
    
    response = client.post("/api/product-registration/review-draft", json=completion_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["review_status"] == "REVIEW_READY"
    assert data["canonical_candidate_fields"]["normalized_name"] == "API Test"
    assert data["write_back_allowed"] is False

def test_api_review_draft_malformed():
    # Empty payload or missing required fields should fail validation
    response = client.post("/api/product-registration/review-draft", json={})
    assert response.status_code == 422
