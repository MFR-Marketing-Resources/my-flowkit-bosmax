from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_fastmoss_reference_lane_is_visible_in_products_page_and_shared_selector():
    products_source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    select_source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")

    for token in [
        "FASTMOSS_REFERENCE",
        "FastMoss Reference",
        "catalog_visibility_reason",
        "Reference-only FastMoss lane",
        "Source Lane",
    ]:
        assert token in products_source

    for token in [
        "source_label",
        "source_lane",
        "Reference only",
    ]:
        assert token in select_source

    assert "REFERENCE_ONLY_PRODUCT" in operator_source
    assert "FastMoss reference products stay visible for review" in operator_source


def test_workspace_selector_contract_keeps_fastmoss_visible_without_gate_bypass():
    operator_source = _read("dashboard/src/pages/OperatorPage.tsx")
    select_source = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")

    assert "Only READY products" in operator_source
    assert "Package Eligibility" in operator_source
    assert "readiness?.detail" in select_source
    assert "readiness?.readiness_status" in select_source
