from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewDraftStatus = Literal[
    "DRAFT",
    "READY_FOR_REVIEW",
    "NEEDS_REVISION",
    "REJECTED",
    "APPROVED",
]


class ProductIntelligenceAIFillRequest(BaseModel):
    """AI Fill Missing input. selected_fields (optional) restricts enrichment to
    those fields; when omitted, only currently-empty target fields are filled."""

    selected_fields: list[str] | None = None


class ProductIntelligenceAIFillProposal(BaseModel):
    field: str
    status: str
    confidence: float | None = None
    rationale: str = ""
    previous_value: Any = None
    proposed_value: Any = None


class ProductIntelligenceAIFillUnresolved(BaseModel):
    field: str
    status: str
    rationale: str = ""


class ProductIntelligenceAIFillResult(BaseModel):
    """AI Fill Missing result. Proposals are stored in the draft as review-only
    suggestions with provenance; the draft is never auto-approved."""

    draft_id: str
    product_id: str
    review_status: str
    provider: str | None = None
    model: str | None = None
    prompt_version: str
    generated_at: str | None = None
    targeted_fields: list[str] = Field(default_factory=list)
    proposed: list[ProductIntelligenceAIFillProposal] = Field(default_factory=list)
    unresolved: list[ProductIntelligenceAIFillUnresolved] = Field(default_factory=list)
    provider_configured: bool = True
ProductIntelligenceClaimGate = Literal[
    "CLAIM_SAFE",
    "CLAIM_REVIEW_REQUIRED",
    "CLAIM_BLOCKED",
]
ProductIntelligenceClaimRiskLevel = Literal["LOW", "MEDIUM", "HIGH"]


class ProductIntelligenceReviewFieldProvenanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    declared_value: str | None = None
    normalized_value: str | None = None
    source_type: str
    source_url: str | None = None
    source_lane: str | None = None
    evidence_kind: str
    extraction_method: str
    confidence_score: float | None = None
    verification_status: str
    claim_risk_flag: str | None = None
    reviewer_decision: str | None = None
    reviewer_note: str | None = None


class ProductIntelligenceReviewFieldProvenance(
    ProductIntelligenceReviewFieldProvenanceInput,
):
    review_provenance_id: str
    draft_id: str
    product_id: str
    created_at: str
    updated_at: str


class ProductIntelligenceReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    product_id: str
    review_status: ReviewDraftStatus
    product_description: str | None = None
    benefits_json: list[str] = Field(default_factory=list)
    usp_json: list[str] = Field(default_factory=list)
    usage_text: str | None = None
    ingredients_text: str | None = None
    warnings_text: str | None = None
    target_customer_text: str | None = None
    paste_anything_summary: str | None = None
    source_urls_json: dict[str, Any] = Field(default_factory=dict)
    image_evidence_json: dict[str, Any] = Field(default_factory=dict)
    package_notes: str | None = None
    size_or_volume: str | None = None
    product_form_factor: str | None = None
    packaging_description: str | None = None
    product_truth_lock: str | None = None
    claim_gate: ProductIntelligenceClaimGate = "CLAIM_REVIEW_REQUIRED"
    claim_risk_level: ProductIntelligenceClaimRiskLevel = "MEDIUM"
    claim_tokens_json: list[str] = Field(default_factory=list)
    allowed_claims_json: list[str] = Field(default_factory=list)
    blocked_claims_json: list[str] = Field(default_factory=list)
    buyer_persona_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    copy_strategy_summary_json: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float | None = None
    completeness_score: float | None = None
    readiness_status: str | None = None
    reviewer_note: str | None = None
    created_by: str | None = None
    reviewed_by: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_at: str | None = None
    created_at: str
    updated_at: str
    provenance_items: list[ProductIntelligenceReviewFieldProvenance] = Field(
        default_factory=list,
    )


class ProductIntelligenceReviewDraftMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_description: str | None = None
    benefits_json: list[str] | None = None
    usp_json: list[str] | None = None
    usage_text: str | None = None
    ingredients_text: str | None = None
    warnings_text: str | None = None
    target_customer_text: str | None = None
    paste_anything_summary: str | None = None
    source_urls_json: dict[str, Any] | None = None
    image_evidence_json: dict[str, Any] | None = None
    package_notes: str | None = None
    size_or_volume: str | None = None
    product_form_factor: str | None = None
    packaging_description: str | None = None
    product_truth_lock: str | None = None
    allowed_claims_json: list[str] | None = None
    blocked_claims_json: list[str] | None = None
    buyer_persona_snapshot_json: dict[str, Any] | None = None
    copy_strategy_summary_json: dict[str, Any] | None = None
    confidence_score: float | None = None
    reviewer_note: str | None = None
    created_by: str | None = None
    reviewed_by: str | None = None
    provenance_items: list[ProductIntelligenceReviewFieldProvenanceInput] | None = None


class ProductIntelligenceReviewDraftCreateRequest(
    ProductIntelligenceReviewDraftMutation,
):
    pass


class ProductIntelligenceReviewDraftUpdateRequest(
    ProductIntelligenceReviewDraftMutation,
):
    pass


class ProductIntelligenceReviewDraftListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    items: list[ProductIntelligenceReviewDraft] = Field(default_factory=list)


class ProductIntelligenceReviewDraftValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: ProductIntelligenceReviewDraft
    missing_required_fields: list[str] = Field(default_factory=list)
    present_required_fields: list[str] = Field(default_factory=list)
    completeness_score: float
    readiness_status: str
    claim_gate: ProductIntelligenceClaimGate
    claim_risk_level: ProductIntelligenceClaimRiskLevel
    claim_tokens_json: list[str] = Field(default_factory=list)
    allowed_claims_json: list[str] = Field(default_factory=list)
    blocked_claims_json: list[str] = Field(default_factory=list)
    approval_blockers: list[str] = Field(default_factory=list)


class ProductIntelligenceReviewDraftApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str | None = None
    approval_note: str | None = None
    # CLAIM_REVIEW_REQUIRED means "a human must look at the claims", not "this
    # can never be approved". Without an explicit acknowledgement every
    # high-claim-risk product would be permanently unapprovable — a deadlock,
    # not a safeguard. Setting this records that the approver read the claim
    # set and accepts it. CLAIM_BLOCKED is NOT satisfiable this way and still
    # blocks absolutely.
    claim_review_acknowledged: bool = False


class ProductIntelligenceReviewDraftRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str | None = None
    reviewer_note: str | None = None
