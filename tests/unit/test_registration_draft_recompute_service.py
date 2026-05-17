from agent.models.product_registration import RegistrationReviewDraft
from agent.services.registration_draft_recompute_service import recompute_review_draft


def test_recompute_refreshes_candidates_readiness_and_freshness():
    draft = RegistrationReviewDraft(
        review_draft_id="draft-bosmax-recompute",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="OWNED",
        declared_evidence_fields={
            "source_lane": "OWNED",
            "product_name": "Bosmax Herbs",
            "product_knowledge_text": "Minyak herba luaran untuk penjagaan diri lelaki.",
            "benefits_text": "Rutin luaran premium untuk self-care lelaki.",
            "usage_text": "Sapuan luaran secara konsisten.",
            "size_or_volume": "5 ML",
            "price": 39.9,
            "currency": "MYR",
            "commission_amount": 4.5,
            "commission_rate": "10%",
            "image_url": "https://example.com/bosmax.jpg",
            "hook_angles": ["Manual hook override"],
            "cta_angles": ["Manual CTA override"],
        },
        draft_freshness_status="STALE",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
    )

    refreshed = recompute_review_draft(draft)

    assert refreshed.draft_freshness_status == "FRESH"
    assert refreshed.last_recomputed_at is not None
    assert refreshed.image_asset_status == "IMAGE_REFERENCE_READY"
    assert refreshed.canonical_candidate_fields["hook_angles"] == ["Manual hook override"]
    assert refreshed.canonical_candidate_fields["cta_angles"] == ["Manual CTA override"]
    assert refreshed.system_inferred_fields["hook_angles_source"] == "MANUAL_OVERRIDE"
    assert refreshed.readiness_by_mode["IMG"].status == "READY"
    assert "PRICE_EVIDENCE" not in refreshed.missing_required_evidence
    assert refreshed.review_draft_id == "draft-bosmax-recompute"


def test_recompute_preserves_reference_lane_labels_for_manual_completion():
    draft = RegistrationReviewDraft(
        review_draft_id="draft-tiktok-recompute",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="TIKTOKSHOP_DRAFT",
        declared_evidence_fields={
            "source_lane": "TIKTOKSHOP_DRAFT",
            "product_name": "TikTok Draft Product",
            "product_url": "https://shop.tiktok.com/view/product/123",
            "tiktok_product_url": "https://shop.tiktok.com/view/product/123",
            "price": 19.9,
            "currency": "MYR",
        },
        draft_freshness_status="STALE",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
    )

    refreshed = recompute_review_draft(draft)

    assert refreshed.source_lane == "TIKTOKSHOP_DRAFT"
    assert refreshed.system_inferred_fields["extraction_status"] == "NOT_IMPLEMENTED"
