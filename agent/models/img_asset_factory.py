"""IMG Asset Factory v1 — API request / response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.models.creative_asset import CreativeAssetReviewStatus


class ImgAssetLaneSummary(BaseModel):
    lane_id: str
    label: str
    family: str
    purpose: str
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    requires_product_id: bool
    requires_character_reference: bool
    requires_scene_reference: bool
    requires_style_reference: bool
    default_semantic_role: str
    default_asset_subtype: str
    default_allowed_modes: list[str] = Field(default_factory=list)
    default_engine_slot_eligibility: list[str] = Field(default_factory=list)
    allows_rendered_text: bool
    default_contains_rendered_text: bool
    default_approved_for_video_support: bool
    default_approved_for_poster: bool


class ImgAssetLaneListResponse(BaseModel):
    items: list[ImgAssetLaneSummary] = Field(default_factory=list)
    total: int


class SaveImgOutputRequest(BaseModel):
    """Save an APPROVED, REAL IMG output into the Creative Library under one lane.

    Exactly one real output source is required — either a finished
    ``generated_artifact`` (image kind) or real uploaded ``image_base64`` bytes.
    There is deliberately NO way to "save" a non-existent / fabricated output.
    """

    model_config = ConfigDict(extra="forbid")

    lane_id: str
    display_name: str
    description: str | None = None

    # Real output source (exactly one) — fail closed if neither is present.
    generated_artifact_media_id: str | None = None
    image_base64: str | None = None
    file_name: str | None = None

    # Lineage
    product_id: str | None = None
    source_character_asset_id: str | None = None
    source_scene_asset_id: str | None = None
    source_style_asset_id: str | None = None
    source_prompt_fingerprint: str | None = None
    source_workspace_execution_package_id: str | None = None
    source_prompt_package_snapshot_id: str | None = None
    # Only the canonical mode is client supplied. Provenance versions are always
    # server-derived by the existing Creative Direction resolver.
    creative_mode: str | None = None

    # Catalog tags
    category: str | None = None
    silo: str | None = None
    product_type: str | None = None

    # Operator review truth flags (optional overrides for the *_status metadata).
    identity_lock_status: str | None = None
    scale_truth_status: str | None = None
    claim_safety_status: str | None = None
    # Governance: a saved asset defaults to PENDING_REVIEW. Marking it APPROVED
    # requires the operator to also supply non-UNVERIFIED truth/safety statuses
    # (enforced in the service) so an asset can never be silently APPROVED while
    # its identity/scale/claim gates stay UNVERIFIED.
    review_status: CreativeAssetReviewStatus = "PENDING_REVIEW"


class ImgProviderStatusResponse(BaseModel):
    # Honest boundary reporting. This PR ships + tests save-to-library only; the
    # image GENERATION runtime is external and is NOT re-proven in this PR.
    provider_state: Literal[
        "SAVE_TO_LIBRARY_READY_GENERATION_RUNTIME_EXTERNAL",
        "NOT_CONFIGURED",
    ]
    detail: str
    generation_endpoint: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


FastlaneRoute = Literal["FRAMES", "INGREDIENTS"]
IngredientRole = Literal[
    "AVATAR_REFERENCE",
    "SCENE_REFERENCE",
    "STYLE_REFERENCE",
    "PRODUCT_REFERENCE",
]


class ImgFastlanePresetSummary(BaseModel):
    preset_id: str
    label: str
    route: FastlaneRoute
    lane_id: str
    ingredient_role: IngredientRole | None = None
    description: str
    required_inputs: list[str] = Field(default_factory=list)
    output_spec: str
    tags: list[str] = Field(default_factory=list)


class ImgFastlanePresetListResponse(BaseModel):
    items: list[ImgFastlanePresetSummary] = Field(default_factory=list)
    total: int


class ImgFastlanePromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_id: str
    route: FastlaneRoute
    ingredient_role: IngredientRole | None = None
    product_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_reference_asset_id: str | None = None
    style_reference_asset_id: str | None = None
    product_reference_asset_id: str | None = None
    advanced_override_notes: str | None = None
    # A scene-context registry SceneCode (e.g. "SCN_RAYA_KAMPUNG"). When set, the
    # scene's Background: prose is injected into the prompt as environment context —
    # so any of the 20 seeded scenes is usable immediately, without first generating
    # a scene image. Independent of scene_reference_asset_id (the image reference).
    scene_context_code: str | None = None
    # Optional governed mode. Omission preserves the legacy fastlane preview.
    creative_mode: str | None = None


class ImgFastlanePromptPreviewResponse(BaseModel):
    preset_id: str
    route: FastlaneRoute
    ingredient_role: IngredientRole | None = None
    lane_id: str
    prompt_text: str
    # Clean, engine-agnostic brief actually sent to the generator. Carries NO
    # internal routing metadata (preset/route/lane ids) so it is portable verbatim
    # across Google Flow, ChatGPT Image, and Grok. `prompt_text` remains the
    # labeled operator breakdown. Additive (default "") for backward compatibility.
    engine_prompt_text: str = ""
    display_name_suggestion: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    output_spec: str
    negative_rules: list[str] = Field(default_factory=list)
    reference_map: list[str] = Field(default_factory=list)
    creative_direction: dict[str, Any] = Field(default_factory=dict)
