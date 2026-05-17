from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_approved_package_api_returns_package(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ACTIVE"}

    async def fake_package(product_id: str, mode: str):
        return {
            "product_id": product_id,
            "product_name": "Bosmax Herbs 5 ML",
            "mode": mode,
            "production_generation_allowed": True,
            "prompt_text": "Approved prompt",
            "prompt_fingerprint": "abc123",
            "blockers": [],
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: False)
    monkeypatch.setattr("agent.api.products.get_approved_product_package", fake_package)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-001/approved-package?mode=T2V")

    assert response.status_code == 200
    assert response.json()["prompt_fingerprint"] == "abc123"


def test_approved_package_api_blocks_archived_product(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": "ARCHIVED"}

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products.is_product_archived", lambda product: True)
    monkeypatch.setattr("agent.api.products.resolve_lifecycle_status", lambda product: "ARCHIVED")

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-001/approved-package?mode=T2V")

    assert response.status_code == 409
    assert response.json()["detail"]["blocker"] == "PRODUCT_ARCHIVED"
