"""Poster recipe / archetype contracts (PR B1 — backend foundation).

A PosterRecipe is a STRUCTURED layout authority: it defines archetype, layout
template, product placement, scene/style, typography, safe zones, and the text
ZONES a poster of that archetype carries. Copy is placed INTO these zones — the
recipe is the structure, copy is the payload.

Two derived outputs feed the response:
- PosterSpec  — the resolved recipe (structure) echoed for the operator/preview.
- OverlaySpec — a DETERMINISTIC layout foundation (percent-based zones + copy).
  This is NOT a rendered/composited poster; a real HTML/SVG/canvas compositor is
  Phase 2 (renderer stays NONE_PHASE_2).

Recipes MUST NOT hardcode medical/disease/therapeutic claims — zone placeholders
are neutral structural labels; operator copy is unsafe-scanned upstream.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PosterZone(BaseModel):
    """A text zone in a poster layout. Percent-based (0-100) so it is
    renderer-agnostic. `source_field` names the draft copy field that feeds it
    (hook / subhook / usp_1 / usp_2 / usp_3 / cta); empty means the zone has no
    operator copy yet and uses its neutral placeholder."""

    zone_id: str
    role: str  # HEADLINE | SUBHEADLINE | CHIP | CTA | FOOTER | ICON_ROW
    source_field: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 100.0
    h: float = 0.0
    align: str = "left"
    font_role: str = "body"  # display | headline | subhead | body | chip | button | caption
    max_chars: int = 0
    placeholder: str = ""  # NEUTRAL structural label only — never a claim


class PosterRecipe(BaseModel):
    recipe_id: str
    archetype: str
    label: str
    description: str = ""
    layout_template: str
    product_placement: str
    background_scene: str
    visual_style: str
    typography_mood: str
    icon_guidance: str = ""
    composition_rules: list[str] = Field(default_factory=list)
    safe_zones: list[str] = Field(default_factory=list)
    chip_slots: list[str] = Field(default_factory=list)
    zones: list[PosterZone] = Field(default_factory=list)
    negative_prompt_additions: list[str] = Field(default_factory=list)
    allowed_text_density: list[str] = Field(default_factory=list)


class PosterRecipeSummary(BaseModel):
    recipe_id: str
    archetype: str
    label: str
    description: str = ""


class PosterSpec(BaseModel):
    """Resolved recipe structure echoed into the prompt-draft response."""

    recipe_id: str
    archetype: str
    layout_template: str
    product_placement: str
    background_scene: str
    visual_style: str
    typography_mood: str
    icon_guidance: str = ""
    composition_rules: list[str] = Field(default_factory=list)
    safe_zones: list[str] = Field(default_factory=list)
    chip_slots: list[str] = Field(default_factory=list)


class OverlayZone(BaseModel):
    zone_id: str
    role: str
    x: float
    y: float
    w: float
    h: float
    align: str
    font_role: str
    max_chars: int
    text: str = ""  # operator slot copy; neutral placeholder if unfilled


class OverlaySpec(BaseModel):
    """DETERMINISTIC LAYOUT FOUNDATION ONLY — not a rendered poster.

    A real compositor (HTML/SVG/canvas) that turns this into crisp text/CTA/chips
    is Phase 2; until then `renderer` is NONE_PHASE_2 and the image-engine poster
    is a visual draft."""

    schema_version: str = "poster-overlay-v1"
    frame_ratio: str = ""
    typography_mood: str = ""
    safe_zones: list[str] = Field(default_factory=list)
    zones: list[OverlayZone] = Field(default_factory=list)
    renderer: str = "NONE_PHASE_2"
    disclaimer: str = (
        "Overlay spec is a deterministic layout foundation only. It is NOT a "
        "rendered poster; crisp headline/chips/CTA/footer text requires a Phase 2 "
        "compositor. The image-engine poster is a visual draft."
    )
