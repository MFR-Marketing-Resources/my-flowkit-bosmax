from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SnapshotStatus = Literal["DRAFT", "APPROVED", "SUPERSEDED", "REJECTED", "ARCHIVED"]
LatestSnapshotStatus = Literal["NO_APPROVED_SNAPSHOT", "APPROVED_SNAPSHOT_AVAILABLE"]


class ProductIntelligenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    product_id: str
    version: int
    status: SnapshotStatus
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
    claim_gate: str | None = None
    claim_risk_level: str | None = None
    claim_tokens_json: list[str] = Field(default_factory=list)
    allowed_claims_json: list[str] = Field(default_factory=list)
    blocked_claims_json: list[str] = Field(default_factory=list)
    buyer_persona_snapshot_json: dict[str, Any] = Field(default_factory=dict)
    copy_strategy_summary_json: dict[str, Any] = Field(default_factory=dict)
    confidence_score: float | None = None
    completeness_score: float | None = None
    readiness_status: str | None = None
    created_from_review_draft_id: str | None = None
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    supersedes_snapshot_id: str | None = None
    created_at: str
    updated_at: str


class ProductIntelligenceFieldProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance_id: str
    snapshot_id: str
    product_id: str
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
    created_at: str
    updated_at: str


class ProductIntelligenceProvenanceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_snapshots: int = 0
    approved_snapshot_count: int = 0
    latest_approved_snapshot_id: str | None = None
    latest_approved_version: int | None = None


class ProductIntelligenceLatestSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    latest_snapshot: ProductIntelligenceSnapshot | None = None
    status: LatestSnapshotStatus
    provenance_summary: ProductIntelligenceProvenanceSummary = Field(
        default_factory=ProductIntelligenceProvenanceSummary
    )


class ProductIntelligenceSnapshotListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    items: list[ProductIntelligenceSnapshot] = Field(default_factory=list)


class ProductIntelligenceFieldProvenanceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    product_id: str
    items: list[ProductIntelligenceFieldProvenance] = Field(default_factory=list)
