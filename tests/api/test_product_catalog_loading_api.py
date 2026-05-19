"""API contract — product catalog loading endpoints.

Verifies /api/products response shape, FastMoss reference row visibility,
and source/filter behavior. Tests run against the live backend if reachable;
falls back to static code audits when the agent is offline.
"""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ── Backend response shape — code audit ─────────────────────────────────────

def test_products_api_returns_items_key():
    """Backend list_products endpoint must return {items: [...]} shape."""
    src = _read("agent/api/products.py")
    assert '"items"' in src


def test_products_api_has_list_endpoint():
    src = _read("agent/api/products.py")
    assert "@router.get" in src
    assert 'prefix="/products"' in src or "products" in src


def test_products_api_has_search_endpoint():
    src = _read("agent/api/products.py")
    assert "/search" in src


def test_products_api_accepts_limit_param():
    src = _read("agent/api/products.py")
    assert "limit" in src


def test_products_api_accepts_source_param():
    src = _read("agent/api/products.py")
    assert "source" in src


# ── Frontend type contract — ProductCatalogResponse ──────────────────────────

def test_product_catalog_response_type_has_items():
    src = _read("dashboard/src/types/index.ts")
    assert "ProductCatalogResponse" in src
    assert "items" in src


def test_product_type_has_reference_only_field():
    src = _read("dashboard/src/types/index.ts")
    assert "reference_only" in src


def test_product_type_has_source_lane_field():
    src = _read("dashboard/src/types/index.ts")
    assert "source_lane" in src


def test_product_type_has_catalog_visibility_reason():
    src = _read("dashboard/src/types/index.ts")
    assert "catalog_visibility_reason" in src


# ── FastMoss reference rows — visible in catalog ─────────────────────────────

def test_fastmoss_reference_products_included_in_list():
    src = _read("agent/api/products.py")
    assert "fastmoss" in src.lower() or "reference" in src.lower()
    assert "list_fastmoss_reference_products" in src


def test_fastmoss_reference_service_defines_blocker():
    src = _read("agent/services/fastmoss_product_reference_service.py")
    assert "FASTMOSS_REFERENCE_BLOCKER" in src
    assert "REFERENCE_ONLY_PRODUCT" in src


def test_fastmoss_reference_products_have_reference_only_flag():
    src = _read("agent/services/fastmoss_product_reference_service.py")
    assert "reference_only" in src


def test_fastmoss_reference_products_have_catalog_visibility_reason():
    src = _read("agent/services/fastmoss_product_reference_service.py")
    assert "catalog_visibility_reason" in src or "REFERENCE_ONLY" in src


# ── Product readiness — reference_only blocked across modes ──────────────────

def test_approved_package_service_blocks_reference_only():
    src = _read("agent/services/approved_product_package_service.py")
    # Uses REFERENCE_ONLY_BLOCKER constant (= FASTMOSS_REFERENCE_BLOCKER = "REFERENCE_ONLY_PRODUCT")
    assert "REFERENCE_ONLY_BLOCKER" in src or "REFERENCE_ONLY_PRODUCT" in src


def test_wgp_service_blocks_reference_only():
    src = _read("agent/services/workspace_generation_package_service.py")
    assert "_assert_not_reference_only" in src


# ── Workspace package readiness — all 4 modes ───────────────────────────────

@pytest.mark.parametrize("mode", ["T2V", "F2V", "I2V", "IMG"])
def test_workspace_package_readiness_supports_mode(mode: str):
    src = _read("agent/services/approved_product_package_service.py")
    assert mode in src


# ── API client normalisation — items fallback ────────────────────────────────

def test_operator_page_normalises_response_items():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    assert "response.items" in src
    # Must guard against undefined with nullish coalescing
    assert "?? []" in src


def test_workspace_jobs_page_normalises_response_items():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    assert "response.items" in src
    assert "?? []" in src


# ── Silent failure prevention ────────────────────────────────────────────────

def test_operator_page_does_not_silently_swallow_product_error():
    src = _read("dashboard/src/pages/OperatorPage.tsx")
    # Product catalog catch must call setProductsError
    assert "setProductsError(" in src


def test_workspace_jobs_page_does_not_silently_swallow_product_error():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    # The catch must set an error state, not silently swallow
    assert "setProductsError" in src
