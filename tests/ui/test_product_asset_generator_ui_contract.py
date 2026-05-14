from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_product_asset_generator_route_and_nav_exist():
    source = _read("dashboard/src/App.tsx")

    assert "/product-asset-generator" in source
    assert "Product Asset Generator" in source


def test_product_asset_generator_ui_calls_only_the_preview_endpoint():
    api_source = _read("dashboard/src/api/productAssetGenerator.ts")
    products_api = _read("dashboard/src/api/products.ts")
    operator_api = _read("dashboard/src/api/operator.ts")

    assert "/api/product-asset-generator/preview" in api_source
    assert "dry_run_only: true" in api_source
    assert "/api/products?limit=" in products_api
    assert "/api/operator/content-pack" in operator_api


def test_product_asset_generator_form_locks_dry_run_only_true_and_shows_truth_copy():
    form_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )
    page_source = _read("dashboard/src/pages/ProductAssetGeneratorPage.tsx")

    assert "dry_run_only: true" in form_source
    assert "dry_run_only=true" in form_source
    assert "Derived suggestions are not canonical truth." in form_source
    assert "No repo-backed wardrobe registry exists in this checkout. Manual fallback remains required." in form_source
    assert "Operator-pack headwear suggestions are not canonical registry truth." in form_source
    assert "Selecting a product hydrates payload JSON" in form_source
    assert "Advanced Manual Override" in form_source
    assert "Use this profile in Prompt Preview" in form_source
    assert "Profile Source Status" in form_source
    assert "Profile Truth Summary" in form_source
    assert "EPHEMERAL_PREVIEW" in form_source
    assert "PRODUCT_ROW_DERIVED" in form_source
    assert "NOT_PERSISTED" in form_source
    assert "Preview is offline-only" in page_source
    assert "No real image generation" in page_source
    assert "No Google Flow execution" in page_source
    assert "No Chrome extension execution" in page_source


def test_product_asset_generator_result_panel_displays_warnings_provenance_and_false_execution_flags():
    result_source = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx"
    )

    for token in [
        "warning_summary",
        "provenance",
        "truth_status",
        "copy_readiness_status",
        "persistence_truth",
        "execution_allowed",
        "image_generation_allowed",
        "flow_execution_allowed",
        "batch_execution_allowed",
        "dry_run_only",
    ]:
        assert token in result_source


def test_product_asset_generator_ui_contains_no_forbidden_execution_controls_or_runtime_imports():
    targets = [
        "dashboard/src/api/products.ts",
        "dashboard/src/api/operator.ts",
        "dashboard/src/api/productAssetGenerator.ts",
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx",
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorResultPanel.tsx",
        "dashboard/src/pages/ProductAssetGeneratorPage.tsx",
        "dashboard/src/App.tsx",
    ]

    banned_tokens = [
        "Generate Image Now",
        "Send to Flow",
        "Upload to Flow",
        "Generate in Flow",
        "Extend Now",
        "Insert Now",
        "Batch Execute",
        "Save as Canonical Registry",
        "chrome.runtime",
        "flow_client",
        "batch_executor",
        "simulateFileUpload",
        "execute_flow",
        "render_complete_detection",
    ]

    combined = "\n".join(_read(path) for path in targets)
    for token in banned_tokens:
        assert token not in combined
