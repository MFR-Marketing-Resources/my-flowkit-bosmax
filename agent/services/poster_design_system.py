"""Route-aware campaign design authority.

This module resolves a route from the already-approved product context and
operator intent, then reads the route tokens from POSTER_TEMPLATE_TOKENS.yaml.
It is intentionally a resolver, not a renderer and not a second template
engine.  Exact Commerce callers omit ``design_route`` and retain legacy
template behavior.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


_TOKENS_PATH = Path(__file__).resolve().parent.parent / "authority" / "POSTER_TEMPLATE_TOKENS.yaml"

DESIGN_ROUTE_IDS = (
    "HERITAGE_EDITORIAL",
    "PRODUCT_HERO_SCULPTURE",
    "ROUTINE_LIFESTYLE_EDITORIAL",
    "BOLD_VALUE_COMMERCE",
    "TECHNICAL_PRECISION",
    "MODEL_AMBASSADOR_SPLIT",
)

_HERITAGE_TERMS = (
    "warisan",
    "tradisi",
    "tradisional",
    "herba",
    "herbal",
    "turun-temurun",
)
_TECHNICAL_TERMS = (
    "elektronik",
    "gadget",
    "digital",
    "sensor",
    "kabel",
    "software",
    "hardware",
    "tool",
    "alat",
)
_VALUE_TERMS = ("promo", "tawaran", "jimat", "nilai", "diskaun", "sale", "offer")
_ROUTINE_TERMS = (
    "rutin",
    "harian",
    "rumah",
    "dapur",
    "penjagaan diri",
    "personal care",
    "bayi",
    "anak",
)


class PosterDesignSystemError(ValueError):
    """Fail-closed route/typography authority error."""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _blob(product: dict[str, Any], objective: str, angle: str, audience: str) -> str:
    return " ".join(
        _clean(product.get(key)).casefold()
        for key in (
            "product_display_name",
            "raw_product_title",
            "category",
            "subcategory",
            "type",
            "product_type",
            "bosmax_product_family",
            "physics_class",
            "product_scale",
            "material_behavior",
            "surface_behavior",
        )
    ) + " " + " ".join(
        _clean(value).casefold() for value in (objective, angle, audience)
    )


@lru_cache(maxsize=1)
def _authority() -> dict[str, Any]:
    try:
        data = yaml.safe_load(_TOKENS_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise PosterDesignSystemError("POSTER_DESIGN_AUTHORITY_INVALID") from exc
    routes = data.get("design_routes")
    if not isinstance(routes, dict) or any(route not in routes for route in DESIGN_ROUTE_IDS):
        raise PosterDesignSystemError("POSTER_DESIGN_ROUTES_INCOMPLETE")
    return routes


def route_contract(route_id: str) -> dict[str, Any]:
    route = _clean(route_id).upper()
    if route not in DESIGN_ROUTE_IDS:
        raise PosterDesignSystemError(f"UNKNOWN_DESIGN_ROUTE:{route or 'EMPTY'}")
    value = _authority().get(route)
    if not isinstance(value, dict) or not isinstance(value.get("fonts"), dict):
        raise PosterDesignSystemError(f"DESIGN_ROUTE_INVALID:{route}")
    return value


def _variant_for(route_id: str, *, copy_chars: int, headline_lines: int) -> str:
    variants = list((route_contract(route_id).get("variants") or {}).keys())
    if len(variants) < 2:
        raise PosterDesignSystemError(f"DESIGN_ROUTE_VARIANTS_INCOMPLETE:{route_id}")
    # Short copy earns a more editorial/asymmetric first read; dense copy gets
    # the centered lock-up so the deterministic compositor has more width.
    return variants[0] if copy_chars <= 96 and headline_lines <= 2 else variants[1]


def resolve_design_route(
    product: dict[str, Any],
    *,
    objective: str = "",
    selected_angle: str = "",
    copy_chars: int = 0,
    headline_lines: int = 1,
    audience: str = "",
    human_presence: str = "",
) -> dict[str, Any]:
    """Resolve a route using product/category/context signals, not prop swaps."""

    blob = _blob(product, objective, selected_angle, audience)
    objective_low = _clean(objective).casefold()
    angle_low = _clean(selected_angle).casefold()
    if _clean(human_presence).casefold() in {"model", "ambassador", "with_model"} or "ambassador" in objective_low:
        route = "MODEL_AMBASSADOR_SPLIT"
    elif any(term in blob for term in _TECHNICAL_TERMS):
        route = "TECHNICAL_PRECISION"
    elif any(term in blob for term in _VALUE_TERMS) or any(term in angle_low for term in _VALUE_TERMS):
        route = "BOLD_VALUE_COMMERCE"
    elif any(term in blob for term in _HERITAGE_TERMS):
        route = "HERITAGE_EDITORIAL"
    elif any(term in blob for term in _ROUTINE_TERMS) or "lifestyle" in objective_low:
        route = "ROUTINE_LIFESTYLE_EDITORIAL"
    else:
        route = "PRODUCT_HERO_SCULPTURE"

    route_data = route_contract(route)
    variant = _variant_for(
        route,
        copy_chars=max(0, int(copy_chars or 0)),
        headline_lines=max(1, int(headline_lines or 1)),
    )
    category = _clean(product.get("category")) or "UNSPECIFIED_CATEGORY"
    signals = [
        f"category={category}",
        f"objective={_clean(objective) or 'UNSPECIFIED_OBJECTIVE'}",
        f"angle={_clean(selected_angle) or 'UNSPECIFIED_ANGLE'}",
        f"copy_chars={max(0, int(copy_chars or 0))}",
        f"human_presence={_clean(human_presence) or 'not_selected'}",
    ]
    context_route = (
        "relevant Malaysian usage ritual/material context selected from approved "
        f"category={category}; no generic prop substitution; route={route}"
    )
    return {
        "design_route": route,
        "layout_variant": variant,
        "type_pairing_id": str(route_data.get("type_pairing_id") or ""),
        "font_license": str(route_data.get("font_license") or ""),
        "color_strategy": str(route_data.get("color_strategy") or ""),
        "proof_treatment": str(route_data.get("proof_treatment") or ""),
        "malaysian_context_route": context_route,
        "anti_cliche_rules": [
            "no automatic rattan/cream/gold heritage shorthand",
            "no generic premium gradient or meaningless empty background",
            "no unsupported ingredients, props, people, urgency or price cues",
        ],
        "resolution_signals": signals,
        "route_variants": list((route_data.get("variants") or {}).keys()),
    }


def font_readiness(
    route_id: str,
    *,
    available_families: set[str] | None = None,
) -> dict[str, Any]:
    """Return a fail-closed readiness record for a selected route.

    The browser compositor remains the host truth.  ``available_families`` is
    injectable for deterministic tests and for future platform probes.
    """

    route = route_contract(route_id)
    fonts = route["fonts"]
    required = sorted(
        {
            _clean(str(token.get("family") or "").split(",", 1)[0]).strip("'\"")
            for token in fonts.values()
            if isinstance(token, dict) and _clean(token.get("family"))
        }
    )
    if available_families is None:
        return {
            "status": "HOST_RUNTIME_REQUIRED",
            "required_families": required,
            "font_license": route.get("font_license") or "UNVERIFIED",
        }
    missing = [family for family in required if family not in available_families]
    if missing:
        raise PosterDesignSystemError(
            "FONT_UNAVAILABLE:" + ",".join(missing)
        )
    return {
        "status": "PASS",
        "required_families": required,
        "missing_families": [],
        "font_license": route.get("font_license") or "UNVERIFIED",
    }
