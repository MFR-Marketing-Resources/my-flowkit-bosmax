"""Unit tests for AI Provider Model & Lane Settings (V3: explicit lanes).

Covers: first-run NOT_CONFIGURED lanes, V1/V2 -> V3 migration (keys preserved,
seeded-default-without-key downgraded, real config preserved), mutable model
catalog wiring, provider/model/lane validation, get_lane_* resolvers, and the
no-raw-key guarantee. Both the settings file AND the model-catalog file are
isolated to tmp; lane execution env overrides are cleared so stored state decides.
"""
import json

import pytest

from agent.services import ai_provider_settings_service as svc
from agent.services import ai_provider_model_catalog as cat


@pytest.fixture
def state(monkeypatch, tmp_path):
    settings_file = tmp_path / "ai-provider-settings.json"
    catalog_file = tmp_path / "ai-model-catalog.json"
    monkeypatch.setattr(svc, "AI_PROVIDER_STATE_DIR", tmp_path)
    monkeypatch.setattr(svc, "AI_PROVIDER_SETTINGS_FILE", settings_file)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_FILE", catalog_file)
    monkeypatch.delenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_MODEL", raising=False)
    for env in svc.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env, raising=False)
    return settings_file


def _lane(summary, lane):
    return next(l for l in summary["lanes"] if l["lane"] == lane)


def _provider(summary, pid):
    return next(p for p in summary["providers"] if p["provider_id"] == pid)


# --- first run ------------------------------------------------------------

def test_fresh_install_lanes_are_not_configured(state):
    summary = svc.summarize_provider_settings()
    for lane_name in ("text_assist", "vision"):
        lane = _lane(summary, lane_name)
        assert lane["provider_id"] is None
        assert lane["model_id"] is None
        assert lane["execution_enabled"] is False
        assert lane["configured_by_user"] is False
        assert lane["status"] == "NOT_CONFIGURED"
    # No hidden default provider/model resolves at runtime either.
    assert svc.get_lane_provider("text_assist") is None
    assert svc.get_lane_model("text_assist") is None
    assert svc.get_lane_provider("vision") is None


# --- migration ------------------------------------------------------------

def test_v1_migrates_preserving_keys_but_lanes_not_configured(state):
    state.write_text(
        json.dumps(
            {
                "version": 1,
                "active_provider": "qwen",
                "providers": {
                    "qwen": {"api_key": "sk-qwen-EXISTING-123456", "updated_at": None, "activated_at": None},
                },
            }
        ),
        encoding="utf-8",
    )
    summary = svc.summarize_provider_settings()
    assert _provider(summary, "qwen")["has_key"] is True
    assert svc.get_provider_api_key("qwen") == "sk-qwen-EXISTING-123456"
    # V1 has no lanes -> explicit NOT_CONFIGURED, never auto-selected.
    assert _lane(summary, "text_assist")["status"] == "NOT_CONFIGURED"


def test_v2_seeded_default_without_key_downgrades_to_not_configured(state):
    # A V2 file whose lanes are ONLY the old hardcoded seed defaults, with NO key.
    state.write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "qwen": {"api_key": "", "updated_at": None, "activated_at": None, "default_model": "qwen-plus"},
                    "anthropic": {"api_key": "", "updated_at": None, "activated_at": None, "default_model": "claude-sonnet-5"},
                },
                "lanes": {
                    "text_assist": {"provider_id": "qwen", "model_id": "qwen-plus", "execution_enabled": True},
                    "vision": {"provider_id": "anthropic", "model_id": "claude-sonnet-5", "execution_enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    summary = svc.summarize_provider_settings()
    assert _lane(summary, "text_assist")["status"] == "NOT_CONFIGURED"
    assert _lane(summary, "text_assist")["provider_id"] is None
    assert _lane(summary, "vision")["status"] == "NOT_CONFIGURED"


def test_v2_seeded_text_assist_default_with_qwen_key_downgrades_to_not_configured(state):
    # A stored Qwen key is NOT proof the operator explicitly chose Qwen for the
    # text_assist lane — the seed default must still downgrade to NOT_CONFIGURED.
    state.write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "qwen": {
                        "api_key": "sk-qwen-existing-abcdef",
                        "updated_at": None,
                        "activated_at": None,
                        "default_model": "qwen-plus",
                    },
                },
                "lanes": {
                    "text_assist": {"provider_id": "qwen", "model_id": "qwen-plus", "execution_enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    summary = svc.summarize_provider_settings()
    # Key preserved.
    assert _provider(summary, "qwen")["has_key"] is True
    assert svc.get_provider_api_key("qwen") == "sk-qwen-existing-abcdef"
    # Lane downgraded despite the key.
    lane = _lane(summary, "text_assist")
    assert lane["status"] == "NOT_CONFIGURED"
    assert lane["provider_id"] is None
    assert lane["model_id"] is None
    assert svc.get_lane_provider("text_assist") is None
    assert svc.get_lane_model("text_assist") is None


def test_v2_seeded_vision_default_with_anthropic_key_downgrades_to_not_configured(state):
    state.write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "anthropic": {
                        "api_key": "sk-ant-existing-abcdef",
                        "updated_at": None,
                        "activated_at": None,
                        "default_model": "claude-sonnet-5",
                    },
                },
                "lanes": {
                    "vision": {"provider_id": "anthropic", "model_id": "claude-sonnet-5", "execution_enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    summary = svc.summarize_provider_settings()
    assert _provider(summary, "anthropic")["has_key"] is True
    lane = _lane(summary, "vision")
    assert lane["status"] == "NOT_CONFIGURED"
    assert lane["provider_id"] is None
    assert svc.get_lane_provider("vision") is None


def test_v2_lane_with_key_is_preserved_as_user_configured(state):
    state.write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "qwen": {"api_key": "sk-qwen-REAL-abcdef", "updated_at": None, "activated_at": None, "default_model": "qwen-plus"},
                },
                "lanes": {
                    "text_assist": {"provider_id": "qwen", "model_id": "qwen-max", "execution_enabled": True},
                    "vision": {"provider_id": None, "model_id": None, "execution_enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    summary = svc.summarize_provider_settings()
    lane = _lane(summary, "text_assist")
    assert lane["provider_id"] == "qwen"
    assert lane["model_id"] == "qwen-max"
    assert lane["configured_by_user"] is True
    assert lane["status"] == "READY"  # key + valid model + execution on
    assert svc.get_lane_model("text_assist") == "qwen-max"


def test_v2_non_default_provider_preserved_even_without_key(state):
    # Operator explicitly chose openai for text_assist (not the seed default) but
    # never added a key -> that is clear user intent; preserve it (KEY_MISSING).
    state.write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "openai": {"api_key": "", "updated_at": None, "activated_at": None, "default_model": "gpt-4o-mini"},
                },
                "lanes": {
                    "text_assist": {"provider_id": "openai", "model_id": "gpt-4o-mini", "execution_enabled": False},
                    "vision": {"provider_id": None, "model_id": None, "execution_enabled": False},
                },
            }
        ),
        encoding="utf-8",
    )
    lane = _lane(svc.summarize_provider_settings(), "text_assist")
    assert lane["provider_id"] == "openai"
    assert lane["configured_by_user"] is True
    assert lane["status"] == "KEY_MISSING"


def test_load_does_not_rewrite_valid_v2_file(state):
    original = {
        "version": 2,
        "active_provider": None,
        "providers": {"qwen": {"api_key": "sk-qwen-REAL-abcdef", "updated_at": None, "activated_at": None}},
        "lanes": {"text_assist": {"provider_id": "qwen", "model_id": "qwen-max", "execution_enabled": True}},
    }
    state.write_text(json.dumps(original), encoding="utf-8")
    svc.summarize_provider_settings()  # plain read
    on_disk = json.loads(state.read_text(encoding="utf-8"))
    assert on_disk["version"] == 2
    assert on_disk["providers"]["qwen"]["api_key"] == "sk-qwen-REAL-abcdef"


# --- summary + catalog ----------------------------------------------------

def test_summary_includes_model_catalog_and_lanes(state):
    summary = svc.summarize_provider_settings()
    assert "model_catalog" in summary
    assert "qwen" in summary["model_catalog"]
    assert summary["model_catalog"]["qwen"]["transport"] == "openai_compatible_chat"
    assert any(m["model_id"] == "qwen-max" for m in summary["model_catalog"]["qwen"]["models"])
    assert {lane["lane"] for lane in summary["lanes"]} == {"text_assist", "vision"}


def test_registry_never_returns_raw_api_key(state):
    svc.update_provider_key("qwen", "sk-qwen-SECRET-123456")
    summary = svc.summarize_provider_settings()
    blob = json.dumps(summary)
    assert "sk-qwen-SECRET-123456" not in blob
    qwen = _provider(summary, "qwen")
    assert qwen["masked_key"] and qwen["masked_key"] != "sk-qwen-SECRET-123456"


# --- provider default model ----------------------------------------------

def test_update_provider_default_model_valid(state):
    summary = svc.update_provider_default_model("qwen", "qwen-max")
    assert _provider(summary, "qwen")["default_model"] == "qwen-max"


def test_update_provider_default_model_rejects_foreign_model(state):
    with pytest.raises(ValueError) as exc:
        svc.update_provider_default_model("qwen", "gpt-4o-mini")
    assert "MODEL_NOT_FOUND" in str(exc.value)


# --- lane settings --------------------------------------------------------

def test_update_lane_settings_valid_text_assist(state):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    summary = svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)
    lane = _lane(summary, "text_assist")
    assert lane["provider_id"] == "qwen"
    assert lane["model_id"] == "qwen-max"
    assert lane["execution_enabled"] is True
    assert lane["configured_by_user"] is True
    assert lane["status"] == "READY"
    assert svc.get_lane_provider("text_assist") == "qwen"
    assert svc.get_lane_model("text_assist") == "qwen-max"
    assert svc.get_lane_api_key("text_assist") == "sk-qwen-live-abcdef"


def test_update_lane_settings_rejects_model_not_supporting_lane(state):
    with pytest.raises(ValueError) as exc:
        svc.update_lane_settings("vision", "qwen", "qwen-plus")
    assert "MODEL_NOT_SUPPORTED_FOR_LANE" in str(exc.value)


def test_update_lane_settings_rejects_foreign_model(state):
    with pytest.raises(ValueError) as exc:
        svc.update_lane_settings("text_assist", "qwen", "gpt-4o-mini")
    assert "MODEL_NOT_FOUND" in str(exc.value)


def test_update_lane_settings_rejects_disabled_model(state):
    cat.disable_provider_model("qwen", "qwen-max")
    with pytest.raises(ValueError) as exc:
        svc.update_lane_settings("text_assist", "qwen", "qwen-max")
    assert "MODEL_DISABLED" in str(exc.value)


def test_validate_provider_model_for_lane_unknown_lane(state):
    with pytest.raises(ValueError) as exc:
        svc.validate_provider_model_for_lane("qwen", "qwen-plus", "not_a_lane")
    assert "UNSUPPORTED_LANE" in str(exc.value)


def test_clear_lane_returns_to_not_configured(state):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)
    summary = svc.clear_lane_settings("text_assist")
    lane = _lane(summary, "text_assist")
    assert lane["status"] == "NOT_CONFIGURED"
    assert lane["provider_id"] is None
    assert lane["configured_by_user"] is False


def test_lane_key_missing_status(state):
    # provider/model valid but no key.
    svc.update_lane_settings("text_assist", "qwen", "qwen-plus", execution_enabled=True)
    lane = _lane(svc.summarize_provider_settings(), "text_assist")
    assert lane["status"] == "KEY_MISSING"


def test_custom_model_selectable_for_lane(state):
    # DeepSeek example: operator adds a model that isn't in source code.
    cat.upsert_provider_model("deepseek", "deepseek-reasoner", "DeepSeek Reasoner", ["text_assist"], True)
    svc.update_provider_key("deepseek", "sk-deepseek-live-abcdef")
    summary = svc.update_lane_settings("text_assist", "deepseek", "deepseek-reasoner", execution_enabled=True)
    lane = _lane(summary, "text_assist")
    assert lane["provider_id"] == "deepseek"
    assert lane["model_id"] == "deepseek-reasoner"
    assert lane["status"] == "READY"
    assert svc.get_lane_model("text_assist") == "deepseek-reasoner"
