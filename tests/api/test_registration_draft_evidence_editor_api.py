from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.main import app
from agent.models.product_registration import RegistrationReviewDraft
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService


client = TestClient(app)


def test_patch_review_draft_evidence_recomputes_and_persists(tmp_path):
    with patch(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    ), patch(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        return_value={
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    ), patch(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        return_value={
            "product_knowledge_summary": "Minyak herba luaran.",
            "benefits": ["Rutin self-care luaran premium"],
            "usage_summary": "Sapuan luaran.",
            "target_customer": "Lelaki dewasa yang mengutamakan rutin self-care",
            "usp_list": ["Rutin luaran yang ringkas"],
            "size_or_volume": "5 ML",
            "package_notes": None,
            "warnings_or_limitations": [],
            "confidence": "MEDIUM",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    ):
        draft = RegistrationReviewDraft(
            review_draft_id="draft-api-evidence-001",
            review_status="NEEDS_HUMAN_REVIEW",
            source_lane="OWNED",
            declared_evidence_fields={
                "product_name": "Bosmax Herbs",
                "source_lane": "OWNED",
                "product_knowledge_text": "Minyak herba luaran.",
                "benefits_text": "Rutin self-care luaran premium.",
                "usage_text": "Sapuan luaran.",
                "size_or_volume": "5 ML",
                "currency": "MYR",
                "image_url": "https://example.com/bosmax.jpg",
            },
        )
        RegistrationDraftStorageService.save_draft(draft)

        response = client.patch(
            "/api/product-registration/review-drafts/draft-api-evidence-001/evidence",
            json={
                "price": 39.9,
                "commission_amount": 4.5,
                "commission_rate": "10%",
                "hook_angles": ["Manual hook from API"],
                "cta_angles": ["Manual CTA from API"],
                "recompute": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["declared_evidence_fields"]["price"] == 39.9
        assert payload["declared_evidence_fields"]["commission_rate"] == "10%"
        assert payload["canonical_candidate_fields"]["hook_angles"] == ["Manual hook from API"]
        assert payload["canonical_candidate_fields"]["cta_angles"] == ["Manual CTA from API"]
        assert payload["canonical_candidate_fields"]["target_customer"] == (
            "Lelaki dewasa yang mengutamakan rutin self-care"
        )
        assert payload["evidence_field_status"]["target_customer"]["status"] == (
            "AI_SUGGESTED"
        )
        assert payload["evidence_field_status"]["target_customer"]["needs_review"] is True
        assert "target_customer" in payload["human_review_fields"]
        assert (
            "text_assist:deepseek:deepseek-v4-pro:review_only"
            in payload["provenance"]
        )
        assert payload["draft_freshness_status"] == "FRESH"
        assert payload["image_asset_status"] == "IMAGE_REFERENCE_READY"
        assert "PRICE_EVIDENCE" not in payload["missing_required_evidence"]
