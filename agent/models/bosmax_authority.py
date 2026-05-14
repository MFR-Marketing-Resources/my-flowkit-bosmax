from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BosmaxAuthorityOption(BaseModel):
    value: str
    label: str
    source_status: str
    source_file: Optional[str] = None
    source_endpoint: Optional[str] = None
    source_origin: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BosmaxAuthorityFallback(BaseModel):
    label: str
    reason: str
    source_status: str
    source_file: Optional[str] = None
    source_endpoint: Optional[str] = None
    source_origin: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class BosmaxFieldProvenance(BaseModel):
    field: str
    source_status: str
    source_file: Optional[str] = None
    source_endpoint: Optional[str] = None
    source_origin: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class BosmaxSourceMatrixEntry(BaseModel):
    key: str
    label: str
    source_status: str
    source_file: Optional[str] = None
    source_endpoint: Optional[str] = None
    source_origin: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class BosmaxProductContext(BaseModel):
    product_id: str
    product: dict[str, Any] = Field(default_factory=dict)
    creative: dict[str, Any] = Field(default_factory=dict)
    visual: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    provenance: list[BosmaxFieldProvenance] = Field(default_factory=list)


class BosmaxProductGroup(BaseModel):
    options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    contexts: list[BosmaxProductContext] = Field(default_factory=list)


class BosmaxCreativeGroup(BaseModel):
    trigger_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    silo_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    formula_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    products_with_copy_signals: list[BosmaxAuthorityOption] = Field(default_factory=list)


class BosmaxVisualGroup(BaseModel):
    scene_context_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    camera_style_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    camera_behavior_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    style_reference_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    overlay_hint_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    product_handling_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    product_physics_options: list[BosmaxAuthorityOption] = Field(default_factory=list)


class BosmaxCharacterGroup(BaseModel):
    character_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    avatar_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    headwear_suggestions: list[BosmaxAuthorityOption] = Field(default_factory=list)
    wardrobe_fallback: BosmaxAuthorityFallback


class BosmaxExecutionGroup(BaseModel):
    language_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    platform_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    engine_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    duration_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    source_route_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    destination_mode_options: list[BosmaxAuthorityOption] = Field(default_factory=list)
    output_type_options: list[BosmaxAuthorityOption] = Field(default_factory=list)


class BosmaxProvenanceGroup(BaseModel):
    source_matrix: list[BosmaxSourceMatrixEntry] = Field(default_factory=list)
    missing_sources: list[BosmaxAuthorityFallback] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sales_analyzer_wired_to_prompt_tools: bool = False


class BosmaxPromptToolContextResponse(BaseModel):
    product: BosmaxProductGroup
    creative: BosmaxCreativeGroup
    visual: BosmaxVisualGroup
    character: BosmaxCharacterGroup
    execution: BosmaxExecutionGroup
    provenance: BosmaxProvenanceGroup


class BosmaxSourceMatrixResponse(BaseModel):
    source_matrix: list[BosmaxSourceMatrixEntry] = Field(default_factory=list)
    missing_sources: list[BosmaxAuthorityFallback] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sales_analyzer_wired_to_prompt_tools: bool = False


class BosmaxProductContextResponse(BaseModel):
    product_context: Optional[BosmaxProductContext] = None
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)