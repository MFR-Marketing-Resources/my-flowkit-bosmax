"""Creative Intelligence Round 1 API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_avatar_recommendation_by_product(monkeypatch):
    captured = {}

    async def fake_by_product(product_id):
        captured["product_id"] = product_id
        return {"product_id": product_id, "category": "Beauty & Personal Care",
                "cluster": "Beauty", "cluster_source": "EXACT", "avatar_count": 3,
                "avatars": [{"avatar_code": "BOS_F_ALYA_08", "fit_source": "EXPLICIT_MAPPING"}]}

    monkeypatch.setattr(
        "agent.services.creative_avatar_recommendation_service.recommend_avatars_for_product",
        fake_by_product,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/avatar-recommendation", params={"product_id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["cluster"] == "Beauty"
    assert body["avatars"][0]["avatar_code"].startswith("BOS_")
    assert captured == {"product_id": "p1"}


def test_avatar_recommendation_by_category(monkeypatch):
    async def fake_by_category(category):
        return {"category": category, "cluster": "Automotive", "cluster_source": "EXACT",
                "avatar_count": 3, "avatars": []}

    monkeypatch.setattr(
        "agent.services.creative_avatar_recommendation_service.recommend_avatars_for_category",
        fake_by_category,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/avatar-recommendation", params={"category": "Automotive & Motorcycle"})
    assert r.status_code == 200
    assert r.json()["cluster"] == "Automotive"


def test_avatar_recommendation_requires_a_selector():
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/avatar-recommendation")
    assert r.status_code == 422


def test_avatar_recommendation_product_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.creative_avatar_recommendation_service.recommend_avatars_for_product", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/avatar-recommendation", params={"product_id": "nope"})
    assert r.status_code == 404


def test_seed_endpoint_dry_run_default(monkeypatch):
    captured = {}

    async def fake_seed(*, dry_run):
        captured["dry_run"] = dry_run
        return {"dry_run": dry_run, "clusters": 12, "mappings_valid": 60, "written": 0, "skipped_invalid": []}

    monkeypatch.setattr(
        "agent.services.creative_avatar_recommendation_service.seed_avatar_product_fit", fake_seed
    )
    client = TestClient(_build_app())
    # default = dry-run
    r = client.post("/api/creative-intelligence/avatar-fit/seed")
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert captured["dry_run"] is True
    # explicit write
    r2 = client.post("/api/creative-intelligence/avatar-fit/seed", params={"dry_run": "false"})
    assert r2.status_code == 200
    assert captured["dry_run"] is False
