from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssetCatalogEntry(BaseModel):
    asset_type: str
    display_name: str
    description: str
    item_count: int = 0
    source_status: str
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    empty_reason: Optional[str] = None


class AssetCatalogResponse(BaseModel):
    catalog: list[AssetCatalogEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class AssetOption(BaseModel):
    asset_id: str
    asset_type: str
    label: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    compatibility_tags: list[str] = Field(default_factory=list)
    source_status: str
    source_file: Optional[str] = None
    source_path: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    is_selectable: bool = True
    is_canonical: bool = False
    verified_level: str = "NOT_VERIFIED"


class AssetOptionsResponse(BaseModel):
    asset_type: str
    options: list[AssetOption] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    source_status: str
    empty_reason: Optional[str] = None


class AssetDetailResponse(BaseModel):
    asset: AssetOption
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class AssetSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    selected_assets: dict[str, str | list[str] | None] = Field(default_factory=dict)


class AssetSelectionResponse(BaseModel):
    selection_status: str
    resolved_assets: list[AssetOption] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class AssetCompatibilityRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    selected_assets: dict[str, str | list[str] | None] = Field(default_factory=dict)


class AssetCompatibilityResponse(BaseModel):
    compatibility_status: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
