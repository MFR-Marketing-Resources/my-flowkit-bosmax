"""Unit tests for AI Provider Model & Lane Settings V1 (service + catalog).

Covers: V1 -> V2 migration (keys preserved), model catalog + lane summary shape,
provider default-model validation, lane provider/model/lane validation, the
get_lane_* resolvers, and the no-raw-key guarantee. State file is monkeypatched
to a tmp path; lane execution env overrides are cleared so stored state decides.
"""
import json

import pytest

from agent.services import ai_provider_settings_service as svc
from agent.services import ai_provider_model_catalog as cat


V1_PAYLOAD = {
    "version": 1,
    "active_provider": "qwen",
    "providers": {
        "qwen": {
            "api_key": "sk-qwen-existing-123456",
            "updated_at": "2026-05-01T00:00:00Z",
            "activated_at": "2026-05-01T00:00:00Z",
        },
        "anthropic": {"api_key": "sk-ant-existing-7890", "updated_at": None, "activated_at": None},
        "openai": {"api_key": "", "updated_at": None, "activated_at": None},
        "gemini": {"api_key": "", "updated_at": None, "activated_at": None},
        "deepseek": {"api_key": "", "updated_at": None, "activated_at": None},
    },
}


@pytest.fixture
def state(monkeypatch, tmp_path):
    settings_file = tmp_path / "ai-provider-settings.json"
    monkeypatch.setattr(svc, "AI_PROVIDER_STATE_DIR", tmp_path)
    monkeypatch.setattr(svc, "AI_PROVIDER_SETTINGS_FILE", settings_file)
    # Clear lane execution env overrides so STORED state is authoritative.
    monkeypatch.delenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_MODEL", raising=False)
    for env in svc.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env, raising=False)
    return settings_file


def _write_v1(settings_file):
    settings_file.write_text(json.dumps(V1_PAYLOAD, indent=2), encoding="utf-8")


# --- migration -------------------------------------------------------------

def test_v1_migrates_to_v2_without_losing_keys(state):
    _write_v1(state)
    summary = svc.summarize_provider_settings()

    qwen = next(p for p in summary["providers"] if p["provider_id"] == "qwen")
    anthropic = next(p for p in summary["providers"] if p["provider_id"] == "anthropic")
    assert qwen["has_key"] is True
    assert anthropic["has_key"] is True
    # Existing key values remain usable through the service.
    assert svc.get_provider_api_key("qwen") == "sk-qwen-existing-123456"
    assert svc.get_provider_api_key("anthropic") == "sk-ant-existing-7890"


def test_v1_migration_backfills_default_model_and_lanes(state):
    _write_v1(state)
    summary = svc.summarize_provider_settings()

    qwen = next(p for p in summary["providers"] if p["provider_id"] == "qwen")
    assert qwen["default_model"] == cat.default_model_for_provider("qwen")
    assert "text_assist" in qwen["supported_lanes"]

    lanes = {lane["lane"]: lane for lane in summary["lanes"]}
    assert lanes["text_assist"]["provider_id"] == "qwen"
    assert lanes["text_assist"]["model_id"] == "qwen-plus"
    assert lanes["vision"]["provider_id"] == "anthropic"


def test_load_does_not_rewrite_valid_v1_file(state):
    _write_v1(state)
    svc.summarize_provider_settings()
    # A plain read must not clobber the on-disk V1 file (migration is in-memory).
    on_disk = json.loads(state.read_text(encoding="utf-8"))
    assert on_disk["version"] == 1
    assert on_disk["providers"]["qwen"]["api_key"] == "sk-qwen-existing-123456"


# --- summary shape ---------------------------------------------------------

def test_summary_includes_model_catalog_and_lanes(state):
    summary = svc.summarize_provider_settings()
    assert "model_catalog" in summary
    assert "qwen" in summary["model_catalog"]
    assert any(m["model_id"] == "qwen-max" for m in summary["model_catalog"]["qwen"])
    assert {lane["lane"] for lane in summary["lanes"]} == {"text_assist", "vision"}


def test_registry_never_returns_raw_api_key(state):
    _write_v1(state)
    summary = svc.summarize_provider_settings()
    blob = json.dumps(summary)
    assert "sk-qwen-existing-123456" not in blob
    assert "sk-ant-existing-7890" not in blob
    qwen = next(p for p in summary["providers"] if p["provider_id"] == "qwen")
    assert qwen["masked_key"] and qwen["masked_key"] != "sk-qwen-existing-123456"


# --- provider default model ------------------------------------------------

def test_update_provider_default_model_valid(state):
    summary = svc.update_provider_default_model("qwen", "qwen-max")
    qwen = next(p for p in summary["providers"] if p["provider_id"] == "qwen")
    assert qwen["default_model"] == "qwen-max"


def test_update_provider_default_model_rejects_foreign_model(state):
    with pytest.raises(ValueError) as exc:
        svc.update_provider_default_model("qwen", "gpt-4o-mini")
    assert "UNKNOWN_MODEL_FOR_PROVIDER" in str(exc.value)


# --- lane settings ---------------------------------------------------------

def test_update_lane_settings_valid_text_assist(state):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    summary = svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)
    lane = next(l for l in summary["lanes"] if l["lane"] == "text_assist")
    assert lane["provider_id"] == "qwen"
    assert lane["model_id"] == "qwen-max"
    assert lane["execution_enabled"] is True
    assert lane["configured"] is True  # has key + valid model
    assert svc.get_lane_provider("text_assist") == "qwen"
    assert svc.get_lane_model("text_assist") == "qwen-max"
    assert svc.get_lane_api_key("text_assist") == "sk-qwen-live-abcdef"


def test_update_lane_settings_rejects_model_not_supporting_lane(state):
    # qwen-plus is text_assist-only; it may not serve the vision lane.
    with pytest.raises(ValueError) as exc:
        svc.update_lane_settings("vision", "qwen", "qwen-plus")
    assert "MODEL_NOT_SUPPORTED_FOR_LANE" in str(exc.value)


def test_update_lane_settings_rejects_foreign_model(state):
    with pytest.raises(ValueError) as exc:
        svc.update_lane_settings("text_assist", "qwen", "gpt-4o-mini")
    assert "UNKNOWN_MODEL_FOR_PROVIDER" in str(exc.value)


def test_validate_provider_model_for_lane_unknown_lane(state):
    with pytest.raises(ValueError) as exc:
        svc.validate_provider_model_for_lane("qwen", "qwen-plus", "not_a_lane")
    assert "UNSUPPORTED_LANE" in str(exc.value)


def test_anthropic_text_assist_lane_is_selectable(state):
    # V1 had an anthropic key; anthropic supports text_assist in the catalog.
    _write_v1(state)
    summary = svc.update_lane_settings(
        "text_assist", "anthropic", "claude-haiku-4-5-20251001", execution_enabled=True
    )
    lane = next(l for l in summary["lanes"] if l["lane"] == "text_assist")
    assert lane["provider_id"] == "anthropic"
    assert lane["model_id"] == "claude-haiku-4-5-20251001"
    assert lane["configured"] is True
    assert svc.get_lane_model("text_assist") == "claude-haiku-4-5-20251001"


def test_lane_execution_stored_state_when_env_absent(state):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    svc.update_lane_settings("text_assist", "qwen", "qwen-plus", execution_enabled=False)
    assert svc.is_lane_execution_enabled("text_assist") is False
    svc.update_lane_settings("text_assist", "qwen", "qwen-plus", execution_enabled=True)
    assert svc.is_lane_execution_enabled("text_assist") is True
