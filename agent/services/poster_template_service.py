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
    COMPOSITION_DETERMINISTIC_COMPOSITE,
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
from agent.services.poster_design_system import (
    PosterDesignSystemError,
    font_readiness,
    route_contract,
)

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


def template_contract(recipe_id: str, design_route: str = "") -> dict[str, Any]:
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
    selected_route = str(design_route or "").strip().upper()
    route_data: dict[str, Any] = {}
    if selected_route:
        try:
            route_data = route_contract(selected_route)
        except PosterDesignSystemError as exc:
            raise PosterTemplateError(str(exc), status_code=409) from exc
        route_fonts = route_data.get("fonts")
        if not isinstance(route_fonts, dict):
            raise PosterTemplateError(
                "POSTER_DESIGN_ROUTE_FONT_TOKENS_MISSING",
                f"design route {selected_route} has no font tokens",
                status_code=500,
            )
        selected_fonts = route_fonts
        try:
            readiness = font_readiness(selected_route)
        except PosterDesignSystemError as exc:
            raise PosterTemplateError(str(exc), status_code=409) from exc
    else:
        selected_fonts = tokens["font_tokens"]
        readiness = {
            "status": "LEGACY_ROUTE_UNVERIFIED",
            "required_families": [],
            "font_license": "LEGACY_HOST_STACK",
        }
    return {
        "recipe": recipe,
        "template_version": template_version(),
        "font_tokens": selected_fonts,
        "component_styles": tokens.get("component_styles") or {},
        "fit_policy": tokens.get("fit_policy") or {"min_scale": 0.6, "step": 0.05},
        "product_safe_region": per_recipe["product_safe_region"],
        "palette": per_recipe.get("palette") or {},
        "background_constraints": per_recipe.get("background_constraints") or "",
        "design_route": selected_route,
        "type_pairing_id": str(route_data.get("type_pairing_id") or ""),
        "font_license": str(route_data.get("font_license") or readiness.get("font_license") or ""),
        "font_readiness": readiness,
        "route_color_strategy": str(route_data.get("color_strategy") or ""),
        "route_proof_treatment": str(route_data.get("proof_treatment") or ""),
        "route_variants": dict(route_data.get("variants") or {}),
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


def manifest_frame_ratio(canvas: dict[str, int] | None = None) -> str:
    """The ACTUAL manifest canvas ratio (reduced), derived from the canvas the
    compositor renders — never a fabricated default."""
    canvas = canvas or {"w": 1080, "h": 1920}
    w, h = int(canvas.get("w") or 0), int(canvas.get("h") or 0)
    if w <= 0 or h <= 0:
        return ""
    from math import gcd

    d = gcd(w, h)
    return f"{w // d}:{h // d}"


def build_render_manifest(
    *,
    recipe_id: str,
    copy_set: dict[str, Any],
    background_media_id: str = "",
    background_local_path: str = "",
    image_model: str = "",
    background_prompt_fingerprint: str = "",
    creative_direction: dict[str, str] | None = None,
    composition_plan: dict[str, Any] | None = None,
    exact_product_layer: dict[str, Any] | None = None,
    design_route: str = "",
    layout_variant: str = "",
    campaign_provenance: dict[str, Any] | None = None,
) -> PosterRenderManifest:
    """Approved poster copy + template contract → versioned render manifest.

    Empty-copy zones are DROPPED (a poster never renders placeholder text);
    the QA layer then asserts every non-empty zone was actually rendered.
    """
    creative_direction = creative_direction or {}
    selected_route = str(
        design_route or creative_direction.get("design_route") or ""
    ).strip().upper()
    selected_variant = str(
        layout_variant or creative_direction.get("layout_variant") or ""
    ).strip().upper()
    contract = template_contract(recipe_id, selected_route)
    recipe: PosterRecipe = contract["recipe"]
    safe = contract["product_safe_region"]
    _validate_zones_against_safe_region(recipe, safe)

    zone_fields = poster_fields_to_zone_fields(copy_set)
    variant_tokens = (contract.get("route_variants") or {}).get(selected_variant, {})
    zones: list[ManifestZone] = []
    for z in recipe.zones:
        text = (zone_fields.get(z.source_field) or "").strip() if z.source_field else ""
        if not text:
            continue  # no placeholder text in production posters
        zone_rect = {"x": z.x, "y": z.y, "w": z.w, "h": z.h}
        if isinstance(variant_tokens, dict):
            zone_prefix = "headline" if z.zone_id == "headline" else "support"
            if z.zone_id in ("headline", "support") and variant_tokens.get(f"{zone_prefix}_x") is not None:
                zone_rect["x"] = float(variant_tokens[f"{zone_prefix}_x"])
            if z.zone_id in ("headline", "support") and variant_tokens.get(f"{zone_prefix}_w") is not None:
                zone_rect["w"] = float(variant_tokens[f"{zone_prefix}_w"])
            if z.zone_id in ("headline", "support") and variant_tokens.get(f"{zone_prefix}_align"):
                z_align = str(variant_tokens[f"{zone_prefix}_align"])
            else:
                z_align = z.align
            if z.zone_id == "cta" and variant_tokens.get("cta_x") is not None:
                zone_rect["x"] = float(variant_tokens["cta_x"])
            if z.zone_id == "cta" and variant_tokens.get("cta_w") is not None:
                zone_rect["w"] = float(variant_tokens["cta_w"])
            if z.zone_id == "cta" and variant_tokens.get("cta_align"):
                z_align = str(variant_tokens["cta_align"])
        else:
            z_align = z.align
        zones.append(
            ManifestZone(
                zone_id=z.zone_id,
                role=z.role,
                component=_zone_component(z.role),
                rect=ManifestRect(**zone_rect),
                align=z_align,
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
                rect=ManifestRect(x=8, y=92.3, w=84, h=2.4),
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

    # The canonical composition plan is resolved ONCE by the caller (with the
    # real product-truth / identity / operator / recipe constraints) and passed
    # in verbatim. The manifest never re-derives a second plan from fabricated
    # defaults — an absent plan is preserved honestly as absent (legacy path).
    composition_plan = composition_plan or {}
    campaign_provenance = campaign_provenance or {}
    font_status = str((contract.get("font_readiness") or {}).get("status") or "")
    return PosterRenderManifest(
        background_media_id=background_media_id,
        background_local_path=background_local_path,
        product_layer=ProductLayer(
            strategy=(COMPOSITION_DETERMINISTIC_COMPOSITE if exact_product_layer else "REFERENCE_CONDITIONED"),
            safe_region=ManifestRect(
                x=float(safe["x"]), y=float(safe["y"]),
                w=float(safe["w"]), h=float(safe["h"]),
            )
            , **(exact_product_layer or {})
        ),
        zones=zones,
        font_tokens=contract["font_tokens"],
        component_styles=contract["component_styles"],
        fit_policy={
            "min_scale": float(contract["fit_policy"].get("min_scale", 0.6)),
            "step": float(contract["fit_policy"].get("step", 0.05)),
        },
        palette=contract["palette"],
        design_route=selected_route,
        layout_variant=selected_variant,
        provenance=ManifestProvenance(
            poster_copy_set_id=str(copy_set.get("poster_copy_set_id") or ""),
            poster_copy_set_version=int(copy_set.get("version") or 0),
            recipe_id=recipe.recipe_id,
            template_version=contract["template_version"],
            ai_model=str(copy_set.get("ai_model") or ""),
            prompt_version=str(copy_set.get("prompt_version") or ""),
            image_model=image_model,
            background_prompt_fingerprint=(
                background_prompt_fingerprint
                or str(campaign_provenance.get("clean_key_visual_prompt_fingerprint") or "")
            ),
            clean_key_visual_prompt_fingerprint=str(
                campaign_provenance.get("clean_key_visual_prompt_fingerprint") or ""
            ),
            creative_mode=str(creative_direction.get("mode") or ""),
            creative_direction_authority_version=str(creative_direction.get("authority_version") or ""),
            representation_policy_version=str(creative_direction.get("representation_policy_version") or ""),
            composition_schema_version=str(composition_plan.get("schema_version") or ""),
            composition_profile_id=str(composition_plan.get("profile_id") or ""),
            composition_signature=str(composition_plan.get("signature") or ""),
            design_route=selected_route,
            layout_variant=selected_variant,
            type_pairing_id=str(contract.get("type_pairing_id") or ""),
            font_readiness_status=font_status,
            approved_snapshot_id=str(campaign_provenance.get("approved_snapshot_id") or ""),
            approved_snapshot_version=campaign_provenance.get("approved_snapshot_version"),
            design_brief_version=str(campaign_provenance.get("design_brief_version") or ""),
            copy_route_id=str(campaign_provenance.get("copy_route_id") or ""),
            reference_pack_id=str(campaign_provenance.get("reference_pack_id") or ""),
            reference_role_hashes={
                str(key): str(value)
                for key, value in (campaign_provenance.get("reference_role_hashes") or {}).items()
                if str(key).strip() and str(value).strip()
            },
            requested_provider_model=str(
                campaign_provenance.get("requested_provider_model") or image_model or ""
            ),
            provider_batch_id=str(campaign_provenance.get("provider_batch_id") or ""),
            provider_operation_id=str(campaign_provenance.get("provider_operation_id") or ""),
            provider_operation_id_status=str(
                campaign_provenance.get("provider_operation_id_status") or ""
            ),
            provider_operation_budget=int(campaign_provenance.get("provider_operation_budget") or 0),
            actual_retry_count=int(campaign_provenance.get("actual_retry_count") or 0),
            raw_key_visual_media_id=str(
                campaign_provenance.get("raw_key_visual_media_id") or background_media_id or ""
            ),
            raw_key_visual_sha256=str(campaign_provenance.get("raw_key_visual_sha256") or ""),
            composition_plan=composition_plan,
        ),
    )
