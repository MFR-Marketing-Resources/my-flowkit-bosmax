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
        "xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.45fr)]",
        "Shop Names",
    ]:
        assert token in source


def test_products_sales_analyzer_does_not_truncate_long_product_and_shop_text():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    assert "truncate text-slate-200" not in source
    assert "truncate mt-0.5" not in source
