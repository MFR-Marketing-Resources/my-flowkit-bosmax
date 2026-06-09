from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from agent.config import BASE_DIR

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]

PROVIDER_IDS: tuple[ProviderId, ...] = (
    "qwen",
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
)

PROVIDER_LABELS: dict[ProviderId, str] = {
    "qwen": "Qwen",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
}

PROVIDER_ENV_VARS: dict[ProviderId, str] = {
    "qwen": "DASHSCOPE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

PROVIDER_SCOPES: dict[ProviderId, str] = {
    "qwen": "REGISTRY_ONLY",
    "anthropic": "LIVE_NOW",
    "openai": "REGISTRY_ONLY",
    "gemini": "REGISTRY_ONLY",
    "deepseek": "REGISTRY_ONLY",
}

PROVIDER_CAPABILITIES: dict[ProviderId, list[str]] = {
    "qwen": ["Stored for future BOSMAX module wiring"],
    "anthropic": ["Video review SDK", "Product image vision provider"],
    "openai": ["Stored for future BOSMAX module wiring"],
    "gemini": ["Stored for future BOSMAX module wiring"],
    "deepseek": ["Stored for future BOSMAX module wiring"],
}

AI_PROVIDER_STATE_DIR = BASE_DIR / ".local-agent"
AI_PROVIDER_SETTINGS_FILE = AI_PROVIDER_STATE_DIR / "ai-provider-settings.json"
AI_PROVIDER_STATE_VERSION = 1
ACTIVE_PROVIDER_ENV_VAR = "BOSMAX_ACTIVE_AI_PROVIDER"
VISION_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_VISION_PROVIDER"
TEXT_ASSIST_PROVIDER_ENV_VAR = "PRODUCT_TEXT_ASSIST_PROVIDER"
LANE_EXECUTION_ENV_VARS: dict[str, str] = {
    "vision": "BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED",
    "text_assist": "BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED",
}
LANE_EXECUTION_DEFAULTS: dict[str, bool] = {
    "vision": False,
    "text_assist": True,
}

# Lane-level defaults: each lane has its own provider assignment, independent of
# which provider the user has set as "active". This allows vision (Anthropic) and
# text-assist (Qwen) to coexist without competing for a single global active slot.
PROVIDER_LANE_DEFAULTS: dict[str, str] = {
    "vision": "anthropic",
    "text_assist": "qwen",
}


def _is_provider_runtime_enabled(provider_id: str) -> bool:
    normalized = str(provider_id or "").strip().lower()
    if normalized == "anthropic":
        return is_lane_execution_enabled("vision")
    return True


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _default_payload() -> dict:
    return {
        "version": AI_PROVIDER_STATE_VERSION,
        "active_provider": None,
        "providers": {
            provider_id: {
                "api_key": "",
                "updated_at": None,
                "activated_at": None,
            }
            for provider_id in PROVIDER_IDS
        },
    }


def _normalize_provider_id(value: str) -> ProviderId:
    normalized = str(value or "").strip().lower()
    if normalized not in PROVIDER_IDS:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{value}")
    return normalized  # type: ignore[return-value]


def _mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"


def _ensure_state_dir() -> None:
    AI_PROVIDER_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_payload() -> dict:
    _ensure_state_dir()
    default_payload = _default_payload()
    if not AI_PROVIDER_SETTINGS_FILE.exists():
        AI_PROVIDER_SETTINGS_FILE.write_text(
            json.dumps(default_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return default_payload

    try:
        raw = json.loads(AI_PROVIDER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        AI_PROVIDER_SETTINGS_FILE.write_text(
            json.dumps(default_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return default_payload

    payload = {
        "version": raw.get("version", AI_PROVIDER_STATE_VERSION),
        "active_provider": raw.get("active_provider"),
        "providers": {},
    }
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    for provider_id in PROVIDER_IDS:
        entry = raw_providers.get(provider_id) if isinstance(raw_providers.get(provider_id), dict) else {}
        payload["providers"][provider_id] = {
            "api_key": str(entry.get("api_key") or ""),
            "updated_at": entry.get("updated_at"),
            "activated_at": entry.get("activated_at"),
        }

    if payload["active_provider"] not in PROVIDER_IDS:
        payload["active_provider"] = None
    return payload


def _save_payload(payload: dict) -> None:
    _ensure_state_dir()
    AI_PROVIDER_SETTINGS_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def get_provider_api_key(provider_id: str) -> str:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    stored_key = str(payload["providers"][normalized].get("api_key") or "").strip()
    if stored_key:
        return stored_key
    return str(os.environ.get(PROVIDER_ENV_VARS[normalized], "")).strip()


def get_lane_provider(lane: str) -> str | None:
    """Return the provider ID assigned to a given lane, or None if lane is unknown."""
    return PROVIDER_LANE_DEFAULTS.get(lane)


def get_lane_api_key(lane: str) -> str | None:
    """Return the stored API key for the provider assigned to a given lane.
    Fail-closed: returns None if lane unknown, provider unknown, or key not stored."""
    provider_id = get_lane_provider(lane)
    if not provider_id:
        return None
    try:
        key = get_provider_api_key(provider_id)
        return key or None
    except (ValueError, Exception):
        return None


def is_lane_execution_enabled(lane: str) -> bool:
    env_var = LANE_EXECUTION_ENV_VARS.get(lane)
    if not env_var:
        return False
    return _env_bool(env_var, LANE_EXECUTION_DEFAULTS.get(lane, False))


def get_active_provider_id() -> ProviderId | None:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    if active_provider in PROVIDER_IDS:
        return active_provider  # type: ignore[return-value]
    env_active = str(os.environ.get(ACTIVE_PROVIDER_ENV_VAR, "")).strip().lower()
    if env_active in PROVIDER_IDS:
        return env_active  # type: ignore[return-value]
    return None


def apply_runtime_provider_environment(payload: dict | None = None) -> None:
    resolved = payload or _load_payload()
    active_provider = resolved.get("active_provider")

    for provider_id in PROVIDER_IDS:
        key = str(resolved["providers"][provider_id].get("api_key") or "").strip()
        env_var = PROVIDER_ENV_VARS[provider_id]
        if key and _is_provider_runtime_enabled(provider_id):
            os.environ[env_var] = key
        else:
            os.environ.pop(env_var, None)

    if active_provider in PROVIDER_IDS:
        os.environ[ACTIVE_PROVIDER_ENV_VAR] = active_provider
    else:
        os.environ.pop(ACTIVE_PROVIDER_ENV_VAR, None)

    # Vision lane — always anthropic by default; independent of active_provider
    vision_key = get_lane_api_key("vision")
    if vision_key:
        os.environ[VISION_PROVIDER_ENV_VAR] = PROVIDER_LANE_DEFAULTS["vision"]
    else:
        os.environ.pop(VISION_PROVIDER_ENV_VAR, None)

    # Text-assist lane — always qwen by default; independent of active_provider
    text_key = get_lane_api_key("text_assist")
    if text_key:
        os.environ[TEXT_ASSIST_PROVIDER_ENV_VAR] = PROVIDER_LANE_DEFAULTS["text_assist"]
    else:
        os.environ.pop(TEXT_ASSIST_PROVIDER_ENV_VAR, None)


def summarize_provider_settings() -> dict:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    providers: list[dict] = []

    for provider_id in PROVIDER_IDS:
        key = get_provider_api_key(provider_id)
        is_active = active_provider == provider_id
        has_key = bool(key)
        if is_active and has_key:
            status = "ACTIVE"
        elif has_key:
            status = "READY"
        else:
            status = "KEY_MISSING"

        providers.append(
            {
                "provider_id": provider_id,
                "label": PROVIDER_LABELS[provider_id],
                "env_var": PROVIDER_ENV_VARS[provider_id],
                "has_key": has_key,
                "masked_key": _mask_api_key(key),
                "status": status,
                "is_active": is_active,
                "updated_at": payload["providers"][provider_id].get("updated_at"),
                "activated_at": payload["providers"][provider_id].get("activated_at"),
                "activation_scope": PROVIDER_SCOPES[provider_id],
                "current_capabilities": PROVIDER_CAPABILITIES[provider_id],
            }
        )

    return {
        "active_provider": active_provider if active_provider in PROVIDER_IDS else None,
        "providers": providers,
    }


def update_provider_key(provider_id: str, api_key: str) -> dict:
    normalized = _normalize_provider_id(provider_id)
    cleaned_key = str(api_key or "").strip()
    if not cleaned_key:
        raise ValueError("API_KEY_REQUIRED")

    payload = _load_payload()
    payload["providers"][normalized]["api_key"] = cleaned_key
    payload["providers"][normalized]["updated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def clear_provider_key(provider_id: str) -> dict:
    normalized = _normalize_provider_id(provider_id)
    payload = _load_payload()
    payload["providers"][normalized]["api_key"] = ""
    payload["providers"][normalized]["updated_at"] = _iso_now()
    payload["providers"][normalized]["activated_at"] = None
    if payload.get("active_provider") == normalized:
        payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def activate_provider(provider_id: str) -> dict:
    normalized = _normalize_provider_id(provider_id)
    if not get_provider_api_key(normalized):
        raise ValueError("API_KEY_MISSING_FOR_PROVIDER")

    payload = _load_payload()
    payload["active_provider"] = normalized
    payload["providers"][normalized]["activated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def deactivate_provider() -> dict:
    payload = _load_payload()
    payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()
