from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_product_image_endpoint_returns_honest_error_for_remote_only_product(monkeypatch):
    async def fake_get_product(product_id: str):
        return {"id": product_id}

    async def fake_enrich(product):
        return {
            **product,
            "image_readiness_status": "IMAGE_READY",
            "image_readiness_detail": "Remote image URL is available.",
            "local_image_path": None,
            "image_url": "https://cdn.example.com/glad2glow.webp",
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products._enrich_product", fake_enrich)
    monkeypatch.setattr("agent.api.products.resolve_cached_image_path", lambda product: None)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-remote/image")

    assert response.status_code == 404
    payload = response.json()["detail"]
    assert payload["status"] == "IMAGE_READY"
    assert payload["local_cache_present"] is False
    assert payload["remote_image_url_present"] is True


def test_product_image_endpoint_returns_local_file(monkeypatch, tmp_path: Path):
    image_path = tmp_path / "local-preview.jpg"
    image_path.write_bytes(b"fake-jpg-bytes")

    async def fake_get_product(product_id: str):
        return {"id": product_id}

    async def fake_enrich(product):
        return {
            **product,
            "image_readiness_status": "IMAGE_CACHE_READY",
            "local_image_path": str(image_path),
            "image_url": "https://cdn.example.com/also-present.webp",
        }

    monkeypatch.setattr("agent.api.products.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.api.products._enrich_product", fake_enrich)
    monkeypatch.setattr("agent.api.products.resolve_cached_image_path", lambda product: image_path)

    client = TestClient(_build_app())
    response = client.get("/api/products/prod-local/image")

    assert response.status_code == 200
    assert response.content == b"fake-jpg-bytes"
