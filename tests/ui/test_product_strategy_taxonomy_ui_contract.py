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
    assert 'data-testid="product-strategy-taxonomy-editor"' in source
    assert 'data-testid="product-taxonomy-cluster-select"' in source
    assert 'data-testid="product-taxonomy-group-select"' in source
    assert "reviewProductStrategyTaxonomy" in source
    assert "registerProductStrategyType" in source
    assert "Manual assignment overrides scouting" in source


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
    assert 'data-testid="registration-strategy-taxonomy-editor"' in source
    assert 'data-testid="registration-taxonomy-cluster-select"' in source
    assert 'data-testid="registration-taxonomy-group-select"' in source
    assert "/api/product-registration/review-drafts" in source
    assert "registerProductStrategyType" in source


def test_registry_api_and_manual_override_contract_are_wired():
    api = _read("dashboard/src/api/products.ts")
    service = _read("agent/services/product_strategy_taxonomy_service.py")
    commit = _read("agent/services/registration_commit_service.py")

    assert "/api/creative-intelligence/product-strategy-type-registry" in api
    assert "/api/products/strategy-taxonomy/${encodeURIComponent(productId)}/review" in api
    assert "UNREGISTERED_PRODUCT_STRATEGY_TYPE" in service
    assert "PRODUCT_STRATEGY_TYPE_NOT_ACTIVE" in service
    assert "authority_source" in service
    assert '"MANUAL_OVERRIDE"' in commit
    assert "_materialize_manual_taxonomy" in commit
