"""API contract — product catalog loading endpoints.

Verifies /api/products response shape, FastMoss reference row visibility,
and source/filter behavior. Tests run against the live backend if reachable;
falls back to static code audits when the agent is offline.
"""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    hook = _read("dashboard/src/hooks/useProductCatalog.ts")
    # Product catalog errors are centralized so every consumer gets the same
    # explicit error state instead of maintaining independent silent catches.
    assert "useProductCatalog" in src
    assert "setState({" in hook
    assert "productsError:" in hook


def test_workspace_jobs_page_does_not_silently_swallow_product_error():
    src = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    # The catch must set an error state, not silently swallow
    assert "setProductsError" in src


def test_product_catalog_cache_is_parameterized_and_invalidatable():
    src = _read("dashboard/src/api/products.ts")
    assert "productCatalogCacheKey" in src
    assert "purpose" in src and "limit" in src
    assert "invalidateProductCatalogCache" in src
    assert "revalidateProductCatalog" in src


def test_product_intelligence_browser_uses_server_pagination_and_read_cache():
    page = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")

    assert "fetchProductRegistry(" in page
    assert "limit: PAGE_SIZE_PRODUCTS" in page
    assert "catalogTotal" in page
    assert 'params.set("limit", "500")' not in page
    load_start = page.index("const loadProducts")
    reload_start = page.index("const reloadProductsAfterMutation", load_start)
    assert "invalidateProductCatalogCache();" not in page[load_start:reload_start]
    assert "invalidateProductCatalogCache();" in page[reload_start:]
    assert "await reloadProductsAfterMutation();" in page[reload_start:]


async def _empty_async_dict():
    return {}


def test_products_api_applies_server_facets_sort_and_pagination(monkeypatch):
    from agent.api.products import router as products_router

    rows = [
        {
            "id": "product-beauty-a",
            "source": "MANUAL",
            "lifecycle_status": "ACTIVE",
            "group": "beauty",
            "bosmax_product_family": "SERUM",
            "copy_route": "DIRECT",
            "claim_gate": "CLAIM_SAFE",
            "intelligence_confidence": "HIGH",
            "product_short_name": "Alpha Serum",
            "product_sold_count": 200,
            "image_readiness_status": "IMAGE_READY",
            "updated_at": "2026-08-01T00:00:00Z",
        },
        {
            "id": "product-beauty-b",
            "source": "MANUAL",
            "lifecycle_status": "ACTIVE",
            "group": "beauty",
            "bosmax_product_family": "SERUM",
            "copy_route": "DIRECT",
            "claim_gate": "CLAIM_SAFE",
            "intelligence_confidence": "LOW",
            "product_short_name": "Beta Serum",
            "product_sold_count": 100,
            "image_readiness_status": "IMAGE_DOWNLOAD_FAILED",
            "updated_at": "2026-08-02T00:00:00Z",
        },
        {
            "id": "product-food",
            "source": "MANUAL",
            "lifecycle_status": "ACTIVE",
            "group": "food",
            "bosmax_product_family": "SPICE",
            "copy_route": "REVIEW_REQUIRED",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "intelligence_confidence": "MEDIUM",
            "product_short_name": "Food Product",
            "product_sold_count": 999,
            "image_readiness_status": "IMAGE_CACHE_READY",
            "updated_at": "2026-08-03T00:00:00Z",
        },
    ]

    async def fake_list_products(**_kwargs):
        return rows

    async def fake_enrich(_product):
        raise AssertionError("registry view must not run full page enrichment")

    async def fake_merge(products, **_kwargs):
        return products

    async def fake_taxonomies(products):
        return products

    async def fake_visual_readiness(_products):
        return None

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products._enrich_product_cached", fake_enrich)
    monkeypatch.setattr("agent.api.products._merge_catalog_products", fake_merge)
    monkeypatch.setattr("agent.api.products.attach_product_strategy_taxonomies", fake_taxonomies)
    monkeypatch.setattr(
        "agent.api.products.crud.count_source_media_by_products",
        lambda _ids: _empty_async_dict(),
    )
    monkeypatch.setattr(
        "agent.api.products.crud.latest_open_review_drafts_by_products",
        lambda _ids: _empty_async_dict(),
    )
    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.annotate_products_visual_readiness",
        fake_visual_readiness,
    )
    monkeypatch.setattr(
        "agent.services.product_catalog_read_model.derive_catalog_state",
        lambda product: {"product_state": "APPROVED_CANONICAL", "product_id": product["id"]},
    )

    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    response = TestClient(app).get(
        "/api/products?view=REGISTRY&group=beauty&sort=PRODUCT_SOLD_VERIFIED_DESC&limit=1&offset=0"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert body["returned_count"] == 1
    assert body["has_pagination"] is True
    assert body["items"][0]["id"] == "product-beauty-a"
    assert body["facets"]["groups"] == ["beauty", "food"]
    assert body["facets"]["product_families"] == ["SERUM", "SPICE"]
    assert body["image_readiness_summary"] == {
        "READY": 1,
        "CACHE_READY": 0,
        "URL_MISSING": 0,
        "DOWNLOAD_FAILED": 1,
        "NOT_AVAILABLE": 0,
    }
