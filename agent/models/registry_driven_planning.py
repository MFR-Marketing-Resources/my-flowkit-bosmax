from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RegistryDrivenManualPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

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
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    target_duration_seconds: int = 8
    extension_strategy: Optional[str] = "NONE"
    asset_bindings: list[dict[str, Any]] = Field(default_factory=list)


class RegistryDrivenManualPlannerResponse(BaseModel):
    planning_status: str
    manual_context: dict[str, Any] = Field(default_factory=dict)
    selected_fields: dict[str, Any] = Field(default_factory=dict)
    planner_request: Optional[dict[str, Any]] = None
    planner_output: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    not_verified_fields: list[str] = Field(default_factory=list)
    external_registry_dependencies: list[str] = Field(default_factory=list)
    compatibility_status: dict[str, Any] = Field(default_factory=dict)
