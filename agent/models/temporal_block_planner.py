from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TemporalBlockPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    composer_status: Optional[str] = None
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    prompt_text: str = ""
    sections: list[str] = Field(default_factory=list)
    section_count: int = 0
    block_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False

    target_duration_seconds: int = 8
    block_duration_seconds: int = 8
    extension_strategy: Optional[str] = "NONE"
    transition_intent: Optional[str] = None
    allow_insert_jump_to: bool = False
    allow_mixed_strategy: bool = False
    requested_block_count: Optional[int] = None
    per_block_intent_notes: list[dict[str, Any]] = Field(default_factory=list)
    allow_image_prompt_temporal_metadata_only: bool = False


class TemporalPlanBlock(BaseModel):
    block_index: int
    duration_seconds: int
    flow_action_planned: str
    prompt_role: str
    depends_on_block_index: Optional[int] = None
    transition_intent: str
    continuation_prefix: Optional[str] = None
    prompt_text: str
    warnings: list[str] = Field(default_factory=list)
    execution_status: str = "PLANNED"


class TemporalBlockPlannerResponse(BaseModel):
    temporal_status: str
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    target_duration_seconds: Optional[int] = None
    block_duration_seconds: Optional[int] = None
    block_count: int = 0
    extension_strategy: Optional[str] = None
    temporal_blocks: list[TemporalPlanBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False
    flow_execution_allowed: bool = False
    batch_execution_allowed: bool = False
