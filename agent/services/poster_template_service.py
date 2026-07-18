"""Poster template service (POSTER_BUILDER_V2).

Fuses the recipe zone-map authority (POSTER_RECIPES.yaml) with the production
template tokens (POSTER_TEMPLATE_TOKENS.yaml) and an approved Poster Copy Set
into a versioned PosterRenderManifest — the compositor's only input.

Read-only authority loader (lru-cached like poster_recipe_service — a YAML edit
needs a process restart).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent.models.poster_copy_set import poster_fields_to_zone_fields
from agent.models.poster_render_manifest import (
    COMPONENT_CHIP,
    COMPONENT_CTA_BUTTON,
    COMPONENT_TEXT,
    ManifestProvenance,
    ManifestRect,
    ManifestZone,
    PosterRenderManifest,
    ProductLayer,
)
from agent.models.poster_recipe import PosterRecipe
from agent.services import poster_recipe_service

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"
_TOKENS_PATH = _AUTHORITY_DIR / "POSTER_TEMPLATE_TOKENS.yaml"

_ROLE_COMPONENT = {
    "CHIP": COMPONENT_CHIP,
    "CTA": COMPONENT_CTA_BUTTON,
}


class PosterTemplateError(Exception):
    def __init__(self, code: str, message: str = "", *, status_code: int = 422):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code


@lru_cache(maxsize=1)
def _load_tokens() -> dict[str, Any]:
    data = yaml.safe_load(_TOKENS_PATH.read_text(encoding="utf-8")) or {}
    if not data.get("font_tokens") or not data.get("recipes"):
        raise PosterTemplateError(
            "POSTER_TEMPLATE_TOKENS_INVALID",
            "POSTER_TEMPLATE_TOKENS.yaml missing font_tokens/recipes",
            status_code=500,
        )
    return data


def template_version() -> str:
    return str(_load_tokens().get("template_version") or "0")


def template_contract(recipe_id: str) -> dict[str, Any]:
    """The merged production template contract for one recipe (recipe zones +
    tokens + product-safe region). Raises when the recipe has no template."""
    recipe = poster_recipe_service.get_recipe(recipe_id)
    if recipe is None:
        raise PosterTemplateError("POSTER_RECIPE_UNKNOWN", f"unknown recipe {recipe_id}",
                                  status_code=404)
    tokens = _load_tokens()
    per_recipe = (tokens.get("recipes") or {}).get(recipe_id)
    if not per_recipe or not per_recipe.get("product_safe_region"):
        raise PosterTemplateError(
            "POSTER_TEMPLATE_CONTRACT_MISSING",
            f"recipe {recipe_id} has no production template tokens/product_safe_region",
            status_code=409,
        )
    return {
        "recipe": recipe,
        "template_version": template_version(),
        "font_tokens": tokens["font_tokens"],
        "component_styles": tokens.get("component_styles") or {},
        "fit_policy": tokens.get("fit_policy") or {"min_scale": 0.6, "step": 0.05},
        "product_safe_region": per_recipe["product_safe_region"],
        "palette": per_recipe.get("palette") or {},
        "background_constraints": per_recipe.get("background_constraints") or "",
    }


def _zone_component(role: str) -> str:
    return _ROLE_COMPONENT.get((role or "").upper(), COMPONENT_TEXT)


def _validate_zones_against_safe_region(
    recipe: PosterRecipe, safe: dict[str, Any]
) -> None:
    """Template invariant: no recipe text zone may intersect the product region."""

    def intersects(a: dict[str, float], b: dict[str, Any]) -> bool:
        return not (
            a["x"] + a["w"] <= float(b["x"])
            or float(b["x"]) + float(b["w"]) <= a["x"]
            or a["y"] + a["h"] <= float(b["y"])
            or float(b["y"]) + float(b["h"]) <= a["y"]
        )

    for z in recipe.zones:
        rect = {"x": z.x, "y": z.y, "w": z.w, "h": z.h}
        if intersects(rect, safe):
            raise PosterTemplateError(
                "POSTER_TEMPLATE_ZONE_OVERLAPS_PRODUCT",
                f"zone {z.zone_id} of {recipe.recipe_id} intersects product_safe_region",
                status_code=500,
            )


def build_render_manifest(
    *,
    recipe_id: str,
    copy_set: dict[str, Any],
    background_media_id: str = "",
    background_local_path: str = "",
    image_model: str = "",
    background_prompt_fingerprint: str = "",
    creative_direction: dict[str, str] | None = None,
) -> PosterRenderManifest:
    """Approved poster copy + template contract → versioned render manifest.

    Empty-copy zones are DROPPED (a poster never renders placeholder text);
    the QA layer then asserts every non-empty zone was actually rendered.
    """
    contract = template_contract(recipe_id)
    recipe: PosterRecipe = contract["recipe"]
    safe = contract["product_safe_region"]
    _validate_zones_against_safe_region(recipe, safe)

    zone_fields = poster_fields_to_zone_fields(copy_set)
    zones: list[ManifestZone] = []
    for z in recipe.zones:
        text = (zone_fields.get(z.source_field) or "").strip() if z.source_field else ""
        if not text:
            continue  # no placeholder text in production posters
        zones.append(
            ManifestZone(
                zone_id=z.zone_id,
                role=z.role,
                component=_zone_component(z.role),
                rect=ManifestRect(x=z.x, y=z.y, w=z.w, h=z.h),
                align=z.align,
                font_token=z.font_role,
                text=text,
                max_chars=z.max_chars,
            )
        )
    disclaimer = str(copy_set.get("disclaimer") or "").strip()
    if disclaimer:
        zones.append(
            ManifestZone(
                zone_id="disclaimer",
                role="FOOTER",
                component="disclaimer",
                rect=ManifestRect(x=8, y=97.0, w=84, h=2.4),
                align="center",
                font_token="caption",
                text=disclaimer,
                max_chars=100,
            )
        )
    if not zones:
        raise PosterTemplateError(
            "POSTER_MANIFEST_NO_COPY",
            "Poster copy set has no renderable text (primary message required)",
        )

    creative_direction = creative_direction or {}
    return PosterRenderManifest(
        background_media_id=background_media_id,
        background_local_path=background_local_path,
        product_layer=ProductLayer(
            safe_region=ManifestRect(
                x=float(safe["x"]), y=float(safe["y"]),
                w=float(safe["w"]), h=float(safe["h"]),
            )
        ),
        zones=zones,
        font_tokens=contract["font_tokens"],
        component_styles=contract["component_styles"],
        fit_policy={
            "min_scale": float(contract["fit_policy"].get("min_scale", 0.6)),
            "step": float(contract["fit_policy"].get("step", 0.05)),
        },
        palette=contract["palette"],
        provenance=ManifestProvenance(
            poster_copy_set_id=str(copy_set.get("poster_copy_set_id") or ""),
            poster_copy_set_version=int(copy_set.get("version") or 0),
            recipe_id=recipe.recipe_id,
            template_version=contract["template_version"],
            ai_model=str(copy_set.get("ai_model") or ""),
            prompt_version=str(copy_set.get("prompt_version") or ""),
            image_model=image_model,
            background_prompt_fingerprint=background_prompt_fingerprint,
            creative_mode=str(creative_direction.get("mode") or ""),
            creative_direction_authority_version=str(creative_direction.get("authority_version") or ""),
            representation_policy_version=str(creative_direction.get("representation_policy_version") or ""),
        ),
    )
