"""Poster copy quality contracts (POSTER_EXPERT_SYSTEM_REDESIGN_V1).

A poster is NOT a video script. This module models poster-NATIVE copy
(headline / support line / chips / CTA) and the quality findings an expert
e-commerce poster reviewer would raise: length/word limits, too many ideas,
video-script style, medical/relief wording, and extra-conservative child copy.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Severities
BLOCK = "BLOCK"  # generation must not proceed
WARN = "WARN"  # allowed, surfaced to the operator


class PosterCopyQualityRequest(BaseModel):
    archetype: str = ""
    language: str = "ms"
    # Extra-conservative mode for baby/child audiences (set by caller/readiness).
    child_sensitive: bool = False
    # Poster-native copy (legacy hook/subhook/usp/cta are mapped INTO these).
    poster_headline: str = ""
    poster_support_line: str = ""
    poster_chips: list[str] = Field(default_factory=list)
    poster_cta: str = ""
    product_detail_line: str = ""
    # Archetype-driven chip cap (default 3; some archetypes allow only 2).
    max_chips: int = 3


class PosterCopyFinding(BaseModel):
    code: str
    severity: str  # BLOCK | WARN
    field: str  # headline | support | chips | cta | product_detail | overall
    message: str


class PosterCopyQualityReport(BaseModel):
    ok: bool = True  # True when there are no BLOCK findings
    findings: list[PosterCopyFinding] = Field(default_factory=list)
    block_count: int = 0
    warn_count: int = 0
