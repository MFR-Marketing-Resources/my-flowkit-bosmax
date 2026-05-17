from pathlib import Path
from unittest.mock import patch

from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationReviewDraftEvidencePatchRequest,
)
from agent.services.registration_draft_evidence_editor_service import (
    patch_registration_draft_evidence,
)
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService


def test_patch_registration_draft_evidence_marks_draft_stale_without_recompute(tmp_path):
    with patch(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    ):
        draft = RegistrationReviewDraft(
            review_draft_id="draft-evidence-001",
            review_status="NEEDS_HUMAN_REVIEW",
            source_lane="OWNED",
            declared_evidence_fields={"product_name": "Bosmax Herbs", "source_lane": "OWNED"},
        )
        RegistrationDraftStorageService.save_draft(draft)

        updated = patch_registration_draft_evidence(
            "draft-evidence-001",
            RegistrationReviewDraftEvidencePatchRequest(
                price=39.9,
                commission_amount=4.5,
                commission_rate="10%",
                hook_angles=["Manual hook"],
                cta_angles=["Manual cta"],
                recompute=False,
            ),
        )

        assert updated is not None
        assert updated.declared_evidence_fields["price"] == 39.9
        assert updated.declared_evidence_fields["commission_rate"] == "10%"
        assert updated.declared_evidence_fields["hook_angles"] == ["Manual hook"]
        assert updated.draft_freshness_status == "STALE"


def test_patch_registration_draft_evidence_with_recompute_refreshes_state(tmp_path):
    cached_image = tmp_path / "draft-image.png"
    cached_image.write_bytes(b"png")
    with patch(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    ), patch(
        "agent.services.registration_draft_evidence_editor_service._persist_intake_image",
        return_value=str(cached_image),
    ):
        draft = RegistrationReviewDraft(
            review_draft_id="draft-evidence-002",
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
            },
        )
        RegistrationDraftStorageService.save_draft(draft)

        updated = patch_registration_draft_evidence(
            "draft-evidence-002",
            RegistrationReviewDraftEvidencePatchRequest(
                price=39.9,
                commission_amount=4.5,
                commission_rate="10%",
                image_base64="data:image/png;base64,cG5n",
                image_filename="bosmax.png",
                recompute=True,
            ),
        )

        assert updated is not None
        assert updated.draft_freshness_status == "FRESH"
        assert updated.image_asset_status == "IMAGE_CACHE_READY"
        assert updated.declared_evidence_fields["local_image_path"] == str(cached_image)
        assert "PRICE_EVIDENCE" not in updated.missing_required_evidence
