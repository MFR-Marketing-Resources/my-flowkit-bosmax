"""Category → visual auto-adapt resolver (Phase C — WRNA techniques).

Read-only lru-cached loader over agent/authority/CATEGORY_SCENE_MODEL_MAP.yaml.
Consumed ONLY by the WRNA IMG presets and poster recipe — never by existing
presets/recipes. Fail-closed: unknown category or malformed file resolves to
the default block (presets keep generating)."""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_AUTHORITY_PATH = (
    Path(__file__).resolve().parents[1] / "authority" / "CATEGORY_SCENE_MODEL_MAP.yaml"
)

_FALLBACK_DEFAULT = {
    "background": "a clean neutral premium studio surface with soft directional light",
    "model": "a Malaysian adult presenter with modest commercial styling",
    "float_elements": (
        "subtle abstract light streaks and soft depth particles that reinforce "
        "a premium feel"
    ),
}


@lru_cache(maxsize=1)
def _load_map() -> dict[str, Any]:
    try:
        raw = yaml.safe_load(_AUTHORITY_PATH.read_text(encoding="utf-8")) or {}
        default = {**_FALLBACK_DEFAULT, **(raw.get("default") or {})}
        categories = [
            entry
            for entry in (raw.get("categories") or [])
            if isinstance(entry, dict) and entry.get("match")
        ]
        return {"default": default, "categories": categories}
    except Exception as exc:  # noqa: BLE001 — fail closed to default-only
        logger.error("CATEGORY_SCENE_MODEL_MAP.yaml unreadable — defaults only: %s", exc)
        return {"default": dict(_FALLBACK_DEFAULT), "categories": []}


def _normalize(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def resolve_category_adapt(product: dict[str, Any] | None) -> dict[str, str]:
    """Resolve {background, model, float_elements} for a product by normalized
    contains-match over its category/subcategory/type/name. Always returns a
    complete dict (default fail-closed)."""
    data = _load_map()
    haystack = " ".join(
        _normalize(v)
        for v in (
            (product or {}).get("category"),
            (product or {}).get("subcategory"),
            (product or {}).get("type"),
            (product or {}).get("product_display_name"),
            (product or {}).get("raw_product_title"),
            (product or {}).get("name"),
        )
    )
    for entry in data["categories"]:
        for token in entry.get("match") or []:
            if _normalize(token) and _normalize(token) in haystack:
                return {**data["default"], **{
                    k: v for k, v in entry.items() if k != "match" and v
                }}
    return dict(data["default"])
