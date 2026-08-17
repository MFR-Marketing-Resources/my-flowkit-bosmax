"""Formula-Driven Storyboard Landbank V3 Phase 2 domain contracts.

This module contains frozen value objects and deterministic digest helpers only.
It does not open the database, call a provider, author copy, approve a
storyboard, materialize V2, or integrate with P6.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


V3_SCHEMA_VERSION = "storyboard-landbank-v3-core-1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

V3LifecycleStatus = Literal[
    "DRAFT",
    "REVIEW_REQUIRED",
    "VALIDATED",
    "APPROVED",
    "FROZEN",
    "REJECTED",
    "ARCHIVED",
    "SUPERSEDED",
    "BLOCKED",
]
V3SemanticClass = Literal["HOOK", "BODY_CORE", "CTA", "STAGE"]
V3WpsMode = Literal["SAFE", "SWEET"]
V3ProjectionTransformMode = Literal["IDENTITY", "COMPRESSED", "MERGED_ADJACENT"]
V3ProjectionOmissionState = Literal["PRESENT", "OMITTED"]


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by every V3 digest."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deterministic_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def deterministic_id(prefix: str, value: Any, *, length: int = 24) -> str:
    token = " ".join(str(prefix or "").strip().split())
    if not token:
        raise ValueError("V3_ID_PREFIX_REQUIRED")
    return f"{token}_{deterministic_digest(value)[:length]}"


def normalized_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def word_count(value: str) -> int:
    text = normalized_text(value)
    return len(text.split()) if text else 0


def digest_text(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


class V3RevisionRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entity_id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class V3ProductTruthLineage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    snapshot_digest: str = Field(pattern=_SHA256_RE.pattern)
    snapshot_status: Literal[
        "DRAFT", "APPROVED", "SUPERSEDED", "REJECTED", "ARCHIVED"
    ]


class V3Objective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: str = Field(min_length=1)
    definition: str = Field(min_length=1)


class V3FormulaRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)


class V3EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    fact_id: str = Field(min_length=1)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)
    fact_kind: str = Field(min_length=1)


class V3BridgeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_key: str = Field(min_length=1)
    exit_key: str = Field(min_length=1)
    continuity_requirements: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("entry_key", "exit_key")
    @classmethod
    def _clean_key(cls, value: str) -> str:
        value = normalized_text(value)
        if not value:
            raise ValueError("V3_BRIDGE_KEY_REQUIRED")
        return value


class V3ValidationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validator: str = Field(min_length=1)
    validator_version: str = Field(min_length=1)
    valid: bool = False
    issue_codes: tuple[str, ...] = Field(default_factory=tuple)
    receipt_digest: str = Field(pattern=_SHA256_RE.pattern)


class V3SeamState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    block_index: int = Field(ge=0)
    outgoing_exit_key: str = Field(min_length=1)
    incoming_entry_key: str = Field(min_length=1)
    dialogue_start_seconds: float = Field(ge=0)
    dialogue_end_seconds: float = Field(ge=0)


class V3FormulaStage(BaseModel):
    """One ordered formula-native stage; the authored text source of truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage_key: str = Field(min_length=1)
    order: int = Field(ge=0)
    formula_stage_key: str = Field(min_length=1)
    semantic_class: V3SemanticClass = "STAGE"
    authored_text: str = Field(min_length=1)
    entry_key: str = Field(min_length=1)
    exit_key: str = Field(min_length=1)
    bridge_contract: V3BridgeContract
    claim_bearing: bool = False
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)
    component_ref: V3RevisionRef | None = None

    @field_validator("authored_text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = normalized_text(value)
        if not value:
            raise ValueError("V3_STAGE_TEXT_REQUIRED")
        return value


class V3ComponentStageSegment(BaseModel):
    """Lossless, formula-native source text for one component stage.

    A BODY_CORE component may cover several adjacent formula stages.  The
    component aggregate text remains a display convenience, while these
    ordered segments are the only authoring source used by the V3 Master
    compiler.  Keeping the value object embedded in the component avoids a
    second authority table and lets older Phase 2 rows migrate additively.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    formula_stage_key: str = Field(min_length=1)
    semantic_class: V3SemanticClass
    order: int = Field(ge=0)
    authored_text: str = Field(min_length=1)
    text_digest: str = Field(pattern=_SHA256_RE.pattern)
    entry_key: str = Field(min_length=1)
    exit_key: str = Field(min_length=1)
    bridge_contract: V3BridgeContract
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    claim_bearing: bool = False

    @field_validator("authored_text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = normalized_text(value)
        if not value:
            raise ValueError("V3_COMPONENT_STAGE_TEXT_REQUIRED")
        return value

    @model_validator(mode="after")
    def _segment_receipts(self) -> "V3ComponentStageSegment":
        if self.entry_key != self.bridge_contract.entry_key:
            raise ValueError("V3_COMPONENT_SEGMENT_ENTRY_BRIDGE_MISMATCH")
        if self.exit_key != self.bridge_contract.exit_key:
            raise ValueError("V3_COMPONENT_SEGMENT_EXIT_BRIDGE_MISMATCH")
        if self.text_digest != digest_text(self.authored_text):
            raise ValueError("V3_COMPONENT_SEGMENT_TEXT_DIGEST_MISMATCH")
        if self.evidence_digest != deterministic_digest(list(self.evidence_fact_ids)):
            raise ValueError("V3_COMPONENT_SEGMENT_EVIDENCE_DIGEST_MISMATCH")
        if len(self.evidence_fact_ids) != len(set(self.evidence_fact_ids)):
            raise ValueError("V3_COMPONENT_SEGMENT_EVIDENCE_DUPLICATE")
        if self.claim_bearing and not self.evidence_fact_ids:
            raise ValueError("V3_COMPONENT_SEGMENT_CLAIM_EVIDENCE_REQUIRED")
        return self


class V3ProjectedStageSlice(BaseModel):
    """A deterministic, typed allocation from one Master stage into a projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    master_stage_key: str = Field(min_length=1)
    master_formula_stage_key: str = Field(min_length=1)
    master_semantic_class: V3SemanticClass
    master_stage_text_digest: str = Field(pattern=_SHA256_RE.pattern)
    projected_text: str = ""
    projected_text_digest: str = Field(pattern=_SHA256_RE.pattern)
    source_evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    target_block_indices: tuple[int, ...] = Field(min_length=1)
    order: int = Field(ge=0)
    transform_mode: V3ProjectionTransformMode
    omission_state: V3ProjectionOmissionState = "PRESENT"

    @field_validator("projected_text")
    @classmethod
    def _clean_projected_text(cls, value: str) -> str:
        return normalized_text(value)


class V3SceneProjectionRef(BaseModel):
    """Typed visual compatibility reference; not a scene authority copy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_strategy_id: str = Field(min_length=1)
    scene_strategy_sha256: str = Field(pattern=_SHA256_RE.pattern)
    choreography_id: str = Field(min_length=1)
    choreography_sha256: str = Field(pattern=_SHA256_RE.pattern)
    treatment_id: str | None = None
    treatment_sha256: str | None = Field(default=None, pattern=_SHA256_RE.pattern)
    compatibility_profile: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _treatment_pair(self) -> "V3SceneProjectionRef":
        if bool(self.treatment_id) != bool(self.treatment_sha256):
            raise ValueError("V3_SCENE_TREATMENT_LINEAGE_INCOMPLETE")
        return self


class V3Angle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    angle_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage
    definition: str = Field(min_length=1)
    objective_compatibility: dict[str, Any] = Field(default_factory=dict)
    audience_compatibility: dict[str, Any] = Field(default_factory=dict)
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    formula: V3FormulaRef | None = None
    source: str = Field(min_length=1)
    status: V3LifecycleStatus = "DRAFT"
    angle_digest: str = Field(pattern=_SHA256_RE.pattern)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3StorylineFamily(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    family_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage
    angle: V3RevisionRef
    formula: V3FormulaRef
    objective_compatibility: dict[str, Any] = Field(default_factory=dict)
    reviewed_definition: str = Field(min_length=1)
    narrative_route: dict[str, Any] = Field(default_factory=dict)
    entry_contract: dict[str, Any] = Field(default_factory=dict)
    exit_contract: dict[str, Any] = Field(default_factory=dict)
    proof_placement: dict[str, Any] = Field(default_factory=dict)
    cta_closure_intent: dict[str, Any] = Field(default_factory=dict)
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)
    status: V3LifecycleStatus = "DRAFT"
    family_digest: str = Field(pattern=_SHA256_RE.pattern)
    source: str = Field(min_length=1)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3StoryboardComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    component_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage
    objective: V3Objective
    angle: V3RevisionRef
    storyline_family: V3RevisionRef
    formula: V3FormulaRef
    semantic_class: V3SemanticClass
    formula_stage_keys: tuple[str, ...] = Field(min_length=1)
    ordered_stage_coverage: tuple[int, ...] = Field(min_length=1)
    # Additive Phase 2→Round 1 field.  Empty is retained only for legacy
    # single-stage rows; all new Round 1 components must carry segments.
    stage_segments: tuple[V3ComponentStageSegment, ...] = Field(default_factory=tuple)
    authored_text: str = Field(min_length=1)
    entry_key: str = Field(min_length=1)
    exit_key: str = Field(min_length=1)
    bridge_contract: V3BridgeContract
    evidence_fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    claim_bearing: bool = False
    content_digest: str = Field(pattern=_SHA256_RE.pattern)
    semantic_fingerprint: str | None = None
    word_count: int = Field(ge=0)
    status: V3LifecycleStatus = "DRAFT"
    source: str = Field(min_length=1)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3CopyRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    recipe_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage | None = None
    campaign_key: str = ""
    campaign_scope: dict[str, Any] = Field(default_factory=dict)
    formula: V3FormulaRef
    objective: V3Objective
    target_angles: tuple[V3RevisionRef, ...] = Field(default_factory=tuple)
    storyline_policy: dict[str, Any] = Field(default_factory=dict)
    component_count_targets: dict[str, int] = Field(default_factory=dict)
    supported_durations_seconds: tuple[int, ...] = Field(default_factory=tuple)
    wps_mode: V3WpsMode = "SAFE"
    novelty_policy: dict[str, Any] = Field(default_factory=dict)
    exact_reuse_policy: dict[str, Any] = Field(default_factory=dict)
    review_policy: dict[str, Any] = Field(default_factory=dict)
    target_capacity: dict[str, Any] = Field(default_factory=dict)
    deterministic_seed: str = Field(min_length=1)
    config_digest: str = Field(pattern=_SHA256_RE.pattern)
    status: V3LifecycleStatus = "DRAFT"
    source: str = Field(min_length=1)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3MasterStoryboard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    master_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    recipe: V3RevisionRef
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage
    objective: V3Objective
    angle: V3RevisionRef
    storyline_family: V3RevisionRef
    formula: V3FormulaRef
    stages: tuple[V3FormulaStage, ...] = Field(min_length=1)
    resolved_component_refs: tuple[V3RevisionRef, ...] = Field(default_factory=tuple)
    evidence_map: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    bridge_continuity_receipt: V3ValidationReceipt
    formula_validation_receipt: V3ValidationReceipt
    claim_safety_receipt: V3ValidationReceipt
    exact_content_digest: str = Field(pattern=_SHA256_RE.pattern)
    duplicate_fingerprint: str = Field(pattern=_SHA256_RE.pattern)
    word_count: int = Field(ge=0)
    status: V3LifecycleStatus = "DRAFT"
    source: str = Field(min_length=1)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3DurationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["3"] = "3"
    projection_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    master: V3RevisionRef
    product_id: str = Field(min_length=1)
    product_truth: V3ProductTruthLineage
    target_duration_seconds: int = Field(gt=0)
    engine: str = "GOOGLE_FLOW"
    language_profile: str = Field(min_length=1)
    wps_mode: V3WpsMode = "SAFE"
    wps_authority_version: str = Field(min_length=1)
    wps_authority_digest: str = Field(pattern=_SHA256_RE.pattern)
    block_plan_seconds: tuple[int, ...] = Field(min_length=1)
    exact_resolved_dialogue: str = Field(min_length=1)
    per_block_slices: tuple[str, ...] = Field(min_length=1)
    per_block_word_counts: tuple[int, ...] = Field(min_length=1)
    per_block_word_budgets: tuple[int, ...] = Field(min_length=1)
    stage_allocations: tuple[V3ProjectedStageSlice, ...] = Field(min_length=1)
    stage_allocation_digest: str = Field(pattern=_SHA256_RE.pattern)
    cta_block_index: int = Field(ge=0)
    cta_stage_key: str = Field(min_length=1)
    seam_states: tuple[V3SeamState, ...] = Field(default_factory=tuple)
    continuity_receipt: V3ValidationReceipt
    formula_arc_receipt: V3ValidationReceipt
    stage_allocation_receipt: V3ValidationReceipt
    master_stage_keys: tuple[str, ...] = Field(min_length=1)
    master_stage_text_digests: tuple[str, ...] = Field(min_length=1)
    master_exact_content_digest: str = Field(pattern=_SHA256_RE.pattern)
    exact_projection_digest: str = Field(pattern=_SHA256_RE.pattern)
    # Round 2 provenance is intentionally separate from exact dialogue content.
    # The deterministic WPS transform remains the projection authority; these
    # fields only identify the authoring lineage that supplied the Master.
    derivation_source: Literal["DETERMINISTIC", "AI_ASSISTED", "HUMAN_EDITED"] = "DETERMINISTIC"
    authoring_run_id: str | None = None
    status: V3LifecycleStatus = "DRAFT"
    source: str = Field(min_length=1)
    supersedes: V3RevisionRef | None = None
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class V3StoryboardCandidate(BaseModel):
    """Deterministic read model over a Master and its projections."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    master: V3MasterStoryboard
    projections: tuple[V3DurationProjection, ...] = Field(default_factory=tuple)
    validation_receipts: tuple[V3ValidationReceipt, ...] = Field(default_factory=tuple)
    status: Literal["DRAFT", "REVIEW_REQUIRED", "VALIDATED", "BLOCKED"] = "DRAFT"


class V3ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    entity_type: Literal[
        "ANGLE",
        "STORYLINE_FAMILY",
        "STORYBOARD_COMPONENT",
        "COPY_RECIPE",
        "MASTER_STORYBOARD",
        "DURATION_PROJECTION",
    ]
    entity_id: str = Field(min_length=1)
    entity_revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    event_type: Literal[
        "CREATED",
        "EDITED_AS_NEW_REVISION",
        "SUBMITTED_FOR_REVIEW",
        "REJECTED",
        "ARCHIVED",
        "SUPERSEDED",
    ]
    from_status: str | None = None
    to_status: str | None = None
    actor_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    request_id: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_digest: str = Field(pattern=_SHA256_RE.pattern)
    created_at: str = Field(min_length=1)


def evidence_refs_digest(refs: tuple[V3EvidenceRef, ...] | list[V3EvidenceRef]) -> str:
    return deterministic_digest([ref.model_dump(mode="json") for ref in refs])


def master_content_payload(master: V3MasterStoryboard) -> dict[str, Any]:
    """Return the lossless Master content payload, excluding metadata/digests."""

    return {
        "schema_version": master.schema_version,
        "recipe": master.recipe.model_dump(mode="json"),
        "product_id": master.product_id,
        "product_truth": master.product_truth.model_dump(mode="json"),
        "objective": master.objective.model_dump(mode="json"),
        "angle": master.angle.model_dump(mode="json"),
        "storyline_family": master.storyline_family.model_dump(mode="json"),
        "formula": master.formula.model_dump(mode="json"),
        "stages": [stage.model_dump(mode="json") for stage in master.stages],
        "resolved_component_refs": [
            ref.model_dump(mode="json") for ref in master.resolved_component_refs
        ],
        "evidence_map": master.evidence_map,
        "evidence_digest": master.evidence_digest,
    }


def master_content_digest(master: V3MasterStoryboard) -> str:
    return deterministic_digest(master_content_payload(master))


def projected_stage_slice_payload(slice_value: V3ProjectedStageSlice) -> dict[str, Any]:
    return slice_value.model_dump(mode="json")


def projected_stage_allocations_digest(
    allocations: tuple[V3ProjectedStageSlice, ...] | list[V3ProjectedStageSlice],
) -> str:
    return deterministic_digest([projected_stage_slice_payload(item) for item in allocations])


def projection_content_payload(projection: V3DurationProjection) -> dict[str, Any]:
    return {
        "schema_version": projection.schema_version,
        "master": projection.master.model_dump(mode="json"),
        "product_id": projection.product_id,
        "product_truth": projection.product_truth.model_dump(mode="json"),
        "target_duration_seconds": projection.target_duration_seconds,
        "engine": projection.engine,
        "language_profile": projection.language_profile,
        "wps_mode": projection.wps_mode,
        "wps_authority_version": projection.wps_authority_version,
        "wps_authority_digest": projection.wps_authority_digest,
        "block_plan_seconds": list(projection.block_plan_seconds),
        "exact_resolved_dialogue": projection.exact_resolved_dialogue,
        "per_block_slices": list(projection.per_block_slices),
        "per_block_word_counts": list(projection.per_block_word_counts),
        "per_block_word_budgets": list(projection.per_block_word_budgets),
        "stage_allocations": [
            projected_stage_slice_payload(item) for item in projection.stage_allocations
        ],
        "stage_allocation_digest": projection.stage_allocation_digest,
        "cta_block_index": projection.cta_block_index,
        "cta_stage_key": projection.cta_stage_key,
        "seam_states": [seam.model_dump(mode="json") for seam in projection.seam_states],
        "master_stage_keys": list(projection.master_stage_keys),
        "master_stage_text_digests": list(projection.master_stage_text_digests),
        "master_exact_content_digest": projection.master_exact_content_digest,
    }


def projection_content_digest(projection: V3DurationProjection) -> str:
    return deterministic_digest(projection_content_payload(projection))


def validation_receipt_payload(receipt: V3ValidationReceipt) -> dict[str, Any]:
    return {
        "validator": receipt.validator,
        "validator_version": receipt.validator_version,
        "valid": receipt.valid,
        "issue_codes": list(receipt.issue_codes),
    }


def validation_receipt_digest(receipt: V3ValidationReceipt) -> str:
    return deterministic_digest(validation_receipt_payload(receipt))


def exact_resolved_content_payload(master: V3MasterStoryboard) -> dict[str, Any]:
    """Return only the exact resolved copy identity used for duplicate checks."""

    return {
        "formula": master.formula.model_dump(mode="json"),
        "stages": [
            {
                "formula_stage_key": stage.formula_stage_key,
                "authored_text": normalized_text(stage.authored_text),
            }
            for stage in master.stages
        ],
    }


def exact_resolved_content_fingerprint(master: V3MasterStoryboard) -> str:
    return deterministic_digest(exact_resolved_content_payload(master))


__all__ = [
    "V3_SCHEMA_VERSION",
    "V3LifecycleStatus",
    "V3SemanticClass",
    "V3WpsMode",
    "V3ProjectionTransformMode",
    "V3ProjectionOmissionState",
    "V3RevisionRef",
    "V3ProductTruthLineage",
    "V3Objective",
    "V3FormulaRef",
    "V3EvidenceRef",
    "V3BridgeContract",
    "V3ValidationReceipt",
    "V3SeamState",
    "V3FormulaStage",
    "V3ComponentStageSegment",
    "V3ProjectedStageSlice",
    "V3SceneProjectionRef",
    "V3Angle",
    "V3StorylineFamily",
    "V3StoryboardComponent",
    "V3CopyRecipe",
    "V3MasterStoryboard",
    "V3DurationProjection",
    "V3StoryboardCandidate",
    "V3ReviewEvent",
    "canonical_json",
    "deterministic_digest",
    "deterministic_id",
    "normalized_text",
    "word_count",
    "digest_text",
    "evidence_refs_digest",
    "master_content_payload",
    "master_content_digest",
    "projected_stage_slice_payload",
    "projected_stage_allocations_digest",
    "projection_content_payload",
    "projection_content_digest",
    "validation_receipt_payload",
    "validation_receipt_digest",
    "exact_resolved_content_payload",
    "exact_resolved_content_fingerprint",
]
