from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router as products_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    return app


def _reference_product() -> dict:
    return {
        "id": "fastmoss-ref:sample-001",
        "source": "FASTMOSS",
        "source_lane": "FASTMOSS_REFERENCE",
        "source_label": "FastMoss Reference",
        "reference_only": True,
        "catalog_blockers": ["REFERENCE_ONLY_PRODUCT"],
        "catalog_visibility_reason": "FastMoss latest reference is visible for review only.",
        "raw_product_title": "FastMoss Reference Serum",
        "product_display_name": "FastMoss Reference Serum",
        "product_short_name": "Reference Serum",
        "category": "Beauty",
        "subcategory": "Serum",
        "type": "Demo",
        "lifecycle_status": "ACTIVE",
        "prompt_readiness_status": "REFERENCE_ONLY",
        "image_readiness_status": "IMAGE_READY",
        "image_url": "https://example.com/serum.jpg",
        "source_url": "https://fastmoss.example/product/serum",
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
    }


def test_fastmoss_reference_products_appear_in_default_catalog(monkeypatch):
    async def fake_list_products(**kwargs):
        return []

    async def fake_list_fastmoss_reference_products(limit=500):
        return [_reference_product()]

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products.list_fastmoss_reference_products", fake_list_fastmoss_reference_products)

    client = TestClient(_build_app())
    response = client.get("/api/products?limit=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_count"] == 1
    assert payload["items"][0]["source"] == "FASTMOSS"
    assert payload["items"][0]["source_lane"] == "FASTMOSS_REFERENCE"
    assert payload["items"][0]["reference_only"] is True


def test_fastmoss_reference_products_appear_in_search_with_lane_filter(monkeypatch):
    async def fake_list_products(**kwargs):
        return []

    async def fake_list_fastmoss_reference_products(limit=500):
        return [_reference_product()]

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products.list_fastmoss_reference_products", fake_list_fastmoss_reference_products)

    client = TestClient(_build_app())
    response = client.get("/api/products/search?q=serum&source_lane=FASTMOSS_REFERENCE")

    assert response.status_code == 200
    payload = response.json()
    assert payload["returned_count"] == 1
    assert payload["items"][0]["raw_product_title"] == "FastMoss Reference Serum"


def test_archived_fastmoss_products_remain_filtered_by_lifecycle(monkeypatch):
    archived_product = {
        "id": "prod-archived",
        "source": "FASTMOSS",
        "raw_product_title": "Archived FastMoss Serum",
        "product_display_name": "Archived FastMoss Serum",
        "product_short_name": "Archived Serum",
        "category": "Beauty",
        "subcategory": "Serum",
        "type": "Demo",
        "lifecycle_status": "ARCHIVED",
        "prompt_readiness_status": "READY",
        "image_readiness_status": "IMAGE_READY",
        "created_at": "2026-05-19T00:00:00Z",
        "updated_at": "2026-05-19T00:00:00Z",
    }

    async def fake_list_products(**kwargs):
        return [archived_product]

    async def fake_enrich_product(product, **kwargs):
        return dict(product)

    async def fake_list_fastmoss_reference_products(limit=500):
        return []

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products._enrich_product", fake_enrich_product)
    monkeypatch.setattr("agent.api.products.list_fastmoss_reference_products", fake_list_fastmoss_reference_products)

    client = TestClient(_build_app())
    hidden = client.get("/api/products?source=FASTMOSS")
    visible = client.get("/api/products?source=FASTMOSS&include_archived=true")

    assert hidden.status_code == 200
    assert hidden.json()["total_count"] == 0
    assert visible.status_code == 200
    assert visible.json()["total_count"] == 1


def test_reference_only_fastmoss_product_returns_explicit_package_blocker(monkeypatch):
    async def fake_get_product(product_id):
        return None

    async def fake_get_reference_product(product_id):
        return _reference_product() if product_id == "fastmoss-ref:sample-001" else None

    monkeypatch.setattr("agent.services.approved_product_package_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.approved_product_package_service.get_fastmoss_reference_product", fake_get_reference_product)

    client = TestClient(_build_app())
    response = client.get("/api/products/fastmoss-ref:sample-001/approved-package?mode=F2V")

    assert response.status_code == 409
    assert response.json()["detail"] == "REFERENCE_ONLY_PRODUCT"
