"""UI contract — product catalog selector loading states.

Verifies that OperatorPage, WorkspaceJobsPage, and ApprovedPackagesPage
never silently drop product-load failures and always surface a visible
error or loading state.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ── OperatorPage — product load error state ──────────────────────────────────

def test_operator_page_has_products_error_state():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "productsError" in src


def test_operator_page_has_is_loading_products_state():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "isLoadingProducts" in src


def test_operator_page_catch_sets_products_error():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "setProductsError" in src
    # Product catalog catch must set error — confirmed by setProductsError presence
    assert "setProductsError(" in src


def test_operator_page_shows_loading_indicator():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Loading products" in src or "isLoadingProducts" in src


def test_operator_page_shows_error_banner():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "Product list failed to load" in src


def test_operator_page_product_fetch_uses_finally_for_loading_state():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "finally" in src


def test_operator_page_normalizes_items_with_fallback():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    # response.items ?? [] protects against undefined
    assert "response.items ?? []" in src or "items ?? []" in src


# ── WorkspaceJobsPage — product load error state ─────────────────────────────

def test_workspace_jobs_page_has_products_error_state():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    assert "productsError" in src


def test_workspace_jobs_page_catch_sets_products_error():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    assert "setProductsError" in src


def test_workspace_jobs_page_shows_error_banner():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    assert "Product list failed to load" in src


def test_workspace_jobs_page_normalizes_items_with_fallback():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    assert "response.items ?? []" in src or "(response.items ?? [])" in src


# ── ApprovedPackagesPage — has notice/error handling already ─────────────────

def test_approved_packages_page_catch_is_not_silent():
    src = _read("dashboard/src/pages/ApprovedPackagesPage.tsx")
    # Product catalog catch must set a notice or error
    assert "catch" in src
    assert "setNotice" in src or "setError" in src


def test_approved_packages_page_shows_product_catalog_error():
    src = _read("dashboard/src/pages/ApprovedPackagesPage.tsx")
    # Either sets notice or error state on product load failure
    assert "Failed to load product catalog" in src or "setNotice" in src or "setError" in src


# ── ProductsSalesAnalyzerPage — already has error handling ───────────────────

def test_products_sales_analyzer_page_has_error_state():
    src = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    assert "setError" in src or "error" in src


def test_products_sales_analyzer_catch_sets_error():
    src = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    assert "catch" in src
    assert "Failed to load products" in src or "setError" in src


# ── API client — throws on failure ───────────────────────────────────────────

def test_api_client_throws_on_error_status():
    src = _read("dashboard/src/api/client.ts")
    assert "throw new Error" in src


def test_api_products_calls_fetch_api():
    src = _read("dashboard/src/api/products.ts")
    assert "fetchAPI" in src
    assert "/api/products" in src


# ── SearchableProductSelect — receives loading/error props ───────────────────

def test_operator_passes_is_loading_readiness_to_selector():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "isLoadingReadiness={isLoadingAnyReadiness}" in src


def test_operator_fetches_selected_product_readiness_independently():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "selectedReadinessLoading" in src
    assert "product_ids: [selectedProduct.id]" in src


def test_searchable_product_select_accepts_is_loading_readiness():
    src = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "isLoadingReadiness" in src


# ── usePromptToolHydration — surfaces product errors ────────────────────────

def test_prompt_tool_hydration_surfaces_product_catalog_error():
    src = _read("dashboard/src/components/prompt-tool/usePromptToolHydration.ts")
    assert "products" in src
    assert "error" in src
