import pytest

from agent.models.product_registration import RegistrationReviewDraft
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services.registration_draft_recompute_service import recompute_review_draft


@pytest.fixture(autouse=True)
def _disable_live_text_assist(monkeypatch):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": False,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": False,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: pytest.fail("unexpected real text_assist call"),
    )


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


def test_recompute_preserves_manual_strategy_taxonomy_override():
    strategy_taxonomy = ProductStrategyTaxonomy(
        product_id="draft-taxonomy",
        taxonomy_version="product_strategy_taxonomy_v1",
        product_fingerprint="draft-fingerprint",
        cluster="beauty_makeup",
        product_type_group="lipstick_lip_tint",
        matched_scene_strategy_id="LIP_COLOR",
        scene_coverage_status="COVERED",
        fallback_used=False,
        specific_strategy=True,
        classification_confidence="HIGH",
        review_status="VERIFIED",
        consumer_status="BLOCKED_REVIEW_REQUIRED",
        authority_source="MANUAL_OVERRIDE",
        materialization_status="PREVIEW",
        review_reasons=[],
        reviewer_id="admin-1",
        reviewer_note="Reviewed registry binding.",
        is_stale=False,
    )
    draft = RegistrationReviewDraft(
        review_draft_id="draft-taxonomy",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="OWNED",
        declared_evidence_fields={
            "source_lane": "OWNED",
            "product_name": "Velvet Lipstick",
        },
        strategy_taxonomy=strategy_taxonomy,
        draft_freshness_status="STALE",
    )

    refreshed = recompute_review_draft(draft)

    assert refreshed.strategy_taxonomy == strategy_taxonomy


def test_recompute_exposes_deepseek_suggestions_as_review_only_candidates(
    monkeypatch,
):
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-pro",
            "execution_enabled": True,
        },
    )
    monkeypatch.setattr(
        "agent.services.product_knowledge_service.ai_copy_provider_adapter.complete_json",
        lambda *args, **kwargs: {
            "product_knowledge_summary": "Serbuk perasa untuk masakan harian.",
            "benefits": ["Melengkapkan rasa masakan"],
            "usage_summary": "Tabur secukup rasa ketika memasak.",
            "target_customer": "Pengguna yang memasak di rumah",
            "usp_list": ["Mudah digunakan"],
            "size_or_volume": None,
            "package_notes": "Pek serbuk.",
            "warnings_or_limitations": [],
            "confidence": "MEDIUM",
            "provenance": ["SOURCE_TEXT_REVIEW_ONLY"],
            "needs_review": True,
        },
    )
    draft = RegistrationReviewDraft(
        review_draft_id="draft-deepseek-recompute",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="OWNED",
        declared_evidence_fields={
            "source_lane": "OWNED",
            "product_name": "Serbuk Perasa Warisan",
            "paste_anything_about_product": (
                "Serbuk perasa untuk masakan harian. Tabur secukup rasa ketika memasak."
            ),
        },
        approval_checklist={"benefits": True},
    )

    refreshed = recompute_review_draft(draft)

    assert refreshed.review_status == "NEEDS_HUMAN_REVIEW"
    assert refreshed.canonical_candidate_fields["benefits"] == [
        "Melengkapkan rasa masakan"
    ]
    assert refreshed.evidence_field_status["benefits"].status == "AI_SUGGESTED"
    assert refreshed.evidence_field_status["benefits"].needs_review is True
    assert refreshed.approval_checklist["benefits"] is False
    assert "benefits" in refreshed.human_review_fields
    assert (
        "text_assist:deepseek:deepseek-v4-pro:review_only"
        in refreshed.provenance
    )
