"""Poster copy recommendation kits — API contract."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PosterKitSource(StrEnum):
    APPROVED_COPY_SET = "APPROVED_COPY_SET"
    DRAFT_COPY_SET = "DRAFT_COPY_SET"
    AI_CANDIDATE = "AI_CANDIDATE"
    FALLBACK_TEMPLATE = "FALLBACK_TEMPLATE"


class PosterKitStatus(StrEnum):
    APPROVED = "approved"
    DRAFT = "draft"
    CANDIDATE = "candidate"


class PosterCopyRecommendationRequest(BaseModel):
    product_id: str
    poster_objective: str = "Product awareness"
    poster_type: str = "Product-only hero poster"
    frame_ratio: str = "9:16"
    language: str = "ms"
    visual_route: str = "Premium commercial"
    human_presence_mode: str = "No human / product-forward"
    text_density: str = "medium"
    brand_tone: str = ""
    background_environment: str = ""
    refresh_ai: bool = False


class PosterCopyKit(BaseModel):
    kit_id: str
    status: PosterKitStatus
    source: PosterKitSource
    angle: str = ""
    hook: str = ""
    subhook: str = ""
    usp_1: str = ""
    usp_2: str = ""
    usp_3: str = ""
    cta: str = ""
    poster_type: str = ""
    visual_route: str = ""
    human_presence_mode: str = ""
    frame_ratio: str = ""
    language: str = ""
    text_density: str = ""
    background_environment: str = ""
    brand_tone: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    copy_set_id: str | None = None
    # True only for an approved Copy Set whose formula-validation verdict passed
    # (approve_copy_set enforces + preserves it). Drives "prefer approved" in the UI.
    formula_validated: bool = False


class PosterCopyRecommendationsResponse(BaseModel):
    product_id: str
    product_display_name: str | None = None
    poster_status: str
    generation_allowed: bool = False
    recommendation_source: PosterKitSource | str = ""
    recommendations: list[PosterCopyKit] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    repair_actions: list[dict[str, Any]] = Field(default_factory=list)
    ai_provider_status: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)