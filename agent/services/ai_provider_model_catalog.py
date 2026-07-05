"""AI provider / model catalog — SEED + mutable local catalog + transport gating
(Dynamic AI Model Catalog & Explicit Lane Configuration V1).

Two layers:
- **Seed catalog** (source-of-truth *reference* constants below): recommended known
  models per provider. It is a bootstrap/reference layer only — it does NOT force
  any runtime lane default.
- **Mutable local catalog** (`.local-agent/ai-model-catalog.json`, untracked):
  operator-owned. Seeded from the seed catalog on first run, then freely
  add/edit/disable-able. New model IDs are added here WITHOUT a code change.

A model ID is treated as operator-provided runtime config, not a claim that the
model exists. Transport compatibility is enforced: a model may serve a lane only
if the provider's transport implements that lane. Unknown transport fails closed.

This module holds NO secrets and performs NO network calls. It never sits on the
deterministic compiler path.
"""
from __future__ import annotations

import json
from typing import Any

from agent.config import BASE_DIR

LANES: tuple[str, ...] = ("text_assist", "vision")

LANE_LABELS: dict[str, str] = {
    "text_assist": "Text Assist",
    "vision": "Vision",
}

# --- transports -----------------------------------------------------------
# A provider declares ONE transport. A lane is servable by a provider only if the
# provider's transport is listed in LANE_TRANSPORT_SUPPORT[lane]. Unknown/unsupported
# transports fail closed (never runnable).
TRANSPORT_OPENAI_COMPATIBLE = "openai_compatible_chat"
TRANSPORT_ANTHROPIC_MESSAGES = "anthropic_messages"
SUPPORTED_TRANSPORTS: frozenset[str] = frozenset(
    {TRANSPORT_OPENAI_COMPATIBLE, TRANSPORT_ANTHROPIC_MESSAGES}
)

# Which transports actually have a runtime implementation for each lane:
# - text_assist: implemented in ai_copy_provider_adapter for BOTH transports.
# - vision: BOTH transports are wired.
#     * anthropic_messages   -> product_image_analysis anthropic SDK path (existing).
#     * openai_compatible_chat -> vision_provider_adapter image_url path, which
#       reaches OpenAI, Gemini (its OpenAI-compatible endpoint), and Qwen-VL
#       (DashScope OpenAI-compatible endpoint). A model is still only vision-
#       selectable if it ALSO lists the vision lane (deepseek ships none).
LANE_TRANSPORT_SUPPORT: dict[str, frozenset[str]] = {
    "text_assist": frozenset({TRANSPORT_OPENAI_COMPATIBLE, TRANSPORT_ANTHROPIC_MESSAGES}),
    "vision": frozenset({TRANSPORT_ANTHROPIC_MESSAGES, TRANSPORT_OPENAI_COMPATIBLE}),
}

# provider_id -> seed provider block. `models[].lanes` are the lanes the seed model
# is intended for (still transport-gated at validation time).
SEED_CATALOG: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic",
        "transport": TRANSPORT_ANTHROPIC_MESSAGES,
        "models": [
            {"model_id": "claude-sonnet-5", "label": "Claude Sonnet 5", "lanes": ["text_assist", "vision"]},
            {"model_id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5", "lanes": ["text_assist", "vision"]},
            {"model_id": "claude-opus-4-8", "label": "Claude Opus 4.8", "lanes": ["text_assist", "vision"]},
        ],
    },
    "qwen": {
        "label": "Qwen",
        "transport": TRANSPORT_OPENAI_COMPATIBLE,
        "models": [
            {"model_id": "qwen-plus", "label": "Qwen Plus", "lanes": ["text_assist"]},
            {"model_id": "qwen-max", "label": "Qwen Max", "lanes": ["text_assist"]},
            # Qwen-VL over the DashScope OpenAI-compatible endpoint (image_url).
            {"model_id": "qwen-vl-max", "label": "Qwen VL Max", "lanes": ["vision"]},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "transport": TRANSPORT_OPENAI_COMPATIBLE,
        "models": [
            # GPT-4o family is natively multimodal (text_assist + vision).
            {"model_id": "gpt-4o-mini", "label": "GPT-4o mini", "lanes": ["text_assist", "vision"]},
            {"model_id": "gpt-4o", "label": "GPT-4o", "lanes": ["text_assist", "vision"]},
        ],
    },
    "gemini": {
        "label": "Gemini",
        "transport": TRANSPORT_OPENAI_COMPATIBLE,
        "models": [
            # Gemini 2.0 Flash is multimodal via the OpenAI-compatible endpoint.
            {"model_id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "lanes": ["text_assist", "vision"]},
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "transport": TRANSPORT_OPENAI_COMPATIBLE,
        "models": [
            {"model_id": "deepseek-chat", "label": "DeepSeek Chat", "lanes": ["text_assist"]},
        ],
    },
}

SEED_PROVIDER_IDS: tuple[str, ...] = tuple(SEED_CATALOG.keys())

AI_MODEL_CATALOG_DIR = BASE_DIR / ".local-agent"
AI_MODEL_CATALOG_FILE = AI_MODEL_CATALOG_DIR / "ai-model-catalog.json"
AI_MODEL_CATALOG_VERSION = 1


# --- pure helpers ---------------------------------------------------------

def is_known_lane(lane: str) -> bool:
    return str(lane or "") in LANES


def _normalize_lanes(lanes: Any) -> list[str]:
    if not isinstance(lanes, (list, tuple)):
        return []
    seen: list[str] = []
    for lane in lanes:
        lane = str(lane or "").strip()
        if lane in LANES and lane not in seen:
            seen.append(lane)
    return [lane for lane in LANES if lane in seen]


def _seed_model(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": str(entry["model_id"]),
        "label": str(entry.get("label") or entry["model_id"]),
        "enabled": True,
        "lanes": _normalize_lanes(entry.get("lanes")),
        "source": "seed",
    }


def _seed_provider(provider_id: str) -> dict[str, Any]:
    seed = SEED_CATALOG[provider_id]
    return {
        "label": str(seed["label"]),
        "transport": str(seed["transport"]),
        "enabled": True,
        "models": [_seed_model(model) for model in seed["models"]],
    }


def seed_catalog_payload() -> dict[str, Any]:
    return {
        "version": AI_MODEL_CATALOG_VERSION,
        "providers": {pid: _seed_provider(pid) for pid in SEED_PROVIDER_IDS},
    }


# --- mutable catalog storage ---------------------------------------------

def _ensure_dir() -> None:
    AI_MODEL_CATALOG_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_model(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    model_id = str(raw.get("model_id") or "").strip()
    if not model_id:
        return None
    source = str(raw.get("source") or "custom")
    if source not in {"seed", "custom"}:
        source = "custom"
    return {
        "model_id": model_id,
        "label": str(raw.get("label") or model_id),
        "enabled": bool(raw.get("enabled", True)),
        "lanes": _normalize_lanes(raw.get("lanes")),
        "source": source,
    }


def _normalize_provider(provider_id: str, raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    seed = SEED_CATALOG.get(provider_id)
    transport = str(raw.get("transport") or (seed["transport"] if seed else "")).strip()
    if transport not in SUPPORTED_TRANSPORTS:
        transport = seed["transport"] if seed else ""
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_model in raw.get("models") if isinstance(raw.get("models"), list) else []:
        model = _normalize_model(raw_model)
        if model and model["model_id"] not in seen:
            seen.add(model["model_id"])
            models.append(model)
    return {
        "label": str(raw.get("label") or (seed["label"] if seed else provider_id)),
        "transport": transport,
        "enabled": bool(raw.get("enabled", True)),
        "models": models,
    }


def _write_catalog(payload: dict[str, Any]) -> None:
    _ensure_dir()
    AI_MODEL_CATALOG_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _merge_seed_lanes(existing_lanes: Any, seed_lanes: list[str]) -> list[str]:
    """Union of existing + seed lanes in canonical LANES order. Only ADDS missing
    seed lanes; never removes a lane the operator already has."""
    combined = set(_normalize_lanes(existing_lanes)) | set(seed_lanes)
    return [lane for lane in LANES if lane in combined]


def _forward_merge_seed_models(provider_id: str, entry: dict[str, Any]) -> bool:
    """Non-destructive forward migration for a KNOWN seed provider already present
    in the local catalog. Mutates `entry` in place and returns True if anything
    changed.

    Rules (see MULTI_PROVIDER_VISION_LANE_ADAPTERS_V1 / this hotfix):
    - ADD any seed model missing from the local provider (new capabilities such as
      qwen-vl-max reach existing installs without a manual reset).
    - For an existing model whose model_id matches a current seed model, MERGE any
      missing seed lanes (e.g. gpt-4o / gemini-2.0-flash gain `vision`). Union only —
      existing lanes are never dropped.
    - PRESERVE everything operator-owned: custom models (non-seed ids) are untouched,
      and existing `enabled` / `label` / `source` are never overwritten. A disabled
      seed model stays disabled.
    """
    seed = SEED_CATALOG.get(provider_id)
    if not seed:
        return False
    seed_model_ids = {str(m["model_id"]) for m in seed["models"]}
    existing_by_id = {m["model_id"]: m for m in entry["models"]}
    changed = False
    for seed_raw in seed["models"]:
        seed_model = _seed_model(seed_raw)
        sid = seed_model["model_id"]
        existing = existing_by_id.get(sid)
        if existing is None:
            # New seed model — add it (enabled, source seed). Lane stays NOT_CONFIGURED
            # until the operator explicitly selects it; adding a model auto-selects nothing.
            entry["models"].append(seed_model)
            existing_by_id[sid] = seed_model
            changed = True
            continue
        # Existing model with a seed id: merge missing seed lanes only. Custom models
        # (ids not in seed_model_ids) are never reached here, so they stay operator-owned.
        if sid in seed_model_ids:
            merged = _merge_seed_lanes(existing.get("lanes"), seed_model["lanes"])
            if merged != _normalize_lanes(existing.get("lanes")):
                existing["lanes"] = merged
                changed = True
    return changed


def _load_catalog() -> dict[str, Any]:
    """Load the mutable catalog, seeding on first run. Non-destructive forward
    merge: seed providers missing from the file are ADDED, and for seed providers
    already present, missing seed MODELS are added and missing seed LANES are merged
    into existing seed models (never overwriting custom models or operator-disabled
    state). Only (re)writes the file when something actually changed."""
    _ensure_dir()
    seed = seed_catalog_payload()
    if not AI_MODEL_CATALOG_FILE.exists():
        _write_catalog(seed)
        return seed
    try:
        raw = json.loads(AI_MODEL_CATALOG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _write_catalog(seed)
        return seed

    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    providers: dict[str, Any] = {}
    added_seed = False
    for pid in raw_providers:
        # Only keep providers we know a transport for; unknown providers are dropped
        # (no unsupported-transport runtime). Seed providers get normalized.
        if pid in SEED_CATALOG:
            providers[pid] = _normalize_provider(pid, raw_providers.get(pid))
    for pid in SEED_PROVIDER_IDS:
        if pid not in providers:
            providers[pid] = _seed_provider(pid)
            added_seed = True

    # Forward-migrate seed providers already present (pre-#210 catalogs lack the new
    # vision seed models / lanes). Non-destructive: adds missing seed models, merges
    # missing seed lanes into existing seed models, preserves everything else.
    migrated = False
    for pid in SEED_PROVIDER_IDS:
        if pid in raw_providers and _forward_merge_seed_models(pid, providers[pid]):
            migrated = True

    payload = {"version": AI_MODEL_CATALOG_VERSION, "providers": providers}
    if added_seed or migrated:
        _write_catalog(payload)
    return payload


# --- catalog queries ------------------------------------------------------

def get_model_catalog() -> dict[str, Any]:
    return _load_catalog()


def summarize_model_catalog() -> dict[str, Any]:
    """Serializable catalog for the registry response (no secrets)."""
    catalog = _load_catalog()
    providers: dict[str, Any] = {}
    for pid, entry in catalog["providers"].items():
        providers[pid] = {
            "label": entry["label"],
            "transport": entry["transport"],
            "enabled": bool(entry["enabled"]),
            "supported_lanes": _provider_supported_lanes(entry),
            "models": [dict(model) for model in entry["models"]],
        }
    return {"version": catalog.get("version", AI_MODEL_CATALOG_VERSION), "providers": providers}


def is_provider_in_catalog(provider_id: str) -> bool:
    return str(provider_id or "").lower() in _load_catalog()["providers"]


def get_provider_entry(provider_id: str) -> dict[str, Any] | None:
    return _load_catalog()["providers"].get(str(provider_id or "").lower())


def get_provider_transport(provider_id: str) -> str | None:
    entry = get_provider_entry(provider_id)
    return entry["transport"] if entry else None


def _transport_supports_lane(transport: str, lane: str) -> bool:
    return transport in LANE_TRANSPORT_SUPPORT.get(lane, frozenset())


def _provider_supported_lanes(entry: dict[str, Any]) -> list[str]:
    lanes: list[str] = []
    if not entry.get("enabled"):
        return lanes
    transport = entry.get("transport") or ""
    for lane in LANES:
        if not _transport_supports_lane(transport, lane):
            continue
        if any(
            model.get("enabled") and lane in (model.get("lanes") or [])
            for model in entry.get("models", [])
        ):
            lanes.append(lane)
    return lanes


def supported_lanes_for_provider(provider_id: str) -> list[str]:
    entry = get_provider_entry(provider_id)
    return _provider_supported_lanes(entry) if entry else []


def models_for_provider(provider_id: str) -> list[dict[str, Any]]:
    entry = get_provider_entry(provider_id)
    return [dict(m) for m in entry["models"]] if entry else []


def get_model_entry(provider_id: str, model_id: str) -> dict[str, Any] | None:
    for model in models_for_provider(provider_id):
        if model["model_id"] == str(model_id):
            return model
    return None


def models_for_lane(provider_id: str, lane: str) -> list[dict[str, Any]]:
    entry = get_provider_entry(provider_id)
    if not entry or not entry.get("enabled"):
        return []
    if not _transport_supports_lane(entry.get("transport") or "", lane):
        return []
    return [
        dict(model)
        for model in entry["models"]
        if model.get("enabled") and lane in (model.get("lanes") or [])
    ]


def model_supports_lane(provider_id: str, model_id: str, lane: str) -> bool:
    """True only when the model exists, is enabled, lists the lane, AND the
    provider's transport implements the lane. Fail-closed everywhere else."""
    if not is_known_lane(lane):
        return False
    entry = get_provider_entry(provider_id)
    if not entry or not entry.get("enabled"):
        return False
    if not _transport_supports_lane(entry.get("transport") or "", lane):
        return False
    model = get_model_entry(provider_id, model_id)
    if not model or not model.get("enabled"):
        return False
    return lane in (model.get("lanes") or [])


def validate_provider_model_for_lane(provider_id: str, model_id: str, lane: str) -> None:
    """Raise ValueError (mapped to 422 by the API) for any impermissible combo."""
    if not is_known_lane(lane):
        raise ValueError(f"UNSUPPORTED_LANE:{lane}")
    pid = str(provider_id or "").lower()
    entry = get_provider_entry(pid)
    if not entry:
        raise ValueError(f"UNKNOWN_PROVIDER:{provider_id}")
    if not entry.get("enabled"):
        raise ValueError(f"PROVIDER_DISABLED:{pid}")
    model = get_model_entry(pid, model_id)
    if not model:
        raise ValueError(f"MODEL_NOT_FOUND:{pid}:{model_id}")
    if not model.get("enabled"):
        raise ValueError(f"MODEL_DISABLED:{pid}:{model_id}")
    if lane not in (model.get("lanes") or []):
        raise ValueError(f"MODEL_NOT_SUPPORTED_FOR_LANE:{pid}:{model_id}:{lane}")
    if not _transport_supports_lane(entry.get("transport") or "", lane):
        raise ValueError(f"TRANSPORT_NOT_SUPPORTED_FOR_LANE:{pid}:{entry.get('transport')}:{lane}")


# --- catalog mutations ----------------------------------------------------

def upsert_provider_model(
    provider_id: str,
    model_id: str,
    label: str | None = None,
    lanes: list[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Add or edit a model for a KNOWN provider. Custom model IDs are allowed
    without a code change. Lanes are transport-gated: a lane the provider's
    transport cannot serve is rejected (fail closed)."""
    pid = str(provider_id or "").lower()
    catalog = _load_catalog()
    entry = catalog["providers"].get(pid)
    if not entry:
        raise ValueError(f"UNKNOWN_PROVIDER:{provider_id}")
    clean_model_id = str(model_id or "").strip()
    if not clean_model_id:
        raise ValueError("MODEL_ID_REQUIRED")

    requested_lanes = _normalize_lanes(lanes if lanes is not None else [])
    transport = entry.get("transport") or ""
    for lane in requested_lanes:
        if not _transport_supports_lane(transport, lane):
            raise ValueError(f"TRANSPORT_NOT_SUPPORTED_FOR_LANE:{pid}:{transport}:{lane}")

    existing = next((m for m in entry["models"] if m["model_id"] == clean_model_id), None)
    if existing is not None:
        if label is not None:
            existing["label"] = str(label) or clean_model_id
        if lanes is not None:
            existing["lanes"] = requested_lanes
        existing["enabled"] = bool(enabled)
    else:
        entry["models"].append(
            {
                "model_id": clean_model_id,
                "label": str(label) if label else clean_model_id,
                "enabled": bool(enabled),
                "lanes": requested_lanes,
                "source": "custom",
            }
        )
    _write_catalog(catalog)
    return summarize_model_catalog()


def disable_provider_model(provider_id: str, model_id: str) -> dict[str, Any]:
    pid = str(provider_id or "").lower()
    catalog = _load_catalog()
    entry = catalog["providers"].get(pid)
    if not entry:
        raise ValueError(f"UNKNOWN_PROVIDER:{provider_id}")
    model = next((m for m in entry["models"] if m["model_id"] == str(model_id)), None)
    if not model:
        raise ValueError(f"MODEL_NOT_FOUND:{pid}:{model_id}")
    model["enabled"] = False
    _write_catalog(catalog)
    return summarize_model_catalog()


def reset_seed_catalog() -> dict[str, Any]:
    """Overwrite the local catalog with the seed catalog (discarding edits)."""
    _write_catalog(seed_catalog_payload())
    return summarize_model_catalog()
