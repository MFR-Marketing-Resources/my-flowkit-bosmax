"""Creative Intelligence Round 3 — camera / video preset API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _fake_result(**over):
    base = {
        "cluster": "Home & Living", "cluster_source": "EXACT",
        "block_groups": ["HOOK", "BODY", "CTA", "TRANS"],
        "block_recommendation_count": 1,
        "block_recommendations": [{
            "block_purpose": "Hook Block", "content_type": "Pain Point Question",
            "recommended_preset": {"preset_code": "HOOK_A", "shot_type": "PAIN",
                                   "distance_angle": "MCU + EYE", "movement": "STATIC"},
            "alt_presets": [{"preset_code": "HOOK_C"}],
        }],
        "library": {"shot_distances": [], "camera_angles": [], "camera_movements": [],
                    "ecomm_shot_types": [], "named_presets": []},
        "filtered_by": {"block": None, "content_type": None},
        "has_recommendations": True,
    }
    base.update(over)
    return base


def test_camera_by_product(monkeypatch):
    captured = {}

    async def fake_by_product(product_id, block=None, content_type=None):
        captured["product_id"] = product_id
        return _fake_result(product_id=product_id)

    monkeypatch.setattr(
        "agent.services.creative_camera_preset_service.recommend_camera_presets_for_product",
        fake_by_product,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/camera-preset-recommendation", params={"product_id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["cluster"] == "Home & Living"
    rec = body["block_recommendations"][0]
    assert rec["recommended_preset"]["preset_code"] == "HOOK_A"
    assert rec["recommended_preset"]["shot_type"] == "PAIN"
    assert rec["recommended_preset"]["distance_angle"] == "MCU + EYE"
    assert rec["recommended_preset"]["movement"] == "STATIC"
    assert captured == {"product_id": "p1"}


def test_camera_by_category(monkeypatch):
    async def fake_by_category(category, block=None, content_type=None):
        return _fake_result(category=category)

    monkeypatch.setattr(
        "agent.services.creative_camera_preset_service.recommend_camera_presets_for_category",
        fake_by_category,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/camera-preset-recommendation", params={"category": "Beauty"})
    assert r.status_code == 200
    assert r.json()["cluster"] == "Home & Living"


def test_camera_by_cluster(monkeypatch):
    async def fake_by_cluster(cluster, block=None, content_type=None):
        return _fake_result(cluster=cluster, cluster_source="EXPLICIT_CLUSTER")

    monkeypatch.setattr(
        "agent.services.creative_camera_preset_service.recommend_camera_presets_for_cluster",
        fake_by_cluster,
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/camera-preset-recommendation", params={"cluster": "Beauty"})
    assert r.status_code == 200
    assert r.json()["cluster_source"] == "EXPLICIT_CLUSTER"


def test_camera_requires_a_selector():
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/camera-preset-recommendation")
    assert r.status_code == 422


def test_camera_product_not_found(monkeypatch):
    async def fake(product_id, block=None, content_type=None):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.creative_camera_preset_service.recommend_camera_presets_for_product", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/camera-preset-recommendation", params={"product_id": "nope"})
    assert r.status_code == 404


def test_camera_seed_dry_run_default(monkeypatch):
    captured = {}

    async def fake_seed(*, dry_run):
        captured["dry_run"] = dry_run
        return {"dry_run": dry_run, "source": "CREATIVE_CAMERA_PRESET_v1",
                "presets_available": 17, "written": 0, "quarantine": []}

    monkeypatch.setattr(
        "agent.services.creative_camera_preset_service.seed_camera_presets", fake_seed
    )
    client = TestClient(_build_app())
    r = client.post("/api/creative-intelligence/camera-preset/seed")
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert captured["dry_run"] is True
    r2 = client.post("/api/creative-intelligence/camera-preset/seed", params={"dry_run": "false"})
    assert r2.status_code == 200
    assert captured["dry_run"] is False
