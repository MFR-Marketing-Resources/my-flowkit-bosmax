from pathlib import Path


def test_registration_review_draft_panel_exposes_completion_editor_contract():
    root = Path(__file__).parent.parent.parent
    content = (
        root
        / "dashboard/src/components/product-registration/RegistrationReviewDraftPanel.tsx"
    ).read_text(encoding="utf-8")

    assert "Complete Missing Evidence" in content
    assert "Save Draft Only" in content
    assert "Save & Recompute" in content
    assert "/api/product-registration/review-drafts/${draft.review_draft_id}/evidence" in content
    assert "Upload Product Image" in content
    assert "Hook Angles" in content
    assert "CTA Angles" in content
    assert "DRAFT_RECOMPUTE_REQUIRED" in content
    assert "image_asset_status" in content
    assert "image_analysis_status" in content
