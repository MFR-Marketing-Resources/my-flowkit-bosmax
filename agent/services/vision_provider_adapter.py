"""Vision Lane provider adapter — OpenAI-compatible multimodal transport.

Executes an image-understanding request for the operator-configured `vision`
lane when the provider speaks the OpenAI-compatible `/chat/completions` transport.
That one transport reaches THREE real multimodal providers:

- OpenAI    -> https://api.openai.com/v1
- Gemini    -> https://generativelanguage.googleapis.com/v1beta/openai  (OpenAI-compat)
- Qwen-VL   -> https://dashscope-intl.aliyuncs.com/compatible-mode/v1   (DashScope OpenAI-compat)

All three accept the same image content block:
    {"type": "image_url", "image_url": {"url": "<data-url|https-url>"}}

Anthropic vision is served by the EXISTING product_image_analysis anthropic SDK
path (preserved untouched); it is intentionally NOT re-implemented here so there
is no second, divergent Anthropic code path.

Hard rules (mirrors ai_copy_provider_adapter):
- No hardcoded keys. The key comes from the provider settings store and is NEVER
  logged or returned.
- Fail closed: an unconfigured lane, a missing key/model, or a transport this
  module does not implement raises — it never guesses.
- This module performs image UNDERSTANDING only. It is never on the deterministic
  compiler path and never produces final engine prompts.
"""
from __future__ import annotations

import os
from typing import Any

from agent.services.ai_provider_model_catalog import (
    TRANSPORT_OPENAI_COMPATIBLE,
    get_provider_transport,
)
from agent.services.ai_provider_settings_service import (
    get_lane_api_key,
    get_lane_model,
    get_lane_provider,
    is_lane_execution_enabled,
)

LANE = "vision"

# Transport endpoints (NOT model choices); overridable per deployment. Mirrors the
# text_assist adapter's map so both lanes resolve providers identically.
_BASE_URL_ENV = "PRODUCT_VISION_BASE_URL"
_TIMEOUT_SECONDS = 45.0
_MAX_TOKENS = 500
_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    # Anthropic vision is served by the existing SDK path, not this adapter.
}

ERR_NOT_CONFIGURED = "VISION_PROVIDER_NOT_CONFIGURED"
ERR_UNSUPPORTED_TRANSPORT = "VISION_TRANSPORT_NOT_IMPLEMENTED"
ERR_CALL_FAILED = "VISION_PROVIDER_CALL_FAILED"
ERR_RESPONSE_INVALID = "VISION_PROVIDER_RESPONSE_INVALID"


class VisionProviderNotConfigured(Exception):
    """Raised when the vision lane is not configured/keyed/enabled (default)."""

    code = ERR_NOT_CONFIGURED


class VisionProviderError(Exception):
    """Raised when a configured vision call fails or returns an invalid shape."""

    def __init__(self, code: str, detail: Any = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def is_configured() -> bool:
    """True only when the vision lane has provider+model+key AND execution is on.
    Fail closed everywhere else (no hidden default)."""
    try:
        return (
            bool(get_lane_provider(LANE))
            and bool(get_lane_model(LANE))
            and bool(get_lane_api_key(LANE))
            and bool(is_lane_execution_enabled(LANE))
        )
    except Exception:
        return False


def _resolve_base_url(provider_id: str | None) -> str | None:
    env = str(os.environ.get(_BASE_URL_ENV, "")).strip().rstrip("/")
    if env:
        return env
    return _DEFAULT_BASE_URLS.get(str(provider_id or "").lower())


def build_openai_vision_messages(
    prompt_text: str,
    *,
    title: str | None = None,
    image_data_url: str | None = None,
    image_remote_url: str | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI-compatible multimodal `messages` array: a single user turn
    whose content mixes text with ONE image_url block. Exactly one image source
    (local base64 data URL OR remote https URL) must be provided."""
    image_url = image_data_url or image_remote_url
    if not image_url:
        raise VisionProviderError(ERR_CALL_FAILED, detail="no image source for vision request")
    content: list[dict[str, Any]] = []
    clean_title = str(title or "").strip()
    if clean_title:
        content.append({"type": "text", "text": f"Product title context: {clean_title}"})
    content.append({"type": "text", "text": str(prompt_text)})
    content.append({"type": "image_url", "image_url": {"url": image_url}})
    return [{"role": "user", "content": content}]


def complete_openai_compatible_vision(
    provider_id: str,
    model: str,
    api_key: str,
    base_url: str,
    messages: list[dict[str, Any]],
) -> str:
    """POST {base_url}/chat/completions with a multimodal messages array and return
    the assistant text. Single HTTP seam — mockable in tests."""
    import httpx  # local import — only when actually executing a configured call

    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "temperature": 0,
            "messages": messages,
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionProviderError(ERR_RESPONSE_INVALID, detail="no message content") from exc


def run_vision_completion(
    provider_id: str,
    model: str,
    api_key: str,
    *,
    prompt_text: str,
    title: str | None = None,
    image_data_url: str | None = None,
    image_remote_url: str | None = None,
) -> str:
    """Resolve transport + base URL and execute a vision completion. Only the
    OpenAI-compatible transport is implemented here; anything else fails closed."""
    pid = str(provider_id or "").lower()
    if not api_key or not model:
        raise VisionProviderError(ERR_CALL_FAILED, detail="vision key/model unresolved")
    transport = get_provider_transport(pid)
    if transport != TRANSPORT_OPENAI_COMPATIBLE:
        # Anthropic (or any future transport) is not served by this adapter.
        raise VisionProviderError(ERR_UNSUPPORTED_TRANSPORT, detail=f"{pid}:{transport}")
    base_url = _resolve_base_url(pid)
    if not base_url:
        raise VisionProviderError(ERR_CALL_FAILED, detail=f"no base url for {pid}")
    messages = build_openai_vision_messages(
        prompt_text,
        title=title,
        image_data_url=image_data_url,
        image_remote_url=image_remote_url,
    )
    try:
        return complete_openai_compatible_vision(pid, model, api_key, base_url, messages)
    except VisionProviderError:
        raise
    except Exception as exc:  # network / shape / auth — fail closed, never leak the key
        raise VisionProviderError(ERR_CALL_FAILED, detail=str(exc)) from exc
