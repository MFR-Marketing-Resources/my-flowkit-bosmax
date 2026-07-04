"""AI Copy Assist — provider adapter boundary (candidate copy only).

Thin, disabled-by-default boundary between the AI Copy Assist service and a text
LLM provider. It REUSES the existing on-main lane provider abstraction
(`ai_provider_settings_service`, the "text_assist" lane) for enablement + key +
provider selection — no new secrets, no new settings UI.

Hard rules:
- Disabled by default: with no configured/enabled text_assist lane key, every
  call fails closed with `AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED`.
- This adapter ONLY produces candidate copy JSON. It never generates final
  engine-facing prompts and is never on the deterministic compiler path.
- No hardcoded keys. The key is read from the existing provider settings store.
- `generate_candidate` is the single mockable seam for tests.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

from agent.services.ai_provider_settings_service import (
    get_lane_api_key,
    get_lane_provider,
    is_lane_execution_enabled,
)

LANE = "text_assist"

# Env-overridable transport config (never a hardcoded key). Base URL / model may
# be supplied per deployment; a small default map covers common OpenAI-compatible
# providers. If unresolved when a key IS present, the call fails closed.
_BASE_URL_ENV = "PRODUCT_TEXT_ASSIST_BASE_URL"
_MODEL_ENV = "PRODUCT_TEXT_ASSIST_MODEL"
_TIMEOUT_SECONDS = 30.0
_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}
_DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
    "qwen": "qwen-plus",
    "gemini": "gemini-2.0-flash",
}

ERR_NOT_CONFIGURED = "AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED"
ERR_RESPONSE_INVALID = "AI_COPY_ASSIST_RESPONSE_INVALID"
ERR_CALL_FAILED = "AI_COPY_ASSIST_CALL_FAILED"


class AICopyProviderNotConfigured(Exception):
    """Raised when the text_assist lane is not configured/enabled (default)."""

    code = ERR_NOT_CONFIGURED


class AICopyProviderError(Exception):
    """Raised when a configured provider call fails or returns invalid JSON."""

    def __init__(self, code: str, detail: Any = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def is_configured() -> bool:
    """True only when the text_assist lane has a key AND execution is enabled."""
    try:
        return bool(get_lane_api_key(LANE)) and bool(is_lane_execution_enabled(LANE))
    except Exception:
        return False


def provider_status() -> dict[str, Any]:
    provider_id = None
    try:
        provider_id = get_lane_provider(LANE)
    except Exception:
        provider_id = None
    return {
        "lane": LANE,
        "configured": is_configured(),
        "provider_id": provider_id,
    }


def _resolve_base_url(provider_id: str | None) -> str | None:
    env = str(os.environ.get(_BASE_URL_ENV, "")).strip().rstrip("/")
    if env:
        return env
    return _DEFAULT_BASE_URLS.get(str(provider_id or "").lower())


def _resolve_model(provider_id: str | None) -> str | None:
    env = str(os.environ.get(_MODEL_ENV, "")).strip()
    if env:
        return env
    return _DEFAULT_MODELS.get(str(provider_id or "").lower())


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model message (tolerating code fences)."""
    raw = str(text or "").strip()
    if not raw:
        raise AICopyProviderError(ERR_RESPONSE_INVALID, detail="empty response")
    fenced = re.search(r"\{.*\}", raw, re.DOTALL)
    candidate = fenced.group(0) if fenced else raw
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError) as exc:
        raise AICopyProviderError(ERR_RESPONSE_INVALID, detail=str(exc)) from exc
    if not isinstance(parsed, dict):
        raise AICopyProviderError(ERR_RESPONSE_INVALID, detail="not a JSON object")
    return parsed


def build_messages(brief: str) -> list[dict[str, str]]:
    """System + user messages. The system prompt bans unsafe claims, metadata
    leakage, and any final/engine prompt output — candidates only."""
    system = (
        "You are a Malay/English direct-response COPY CANDIDATE generator for a "
        "commercial UGC pipeline. You produce ONLY draft marketing copy candidates "
        "for human review. You NEVER produce final video prompts, NEVER produce "
        "9-section or engine-specific output, and NEVER include internal metadata "
        "(ids, provenance, system names). "
        "Hard safety rules — DO NOT write medical/cure/treat/heal claims, guaranteed "
        "results, universal-safety ('no side effects', 'safe for everyone'), "
        "before/after implications, or clinical-authority claims. "
        "Return STRICT JSON ONLY, no markdown, with keys: angle, hook, subhook, "
        "usp_set (array of up to 3 strings), cta, formula_family, rationale, "
        "risk_notes (array of strings)."
    )
    user = (
        "Generate ONE safe copy candidate as JSON for this brief. "
        "Ground it in the product truth; invent no facts.\n\n" + str(brief)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _complete(messages: list[dict[str, str]]) -> str:
    """Execute an OpenAI-compatible chat completion via the configured lane.
    Mirrors the proven product_knowledge_service httpx pattern. Never reached in
    tests (disabled by default)."""
    import httpx  # local import — only when actually executing a configured call

    api_key = get_lane_api_key(LANE)
    provider_id = get_lane_provider(LANE)
    base_url = _resolve_base_url(provider_id)
    model = _resolve_model(provider_id)
    if not base_url or not model:
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail="text_assist base_url/model unresolved"
        )
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "temperature": 0.5, "messages": messages},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])
    except AICopyProviderError:
        raise
    except Exception as exc:  # network / shape / auth — fail closed
        raise AICopyProviderError(ERR_CALL_FAILED, detail=str(exc)) from exc


def generate_candidate(brief: str) -> dict[str, Any]:
    """Single mockable seam. Fail closed when unconfigured; otherwise call the
    provider and return the parsed candidate JSON dict."""
    if not is_configured():
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    message_text = _complete(build_messages(brief))
    return _extract_json_object(message_text)
