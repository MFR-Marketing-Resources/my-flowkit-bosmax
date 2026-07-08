"""Recipe-aware poster prompt composer (PR B1).

Given a resolved PosterRecipe + the operator's (already validated + unsafe-scanned)
copy fields + the product truth lock, emit:
  - poster_prompt : a recipe-structured text prompt for the image engine;
  - PosterSpec    : the resolved recipe structure (for preview / response);
  - OverlaySpec   : a DETERMINISTIC layout foundation (percent zones + copy).

This module is self-contained (no import of poster_prompt_draft_service) to avoid
a cycle: build_draft validates copy lengths + unsafe terms BEFORE calling here, so
the composer never re-runs governance — it only structures already-safe inputs.

Guardrails honored:
- No claims are invented here; copy comes from the (safe) operator fields and the
  recipe's neutral structural placeholders.
- OverlaySpec is a foundation only (renderer = NONE_PHASE_2); it does NOT render a
  poster.
"""

from __future__ import annotations

from typing import Any

from agent.models.poster_recipe import (
    OverlaySpec,
    OverlayZone,
    PosterRecipe,
    PosterSpec,
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _zone_copy(zone, fields: dict[str, str]) -> str:
    """Resolve a zone's copy from its source draft field; fall back to the recipe's
    neutral placeholder when the operator has not filled it yet."""
    if zone.source_field:
        value = _norm(fields.get(zone.source_field))
        if value:
            return value
    return zone.placeholder


def _build_poster_spec(recipe: PosterRecipe) -> PosterSpec:
    return PosterSpec(
        recipe_id=recipe.recipe_id,
        archetype=recipe.archetype,
        layout_template=recipe.layout_template,
        product_placement=recipe.product_placement,
        background_scene=recipe.background_scene,
        visual_style=recipe.visual_style,
        typography_mood=recipe.typography_mood,
        icon_guidance=recipe.icon_guidance,
        composition_rules=list(recipe.composition_rules),
        safe_zones=list(recipe.safe_zones),
        chip_slots=list(recipe.chip_slots),
    )


def _build_overlay_spec(recipe: PosterRecipe, fields: dict[str, str]) -> OverlaySpec:
    zones = [
        OverlayZone(
            zone_id=z.zone_id,
            role=z.role,
            x=z.x,
            y=z.y,
            w=z.w,
            h=z.h,
            align=z.align,
            font_role=z.font_role,
            max_chars=z.max_chars,
            text=_zone_copy(z, fields),
        )
        for z in recipe.zones
    ]
    return OverlaySpec(
        frame_ratio=_norm(fields.get("frame_ratio")) or "9:16",
        typography_mood=recipe.typography_mood,
        safe_zones=list(recipe.safe_zones),
        zones=zones,
    )


def _build_poster_prompt(
    recipe: PosterRecipe,
    fields: dict[str, str],
    *,
    product_truth_lock: str,
    visual_instruction: str,
    text_overlay_instruction: str,
    safety_guardrails: list[str],
    restricted_mode: bool,
) -> str:
    copy_lines: list[str] = []
    for z in recipe.zones:
        copy_lines.append(f"- [{z.role}] {z.zone_id}: {_zone_copy(z, fields)}")
    guardrail_block = "\n".join(f"- {g}" for g in safety_guardrails)
    rules_block = "\n".join(f"- {r}" for r in recipe.composition_rules) or "- (none)"
    sections = [
        "=== PRODUCT TRUTH LOCK ===",
        product_truth_lock,
        "=== POSTER RECIPE ===",
        f"Recipe: {recipe.label} ({recipe.recipe_id}) / archetype {recipe.archetype}.",
        f"Layout template: {recipe.layout_template}.",
        f"Product placement: {recipe.product_placement}",
        "=== VISUAL COMPOSITION ===",
        visual_instruction,
        f"Background scene: {recipe.background_scene}",
        f"Visual style: {recipe.visual_style}. Typography mood: {recipe.typography_mood}.",
        f"Frame ratio: {fields.get('frame_ratio') or '9:16'}. Camera: commercial product poster framing.",
        "Composition rules:",
        rules_block,
        "=== COPY SLOTS ===",
        "\n".join(copy_lines) if copy_lines else "- (no zones defined)",
        "=== TEXT OVERLAY ===",
        text_overlay_instruction,
        "=== OPERATOR NOTES ===",
        _norm(fields.get("operator_notes")) or "(none)",
        "=== SAFETY / COMPLIANCE ===",
        guardrail_block,
    ]
    if restricted_mode:
        sections.append("=== RESTRICTED-SAFE MODE ===")
        sections.append(
            "Lifestyle / routine / heritage / portability only. No therapeutic promises."
        )
    return "\n".join(sections)


def compose_recipe_poster(
    *,
    fields: dict[str, str],
    recipe: PosterRecipe,
    product_truth_lock: str,
    visual_instruction: str,
    text_overlay_instruction: str,
    safety_guardrails: list[str],
    restricted_mode: bool,
) -> tuple[str, PosterSpec, OverlaySpec]:
    """Compose the recipe-driven poster prompt + structured specs."""
    poster_prompt = _build_poster_prompt(
        recipe,
        fields,
        product_truth_lock=product_truth_lock,
        visual_instruction=visual_instruction,
        text_overlay_instruction=text_overlay_instruction,
        safety_guardrails=safety_guardrails,
        restricted_mode=restricted_mode,
    )
    return poster_prompt, _build_poster_spec(recipe), _build_overlay_spec(recipe, fields)
