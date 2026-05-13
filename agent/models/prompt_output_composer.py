from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PromptOutputComposerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    adapter_status: Optional[str] = None
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    mode_payload: Optional[dict[str, Any]] = None
    asset_requirements: list[dict[str, Any]] = Field(default_factory=list)
    missing_assets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    planner_block_summary: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False


class PromptOutputComposerResponse(BaseModel):
    composer_status: str
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    prompt_text: str = ""
    sections: list[str] = Field(default_factory=list)
    section_count: int = 0
    block_summary: dict[str, Any] = Field(default_factory=dict)
    negative_prompt_notes: list[str] = Field(default_factory=list)
    aspect_ratio_or_platform: Optional[str] = None
    product_handling_notes: Optional[str] = None
    asset_reference_notes: list[str] = Field(default_factory=list)
    dialogue_or_narration_notes: Optional[str] = None
    overlay_notes: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False
