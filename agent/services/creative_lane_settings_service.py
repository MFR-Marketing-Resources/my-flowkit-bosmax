"""Controlled Hook + Background settings for Faceless and Montage lanes.

SSOT: agent/authority/creative_lane_settings.json

- UI consumes the same option lists as backend validation and tests.
- AUTO is a stable internal id; the display label is "Auto (AI decided)".
- AUTO resolution is deterministic (no paid LLM requirement).
- Hook is creative strategy only — never invents product claims.
- Background is environment intent only — never overrides product truth.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_AUTHORITY = Path(__file__).resolve().parent.parent / "authority" / "creative_lane_settings.json"

AUTO_ID = "AUTO"
ERR_UNKNOWN_HOOK = "ERR_UNKNOWN_HOOK_SETTING"
ERR_UNKNOWN_BACKGROUND = "ERR_UNKNOWN_BACKGROUND_SETTING"


@lru_cache(maxsize=1)
def _doc() -> dict[str, Any]:
    return json.loads(_AUTHORITY.read_text(encoding="utf-8"))


def settings_document() -> dict[str, Any]:
    """Full authority document (read-only copy for API/tests)."""
    return json.loads(json.dumps(_doc()))


def hook_options() -> list[dict[str, str]]:
    return [dict(o) for o in _doc()["hook"]["options"]]


def background_options() -> list[dict[str, str]]:
    return [dict(o) for o in _doc()["background"]["options"]]


def hook_default() -> str:
    return str(_doc()["hook"]["default"])


def background_default() -> str:
    return str(_doc()["background"]["default"])


def hook_ids() -> set[str]:
    return {str(o["id"]) for o in hook_options()}


def background_ids() -> set[str]:
    return {str(o["id"]) for o in background_options()}


def label_for_hook(hook_id: str) -> str:
    for o in hook_options():
        if o["id"] == hook_id:
            return o["label"]
    return hook_id


def label_for_background(background_id: str) -> str:
    for o in background_options():
        if o["id"] == background_id:
            return o["label"]
    return background_id


def validate_hook(hook_id: Optional[str]) -> tuple[bool, Optional[str], Optional[str]]:
    value = str(hook_id or "").strip() or hook_default()
    if value not in hook_ids():
        return False, ERR_UNKNOWN_HOOK, (
            f"Hook setting '{value}' is not in the controlled vocabulary — "
            f"allowed: {sorted(hook_ids())}"
        )
    return True, None, None


def validate_background(background_id: Optional[str]) -> tuple[bool, Optional[str], Optional[str]]:
    value = str(background_id or "").strip() or background_default()
    if value not in background_ids():
        return False, ERR_UNKNOWN_BACKGROUND, (
            f"Background setting '{value}' is not in the controlled vocabulary — "
            f"allowed: {sorted(background_ids())}"
        )
    return True, None, None


def resolve_hook(
    hook_id: Optional[str],
    *,
    product_cluster: Optional[str] = None,
    has_approved_usp: bool = False,
) -> dict[str, Any]:
    """Resolve Hook to a stable internal id + display label + strategy intent.

    AUTO is deterministic:
    - if product has approved USP / truth angles → GENERAL_USP_PRODUCT
    - else → GENERAL_USP_PRODUCT still (safe default; never invent promo hooks)
    No LLM call.
    """
    raw = str(hook_id or "").strip() or AUTO_ID
    ok, code, detail = validate_hook(raw)
    if not ok:
        raise ValueError(f"{code}: {detail}")

    selected = raw
    resolution = "EXPLICIT"
    if selected == AUTO_ID:
        # Prefer general USP; promo-style hooks require explicit operator choice.
        selected = "GENERAL_USP_PRODUCT"
        resolution = "AUTO_DETERMINISTIC"
        _ = (product_cluster, has_approved_usp)  # reserved for future knowledge rules

    intent = (_doc().get("hook_strategy_intent") or {}).get(selected, "")
    return {
        "setting_id": selected,
        "display_label": label_for_hook(selected),
        "operator_selection": raw,
        "resolution": resolution,
        "strategy_intent": intent,
        "claim_authority": "PRODUCT_TRUTH_ONLY",
    }


def resolve_background(
    background_id: Optional[str],
    *,
    scene_context_hint: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve Background to stable id + environment intent text.

    AUTO picks from a known scene_context_hint when it maps cleanly; otherwise
    AESTHETIC_TABLE (neutral product-forward surface). No LLM call.
    """
    raw = str(background_id or "").strip() or AUTO_ID
    ok, code, detail = validate_background(raw)
    if not ok:
        raise ValueError(f"{code}: {detail}")

    selected = raw
    resolution = "EXPLICIT"
    if selected == AUTO_ID:
        selected = _auto_background_from_hint(scene_context_hint)
        resolution = "AUTO_DETERMINISTIC"

    intent_map = _doc().get("background_environment_intent") or {}
    intent = intent_map.get(selected, "")
    return {
        "setting_id": selected,
        "display_label": label_for_background(selected),
        "operator_selection": raw,
        "resolution": resolution,
        "environment_intent": intent,
        "product_truth_override": False,
    }


def _auto_background_from_hint(hint: Optional[str]) -> str:
    text = str(hint or "").strip().casefold()
    if not text:
        return "AESTHETIC_TABLE"
    mapping = (
        ("kereta", "DALAM_KERETA"),
        ("car", "DALAM_KERETA"),
        ("laman", "LAMAN_RUMAH"),
        ("yard", "LAMAN_RUMAH"),
        ("pharmacy", "PHARMACY"),
        ("farmasi", "PHARMACY"),
        ("kitchen", "KITCHEN"),
        ("dapur", "KITCHEN"),
        ("table", "AESTHETIC_TABLE"),
        ("rumah", "RUMAH_AESTHETIC"),
        ("home", "RUMAH_AESTHETIC"),
    )
    for needle, bid in mapping:
        if needle in text:
            return bid
    return "AESTHETIC_TABLE"


def public_settings_payload() -> dict[str, Any]:
    """API shape for dashboard consumers."""
    auto = _doc()["auto"]
    return {
        "version": _doc().get("_meta", {}).get("version", "CREATIVE_LANE_SETTINGS_v1"),
        "auto": dict(auto),
        "hook": {
            "default": hook_default(),
            "options": hook_options(),
        },
        "background": {
            "default": background_default(),
            "options": background_options(),
        },
        "semantics": (_doc().get("_meta") or {}).get("semantics", {}),
        "source": "agent/authority/creative_lane_settings.json",
    }
