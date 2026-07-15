"""Creative Intelligence Round 5 — gated generation handoff API contract tests."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _payload(**over):
    base = {
        "product_id": "p1", "product_name": "Rug", "selection_id": "sel-1",
        "selection_status": "APPROVED", "cluster": "Home & Living", "cluster_source": "EXACT",
        "avatar": {"avatar_code": "BOS_F_FARAH_02", "character_name": "Farah",
                   "resolved_descriptor": "The presenter is a Malaysian adult woman..."},
        "scene_template": {"template_id": "SCN-0001", "variant": "V1",
                           "raw_prompt_template": "[AVATAR] holds [PRODUCT]"},
        "camera_preset": {"preset_code": "HOOK_A", "shot_type": "PAIN"},
        "resolved_prompt_preview": "The presenter is a Malaysian adult woman... holds Rug",
        "placeholders_resolved": {"[AVATAR]": True, "[PRODUCT]": True},
        "provenance": {"source": "CREATIVE_HANDOFF_v1"},
        "auto_generated": False, "requires_confirmation": True,
        "handoff_status": "PREVIEW_ONLY_REQUIRES_CONFIRMATION", "note": "preview only",
    }
    base.update(over)
    return base


def test_handoff_by_product(monkeypatch):
    captured = {}

    async def fake(product_id):
        captured["product_id"] = product_id
        return _payload(product_id=product_id)

    monkeypatch.setattr(
        "agent.services.creative_handoff_service.prepare_generation_handoff", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff", params={"product_id": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert body["selection_status"] == "APPROVED"
    assert body["auto_generated"] is False
    assert body["requires_confirmation"] is True
    assert "[AVATAR]" not in body["resolved_prompt_preview"]
    assert "[PRODUCT]" not in body["resolved_prompt_preview"]
    assert "[AVATAR]" in body["scene_template"]["raw_prompt_template"]  # raw preserved
    assert captured == {"product_id": "p1"}


def test_handoff_requires_product_id():
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff")
    assert r.status_code == 422


def test_handoff_product_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("PRODUCT_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.creative_handoff_service.prepare_generation_handoff", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff", params={"product_id": "nope"})
    assert r.status_code == 404


def test_handoff_selection_not_found(monkeypatch):
    async def fake(product_id):
        raise ValueError("SELECTION_NOT_FOUND")

    monkeypatch.setattr(
        "agent.services.creative_handoff_service.prepare_generation_handoff", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff", params={"product_id": "p2"})
    assert r.status_code == 404


def test_handoff_not_approved_returns_409(monkeypatch):
    async def fake(product_id):
        raise ValueError("SELECTION_NOT_APPROVED")

    monkeypatch.setattr(
        "agent.services.creative_handoff_service.prepare_generation_handoff", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff", params={"product_id": "p3"})
    assert r.status_code == 409


def test_handoff_invalid_avatar_returns_422(monkeypatch):
    async def fake(product_id):
        raise ValueError("INVALID_AVATAR_CODE")

    monkeypatch.setattr(
        "agent.services.creative_handoff_service.prepare_generation_handoff", fake
    )
    client = TestClient(_build_app())
    r = client.get("/api/creative-intelligence/creative-handoff", params={"product_id": "p4"})
    assert r.status_code == 422
