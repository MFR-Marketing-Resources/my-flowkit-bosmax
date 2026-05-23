from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


I2VRecipeId = Literal[
    "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
    "CHARACTER_FIRST_PRODUCT_DEMO",
    "STYLE_MOOD_DOMINANT_PRODUCT_SPOT",
]


class I2VSemanticSlotResolverRequest(BaseModel):
    mode: Literal["I2V"] = "I2V"
    product_id: str
    product_reference_asset_id: str | None = None
    character_reference_asset_id: str | None = None
    scene_context_reference_asset_id: str | None = None
    style_reference_asset_id: str | None = None
    recipe_id: I2VRecipeId = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"


class I2VResolvedAsset(BaseModel):
    slot_key: Literal["subject", "scene", "style"]
    semantic_role: str
    asset_id: str
    display_name: str | None = None
    asset_source: str | None = None
    asset_fingerprint: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    media_id: str | None = None
    local_file_path: str | None = None
    local_image_path_present: bool | None = None
    remote_image_url_present: bool | None = None


class I2VSemanticSlotResolverResponse(BaseModel):
    mode: Literal["I2V"] = "I2V"
    recipe_id: I2VRecipeId
    semantic_roles: dict[str, str | None] = Field(default_factory=dict)
    engine_slot_mapping: dict[str, str] = Field(default_factory=dict)
    creative_asset_ids: dict[str, str | None] = Field(default_factory=dict)
    resolved_assets: list[I2VResolvedAsset] = Field(default_factory=list)
    compiler_context_summary: str
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
