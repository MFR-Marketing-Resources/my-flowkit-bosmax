from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.models.creative_treatment import (
    TreatmentActionStep,
    TreatmentCompatibilityProfile,
    TreatmentShot,
)
from agent.models.product_readiness import EvidenceRequirementResult


FactoryPlanStatus = Literal[
    "DRAFT",
    "SCANNED",
    "PREPARING",
    "PAUSED",
    "COMPLETED",
    "COMPLETED_WITH_BLOCKERS",
    "FAILED",
]
FactoryTaskStatus = Literal[
    "PENDING",
    "READY",
    "RUNNING",
    "REVIEW_REQUIRED",
    "SATISFIED",
    "PAUSED",
    "FAILED",
    "SUPERSEDED",
]
FactoryTaskType = Literal[
    "PRODUCT_TRUTH_REVIEW",
    "EVIDENCE_REVIEW",
    "COPY_GROUNDING",
    "COPY_COMPOSITION",
    "COPY_REVIEW",
    "CREATIVE_SELECTION",
    "ASSET_SUPPLY",
    "TREATMENT_CANDIDATE",
    "TREATMENT_REVIEW",
    "P6_CAPACITY",
]
FactoryFormat = Literal["UGC", "PGC", "CINEMATIC"]
FactoryLogicalMode = Literal["T2V", "F2V", "I2V", "HYBRID"]
FactoryGenerationMode = Literal["SINGLE", "EXTEND"]


class FactoryContextDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_action_index: int = Field(default=0, ge=0)
    format: FactoryFormat = "PGC"
    logical_mode: FactoryLogicalMode = "HYBRID"
    generation_mode: FactoryGenerationMode = "SINGLE"
    model_key: str = Field(default="veo_3_1_fast", min_length=1)
    duration_seconds: int = Field(default=8, gt=0)


class FactoryProductContext(FactoryContextDefaults):
    product_id: str = Field(min_length=1)
    # The public plan target is allocated deterministically across the product
    # cohort. Zero is an internal allocation for a cohort smaller than the
    # requested run; it keeps readiness scans product-isolated without
    # manufacturing content for an unallocated product.
    target_video_count: int = Field(default=1, ge=0, le=200)


class CreateFactoryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    products: list[FactoryProductContext] = Field(default_factory=list)
    scan_all_active: bool = False
    target_video_count: int = Field(default=1, ge=1, le=200)
    defaults: FactoryContextDefaults = Field(default_factory=FactoryContextDefaults)
    created_by: str = Field(min_length=1)
    provider_calls_enabled: bool = False
    media_generation_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_cohort_authority(self) -> "CreateFactoryPlanRequest":
        if self.scan_all_active == bool(self.products):
            raise ValueError("EXACTLY_ONE_COHORT_SOURCE_REQUIRED")
        product_ids = [item.product_id for item in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("DUPLICATE_PRODUCT_CONTEXT")
        return self


class PrepareFactoryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    max_tasks: int = Field(default=1000, ge=1, le=10000)
    materialize_copy_composition: bool = True
    materialize_treatment_candidates: bool = True
    provider_calls_enabled: bool = False
    media_generation_enabled: Literal[False] = False


class FactoryPlanControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class TreatmentTemplateProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version: str
    template_id: str
    template_sha256: str
    scene_strategy_id: str
    profile_version: str
    profile_sha256: str
    risk_flags: list[str] = Field(default_factory=list)
    selected_action_index: int
    action_text: str
    action_classes: list[str] = Field(default_factory=list)
    format: FactoryFormat
    actor_policy: str
    logical_mode: FactoryLogicalMode
    generation_mode: FactoryGenerationMode
    duration_seconds: int
    evidence_requirements: list[EvidenceRequirementResult] = Field(
        default_factory=list,
    )
    action_sequence: list[TreatmentActionStep] = Field(min_length=1)
    shot_grammar: list[TreatmentShot] = Field(min_length=1)
    compatibility_profile: TreatmentCompatibilityProfile


class FactoryTaskProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    plan_id: str
    product_id: str
    task_type: FactoryTaskType
    status: FactoryTaskStatus
    task_identity_sha256: str
    required_authority_sha256: str
    blocker_code: str | None = None
    next_action: str | None = None
    template_id: str | None = None
    template_sha256: str | None = None
    treatment_id: str | None = None
    treatment_sha256: str | None = None
    snapshot: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    attempt_count: int = 0
    created_at: str
    updated_at: str


class FactoryPlanProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    plan_identity_sha256: str
    cohort_sha256: str
    context_sha256: str
    status: FactoryPlanStatus
    product_count: int
    request: dict[str, object]
    authority_versions: dict[str, object]
    readiness_summary: dict[str, int] = Field(default_factory=dict)
    capacity_summary: dict[str, object] = Field(default_factory=dict)
    failure_count: int = 0
    provider_calls_enabled: Literal[False] = False
    media_generation_enabled: Literal[False] = False
    created_by: str
    created_at: str
    updated_at: str
    tasks: list[FactoryTaskProjection] = Field(default_factory=list)


class FactoryPlanListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plans: list[FactoryPlanProjection] = Field(default_factory=list)
