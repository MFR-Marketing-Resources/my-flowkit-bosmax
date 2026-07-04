from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.ai_provider_settings import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _build_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("BOSMAX_ACTIVE_AI_PROVIDER", raising=False)
    monkeypatch.delenv("PRODUCT_IMAGE_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_PROVIDER", raising=False)
    return TestClient(_build_app())


def _lane(payload: dict, lane_id: str) -> dict:
    return next(item for item in payload["lanes"] if item["lane_id"] == lane_id)


def test_ai_provider_activation_requires_stored_key(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    response = client.post("/api/ai-providers/anthropic/activate")

    assert response.status_code == 422
    assert response.json()["detail"] == "API_KEY_MISSING_FOR_PROVIDER"


def test_ai_provider_put_activate_and_clear_round_trip(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

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


def test_model_catalog_and_routing_defaults_exist(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    catalog_response = client.get("/api/ai-model-catalog")
    routing_response = client.get("/api/ai-routing")

    assert catalog_response.status_code == 200
    assert routing_response.status_code == 200

    catalog = catalog_response.json()
    routing = routing_response.json()
    deterministic = next(
        provider
        for provider in catalog["providers"]
        if provider["provider_id"] == "deterministic"
    )
    final_route = _lane(routing, "final_prompt_compiler")

    assert deterministic["models"][0]["model_id"] == "bosmax-canonical-compiler"
    assert final_route["provider_id"] == "deterministic"
    assert final_route["model_id"] == "bosmax-canonical-compiler"
    assert final_route["locked"] is True
    assert final_route["enabled"] is True


def test_locked_final_prompt_compiler_cannot_be_changed(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.put(
        "/api/ai-routing/final_prompt_compiler",
        json={
            "provider_id": "openai",
            "model_id": "gpt-5.4-mini",
            "enabled": True,
            "execution_mode": "live",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "LANE_LOCKED"


def test_incompatible_model_lane_combination_is_rejected(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.put(
        "/api/ai-routing/product_image_analysis",
        json={
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-flash",
            "enabled": False,
            "execution_mode": "registry_only",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "MODEL_LANE_INCOMPATIBLE"


def test_unknown_model_is_rejected(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.put(
        "/api/ai-routing/claim_risk_qa",
        json={
            "provider_id": "openai",
            "model_id": "not-a-real-model",
            "enabled": False,
            "execution_mode": "registry_only",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "UNKNOWN_MODEL"


def test_live_execution_without_key_is_rejected(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    response = client.put(
        "/api/ai-routing/product_image_analysis",
        json={
            "provider_id": "anthropic",
            "model_id": "claude-haiku-4-5-20251001",
            "enabled": True,
            "execution_mode": "live",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "API_KEY_REQUIRED_FOR_LIVE_EXECUTION"


def test_registry_only_route_can_be_saved_without_key_and_persists(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    update_response = client.put(
        "/api/ai-routing/claim_risk_qa",
        json={
            "provider_id": "openai",
            "model_id": "gpt-5.4-mini",
            "enabled": True,
            "execution_mode": "registry_only",
        },
    )

    assert update_response.status_code == 200
    updated_route = _lane(update_response.json(), "claim_risk_qa")
    assert updated_route["execution_mode"] == "registry_only"
    assert updated_route["enabled"] is True
    assert updated_route["provider_key_status"] == "MISSING"
    assert updated_route["is_executable_now"] is False

    reload_response = client.get("/api/ai-routing")
    reloaded_route = _lane(reload_response.json(), "claim_risk_qa")
    assert reloaded_route["provider_id"] == "openai"
    assert reloaded_route["model_id"] == "gpt-5.4-mini"


def test_reset_restores_safe_defaults(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)

    update_response = client.put(
        "/api/ai-routing/claim_risk_qa",
        json={
            "provider_id": "openai",
            "model_id": "gpt-5.4-mini",
            "enabled": True,
            "execution_mode": "registry_only",
        },
    )
    assert update_response.status_code == 200

    reset_response = client.post("/api/ai-routing/reset", json={})
    assert reset_response.status_code == 200

    claim_route = _lane(reset_response.json(), "claim_risk_qa")
    copy_route = _lane(reset_response.json(), "copywriting_assist")
    final_route = _lane(reset_response.json(), "final_prompt_compiler")

    assert claim_route["enabled"] is False
    assert claim_route["execution_mode"] == "registry_only"
    assert copy_route["provider_id"] == "qwen"
    assert final_route["locked"] is True
