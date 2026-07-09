"""Pydantic models for workspace_generation_package."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class F2VGenerationPackageRequest(BaseModel):
    product_id: str
    workspace_execution_package_id: str | None = None
    generation_mode: str = "SINGLE"
    duration_seconds: int = 8
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008): default off
    dialogue_enabled: bool = True
    source_mode: str | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    # BLOCK-SPLIT authority: a requested TOTAL derives the workbook block chain and
    # OVERRIDES raw blocks[]; unsupported totals fail closed (parity with the
    # execution package + preview).
    engine_duration_target: str | None = None  # GOOGLE_FLOW | GROK
    requested_total_duration_seconds: int | None = None
    start_frame_asset_id: str | None = None
    start_frame_preview_url: str | None = None
    start_frame_download_url: str | None = None
    end_frame_asset_id: str | None = None
    end_frame_preview_url: str | None = None
    end_frame_download_url: str | None = None
    operator_notes: str | None = None


class I2VGenerationPackageRequest(BaseModel):
    product_id: str
    workspace_execution_package_id: str | None = None
    recipe_id: str = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"
    generation_mode: str = "SINGLE"
    target_language: str = "BM_MS"
    camera_style: str = "UGC_IPHONE_RAW"
    character_presence: str = "VISIBLE_CREATOR"
    creator_persona: str = "DEFAULT_CREATOR"
    overlay_enabled: bool = False  # NO_OVERLAY law (ADR-008): default off
    dialogue_enabled: bool = True
    # BLOCK-SPLIT authority (parity with F2V/execution/preview): requested TOTAL
    # derives the workbook chain and OVERRIDES raw blocks; unsupported fails closed.
    engine_duration_target: str | None = None  # GOOGLE_FLOW | GROK
    requested_total_duration_seconds: int | None = None
    product_reference_asset_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_context_reference_asset_id: str | None = None
    style_reference_asset_id: str | None = None
    operator_notes: str | None = None


class WorkspaceGenerationPackagePatchRequest(BaseModel):
    status: str | None = None
    operator_notes: str | None = None


class WorkspaceGenerationPackageListRequest(BaseModel):
    mode: str | None = None
    status: str | None = None
    product_id: str | None = None
    limit: int = 50
