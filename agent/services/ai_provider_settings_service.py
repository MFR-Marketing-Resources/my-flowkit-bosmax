from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from agent.config import BASE_DIR, REVIEW_MODEL

ProviderId = Literal["qwen", "anthropic", "openai", "gemini", "deepseek"]
RoutingProviderId = Literal[
    "qwen",
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
    "deterministic",
]
ExecutionMode = Literal["disabled", "registry_only", "live"]
LaneId = Literal[
    "product_image_analysis",
    "copywriting_assist",
    "angle_hook_subhook_expansion",
    "claim_risk_qa",
    "product_truth_extraction",
    "video_review",
    "final_prompt_compiler",
]

PROVIDER_IDS: tuple[ProviderId, ...] = (
    "qwen",
    "anthropic",
    "openai",
    "gemini",
    "deepseek",
)
ROUTING_PROVIDER_IDS: tuple[RoutingProviderId, ...] = (
    *PROVIDER_IDS,
    "deterministic",
)
LANE_IDS: tuple[LaneId, ...] = (
    "product_image_analysis",
    "copywriting_assist",
    "angle_hook_subhook_expansion",
    "claim_risk_qa",
    "product_truth_extraction",
    "video_review",
    "final_prompt_compiler",
)

PROVIDER_LABELS: dict[RoutingProviderId, str] = {
    "qwen": "Qwen",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "deepseek": "DeepSeek",
    "deterministic": "Deterministic",
}

PROVIDER_ENV_VARS: dict[ProviderId, str] = {
    "qwen": "DASHSCOPE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

PROVIDER_SCOPES: dict[ProviderId, str] = {
    "qwen": "LIVE_NOW",
    "anthropic": "LIVE_NOW",
    "openai": "REGISTRY_ONLY",
    "gemini": "REGISTRY_ONLY",
    "deepseek": "REGISTRY_ONLY",
}

PROVIDER_CAPABILITIES: dict[ProviderId, list[str]] = {
    "qwen": ["Copywriting assist lane (Qwen API)"],
    "anthropic": ["Product image analysis", "Video review SDK"],
    "openai": ["Stored for model-routing registry"],
    "gemini": ["Stored for model-routing registry"],
    "deepseek": ["Stored for model-routing registry"],
}

AI_PROVIDER_STATE_DIR = BASE_DIR / ".local-agent"
AI_PROVIDER_SETTINGS_FILE = AI_PROVIDER_STATE_DIR / "ai-provider-settings.json"
AI_PROVIDER_STATE_VERSION = 2
ACTIVE_PROVIDER_ENV_VAR = "BOSMAX_ACTIVE_AI_PROVIDER"
VISION_PROVIDER_ENV_VAR = "PRODUCT_IMAGE_VISION_PROVIDER"
TEXT_ASSIST_PROVIDER_ENV_VAR = "PRODUCT_TEXT_ASSIST_PROVIDER"

LEGACY_LANE_ALIASES: dict[str, LaneId] = {
    "text_assist": "copywriting_assist",
    "vision": "product_image_analysis",
}

LANE_DEFINITIONS: dict[LaneId, dict[str, Any]] = {
    "product_image_analysis": {
        "label": "Product Image Analysis",
        "description": "Semantic pack/image analysis for product registration and intelligence.",
        "locked": False,
        "provider_context": "vision",
    },
    "copywriting_assist": {
        "label": "Copywriting Assist",
        "description": "Operator-configurable text-assist lane for USP and copy suggestion helpers.",
        "locked": False,
        "provider_context": "text_assist",
    },
    "angle_hook_subhook_expansion": {
        "label": "Angle / Hook / Subhook Expansion",
        "description": "Foundation lane for future BOSMAX angle, hook, and subhook expansion.",
        "locked": False,
        "provider_context": "registry_only",
    },
    "claim_risk_qa": {
        "label": "Claim Risk QA",
        "description": "Foundation lane for future claim-risk review and QA routing.",
        "locked": False,
        "provider_context": "registry_only",
    },
    "product_truth_extraction": {
        "label": "Product Truth Extraction",
        "description": "Foundation lane for future product-truth extraction and reconciliation.",
        "locked": False,
        "provider_context": "registry_only",
    },
    "video_review": {
        "label": "Video Review",
        "description": "Frame-based video review lane with Anthropic SDK compatibility preserved.",
        "locked": False,
        "provider_context": "vision",
    },
    "final_prompt_compiler": {
        "label": "Final Prompt Compiler",
        "description": "Canonical deterministic 9-section BOSMAX compiler. This lane is read-only.",
        "locked": True,
        "provider_context": "deterministic",
    },
}

LIVE_ROUTE_SUPPORT: dict[LaneId, set[RoutingProviderId]] = {
    "product_image_analysis": {"anthropic"},
    "copywriting_assist": {"qwen"},
    "angle_hook_subhook_expansion": set(),
    "claim_risk_qa": set(),
    "product_truth_extraction": set(),
    "video_review": {"anthropic"},
    "final_prompt_compiler": {"deterministic"},
}

PRODUCT_IMAGE_ANALYSIS_DEFAULT_MODEL = (
    str(os.environ.get("PRODUCT_IMAGE_ANALYSIS_MODEL") or REVIEW_MODEL).strip()
    or REVIEW_MODEL
)
QWEN_TEXT_DEFAULT_MODEL = (
    str(os.environ.get("QWEN_TEXT_MODEL") or "qwen-plus").strip() or "qwen-plus"
)

MODEL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "provider_id": "gemini",
        "model_id": "gemini-2.5-flash-lite",
        "label": "Gemini 2.5 Flash Lite",
        "capability_tags": ["text", "image", "video", "json", "low_cost"],
        "recommended_lanes": ["product_image_analysis", "product_truth_extraction"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": ["product_truth_extraction"],
        "locked": False,
    },
    {
        "provider_id": "gemini",
        "model_id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "capability_tags": ["text", "image", "video", "json", "balanced"],
        "recommended_lanes": ["product_image_analysis", "product_truth_extraction"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": [],
        "locked": False,
    },
    {
        "provider_id": "openai",
        "model_id": "gpt-5.4-mini",
        "label": "GPT-5.4 Mini",
        "capability_tags": ["text", "json", "reasoning", "qa"],
        "recommended_lanes": ["claim_risk_qa", "copywriting_assist", "product_truth_extraction"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": ["claim_risk_qa"],
        "locked": False,
    },
    {
        "provider_id": "openai",
        "model_id": "gpt-5.4-nano",
        "label": "GPT-5.4 Nano",
        "capability_tags": ["text", "json", "low_cost"],
        "recommended_lanes": ["copywriting_assist", "product_truth_extraction"],
        "status": "experimental",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": [],
        "locked": False,
    },
    {
        "provider_id": "anthropic",
        "model_id": PRODUCT_IMAGE_ANALYSIS_DEFAULT_MODEL,
        "label": "Claude Haiku 4.5 (Repo Authority)",
        "capability_tags": ["text", "image", "video", "json", "low_cost", "qa"],
        "recommended_lanes": ["product_image_analysis", "video_review"],
        "status": "available",
        "notes": "Matches the repo's current REVIEW_MODEL / product-image analysis authority.",
        "default_for_lanes": ["product_image_analysis", "video_review"],
        "locked": False,
    },
    {
        "provider_id": "anthropic",
        "model_id": "claude-sonnet-5",
        "label": "Claude Sonnet 5",
        "capability_tags": ["text", "image", "json", "reasoning", "qa"],
        "recommended_lanes": ["claim_risk_qa", "product_truth_extraction", "video_review"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": [],
        "locked": False,
    },
    {
        "provider_id": "deepseek",
        "model_id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "capability_tags": ["text", "json", "low_cost"],
        "recommended_lanes": ["copywriting_assist", "angle_hook_subhook_expansion"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": ["angle_hook_subhook_expansion"],
        "locked": False,
    },
    {
        "provider_id": "deepseek",
        "model_id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "capability_tags": ["text", "json", "reasoning"],
        "recommended_lanes": ["copywriting_assist", "claim_risk_qa"],
        "status": "experimental",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": [],
        "locked": False,
    },
    {
        "provider_id": "qwen",
        "model_id": QWEN_TEXT_DEFAULT_MODEL,
        "label": "Qwen Plus (Repo Authority)",
        "capability_tags": ["text", "json", "copywriting", "balanced"],
        "recommended_lanes": ["copywriting_assist", "angle_hook_subhook_expansion"],
        "status": "available",
        "notes": "Matches the repo's current text-assist model authority.",
        "default_for_lanes": ["copywriting_assist"],
        "locked": False,
    },
    {
        "provider_id": "qwen",
        "model_id": "qwen3.7-plus",
        "label": "Qwen 3.7 Plus",
        "capability_tags": ["text", "json", "balanced"],
        "recommended_lanes": ["copywriting_assist", "angle_hook_subhook_expansion", "claim_risk_qa"],
        "status": "registry_only",
        "notes": "Catalog-only foundation entry. Runtime adapter not wired in this phase.",
        "default_for_lanes": [],
        "locked": False,
    },
    {
        "provider_id": "deterministic",
        "model_id": "bosmax-canonical-compiler",
        "label": "BOSMAX Canonical Compiler",
        "capability_tags": ["deterministic_prompt_compiler"],
        "recommended_lanes": ["final_prompt_compiler"],
        "status": "available",
        "notes": "Locked canonical 9-section compiler. Not routable to external LLM providers.",
        "default_for_lanes": ["final_prompt_compiler"],
        "locked": True,
    },
)


def _resolve_lane_id(value: str) -> LaneId:
    normalized = str(value or "").strip()
    alias = LEGACY_LANE_ALIASES.get(normalized, normalized)
    if alias not in LANE_IDS:
        raise ValueError(f"UNKNOWN_LANE:{value}")
    return alias  # type: ignore[return-value]


def _normalize_provider_id(value: str) -> ProviderId:
    normalized = str(value or "").strip().lower()
    if normalized not in PROVIDER_IDS:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{value}")
    return normalized  # type: ignore[return-value]


def _normalize_routing_provider_id(value: str) -> RoutingProviderId:
    normalized = str(value or "").strip().lower()
    if normalized not in ROUTING_PROVIDER_IDS:
        raise ValueError(f"UNSUPPORTED_PROVIDER:{value}")
    return normalized  # type: ignore[return-value]


def _normalize_execution_mode(value: str) -> ExecutionMode:
    normalized = str(value or "").strip().lower()
    if normalized not in {"disabled", "registry_only", "live"}:
        raise ValueError(f"UNSUPPORTED_EXECUTION_MODE:{value}")
    return normalized  # type: ignore[return-value]


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


def _mask_api_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * max(4, len(value) - 8)}{value[-4:]}"


def _ensure_state_dir() -> None:
    AI_PROVIDER_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _find_model(provider_id: RoutingProviderId, model_id: str) -> dict[str, Any] | None:
    normalized_model_id = str(model_id or "").strip()
    for entry in MODEL_CATALOG:
        if entry["provider_id"] == provider_id and entry["model_id"] == normalized_model_id:
            return dict(entry)
    return None


def _model_supports_lane(model_entry: dict[str, Any], lane_id: LaneId) -> bool:
    recommended = {
        str(item)
        for item in list(model_entry.get("recommended_lanes") or [])
    }
    defaults = {
        str(item)
        for item in list(model_entry.get("default_for_lanes") or [])
    }
    return lane_id in recommended or lane_id in defaults


def _default_routing_payload() -> dict[str, dict[str, Any]]:
    legacy_vision_enabled = _env_bool("BOSMAX_VISION_PROVIDER_EXECUTION_ENABLED", False)
    legacy_text_assist_enabled = _env_bool("BOSMAX_TEXT_ASSIST_EXECUTION_ENABLED", True)
    return {
        "product_image_analysis": {
            "provider_id": "anthropic",
            "model_id": PRODUCT_IMAGE_ANALYSIS_DEFAULT_MODEL,
            "enabled": legacy_vision_enabled,
            "execution_mode": "live",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "copywriting_assist": {
            "provider_id": "qwen",
            "model_id": QWEN_TEXT_DEFAULT_MODEL,
            "enabled": legacy_text_assist_enabled,
            "execution_mode": "live",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "angle_hook_subhook_expansion": {
            "provider_id": "deepseek",
            "model_id": "deepseek-v4-flash",
            "enabled": False,
            "execution_mode": "registry_only",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "claim_risk_qa": {
            "provider_id": "openai",
            "model_id": "gpt-5.4-mini",
            "enabled": False,
            "execution_mode": "registry_only",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "product_truth_extraction": {
            "provider_id": "gemini",
            "model_id": "gemini-2.5-flash-lite",
            "enabled": False,
            "execution_mode": "registry_only",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "video_review": {
            "provider_id": "anthropic",
            "model_id": REVIEW_MODEL,
            "enabled": legacy_vision_enabled,
            "execution_mode": "live",
            "locked": False,
            "updated_at": None,
            "source": "system_default",
        },
        "final_prompt_compiler": {
            "provider_id": "deterministic",
            "model_id": "bosmax-canonical-compiler",
            "enabled": True,
            "execution_mode": "live",
            "locked": True,
            "updated_at": None,
            "source": "system_default",
        },
    }


def _default_payload() -> dict[str, Any]:
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
        "routing": _default_routing_payload(),
    }


def _coerce_provider_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {
            "api_key": "",
            "updated_at": None,
            "activated_at": None,
        }
    return {
        "api_key": str(entry.get("api_key") or ""),
        "updated_at": entry.get("updated_at"),
        "activated_at": entry.get("activated_at"),
    }


def _coerce_route_entry(lane_id: LaneId, entry: Any) -> dict[str, Any]:
    defaults = deepcopy(_default_routing_payload()[lane_id])
    if not isinstance(entry, dict):
        return defaults

    provider_id = str(entry.get("provider_id") or defaults["provider_id"]).strip().lower()
    model_id = str(entry.get("model_id") or defaults["model_id"]).strip() or defaults["model_id"]
    enabled = bool(entry.get("enabled", defaults["enabled"]))
    execution_mode = str(entry.get("execution_mode") or defaults["execution_mode"]).strip().lower()
    source = str(entry.get("source") or defaults["source"]).strip() or defaults["source"]
    updated_at = entry.get("updated_at")

    try:
        normalized_provider = _normalize_routing_provider_id(provider_id)
    except ValueError:
        normalized_provider = defaults["provider_id"]
    try:
        normalized_mode = _normalize_execution_mode(execution_mode)
    except ValueError:
        normalized_mode = defaults["execution_mode"]

    model_entry = _find_model(normalized_provider, model_id)
    if not model_entry or not _model_supports_lane(model_entry, lane_id):
        normalized_provider = defaults["provider_id"]
        model_id = defaults["model_id"]
        normalized_mode = defaults["execution_mode"]
        enabled = bool(defaults["enabled"])

    locked = bool(LANE_DEFINITIONS[lane_id]["locked"])
    if locked:
        enabled = True
        normalized_mode = "live"
        normalized_provider = "deterministic"
        model_id = "bosmax-canonical-compiler"
        source = "system_locked"

    return {
        "provider_id": normalized_provider,
        "model_id": model_id,
        "enabled": enabled,
        "execution_mode": normalized_mode,
        "locked": locked,
        "updated_at": updated_at,
        "source": source,
    }


def _load_payload() -> dict[str, Any]:
    _ensure_state_dir()
    default_payload = _default_payload()
    if not AI_PROVIDER_SETTINGS_FILE.exists():
        AI_PROVIDER_SETTINGS_FILE.write_text(
            json.dumps(default_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return default_payload

    needs_save = False
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
        "routing": {},
    }
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    for provider_id in PROVIDER_IDS:
        payload["providers"][provider_id] = _coerce_provider_entry(raw_providers.get(provider_id))

    if payload["active_provider"] not in PROVIDER_IDS:
        payload["active_provider"] = None

    raw_routing = raw.get("routing") if isinstance(raw.get("routing"), dict) else {}
    for lane_id in LANE_IDS:
        payload["routing"][lane_id] = _coerce_route_entry(lane_id, raw_routing.get(lane_id))

    if payload["version"] != AI_PROVIDER_STATE_VERSION:
        payload["version"] = AI_PROVIDER_STATE_VERSION
        needs_save = True
    if not isinstance(raw.get("routing"), dict):
        needs_save = True

    if needs_save:
        _save_payload(payload)
    return payload


def _save_payload(payload: dict[str, Any]) -> None:
    _ensure_state_dir()
    payload["version"] = AI_PROVIDER_STATE_VERSION
    AI_PROVIDER_SETTINGS_FILE.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_provider_api_key(payload: dict[str, Any], provider_id: ProviderId) -> str:
    stored_key = str(payload["providers"][provider_id].get("api_key") or "").strip()
    if stored_key:
        return stored_key
    return str(os.environ.get(PROVIDER_ENV_VARS[provider_id], "")).strip()


def get_provider_api_key(provider_id: str) -> str:
    normalized = _normalize_provider_id(provider_id)
    return _get_provider_api_key(_load_payload(), normalized)


def get_active_provider_id() -> ProviderId | None:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    if active_provider in PROVIDER_IDS:
        return active_provider  # type: ignore[return-value]
    env_active = str(os.environ.get(ACTIVE_PROVIDER_ENV_VAR, "")).strip().lower()
    if env_active in PROVIDER_IDS:
        return env_active  # type: ignore[return-value]
    return None


def _provider_key_status(payload: dict[str, Any], provider_id: RoutingProviderId) -> tuple[bool, str]:
    if provider_id == "deterministic":
        return True, "NOT_REQUIRED"
    has_key = bool(_get_provider_api_key(payload, provider_id))
    return has_key, "CONFIGURED" if has_key else "MISSING"


def _is_live_supported(lane_id: LaneId, provider_id: RoutingProviderId) -> bool:
    return provider_id in LIVE_ROUTE_SUPPORT.get(lane_id, set())


def _build_lane_warnings(payload: dict[str, Any], lane_id: LaneId, route: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    provider_id = route["provider_id"]
    execution_mode = route["execution_mode"]
    enabled = bool(route["enabled"])
    has_key, _ = _provider_key_status(payload, provider_id)
    live_supported = _is_live_supported(lane_id, provider_id)

    if route["locked"]:
        warnings.append("LOCKED_DETERMINISTIC_LANE")
    if execution_mode == "disabled":
        warnings.append("EXECUTION_MODE_DISABLED")
    elif execution_mode == "registry_only":
        warnings.append("REGISTRY_ONLY_CONFIGURATION")
    if enabled and execution_mode != "live":
        warnings.append("ENABLED_WITHOUT_LIVE_EXECUTION")
    if execution_mode == "live" and provider_id != "deterministic" and not has_key:
        warnings.append("PROVIDER_KEY_MISSING")
    if execution_mode == "live" and not live_supported:
        warnings.append("LIVE_ADAPTER_NOT_IMPLEMENTED")
    return warnings


def _is_route_executable(payload: dict[str, Any], lane_id: LaneId, route: dict[str, Any]) -> bool:
    provider_id = route["provider_id"]
    enabled = bool(route["enabled"])
    execution_mode = route["execution_mode"]
    has_key, _ = _provider_key_status(payload, provider_id)
    if not enabled:
        return False
    if execution_mode != "live":
        return False
    if not _is_live_supported(lane_id, provider_id):
        return False
    if provider_id == "deterministic":
        return True
    return has_key


def _build_lane_summary(payload: dict[str, Any], lane_id: LaneId) -> dict[str, Any]:
    route = dict(payload["routing"][lane_id])
    model_entry = _find_model(route["provider_id"], route["model_id"]) or {}
    has_key, key_status = _provider_key_status(payload, route["provider_id"])
    warnings = _build_lane_warnings(payload, lane_id, route)
    return {
        "lane_id": lane_id,
        "label": LANE_DEFINITIONS[lane_id]["label"],
        "description": LANE_DEFINITIONS[lane_id]["description"],
        "provider_id": route["provider_id"],
        "provider_label": PROVIDER_LABELS[route["provider_id"]],
        "model_id": route["model_id"],
        "model_label": str(model_entry.get("label") or route["model_id"]),
        "enabled": bool(route["enabled"]),
        "execution_mode": route["execution_mode"],
        "locked": bool(route["locked"]),
        "updated_at": route.get("updated_at"),
        "source": route.get("source") or "system_default",
        "provider_has_key": has_key,
        "provider_key_status": key_status,
        "live_supported": _is_live_supported(lane_id, route["provider_id"]),
        "is_executable_now": _is_route_executable(payload, lane_id, route),
        "warnings": warnings,
    }


def summarize_ai_model_catalog() -> dict[str, Any]:
    providers: list[dict[str, Any]] = []
    for provider_id in ROUTING_PROVIDER_IDS:
        models = [
            {
                "provider_id": entry["provider_id"],
                "model_id": entry["model_id"],
                "label": entry["label"],
                "capability_tags": list(entry.get("capability_tags") or []),
                "recommended_lanes": list(entry.get("recommended_lanes") or []),
                "status": entry["status"],
                "notes": entry.get("notes"),
                "default_for_lanes": list(entry.get("default_for_lanes") or []),
                "locked": bool(entry.get("locked")),
            }
            for entry in MODEL_CATALOG
            if entry["provider_id"] == provider_id
        ]
        if not models:
            continue
        providers.append(
            {
                "provider_id": provider_id,
                "label": PROVIDER_LABELS[provider_id],
                "models": models,
            }
        )
    return {"providers": providers}


def summarize_ai_routing() -> dict[str, Any]:
    payload = _load_payload()
    return {
        "lanes": [_build_lane_summary(payload, lane_id) for lane_id in LANE_IDS]
    }


def summarize_effective_ai_routing() -> dict[str, Any]:
    return summarize_ai_routing()


def get_ai_lane_route(lane_id: str) -> dict[str, Any]:
    resolved_lane_id = _resolve_lane_id(lane_id)
    payload = _load_payload()
    return _build_lane_summary(payload, resolved_lane_id)


def get_ai_lane_model(lane_id: str) -> str | None:
    route = get_ai_lane_route(lane_id)
    model_id = str(route.get("model_id") or "").strip()
    return model_id or None


def is_ai_lane_executable(lane_id: str) -> bool:
    resolved_lane_id = _resolve_lane_id(lane_id)
    payload = _load_payload()
    route = payload["routing"][resolved_lane_id]
    return _is_route_executable(payload, resolved_lane_id, route)


def require_ai_lane_or_fail_closed(lane_id: str) -> dict[str, Any]:
    route = get_ai_lane_route(lane_id)
    if route["locked"] and route["provider_id"] == "deterministic":
        return route
    if not route["enabled"]:
        raise ValueError(f"LANE_DISABLED:{route['lane_id']}")
    if route["execution_mode"] != "live":
        raise ValueError(f"LANE_NOT_LIVE:{route['lane_id']}")
    if not route["live_supported"]:
        raise ValueError(f"LANE_LIVE_ADAPTER_NOT_IMPLEMENTED:{route['lane_id']}")
    if not route["provider_has_key"]:
        raise ValueError(f"LANE_PROVIDER_KEY_MISSING:{route['lane_id']}")
    return route


def get_lane_provider(lane: str) -> str | None:
    try:
        return str(get_ai_lane_route(lane).get("provider_id") or "") or None
    except ValueError:
        return None


def get_lane_api_key(lane: str) -> str | None:
    provider_id = get_lane_provider(lane)
    if not provider_id or provider_id == "deterministic":
        return None
    try:
        key = get_provider_api_key(provider_id)
        return key or None
    except (ValueError, Exception):
        return None


def is_lane_execution_enabled(lane: str) -> bool:
    try:
        route = get_ai_lane_route(lane)
    except ValueError:
        return False
    return bool(route["enabled"]) and str(route["execution_mode"]) == "live"


def _is_provider_runtime_enabled(payload: dict[str, Any], provider_id: ProviderId) -> bool:
    for lane_id in LANE_IDS:
        route = payload["routing"][lane_id]
        if route["provider_id"] != provider_id:
            continue
        if _is_route_executable(payload, lane_id, route):
            return True
    return False


def apply_runtime_provider_environment(payload: dict[str, Any] | None = None) -> None:
    resolved = payload or _load_payload()
    active_provider = resolved.get("active_provider")

    for provider_id in PROVIDER_IDS:
        key = str(resolved["providers"][provider_id].get("api_key") or "").strip()
        env_var = PROVIDER_ENV_VARS[provider_id]
        if key and _is_provider_runtime_enabled(resolved, provider_id):
            os.environ[env_var] = key
        else:
            os.environ.pop(env_var, None)

    if active_provider in PROVIDER_IDS:
        os.environ[ACTIVE_PROVIDER_ENV_VAR] = active_provider
    else:
        os.environ.pop(ACTIVE_PROVIDER_ENV_VAR, None)

    product_image_provider = get_lane_provider("product_image_analysis")
    if product_image_provider and is_ai_lane_executable("product_image_analysis"):
        os.environ[VISION_PROVIDER_ENV_VAR] = product_image_provider
    else:
        os.environ.pop(VISION_PROVIDER_ENV_VAR, None)

    copywriting_provider = get_lane_provider("copywriting_assist")
    if copywriting_provider and is_ai_lane_executable("copywriting_assist"):
        os.environ[TEXT_ASSIST_PROVIDER_ENV_VAR] = copywriting_provider
    else:
        os.environ.pop(TEXT_ASSIST_PROVIDER_ENV_VAR, None)


def summarize_provider_settings() -> dict[str, Any]:
    payload = _load_payload()
    active_provider = payload.get("active_provider")
    providers: list[dict[str, Any]] = []

    for provider_id in PROVIDER_IDS:
        key = _get_provider_api_key(payload, provider_id)
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


def update_provider_key(provider_id: str, api_key: str) -> dict[str, Any]:
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


def clear_provider_key(provider_id: str) -> dict[str, Any]:
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


def activate_provider(provider_id: str) -> dict[str, Any]:
    normalized = _normalize_provider_id(provider_id)
    if not get_provider_api_key(normalized):
        raise ValueError("API_KEY_MISSING_FOR_PROVIDER")

    payload = _load_payload()
    payload["active_provider"] = normalized
    payload["providers"][normalized]["activated_at"] = _iso_now()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def deactivate_provider() -> dict[str, Any]:
    payload = _load_payload()
    payload["active_provider"] = None
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_provider_settings()


def _validate_route_update(
    payload: dict[str, Any],
    lane_id: LaneId,
    provider_id: RoutingProviderId,
    model_id: str,
    enabled: bool,
    execution_mode: ExecutionMode,
) -> None:
    current_route = payload["routing"][lane_id]
    if current_route.get("locked") or LANE_DEFINITIONS[lane_id]["locked"]:
        raise ValueError("LANE_LOCKED")

    model_entry = _find_model(provider_id, model_id)
    if not model_entry:
        raise ValueError("UNKNOWN_MODEL")
    if not _model_supports_lane(model_entry, lane_id):
        raise ValueError("MODEL_LANE_INCOMPATIBLE")

    if execution_mode == "live":
        if not _is_live_supported(lane_id, provider_id):
            raise ValueError("LIVE_EXECUTION_NOT_IMPLEMENTED_FOR_ROUTE")
        if enabled and provider_id != "deterministic":
            has_key, _ = _provider_key_status(payload, provider_id)
            if not has_key:
                raise ValueError("API_KEY_REQUIRED_FOR_LIVE_EXECUTION")


def update_ai_lane_routing(
    lane_id: str,
    *,
    provider_id: str,
    model_id: str,
    enabled: bool,
    execution_mode: str,
) -> dict[str, Any]:
    resolved_lane_id = _resolve_lane_id(lane_id)
    normalized_provider_id = _normalize_routing_provider_id(provider_id)
    normalized_execution_mode = _normalize_execution_mode(execution_mode)
    normalized_enabled = bool(enabled) and normalized_execution_mode != "disabled"
    normalized_model_id = str(model_id or "").strip()

    payload = _load_payload()
    _validate_route_update(
        payload,
        resolved_lane_id,
        normalized_provider_id,
        normalized_model_id,
        normalized_enabled,
        normalized_execution_mode,
    )

    payload["routing"][resolved_lane_id] = {
        "provider_id": normalized_provider_id,
        "model_id": normalized_model_id,
        "enabled": normalized_enabled,
        "execution_mode": normalized_execution_mode,
        "locked": False,
        "updated_at": _iso_now(),
        "source": "user",
    }
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_ai_routing()


def reset_ai_routing() -> dict[str, Any]:
    payload = _load_payload()
    payload["routing"] = _default_routing_payload()
    _save_payload(payload)
    apply_runtime_provider_environment(payload)
    return summarize_ai_routing()
