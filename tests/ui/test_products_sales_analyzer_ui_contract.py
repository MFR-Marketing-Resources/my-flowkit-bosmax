from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_products_sales_analyzer_uses_wrap_safe_layout_and_kv_structure():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    for token in [
        "bosmax-kv-row",
        "bosmax-kv-label",
        "bosmax-kv-value",
        "bosmax-wrap-safe",
        "bosmax-pre-wrap-safe",
        "bosmax-auto-fit-grid",
        "2xl:grid-cols-[minmax(0,1fr)_300px]",
        "lg:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.45fr)]",
        "rounded-2xl border bg-slate-900/30 lg:min-h-0",
        "min-h-[280px] flex-1 overflow-y-auto p-2 lg:min-h-0",
        "2xl:sticky 2xl:top-6",
        "Shop Names",
        "Commission Amount",
        "Commission Rate",
        "Image Analysis Status",
        "Visual Confidence",
        "Semantic Analysis Provider",
        "Detected Package",
        "Detected Text",
        "Image Analysis Warnings",
        "Product Sold Verified",
        "Shop Total Sold",
        "Product Name A-Z",
        "Product sold: NOT_VERIFIED",
        "Shop total sold:",
        "SHOP_LEVEL_METRIC_NOT_PRODUCT_SALES",
        "Sales Metrics Source",
        "Sales Metrics Batch ID",
        "Sold Count Metric Scope",
        "Sold Count Truth Status",
        "Product Sold Count",
        "Shop Total Sold Count",
        "Sales Metric Warnings",
        "Sales Metric Provenance",
        "Lifecycle Status",
        "Archived At",
        "Archived Reason",
        "Active only",
        "Include archived",
        "Archived only",
        "Archive",
        "Unarchive",
        "Delete Test Row",
        "Archive Product",
        "Unarchive Product",
        "DELETE_TEST_ROW_ONLY",
        "ARCHIVE_PRODUCT",
        "UNARCHIVE_PRODUCT",
        "formatCountDisplay",
        "formatCommissionRateDisplay",
        "FastMoss Latest Import Refresh",
        "FastMoss affiliate data is latest reference only. No weekly/growth analytics.",
        "Creator Search",
        "Export Ad List",
        "Export Advertiser List",
        "Shop List",
        "Sales Rank",
        "New Products Ranking",
        "Product Search Data",
        "Product Search Sales Rank",
        "Most Promoted Products Rank",
        "Video Product List",
        "Upload Latest FastMoss Batch",
        "Latest Import Report",
        "Sales Metric Scope Summary",
        "Ready For Processing",
        "Raw File Storage Path",
        "Column Validation",
        "Filter products by lifecycle status",
        "ARCHIVED",
        "isDeleteTestEligible",
        "lifecycle_status",
    ]:
        assert token in source

    assert "grid h-full min-w-0 gap-4 overflow-hidden xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.45fr)]" not in source
    assert "Highest Sold" not in source
    assert "formatCountDisplay(product.sold_count)} sold" not in source


def test_products_sales_analyzer_does_not_truncate_long_product_and_shop_text():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    assert "truncate text-slate-200" not in source
    assert "truncate mt-0.5" not in source


def test_product_display_util_formats_currency_with_commas_and_two_decimals():
    source = _read("dashboard/src/utils/productDisplay.ts")

    assert "toLocaleString('en-MY'" in source
    assert "minimumFractionDigits: 2" in source
    assert "maximumFractionDigits: 2" in source
    assert "formatCountDisplay" in source


def test_products_sales_analyzer_detail_panel_is_not_plain_sticky_overlay_in_primary_layout():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    assert "sticky top-6" not in source
    assert "2xl:sticky 2xl:top-6" in source
    assert "flex flex-wrap gap-1 border-b border-slate-800 pb-px" in source
