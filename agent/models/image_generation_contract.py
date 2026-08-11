"""Shared, provider-neutral image generation contracts.

The image surfaces are control planes.  Google Flow remains the generation
provider; these models describe the evidence BOSMAX compiles and the
provenance it expects back.  They deliberately distinguish a reference pack
approval from any approval of a generated output.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


IMAGE_PROMPT_COMPILER_VERSION = "image_prompt_compiler_v1"
IMAGE_REFERENCE_PACK_SCHEMA_VERSION = "product_reference_pack_v1"

ImageReferenceRole = Literal[
    "PRODUCT_CANONICAL",
    "PRODUCT_LABEL_CROP",
    "PRODUCT_LOGO_CROP",
    "PRODUCT_SCALE_EVIDENCE",
    "PRODUCT_CUTOUT",
    "CHARACTER",
    "SCENE",
    "STYLE",
]

ImageOutputIntent = Literal[
    "COMPLETE_POSTER",
    "CLEAN_KEY_VISUAL",
    "COMPLETE_IMAGE",
]

CapabilityStatus = Literal["SUPPORTED", "OBSERVED", "UNPROVEN", "BLOCKED"]
ReferencePackStatus = Literal["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"]
MachineQAStatus = Literal["PASS", "WARN", "FAIL"]
ScaleConfidence = Literal["UNVERIFIED", "LOW", "MEDIUM", "HIGH"]
GeneratedOutputReviewState = Literal[
    "REFERENCE_PACK_APPROVED",
    "GENERATED_OUTPUT_MACHINE_CHECKED",
    "GENERATED_OUTPUT_HUMAN_APPROVED",
]


class PhysicalMeasurementEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    physical_width_mm: float | None = Field(default=None, gt=0)
    physical_height_mm: float | None = Field(default=None, gt=0)
    physical_depth_mm: float | None = Field(default=None, gt=0)
    volume_ml: float | None = Field(default=None, gt=0)
    scale_evidence_source: str = Field(default="UNVERIFIED", min_length=1, max_length=256)
    scale_confidence: ScaleConfidence = "UNVERIFIED"


class ImageReferenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ImageReferenceRole
    asset_id: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_type: str = Field(min_length=1, max_length=128)
    approved: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class ProductReferencePackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack_id: str
    product_id: str
    schema_version: str
    pack_status: ReferencePackStatus
    machine_qa_status: MachineQAStatus
    machine_qa: dict[str, Any] = Field(default_factory=dict)
    physical_measurements: PhysicalMeasurementEvidence
    references: list[ImageReferenceBinding] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    human_review: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ImageArtDirection(BaseModel):
    """Typed, product-sensitive art direction for a complete generated image."""

    model_config = ConfigDict(extra="forbid")

    creative_territory: str = ""
    layout_family: str = ""
    visual_tension: str = ""
    product_anchor: str = ""
    copy_anchor: str = ""
    headline_personality: str = ""
    headline_line_budget: int = Field(default=1, ge=1, le=3)
    type_contrast: str = ""
    cta_treatment: str = ""
    negative_space_strategy: str = ""
    brand_visual_codes: list[str] = Field(default_factory=list, max_length=8)
    anti_cliche_rules: list[str] = Field(default_factory=list, max_length=8)
    design_route: str = ""
    layout_variant: str = ""
    type_pairing_id: str = ""
    color_strategy: str = ""
    proof_treatment: str = ""
    malaysian_context_route: str = ""
    font_license: str = ""
    font_readiness_status: str = "HOST_RUNTIME_REQUIRED"


class ImageCreativeContext(BaseModel):
    """Safe, auditable product-intelligence context for image generation.

    Raw persona pain language must not be copied into a provider prompt. This
    contract carries only transformed campaign strategy and approved facts.
    """

    model_config = ConfigDict(extra="forbid")

    intelligence_status: Literal["READY", "INCOMPLETE"] = "INCOMPLETE"
    grounding_source: str = "MINIMAL"
    approved_snapshot_id: str | None = None
    approved_snapshot_version: int | None = None
    product_family: str = ""
    formula: str = ""
    audience: str = ""
    desire: str = ""
    objection: str = ""
    trigger: str = ""
    safe_angle: str = ""
    tone: str = ""
    approved_facts: list[str] = Field(default_factory=list, max_length=5)
    missing_fields: list[str] = Field(default_factory=list, max_length=20)
    field_provenance: dict[str, str] = Field(default_factory=dict, max_length=30)
    art_direction: ImageArtDirection = Field(default_factory=ImageArtDirection)
    campaign_design_brief: dict[str, Any] | None = None


class ImagePromptCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    output_intent: ImageOutputIntent = "COMPLETE_POSTER"
    objective: str = Field(default="Product Hero", min_length=1, max_length=500)
    composition: str = Field(default="Product-led vertical campaign composition", max_length=2000)
    camera: str = Field(default="Vertical 9:16, natural perspective, product remains readable", max_length=2000)
    lighting: str = Field(default="Natural physically coherent light, contact shadow and material response", max_length=2000)
    scene_direction: str = Field(default="A culturally appropriate Malaysian commercial environment", max_length=3000)
    # Provider-facing campaign prompts may carry geometry/line-budget metadata,
    # but a clean key visual must never receive the actual marketing wording.
    # The compiler allowlists the structural keys before serialising this field.
    copy_space: dict[str, Any] = Field(default_factory=dict)
    copy_layout: dict[str, str] = Field(default_factory=dict)
    negative_constraints: list[str] = Field(default_factory=list, max_length=40)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1|4:3|3:4)$")
    creative_mode: str = Field(default="CREATIVE_CAMPAIGN", min_length=1, max_length=128)
    requested_outputs: int = Field(default=1, ge=1, le=3)
    model: str = Field(default="NANO_BANANA_PRO", min_length=1, max_length=128)
    reference_roles: list[ImageReferenceRole] = Field(
        default_factory=lambda: [
            "PRODUCT_CANONICAL",
            "PRODUCT_LABEL_CROP",
            "PRODUCT_LOGO_CROP",
            "PRODUCT_CUTOUT",
        ],
        max_length=8,
    )


class ImagePromptCompileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compiler_version: str
    product_id: str
    output_intent: ImageOutputIntent
    aspect_ratio: str
    compiled_prompt: str
    sections: dict[str, str]
    prompt_fingerprint: str
    reference_pack: ProductReferencePackRecord
    reference_bindings: list[ImageReferenceBinding]
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    capability_status: dict[str, CapabilityStatus] = Field(default_factory=dict)
    creative_context: ImageCreativeContext | None = None
    provider_operation_plan: dict[str, Any] = Field(default_factory=dict)


class ImageCapabilityAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["1A_STATIC_NO_SPEND"]
    no_spend: bool = True
    provider: str
    model_mapping: dict[str, dict[str, Any]]
    transport_contract: dict[str, Any]
    capability_status: dict[str, CapabilityStatus]
    observed_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImageOperationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1)
    requested_outputs: int = Field(default=3, ge=1, le=3)
    max_retry_operations: int = Field(default=0, ge=0, le=2)
    model: str = Field(default="NANO_BANANA_PRO", min_length=1, max_length=128)


class ImageOperationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    model: str
    requested_outputs: int
    max_provider_operations: int
    max_retry_operations: int
    estimated_credit_exposure: float | None
    estimated_credit_exposure_status: Literal["UNVERIFIED", "ESTIMATED"]
    explicit_confirmation_required: bool = True
    hidden_retry_allowed: bool = False


class GeneratedImageMachineQA(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: str
    review_state: GeneratedOutputReviewState = "GENERATED_OUTPUT_MACHINE_CHECKED"
    machine_qa_status: MachineQAStatus
    identity_status: Literal["UNVERIFIED", "FLAGGED", "PASS"] = "UNVERIFIED"
    label_status: Literal["UNVERIFIED", "FLAGGED", "PASS"] = "UNVERIFIED"
    geometry_status: Literal["UNVERIFIED", "FLAGGED", "PASS"] = "UNVERIFIED"
    scale_status: Literal["UNVERIFIED", "FLAGGED", "PASS"] = "UNVERIFIED"
    findings: list[str] = Field(default_factory=list)
    human_review_required: bool = True
