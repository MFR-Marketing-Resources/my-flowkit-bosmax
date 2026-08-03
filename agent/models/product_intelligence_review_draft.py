from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewDraftStatus = Literal[
    "DRAFT",
    "READY_FOR_REVIEW",
    "NEEDS_REVISION",
    "REJECTED",
    "APPROVED",
    # B-586-04. Written ONLY by duplicate convergence, never by a reviewer: it records
    # that another draft for this product became canonical. Terminal, so a superseded
    # row keeps all of its evidence without competing for the one-open-draft slot.
    "SUPERSEDED",
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

# Mission-08D. The three governed answers to "this required field is empty and the
# source does not supply it". Stored as a field-scoped provenance row on the CURRENT
# draft — never as a placeholder string in the knowledge value column, which would be
# indistinguishable from real knowledge everywhere downstream.
FieldAbsenceDisposition = Literal[
    "NOT_STATED_IN_SOURCE",     # a source WAS inspected and omits the fact; satisfies the blocker
    "NOT_APPLICABLE",           # fact does not exist for this product type
    "REQUIRES_EXTERNAL_EVIDENCE",  # documented as unresolved; remains BLOCKING
    # PI-11: the live marketplace source cannot be acquired (e.g. TikTok automation is
    # externally blocked), so the field's absence is a truthful SUPPLY gap, not a claim that
    # an inspected source omitted it. Distinct from NOT_STATED_IN_SOURCE (which asserts a
    # source was read) and from REQUIRES_EXTERNAL_EVIDENCE (which stays blocking): a product
    # can be COPY_GROUNDING_READY with source-unavailable KNOWLEDGE fields, so this SATISFIES
    # the field blocker as a governed absence — while never being dressed up as evidence.
    "SOURCE_UNAVAILABLE",
]


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
    # PI-13 revision lineage (nullable): set when cloned into a revision draft
    inherited_from_draft_id: str | None = None
    inherited_from_snapshot_id: str | None = None
    inherited_at: str | None = None


class ProductIntelligenceReviewFieldProvenance(
    ProductIntelligenceReviewFieldProvenanceInput,
):
    review_provenance_id: str
    draft_id: str
    product_id: str
    created_at: str
    updated_at: str
    # PI-13 revision lineage (nullable): set when this provenance row was cloned into a revision draft
    inherited_from_draft_id: str | None = None
    inherited_from_snapshot_id: str | None = None
    inherited_at: str | None = None


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
    # PI-13 revision lineage (nullable)
    revision_of_draft_id: str | None = None
    revision_of_snapshot_id: str | None = None
    revision_reason: str | None = None
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
    # Mission-08D governed absence. A required field the source does not state can be
    # RESOLVED (reviewer-attributed, note-backed) instead of deadlocking approval — and
    # that resolution is reported here as its own category, never folded into "present".
    # governed_absent_fields: field -> disposition currently satisfying its blocker.
    governed_absent_fields: dict[str, FieldAbsenceDisposition] = Field(default_factory=dict)
    # Fields whose only disposition is REQUIRES_EXTERNAL_EVIDENCE — still BLOCKING.
    unresolved_external_fields: list[str] = Field(default_factory=list)
    # Which of the still-missing fields MAY be resolved with a disposition, and which
    # dispositions the category matrix permits for each (the UI disables the rest with
    # this server-derived truth instead of guessing).
    disposition_options: dict[str, list[FieldAbsenceDisposition]] = Field(default_factory=dict)


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
    # Product-KNOWLEDGE fields (ingredients/usage/warnings/provenance) are not
    # copy inputs — copy is grounded on persona, angles, benefits and the claim
    # gate. Setting this approves a draft for COPY GROUNDING once every
    # copy-critical field is present, without blocking on missing product
    # knowledge. Copy-critical fields still block, and the claim gate
    # (CLAIM_BLOCKED / CLAIM_REVIEW_REQUIRED) is NEVER bypassed by this.
    allow_incomplete_product_knowledge: bool = False


class ProductIntelligenceReviewDraftRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rejected_by: str | None = None
    reviewer_note: str | None = None




class ProductIntelligenceFieldDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    disposition: FieldAbsenceDisposition
    # Accountability is the point: no anonymous dispositions and no empty rationales.
    reviewed_by: str
    reviewer_note: str
