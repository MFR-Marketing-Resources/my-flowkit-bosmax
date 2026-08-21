"""Typed P6 Batch Creative Production Orchestrator contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled


# Re-pinned 2026-08-05 after the Copywriting Hub-Rev2 catalog import re-derived the
# P6_READY set (old ~211 FastMoss rows archived out, 235 Rev2 products qualified in;
# net 438 -> 453). Owner-approved acceptance of the current catalog as the certified
# P6 launch cohort.
# Re-pinned again 2026-08-05: owner purged the registered pharmaceutical "Panadol
# Regular Coated" (paracetamol) from the marketing/generation catalog (archived,
# reversible). It was a cohort member, so the certified set drops 453 -> 452.
# Re-pinned 2026-08-21: the P6 launch cohort is now claim-safe by construction —
# the matrix builder blocks any product whose latest approved Product Intelligence
# is not CLAIM_SAFE (see catalog_coverage_service._claim_safety_launch_blocker).
# Post-freeze re-derivation had grown the (claim-blind) cohort to 581; gating out
# the 7 CLAIM_REVIEW_REQUIRED products (3 HIGH / 4 MEDIUM health-claim items) yields
# the certified claim-safe set 574. Owner-approved acceptance of that vetted cohort.
P58_COHORT_COUNT = 574
P58_COHORT_SHA256 = (
    "add708e17fb9b474764b7287c025724cb01f8a8c19eb35929cff9cc97da9ba14"
)
P6_LIVE_CONFIRMATION = "AUTHORIZE_P6_LIVE_CREDIT_SPEND"


class ProductionRecipe(StrEnum):
    """The only business recipes available to new Production Studio plans.

    The technical ``logical_mode`` field remains below this boundary for
    historical rows and private execution adapters.  It is intentionally not
    the operator-facing contract.
    """

    HYBRID = "HYBRID"
    FACELESS = "FACELESS"
    MONTAGE = "MONTAGE"


RETIRED_PRODUCTION_LOGICAL_MODES = frozenset({"T2V", "F2V", "I2V"})


def _reject_legacy_production_mode(value: str | None) -> None:
    if value is None:
        return
    normalized = str(value).strip().upper()
    if normalized in RETIRED_PRODUCTION_LOGICAL_MODES:
        raise ValueError("PRODUCTION_RECIPE_RETIRED")
    raise ValueError("PRODUCTION_RECIPE_UNSUPPORTED")


def _validate_production_recipe_value(value: ProductionRecipe | str | None):
    """Preserve semantic retirement errors before Enum coercion happens."""

    if value is None or isinstance(value, ProductionRecipe):
        return value
    normalized = str(value).strip().upper()
    if normalized in RETIRED_PRODUCTION_LOGICAL_MODES:
        raise ValueError("PRODUCTION_RECIPE_RETIRED")
    if normalized not in {recipe.value for recipe in ProductionRecipe}:
        raise ValueError("PRODUCTION_RECIPE_UNSUPPORTED")
    return normalized


class PlanStatus(StrEnum):
    DRAFT = "DRAFT"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    PREFLIGHT_READY = "PREFLIGHT_READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ItemStatus(StrEnum):
    PLANNED = "PLANNED"
    COMPILED = "COMPILED"
    DEDUPE_BLOCKED = "DEDUPE_BLOCKED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    WAVE_ASSIGNED = "WAVE_ASSIGNED"
    QUEUED = "QUEUED"
    DISPATCHING = "DISPATCHING"
    SUBMITTED = "SUBMITTED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    RETRIEVING = "RETRIEVING"
    RETRIEVED = "RETRIEVED"
    QA_PENDING = "QA_PENDING"
    QA_APPROVED = "QA_APPROVED"
    QA_REJECTED = "QA_REJECTED"
    REPLACEMENT_PLANNED = "REPLACEMENT_PLANNED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class AttemptState(StrEnum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMISSION_STARTED = "SUBMISSION_STARTED"
    SUBMISSION_OUTCOME_UNCERTAIN = "SUBMISSION_OUTCOME_UNCERTAIN"
    PROVIDER_JOB_KNOWN = "PROVIDER_JOB_KNOWN"
    GENERATED_NOT_RETRIEVED = "GENERATED_NOT_RETRIEVED"
    RETRIEVED_NOT_REGISTERED = "RETRIEVED_NOT_REGISTERED"
    REGISTERED = "REGISTERED"
    QA_REJECTED = "QA_REJECTED"
    REPLACEMENT_REQUESTED = "REPLACEMENT_REQUESTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class CreativePoolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    treatment_ids: list[str] = Field(default_factory=list, max_length=200)
    copy_set_ids: list[str] = Field(default_factory=list, max_length=400)
    poster_copy_set_ids: list[str] = Field(default_factory=list, max_length=400)
    avatar_codes: list[str] = Field(default_factory=list, max_length=400)
    product_reference_asset_ids: list[str] = Field(
        default_factory=list,
        max_length=400,
    )
    finished_frame_asset_ids: list[str] = Field(
        default_factory=list,
        max_length=400,
    )
    character_asset_ids: list[str] = Field(default_factory=list, max_length=400)
    scene_asset_ids: list[str] = Field(default_factory=list, max_length=400)
    style_asset_ids: list[str] = Field(default_factory=list, max_length=200)
    layout_ids: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def _legacy_copy_pools_are_archived(self) -> "CreativePoolSelection":
        if not legacy_copy_maintenance_enabled() and (
            self.copy_set_ids or self.poster_copy_set_ids
        ):
            raise ValueError("LEGACY_COPY_STORAGE_DISABLED")
        return self


class CreativeProductionExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect: Literal["9:16", "16:9"] = "9:16"
    credit_policy: Literal["EXPLICIT_CONFIRMATION_REQUIRED"] = (
        "EXPLICIT_CONFIRMATION_REQUIRED"
    )
    near_duplicate_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    copy_reuse_cap: int = Field(default=15, ge=1, le=15)
    capacity_objective_not_sla: Literal[True] = True


class ProductVideoAllocation(BaseModel):
    """Explicit durable video quantity for one selected cohort product."""

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=200)
    video_count: int = Field(ge=1, le=200)


class TreatmentAvailabilityRequest(BaseModel):
    """Server-authoritative Creative Treatment capacity query for Studio."""

    model_config = ConfigDict(extra="forbid")

    product_video_allocations: list[ProductVideoAllocation] = Field(
        min_length=1,
        max_length=P58_COHORT_COUNT,
    )
    production_recipe: ProductionRecipe | None = None
    # Compatibility-only input.  It is explicit so retired callers receive a
    # deterministic semantic error instead of an incidental extra-field error.
    logical_mode: str | None = None
    model_key: str = Field(min_length=1, max_length=160)
    duration_seconds: int = Field(ge=1, le=240)
    creative_format: Literal["AUTO", "UGC", "PGC", "CINEMATIC"] = "AUTO"
    treatment_ids: list[str] = Field(default_factory=list, max_length=200)

    _validate_recipe_value = field_validator("production_recipe", mode="before")(
        _validate_production_recipe_value
    )

    @model_validator(mode="after")
    def validate_unique_authority(self) -> "TreatmentAvailabilityRequest":
        _reject_legacy_production_mode(self.logical_mode)
        if self.production_recipe is None:
            raise ValueError("PRODUCTION_RECIPE_REQUIRED")
        product_ids = [item.product_id for item in self.product_video_allocations]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("product_video_allocations product_id values must be unique")
        if len(set(self.treatment_ids)) != len(self.treatment_ids):
            raise ValueError("treatment_ids must be unique")
        return self


class ProductionPlanProductAllocationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    video_count: int = Field(ge=0, le=200)


class ProductionPlanVideoConfigurationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_key: str
    model_label: str
    requested_total_duration_seconds: int
    engine_block_duration_seconds: int
    generation_mode: Literal["SINGLE", "EXTEND"]
    segment_count: int
    execution_route: str


class ProductionPlanCanonicalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    completeness: Literal["COMPLETE", "LEGACY_INCOMPLETE"]
    missing_fields: list[str]
    source: Literal["CREATE_REQUEST", "LEGACY_RECONCILIATION", "LEGACY_PREVIEW"]
    evidence: dict[str, Any]
    plan_id: str
    plan_name: str
    purpose: str | None
    status: PlanStatus
    operator_id: str
    request_id: str
    product_allocations: list[ProductionPlanProductAllocationSnapshot]
    target_video_count: int
    target_image_count: int
    target_poster_count: int
    production_recipe: ProductionRecipe | None = None
    logical_mode: Literal["T2V", "HYBRID", "F2V", "I2V"]
    video_configurations: list[ProductionPlanVideoConfigurationSnapshot]
    aspect_ratio: Literal["9:16", "16:9"]
    operating_window_hours: int
    allocation_strategy: str
    variation_strategy: str
    approved_pool_snapshot: dict[str, Any] | None
    pool_snapshot: dict[str, Any]
    cohort_snapshot: dict[str, Any]
    matrix_count: int
    attempts_count: int
    qa_count: int
    created_at: str
    updated_at: str


class ProductionPlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8, max_length=128)
    operator_id: str = Field(min_length=2, max_length=160)
    name: str = Field(min_length=3, max_length=160)
    campaign_key: str = Field(default="", max_length=160)
    product_ids: list[str] = Field(min_length=1, max_length=P58_COHORT_COUNT)
    product_video_allocations: list[ProductVideoAllocation] = Field(
        default_factory=list,
        max_length=P58_COHORT_COUNT,
    )
    target_video_count: int = Field(default=0, ge=0, le=200)
    # Dormant compatibility fields: old wire clients may still send zero, but
    # positive image/poster targets are rejected by the semantic validator.
    target_image_count: int | None = Field(default=None, ge=0, le=200)
    target_poster_count: int | None = Field(default=None, ge=0, le=200)
    operating_window_hours: Literal[8, 12, 24] = 12
    allocation_strategy: Literal["ROUND_ROBIN", "PRODUCT_WEIGHTED"] = "ROUND_ROBIN"
    variation_strategy: Literal[
        "SAME_SCRIPT_DIFF_VISUALS",
        "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        "DIFF_SCRIPT_DIFF_VISUALS",
        "OPERATOR_MATRIX",
    ] = "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS"
    production_recipe: ProductionRecipe | None = None
    # Compatibility-only input; new Studio callers must use production_recipe.
    logical_mode: str | None = None
    model_keys: list[str] = Field(min_length=1, max_length=12)
    duration_seconds: list[int] = Field(min_length=1, max_length=12)
    creative_format: Literal[
        "AUTO", "UGC", "PGC", "CINEMATIC"
    ] = "AUTO"
    pools: CreativePoolSelection
    controlled_reuse_reason: str | None = Field(default=None, max_length=500)
    controlled_reuse_max_per_dna: int = Field(default=1, ge=1, le=3)
    execution_policy: CreativeProductionExecutionPolicy = Field(
        default_factory=CreativeProductionExecutionPolicy
    )
    copy_v2_context: dict[str, Any] | None = None

    _validate_recipe_value = field_validator("production_recipe", mode="before")(
        _validate_production_recipe_value
    )

    @model_validator(mode="after")
    def validate_targets(self) -> "ProductionPlanCreateRequest":
        _reject_legacy_production_mode(self.logical_mode)
        if (self.target_image_count or 0) > 0 or (self.target_poster_count or 0) > 0:
            raise ValueError("PRODUCTION_STUDIO_VIDEO_ONLY")
        if self.production_recipe is None:
            raise ValueError("PRODUCTION_RECIPE_REQUIRED")
        if self.target_video_count <= 0:
            raise ValueError("PRODUCTION_STUDIO_VIDEO_ONLY")
        if len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("product_ids must be unique")
        if len(set(self.pools.treatment_ids)) != len(self.pools.treatment_ids):
            raise ValueError("treatment_ids must be unique")
        if self.target_video_count > 0 and not self.product_video_allocations:
            raise ValueError(
                "product_video_allocations is required when target_video_count is positive"
            )
        if self.target_video_count == 0 and self.product_video_allocations:
            raise ValueError(
                "product_video_allocations must be empty when target_video_count is zero"
            )
        if self.product_video_allocations:
            allocation_ids = [
                allocation.product_id
                for allocation in self.product_video_allocations
            ]
            if len(set(allocation_ids)) != len(allocation_ids):
                raise ValueError(
                    "product_video_allocations product_id values must be unique"
                )
            if set(allocation_ids) != set(self.product_ids):
                raise ValueError(
                    "product_video_allocations must cover product_ids exactly"
                )
            allocated_total = sum(
                allocation.video_count
                for allocation in self.product_video_allocations
            )
            if allocated_total != self.target_video_count:
                raise ValueError(
                    "sum(product_video_allocations.video_count) must equal "
                    "target_video_count"
                )
        if len(set(self.model_keys)) != len(self.model_keys):
            raise ValueError("model_keys must be unique")
        if any(not model.strip() for model in self.model_keys):
            raise ValueError("model_keys cannot contain empty values")
        if len(set(self.duration_seconds)) != len(self.duration_seconds):
            raise ValueError("duration_seconds must be unique")
        if any(duration < 1 or duration > 240 for duration in self.duration_seconds):
            raise ValueError("duration_seconds values must be between 1 and 240")
        from agent.services import video_models

        if self.production_recipe is ProductionRecipe.MONTAGE:
            if self.execution_policy.aspect != "9:16":
                raise ValueError("MONTAGE_ASPECT_9_16_ONLY")
        for model_key in self.model_keys:
            for duration in self.duration_seconds:
                try:
                    orchestration = video_models.resolve_orchestration(
                        model_key, duration
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"invalid governed model-duration combination: {exc}"
                    ) from exc
                if (
                    self.production_recipe is ProductionRecipe.MONTAGE
                    and orchestration["generation_mode"] != "SINGLE"
                ):
                    raise ValueError("MONTAGE_SINGLE_CLIPS_ONLY")
        if self.controlled_reuse_max_per_dna > 1 and not str(
            self.controlled_reuse_reason or ""
        ).strip():
            raise ValueError(
                "controlled_reuse_reason is required when exact reuse is enabled"
            )
        return self


class ProductionPlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8, max_length=128)
    operator_id: str = Field(min_length=2, max_length=160)
    name: str | None = Field(default=None, min_length=3, max_length=160)
    campaign_key: str | None = Field(default=None, max_length=160)
    target_video_count: int | None = Field(default=None, ge=0, le=200)
    product_video_allocations: list[ProductVideoAllocation] | None = Field(
        default=None,
        max_length=P58_COHORT_COUNT,
    )
    target_image_count: int | None = Field(default=None, ge=0, le=200)
    target_poster_count: int | None = Field(default=None, ge=0, le=200)
    operating_window_hours: Literal[8, 12, 24] | None = None
    allocation_strategy: Literal["ROUND_ROBIN", "PRODUCT_WEIGHTED"] | None = None
    variation_strategy: Literal[
        "SAME_SCRIPT_DIFF_VISUALS",
        "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        "DIFF_SCRIPT_DIFF_VISUALS",
        "OPERATOR_MATRIX",
    ] | None = None
    production_recipe: ProductionRecipe | None = None
    # Compatibility-only input; retired logical modes are never accepted as a
    # new P6 configuration value.
    logical_mode: str | None = None
    model_keys: list[str] | None = Field(default=None, min_length=1, max_length=12)
    duration_seconds: list[int] | None = Field(
        default=None,
        min_length=1,
        max_length=12,
    )
    pools: CreativePoolSelection | None = None
    controlled_reuse_reason: str | None = Field(default=None, max_length=500)
    controlled_reuse_max_per_dna: int | None = Field(default=None, ge=1, le=3)

    _validate_recipe_value = field_validator("production_recipe", mode="before")(
        _validate_production_recipe_value
    )

    @model_validator(mode="after")
    def validate_public_recipe(self) -> "ProductionPlanUpdateRequest":
        _reject_legacy_production_mode(self.logical_mode)
        if (self.target_image_count or 0) > 0 or (self.target_poster_count or 0) > 0:
            raise ValueError("PRODUCTION_STUDIO_VIDEO_ONLY")
        return self


class PoolAuthorityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[str] = Field(min_length=1, max_length=P58_COHORT_COUNT)
    production_recipe: ProductionRecipe | None = None
    # Compatibility-only input for deterministic retirement errors.
    logical_mode: str | None = None

    _validate_recipe_value = field_validator("production_recipe", mode="before")(
        _validate_production_recipe_value
    )

    @model_validator(mode="after")
    def validate_public_recipe(self) -> "PoolAuthorityRequest":
        _reject_legacy_production_mode(self.logical_mode)
        if self.production_recipe is None:
            raise ValueError("PRODUCTION_RECIPE_REQUIRED")
        return self


class PlanActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8, max_length=128)
    operator_id: str = Field(min_length=2, max_length=160)


class WaveAssignmentRequest(PlanActionRequest):
    wave_count: int = Field(default=1, ge=1, le=50)
    batch_size: int = Field(default=25, ge=1, le=200)
    scheduled_at: str | None = None


class DryRunRequest(PlanActionRequest):
    aspect: str = Field(default="9:16", pattern=r"^(9:16|16:9)$")


class StartPlanRequest(DryRunRequest):
    live: bool = False
    credit_confirmation: str | None = Field(default=None, max_length=160)


class AttemptTransitionRequest(PlanActionRequest):
    attempt_state: AttemptState
    provider_job_id: str | None = Field(default=None, max_length=300)
    artifact_media_id: str | None = Field(default=None, max_length=300)
    failure_stage: str | None = Field(default=None, max_length=120)
    failure_code: str | None = Field(default=None, max_length=300)


class LanePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health_status: Literal["UNKNOWN", "HEALTHY", "DEGRADED", "UNAVAILABLE"]
    enabled: bool
    runtime_proof_status: Literal["UNVERIFIED", "VERIFIED", "EXPIRED", "REVOKED"]
    evidence_reference: str = Field(min_length=3, max_length=500)


class QaDecisionRequest(PlanActionRequest):
    decision: Literal["QA_APPROVED", "QA_REJECTED"]
    reviewer_note: str = Field(default="", max_length=1000)
    request_replacement: bool = False


class P58CohortAuthorityResponse(BaseModel):
    cohort_count: int
    cohort_sha256: str
    product_ids: list[str]
    products: list[dict[str, str]]
    matches_frozen_authority: bool
    p6_not_started: bool = False
    # The authority snapshot remains complete (cohort_count/product_ids), while
    # browser-facing product rows are a bounded searchable page.
    total_count: int | None = None
    returned_count: int | None = None
    has_pagination: bool | None = None
    limit: int | None = None
    offset: int | None = None


class CapacityPreflightResponse(BaseModel):
    plan_id: str
    status: Literal["PREFLIGHT_READY", "PREFLIGHT_BLOCKED"]
    requested: dict[str, int]
    safe_capacity: dict[str, int]
    pool_counts: dict[str, int]
    quota_pressure: dict[str, float]
    historical_exclusions: int
    blockers: list[dict[str, Any]]
    remediation: list[dict[str, Any]]
    assumptions: dict[str, Any]
    snapshot_sha256: str


class ProductionPlanDetailResponse(BaseModel):
    plan: dict[str, Any]
    snapshot: ProductionPlanCanonicalSnapshot
    waves: list[dict[str, Any]]
    batches: list[dict[str, Any]]
    items: list[dict[str, Any]]
    attempts: list[dict[str, Any]]
    qa: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]
    progress: dict[str, Any]
