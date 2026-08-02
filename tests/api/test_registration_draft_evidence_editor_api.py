import json
import sqlite3
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.config import DB_PATH
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
        assert payload["storage_backend"] == "SQLITE_DATABASE"
        assert payload["storage_location"].endswith(
            ":product_registration_review_draft"
        )
        assert not (tmp_path / "draft-api-evidence-001.json").exists()

        with sqlite3.connect(str(DB_PATH)) as connection:
            row = connection.execute(
                "SELECT payload_json FROM product_registration_review_draft "
                "WHERE draft_id=?",
                ("draft-api-evidence-001",),
            ).fetchone()
        assert row is not None
        stored_payload = json.loads(row[0])
        assert stored_payload["declared_evidence_fields"]["price"] == 39.9
        assert stored_payload["storage_backend"] == "SQLITE_DATABASE"

        reloaded = RegistrationDraftStorageService.get_draft(
            "draft-api-evidence-001"
        )
        assert reloaded is not None
        assert reloaded.declared_evidence_fields["price"] == 39.9
        assert reloaded.storage_backend == "SQLITE_DATABASE"

        fresh_session = TestClient(app)
        rehydrated_response = fresh_session.get(
            "/api/product-registration/review-drafts/draft-api-evidence-001"
        )
        assert rehydrated_response.status_code == 200
        assert rehydrated_response.json()["declared_evidence_fields"]["price"] == 39.9
        assert rehydrated_response.json()["storage_backend"] == "SQLITE_DATABASE"


def test_legacy_json_draft_is_readable_then_deduped_after_database_save(tmp_path):
    draft = RegistrationReviewDraft(
        review_draft_id="draft-legacy-evidence-001",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="FASTMOSS_PROMOTED",
        declared_evidence_fields={
            "product_name": "Legacy Draft",
            "source_lane": "FASTMOSS_PROMOTED",
        },
    )
    legacy_path = tmp_path / "draft-legacy-evidence-001.json"
    legacy_path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")

    with patch(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    ):
        legacy = RegistrationDraftStorageService.get_draft(
            "draft-legacy-evidence-001"
        )
        assert legacy is not None
        assert legacy.storage_backend == "LEGACY_JSON"

        saved = RegistrationDraftStorageService.save_draft(legacy)
        listed = [
            item
            for item in RegistrationDraftStorageService.list_drafts()
            if item.review_draft_id == "draft-legacy-evidence-001"
        ]

    assert saved.storage_backend == "SQLITE_DATABASE"
    assert legacy_path.exists()
    assert len(listed) == 1
    assert listed[0].storage_backend == "SQLITE_DATABASE"
