from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductRegistrationEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str | None = None
    product_payload: dict[str, Any] | None = None
    manual_declared_fields: dict[str, Any] = Field(default_factory=dict)
    target_lane: str = "OWNED_CANONICAL"
    dry_run_only: bool = True
    write_back_requested: bool = False


class ProductRegistrationEvaluateResponse(BaseModel):
    registration_status: str
    write_back_allowed: bool = False
    write_back_performed: bool = False
    dry_run_only: bool = True
    product_truth_status: str = "TRUTH_REVIEW_REQUIRED"
    truth_authority_source: str = "KEYWORD_RULE"
    source_anchor_status: str = "SOURCE_ANCHOR_MISSING"
    mapping_v2_status: str = "NEEDS_REVIEW"
    mapping_confidence: str = "LOW"
    taxonomy_conflict: bool = False
    taxonomy_conflict_reason: str | None = None
    owned_product_lane_status: str = "OWNED_LANE_REVIEW_REQUIRED"
    affiliate_source_contamination_risk: bool = False
    canonical_fields_allowed: list[str] = Field(default_factory=list)
    declared_evidence_fields: list[str] = Field(default_factory=list)
    blocked_fields: list[str] = Field(default_factory=list)
    human_review_fields: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    claim_gate: str = "CLAIM_REVIEW_REQUIRED"
    claim_tokens: list[str] = Field(default_factory=list)
    claim_safety_requires_human_review: bool = True
    scale_truth_status: str = "SCALE_NOT_FOUND"
    product_scale_prompt: str | None = None
    dimension_truth_status: str = "DIMENSIONS_NOT_VERIFIED"
    image_analysis_status: str = "IMAGE_MISSING"
    image_analysis_provider: str = "not_configured"
    image_analysis_visual_confidence: str = "NOT_VERIFIED"
    physics_truth_status: str = "DERIVED_NOT_CANONICAL"
    registration_warnings: list[str] = Field(default_factory=list)
    registration_errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    no_db_write_reason: str | None = None
