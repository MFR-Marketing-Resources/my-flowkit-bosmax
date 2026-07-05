"""Adapter tests: AI Copy Assist honors the UI-selected text_assist lane.

Proves provider_status surfaces the selected model + execution flag, that the
OpenAI-compatible transport sends the lane-selected model, and that the native
Anthropic /v1/messages transport is wired correctly. httpx.post is monkeypatched;
no network, no real key.
"""
import json

import httpx
import pytest

from agent.services import ai_copy_provider_adapter as adapter
from agent.services import ai_provider_settings_service as svc


CANDIDATE_JSON = json.dumps(
    {
        "angle": "Segar",
        "hook": "Nak kulit segar?",
        "subhook": "Rutin ringkas",
        "usp_set": ["a", "b"],
        "cta": "Cuba hari ni",
        "formula_family": "HSO",
        "rationale": "test",
        "risk_notes": [],
    }
)


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "AI_PROVIDER_STATE_DIR", tmp_path)
    monkeypatch.setattr(svc, "AI_PROVIDER_SETTINGS_FILE", tmp_path / "ai-provider-settings.json")
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_MODEL", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_BASE_URL", raising=False)
    for env in svc.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env, raising=False)
    return tmp_path


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_provider_status_reports_selected_model_and_execution(state):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)

    status = adapter.provider_status()
    assert status["provider_id"] == "qwen"
    assert status["model_id"] == "qwen-max"
    assert status["execution_enabled"] is True
    assert status["configured"] is True


def test_openai_compatible_transport_uses_lane_model(state, monkeypatch):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResp({"choices": [{"message": {"content": CANDIDATE_JSON}}]})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = adapter.generate_candidate("brief text")
    assert result["hook"] == "Nak kulit segar?"
    assert captured["json"]["model"] == "qwen-max"  # UI-selected lane model
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-qwen-live-abcdef"


def test_anthropic_transport_wired(state, monkeypatch):
    svc.update_provider_key("anthropic", "sk-ant-live-abcdef123456")
    # Enable the vision lane so anthropic runtime is permitted, then point
    # text_assist at anthropic and enable its execution.
    monkeypatch.setenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", "1")
    svc.update_lane_settings(
        "text_assist", "anthropic", "claude-haiku-4-5-20251001", execution_enabled=True
    )

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResp({"content": [{"type": "text", "text": CANDIDATE_JSON}]})

    monkeypatch.setattr(httpx, "post", fake_post)

    result = adapter.generate_candidate("brief text")
    assert result["hook"] == "Nak kulit segar?"
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant-live-abcdef123456"
    assert captured["headers"]["anthropic-version"]
    assert captured["json"]["model"] == "claude-haiku-4-5-20251001"
    # system prompt is separated from user turns (Anthropic contract)
    assert captured["json"]["system"]
    assert all(turn["role"] != "system" for turn in captured["json"]["messages"])
