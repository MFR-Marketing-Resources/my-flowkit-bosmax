"""Creative Intelligence Round 4 — unified setup + selection API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_creative_setup_by_product(monkeypatch):
    captured = {}

    async def fake_resolve(product_id):
        captured["product_id"] = product_id
        return {"product_id": product_id, "cluster": "Beauty", "cluster_source": "EXACT",
                "recommended_avatars": [{"avatar_code": "BOS_F_ALYA_08"}],
                "recommended_scene_templates": [{"template_id": "SCN-0015"}],
                "camera_block_recommendations": [{"block_purpose": "Hook Block"}],
                "camera_library": {"named_presets": [{"preset_code": "HOOK_A"}]},
                "saved_selection": None}

    monkeypatch.setattr("agent.services.creative_setup_service.resolve_creative_setup", fake_resolve)
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-setup", params={"product_id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["cluster"] == "Beauty"
    assert body["recommended_avatars"][0]["avatar_code"] == "BOS_F_ALYA_08"
    assert captured == {"product_id": "p1"}


def test_creative_setup_requires_product_id():
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-setup")
    assert r.status_code == 422


def test_creative_setup_product_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr("agent.services.creative_setup_service.resolve_creative_setup", fake)
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-setup", params={"product_id": "nope"})
    assert r.status_code == 404


def test_save_selection(monkeypatch):
    captured = {}

    async def fake_save(product_id, **kw):
        captured["product_id"] = product_id
        captured.update(kw)
        return {"product_id": product_id, "selection_id": "sel-1", "status": "DRAFT",
                "selected_avatar_code": kw.get("selected_avatar_code")}

    monkeypatch.setattr("agent.services.creative_setup_service.save_creative_selection", fake_save)
    client = TestClient(_build_app())
    r = client.post("/api/creative-intelligence/creative-selection", json={
        "product_id": "p1", "selected_avatar_code": "BOS_F_ALYA_08",
        "selected_scene_template_id": "SCN-0015", "selected_camera_preset_code": "HOOK_A",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "DRAFT"
    assert captured["product_id"] == "p1"
    assert captured["selected_avatar_code"] == "BOS_F_ALYA_08"


def test_save_selection_invalid_id_returns_422(monkeypatch):
    async def fake_save(product_id, **kw):
        raise ValueError("INVALID_AVATAR_CODE")

    monkeypatch.setattr("agent.services.creative_setup_service.save_creative_selection", fake_save)
    client = TestClient(_build_app())
    r = client.post("/api/creative-intelligence/creative-selection",
                    json={"product_id": "p1", "selected_avatar_code": "NOPE"})
    assert r.status_code == 422


def test_save_selection_product_not_found_returns_404(monkeypatch):
    async def fake_save(product_id, **kw):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr("agent.services.creative_setup_service.save_creative_selection", fake_save)
    client = TestClient(_build_app())
    r = client.post("/api/creative-intelligence/creative-selection", json={"product_id": "nope"})
    assert r.status_code == 404


def test_get_saved_selection(monkeypatch):
    async def fake_get(product_id):
        return {"product_id": product_id, "selection_id": "sel-1", "status": "DRAFT"}

    monkeypatch.setattr("agent.services.creative_setup_service.get_creative_selection", fake_get)
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-selection", params={"product_id": "p1"})
    assert r.status_code == 200
    assert r.json()["selection"]["status"] == "DRAFT"


def test_review_selection_transitions_and_guards(monkeypatch):
    async def fake_review(product_id, action, reviewer_note=None):
        if action == "APPROVE":
            return {"product_id": product_id, "status": "APPROVED"}
        raise ValueError("NOT_IN_DRAFT")

    monkeypatch.setattr("agent.services.creative_setup_service.review_creative_selection", fake_review)
    client = TestClient(_build_app())
    ok = client.post("/api/creative-intelligence/creative-selection/review",
                     json={"product_id": "p1", "action": "APPROVE"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "APPROVED"
    conflict = client.post("/api/creative-intelligence/creative-selection/review",
                           json={"product_id": "p1", "action": "REJECT"})
    assert conflict.status_code == 409
