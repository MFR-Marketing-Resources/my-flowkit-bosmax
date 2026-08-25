"""Request-contract tests for the OpenAI-compatible adapter (GPT-5.x support).

Closure proof for the GPT-5.6 STRUCTURE adapter defect:
- GPT-5.x models must send ``max_completion_tokens`` (not ``max_tokens``) and must
  omit an explicit temperature, per the official OpenAI Chat Completions contract.
- DeepSeek / Qwen / Gemini / gpt-4o request shapes are unchanged.
- Non-2xx provider error bodies are captured as secret-safe diagnostics.

Every test uses a local HTTP double.  No real provider call is ever made, and no
API key/Authorization value is allowed into any receipt or exception.
"""

import json

import pytest

from agent.services import ai_copy_provider_adapter as adapter
from agent.services import ai_provider_model_catalog as catalog
from agent.services import ai_provider_settings_service as settings

_SENTINEL_KEY = "unit-test-openai-key-DO-NOT-LEAK"


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


class _FakeResponse:
    """Local HTTP double — never calls the network."""

    def __init__(self, payload, *, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("non-JSON body")
        return self._payload


_VALID_ENVELOPE = {
    "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]
}


def _capture_request(monkeypatch, provider, model, *, lane="structure"):
    """Configure a lane (no fallback) and capture the outgoing request payload."""
    settings.update_provider_key(provider, _SENTINEL_KEY)
    settings.update_lane_settings(lane, provider, model, execution_enabled=True)
    seen: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["request_headers"] = headers
        seen["payload"] = json
        return _FakeResponse(_VALID_ENVELOPE)

    monkeypatch.setattr("httpx.post", fake_post)
    parsed, receipt = adapter.complete_json_with_receipt(
        "Return one strict object.", "Use the supplied evidence.", lane=lane
    )
    return seen["payload"], receipt


def _capture_error(monkeypatch, provider, model, *, status_code, error_body, resp_headers=None, lane="structure"):
    settings.update_provider_key(provider, _SENTINEL_KEY)
    settings.update_lane_settings(lane, provider, model, execution_enabled=True)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(error_body, status_code=status_code, headers=resp_headers or {})

    monkeypatch.setattr("httpx.post", fake_post)
    with pytest.raises(adapter.AICopyProviderError) as excinfo:
        adapter.complete_json_with_receipt(
            "Return one strict object.", "Use the supplied evidence.", lane=lane
        )
    return excinfo.value


# --- catalog resolver -----------------------------------------------------

def test_default_request_contract_for_non_gpt5_model(isolated_state):
    contract = catalog.get_model_request_contract("deepseek", "deepseek-v4-flash")
    assert contract["output_token_parameter"] == "max_tokens"
    assert contract["temperature_policy"] == "explicit"
    assert contract["temperature_value"] == 0.5


def test_gpt5_luna_request_contract_resolved(isolated_state):
    contract = catalog.get_model_request_contract("openai", "gpt-5.6-luna")
    assert contract["output_token_parameter"] == "max_completion_tokens"
    assert contract["temperature_policy"] == "omit"


# --- A/B/C GPT-5.6 Luna request shape -------------------------------------

def test_A_gpt5_luna_uses_max_completion_tokens(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "openai", "gpt-5.6-luna")
    assert "max_completion_tokens" in payload
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] <= adapter.OPENAI_COMPATIBLE_JSON_MAX_TOKENS


def test_B_gpt5_luna_omits_temperature(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "openai", "gpt-5.6-luna")
    assert "temperature" not in payload


def test_C_gpt5_luna_structured_fields_only(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "openai", "gpt-5.6-luna")
    assert payload["response_format"] == {"type": "json_object"}
    assert "thinking" not in payload  # DeepSeek-only field never sent to OpenAI
    assert set(payload) <= {"model", "messages", "response_format", "max_completion_tokens"}


# --- D/E DeepSeek unchanged ------------------------------------------------

def test_D_deepseek_flash_request_unchanged(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "deepseek", "deepseek-v4-flash")
    assert payload["temperature"] == 0.5
    assert "max_tokens" in payload
    assert "max_completion_tokens" not in payload
    assert payload["thinking"] == {"type": "disabled"}


def test_E_deepseek_pro_request_unchanged(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "deepseek", "deepseek-v4-pro")
    assert payload["temperature"] == 0.5
    assert "max_tokens" in payload
    assert "max_completion_tokens" not in payload
    assert payload["thinking"] == {"type": "disabled"}


# --- F gpt-4o unchanged ----------------------------------------------------

def test_F_gpt4o_request_unchanged(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "openai", "gpt-4o")
    assert payload["temperature"] == 0.5
    assert "max_tokens" in payload
    assert "max_completion_tokens" not in payload
    assert "thinking" not in payload


# --- G/H Qwen & Gemini unchanged (no JSON-object mode → no output-token param)

def test_G_qwen_request_unchanged(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "qwen", "qwen-plus")
    assert payload["temperature"] == 0.5
    assert "max_completion_tokens" not in payload
    assert "response_format" not in payload


def test_H_gemini_request_unchanged(isolated_state, monkeypatch):
    payload, _ = _capture_request(monkeypatch, "gemini", "gemini-2.0-flash")
    assert payload["temperature"] == 0.5
    assert "max_completion_tokens" not in payload
    assert "response_format" not in payload


# --- I/J non-2xx provider diagnostics -------------------------------------

def test_I_http_400_body_captured_as_safe_diagnostics(isolated_state, monkeypatch):
    err = _capture_error(
        monkeypatch,
        "openai",
        "gpt-5.6-luna",
        status_code=400,
        error_body={
            "error": {
                "type": "invalid_request_error",
                "code": "unsupported_parameter",
                "message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.",
            }
        },
        resp_headers={"x-request-id": "req_abc123"},
    )
    assert err.http_status == 400
    receipt = err.provider_receipt
    assert receipt["http_status"] == 400
    assert receipt["diagnostic_category"] == "PROVIDER_HTTP_ERROR"
    md = receipt["diagnostic_metadata"]
    assert md["provider_error_type"] == "invalid_request_error"
    assert md["provider_error_code"] == "unsupported_parameter"
    assert "max_completion_tokens" in md["provider_error_message"]
    assert md["provider_request_id"] == "req_abc123"


def test_J_http_429_body_captured_as_safe_diagnostics(isolated_state, monkeypatch):
    err = _capture_error(
        monkeypatch,
        "openai",
        "gpt-5.6-luna",
        status_code=429,
        error_body={
            "error": {
                "type": "insufficient_quota",
                "code": "insufficient_quota",
                "message": "You exceeded your current quota, please check your plan and billing details.",
            }
        },
        resp_headers={"x-request-id": "req_429xyz"},
    )
    assert err.http_status == 429
    md = err.provider_receipt["diagnostic_metadata"]
    assert md["provider_error_type"] == "insufficient_quota"
    assert md["provider_error_code"] == "insufficient_quota"
    assert md["provider_request_id"] == "req_429xyz"


# --- K no credential ever surfaces ----------------------------------------

def test_K_api_key_never_in_receipt_or_exception(isolated_state, monkeypatch):
    # success receipt
    _, receipt = _capture_request(monkeypatch, "openai", "gpt-5.6-luna")
    assert _SENTINEL_KEY not in json.dumps(receipt)
    # error receipt + exception surfaces
    err = _capture_error(
        monkeypatch,
        "openai",
        "gpt-5.6-luna",
        status_code=400,
        error_body={"error": {"type": "invalid_request_error", "code": "bad", "message": "nope"}},
        resp_headers={"x-request-id": "req_1"},
    )
    assert _SENTINEL_KEY not in json.dumps(err.provider_receipt)
    assert _SENTINEL_KEY not in str(err)
    assert _SENTINEL_KEY not in repr(err)


def test_K_sanitizer_scrubs_accidental_key_in_body(isolated_state, monkeypatch):
    # Even if a provider error body echoed a bearer/sk- token, diagnostics scrub it.
    err = _capture_error(
        monkeypatch,
        "openai",
        "gpt-5.6-luna",
        status_code=400,
        error_body={"error": {"type": "invalid_request_error", "code": "bad", "message": "leaked sk-abcdef0123456789 and Bearer sk-zzzzzzzzzzzz"}},
    )
    msg = err.provider_receipt["diagnostic_metadata"]["provider_error_message"]
    assert "sk-abcdef0123456789" not in msg
    assert "[REDACTED]" in msg
