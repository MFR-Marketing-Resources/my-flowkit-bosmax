from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ProductTruthProvenance(BaseModel):
    source_origin: str = "UNKNOWN"  # FASTMOSS | TIKTOKSHOP | MANUAL | INTERNAL_CANONICAL | TEST | UNKNOWN
    commerce_mode: str = "UNKNOWN"  # OWN_STORE | AFFILIATE | HYBRID | UNKNOWN
    source_url: str | None = None
    tiktok_product_url: str | None = None
    source_file_hint: str | None = None
    ingestion_timestamp: str | None = None
    builder_version: str = "1.0.0"


class ProductTruthSourceAnchors(BaseModel):
    source_category: str | None = None
    source_subcategory: str | None = None
    source_product_type: str | None = None
    source_anchor_status: str = "UNKNOWN"  # PRESENT | PARTIAL | MISSING | UNVERIFIED | WEAK_FILE_HINT_ONLY | COLUMN_NOT_FOUND
    source_anchor_origin: str = "UNKNOWN"  # FASTMOSS_ROW | FASTMOSS_WORKBOOK | FASTMOSS_SOURCE_FILE_HINT | TIKTOKSHOP_DOM | MANUAL_DECLARED | UNKNOWN
    source_anchor_columns: list[str] = Field(default_factory=list)
    source_anchor_notes: list[str] = Field(default_factory=list)


class ProductTruthDeclaredEvidence(BaseModel):
    user_category: str | None = None
    user_subcategory: str | None = None
    user_product_type: str | None = None
    manual_authority_status: str = "NOT_PROVIDED"  # NOT_PROVIDED | DECLARED_PENDING_RECONCILIATION | VERIFIED | CONTRADICTED
    review_required: bool = False


class ProductTruthTextEvidence(BaseModel):
    raw_title: str | None = None
    normalized_title: str | None = None
    description: str | None = None
    description_sources: list[str] = Field(default_factory=list)
    extracted_keywords: list[str] = Field(default_factory=list)
    keyword_matches: list[str] = Field(default_factory=list)
    negative_exclusion_matches: list[str] = Field(default_factory=list)


class ProductTruthDimensionNormalized(BaseModel):
    length_cm: float | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    display: str | None = None


class ProductTruthSpecEvidence(BaseModel):
    raw_specs: dict[str, Any] = Field(default_factory=dict)
    normalized_specs: dict[str, Any] = Field(default_factory=dict)
    dimension_evidence: str | None = None
    dimension_normalized_cm: ProductTruthDimensionNormalized = Field(default_factory=ProductTruthDimensionNormalized)
    material_evidence: str | None = None
    power_voltage_evidence: str | None = None
    spec_status: str = "MISSING"  # PRESENT | PARTIAL | MISSING


class ProductTruthVisualTrait(BaseModel):
    value: str | None = None
    confidence: float | None = None


class ProductTruthAnalyzedTraits(BaseModel):
    scale: ProductTruthVisualTrait = Field(default_factory=ProductTruthVisualTrait)
    package: ProductTruthVisualTrait = Field(default_factory=ProductTruthVisualTrait)
    text: list[str] = Field(default_factory=list)
    text_confidence: float | None = None


class ProductTruthVisualEvidence(BaseModel):
    image_urls: list[str] = Field(default_factory=list)
    image_analysis_status: str = "UNKNOWN"  # ANALYZED | VISION_PROVIDER_NOT_CONFIGURED | IMAGE_MISSING | IMAGE_INACCESSIBLE | ANALYSIS_FAILED | UNKNOWN
    analyzed_traits: ProductTruthAnalyzedTraits = Field(default_factory=ProductTruthAnalyzedTraits)
    provider: str = "unknown"


class ProductTruthCommerceEvidence(BaseModel):
    price: float | None = None
    currency: str | None = None
    commission_rate: str | None = None
    commission_amount: float | None = None
    margin: float | None = None
    sold_count: int | None = None
    shop_count: int | None = None
    shop_names: list[str] = Field(default_factory=list)


class ProductTruthClaimEvidence(BaseModel):
    claim_tokens: list[str] = Field(default_factory=list)
    claim_sources: list[str] = Field(default_factory=list)
    claim_gate_preview: str = "UNKNOWN"  # CLAIM_SAFE | CLAIM_REVIEW_REQUIRED | CLAIM_BLOCKED | UNKNOWN


class ProductTruthNegativeConstraints(BaseModel):
    category_boundary_locks: list[str] = Field(default_factory=list)
    forbidden_family_transitions: list[str] = Field(default_factory=list)
    negative_keyword_rules: list[str] = Field(default_factory=list)
    matched_negative_constraints: list[str] = Field(default_factory=list)


class ProductTruthReconciliation(BaseModel):
    contradiction_flags: list[str] = Field(default_factory=list)
    matched_negative_constraints: list[str] = Field(default_factory=list)
    evidence_scores: dict[str, float] = Field(default_factory=dict)
    authority_decision: str = "UNKNOWN"  # SOURCE_ANCHOR | TIKTOKSHOP_DOM | MANUAL_DECLARED | KEYWORD_RULE | IMAGE_CORROBORATED | RECONCILIATION_FAILED | REVIEW_REQUIRED
    confidence_score: float = 0.0
    confidence_label: str = "NEEDS_REVIEW"  # HIGH | MEDIUM | LOW | NEEDS_REVIEW
    warnings: list[str] = Field(default_factory=list)
    provenance_notes: list[str] = Field(default_factory=list)


class ProductTruthFinalOutputPreview(BaseModel):
    final_group: str | None = None
    final_sub_group: str | None = None
    final_type_of_product: str | None = None
    bosmax_product_family: str | None = None
    package_form: str | None = None
    physical_state: str | None = None
    product_scale_class: str | None = None
    copy_route: str = "UNKNOWN"  # DIRECT | STEALTH | REVIEW_REQUIRED | UNKNOWN
    claim_gate: str = "UNKNOWN"  # CLAIM_SAFE | CLAIM_REVIEW_REQUIRED | CLAIM_BLOCKED | UNKNOWN


class ProductTruthProfile(BaseModel):
    product_id: str | None = None
    provenance: ProductTruthProvenance = Field(default_factory=ProductTruthProvenance)
    source_anchors: ProductTruthSourceAnchors = Field(default_factory=ProductTruthSourceAnchors)
    declared_evidence: ProductTruthDeclaredEvidence = Field(default_factory=ProductTruthDeclaredEvidence)
    text_evidence: ProductTruthTextEvidence = Field(default_factory=ProductTruthTextEvidence)
    spec_evidence: ProductTruthSpecEvidence = Field(default_factory=ProductTruthSpecEvidence)
    visual_evidence: ProductTruthVisualEvidence = Field(default_factory=ProductTruthVisualEvidence)
    commerce_evidence: ProductTruthCommerceEvidence = Field(default_factory=ProductTruthCommerceEvidence)
    claim_evidence: ProductTruthClaimEvidence = Field(default_factory=ProductTruthClaimEvidence)
    negative_constraints: ProductTruthNegativeConstraints = Field(default_factory=ProductTruthNegativeConstraints)
    reconciliation: ProductTruthReconciliation = Field(default_factory=ProductTruthReconciliation)
    final_output_preview: ProductTruthFinalOutputPreview = Field(default_factory=ProductTruthFinalOutputPreview)
