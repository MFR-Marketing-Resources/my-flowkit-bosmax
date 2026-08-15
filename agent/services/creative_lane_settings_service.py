"""Controlled Opening Strategy + Background settings for Faceless and Montage lanes.

SSOT: agent/authority/creative_lane_settings.json

- UI consumes the same option lists as backend validation and tests.
- AUTO is a stable internal id; the display label is "Auto (AI decided)".
- AUTO resolution is deterministic (no paid LLM requirement).
- The historical Hook key is a wire alias for creative strategy only — never
  invents product claims or replaces Copy Register V2 text.
- Background is environment intent only — never overrides product truth.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence

_AUTHORITY = Path(__file__).resolve().parent.parent / "authority" / "creative_lane_settings.json"

AUTO_ID = "AUTO"
ERR_UNKNOWN_HOOK = "ERR_UNKNOWN_HOOK_SETTING"
ERR_UNKNOWN_BACKGROUND = "ERR_UNKNOWN_BACKGROUND_SETTING"
ERR_FACELESS_BACKGROUND_INCOMPATIBLE = "ERR_FACELESS_BACKGROUND_INCOMPATIBLE"
ERR_FACELESS_BACKGROUND_COMPATIBILITY_UNRESOLVED = (
    "ERR_FACELESS_BACKGROUND_COMPATIBILITY_UNRESOLVED"
)

# Existing controlled background ids are intentionally matched against the
# existing Scene Strategy context vocabulary. This is a small semantic bridge,
# not a second persistence authority or background registry.
_BACKGROUND_CONTEXT_TOKENS: dict[str, tuple[str, ...]] = {
    "DALAM_KERETA": ("car", "kereta", "vehicle", "travel", "commute", "road"),
    "LAMAN_RUMAH": ("yard", "outdoor", "garden", "porch", "residential"),
    "AESTHETIC_TABLE": (
        "table",
        "tabletop",
        "counter",
        "shelf",
        "surface",
        "desk",
        "bench",
        "display",
        "mat",
        "sample",
        "vanity",
        "flat lay",
        "clean",
        "inspection",
        "setup",
        "area",
        "equipment",
        "window",
    ),
    "PHARMACY": (
        "pharmacy",
        "farmasi",
        "wellness",
        "health",
        "medicine",
        "clinic",
        "shelf",
        "counter",
    ),
    "KITCHEN": (
        "kitchen",
        "dapur",
        "cooking",
        "cook",
        "pan",
        "dish",
        "ingredient",
        "prep",
        "counter",
    ),
    "RUMAH_AESTHETIC": (
        "home",
        "rumah",
        "bedside",
        "bedroom",
        "living",
        "interior",
        "shelf",
        "routine",
        "toiletry",
        "drawer",
        "room",
        "sink",
        "bathroom",
        "wardrobe",
        "mirror",
        "window",
    ),
}


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


def opening_strategy_options() -> list[dict[str, str]]:
    """Preferred semantic name; ``hook_options`` remains the wire alias."""
    return hook_options()


def opening_strategy_default() -> str:
    return hook_default()


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


def validate_opening_strategy(
    opening_strategy_id: Optional[str],
) -> tuple[bool, Optional[str], Optional[str]]:
    return validate_hook(opening_strategy_id)


def validate_background(background_id: Optional[str]) -> tuple[bool, Optional[str], Optional[str]]:
    value = str(background_id or "").strip() or background_default()
    if value not in background_ids():
        return False, ERR_UNKNOWN_BACKGROUND, (
            f"Background setting '{value}' is not in the controlled vocabulary — "
            f"allowed: {sorted(background_ids())}"
        )
    return True, None, None


def resolve_opening_strategy(
    hook_id: Optional[str],
    *,
    product_cluster: Optional[str] = None,
    has_approved_usp: bool = False,
) -> dict[str, Any]:
    """Resolve the Faceless Opening Strategy, never approved sales copy.

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
        "opening_strategy_id": selected,
        "opening_strategy_operator": raw,
    }


def resolve_hook(
    hook_id: Optional[str],
    *,
    product_cluster: Optional[str] = None,
    has_approved_usp: bool = False,
) -> dict[str, Any]:
    """Backward-compatible wire alias for ``resolve_opening_strategy``."""
    return resolve_opening_strategy(
        hook_id,
        product_cluster=product_cluster,
        has_approved_usp=has_approved_usp,
    )


def resolve_background(
    background_id: Optional[str],
    *,
    scene_context_hint: Optional[str] = None,
    compatible_contexts: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Resolve Background to stable id + environment intent text.

    AUTO picks from a known scene_context_hint when it maps cleanly; otherwise
    AESTHETIC_TABLE (neutral product-forward surface). No LLM call.
    """
    raw = str(background_id or "").strip() or AUTO_ID
    ok, code, detail = validate_background(raw)
    if not ok:
        raise ValueError(f"{code}: {detail}")

    eligible_ids: list[str] | None = None
    if compatible_contexts is not None:
        eligible_ids = compatible_background_ids(compatible_contexts)
        if not eligible_ids:
            raise ValueError(
                f"{ERR_FACELESS_BACKGROUND_COMPATIBILITY_UNRESOLVED}: "
                "no controlled background matches the resolved choreography contexts"
            )

    selected = raw
    resolution = "EXPLICIT"
    if selected == AUTO_ID:
        selected = _auto_background_from_hint(scene_context_hint)
        if eligible_ids is not None and selected not in eligible_ids:
            selected = (
                "AESTHETIC_TABLE"
                if "AESTHETIC_TABLE" in eligible_ids
                else eligible_ids[0]
            )
        resolution = "AUTO_DETERMINISTIC"
    elif eligible_ids is not None and selected not in eligible_ids:
        raise ValueError(
            f"{ERR_FACELESS_BACKGROUND_INCOMPATIBLE}: "
            f"{selected} is not compatible with the resolved choreography contexts"
        )

    intent_map = _doc().get("background_environment_intent") or {}
    intent = intent_map.get(selected, "")
    return {
        "setting_id": selected,
        "display_label": label_for_background(selected),
        "operator_selection": raw,
        "resolution": resolution,
        "environment_intent": intent,
        "product_truth_override": False,
        "compatible_contexts": list(compatible_contexts or []),
        "compatibility_status": "COMPATIBLE" if compatible_contexts is not None else None,
    }


def compatible_background_ids(compatible_contexts: Sequence[str]) -> list[str]:
    """Return existing background ids that match existing scene contexts."""

    contexts = [str(value or "").strip().casefold() for value in compatible_contexts]
    contexts = [value for value in contexts if value]
    if not contexts:
        return []
    eligible: list[str] = []
    for option in background_options():
        background_id = str(option["id"])
        if background_id == AUTO_ID:
            continue
        tokens = _BACKGROUND_CONTEXT_TOKENS.get(background_id, ())
        if any(token in context for context in contexts for token in tokens):
            eligible.append(background_id)
    return eligible


def background_options_for_contexts(
    compatible_contexts: Sequence[str],
) -> list[dict[str, str]]:
    eligible = {AUTO_ID, *compatible_background_ids(compatible_contexts)}
    return [option for option in background_options() if option["id"] in eligible]


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
        "opening_strategy": {
            "default": opening_strategy_default(),
            "options": opening_strategy_options(),
        },
        # ``hook`` is retained as a backward-compatible wire alias for Montage
        # and older clients; Faceless UI uses ``opening_strategy``.
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
