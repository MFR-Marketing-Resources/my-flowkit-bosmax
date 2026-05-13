from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProductDrivenAutoPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: Optional[str] = None
    product_payload: Optional[dict[str, Any]] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    target_duration_seconds: int = 8
    extension_strategy: Optional[str] = "NONE"
    requested_scene: Optional[str] = None
    requested_character: Optional[str] = None
    requested_language: Optional[str] = None
    requested_platform: Optional[str] = None
    requested_engine: Optional[str] = None
    asset_bindings: list[dict[str, Any]] = Field(default_factory=list)


class ProductDrivenAutoPlannerResponse(BaseModel):
    planning_status: str
    product_context: dict[str, Any] = Field(default_factory=dict)
    inferred_context: dict[str, Any] = Field(default_factory=dict)
    planner_request: Optional[dict[str, Any]] = None
    planner_output: Optional[dict[str, Any]] = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    not_verified_fields: list[str] = Field(default_factory=list)
