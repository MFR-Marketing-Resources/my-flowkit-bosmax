"""API contract tests for AI Provider Model & Lane Settings V4 endpoints.

Covers registry shape (catalog + lanes), provider default model, lane config,
the mutable model-catalog CRUD endpoints (add custom / disable / reset-seed),
fail-closed 422s, and the no-raw-key guarantee. Both state files are isolated.
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
    monkeypatch.setattr(
        "agent.services.ai_provider_model_catalog.AI_MODEL_CATALOG_DIR", tmp_path
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_model_catalog.AI_MODEL_CATALOG_FILE",
        tmp_path / "ai-model-catalog.json",
    )
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _lane(body, lane):
    return next(l for l in body["lanes"] if l["lane"] == lane)


def test_get_registry_fresh_lanes_not_configured(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = client.get("/api/ai-providers").json()
    assert "model_catalog" in body and "qwen" in body["model_catalog"]
    assert body["model_catalog"]["qwen"]["transport"] == "openai_compatible_chat"
    for lane_name in ("text", "structure", "image", "video"):
        assert _lane(body, lane_name)["status"] == "NOT_CONFIGURED"


def test_get_model_catalog_endpoint(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = client.get("/api/ai-providers/model-catalog").json()
    assert body["version"] >= 1
    assert "deepseek" in body["providers"]
    assert any(m["model_id"] == "deepseek-v4-pro" for m in body["providers"]["deepseek"]["models"])


def test_add_custom_deepseek_model_and_select_for_lane(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Operator adds a custom DeepSeek model with no code change.
    r = client.put(
        "/api/ai-providers/model-catalog/deepseek/models/deepseek-reasoner",
        json={"label": "DeepSeek Reasoner", "lanes": ["text"], "enabled": True},
    )
    assert r.status_code == 200
    models = r.json()["model_catalog"]["deepseek"]["models"]
    custom = next(m for m in models if m["model_id"] == "deepseek-reasoner")
    assert custom["source"] == "custom"
    assert custom["enabled"] is True

    client.put("/api/ai-providers/deepseek/key", json={"api_key": "sk-deepseek-live-abcdef"})
    r2 = client.put(
        "/api/ai-providers/lanes/text",
        json={"provider_id": "deepseek", "model_id": "deepseek-reasoner", "execution_enabled": True},
    )
    assert r2.status_code == 200
    lane = _lane(r2.json(), "text")
    assert lane["provider_id"] == "deepseek"
    assert lane["model_id"] == "deepseek-reasoner"
    assert lane["status"] == "READY"


def test_disable_model_then_lane_selection_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.patch("/api/ai-providers/model-catalog/qwen/models/qwen-max/disable")
    r = client.put(
        "/api/ai-providers/lanes/text",
        json={"provider_id": "qwen", "model_id": "qwen-max"},
    )
    assert r.status_code == 422
    assert "MODEL_DISABLED" in r.json()["detail"]


def test_reset_seed_restores_catalog(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.patch("/api/ai-providers/model-catalog/qwen/models/qwen-max/disable")
    client.post("/api/ai-providers/model-catalog/reset-seed")
    body = client.get("/api/ai-providers/model-catalog").json()
    qwen_max = next(m for m in body["providers"]["qwen"]["models"] if m["model_id"] == "qwen-max")
    assert qwen_max["enabled"] is True


def test_put_provider_model_invalid_returns_422(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put("/api/ai-providers/qwen/model", json={"model_id": "gpt-4o-mini"})
    assert r.status_code == 422
    assert "MODEL_NOT_FOUND" in r.json()["detail"]


def test_put_lane_model_not_supporting_lane_returns_422(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/api/ai-providers/lanes/image",
        json={"provider_id": "qwen", "model_id": "qwen-plus"},
    )
    assert r.status_code == 422
    assert "MODEL_NOT_SUPPORTED_FOR_LANE" in r.json()["detail"]


def test_add_custom_qwen_image_model_now_allowed(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    # Multi-provider image: qwen transport is a wired image transport, so a
    # custom Qwen-VL model on the image lane is accepted.
    r = client.put(
        "/api/ai-providers/model-catalog/qwen/models/qwen-vision-x",
        json={"label": "Q VL", "lanes": ["image"], "enabled": True},
    )
    assert r.status_code == 200
    models = r.json()["model_catalog"]["qwen"]["models"]
    custom = next(m for m in models if m["model_id"] == "qwen-vision-x")
    assert custom["lanes"] == ["image"]
    assert custom["source"] == "custom"


def test_clear_lane_endpoint(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/api/ai-providers/qwen/key", json={"api_key": "sk-qwen-live-abcdef"})
    client.put(
        "/api/ai-providers/lanes/text",
        json={"provider_id": "qwen", "model_id": "qwen-max", "execution_enabled": True},
    )
    r = client.delete("/api/ai-providers/lanes/text")
    assert r.status_code == 200
    assert _lane(r.json(), "text")["status"] == "NOT_CONFIGURED"


def test_registry_response_has_no_raw_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/api/ai-providers/anthropic/key", json={"api_key": "sk-ant-secret-abcdef123456"})
    body = client.get("/api/ai-providers").text
    assert "sk-ant-secret-abcdef123456" not in body


# --- HOTFIX regression: corrupt/legacy state must never break the registry ---
# The /settings blank-page incident traced to a shape mismatch. The frontend is
# now defensive, and the backend must keep emitting a valid V4 registry shape
# (never 500) even when its on-disk state files are corrupt or legacy.


def _fresh_registry_shape_ok(body: dict) -> None:
    assert isinstance(body.get("providers"), list) and body["providers"]
    assert isinstance(body.get("model_catalog"), dict) and body["model_catalog"]
    assert isinstance(body.get("lanes"), list) and body["lanes"]
    # Every catalog entry is the V4 object shape (not a bare array).
    for entry in body["model_catalog"].values():
        assert isinstance(entry, dict)
        assert "transport" in entry and isinstance(entry.get("models"), list)
    # Every lane carries an explicit status string.
    for lane in body["lanes"]:
        assert isinstance(lane.get("status"), str) and lane["status"]


def test_registry_after_old_catalog_exposes_multi_provider_image(monkeypatch, tmp_path):
    import json

    # A pre-#210 local catalog: openai/gemini text_assist only, no qwen-vl-max.
    old_catalog = {
        "version": 1,
        "providers": {
            "anthropic": {"label": "Anthropic", "transport": "anthropic_messages", "enabled": True,
                          "models": [{"model_id": "claude-sonnet-5", "label": "Claude Sonnet 5", "enabled": True, "lanes": ["text_assist", "vision"], "source": "seed"}]},
            "openai": {"label": "OpenAI", "transport": "openai_compatible_chat", "enabled": True,
                       "models": [{"model_id": "gpt-4o", "label": "GPT-4o", "enabled": True, "lanes": ["text_assist"], "source": "seed"}]},
            "gemini": {"label": "Gemini", "transport": "openai_compatible_chat", "enabled": True,
                       "models": [{"model_id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "enabled": True, "lanes": ["text_assist"], "source": "seed"}]},
            "qwen": {"label": "Qwen", "transport": "openai_compatible_chat", "enabled": True,
                     "models": [{"model_id": "qwen-plus", "label": "Qwen Plus", "enabled": True, "lanes": ["text_assist"], "source": "seed"}]},
            "deepseek": {"label": "DeepSeek", "transport": "openai_compatible_chat", "enabled": True,
                         "models": [{"model_id": "deepseek-chat", "label": "DeepSeek Chat", "enabled": True, "lanes": ["text_assist"], "source": "seed"}]},
        },
    }
    (tmp_path / "ai-model-catalog.json").write_text(json.dumps(old_catalog), encoding="utf-8")

    client = _client(monkeypatch, tmp_path)
    body = client.get("/api/ai-providers").json()
    providers = {p["provider_id"]: p for p in body["providers"]}
    for pid in ("anthropic", "openai", "gemini", "qwen"):
        assert "image" in providers[pid]["supported_lanes"], pid
    assert "image" not in providers["deepseek"]["supported_lanes"]
    # Forward-migrated new seed model reaches an existing install.
    qwen_models = {m["model_id"] for m in body["model_catalog"]["qwen"]["models"]}
    assert "qwen-vl-max" in qwen_models
    # Lanes remain NOT_CONFIGURED — migration never auto-selects.
    assert _lane(body, "image")["status"] == "NOT_CONFIGURED"


def test_image_lane_supports_multiple_providers(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    body = client.get("/api/ai-providers").json()
    # Image is multi-provider: openai/gemini/qwen expose seed image models.
    catalog = body["model_catalog"]
    assert any(m["model_id"] == "gpt-4o" and "image" in m["lanes"] for m in catalog["openai"]["models"])
    assert any(m["model_id"] == "gemini-2.0-flash" and "image" in m["lanes"] for m in catalog["gemini"]["models"])
    assert any(m["model_id"] == "qwen-vl-max" and "image" in m["lanes"] for m in catalog["qwen"]["models"])
    for pid in ("anthropic", "openai", "gemini", "qwen"):
        provider = next(p for p in body["providers"] if p["provider_id"] == pid)
        assert "image" in provider["supported_lanes"]


def test_select_openai_image_lane_ready_when_keyed(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put("/api/ai-providers/openai/key", json={"api_key": "sk-openai-vision-live"})
    r = client.put(
        "/api/ai-providers/lanes/image",
        json={"provider_id": "openai", "model_id": "gpt-4o", "execution_enabled": True},
    )
    assert r.status_code == 200
    lane = _lane(r.json(), "image")
    assert lane["provider_id"] == "openai"
    assert lane["model_id"] == "gpt-4o"
    assert lane["status"] == "READY"
    # Selecting a vision provider must not leak the raw key.
    assert "sk-openai-vision-live" not in r.text


def test_select_openai_image_without_key_is_key_missing(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    r = client.put(
        "/api/ai-providers/lanes/image",
        json={"provider_id": "openai", "model_id": "gpt-4o", "execution_enabled": False},
    )
    assert r.status_code == 200
    assert _lane(r.json(), "image")["status"] == "KEY_MISSING"


def test_registry_valid_v4_shape_on_fresh_state(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    _fresh_registry_shape_ok(client.get("/api/ai-providers").json())


def test_registry_survives_corrupt_model_catalog(monkeypatch, tmp_path):
    (tmp_path / "ai-model-catalog.json").write_text("{ not json", encoding="utf-8")
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/ai-providers")
    assert r.status_code == 200
    # Corrupt catalog is reseeded, not surfaced as a 500.
    _fresh_registry_shape_ok(r.json())


def test_registry_survives_corrupt_provider_settings(monkeypatch, tmp_path):
    (tmp_path / "ai-provider-settings.json").write_text("</corrupt>", encoding="utf-8")
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/ai-providers")
    assert r.status_code == 200
    _fresh_registry_shape_ok(r.json())


def test_registry_migrates_legacy_v1_provider_settings(monkeypatch, tmp_path):
    # A pre-#208 (V1, no `version`) settings file with a stored key must migrate
    # forward: the key is preserved and a valid V4 registry is emitted.
    (tmp_path / "ai-provider-settings.json").write_text(
        '{"providers": {"anthropic": {"api_key": "sk-ant-legacy-key-000111"}}}',
        encoding="utf-8",
    )
    client = _client(monkeypatch, tmp_path)
    r = client.get("/api/ai-providers")
    assert r.status_code == 200
    body = r.json()
    _fresh_registry_shape_ok(body)
    anthropic = next(p for p in body["providers"] if p["provider_id"] == "anthropic")
    assert anthropic["has_key"] is True
    assert "sk-ant-legacy-key-000111" not in r.text  # masked only


def test_legacy_lane_routes_are_rejected_after_v4(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for legacy_lane in ("text_assist", "vision"):
        response = client.put(
            f"/api/ai-providers/lanes/{legacy_lane}",
            json={"provider_id": "qwen", "model_id": "qwen-plus"},
        )
        assert response.status_code == 422


def test_structure_fallback_is_visible_and_limited_to_structure_lane(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.put(
        "/api/ai-providers/deepseek/key",
        json={"api_key": "unit-test-provider-key"},
    )
    response = client.put(
        "/api/ai-providers/lanes/structure",
        json={
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-flash",
            "execution_enabled": True,
            "fallback_provider_id": "deepseek",
            "fallback_model_id": "deepseek-v4-pro",
            "fallback_enabled": True,
        },
    )
    assert response.status_code == 200
    structure = _lane(response.json(), "structure")
    assert structure["fallback_provider_id"] == "deepseek"
    assert structure["fallback_model_id"] == "deepseek-v4-pro"
    assert structure["fallback_enabled"] is True
    assert "unit-test-provider-key" not in response.text

    invalid = client.put(
        "/api/ai-providers/lanes/text",
        json={
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-flash",
            "fallback_provider_id": "deepseek",
            "fallback_model_id": "deepseek-v4-pro",
        },
    )
    assert invalid.status_code == 422
    assert "FALLBACK_ONLY_SUPPORTED_FOR_STRUCTURE" in invalid.json()["detail"]


def test_deepseek_v4_cannot_be_selected_for_image_or_video(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    for lane in ("image", "video"):
        response = client.put(
            f"/api/ai-providers/lanes/{lane}",
            json={
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-flash",
            },
        )
        assert response.status_code == 422
        assert "MODEL_NOT_SUPPORTED_FOR_LANE" in response.json()["detail"]
