from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DestinationAdapterRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    planner_output: Optional[dict[str, Any]] = None
    asset_bindings: list[dict[str, Any]] = Field(default_factory=list)
    product_context: dict[str, Any] = Field(default_factory=dict)
    manual_context: dict[str, Any] = Field(default_factory=dict)
    inferred_context: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class DestinationAdapterResponse(BaseModel):
    adapter_status: str
    source_route: Optional[str] = None
    destination_mode: Optional[str] = None
    output_type: Optional[str] = None
    mode_payload: dict[str, Any] = Field(default_factory=dict)
    asset_requirements: list[dict[str, Any]] = Field(default_factory=list)
    missing_assets: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    planner_block_summary: dict[str, Any] = Field(default_factory=dict)
    execution_allowed: bool = False
