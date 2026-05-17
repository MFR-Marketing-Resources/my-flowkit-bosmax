from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent.main import app
from agent.models.product_registration import RegistrationReviewDraft
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService


client = TestClient(app)


def test_patch_review_draft_image_attach_caches_image_and_serves_preview(tmp_path):
    cached_image = tmp_path / "cached-bosmax.png"
    cached_image.write_bytes(b"png")

    with patch(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    ), patch(
        "agent.services.registration_draft_evidence_editor_service._persist_intake_image",
        return_value=str(cached_image),
    ):
        draft = RegistrationReviewDraft(
            review_draft_id="draft-api-image-001",
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
                "price": 39.9,
                "commission_amount": 4.5,
                "commission_rate": "10%",
            },
        )
        RegistrationDraftStorageService.save_draft(draft)

        response = client.patch(
            "/api/product-registration/review-drafts/draft-api-image-001/evidence",
            json={
                "image_base64": "data:image/png;base64,cG5n",
                "image_filename": "bosmax.png",
                "recompute": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["declared_evidence_fields"]["local_image_path"] == str(cached_image)
        assert payload["image_asset_status"] == "IMAGE_CACHE_READY"

        preview = client.get("/api/product-registration/review-drafts/draft-api-image-001/image")
        assert preview.status_code == 200
