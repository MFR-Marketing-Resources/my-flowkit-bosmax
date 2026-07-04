import os

from agent.services.ai_provider_settings_service import (
    apply_runtime_provider_environment,
    get_ai_lane_route,
    is_ai_lane_executable,
    reset_ai_routing,
    update_ai_lane_routing,
)


def test_apply_runtime_provider_environment_keeps_anthropic_env_unset_when_route_not_enabled(
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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PRODUCT_IMAGE_VISION_PROVIDER", raising=False)
    monkeypatch.delenv("BOSMAX_ACTIVE_AI_PROVIDER", raising=False)

    payload = {
        "version": 2,
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
        "routing": {
            "product_image_analysis": {
                "provider_id": "anthropic",
                "model_id": "claude-haiku-4-5-20251001",
                "enabled": False,
                "execution_mode": "live",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "copywriting_assist": {
                "provider_id": "qwen",
                "model_id": "qwen-plus",
                "enabled": False,
                "execution_mode": "live",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "angle_hook_subhook_expansion": {
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-flash",
                "enabled": False,
                "execution_mode": "registry_only",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "claim_risk_qa": {
                "provider_id": "openai",
                "model_id": "gpt-5.4-mini",
                "enabled": False,
                "execution_mode": "registry_only",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "product_truth_extraction": {
                "provider_id": "gemini",
                "model_id": "gemini-2.5-flash-lite",
                "enabled": False,
                "execution_mode": "registry_only",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "video_review": {
                "provider_id": "anthropic",
                "model_id": "claude-haiku-4-5-20251001",
                "enabled": False,
                "execution_mode": "live",
                "locked": False,
                "updated_at": None,
                "source": "test",
            },
            "final_prompt_compiler": {
                "provider_id": "deterministic",
                "model_id": "bosmax-canonical-compiler",
                "enabled": True,
                "execution_mode": "live",
                "locked": True,
                "updated_at": None,
                "source": "test",
            },
        },
    }

    apply_runtime_provider_environment(payload)

    assert os.environ.get("ANTHROPIC_API_KEY") is None
    assert os.environ.get("PRODUCT_IMAGE_VISION_PROVIDER") is None
    assert os.environ.get("BOSMAX_ACTIVE_AI_PROVIDER") == "anthropic"


def test_routing_helpers_require_key_for_live_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )

    route = get_ai_lane_route("product_image_analysis")

    assert route["provider_id"] == "anthropic"
    assert route["execution_mode"] == "live"
    assert route["enabled"] is False
    assert is_ai_lane_executable("product_image_analysis") is False


def test_update_and_reset_routing_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_STATE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "agent.services.ai_provider_settings_service.AI_PROVIDER_SETTINGS_FILE",
        tmp_path / "ai-provider-settings.json",
    )

    update_ai_lane_routing(
        "claim_risk_qa",
        provider_id="openai",
        model_id="gpt-5.4-mini",
        enabled=True,
        execution_mode="registry_only",
    )

    updated = get_ai_lane_route("claim_risk_qa")
    assert updated["provider_id"] == "openai"
    assert updated["model_id"] == "gpt-5.4-mini"
    assert updated["enabled"] is True
    assert updated["execution_mode"] == "registry_only"

    reset_payload = reset_ai_routing()
    reset_route = next(
        lane for lane in reset_payload["lanes"] if lane["lane_id"] == "claim_risk_qa"
    )

    assert reset_route["enabled"] is False
    assert reset_route["execution_mode"] == "registry_only"
