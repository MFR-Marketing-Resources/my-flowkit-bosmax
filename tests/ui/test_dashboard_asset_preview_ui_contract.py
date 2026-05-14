from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_dashboard_routes_and_nav_include_asset_registry_and_prompt_preview():
    source = _read("dashboard/src/App.tsx")

    assert "/asset-registry" in source
    assert "/prompt-preview" in source
    assert "Asset Registry" in source
    assert "Prompt Preview" in source


def test_dashboard_api_helpers_only_call_approved_round_7_and_round_8_endpoints():
    asset_registry_api = _read("dashboard/src/api/assetRegistry.ts")
    prompt_preview_api = _read("dashboard/src/api/promptPreview.ts")
    products_api = _read("dashboard/src/api/products.ts")
    operator_api = _read("dashboard/src/api/operator.ts")

    assert "/api/asset-registry/catalog" in asset_registry_api
    assert "/api/asset-registry/assets?" in asset_registry_api
    assert "/api/asset-registry/assets/" in asset_registry_api
    assert "/api/asset-registry/resolve-selection" in asset_registry_api
    assert "/api/asset-registry/compatibility-check" in asset_registry_api
    assert "/api/prompt-preview/offline" in prompt_preview_api
    assert "/api/products?limit=" in products_api
    assert "/api/operator/content-pack" in operator_api


def test_dashboard_ui_contains_no_forbidden_execution_controls_or_runtime_imports():
    targets = [
      "dashboard/src/api/assetRegistry.ts",
    "dashboard/src/api/products.ts",
    "dashboard/src/api/operator.ts",
      "dashboard/src/api/promptPreview.ts",
      "dashboard/src/components/asset-registry/AssetSourceStatusBadge.tsx",
      "dashboard/src/components/asset-registry/AssetCatalogSummary.tsx",
      "dashboard/src/components/asset-registry/AssetOptionsTable.tsx",
      "dashboard/src/components/asset-registry/AssetDetailPanel.tsx",
      "dashboard/src/components/asset-registry/AssetSelectionResolverPanel.tsx",
      "dashboard/src/components/asset-registry/AssetCompatibilityPanel.tsx",
      "dashboard/src/components/prompt-preview/PromptPreviewForm.tsx",
      "dashboard/src/components/prompt-preview/PromptPreviewResultPanel.tsx",
      "dashboard/src/pages/AssetRegistryPage.tsx",
      "dashboard/src/pages/PromptPreviewPage.tsx",
      "dashboard/src/App.tsx",
    ]

    banned_tokens = [
      "Send to Flow",
      "Generate in Flow",
      "Extend Now",
      "Insert Now",
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


def test_prompt_preview_form_locks_dry_run_only_true_and_shows_offline_safety_copy():
    form_source = _read("dashboard/src/components/prompt-preview/PromptPreviewForm.tsx")
    result_source = _read("dashboard/src/components/prompt-preview/PromptPreviewResultPanel.tsx")
    page_source = _read("dashboard/src/pages/PromptPreviewPage.tsx")

    assert "dry_run_only: true" in form_source
    assert "dry_run_only=true" in form_source
    assert "offline-only" in form_source.lower()
    assert "VIDEO_9_SECTION_PROMPT" in form_source
    assert 'output_type: "VIDEO_9_SECTION_PROMPT"' in page_source
    assert "No repo-backed wardrobe registry exists in this checkout. Manual fallback remains required." in form_source
    assert "Operator-pack headwear suggestions are not canonical registry truth." in form_source
    assert "Selecting a product hydrates payload JSON" in form_source
    assert "!result.dry_run_only" not in result_source
    assert "value={result.dry_run_only}" in result_source
    assert "dry_run_only" in result_source
    assert "offline-only" in result_source.lower()
    assert "no Google Flow execution".lower() in page_source.lower()
    assert "no Chrome extension execution".lower() in page_source.lower()
    assert "batch execution".lower() in result_source.lower()


def test_asset_registry_ui_preserves_truth_labels_warnings_and_not_verified_states():
    registry_page = _read("dashboard/src/pages/AssetRegistryPage.tsx")
    detail_panel = _read("dashboard/src/components/asset-registry/AssetDetailPanel.tsx")
    compatibility_panel = _read("dashboard/src/components/asset-registry/AssetCompatibilityPanel.tsx")
    selection_panel = _read("dashboard/src/components/asset-registry/AssetSelectionResolverPanel.tsx")
    badge = _read("dashboard/src/components/asset-registry/AssetSourceStatusBadge.tsx")

    for token in [
        "REPO_VERIFIED",
        "INPUT_SLOT_ONLY",
        "EXTERNAL_OPERATOR_PACK_NOT_VERIFIED",
        "EMPTY_NOT_VERIFIED",
        "DERIVED_FROM_PRODUCT_DATA",
        "FULL_TUPLE_LEGALITY_NOT_PROVEN",
        "CANONICAL_VS_PREVIEW_ISOLATION_NOT_PROVEN",
    ]:
        assert token in "\n".join([registry_page, detail_panel, compatibility_panel, selection_panel, badge])
