"""Permanent source contracts for the product-data loading architecture.

These checks are intentionally small semantic guards. The dashboard is a TypeScript
application, but the loading invariants (shared helper, bounded windows, explicit
exceptions, and mutation invalidation) are stable source-level contracts that can
run offline before a browser or provider is available.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_SRC = ROOT / "dashboard" / "src"


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_active_selector_consumers_use_the_shared_bounded_hook():
    consumers = (
        "dashboard/src/pages/OperatorPage.tsx",
        "dashboard/src/pages/FacelessVideoPage.tsx",
        "dashboard/src/pages/MontagePage.tsx",
        "dashboard/src/pages/ApprovedPackagesPage.tsx",
        "dashboard/src/pages/AvatarRegistryPage.tsx",
        "dashboard/src/pages/CopySetRegistryPage.tsx",
        "dashboard/src/pages/PosterBuilderPage.tsx",
        "dashboard/src/components/prompt-tool/usePromptToolHydration.ts",
    )
    for relative_path in consumers:
        source = _read(relative_path)
        if relative_path.endswith("usePromptToolHydration.ts"):
            assert "fetchProductCatalog()" in source
        else:
            assert "useProductCatalog" in source
            assert re.search(r"useProductCatalog\(\s*50", source)


def test_catalog_url_construction_has_one_non_test_owner():
    offenders: list[str] = []
    for path in DASHBOARD_SRC.rglob("*.ts"):
        if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
            continue
        if path == DASHBOARD_SRC / "api" / "products.ts":
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "/api/products?" in line and not line.lstrip().startswith("//"):
                offenders.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert offenders == []


def test_product_helpers_enforce_cache_dedupe_ttl_and_failed_request_eviction():
    source = _read("dashboard/src/api/products.ts")
    assert "PRODUCT_CATALOG_CACHE_TTL_MS = 30_000" in source
    assert "PRODUCT_REGISTRY_CACHE_TTL_MS = 30_000" in source
    assert "productCatalogCacheKey" in source
    assert "if (cached?.promise) return cached.promise;" in source
    assert "if (productCatalogCache.get(key)?.promise === request)" in source
    assert "productCatalogCache.delete(key);" in source
    assert "query.set(\"view\", \"REGISTRY\")" in source
    assert "query.set(\"limit\", String(params.limit ?? 50))" in source
    assert "query.set(\"offset\", String(params.offset ?? 0))" in source
    assert "export async function fetchProductDetail" in source


def test_registry_and_all_products_consumers_are_server_paged_and_image_bounded():
    products_page = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    all_products = _read(
        "dashboard/src/components/product-registration/AllProductsTab.tsx"
    )

    assert "fetchProductRegistry(" in products_page
    assert "limit: PAGE_SIZE_PRODUCTS" in products_page
    assert "offset: (currentPageProducts - 1) * PAGE_SIZE_PRODUCTS" in products_page
    assert 'params.set("limit", "500")' not in products_page
    assert 'data-testid="product-intelligence-review-drafts-lazy"' in products_page

    assert "const PAGE_SIZE = 50" in all_products
    assert "fetchProductRegistry(" in all_products
    assert "limit: PAGE_SIZE" in all_products
    assert "offset" in all_products
    assert "IntersectionObserver" in all_products
    assert 'rootMargin: "160px 0px"' in all_products
    assert 'loading="lazy"' in all_products


def test_product_catalog_mutations_invalidate_registry_pages_but_reads_do_not():
    source = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    load_start = source.index("const loadProducts")
    mutation_start = source.index("const reloadProductsAfterMutation", load_start)
    load_body = source[load_start:mutation_start]
    mutation_body = source[mutation_start:]

    assert "invalidateProductCatalogCache();" not in load_body
    assert "invalidateProductCatalogCache();" in mutation_body
    assert mutation_body.count("await reloadProductsAfterMutation();") >= 8
    assert "fetchProductDetail(productId, controller.signal)" in load_body


def test_smart_registration_defaults_to_bounded_all_products_and_defers_legacy_drafts():
    source = _read("dashboard/src/pages/ProductRegistrationPage.tsx")
    assert 'if (tab === "single") return "single"' in source
    assert 'return "all"' in source
    assert 'if (activeTab !== "single") return;' in source
    assert '"/api/product-registration/review-drafts"' in source
    assert "const PAGE_SIZE_DRAFTS = 10" in source


def test_exact_detail_and_p6_authority_use_bounded_contracts():
    detail_page = _read("dashboard/src/pages/ProductDetailPage.tsx")
    sales_page = _read("dashboard/src/pages/ProductsSalesAnalyzerPage.tsx")
    p6_api = _read("agent/api/creative_production.py")
    p6_service = _read("agent/services/creative_production_plan_service.py")
    p6_page = _read("dashboard/src/pages/CreativeProductionStudioPage.tsx")
    p6_picker = _read(
        "dashboard/src/components/production-studio/ProductAllocationPicker.tsx"
    )

    assert "fetchProductDetail(id)" in detail_page
    assert "fetchProductDetail(productId, controller.signal)" in sales_page
    assert "limit: int = Query(default=50, ge=1, le=100)" in p6_api
    assert "offset: int = Query(default=0, ge=0)" in p6_api
    assert "query=q" in p6_api
    assert "page_rows = ready_rows[page_offset : page_offset + limit]" in p6_service
    assert "P6_COHORT_PAGE_SIZE = 50" in p6_page
    assert "onSearchChange={handleCohortSearchChange}" in p6_page
    assert "onPageChange={handleCohortPageChange}" in p6_page
    assert 'data-testid="p6-product-pagination"' in p6_picker
    assert 'loading="lazy"' in p6_picker


def test_backend_registry_path_is_projection_first_and_provider_free():
    source = _read("agent/api/products.py")
    assert "def _build_catalog_projection(" in source
    assert "registry_projection =" in source
    assert "if registry_projection:" in source
    assert "page_products = filtered_all[offset:offset + limit]" in source
    assert "Full enrichment" in source
    # The full enricher is structurally below the registry branch, not used by it.
    registry_comment = source.index("# Registry consumers only need the bounded read model.")
    full_enricher = source.index("_enrich_product_cached(refreshed_product)")
    assert registry_comment < full_enricher


def test_reporting_and_legacy_exceptions_are_explicit_and_allowlisted():
    workspace_jobs = _read("dashboard/src/pages/WorkspaceJobsPage.tsx")
    contract = _read("docs/architecture/PRODUCT_DATA_LOADING_CONTRACT.md")
    deactivated = _read("dashboard/src/deactivatedSurfaces.ts")

    assert workspace_jobs.count("fetchProductCatalog(500)") == 1
    assert "WorkspaceJobsPage" in contract
    assert "legacy single-registration workflow" in contract
    assert '"/assets/img-cockpit": "/creative/poster-builder"' in deactivated
    assert '"/assets/scene-context-registry": "/assets/creative-library"' in deactivated
