from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class CopySignalGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: Optional[str] = None
    product_payload: Optional[dict[str, Any]] = None
    content_style_mode: str = "UGC_IPHONE"
    dialogue_metaphor_hint: Optional[str] = None
    stealth_metaphor: Optional[str] = None
    scene_context: Optional[str] = None
    camera_style: Optional[str] = None
    camera_behavior: Optional[str] = None


class CopySignalRoutesResponse(BaseModel):
    scope: str
    routes: list[str] = Field(default_factory=list)
    content_style_modes: list[str] = Field(default_factory=list)
    authority_files_found: list[str] = Field(default_factory=list)
    authority_files_missing: list[str] = Field(default_factory=list)


class CopySignalGenerateResponse(BaseModel):
    scope: str
    route: str
    review_status: str
    copy_quality_status: str = ""
    text_to_video_readiness_status: str = ""
    content_style_mode: str
    authority_files_found: list[str] = Field(default_factory=list)
    product_context: dict[str, Any] = Field(default_factory=dict)
    copy_signals: dict[str, Any] = Field(default_factory=dict)
    claim_safety: dict[str, Any] = Field(default_factory=dict)
    visual_dialogue_isolation: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
