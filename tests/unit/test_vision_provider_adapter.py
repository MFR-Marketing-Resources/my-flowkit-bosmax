"""Unit tests for the multi-provider Vision Lane adapter (OpenAI-compatible path).

Proves provider-specific payload format (image_url content block), per-provider
base-URL resolution, fail-closed behavior on unimplemented transports / missing
config, and that the raw API key never appears in the returned content.
"""
import httpx
import pytest

from agent.services import ai_provider_model_catalog as cat
from agent.services import vision_provider_adapter as adapter


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_DIR", tmp_path)
    monkeypatch.setattr(cat, "AI_MODEL_CATALOG_FILE", tmp_path / "ai-model-catalog.json")
    monkeypatch.delenv("PRODUCT_VISION_BASE_URL", raising=False)
    return tmp_path


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _capture_httpx(monkeypatch):
    """Patch httpx.post to capture the outbound request and return a canned reply."""
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["json"] = json or {}
        captured["timeout"] = timeout
        return _FakeResponse(
            {"choices": [{"message": {"content": '{"detected_package": "bottle"}'}}]}
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    return captured


def test_build_messages_local_image_is_base64_data_url():
    messages = adapter.build_openai_vision_messages(
        "RETURN JSON",
        title="Sabun Dobi",
        image_data_url="data:image/jpeg;base64,QUJD",
    )
    assert messages[0]["role"] == "user"
    content = messages[0]["content"]
    image_blocks = [b for b in content if b["type"] == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"
    assert any(b["type"] == "text" and "Sabun Dobi" in b["text"] for b in content)
    assert any(b["type"] == "text" and "RETURN JSON" in b["text"] for b in content)


def test_build_messages_remote_url_passthrough():
    messages = adapter.build_openai_vision_messages(
        "RETURN JSON", image_remote_url="https://example.com/p.jpg"
    )
    block = next(b for b in messages[0]["content"] if b["type"] == "image_url")
    assert block["image_url"]["url"] == "https://example.com/p.jpg"


def test_build_messages_without_image_fails_closed():
    with pytest.raises(adapter.VisionProviderError):
        adapter.build_openai_vision_messages("prompt")


@pytest.mark.parametrize(
    "provider,expected_host",
    [
        ("openai", "api.openai.com"),
        ("gemini", "generativelanguage.googleapis.com"),
        ("qwen", "dashscope-intl.aliyuncs.com"),
    ],
)
def test_openai_compatible_vision_sends_image_payload_per_provider(
    catalog, monkeypatch, provider, expected_host
):
    captured = _capture_httpx(monkeypatch)
    out = adapter.run_vision_completion(
        provider,
        "some-vision-model",
        "sk-secret-key-do-not-leak",
        prompt_text="RETURN JSON",
        title="Widget",
        image_data_url="data:image/png;base64,QUJD",
    )
    # Correct provider endpoint + chat/completions transport.
    assert expected_host in captured["url"]
    assert captured["url"].endswith("/chat/completions")
    # Correct multimodal payload: model + an image_url content block.
    body = captured["json"]
    assert body["model"] == "some-vision-model"
    content = body["messages"][0]["content"]
    assert any(b.get("type") == "image_url" for b in content)
    # Key travels only in the Authorization header, never in the returned content.
    assert captured["headers"]["Authorization"] == "Bearer sk-secret-key-do-not-leak"
    assert "sk-secret-key-do-not-leak" not in out


def test_anthropic_transport_not_served_by_this_adapter(catalog, monkeypatch):
    # Anthropic vision is served by the existing SDK path; this adapter fails closed.
    _capture_httpx(monkeypatch)
    with pytest.raises(adapter.VisionProviderError) as exc:
        adapter.run_vision_completion(
            "anthropic",
            "claude-sonnet-5",
            "sk-anthropic",
            prompt_text="RETURN JSON",
            image_remote_url="https://example.com/p.jpg",
        )
    assert exc.value.code == adapter.ERR_UNSUPPORTED_TRANSPORT


def test_missing_key_or_model_fails_closed(catalog):
    with pytest.raises(adapter.VisionProviderError):
        adapter.run_vision_completion(
            "openai", "gpt-4o", "", prompt_text="x", image_remote_url="https://e/p.jpg"
        )
    with pytest.raises(adapter.VisionProviderError):
        adapter.run_vision_completion(
            "openai", "", "sk-k", prompt_text="x", image_remote_url="https://e/p.jpg"
        )


def test_is_configured_false_when_lane_unconfigured(catalog, monkeypatch):
    monkeypatch.setattr(adapter, "get_lane_provider", lambda lane: None)
    assert adapter.is_configured() is False
