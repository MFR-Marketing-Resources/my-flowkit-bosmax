"""Poster prompt draft package — request/response contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PromptPackageStatus(StrEnum):
    DRAFT_READY = "DRAFT_READY"
    PREVIEW_ONLY = "PREVIEW_ONLY"
    BLOCKED = "BLOCKED"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"


class PosterPromptDraftRequest(BaseModel):
    product_id: str
    poster_objective: str = ""
    poster_type: str = ""
    visual_route: str = ""
    human_presence_mode: str = ""
    frame_ratio: str = ""
    language: str = ""
    text_density: str = ""
    angle: str = ""
    hook: str = ""
    subhook: str = ""
    usp_1: str = ""
    usp_2: str = ""
    usp_3: str = ""
    cta: str = ""
    operator_notes: str = ""
    # Copy provenance (Phase D). copy_source is the kit source the copy came from
    # (APPROVED_COPY_SET / DRAFT_COPY_SET / AI_CANDIDATE / FALLBACK_TEMPLATE / manual).
    # Copy that is not an approved Copy Set is review-only unless copy_fallback_confirmed.
    copy_source: str = ""
    copy_set_id: str = ""
    copy_fallback_confirmed: bool = False


class PosterCopyLayout(BaseModel):
    hook: str = ""
    subhook: str = ""
    usp: list[str] = Field(default_factory=list)
    cta: str = ""


class PosterPromptDraftResponse(BaseModel):
    product_id: str
    product_display_name: str | None = None
    poster_status: str
    prompt_package_status: PromptPackageStatus
    generation_allowed: bool = False
    production_allowed: bool = False
    restricted_mode: bool = False
    poster_prompt: str = ""
    negative_prompt: str = ""
    copy_layout: PosterCopyLayout = Field(default_factory=PosterCopyLayout)
    visual_instruction: str = ""
    text_overlay_instruction: str = ""
    product_truth_lock: str = ""
    safety_guardrails: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    repair_actions: list[dict[str, Any]] = Field(default_factory=list)
    readiness_meta: dict[str, Any] = Field(default_factory=dict)
    operator_notes: str = ""
    validation_warnings: list[str] = Field(default_factory=list)