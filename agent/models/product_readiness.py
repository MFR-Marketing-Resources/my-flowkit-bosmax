from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceState = Literal[
    "VERIFIED_VALUE",
    "NOT_APPLICABLE",
    "NOT_STATED_IN_EVIDENCE",
    "UNKNOWN_REVIEW_REQUIRED",
]
PrimaryReadinessStatus = Literal[
    "READY",
    "REVIEW_REQUIRED",
    "EVIDENCE_REQUIRED",
    "ASSET_REQUIRED",
    "COPY_SUPPLY_REQUIRED",
    "UNSUPPORTED_PRODUCT_TAXONOMY",
]
CreativeFormat = Literal["UGC", "PGC", "CINEMATIC"]
LogicalMode = Literal["T2V", "HYBRID", "F2V", "I2V"]
GenerationMode = Literal["SINGLE", "EXTEND"]
RequirementCriticality = Literal[
    "COPY_CRITICAL",
    "TREATMENT_CRITICAL",
    "BOTH",
    "OPTIONAL",
]
ReadinessLayerName = Literal[
    "taxonomy",
    "product_truth",
    "copy_grounding",
    "claim_safety",
    "action_evidence",
    "copy_set",
    "creative_selection",
    "visual_assets",
    "treatment_template",
    "treatment_instance",
    "p6",
]
ReadinessLayerState = Literal[
    "READY",
    "BLOCKED",
    "REVIEW_REQUIRED",
    "NOT_APPLICABLE",
]
ActorPolicy = Literal["PRESENTER_REQUIRED", "PRESENTER_FORBIDDEN", "PRESENTER_OPTIONAL"]
AssetRole = Literal[
    "PRODUCT_REFERENCE",
    "CHARACTER_REFERENCE",
    "SCENE_CONTEXT_REFERENCE",
    "STYLE_REFERENCE",
    "COMPOSITE_FRAME_REFERENCE",
]


class ProductReadinessEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    allowed_action_index: int = Field(ge=0)
    creative_format: CreativeFormat
    logical_mode: LogicalMode
    generation_mode: GenerationMode
    model_key: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)


class EvidenceProvenanceAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provenance_id: str
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
    provenance_sha256: str


class ProductTruthReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str | None = None
    snapshot_sha256: str | None = None
    snapshot_status: str | None = None
    field_values: dict[str, object] = Field(default_factory=dict)
    provenance: list[EvidenceProvenanceAuthority] = Field(default_factory=list)
    claim_gate: str | None = None
    claim_risk_level: str | None = None
    is_stale: bool = False


class ProductTaxonomyReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taxonomy_version: str | None = None
    taxonomy_fingerprint: str | None = None
    cluster: str | None = None
    product_type_group: str | None = None
    matched_scene_strategy_id: str | None = None
    scene_coverage_status: str | None = None
    fallback_used: bool = False
    specific_strategy: bool = False
    review_status: str | None = None
    consumer_status: str | None = None
    materialization_status: str | None = None
    is_stale: bool = False
    failure_code: str | None = None


class CopyReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grounding_ready: bool = False
    grounding_source: str | None = None
    approved_copy_set_ids: list[str] = Field(default_factory=list)


class SelectionReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection_id: str | None = None
    status: str | None = None
    selected_avatar_code: str | None = None
    selected_avatar_codes: list[str] = Field(default_factory=list)
    selected_scene_template_id: str | None = None
    selected_scene_template_ids: list[str] = Field(default_factory=list)
    selected_camera_preset_code: str | None = None
    selected_camera_preset_codes: list[str] = Field(default_factory=list)
    selection_sha256: str | None = None


class AssetReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_roles: list[AssetRole] = Field(default_factory=list)
    eligible_asset_ids_by_role: dict[str, list[str]] = Field(default_factory=dict)
    missing_roles: list[AssetRole] = Field(default_factory=list)
    authority_sha256: str | None = None


class TreatmentReadinessAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_treatment_ids: list[str] = Field(default_factory=list)
    selected_treatment_ids: list[str] = Field(default_factory=list)
    availability_sha256: str | None = None
    p6_ready: bool = False
    blocker_codes: list[str] = Field(default_factory=list)


class ResolvedProductReadinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    context: ProductReadinessEvaluateRequest
    product_authority_sha256: str
    taxonomy: ProductTaxonomyReadinessAuthority
    product_truth: ProductTruthReadinessAuthority
    copy_authority: CopyReadinessAuthority = Field(
        default_factory=CopyReadinessAuthority,
        alias="copy",
    )
    selection: SelectionReadinessAuthority = Field(
        default_factory=SelectionReadinessAuthority,
    )
    assets: AssetReadinessAuthority = Field(default_factory=AssetReadinessAuthority)
    treatment: TreatmentReadinessAuthority = Field(
        default_factory=TreatmentReadinessAuthority,
    )

    @property
    def copy(self) -> CopyReadinessAuthority:
        return self.copy_authority


class IndexedActionApplicability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_action_index: int
    action_text: str
    action_classes: list[str]
    choreography_id: str | None = None
    choreography_sha256: str | None = None


class ApplicabilityProfileProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version: str
    scene_strategy_id: str
    product_family: str
    product_type: str
    supported: bool
    unsupported_code: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    indexed_actions: list[IndexedActionApplicability] = Field(default_factory=list)
    actor_policy_by_format: dict[str, ActorPolicy] = Field(default_factory=dict)
    required_asset_roles_by_mode: dict[str, list[AssetRole]] = Field(
        default_factory=dict,
    )
    profile_sha256: str


class EvidenceRequirementResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_code: str
    criticality: RequirementCriticality
    applicable: bool
    state: EvidenceState
    rule_code: str
    source_fields: list[str] = Field(default_factory=list)
    provenance_ids: list[str] = Field(default_factory=list)
    provenance_hashes: list[str] = Field(default_factory=list)
    value_sha256: str | None = None


class ReadinessLayerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: ReadinessLayerName
    state: ReadinessLayerState
    blocker_codes: list[str] = Field(default_factory=list)


class ReadinessBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    layer: ReadinessLayerName
    message: str
    next_action: str
    requirement_code: str | None = None


class ProductReadinessProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: str
    product_id: str
    primary_status: PrimaryReadinessStatus
    context: ProductReadinessEvaluateRequest
    context_sha256: str
    product_authority_sha256: str
    taxonomy_fingerprint: str | None = None
    applicability_profile: ApplicabilityProfileProjection
    selected_action: IndexedActionApplicability | None = None
    product_truth_snapshot_id: str | None = None
    product_truth_snapshot_sha256: str | None = None
    evidence_requirements: list[EvidenceRequirementResult] = Field(
        default_factory=list,
    )
    readiness_layers: list[ReadinessLayerResult] = Field(default_factory=list)
    blockers: list[ReadinessBlocker] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    approved_copy_set_ids: list[str] = Field(default_factory=list)
    approved_treatment_ids: list[str] = Field(default_factory=list)
    selected_treatment_ids: list[str] = Field(default_factory=list)
    readiness_sha256: str


class ApplicabilityProfileListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profiles: list[ApplicabilityProfileProjection]
    supported_count: int
    unsupported_count: int
    registry_sha256: str
