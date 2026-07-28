import pytest
from fastapi.testclient import TestClient
from agent.main import app
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
)

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
    assert data["strategy_taxonomy"]["materialization_status"] == "PREVIEW"
    assert data["strategy_taxonomy"]["review_status"] == "REVIEW_REQUIRED"
    assert data["strategy_taxonomy"]["consumer_status"] == "BLOCKED_REVIEW_REQUIRED"

def test_api_review_draft_malformed():
    # Empty payload or missing required fields should fail validation
    response = client.post("/api/product-registration/review-draft", json={})
    assert response.status_code == 422


def test_manual_draft_taxonomy_save_is_registry_validated(monkeypatch):
    captured = {}
    saved_drafts = []

    async def fake_validate(**kwargs):
        captured.update(kwargs)

    def fake_save(draft):
        saved_drafts[:] = [draft]
        return draft

    monkeypatch.setattr(
        "agent.api.product_registration._strategy_taxonomy.validate_product_strategy_assignment",
        fake_validate,
    )
    monkeypatch.setattr(
        "agent.api.product_registration.RegistrationDraftStorageService.save_draft",
        fake_save,
    )
    monkeypatch.setattr(
        "agent.api.product_registration.RegistrationDraftStorageService.list_drafts",
        lambda: saved_drafts,
    )
    payload = {
        "review_draft_id": "draft-taxonomy-api",
        "review_status": "NEEDS_HUMAN_REVIEW",
        "source_lane": "MANUAL",
        "strategy_taxonomy": {
            "product_id": "draft-taxonomy-api",
            "taxonomy_version": "product_strategy_taxonomy_v1",
            "product_fingerprint": "fingerprint",
            "cluster": "beauty_makeup",
            "product_type_group": "lipstick_lip_tint",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "COVERED",
            "fallback_used": False,
            "specific_strategy": True,
            "classification_confidence": "HIGH",
            "review_status": "VERIFIED",
            "consumer_status": "BLOCKED_REVIEW_REQUIRED",
            "authority_source": "MANUAL_OVERRIDE",
            "materialization_status": "PREVIEW",
            "review_reasons": [],
            "reviewer_id": "admin-1",
            "reviewer_note": "Reviewed registry binding.",
            "is_stale": False,
        },
    }

    response = client.post(
        "/api/product-registration/review-drafts",
        json=payload,
    )
    readback = client.get("/api/product-registration/review-drafts")

    assert response.status_code == 200
    assert readback.status_code == 200
    assert (
        readback.json()[0]["strategy_taxonomy"]["product_type_group"]
        == "lipstick_lip_tint"
    )
    assert captured["product_type_group"] == "lipstick_lip_tint"
    assert captured["review_status"] == "VERIFIED"


def test_manual_draft_taxonomy_rejects_unregistered_pair(monkeypatch):
    async def fake_validate(**kwargs):
        raise ProductStrategyTaxonomyError(
            "UNREGISTERED_PRODUCT_STRATEGY_TYPE"
        )

    monkeypatch.setattr(
        "agent.api.product_registration._strategy_taxonomy.validate_product_strategy_assignment",
        fake_validate,
    )
    payload = {
        "review_draft_id": "draft-taxonomy-invalid",
        "review_status": "NEEDS_HUMAN_REVIEW",
        "source_lane": "MANUAL",
        "strategy_taxonomy": {
            "product_id": "draft-taxonomy-invalid",
            "taxonomy_version": "product_strategy_taxonomy_v1",
            "product_fingerprint": "fingerprint",
            "cluster": "beauty_makeup",
            "product_type_group": "made_up_group",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "COVERED",
            "fallback_used": False,
            "specific_strategy": True,
            "classification_confidence": "HIGH",
            "review_status": "REVIEW_REQUIRED",
            "consumer_status": "BLOCKED_REVIEW_REQUIRED",
            "authority_source": "MANUAL_OVERRIDE",
            "materialization_status": "PREVIEW",
            "review_reasons": ["MANUAL_REVIEW_REQUIRED"],
            "reviewer_id": "admin-1",
            "reviewer_note": "Review.",
            "is_stale": False,
        },
    }

    response = client.post(
        "/api/product-registration/review-drafts",
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "UNREGISTERED_PRODUCT_STRATEGY_TYPE"
