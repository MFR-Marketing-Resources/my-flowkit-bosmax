"""V4 contract tests for the four independent AI provider lanes.

All provider transport tests use local doubles.  This module never performs a
network call and never writes a real operator settings file.
"""

import json

import pytest

from agent.services import ai_copy_provider_adapter as adapter
from agent.services import ai_provider_model_catalog as catalog
from agent.services import ai_provider_settings_service as settings


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    settings_file = tmp_path / "ai-provider-settings.json"
    catalog_file = tmp_path / "ai-model-catalog.json"
    monkeypatch.setattr(settings, "AI_PROVIDER_STATE_DIR", tmp_path)
    monkeypatch.setattr(settings, "AI_PROVIDER_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(catalog, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(catalog, "AI_MODEL_CATALOG_FILE", catalog_file)
    for name in set(settings.LANE_EXECUTION_ENV_VARS.values()) | set(
        settings.LEGACY_LANE_EXECUTION_ENV_VARS.values()
    ):
        monkeypatch.delenv(name, raising=False)
    for name in settings.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(settings.ACTIVE_PROVIDER_ENV_VAR, raising=False)
    return settings_file


def _lane(summary, lane):
    return next(item for item in summary["lanes"] if item["lane"] == lane)


def _configure(settings_file, provider, model, lane, *, execution=True):
    settings.update_provider_key(provider, "unit-test-provider-key")
    return settings.update_lane_settings(
        lane, provider, model, execution_enabled=execution
    )


def test_fresh_install_has_exactly_four_fail_closed_lanes(isolated_state):
    summary = settings.summarize_provider_settings()
    assert [item["lane"] for item in summary["lanes"]] == [
        "text",
        "structure",
        "image",
        "video",
    ]
    assert all(item["status"] == "NOT_CONFIGURED" for item in summary["lanes"])
    assert all(not item["configured"] for item in summary["lanes"])


def test_v3_migration_copies_explicit_text_to_text_and_structure_and_is_idempotent(
    isolated_state,
):
    isolated_state.write_text(
        json.dumps(
            {
                "version": 3,
                "active_provider": "deepseek",
                "providers": {
                    "deepseek": {
                        "api_key": "unit-test-provider-key",
                        "updated_at": "2026-08-01T00:00:00Z",
                        "activated_at": "2026-08-02T00:00:00Z",
                        "default_model": "deepseek-v4-flash",
                    }
                },
                "lanes": {
                    "text_assist": {
                        "provider_id": "deepseek",
                        "model_id": "deepseek-v4-flash",
                        "execution_enabled": True,
                        "configured_by_user": True,
                    },
                    "vision": {
                        "provider_id": "openai",
                        "model_id": "gpt-4o",
                        "execution_enabled": False,
                        "configured_by_user": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    first = settings.summarize_provider_settings()
    assert _lane(first, "text")["provider_id"] == "deepseek"
    assert _lane(first, "text")["model_id"] == "deepseek-v4-flash"
    assert _lane(first, "structure")["provider_id"] == "deepseek"
    assert _lane(first, "structure")["model_id"] == "deepseek-v4-flash"
    assert _lane(first, "image")["provider_id"] == "openai"
    assert _lane(first, "video")["status"] == "NOT_CONFIGURED"
    assert first["active_provider"] == "deepseek"
    provider = next(
        item for item in first["providers"] if item["provider_id"] == "deepseek"
    )
    assert provider["has_key"] is True
    assert provider["updated_at"] == "2026-08-01T00:00:00Z"
    assert provider["activated_at"] == "2026-08-02T00:00:00Z"
    assert provider["default_model"] == "deepseek-v4-flash"

    on_disk = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert on_disk["version"] == 4
    assert set(on_disk["lanes"]) == {"text", "structure", "image", "video"}
    assert "text_assist" not in on_disk["lanes"]
    assert "vision" not in on_disk["lanes"]

    second = settings.summarize_provider_settings()
    assert second == first
    assert "unit-test-provider-key" not in json.dumps(first)


def test_unconfigured_v3_text_does_not_invent_text_or_structure(isolated_state):
    isolated_state.write_text(
        json.dumps(
            {
                "version": 3,
                "providers": {},
                "lanes": {
                    "text_assist": {
                        "provider_id": "deepseek",
                        "model_id": "deepseek-v4-flash",
                        "execution_enabled": True,
                        "configured_by_user": False,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    summary = settings.summarize_provider_settings()
    assert _lane(summary, "text")["status"] == "NOT_CONFIGURED"
    assert _lane(summary, "structure")["status"] == "NOT_CONFIGURED"
    assert _lane(summary, "video")["status"] == "NOT_CONFIGURED"


def test_lane_ownership_is_independent_from_global_active_provider(isolated_state):
    _configure(isolated_state, "qwen", "qwen-max", "text")
    _configure(isolated_state, "deepseek", "deepseek-v4-flash", "structure")
    _configure(isolated_state, "openai", "gpt-4o", "image")
    _configure(
        isolated_state,
        "anthropic",
        "claude-haiku-4-5-20251001",
        "video",
        execution=False,
    )
    settings.activate_provider("openai")

    summary = settings.summarize_provider_settings()
    assert summary["active_provider"] == "openai"
    assert settings.get_lane_provider("text") == "qwen"
    assert settings.get_lane_model("text") == "qwen-max"
    assert settings.get_lane_provider("structure") == "deepseek"
    assert settings.get_lane_model("structure") == "deepseek-v4-flash"
    assert settings.get_lane_provider("image") == "openai"
    assert settings.get_lane_provider("video") == "anthropic"

    settings.update_lane_settings(
        "text", "qwen", "qwen-plus", execution_enabled=False
    )
    assert settings.get_lane_model("structure") == "deepseek-v4-flash"
    assert settings.get_lane_model("image") == "gpt-4o"
    settings.update_lane_settings(
        "structure", "deepseek", "deepseek-v4-pro", execution_enabled=False
    )
    assert settings.get_lane_model("text") == "qwen-plus"


def test_catalog_capabilities_are_explicit_and_deepseek_is_not_media_capable(
    isolated_state,
):
    assert catalog.model_supports_lane(
        "deepseek", "deepseek-v4-flash", "text"
    )
    assert catalog.model_supports_lane(
        "deepseek", "deepseek-v4-flash", "structure"
    )
    assert not catalog.model_supports_lane(
        "deepseek", "deepseek-v4-flash", "image"
    )
    assert not catalog.model_supports_lane(
        "deepseek", "deepseek-v4-flash", "video"
    )
    assert not catalog.model_supports_lane(
        "deepseek", "deepseek-v4-pro", "image"
    )
    assert not catalog.model_supports_lane(
        "deepseek", "deepseek-v4-pro", "video"
    )
    luna = catalog.get_model_entry("openai", "gpt-5.6-luna")
    assert luna is not None
    assert luna["label"] == "GPT-5.6 Luna"
    assert luna["lanes"] == ["text", "structure"]
    with pytest.raises(ValueError, match="MODEL_NOT_SUPPORTED_FOR_LANE"):
        settings.update_lane_settings(
            "video", "deepseek", "deepseek-v4-flash", execution_enabled=False
        )


def test_structure_primary_and_fallback_resolve_without_provider_call(isolated_state, monkeypatch):
    # This is the provider-free V3/FAST54 resolution proof: selecting the
    # operator-intended pair exposes STRUCTURE ownership while no key/gate is
    # present, so the adapter must not reach its HTTP seam.
    settings.update_lane_settings(
        "structure",
        "deepseek",
        "deepseek-v4-flash",
        execution_enabled=False,
        fallback_provider_id="deepseek",
        fallback_model_id="deepseek-v4-pro",
        fallback_enabled=True,
    )
    monkeypatch.setattr(
        "httpx.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider call forbidden in provider-free proof")
        ),
    )

    summary = settings.summarize_provider_settings()
    structure = _lane(summary, "structure")
    assert structure["provider_id"] == "deepseek"
    assert structure["model_id"] == "deepseek-v4-flash"
    assert structure["fallback_provider_id"] == "deepseek"
    assert structure["fallback_model_id"] == "deepseek-v4-pro"
    assert structure["fallback_enabled"] is True
    assert structure["status"] == "KEY_MISSING"
    assert adapter.is_configured("structure") is False


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_structure_fallback_is_one_call_and_keeps_separate_receipts(
    isolated_state, monkeypatch
):
    settings.update_provider_key("deepseek", "unit-test-provider-key")
    settings.update_lane_settings(
        "structure",
        "deepseek",
        "deepseek-v4-flash",
        execution_enabled=True,
        fallback_provider_id="deepseek",
        fallback_model_id="deepseek-v4-pro",
        fallback_enabled=True,
    )
    responses = iter(
        [
            _FakeResponse(
                {
                    "choices": [
                        {"message": {"content": "{"}, "finish_reason": "stop"}
                    ]
                }
            ),
            _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {"content": '{"selected": true}'},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ),
        ]
    )
    seen_models = []

    def fake_post(url, headers=None, json=None, timeout=None):
        seen_models.append(json["model"])
        return next(responses)

    monkeypatch.setattr("httpx.post", fake_post)
    parsed, receipt = adapter.complete_json_with_receipt(
        "Return one strict object.", "Use the supplied evidence.", lane="structure"
    )

    assert parsed == {"selected": True}
    assert seen_models == ["deepseek-v4-flash", "deepseek-v4-pro"]
    assert receipt["fallback_used"] is True
    assert receipt["primary_receipt"]["model_id"] == "deepseek-v4-flash"
    assert receipt["fallback_receipt"]["model_id"] == "deepseek-v4-pro"
    assert receipt["primary_receipt"]["lane"] == "structure"
    assert receipt["fallback_receipt"]["lane"] == "structure"
    assert "unit-test-provider-key" not in json.dumps(receipt)


def test_structure_deterministic_system_error_never_falls_back(
    isolated_state, monkeypatch
):
    settings.update_provider_key("deepseek", "unit-test-provider-key")
    settings.update_lane_settings(
        "structure",
        "deepseek",
        "deepseek-v4-flash",
        execution_enabled=True,
        fallback_provider_id="deepseek",
        fallback_model_id="deepseek-v4-pro",
        fallback_enabled=True,
    )
    calls = 0

    def deterministic_failure(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise ValueError("BOSMAX_DETERMINISTIC_SCHEMA_DEFECT")

    monkeypatch.setattr("httpx.post", deterministic_failure)
    with pytest.raises(adapter.AICopyProviderError):
        adapter.complete_json_with_receipt(
            "Return one strict object.", "Use the supplied evidence.", lane="structure"
        )
    assert calls == 1
