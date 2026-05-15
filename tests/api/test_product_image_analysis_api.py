from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.product_image_analysis import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_get_product_image_analysis_by_id(monkeypatch):
    async def fake_get(product_id: str):
        assert product_id == "prod-001"
        return {
            "product_id": product_id,
            "status": "VISION_PROVIDER_NOT_CONFIGURED",
            "provider": "not_configured",
            "detected_package": None,
            "detected_text": [],
            "visual_confidence": "NOT_VERIFIED",
            "warnings": ["SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"],
        }

    monkeypatch.setattr(
        "agent.api.product_image_analysis.get_product_image_analysis_by_id",
        fake_get,
    )
    client = TestClient(_build_app())

    response = client.get("/api/product-image-analysis/prod-001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "VISION_PROVIDER_NOT_CONFIGURED"
    assert payload["detected_text"] == []


def test_post_product_image_analysis_resolve(monkeypatch):
    async def fake_resolve(request):
        assert request.image_url == "https://example.com/product.jpg"
        return {
            "status": "VISION_PROVIDER_NOT_CONFIGURED",
            "provider": "not_configured",
            "detected_package": None,
            "detected_text": [],
            "visual_confidence": "NOT_VERIFIED",
            "warnings": ["SEMANTIC_IMAGE_ANALYSIS_NOT_AVAILABLE"],
        }

    monkeypatch.setattr(
        "agent.api.product_image_analysis.resolve_product_image_analysis_request",
        fake_resolve,
    )
    client = TestClient(_build_app())

    response = client.post(
        "/api/product-image-analysis/resolve",
        json={"image_url": "https://example.com/product.jpg"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "not_configured"
    assert payload["detected_package"] is None
