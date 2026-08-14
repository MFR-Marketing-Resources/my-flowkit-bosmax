"""P7.5 Creative Treatment authority contracts.

These models are deliberately independent of P6. They describe a durable,
review-gated treatment and its same-dialogue Variation Group authority.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


APPROVE_TREATMENT_CONFIRMATION = "APPROVE CREATIVE TREATMENT"
APPROVE_VARIATION_GROUP_CONFIRMATION = "APPROVE CREATIVE VARIATION GROUP"


class TreatmentStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CreativeTreatmentFormat(StrEnum):
    UGC = "UGC"
    PGC = "PGC"
    CINEMATIC = "CINEMATIC"


class AssetBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal[
        "PRODUCT_REFERENCE",
        "CHARACTER_REFERENCE",
        "SCENE_CONTEXT_REFERENCE",
        "STYLE_REFERENCE",
        "COMPOSITE_FRAME_REFERENCE",
    ]
    asset_id: str = Field(min_length=1)


class TreatmentActionStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    allowed_action_index: int = Field(ge=0)
    action_text: str = Field(min_length=1)
    actor_role: Literal["PRESENTER", "HANDS", "PRODUCT", "ENVIRONMENT"]
    initial_state: str = Field(min_length=1)
    resulting_state: str = Field(min_length=1)
    continuity_requirements: list[str] = Field(default_factory=list)
    start_time_seconds: float | None = Field(default=None, ge=0)
    end_time_seconds: float | None = Field(default=None, gt=0)
    support_hand: str | None = None
    active_hand: str | None = None
    visibility: str | None = None
    camera_cut_boundary: str | None = None
    product_location: str | None = None
    component_custody: str | None = None


class TreatmentShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    action_sequences: list[int] = Field(min_length=1)
    purpose: str = Field(min_length=1)
    framing: str = Field(min_length=1)
    camera_motion: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    continuity_in: list[str] = Field(default_factory=list)
    continuity_out: list[str] = Field(default_factory=list)


class TreatmentCompatibilityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_mode: Literal["T2V", "F2V", "I2V", "HYBRID"]
    source_mode: Literal["T2V", "HYBRID", "FRAMES", "INGREDIENTS"]
    model_keys: list[str] = Field(default_factory=list)
    required_asset_roles: list[
        Literal[
            "PRODUCT_REFERENCE",
            "CHARACTER_REFERENCE",
            "SCENE_CONTEXT_REFERENCE",
            "STYLE_REFERENCE",
            "COMPOSITE_FRAME_REFERENCE",
        ]
    ] = Field(default_factory=list)
    choreography_schema_version: str | None = None
    choreography_id: str | None = None
    choreography_sha256: str | None = None


class CreateTreatmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    product_truth_snapshot_id: str = Field(min_length=1)
    copy_set_id: str = Field(min_length=1)
    creative_selection_id: str = Field(min_length=1)
    scene_strategy_id: str = Field(min_length=1)
    format: CreativeTreatmentFormat
    generation_mode: Literal["SINGLE", "EXTEND"] = "SINGLE"
    duration_seconds: float = Field(gt=0)
    action_sequence: list[TreatmentActionStep] = Field(min_length=1)
    shot_grammar: list[TreatmentShot] = Field(min_length=1)
    compatibility_profile: TreatmentCompatibilityProfile
    asset_bindings: list[AssetBindingRequest] = Field(default_factory=list)
    # Optional per-treatment tuple overrides. The factory supplies these from the
    # APPROVED creative-selection recipe grid; omitted values retain the primary
    # single-select behavior for existing API callers and stored treatments.
    avatar_code: str | None = Field(default=None, min_length=1)
    scene_template_id: str | None = Field(default=None, min_length=1)
    variation_group_id: str | None = None
    variation_ordinal: int | None = Field(default=None, ge=1, le=5)
    supersedes_treatment_id: str | None = None
    choreography_schema_version: str | None = None
    choreography_id: str | None = None
    choreography_sha256: str | None = None
    created_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_variation_binding(self) -> "CreateTreatmentRequest":
        if (
            not self.asset_bindings
            and self.compatibility_profile.required_asset_roles
        ):
            raise ValueError("ASSET_BINDINGS_REQUIRED_BY_COMPATIBILITY_PROFILE")
        has_group = self.variation_group_id is not None
        has_ordinal = self.variation_ordinal is not None
        if has_group != has_ordinal:
            raise ValueError("VARIATION_GROUP_AND_ORDINAL_REQUIRED_TOGETHER")
        return self


class CreateVariationGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    copy_set_id: str = Field(min_length=1)
    supersedes_group_id: str | None = None
    created_by: str = Field(min_length=1)


class SubmitTreatmentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)


class ReviewTreatmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    actor_id: str = Field(min_length=1)
    expected_sha256: str = Field(min_length=64, max_length=64)
    confirmation: str
    reviewer_note: str | None = None


class SubmitVariationGroupReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(min_length=1)


class ReviewVariationGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVED", "REJECTED"]
    actor_id: str = Field(min_length=1)
    expected_sha256: str = Field(min_length=64, max_length=64)
    confirmation: str
    reviewer_note: str | None = None
