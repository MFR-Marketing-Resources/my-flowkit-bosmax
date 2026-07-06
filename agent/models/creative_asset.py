from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CreativeAssetSemanticRole = Literal[
    "PRODUCT_REFERENCE",
    "CHARACTER_REFERENCE",
    "SCENE_CONTEXT_REFERENCE",
    "STYLE_REFERENCE",
    "COMPOSITE_FRAME_REFERENCE",
]
CreativeAssetStatus = Literal["ACTIVE", "ARCHIVED"]
CreativeAssetSourceType = Literal[
    "UPLOAD",
    "GENERATED_IMAGE",
    "PRODUCT_CACHE",
    "REMOTE_URL",
    "SYSTEM_SEED",
]
CreativeAssetStorageKind = Literal[
    "LOCAL_FILE",
    "REMOTE_URL",
    "MEDIA_ID",
    "PRODUCT_IMAGE_CACHE",
]
CreativeAssetAllowedMode = Literal["T2V", "F2V", "I2V", "IMG"]
CreativeAssetEngineSlot = Literal["subject", "scene", "style", "start_frame", "end_frame"]
CreativeAssetReviewStatus = Literal["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"]
CreativeAssetLifecycle = Literal[
    "TEMP_JOB_OUTPUT",
    "CANONICAL_AVATAR_ASSET",
    "CANONICAL_PRODUCT_ASSET",
    "SAVED_REUSABLE_ASSET",
    "BROKEN_OR_MISSING_ASSET",
]
CreativeAssetRetentionPolicy = Literal["TEMP_48H", "PERSISTENT"]


class CreativeAssetRecord(BaseModel):
    asset_id: str
    semantic_role: CreativeAssetSemanticRole
    display_name: str
    description: str | None = None
    source_type: CreativeAssetSourceType
    storage_kind: CreativeAssetStorageKind
    preview_url: str | None = None
    download_url: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None
    remote_source_url: str | None = None
    product_id: str | None = None
    category: str | None = None
    silo: str | None = None
    product_type: str | None = None
    allowed_modes: list[CreativeAssetAllowedMode] = Field(default_factory=list)
    engine_slot_eligibility: list[CreativeAssetEngineSlot] = Field(default_factory=list)
    mode_a_metadata_handoff: dict[str, Any] | str | None = None
    visual_dna_summary: str | None = None
    character_dna: str | None = None
    scene_context_dna: str | None = None
    style_mood_dna: str | None = None
    source_prompt_fingerprint: str | None = None
    source_workspace_execution_package_id: str | None = None
    source_prompt_package_snapshot_id: str | None = None
    asset_subtype: str | None = None
    generation_recipe_id: str | None = None
    source_character_asset_id: str | None = None
    source_scene_asset_id: str | None = None
    source_style_asset_id: str | None = None
    contains_rendered_text: bool = False
    approved_for_video_support: bool = False
    approved_for_poster: bool = False
    product_truth_status: str | None = None
    identity_lock_status: str | None = None
    scale_truth_status: str | None = None
    claim_safety_status: str | None = None
    review_status: str = "PENDING_REVIEW"
    asset_lifecycle: CreativeAssetLifecycle = "SAVED_REUSABLE_ASSET"
    retention_policy: CreativeAssetRetentionPolicy = "PERSISTENT"
    expires_at: str | None = None
    is_reusable: bool = True
    is_canonical: bool = False
    source_job_id: str | None = None
    avatar_code: str | None = None
    status: CreativeAssetStatus
    created_at: str
    updated_at: str


class CreativeAssetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_role: CreativeAssetSemanticRole
    display_name: str
    description: str | None = None
    source_type: CreativeAssetSourceType = "UPLOAD"
    storage_kind: CreativeAssetStorageKind = "LOCAL_FILE"
    preview_url: str | None = None
    download_url: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None
    remote_source_url: str | None = None
    product_id: str | None = None
    category: str | None = None
    silo: str | None = None
    product_type: str | None = None
    allowed_modes: list[CreativeAssetAllowedMode] = Field(default_factory=list)
    engine_slot_eligibility: list[CreativeAssetEngineSlot] = Field(default_factory=list)
    mode_a_metadata_handoff: dict[str, Any] | str | None = None
    visual_dna_summary: str | None = None
    character_dna: str | None = None
    scene_context_dna: str | None = None
    style_mood_dna: str | None = None
    source_prompt_fingerprint: str | None = None
    source_workspace_execution_package_id: str | None = None
    source_prompt_package_snapshot_id: str | None = None
    asset_subtype: str | None = None
    generation_recipe_id: str | None = None
    source_character_asset_id: str | None = None
    source_scene_asset_id: str | None = None
    source_style_asset_id: str | None = None
    contains_rendered_text: bool = False
    approved_for_video_support: bool = False
    approved_for_poster: bool = False
    product_truth_status: str | None = None
    identity_lock_status: str | None = None
    scale_truth_status: str | None = None
    claim_safety_status: str | None = None
    review_status: CreativeAssetReviewStatus = "PENDING_REVIEW"
    asset_lifecycle: CreativeAssetLifecycle = "SAVED_REUSABLE_ASSET"
    retention_policy: CreativeAssetRetentionPolicy = "PERSISTENT"
    expires_at: str | None = None
    is_reusable: bool = True
    is_canonical: bool = False
    source_job_id: str | None = None
    avatar_code: str | None = None
    image_base64: str | None = None
    file_name: str | None = None


class CreativeAssetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    product_id: str | None = None
    category: str | None = None
    silo: str | None = None
    product_type: str | None = None
    allowed_modes: list[CreativeAssetAllowedMode] | None = None
    engine_slot_eligibility: list[CreativeAssetEngineSlot] | None = None
    mode_a_metadata_handoff: dict[str, Any] | str | None = None
    visual_dna_summary: str | None = None
    character_dna: str | None = None
    scene_context_dna: str | None = None
    style_mood_dna: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    remote_source_url: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None
    contains_rendered_text: bool | None = None
    approved_for_video_support: bool | None = None
    approved_for_poster: bool | None = None
    product_truth_status: str | None = None
    identity_lock_status: str | None = None
    scale_truth_status: str | None = None
    claim_safety_status: str | None = None
    review_status: CreativeAssetReviewStatus | None = None
    asset_lifecycle: CreativeAssetLifecycle | None = None
    retention_policy: CreativeAssetRetentionPolicy | None = None
    expires_at: str | None = None
    is_reusable: bool | None = None
    is_canonical: bool | None = None
    source_job_id: str | None = None
    avatar_code: str | None = None


class CreativeAssetListResponse(BaseModel):
    items: list[CreativeAssetRecord] = Field(default_factory=list)
    total: int


class CreativeAssetValidationResult(BaseModel):
    valid: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    asset: CreativeAssetRecord | None = None
