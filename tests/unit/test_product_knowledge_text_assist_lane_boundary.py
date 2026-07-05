"""Provider-boundary tests for Product Knowledge Qwen USP extraction.

Regression guard for the PR #202 audit blocker: `_extract_qwen_usp_suggestions`
posts to the Qwen/DashScope endpoint, so it must NEVER read or send a non-Qwen
`text_assist` lane key. It runs only when the lane provider is qwen; for any
non-Qwen lane provider it fails closed (returns [] and never calls httpx.post).
"""
import httpx
import pytest

from agent.models.product_knowledge import ProductKnowledgeCompleteRequest
from agent.services import product_knowledge_service as pks
from agent.services import ai_provider_model_catalog as cat
from agent.services import ai_provider_settings_service as svc


@pytest.fixture
def lane_state(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "AI_PROVIDER_STATE_DIR", tmp_path)
    monkeypatch.setattr(svc, "AI_PROVIDER_SETTINGS_FILE", tmp_path / "ai-provider-settings.json")
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_FILE", tmp_path / "ai-model-catalog.json")
    monkeypatch.delenv("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCT_TEXT_ASSIST_MODEL", raising=False)
    monkeypatch.delenv("QWEN_TEXT_MODEL", raising=False)
    for env in svc.PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env, raising=False)
    return tmp_path


def _req() -> ProductKnowledgeCompleteRequest:
    return ProductKnowledgeCompleteRequest(
        product_name="Serum X",
        paste_anything_about_product="ringan dan segar untuk rutin harian kulit",
        source_lane="OWNED",
    )


class _QwenResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": '{"usp_list": ["Ringan", "Segar"]}'}}]}


def test_qwen_lane_calls_qwen_endpoint_with_qwen_key_and_selected_model(lane_state, monkeypatch):
    svc.update_provider_key("qwen", "sk-qwen-REAL-123456")
    svc.update_lane_settings("text_assist", "qwen", "qwen-max", execution_enabled=True)

    calls: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _QwenResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = pks._extract_qwen_usp_suggestions(_req(), {})
    assert result == ["Ringan", "Segar"]
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/chat/completions")
    assert "dashscope" in calls[0]["url"]
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-qwen-REAL-123456"
    assert calls[0]["json"]["model"] == "qwen-max"  # operator-selected qwen model


def test_anthropic_lane_skips_and_never_posts(lane_state, monkeypatch):
    # A non-Qwen key IS stored and the lane points at it — the guard must skip
    # BEFORE any key is read, so the anthropic key can never reach the qwen endpoint.
    svc.update_provider_key("qwen", "sk-qwen-REAL-123456")
    svc.update_provider_key("anthropic", "sk-ant-SECRET-7890")
    svc.update_lane_settings(
        "text_assist", "anthropic", "claude-haiku-4-5-20251001", execution_enabled=True
    )

    def boom(*args, **kwargs):
        raise AssertionError("httpx.post must not be called for a non-qwen text_assist lane")

    monkeypatch.setattr(httpx, "post", boom)

    assert pks._extract_qwen_usp_suggestions(_req(), {}) == []


@pytest.mark.parametrize(
    "provider,model",
    [
        ("openai", "gpt-4o-mini"),
        ("gemini", "gemini-2.0-flash"),
        ("deepseek", "deepseek-chat"),
    ],
)
def test_other_non_qwen_lanes_skip_and_never_post(lane_state, monkeypatch, provider, model):
    svc.update_provider_key("qwen", "sk-qwen-REAL-123456")
    svc.update_provider_key(provider, f"sk-{provider}-SECRET-abcdef")
    svc.update_lane_settings("text_assist", provider, model, execution_enabled=True)

    def boom(*args, **kwargs):
        raise AssertionError(f"httpx.post must not be called for {provider} text_assist lane")

    monkeypatch.setattr(httpx, "post", boom)

    assert pks._extract_qwen_usp_suggestions(_req(), {}) == []


def test_no_non_qwen_key_ever_reaches_qwen_request(lane_state, monkeypatch):
    # Capture every outbound request; assert none carries a non-qwen secret.
    svc.update_provider_key("qwen", "sk-qwen-REAL-123456")
    svc.update_provider_key("anthropic", "sk-ant-SECRET-7890")
    svc.update_provider_key("openai", "sk-openai-SECRET-abcdef")

    captured: list[dict] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "headers": headers or {}})
        return _QwenResp()

    monkeypatch.setattr(httpx, "post", fake_post)

    for provider, model in [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-4o-mini"),
    ]:
        svc.update_lane_settings("text_assist", provider, model, execution_enabled=True)
        pks._extract_qwen_usp_suggestions(_req(), {})

    # Non-qwen lanes never post at all.
    assert captured == []

    # Qwen lane posts, and only the qwen key is ever present.
    svc.update_lane_settings("text_assist", "qwen", "qwen-plus", execution_enabled=True)
    pks._extract_qwen_usp_suggestions(_req(), {})
    assert len(captured) == 1
    auth = captured[0]["headers"].get("Authorization", "")
    assert auth == "Bearer sk-qwen-REAL-123456"
    assert "SECRET" not in auth
