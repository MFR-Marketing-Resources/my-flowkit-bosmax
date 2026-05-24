from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.ai_provider_settings import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_ai_provider_activation_requires_stored_key(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BOSMAX_ACTIVE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("PRODUCT_IMAGE_VISION_PROVIDER", raising=False)

    client = TestClient(_build_app())
    response = client.post("/api/ai-providers/anthropic/activate")

    assert response.status_code == 422
    assert response.json()["detail"] == "API_KEY_MISSING_FOR_PROVIDER"


def test_ai_provider_put_activate_and_clear_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("BOSMAX_ACTIVE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("PRODUCT_IMAGE_VISION_PROVIDER", raising=False)

    client = TestClient(_build_app())

    put_response = client.put(
        "/api/ai-providers/anthropic/key",
        json={"api_key": "sk-ant-test-1234567890"},
    )

    assert put_response.status_code == 200
    put_payload = put_response.json()
    anthropic = next(
        provider
        for provider in put_payload["providers"]
        if provider["provider_id"] == "anthropic"
    )
    assert anthropic["has_key"] is True
    assert anthropic["status"] == "READY"
    assert anthropic["masked_key"] != "sk-ant-test-1234567890"

    activate_response = client.post("/api/ai-providers/anthropic/activate")

    assert activate_response.status_code == 200
    activate_payload = activate_response.json()
    anthropic_active = next(
        provider
        for provider in activate_payload["providers"]
        if provider["provider_id"] == "anthropic"
    )
    assert activate_payload["active_provider"] == "anthropic"
    assert anthropic_active["status"] == "ACTIVE"
    assert anthropic_active["is_active"] is True

    clear_response = client.delete("/api/ai-providers/anthropic/key")

    assert clear_response.status_code == 200
    clear_payload = clear_response.json()
    anthropic_cleared = next(
        provider
        for provider in clear_payload["providers"]
        if provider["provider_id"] == "anthropic"
    )
    assert clear_payload["active_provider"] is None
    assert anthropic_cleared["has_key"] is False
    assert anthropic_cleared["status"] == "KEY_MISSING"
