from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProductAssetGeneratorRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: Optional[str] = None
    product_payload: Optional[dict[str, Any]] = None
    target_asset_intent: str

    gender: Optional[str] = None
    ethnicity: Optional[str] = None
    age_range: Optional[str] = None
    scene_context: Optional[str] = None
    platform: Optional[str] = None
    language: Optional[str] = None
    camera_style: Optional[str] = None
    camera_behavior: Optional[str] = None
    wardrobe: Optional[str] = None
    headwear: Optional[str] = None
    include_product_in_hand: bool = False
    target_destination_mode: Optional[str] = None
    strict_validation: bool = False
    dry_run_only: bool = True


class ProductAssetGeneratorResponse(BaseModel):
    preview_status: str
    target_asset_intent: Optional[str] = None
    product_context: dict[str, Any] = Field(default_factory=dict)
    derived_asset_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    prompt_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    required_assets: list[dict[str, Any]] = Field(default_factory=list)
    missing_assets: list[dict[str, Any]] = Field(default_factory=list)
    handling_notes: list[str] = Field(default_factory=list)
    physics_notes: list[str] = Field(default_factory=list)
    scene_notes: list[str] = Field(default_factory=list)
    camera_notes: list[str] = Field(default_factory=list)
    warning_summary: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    truth_warnings: list[str] = Field(default_factory=list)
    preview_warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    truth_status: dict[str, Any] = Field(default_factory=dict)
    
    # Truth Authority Block
    product_truth_status: str = "UNVERIFIED"
    truth_authority_source: str = "EPHEMERAL_DERIVED"
    source_anchor_status: str = "MISSING"
    mapping_v2_status: str = "NEEDS_REVIEW"
    mapping_confidence: str = "LOW"
    taxonomy_conflict: bool = False
    taxonomy_conflict_reason: Optional[str] = None
    scale_truth_status: str = "SCALE_NOT_FOUND"
    image_analysis_status: str = "NOT_CONFIGURED"
    
    dry_run_only: bool = True
    execution_allowed: bool = False
    image_generation_allowed: bool = False
    flow_execution_allowed: bool = False
    batch_execution_allowed: bool = False
