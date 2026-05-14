from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_product_readiness_profile_primary_workflow_exists():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    assert "Product Readiness Profile" in form_source
    assert "Product Selector" in form_source
    assert "Analyze Product" in form_source
    assert "Readiness Status" in form_source
    assert "Profile Source Status" in form_source


def test_product_readiness_profile_cards_exist():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    assert "UGC_IPHONE" in form_source
    assert "CINEMATIC_PRO" in form_source
    assert "dialogue_style" in form_source
    assert "voiceover_style" in form_source
    assert "Video/Image Readiness" in form_source
    assert "recommended_first_mode" in form_source
    assert "Profile Truth Summary" in form_source
    assert "Copy Quality Status" in form_source
    assert "copy_quality_status" in form_source
    assert "Dialogue Opening" in form_source
    assert "Dialogue Body" in form_source
    assert "Dialogue CTA" in form_source
    assert "execution_readiness_status" in form_source
    assert "Product Scale Prompt" in form_source
    assert "Scale Truth Status" in form_source
    assert "Camera Capture Mode" in form_source
    assert "UGC iPhone Raw Camera Lock" in form_source
    assert "Cinematic Camera Prompt" in form_source


def test_advanced_manual_override_exists_and_old_manual_fields_are_not_primary():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    assert "Advanced Manual Override" in form_source
    assert "old manual fields are still" in form_source
    assert "primary top-level workflow" in form_source
    assert "Gender" in form_source
    assert "Ethnicity" in form_source
    assert "Age Range" in form_source
    assert "Product Payload JSON" in form_source


def test_product_readiness_profile_supports_prompt_preview_handoff():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )
    preview_page_source = _read("dashboard/src/pages/PromptPreviewPage.tsx")

    assert "Use this profile in Prompt Preview" in form_source
    assert 'navigate("/prompt-preview"' in form_source
    assert "productReadinessProfile" in form_source
    assert "product_scale_prompt" in form_source
    assert "ugc_camera_lock_prompt" in form_source
    assert "cinematic_camera_prompt" in form_source
    assert "productReadinessProfile" in preview_page_source


def test_product_readiness_profile_absents_internal_fallback_phrases_from_fixtures():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )

    for token in [
        "Review the prompt package for",
        "Use Atlas Bottle with",
        "Keep the demo grounded in",
        "Show the product clearly before any performance implication",
    ]:
        assert token not in form_source


def test_product_readiness_profile_contains_no_forbidden_execution_controls():
    targets = [
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx",
        "dashboard/src/pages/ProductAssetGeneratorPage.tsx",
        "dashboard/src/pages/PromptPreviewPage.tsx",
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
