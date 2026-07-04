"""API contract tests for AI Provider Model & Lane Settings V1 endpoints.

Covers PUT /{provider_id}/model and PUT /lanes/{lane}: happy path, fail-closed
422s for invalid model / lane / combo, and the no-raw-key guarantee in responses.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.ai_provider_settings import router


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR", tmp_path
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_registry_exposes_catalog_and_lanes(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = client.get("/api/ai-providers").json()
    assert "model_catalog" in body and "qwen" in body["model_catalog"]
    assert {lane["lane"] for lane in body["lanes"]} == {"text_assist", "vision"}


def test_put_provider_model_valid(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put("/api/ai-providers/qwen/model", json={"model_id": "qwen-max"})
    assert r.status_code == 200
    qwen = next(p for p in r.json()["providers"] if p["provider_id"] == "qwen")
    assert qwen["default_model"] == "qwen-max"


def test_put_provider_model_invalid_returns_422(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put("/api/ai-providers/qwen/model", json={"model_id": "gpt-4o-mini"})
    assert r.status_code == 422
    assert "UNKNOWN_MODEL_FOR_PROVIDER" in r.json()["detail"]


def test_put_lane_valid_text_assist(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/api/ai-providers/qwen/key", json={"api_key": "sk-qwen-live-abcdef"})
    r = client.put(
        "/api/ai-providers/lanes/text_assist",
        json={"provider_id": "qwen", "model_id": "qwen-max", "execution_enabled": True},
    )
    assert r.status_code == 200
    lane = next(l for l in r.json()["lanes"] if l["lane"] == "text_assist")
    assert lane["provider_id"] == "qwen"
    assert lane["model_id"] == "qwen-max"
    assert lane["execution_enabled"] is True
    assert lane["configured"] is True


def test_put_lane_model_not_supporting_lane_returns_422(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/api/ai-providers/lanes/vision",
        json={"provider_id": "qwen", "model_id": "qwen-plus"},
    )
    assert r.status_code == 422
    assert "MODEL_NOT_SUPPORTED_FOR_LANE" in r.json()["detail"]


def test_put_lane_unknown_lane_returns_422(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Unknown lane fails pydantic Literal validation before service is called.
    r = client.put(
        "/api/ai-providers/lanes/not_a_lane",
        json={"provider_id": "qwen", "model_id": "qwen-plus"},
    )
    assert r.status_code == 422


def test_registry_response_has_no_raw_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/api/ai-providers/anthropic/key", json={"api_key": "sk-ant-secret-abcdef123456"})
    body = client.get("/api/ai-providers").text
    assert "sk-ant-secret-abcdef123456" not in body
