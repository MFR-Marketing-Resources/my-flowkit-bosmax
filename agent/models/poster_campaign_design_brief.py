"""Canonical Campaign Design Brief and copy-route contracts.

The brief is the typed boundary between approved product intelligence and the
poster compiler.  It deliberately keeps provenance and missing evidence
visible; a prose prompt is produced only after this contract has been
resolved.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


POSTER_CAMPAIGN_BRIEF_SCHEMA_VERSION = "poster-campaign-design-brief-v1"
POSTER_COPY_ROUTE_SCHEMA_VERSION = "poster-copy-route-v1"
CAMPAIGN_BRIEF_REVIEW_READY = "READY_FOR_COPY_REVIEW"
CAMPAIGN_BRIEF_REVIEW_BLOCKED = "BLOCKED_MISSING_APPROVED_INTELLIGENCE"
COPY_ROUTE_DRAFT_FALLBACK = "DRAFT_FALLBACK_NOT_PRODUCTION"
COPY_ROUTE_AI_CANDIDATE = "AI_CANDIDATE_REVIEW_REQUIRED"
COPY_ROUTE_PRODUCTION_READY = "PRODUCTION_REVIEW_REQUIRED"


class PosterCampaignDesignBrief(BaseModel):
    """One resolved, provenance-carrying campaign brief.

    Empty required values are retained in the model so diagnostics can show
    precisely what is missing; ``missing_field_blockers`` and ``review_status``
    are the fail-closed decision, not implicit defaults.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = POSTER_CAMPAIGN_BRIEF_SCHEMA_VERSION
    product_id: str = Field(min_length=1)
    # The canonical display name is carried alongside the id so deterministic
    # draft copy never exposes an internal UUID as customer-facing text.
    product_name: str = ""
    approved_snapshot_id: str = ""
    approved_snapshot_version: int | None = None
    product_truth_status: str = "UNVERIFIED"
    approved_claims_status: str = "UNVERIFIED"
    audience: str = ""
    buyer_moment: str = ""
    desire: str = ""
    objection: str = ""
    trigger: str = ""
    selected_message_angle: str = ""
    singular_proposition: str = ""
    reason_to_believe: str = ""
    approved_proof_points: list[str] = Field(default_factory=list, max_length=3)
    tone: str = ""
    creative_territory: str = ""
    visual_metaphor_or_thesis: str = ""
    layout_family: str = ""
    visual_tension: str = ""
    product_anchor: str = ""
    copy_anchor: str = ""
    headline_personality: str = ""
    headline_line_budget: int = Field(default=1, ge=1, le=3)
    type_pairing_id: str = ""
    color_strategy: str = ""
    cta_treatment: str = ""
    proof_treatment: str = ""
    malaysian_context_route: str = ""
    anti_cliche_rules: list[str] = Field(default_factory=list, max_length=12)
    prohibited_claims_and_visuals: list[str] = Field(default_factory=list, max_length=30)
    field_provenance: dict[str, str] = Field(default_factory=dict, max_length=60)
    missing_field_blockers: list[str] = Field(default_factory=list, max_length=40)
    review_status: Literal[
        "READY_FOR_COPY_REVIEW",
        "BLOCKED_MISSING_APPROVED_INTELLIGENCE",
        "REVIEW_REQUIRED",
    ] = CAMPAIGN_BRIEF_REVIEW_BLOCKED
    design_route: str = ""
    layout_variant: str = ""
    objective: str = ""


class CopyRouteScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_specificity: int = Field(ge=0, le=10)
    customer_relevance: int = Field(ge=0, le=10)
    immediate_comprehension: int = Field(ge=0, le=10)
    reason_to_believe: int = Field(ge=0, le=10)
    emotional_commercial_tension: int = Field(ge=0, le=10)
    natural_malaysian_malay: int = Field(ge=0, le=10)
    proof_relevance: int = Field(ge=0, le=10)
    non_redundancy: int = Field(ge=0, le=10)
    visual_fit_line_budget: int = Field(ge=0, le=10)
    differentiation: int = Field(ge=0, le=10)
    claim_safety: int = Field(ge=0, le=10)
    approved_fact_provenance: int = Field(ge=0, le=10)
    total: int = Field(ge=0, le=100)


class CampaignCopyRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = POSTER_COPY_ROUTE_SCHEMA_VERSION
    route_id: str = Field(min_length=1)
    singular_proposition: str = ""
    primary_message: str = ""
    support_message: str = ""
    approved_proof_points: list[str] = Field(default_factory=list, max_length=3)
    cta: str = ""
    tone: str = ""
    intended_buyer_moment: str = ""
    reason_to_believe: str = ""
    copy_provenance: dict[str, str] = Field(default_factory=dict, max_length=30)
    score: CopyRouteScore
    rejected_reasons: list[str] = Field(default_factory=list, max_length=30)
    status: Literal[
        "DRAFT_FALLBACK_NOT_PRODUCTION",
        "AI_CANDIDATE_REVIEW_REQUIRED",
        "PRODUCTION_REVIEW_REQUIRED",
    ] = COPY_ROUTE_DRAFT_FALLBACK
    production_eligible: bool = False


class CampaignCopyRoutesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = POSTER_COPY_ROUTE_SCHEMA_VERSION
    product_id: str
    brief_schema_version: str = POSTER_CAMPAIGN_BRIEF_SCHEMA_VERSION
    requested_candidate_count: int = 5
    candidates: list[CampaignCopyRoute] = Field(default_factory=list, max_length=5)
    top_three_route_ids: list[str] = Field(default_factory=list, max_length=3)
    rejected_candidate_reasons: list[dict[str, Any]] = Field(default_factory=list)
    auto_selected: bool = False
    production_threshold: int = 72
    provider_operation_count: int = 0
    hidden_retry_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CampaignDesignBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    objective: str = "Product Hero"
    selected_angle: str = ""
    copy_layout: dict[str, str] = Field(default_factory=dict)


class CampaignCopyRoutesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    objective: str = "Product Hero"
    selected_angle: str = ""
    copy_layout: dict[str, str] = Field(default_factory=dict)
    invoke_provider: bool = False
