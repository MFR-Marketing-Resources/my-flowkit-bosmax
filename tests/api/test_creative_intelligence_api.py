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


def test_registry_coverage_aggregates_and_computes_gaps(monkeypatch):
    """Read-only coverage lens: aggregates pools + config tables and computes
    covered vs missing clusters against the canonical list. Hermetic (no DB)."""
    from agent.services import avatar_fit_service

    beauty_cat = avatar_fit_service.normalise_category("Beauty")
    fashion_cat = avatar_fit_service.normalise_category("Fashion")

    async def fake_fits(limit=200):
        return [
            {"avatar_code": "BOS_F_ALYA_01", "product_category": beauty_cat},
            {"avatar_code": "BOS_F_ALYA_02", "product_category": fashion_cat},
            {"avatar_code": "BOS_F_ALYA_01", "product_category": fashion_cat},
        ]

    async def fake_prompts(limit=200):
        return [
            {"template_id": "t1", "cluster": "Beauty"},
            {"template_id": "t2", "cluster": "Fashion"},
        ]

    async def fake_presets(limit=200):
        return [{"preset_code": "HOOK_A", "block_group": "HOOK"}]

    async def fake_count():
        return 659

    monkeypatch.setattr("agent.db.crud.list_avatar_product_fits", fake_fits)
    monkeypatch.setattr("agent.db.crud.list_creative_scene_prompts", fake_prompts)
    monkeypatch.setattr("agent.db.crud.list_creative_camera_presets", fake_presets)
    monkeypatch.setattr("agent.db.crud.count_products", fake_count)
    monkeypatch.setattr(
        "agent.services.avatar_registry.list_pool",
        lambda: [{"avatar_code": f"A{i}"} for i in range(251)],
    )
    monkeypatch.setattr(
        "agent.services.scene_context_registry.list_pool",
        lambda: [{"scene_code": f"S{i}"} for i in range(20)],
    )

    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/registry-coverage")
    assert r.status_code == 200
    body = r.json()

    assert body["cluster_total"] == 12
    assert len(body["canonical_clusters"]) == 12
    assert body["product_total"] == 659

    assert body["avatar"]["pool_total"] == 251
    assert body["avatar"]["fit_total"] == 3
    assert body["avatar"]["distinct_avatars_in_fit"] == 2
    assert set(body["avatar"]["clusters_covered"]) == {"Beauty", "Fashion"}
    assert "Pet Care" in body["avatar"]["clusters_missing"]

    assert body["scene"]["pool_total"] == 20
    assert body["scene"]["prompt_total"] == 2
    assert set(body["scene"]["clusters_covered"]) == {"Beauty", "Fashion"}
    assert "Pet Care" in body["scene"]["clusters_missing"]
    assert "Office & Stationery" in body["scene"]["clusters_missing"]

    assert body["camera"]["preset_total"] == 1
    assert body["camera"]["block_groups"] == ["HOOK"]

    # Dependency notes surfaced so the registry pages can render "used by".
    assert any("R1" in note for note in body["used_by"]["avatar"])
    assert body["used_by"]["scene"]


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
