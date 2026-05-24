import os

from agent.services.ai_provider_settings_service import apply_runtime_provider_environment


def test_apply_runtime_provider_environment_keeps_anthropic_env_unset_when_vision_lane_disabled(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )
    monkeypatch.setenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PRODUCT_IMAGE_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("BOSMAX_ACTIVE_AI_PROVIDER", raising=False)

    payload = {
        "version": 1,
        "active_provider": "anthropic",
        "providers": {
            "qwen": {"api_key": "", "updated_at": None, "activated_at": None},
            "anthropic": {
                "api_key": "sk-ant-test-1234567890",
                "updated_at": "2026-05-25T00:00:00Z",
                "activated_at": "2026-05-25T00:00:00Z",
            },
            "openai": {"api_key": "", "updated_at": None, "activated_at": None},
            "gemini": {"api_key": "", "updated_at": None, "activated_at": None},
            "deepseek": {"api_key": "", "updated_at": None, "activated_at": None},
        },
    }

    apply_runtime_provider_environment(payload)

    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert os.environ.get("PRODUCT_IMAGE_VISION_PROVIDER") is None
    assert os.environ.get("BOSMAX_ACTIVE_AI_PROVIDER") == "anthropic"
