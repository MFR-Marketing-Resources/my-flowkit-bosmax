from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_products_page_exposes_official_strategy_taxonomy_fields():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    for label in (
        "Strategy Cluster",
        "Strategy Product Type Group",
        "Matched Scene Strategy",
        "Scene Strategy Coverage",
        "Taxonomy Review Status",
        "Taxonomy Consumer Gate",
        "Taxonomy Authority",
        "Taxonomy Review Reasons",
    ):
        assert label in source
    assert "selectedProduct.strategy_taxonomy" in source


def test_smart_registration_exposes_preview_and_copy_gate():
    source = _read(
        "dashboard/src/components/product-registration/"
        "RegistrationReviewDraftPanel.tsx"
    )

    assert 'data-testid="registration-strategy-taxonomy"' in source
    assert "Product Strategy Taxonomy" in source
    assert "product_type_group" in source
    assert "matched_scene_strategy_id" in source
    assert "scene_coverage_status" in source
    assert "consumer_status" in source
    assert "Copy consumers remain" in source
