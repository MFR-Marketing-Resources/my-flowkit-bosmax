from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_global_wrap_safe_utilities_exist():
    source = _read("dashboard/src/index.css")

    for token in [
        ".bosmax-wrap-safe",
        ".bosmax-pre-wrap-safe",
        ".bosmax-json-block",
        ".bosmax-warning-list",
        ".bosmax-provenance-list",
        ".bosmax-kv-row",
        "overflow-wrap: anywhere",
        "word-break: break-word",
        "grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));",
    ]:
        assert token in source


def test_app_shell_and_pages_propagate_min_width_safety():
    app_source = _read("dashboard/src/App.tsx")
    product_page = _read("dashboard/src/pages/ProductAssetGeneratorPage.tsx")
    preview_page = _read("dashboard/src/pages/PromptPreviewPage.tsx")
    asset_page = _read("dashboard/src/pages/AssetRegistryPage.tsx")
    products_page = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    assert "min-w-0 flex-1 overflow-auto" in app_source
    assert "grid gap-6 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]" in product_page
    assert "flex min-w-0 flex-col gap-6 p-4 md:p-6" in preview_page
    assert "grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]" in preview_page
    assert "flex min-w-0 flex-col gap-6 p-4 md:p-6" in asset_page
    assert "grid min-w-0 gap-6 2xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.95fr)]" in asset_page
    assert "grid min-h-full min-w-0 gap-4 p-4 md:p-6" in products_page
    assert "lg:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.45fr)]" in products_page
