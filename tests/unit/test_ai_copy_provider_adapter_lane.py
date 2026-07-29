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
from agent.services import ai_provider_model_catalog as cat
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
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_FILE", tmp_path / "ai-model-catalog.json")
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_MODEL", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_BASE_URL", raising=False)
    for env in svc.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env, raising=False)
    return tmp_path


class _FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_migrated_seed_default_with_key_fails_closed(state):
    # A V2 state with a qwen key + the OLD seeded text_assist default migrates to
    # NOT_CONFIGURED, so AI Copy Assist must fail closed — never silently use
    # qwen/qwen-plus.
    (state / "ai-provider-settings.json").write_text(
        json.dumps(
            {
                "version": 2,
                "active_provider": None,
                "providers": {
                    "qwen": {"api_key": "sk-qwen-existing-abcdef", "updated_at": None, "activated_at": None},
                },
                "lanes": {
                    "text_assist": {"provider_id": "qwen", "model_id": "qwen-plus", "execution_enabled": True},
                },
            }
        ),
        encoding="utf-8",
    )
    assert adapter.is_configured() is False
    with pytest.raises(adapter.AICopyProviderNotConfigured):
        adapter.generate_candidate("brief text")


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
    count_before = adapter.provider_call_receipt()[
        "request_count_since_process_start"
    ]

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResp(
            {
                "choices": [
                    {
                        "message": {"content": CANDIDATE_JSON},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 41,
                    "completion_tokens": 23,
                    "total_tokens": 64,
                },
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = adapter.generate_candidate("brief text")
    assert result["hook"] == "Nak kulit segar?"
    assert captured["json"]["model"] == "qwen-max"  # UI-selected lane model
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-qwen-live-abcdef"
    receipt = adapter.provider_call_receipt()
    assert receipt["request_count_since_process_start"] == count_before + 1
    assert receipt["last_call"] == {
        "call_id": count_before + 1,
        "lane": "text_assist",
        "provider_id": "qwen",
        "model_id": "qwen-max",
        "transport": cat.TRANSPORT_OPENAI_COMPATIBLE,
        "started_at": receipt["last_call"]["started_at"],
        "completed_at": receipt["last_call"]["completed_at"],
        "response_status": "SUCCEEDED",
        "http_status": 200,
        "finish_reason": "stop",
        "structured_output_requested": False,
        "json_output_mode": None,
        "json_parse_status": None,
        "diagnostic_category": None,
        "diagnostic_metadata": {},
        "usage": {
            "prompt_tokens": 41,
            "completion_tokens": 23,
            "total_tokens": 64,
        },
    }
    serialized_receipt = json.dumps(receipt)
    assert "sk-qwen-live-abcdef" not in serialized_receipt
    assert "brief text" not in serialized_receipt


def test_complete_json_uses_deepseek_json_output_and_records_safe_receipt(
    state, monkeypatch
):
    svc.update_provider_key("deepseek", "sk-deepseek-live-abcdef")
    svc.update_lane_settings(
        "text_assist",
        "deepseek",
        "deepseek-v4-pro",
        execution_enabled=True,
    )
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResp(
            {
                "choices": [
                    {
                        "message": {"content": '{"safe": true}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 17,
                    "completion_tokens": 5,
                    "total_tokens": 22,
                },
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = adapter.complete_json(
        "Return a strict JSON object.",
        "Use only supplied review evidence.",
    )

    assert result == {"safe": True}
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == "deepseek-v4-pro"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["max_tokens"] == 4096
    receipt = adapter.provider_call_receipt()["last_call"]
    assert receipt["response_status"] == "SUCCEEDED"
    assert receipt["http_status"] == 200
    assert receipt["finish_reason"] == "stop"
    assert receipt["structured_output_requested"] is True
    assert receipt["json_output_mode"] == "json_object"
    assert receipt["json_parse_status"] == "VALID"
    assert receipt["diagnostic_category"] is None
    serialized_receipt = json.dumps(receipt)
    assert "sk-deepseek-live-abcdef" not in serialized_receipt
    assert "supplied review evidence" not in serialized_receipt
    assert '{"safe": true}' not in serialized_receipt


def test_complete_json_does_not_apply_json_mode_to_unlisted_provider(
    state, monkeypatch
):
    svc.update_provider_key("qwen", "sk-qwen-live-abcdef")
    svc.update_lane_settings(
        "text_assist",
        "qwen",
        "qwen-max",
        execution_enabled=True,
    )
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _FakeResp(
            {
                "choices": [
                    {
                        "message": {"content": '{"safe": true}'},
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    assert adapter.complete_json("Return JSON.", "Safe input.") == {"safe": True}
    assert "response_format" not in captured["json"]
    assert "max_tokens" not in captured["json"]
    receipt = adapter.provider_call_receipt()["last_call"]
    assert receipt["structured_output_requested"] is True
    assert receipt["json_output_mode"] is None


@pytest.mark.parametrize(
    ("content", "finish_reason", "category"),
    [
        ("", "stop", adapter.DIAGNOSTIC_EMPTY_CONTENT),
        ("{", "stop", adapter.DIAGNOSTIC_JSON_PARSE_FAILED),
        ("[]", "stop", adapter.DIAGNOSTIC_NON_OBJECT_JSON),
        ('{"safe": true}', "length", adapter.DIAGNOSTIC_TRUNCATED_RESPONSE),
        (
            'prefix {"safe": true} suffix',
            "stop",
            adapter.DIAGNOSTIC_JSON_PARSE_FAILED,
        ),
    ],
)
def test_json_parser_fails_closed_with_exact_category(
    content, finish_reason, category
):
    with pytest.raises(adapter.AICopyProviderError) as caught:
        adapter._extract_json_object(content, finish_reason=finish_reason)
    assert caught.value.code == adapter.ERR_RESPONSE_INVALID
    assert caught.value.diagnostic_category == category


def test_json_parser_accepts_lossless_full_message_code_fence():
    assert adapter._extract_json_object(
        '```json\n{"safe": true}\n```',
        finish_reason="stop",
    ) == {"safe": True}


def test_provider_http_200_invalid_content_is_diagnosed_without_content(
    state, monkeypatch
):
    svc.update_provider_key("deepseek", "sk-deepseek-live-abcdef")
    svc.update_lane_settings(
        "text_assist",
        "deepseek",
        "deepseek-v4-pro",
        execution_enabled=True,
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResp(
            {
                "choices": [
                    {"message": {"content": ""}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 12},
            }
        ),
    )

    with pytest.raises(adapter.AICopyProviderError) as caught:
        adapter.complete_json("Return JSON.", "Private source text.")

    assert caught.value.diagnostic_category == adapter.DIAGNOSTIC_EMPTY_CONTENT
    receipt = adapter.provider_call_receipt()["last_call"]
    assert receipt["response_status"] == "SUCCEEDED"
    assert receipt["http_status"] == 200
    assert receipt["json_parse_status"] == "INVALID"
    assert receipt["diagnostic_category"] == adapter.DIAGNOSTIC_EMPTY_CONTENT
    serialized_receipt = json.dumps(receipt)
    assert "Private source text" not in serialized_receipt
    assert "sk-deepseek-live-abcdef" not in serialized_receipt


def test_provider_http_200_missing_message_has_extraction_diagnostic(
    state, monkeypatch
):
    svc.update_provider_key("deepseek", "sk-deepseek-live-abcdef")
    svc.update_lane_settings(
        "text_assist",
        "deepseek",
        "deepseek-v4-pro",
        execution_enabled=True,
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResp(
            {
                "choices": [{"finish_reason": "stop"}],
                "usage": {"total_tokens": 8},
            }
        ),
    )

    with pytest.raises(adapter.AICopyProviderError) as caught:
        adapter.complete_json("Return JSON.", "Safe input.")

    assert (
        caught.value.diagnostic_category
        == adapter.DIAGNOSTIC_CONTENT_EXTRACTION_FAILED
    )
    receipt = adapter.provider_call_receipt()["last_call"]
    assert receipt["response_status"] == "INVALID_RESPONSE"
    assert receipt["http_status"] == 200
    assert (
        receipt["diagnostic_category"]
        == adapter.DIAGNOSTIC_CONTENT_EXTRACTION_FAILED
    )


def test_provider_http_failure_is_fail_closed_and_receipted(state, monkeypatch):
    svc.update_provider_key("deepseek", "sk-deepseek-live-abcdef")
    svc.update_lane_settings(
        "text_assist",
        "deepseek",
        "deepseek-v4-pro",
        execution_enabled=True,
    )

    def fail_post(*args, **kwargs):
        response = httpx.Response(
            503,
            request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
        )
        raise httpx.HTTPStatusError(
            "service unavailable",
            request=response.request,
            response=response,
        )

    monkeypatch.setattr(httpx, "post", fail_post)

    with pytest.raises(adapter.AICopyProviderError) as caught:
        adapter.complete_json("Return JSON.", "Safe input.")

    assert caught.value.code == adapter.ERR_CALL_FAILED
    receipt = adapter.provider_call_receipt()["last_call"]
    assert receipt["response_status"] == "FAILED"
    assert receipt["http_status"] == 503
    assert receipt["json_parse_status"] is None


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
