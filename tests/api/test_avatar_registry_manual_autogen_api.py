"""Avatar registry — manual add + AI auto-generate API contract.

The AI adapter is ALWAYS mocked — no real provider network call ever happens.
add_avatar is mocked in the happy paths so the committed data/ bridge is never
touched.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_add_manual_redundant_avatar_409():
    """An avatar whose descriptor already exists (Alya seed) fails closed 409."""
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Clone",
            "gender": "F",
            "skin_tone": "Light-medium",
            "hair_style": "Medium tidy",
            "wardrobe": "Smart office wear",
            "expression": "Calm neutral",
        },
    )
    assert response.status_code == 409
    assert "AVATAR_REDUNDANT" in response.text


def test_add_manual_happy_path(monkeypatch):
    """A distinct avatar is added through the (mocked) add_avatar door."""
    captured: dict = {}

    def fake_add_avatar(row):
        captured["row"] = row
        return {"rows": 251, "approved_loaded": 251, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.avatar_registry.add_avatar", fake_add_avatar)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "Zara",
            "gender": "F",
            "skin_tone": "Deep dark",
            "hair_style": "Long wavy",
            "wardrobe": "Batik kebaya",
            "hijab": True,
            "expression": "Warm smile",
            "usage_tags": "raya|festive",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redundant"] is False
    assert body["character_name"] == "Zara"
    assert body["avatar_code"].startswith("BOS_F_ZARA_BATIK_KEBAYA_")
    row = captured["row"]
    assert row["approved_flag"] == "TRUE"
    assert "Identity: Zara" in row["PromptV1"]
    assert "hijab" in row["PromptV1"].lower()


def test_add_manual_rejects_bad_gender():
    """gender must be F or M (pydantic pattern) → 422."""
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/add-manual",
        json={
            "character_name": "X",
            "gender": "Z",
            "skin_tone": "Fair",
            "hair_style": "Short",
            "wardrobe": "Suit",
            "expression": "Serious",
        },
    )
    assert response.status_code == 422


def test_auto_generate_fail_closed_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: False)
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a friendly pharmacist"},
    )
    assert response.status_code == 503
    assert "TEXT_ASSIST_NOT_CONFIGURED" in response.text


def test_auto_generate_happy_path_mocked_adapter(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)

    def fake_complete_json(system, user):
        return {
            "character_name": "Farah",
            "gender": "F",
            "skin_tone": "Warm tan",
            "hair_style": "Shoulder-length curly",
            "wardrobe": "Modern hijab abaya",
            "hijab": True,
            "expression": "Bright confident",
            "environment": "Bright pharmacy interior",
            "lighting": "Soft daylight",
            "camera": "Waist-up",
            "usage_tags": ["pharmacy", "health"],
        }

    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json", fake_complete_json)

    captured: dict = {}

    def fake_add_avatar(row):
        captured["row"] = row
        return {"rows": 251, "approved_loaded": 251, "bridge_path": "x"}

    monkeypatch.setattr(
        "agent.services.avatar_registry.add_avatar", fake_add_avatar)

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "a friendly Malaysian pharmacist", "gender": "F"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] is True
    assert body["character_name"] == "Farah"
    assert body["avatar_code"].startswith("BOS_F_FARAH_")
    assert captured["row"]["usage_tags"] == "pharmacy|health"
    assert "hijab" in captured["row"]["PromptV1"].lower()


def test_auto_generate_invalid_ai_json_502(monkeypatch):
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.is_configured", lambda: True)
    monkeypatch.setattr(
        "agent.services.ai_copy_provider_adapter.complete_json",
        lambda system, user: {"character_name": "NoGender"})  # missing keys
    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/avatar-registry/auto-generate",
        json={"brief": "x"},
    )
    assert response.status_code == 502
    assert "AI_AVATAR_INVALID" in response.text
