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

from agent.services.ai_provider_model_catalog import (
    TRANSPORT_ANTHROPIC_MESSAGES,
    TRANSPORT_OPENAI_COMPATIBLE,
    get_provider_transport,
)
from agent.services.ai_provider_settings_service import (
    get_lane_api_key,
    get_lane_model,
    get_lane_provider,
    is_lane_execution_enabled,
)

LANE = "text_assist"

# The operator's UI-selected lane model is the ONLY model source (with an optional
# deployment env override). There is NO hardcoded model fallback — an unconfigured
# lane resolves to None and the call fails closed. Base URLs below are transport
# endpoints (not model choices) and may be overridden per deployment.
_BASE_URL_ENV = "PRODUCT_TEXT_ASSIST_BASE_URL"
_MODEL_ENV = "PRODUCT_TEXT_ASSIST_MODEL"
_TIMEOUT_SECONDS = 30.0
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 1024
_DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    # Anthropic uses its native /v1/messages transport (NOT OpenAI-compatible).
    "anthropic": "https://api.anthropic.com",
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
    """True only when the text_assist lane has a configured provider+model, a key,
    AND execution is enabled. Fail closed everywhere else (no hidden default)."""
    try:
        return (
            bool(get_lane_api_key(LANE))
            and bool(get_lane_model(LANE))
            and bool(is_lane_execution_enabled(LANE))
        )
    except Exception:
        return False


def provider_status() -> dict[str, Any]:
    provider_id = None
    model_id = None
    execution_enabled = False
    try:
        provider_id = get_lane_provider(LANE)
    except Exception:
        provider_id = None
    try:
        model_id = _resolve_model(provider_id)
    except Exception:
        model_id = None
    try:
        execution_enabled = bool(is_lane_execution_enabled(LANE))
    except Exception:
        execution_enabled = False
    return {
        "lane": LANE,
        "configured": is_configured(),
        "provider_id": provider_id,
        "model_id": model_id,
        "execution_enabled": execution_enabled,
    }


def _resolve_base_url(provider_id: str | None) -> str | None:
    env = str(os.environ.get(_BASE_URL_ENV, "")).strip().rstrip("/")
    if env:
        return env
    return _DEFAULT_BASE_URLS.get(str(provider_id or "").lower())


def _resolve_model(provider_id: str | None) -> str | None:
    # UI-selected lane model is the ONLY source (optional env override). No
    # hardcoded per-provider default — unconfigured resolves to None (fail closed).
    try:
        lane_model = get_lane_model(LANE)
    except Exception:
        lane_model = None
    if lane_model:
        return lane_model
    env = str(os.environ.get(_MODEL_ENV, "")).strip()
    return env or None


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
        "Ground every candidate in the brief. The brief may include product signals "
        "(product_class, sensitivity, product_family, copy_trigger, copy_formula, "
        "silo, claim_gate, claim_risk_level, route_type, strategy). Treat these as "
        "STRATEGY GUIDANCE to shape the angle, tone and buyer psychology — but NEVER "
        "print any signal code or id (e.g. trigger ids, silo/formula codes) in the "
        "copy itself. Honour route_type and the strategy field. "
        "If sensitivity is STEALTH or route_type is STEALTH: this is a "
        "privacy-sensitive product — NEVER name the body part, medical condition, or "
        "intimate/sexual function explicitly; sell through wrapped metaphor, ego / "
        "maruah (masculine pride & dignity) and self-confidence pressure, and "
        "everyday-routine framing; keep every line dialogue-safe. "
        "If claim_risk_level is HIGH, be extra conservative — no health/medical "
        "outcomes and no performance or cure implications of any kind. "
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


def _split_system_and_turns(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """Anthropic /v1/messages takes `system` at the top level and only
    user/assistant turns in `messages`."""
    system_parts: list[str] = []
    turns: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "system":
            if content:
                system_parts.append(content)
        else:
            turns.append({"role": role, "content": content})
    return "\n\n".join(system_parts), turns


def _complete_anthropic(
    messages: list[dict[str, str]], api_key: str, base_url: str, model: str
) -> str:
    """Native Anthropic Messages transport (/v1/messages). Scoped to the
    text_assist lane; disabled by default and exercised only via unit tests."""
    import httpx  # local import — only when actually executing a configured call

    system, turns = _split_system_and_turns(messages)
    response = httpx.post(
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "temperature": 0.5,
            "system": system,
            "messages": turns,
        },
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    blocks = data.get("content") or []
    for block in blocks:
        if isinstance(block, dict) and str(block.get("type") or "") == "text":
            return str(block.get("text") or "")
    raise AICopyProviderError(ERR_RESPONSE_INVALID, detail="no text block in response")


def _complete_openai_compatible(
    messages: list[dict[str, str]], api_key: str, base_url: str, model: str
) -> str:
    """OpenAI-compatible /chat/completions transport (qwen/openai/gemini/deepseek).
    Mirrors the proven product_knowledge_service httpx pattern."""
    import httpx  # local import — only when actually executing a configured call

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


def _complete(messages: list[dict[str, str]]) -> str:
    """Execute a chat completion via the configured text_assist lane. Anthropic
    speaks its native /v1/messages shape; every other provider is OpenAI-compatible.
    Never reached in tests (disabled by default)."""
    api_key = get_lane_api_key(LANE)
    provider_id = str(get_lane_provider(LANE) or "").lower()
    base_url = _resolve_base_url(provider_id)
    model = _resolve_model(provider_id)
    transport = get_provider_transport(provider_id)
    if not api_key or not base_url or not model:
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail="text_assist key/base_url/model unresolved"
        )
    try:
        if transport == TRANSPORT_ANTHROPIC_MESSAGES:
            return _complete_anthropic(messages, api_key, base_url, model)
        if transport == TRANSPORT_OPENAI_COMPATIBLE:
            return _complete_openai_compatible(messages, api_key, base_url, model)
        # Unknown / unimplemented transport — fail closed, never guess.
        raise AICopyProviderError(
            ERR_CALL_FAILED, detail=f"unsupported transport for {provider_id}: {transport}"
        )
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


def complete_json(system: str, user: str) -> dict[str, Any]:
    """Generic structured-JSON call via the configured text_assist lane. Fail-closed
    when the lane is unconfigured (raises AICopyProviderNotConfigured). Reuses the
    SAME provider/key/model/transport as copy — no new secrets, no hardcoded model."""
    if not is_configured():
        raise AICopyProviderNotConfigured(ERR_NOT_CONFIGURED)
    text = _complete([{"role": "system", "content": system}, {"role": "user", "content": user}])
    return _extract_json_object(text)
