from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_truth_status_ui_uses_profile_source_status_instead_of_saved_persistence_claim():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    assert "Profile Source Status" in form_source
    assert "Persistence Status" not in form_source
    for token in [
        "NOT_ANALYZED",
        "PRODUCT_ROW_DERIVED",
        "EPHEMERAL_PREVIEW",
        "PERSISTED_PROFILE",
    ]:
        assert token in form_source


def test_truth_summary_and_copy_readiness_labels_exist():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    assert "Profile Truth Summary" in form_source
    assert "profile_source_status" in form_source
    assert "copy_quality_status" in form_source
    assert "COMMERCIAL_COPY_READY" in form_source
    assert "FALLBACK_COPY_DRAFT" in form_source
    assert "REVIEW_REQUIRED" in form_source
    assert "COPY_MISSING" in form_source
    assert "execution_readiness_status" in form_source
    assert "DRY_RUN_ONLY" in form_source
    assert "NOT_PERSISTED" in form_source
    assert "CHARACTER_CONCEPT_ONLY" in form_source
    assert "NOT_PROVIDED" in form_source
    assert "scale_truth_status" in form_source
    assert "camera_truth_status" in form_source
    assert "text_to_video_readiness_status" in form_source
    assert "image_prompt_readiness_status" in form_source


def test_null_character_attributes_are_not_marked_derived_from_product_data():
    service_source = _read("agent/services/product_asset_generator_service.py")

    assert '"gender": _build_character_attribute_truth(request.gender)' in service_source
    assert '"ethnicity": _build_character_attribute_truth(request.ethnicity)' in service_source
    assert '"age_range": _build_character_attribute_truth(request.age_range)' in service_source
    assert "return \"INPUT_SLOT_ONLY\" if value else \"NOT_PROVIDED\"" in service_source


def test_result_panel_truth_copy_stays_preview_only_and_not_persisted():
    result_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx"
    )

    assert "not a persisted readiness profile" in result_source
    assert "Preview-only readiness profile. No persistence write happened." in result_source
    assert "Copy Quality Status" in result_source
    assert "COPY_MISSING" in result_source
    assert "Not Chrome extension execution." in result_source
    assert "Not Google" in result_source
    assert "Flow ready." in result_source
    assert "Product Scale Prompt" in result_source
    assert "UGC iPhone Raw Camera Lock" in result_source
    assert "Cinematic Camera Prompt" in result_source
    assert "Dialogue Opening" in result_source
    assert "Dialogue Body" in result_source
    assert "Dialogue CTA" in result_source


def test_truth_status_ui_contains_no_forbidden_execution_controls():
    targets = [
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx",
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx",
        "dashboard/src/pages/ProductAssetGeneratorPage.tsx",
    ]
    banned_tokens = [
        "Generate in Flow",
        "Send to Flow",
        "Upload to Flow",
        "Extend Now",
        "Insert Now",
        "Batch Execute",
    ]
    combined = "\n".join(_read(path) for path in targets)
    for token in banned_tokens:
        assert token not in combined
