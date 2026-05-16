from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_registration import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_post_product_registration_evaluate(monkeypatch):
    async def fake_evaluate(request):
        assert request.product_payload["raw_product_title"] == "Atlas Laundry Detergent"
        return {
            "registration_status": "HUMAN_REVIEW_REQUIRED",
            "write_back_allowed": False,
            "write_back_performed": False,
            "dry_run_only": True,
            "product_truth_status": "TRUTH_REVIEW_REQUIRED",
            "truth_authority_source": "KEYWORD_RULE",
            "source_anchor_status": "SOURCE_ANCHOR_UNVERIFIED",
            "mapping_v2_status": "NEEDS_REVIEW",
            "mapping_confidence": "LOW",
            "taxonomy_conflict": False,
            "taxonomy_conflict_reason": None,
            "owned_product_lane_status": "OWNED_LANE_REVIEW_REQUIRED",
            "affiliate_source_contamination_risk": False,
            "canonical_fields_allowed": [],
            "declared_evidence_fields": ["raw_product_title", "category"],
            "blocked_fields": [],
            "human_review_fields": ["group", "type_of_product"],
            "required_evidence": ["SOURCE_ANCHORED_PRODUCT_EVIDENCE"],
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "claim_safety_requires_human_review": False,
            "scale_truth_status": "DERIVED_RELATIVE_SCALE",
            "product_scale_prompt": "Show bottle scale.",
            "dimension_truth_status": "DIMENSIONS_NOT_VERIFIED",
            "image_analysis_status": "VISION_PROVIDER_NOT_CONFIGURED",
            "image_analysis_provider": "not_configured",
            "image_analysis_visual_confidence": "NOT_VERIFIED",
            "physics_truth_status": "DERIVED_NOT_CANONICAL",
            "registration_warnings": ["SOURCE_ANCHOR_REVIEW_REQUIRED"],
            "registration_errors": [],
            "provenance": {"preview_only": True},
            "no_db_write_reason": "WRITE_BACK_NOT_ENABLED_IN_THIS_PR",
        }

    monkeypatch.setattr(
        "agent.api.product_registration.evaluate_product_registration",
        fake_evaluate,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/product-registration/evaluate",
        json={
            "product_payload": {
                "source": "MANUAL",
                "raw_product_title": "Atlas Laundry Detergent",
                "category": "Laundry Care",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["registration_status"] == "HUMAN_REVIEW_REQUIRED"
    assert payload["no_db_write_reason"] == "WRITE_BACK_NOT_ENABLED_IN_THIS_PR"
    assert payload["declared_evidence_fields"] == ["raw_product_title", "category"]


def test_post_product_registration_evaluate_with_product_id(monkeypatch):
    async def fake_evaluate(request):
        assert request.product_id == "prod-123"
        return {
            "registration_status": "BLOCK_REGISTRATION",
            "write_back_allowed": False,
            "write_back_performed": False,
            "dry_run_only": True,
            "product_truth_status": "SOURCE_ANCHORED_RECONCILED",
            "truth_authority_source": "SOURCE_ANCHOR",
            "source_anchor_status": "SOURCE_ANCHOR_VERIFIED_FROM_RAW_SOURCE",
            "mapping_v2_status": "READY",
            "mapping_confidence": "HIGH",
            "taxonomy_conflict": False,
            "taxonomy_conflict_reason": None,
            "owned_product_lane_status": "AFFILIATE_SOURCE_REVIEW_REQUIRED",
            "affiliate_source_contamination_risk": True,
            "canonical_fields_allowed": [],
            "declared_evidence_fields": [],
            "blocked_fields": [],
            "human_review_fields": ["group"],
            "required_evidence": [],
            "claim_gate": "CLAIM_SAFE",
            "claim_tokens": [],
            "claim_safety_requires_human_review": False,
            "scale_truth_status": "DERIVED_RELATIVE_SCALE",
            "product_scale_prompt": "Show bottle scale.",
            "dimension_truth_status": "DIMENSIONS_NOT_VERIFIED",
            "image_analysis_status": "VISION_PROVIDER_NOT_CONFIGURED",
            "image_analysis_provider": "not_configured",
            "image_analysis_visual_confidence": "NOT_VERIFIED",
            "physics_truth_status": "SOURCE_ANCHORED_DERIVED",
            "registration_warnings": ["AFFILIATE_SOURCE_CONTAMINATION_RISK"],
            "registration_errors": [],
            "provenance": {"preview_only": True},
            "no_db_write_reason": "WRITE_BACK_NOT_ENABLED_IN_THIS_PR",
        }

    monkeypatch.setattr(
        "agent.api.product_registration.evaluate_product_registration",
        fake_evaluate,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/product-registration/evaluate",
        json={"product_id": "prod-123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["affiliate_source_contamination_risk"] is True
    assert payload["registration_status"] == "BLOCK_REGISTRATION"
