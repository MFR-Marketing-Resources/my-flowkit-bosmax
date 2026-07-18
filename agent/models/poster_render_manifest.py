"""Poster Render Manifest — canonical versioned compositor contract
(POSTER_BUILDER_V2).

The manifest is the single source of truth for deterministic rendering,
post-render QA, persistence, reconstruction, preview/save identity and
debugging. It carries the EXACT strings to draw (from an immutable approved
Poster Copy Set version), the resolved typography/component tokens, the
product-safe region and full provenance. The compositor consumes ONLY this.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

POSTER_RENDER_MANIFEST_SCHEMA = "poster-render-manifest-v1"

COMPOSITION_REFERENCE_CONDITIONED = "REFERENCE_CONDITIONED"
COMPOSITION_DETERMINISTIC_COMPOSITE = "DETERMINISTIC_COMPOSITE"  # reserved (no cutout capability yet)

# Zone component kinds the production compositor can draw.
COMPONENT_TEXT = "text"
COMPONENT_CHIP = "chip"
COMPONENT_CTA_BUTTON = "cta_button"
COMPONENT_DISCLAIMER = "disclaimer"


class ManifestRect(BaseModel):
    x: float
    y: float
    w: float
    h: float


class ManifestZone(BaseModel):
    zone_id: str
    role: str
    component: str = COMPONENT_TEXT  # text | chip | cta_button | disclaimer
    rect: ManifestRect
    align: str = "left"
    font_token: str = "body"
    text: str = ""
    max_chars: int = 0


class ProductLayer(BaseModel):
    strategy: str = COMPOSITION_REFERENCE_CONDITIONED
    safe_region: ManifestRect
    asset_ref: str = ""  # reserved for DETERMINISTIC_COMPOSITE (cutout asset)


class ManifestProvenance(BaseModel):
    poster_copy_set_id: str = ""
    poster_copy_set_version: int = 0
    recipe_id: str = ""
    template_version: str = ""
    ai_model: str = ""
    prompt_version: str = ""
    image_model: str = ""
    background_prompt_fingerprint: str = ""
    creative_mode: str = ""
    creative_direction_authority_version: str = ""
    representation_policy_version: str = ""
    composition_schema_version: str = ""
    composition_profile_id: str = ""
    composition_signature: str = ""


class PosterRenderManifest(BaseModel):
    schema_version: str = POSTER_RENDER_MANIFEST_SCHEMA
    canvas: dict[str, int] = Field(default_factory=lambda: {"w": 1080, "h": 1920})
    background_media_id: str = ""
    background_local_path: str = ""
    product_layer: ProductLayer
    zones: list[ManifestZone] = Field(default_factory=list)
    font_tokens: dict[str, Any] = Field(default_factory=dict)
    component_styles: dict[str, Any] = Field(default_factory=dict)
    fit_policy: dict[str, float] = Field(default_factory=lambda: {"min_scale": 0.6, "step": 0.05})
    palette: dict[str, str] = Field(default_factory=dict)
    provenance: ManifestProvenance = Field(default_factory=ManifestProvenance)


class ZoneRenderResult(BaseModel):
    zone_id: str
    fitted: bool
    overflowed: bool
    overlaps_product: bool
    font_scale: float = 1.0
    rendered_text: str = ""


class PosterRenderReport(BaseModel):
    renderer: str = ""
    canvas: dict[str, int] = Field(default_factory=dict)
    output_png: dict[str, Any] = Field(default_factory=dict)
    zones: list[ZoneRenderResult] = Field(default_factory=list)
    missing_zones: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    ok: bool = False


class PosterQAFinding(BaseModel):
    code: str
    severity: str  # BLOCK | WARN
    message: str
    zone_id: str = ""


class PosterQAReport(BaseModel):
    """Lean deterministic QA over the render report (geometry-class checks only;
    heuristic/human checks are labelled WARN and never block drafts)."""

    ok: bool = True
    findings: list[PosterQAFinding] = Field(default_factory=list)
    block_count: int = 0
    warn_count: int = 0


def build_qa_report(report: PosterRenderReport, *, expected_zone_ids: list[str],
                    strict: bool = False) -> PosterQAReport:
    """Deterministic QA over a render report.

    BLOCK (deterministic invariants): render failure, wrong dimensions,
    missing expected text element, text overflow/clipping, zone over product
    region. WARN (deterministic but non-fatal for drafts): font scaled below
    85% of its base size (dense copy).
    """
    findings: list[PosterQAFinding] = []

    def add(code: str, sev: str, msg: str, zone_id: str = "") -> None:
        findings.append(PosterQAFinding(code=code, severity=sev, message=msg, zone_id=zone_id))

    if report.errors:
        for e in report.errors:
            add("RENDER_FAILURE", "BLOCK", e)
    canvas = report.output_png or {}
    if canvas and (canvas.get("width") != 1080 or canvas.get("height") != 1920):
        add("OUTPUT_DIMENSIONS_INVALID", "BLOCK",
            f"output is {canvas.get('width')}x{canvas.get('height')}, expected 1080x1920")
    rendered_ids = {z.zone_id for z in report.zones}
    for zid in expected_zone_ids:
        if zid not in rendered_ids:
            add("MISSING_RENDERED_ELEMENT", "BLOCK", f"zone {zid} was not rendered", zid)
    for z in report.zones:
        if z.overflowed or not z.fitted:
            add("TEXT_OVERFLOW", "BLOCK",
                f"zone {z.zone_id} text does not fit even at minimum scale", z.zone_id)
        if z.overlaps_product:
            add("PRODUCT_REGION_OVERLAP", "BLOCK",
                f"zone {z.zone_id} intersects the AUTHOR-DEFINED product-safe "
                "region (template geometry check — the actual product is NOT "
                "detected; its position/identity/scale need human review)",
                z.zone_id)
        if z.fitted and z.font_scale < 0.85:
            add("DENSE_COPY_SCALED", "WARN",
                f"zone {z.zone_id} shrank to {int(z.font_scale * 100)}% — consider shorter copy",
                z.zone_id)
    blocks = sum(1 for f in findings if f.severity == "BLOCK")
    warns = sum(1 for f in findings if f.severity == "WARN")
    return PosterQAReport(ok=blocks == 0, findings=findings,
                          block_count=blocks, warn_count=warns)
