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


class RegistrationReviewDraft(BaseModel):
    review_draft_id: str
    review_status: str  # REVIEW_READY / NEEDS_HUMAN_REVIEW / BLOCKED
    source_lane: str
    
    # Evidence vs Candidates
    declared_evidence_fields: dict[str, Any] = Field(default_factory=dict)
    system_inferred_fields: dict[str, Any] = Field(default_factory=dict)
    canonical_candidate_fields: dict[str, Any] = Field(default_factory=dict)
    
    # Review / Safety
    human_review_fields: list[str] = Field(default_factory=list)
    blocked_fields: list[str] = Field(default_factory=list)
    missing_required_evidence: list[str] = Field(default_factory=list)
    
    # Gate statuses (mirroring ProductRegistrationEvaluateResponse)
    claim_gate: str = "CLAIM_REVIEW_REQUIRED"
    claim_tokens: list[str] = Field(default_factory=list)
    claim_risk_level: str = "HIGH"
    copy_safety_notes: str | None = None
    
    taxonomy_status: str = "NEEDS_REVIEW"
    taxonomy_conflict: bool = False
    taxonomy_conflict_reason: str | None = None
    
    product_family_status: str = "NEEDS_REVIEW"
    physics_status: str = "NEEDS_REVIEW"
    scale_truth_status: str = "NEEDS_REVIEW"
    registration_gate_status: str = "NEEDS_REVIEW"
    
    # Governance
    write_back_allowed: bool = False
    write_back_performed: bool = False
    write_back_status: str = "READ_ONLY_REVIEW_PREVIEW"
    
    user_actions: list[str] = Field(default_factory=list)
    approval_checklist: dict[str, bool] = Field(default_factory=dict)
    
    readiness_by_mode: dict[str, Any] = Field(default_factory=dict)
    
    provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    draft_freshness_status: str = "FRESH"
    last_evidence_edit_at: str | None = None
    last_recomputed_at: str | None = None
    image_asset_status: str = "IMAGE_REFERENCE_MISSING"
    image_asset_detail: str | None = None
    
    created_at: str | None = None
    updated_at: str | None = None
    rejection_checklist: dict[str, bool] = Field(default_factory=dict)


class RegistrationReviewDraftFieldDecisions(BaseModel):
    approved_fields: list[str] = Field(default_factory=list)
    rejected_fields: list[str] = Field(default_factory=list)
    edited_declared_evidence: dict[str, Any] = Field(default_factory=dict)
    requested_more_evidence_fields: list[str] = Field(default_factory=list)


class RegistrationReviewDraftEvidencePatchRequest(BaseModel):
    product_name: str | None = None
    product_knowledge_text: str | None = None
    benefits_text: str | None = None
    usage_text: str | None = None
    target_customer_text: str | None = None
    ingredients_text: str | None = None
    warnings_text: str | None = None
    paste_anything_about_product: str | None = None

    price: float | None = None
    currency: str | None = None
    commission_amount: float | None = None
    commission_rate: str | None = None

    size_or_volume: str | None = None
    package_notes: str | None = None

    product_url: str | None = None
    source_url: str | None = None
    tiktok_product_url: str | None = None
    tiktok_shop_url: str | None = None
    image_url: str | None = None
    local_image_path: str | None = None
    image_base64: str | None = None
    image_filename: str | None = None

    hook_angles: list[str] | None = None
    cta_angles: list[str] | None = None
    recompute: bool = True


class RegistrationCommitRequest(BaseModel):
    draft_id: str
    write_back_confirmed: bool = False
    user_confirmation_phrase: str | None = None  # Expected: REGISTER_OWNED_PRODUCT
    commit_reason: str | None = None
