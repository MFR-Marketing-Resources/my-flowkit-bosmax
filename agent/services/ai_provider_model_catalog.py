"""AI provider / model catalog + lane compatibility (AI Provider Model & Lane Settings V1).

Single source of truth for:
- which models each provider exposes,
- which lanes (`text_assist` / `vision`) each model may serve,
- the safe default model per provider and per lane.

This module is pure data + pure helpers. It holds NO secrets and performs NO
network calls. It is imported by `ai_provider_settings_service` (state + API) and
never sits on the deterministic compiler path.

Honesty note (V1 transport reality):
- `text_assist` executes through `ai_copy_provider_adapter`, which speaks the
  OpenAI-compatible `/chat/completions` shape for qwen/openai/gemini/deepseek AND
  a native Anthropic `/v1/messages` shape for anthropic. Both are wired + tested.
- `vision` is a *selection surface* only in V1: the registry lets an operator pick
  the provider/model, but the actual vision execution lane is owned elsewhere and
  is disabled-by-default. Do not assume enabling the vision toggle here starts a
  new vision call path.
"""
from __future__ import annotations

from typing import Any

LANES: tuple[str, ...] = ("text_assist", "vision")

LANE_LABELS: dict[str, str] = {
    "text_assist": "Text Assist",
    "vision": "Vision",
}

# Lane assignment defaults — used to seed V2 state and to fail-safe when stored
# state is missing a lane. Kept in sync with the catalog `default_for` markers.
LANE_PROVIDER_DEFAULTS: dict[str, str] = {
    "text_assist": "qwen",
    "vision": "anthropic",
}
LANE_MODEL_DEFAULTS: dict[str, str] = {
    "text_assist": "qwen-plus",
    "vision": "claude-sonnet-5",
}

# provider_id -> { label, models: [ { model_id, label, lanes, default_for } ] }
# `lanes`       = lanes this model is allowed to serve.
# `default_for` = lanes for which this model is the catalog default (informational).
PROVIDER_MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic",
        "models": [
            {
                "model_id": "claude-sonnet-5",
                "label": "Claude Sonnet 5",
                "lanes": ["text_assist", "vision"],
                "default_for": ["vision"],
            },
            {
                "model_id": "claude-haiku-4-5-20251001",
                "label": "Claude Haiku 4.5",
                "lanes": ["text_assist", "vision"],
                "default_for": [],
            },
            {
                "model_id": "claude-opus-4-8",
                "label": "Claude Opus 4.8",
                "lanes": ["text_assist", "vision"],
                "default_for": [],
            },
        ],
    },
    "qwen": {
        "label": "Qwen",
        "models": [
            {
                "model_id": "qwen-plus",
                "label": "Qwen Plus",
                "lanes": ["text_assist"],
                "default_for": ["text_assist"],
            },
            {
                "model_id": "qwen-max",
                "label": "Qwen Max",
                "lanes": ["text_assist"],
                "default_for": [],
            },
        ],
    },
    "openai": {
        "label": "OpenAI",
        "models": [
            {
                "model_id": "gpt-4o-mini",
                "label": "GPT-4o mini",
                "lanes": ["text_assist"],
                "default_for": [],
            },
            {
                "model_id": "gpt-4o",
                "label": "GPT-4o",
                "lanes": ["text_assist"],
                "default_for": [],
            },
        ],
    },
    "gemini": {
        "label": "Gemini",
        "models": [
            {
                "model_id": "gemini-2.0-flash",
                "label": "Gemini 2.0 Flash",
                "lanes": ["text_assist"],
                "default_for": [],
            },
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "models": [
            {
                "model_id": "deepseek-chat",
                "label": "DeepSeek Chat",
                "lanes": ["text_assist"],
                "default_for": [],
            },
        ],
    },
}


def is_known_lane(lane: str) -> bool:
    return str(lane or "") in LANES


def models_for_provider(provider_id: str) -> list[dict[str, Any]]:
    entry = PROVIDER_MODEL_CATALOG.get(str(provider_id or "").lower())
    if not entry:
        return []
    return [dict(model) for model in entry.get("models", [])]


def model_ids_for_provider(provider_id: str) -> list[str]:
    return [str(model["model_id"]) for model in models_for_provider(provider_id)]


def get_model_entry(provider_id: str, model_id: str) -> dict[str, Any] | None:
    for model in models_for_provider(provider_id):
        if str(model.get("model_id")) == str(model_id):
            return model
    return None


def is_model_in_provider(provider_id: str, model_id: str) -> bool:
    return get_model_entry(provider_id, model_id) is not None


def model_supports_lane(provider_id: str, model_id: str, lane: str) -> bool:
    model = get_model_entry(provider_id, model_id)
    if not model:
        return False
    return str(lane) in list(model.get("lanes") or [])


def supported_lanes_for_provider(provider_id: str) -> list[str]:
    lanes: list[str] = []
    for model in models_for_provider(provider_id):
        for lane in list(model.get("lanes") or []):
            if lane not in lanes:
                lanes.append(str(lane))
    # keep canonical LANES ordering
    return [lane for lane in LANES if lane in lanes]


def provider_supports_lane(provider_id: str, lane: str) -> bool:
    return lane in supported_lanes_for_provider(provider_id)


def default_model_for_provider(provider_id: str) -> str | None:
    """The provider's pre-selected default model — first catalog entry."""
    models = model_ids_for_provider(provider_id)
    return models[0] if models else None


def lane_default_provider(lane: str) -> str | None:
    return LANE_PROVIDER_DEFAULTS.get(str(lane or ""))


def lane_default_model(lane: str) -> str | None:
    return LANE_MODEL_DEFAULTS.get(str(lane or ""))


def catalog_payload() -> dict[str, list[dict[str, Any]]]:
    """Serializable model catalog keyed by provider_id (models only)."""
    return {
        provider_id: models_for_provider(provider_id)
        for provider_id in PROVIDER_MODEL_CATALOG
    }
