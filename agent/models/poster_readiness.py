"""Poster readiness gate — status taxonomy and API response models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PosterReadinessStatus(StrEnum):
    POSTER_READY = "POSTER_READY"
    POSTER_READY_RESTRICTED = "POSTER_READY_RESTRICTED"
    POSTER_REPAIR_REQUIRED = "POSTER_REPAIR_REQUIRED"
    POSTER_PREVIEW_ONLY = "POSTER_PREVIEW_ONLY"
    POSTER_BLOCKED = "POSTER_BLOCKED"


class PosterImageTier(StrEnum):
    PRODUCT_HERO_POSTER_READY = "PRODUCT_HERO_POSTER_READY"
    PRODUCT_IMAGE_PROMPT_READY = "PRODUCT_IMAGE_PROMPT_READY"
    TEXT_ONLY_POSTER_READY = "TEXT_ONLY_POSTER_READY"
    IMAGE_MISSING = "IMAGE_MISSING"


class PosterRepairAction(BaseModel):
    action_code: str
    label: str
    severity: str = "P2"
    allowed_now: bool = True
    auto_executable: bool = False
    requires_human_approval: bool = False
    recommended_endpoint: str | None = None
    recommended_future_endpoint: str | None = None
    manual_review_required: bool = False
    next_check: str = "recheck_poster_readiness"
    expected_status_after_success: str | None = None
    expected_status_if_no_other_blockers: str | None = None
    notes: str | None = None


class PosterClaimRoute(BaseModel):
    claim_risk_level: str | None = None
    claim_gate: str | None = None
    claim_safe_copy_status: str | None = None
    safe_claim_clearance_required: bool = False
    safe_claim_clearance_status: str = "NOT_CLEARED"
    restricted_safe_poster_route_verified: bool = False


class PosterMappingRoute(BaseModel):
    mapping_status: str | None = None
    mapping_ready: bool = False
    mapping_review_status: str | None = None


class PosterApprovalRoute(BaseModel):
    img_approved: bool = False
    approved_modes: list[str] = Field(default_factory=list)
    production_prompt_approval_status: str | None = None


class PosterReadinessResponse(BaseModel):
    product_id: str
    product_display_name: str | None = None
    poster_status: PosterReadinessStatus
    generation_allowed: bool = False
    restricted_generation_required: bool = False
    preview_allowed: bool = False
    production_allowed: bool = False
    blockers: list[str] = Field(default_factory=list)
    repair_actions: list[PosterRepairAction] = Field(default_factory=list)
    image_tier: PosterImageTier
    claim_route: PosterClaimRoute
    mapping_route: PosterMappingRoute
    approval_route: PosterApprovalRoute
    next_best_action: str | None = None
    recheck_required_after_repair: bool = True
    notes: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)