"""Typed QA, human-review and deterministic-variant contracts for Campaign posters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CampaignQAStatus = Literal["PASS", "WARN", "UNVERIFIED", "BLOCK"]
CampaignReviewDecision = Literal["REJECTED", "REVISION_REQUIRED", "APPROVED"]

CAMPAIGN_REJECTION_REASONS = (
    "COPY_GENERIC",
    "COPY_UNSUPPORTED",
    "TYPOGRAPHY_WEAK",
    "HIERARCHY_WEAK",
    "PRODUCT_DRIFT",
    "LABEL_DRIFT",
    "LIGHTING_MISMATCH",
    "BACKGROUND_CLICHE",
    "MALAYSIAN_CONTEXT_WEAK",
    "CTA_DUPLICATED",
    "CONVERSION_WEAK",
    "OTHER",
)


class CampaignQADimension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CampaignQAStatus = "UNVERIFIED"
    evidence: list[str] = Field(default_factory=list, max_length=12)


class CampaignPreProviderLint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool = False
    product_id: str
    reference_pack_status: str = "UNVERIFIED"
    approved_intelligence_status: str = "UNVERIFIED"
    copy_score: int = Field(default=0, ge=0, le=100)
    model: str = "NANO_BANANA_PRO"
    output_intent: str = "CLEAN_KEY_VISUAL"
    # The report must be able to represent an invalid caller request (for
    # example max_provider_operations=2) so the lint can return a structured
    # blocker instead of failing while serialising the evidence itself.
    max_provider_operations: int = Field(default=1, ge=0)
    max_retry_operations: int = Field(default=0, ge=0)
    prompt_marketing_copy_leak: bool = False
    blockers: list[str] = Field(default_factory=list, max_length=40)
    warnings: list[str] = Field(default_factory=list, max_length=40)


class CampaignMachineQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: str = ""
    machine_qa_status: Literal["PASS", "WARN", "FAIL", "UNVERIFIED"] = "UNVERIFIED"
    product_identity: CampaignQADimension = Field(default_factory=CampaignQADimension)
    label: CampaignQADimension = Field(default_factory=CampaignQADimension)
    logo: CampaignQADimension = Field(default_factory=CampaignQADimension)
    geometry: CampaignQADimension = Field(default_factory=CampaignQADimension)
    scale: CampaignQADimension = Field(default_factory=CampaignQADimension)
    perspective: CampaignQADimension = Field(default_factory=CampaignQADimension)
    contact_shadow: CampaignQADimension = Field(default_factory=CampaignQADimension)
    lighting_coherence: CampaignQADimension = Field(default_factory=CampaignQADimension)
    product_background_integration: CampaignQADimension = Field(default_factory=CampaignQADimension)
    unexpected_marketing_text: CampaignQADimension = Field(default_factory=CampaignQADimension)
    duplicated_products: CampaignQADimension = Field(default_factory=CampaignQADimension)
    human_defects: CampaignQADimension = Field(default_factory=CampaignQADimension)
    findings: list[str] = Field(default_factory=list, max_length=40)
    human_review_required: bool = True
    review_state: Literal[
        "GENERATED_OUTPUT_MACHINE_CHECKED",
        "GENERATED_OUTPUT_HUMAN_APPROVED",
    ] = "GENERATED_OUTPUT_MACHINE_CHECKED"


class CampaignPostCompositionQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = False
    checks: dict[str, CampaignQADimension] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list, max_length=60)
    block_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    human_review_required: bool = True
    campaign_review_status: Literal[
        "PENDING_HUMAN_REVIEW",
        "REVISION_REQUIRED",
        "APPROVED",
        "REJECTED",
    ] = "PENDING_HUMAN_REVIEW"
    clean_key_visual_lineage: bool = False
    copy_provenance_verified: bool = False
    output_sha256: str = ""


class WorldClassPosterReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_identity: int = Field(ge=0, le=25)
    product_integration_physics: int = Field(ge=0, le=25)
    typography_copy_hierarchy: int = Field(ge=0, le=20)
    malaysian_context_authenticity: int = Field(ge=0, le=15)
    conversion_strength: int = Field(ge=0, le=15)
    total: int = Field(default=0, ge=0, le=100)
    critical_findings: list[str] = Field(default_factory=list, max_length=20)
    reviewer: str = Field(min_length=1, max_length=120)
    reviewed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    review_notes: str = Field(default="", max_length=4000)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=12)
    decision: CampaignReviewDecision = "REVISION_REQUIRED"

    @model_validator(mode="after")
    def calculate_total(self) -> "WorldClassPosterReview":
        self.total = (
            self.product_identity
            + self.product_integration_physics
            + self.typography_copy_hierarchy
            + self.malaysian_context_authenticity
            + self.conversion_strength
        )
        return self


class CampaignReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: CampaignReviewDecision
    reviewer: str = Field(min_length=1, max_length=120)
    product_identity: int = Field(ge=0, le=25)
    product_integration_physics: int = Field(ge=0, le=25)
    typography_copy_hierarchy: int = Field(ge=0, le=20)
    malaysian_context_authenticity: int = Field(ge=0, le=15)
    conversion_strength: int = Field(ge=0, le=15)
    critical_findings: list[str] = Field(default_factory=list, max_length=20)
    review_notes: str = Field(default="", max_length=4000)
    rejection_reasons: list[str] = Field(default_factory=list, max_length=12)


class CampaignVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: str
    variant_index: int = Field(ge=1, le=3)
    design_route: str
    layout_variant: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_url: str
    key_visual_media_id: str = ""
    provider_operation_count: int = Field(default=0, ge=0)
    max_retry_operations: int = Field(default=0, ge=0)
    kv_reused: bool = True


class CampaignVariantsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    poster_deliverable_id: str
    selected_copy_route: str = ""
    selected_design_route: str = ""
    variants: list[CampaignVariant] = Field(min_length=3, max_length=3)
    key_visual_reused: bool = True
    provider_operation_count: int = 0
    max_retry_operations: int = 0
    warnings: list[str] = Field(default_factory=list)


class CampaignVariantsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    copy_patch: dict[str, str] = Field(default_factory=dict, max_length=8)
    design_route: str = ""
    layout_variant: str = ""


class CampaignDryRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["DRY_RUN_READY", "DRY_RUN_BLOCKED"]
    runtime_sha: str
    product_id: str
    approved_snapshot_id: str = ""
    approved_snapshot_version: int | None = None
    copy_candidate_scores: list[dict[str, Any]] = Field(default_factory=list)
    selected_copy_route: str = ""
    selected_design_route: str = ""
    selected_model: str = "NANO_BANANA_PRO"
    output_intent: str = "CLEAN_KEY_VISUAL"
    prompt_fingerprint: str = ""
    reference_pack_id: str = ""
    reference_role_hashes: dict[str, str] = Field(default_factory=dict)
    maximum_provider_operations: int = 1
    max_retry_operations: int = 0
    manifest_fingerprints: list[str] = Field(default_factory=list, min_length=3, max_length=3)
    expected_review_gates: list[str] = Field(default_factory=list)
    provider_operation_count: int = 0
    blockers: list[str] = Field(default_factory=list)
