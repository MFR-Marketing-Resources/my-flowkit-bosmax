"""Creative Intelligence Round 2 — scene / image prompt API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_scene_prompt_by_product(monkeypatch):
    captured = {}

    async def fake_by_product(product_id):
        captured["product_id"] = product_id
        return {
            "product_id": product_id, "category": "Home & Living",
            "cluster": "Home & Living", "cluster_source": "EXACT", "template_count": 1,
            "templates": [{"template_id": "SCN-0001", "cluster": "Home & Living",
                           "full_prompt_template": "[AVATAR], holding [PRODUCT]"}],
            "global_config": {"style_suffix": "photorealistic", "negative_prompt": "blurry"},
            "cluster_has_templates": True,
        }

    monkeypatch.setattr(
        "agent.services.creative_scene_prompt_service.recommend_scene_prompts_for_product",
        fake_by_product,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/scene-prompt-recommendation", params={"product_id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["cluster"] == "Home & Living"
    assert body["templates"][0]["template_id"] == "SCN-0001"
    # placeholders survive the API boundary unresolved
    assert "[AVATAR]" in body["templates"][0]["full_prompt_template"]
    assert "[PRODUCT]" in body["templates"][0]["full_prompt_template"]
    assert body["global_config"]["style_suffix"] == "photorealistic"
    assert captured == {"product_id": "p1"}


def test_scene_prompt_by_category(monkeypatch):
    async def fake_by_category(category):
        return {"category": category, "cluster": "Beauty", "cluster_source": "EXACT",
                "template_count": 0, "templates": [], "global_config": {},
                "cluster_has_templates": False}

    monkeypatch.setattr(
        "agent.services.creative_scene_prompt_service.recommend_scene_prompts_for_category",
        fake_by_category,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/scene-prompt-recommendation", params={"category": "Beauty & Personal Care"})
    assert r.status_code == 200
    assert r.json()["cluster"] == "Beauty"


def test_scene_prompt_requires_a_selector():
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/scene-prompt-recommendation")
    assert r.status_code == 422


def test_scene_prompt_product_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.creative_scene_prompt_service.recommend_scene_prompts_for_product", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/scene-prompt-recommendation", params={"product_id": "nope"})
    assert r.status_code == 404


def test_scene_prompt_seed_dry_run_default(monkeypatch):
    captured = {}

    async def fake_seed(*, dry_run):
        captured["dry_run"] = dry_run
        return {"dry_run": dry_run, "source": "CREATIVE_SCENE_PROMPT_v1",
                "templates_available": 154, "written": 0, "quarantine": []}

    monkeypatch.setattr(
        "agent.services.creative_scene_prompt_service.seed_scene_prompts", fake_seed
    )
    client = TestClient(_build_app())
    # default = dry-run
    r = client.post("/api/creative-intelligence/scene-prompt/seed")
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert captured["dry_run"] is True
    # explicit write
    r2 = client.post("/api/creative-intelligence/scene-prompt/seed", params={"dry_run": "false"})
    assert r2.status_code == 200
    assert captured["dry_run"] is False
