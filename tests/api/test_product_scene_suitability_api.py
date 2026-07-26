"""Round 1 Product Scene Suitability Registry API contracts."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _result(**over):
    base = {
        "category": "Home & Living",
        "cluster": "Home & Living",
        "cluster_source": "EXACT",
        "review_required": False,
        "template_count": 1,
        "recommendations": [{
            "template_id": "SCN-HOME-01",
            "source_category": "Home & Living",
            "variant": "Variation 1",
            "main_action": "Displaying [PRODUCT]",
            "setting": "A home",
            "notes": "Preview only",
            "status": "READ_ONLY_PREVIEW",
            "full_prompt_template": "[AVATAR] holding [PRODUCT]",
            "suitability_reason": "Canonical cluster 'Home & Living' matches template.",
        }],
        "source": "PRODUCT_SCENE_SUITABILITY_R1",
    }
    base.update(over)
    return base


def test_scene_suitability_by_category(monkeypatch):
    captured = {}

    async def fake(category):
        captured["category"] = category
        return _result(category=category)

    monkeypatch.setattr(
        "agent.services.product_scene_suitability_service.recommend_scene_suitability_for_category",
        fake,
    )
    response = TestClient(_build_app()).get(
        "/api/creative-intelligence/scene-suitability/category",
        params={"category": "Home & Living"},
    )

    assert response.status_code == 200
    assert response.json()["recommendations"][0]["status"] == "READ_ONLY_PREVIEW"
    assert "[AVATAR]" in response.json()["recommendations"][0]["full_prompt_template"]
    assert captured == {"category": "Home & Living"}


def test_scene_suitability_by_product(monkeypatch):
    captured = {}

    async def fake(product_id):
        captured["product_id"] = product_id
        return _result(product_id=product_id, product_name="Desk Lamp")

    monkeypatch.setattr(
        "agent.services.product_scene_suitability_service.recommend_scene_suitability_for_product",
        fake,
    )
    response = TestClient(_build_app()).get(
        "/api/creative-intelligence/scene-suitability/product/p1"
    )

    assert response.status_code == 200
    assert response.json()["product_name"] == "Desk Lamp"
    assert captured == {"product_id": "p1"}


def test_scene_suitability_category_requires_category():
    response = TestClient(_build_app()).get("/api/creative-intelligence/scene-suitability/category")
    assert response.status_code == 422


def test_scene_suitability_product_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.product_scene_suitability_service.recommend_scene_suitability_for_product",
        fake,
    )
    response = TestClient(_build_app()).get(
        "/api/creative-intelligence/scene-suitability/product/missing"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PRODUCT_NOT_FOUND"
