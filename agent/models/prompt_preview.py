from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None

    product_id: Optional[str] = None
    product_payload: Optional[dict[str, Any]] = None

    avatar_id: Optional[str] = None
    avatar_selection: Optional[str] = None
    wardrobe_id: Optional[str] = None
    wardrobe_selection: Optional[str] = None
    headwear_style: Optional[str] = None
    scene_context: Optional[str] = None
    camera_style: Optional[str] = None
    camera_behavior: Optional[str] = None
    trigger_id: Optional[str] = None
    silo: Optional[str] = None
    formula: Optional[str] = None
    language: Optional[str] = None
    platform: Optional[str] = None
    engine: Optional[str] = None

    requested_scene: Optional[str] = None
    requested_character: Optional[str] = None
    requested_language: Optional[str] = None
    requested_platform: Optional[str] = None
    requested_engine: Optional[str] = None

    asset_bindings: list[dict[str, Any]] = Field(default_factory=list)
    target_duration_seconds: int = 8
    block_duration_seconds: int = 8
    extension_strategy: Optional[str] = "NONE"
    include_temporal_plan: bool = False
    strict_validation: bool = False
    dry_run_only: bool = True

    transition_intent: Optional[str] = None
    allow_insert_jump_to: bool = False
    allow_mixed_strategy: bool = False
    requested_block_count: Optional[int] = None
    per_block_intent_notes: list[dict[str, Any]] = Field(default_factory=list)
    allow_image_prompt_temporal_metadata_only: bool = False


class PromptPreviewResponse(BaseModel):
    preview_status: str
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    planner_output: dict[str, Any] = Field(default_factory=dict)
    adapter_output: dict[str, Any] = Field(default_factory=dict)
    composer_output: dict[str, Any] = Field(default_factory=dict)
    temporal_output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False
    flow_execution_allowed: bool = False
    batch_execution_allowed: bool = False
    dry_run_only: bool = True
