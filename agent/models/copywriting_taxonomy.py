"""Contracts for the workbook-backed copywriting taxonomy authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CopywritingTaxonomyRegistryStatus = Literal["ACTIVE", "REVIEW_REQUIRED"]
CopywritingTaxonomyMatchStatus = Literal[
    "EXACT_CODE",
    "EXACT_TAXONOMY",
    "AMBIGUOUS",
    "UNMATCHED",
]


class CopywritingTaxonomyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_type_code: str
    cluster_name: str
    display_name: str
    category: str
    subcategory: str
    type: str
    copywriting_angle: str
    source_workbook: str
    source_sheet: str
    source_row: int = Field(ge=1)
    registry_status: CopywritingTaxonomyRegistryStatus
    created_at: str | None = None
    updated_at: str | None = None


class CopywritingTaxonomyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["copywriting-taxonomy-v1"]
    source_workbook: str
    source_sheet: str
    items: list[CopywritingTaxonomyEntry]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    filters: dict[str, str | None]


class CopywritingTaxonomyRollupCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_name: str
    product_type_count: int = Field(ge=0)
    category_count: int = Field(ge=0)
    subcategory_count: int = Field(ge=0)
    type_count: int = Field(ge=0)
    angle_count: int = Field(ge=0)


class CopywritingTaxonomyRollupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["copywriting-taxonomy-v1"]
    source_workbook: str
    source_sheet: str
    total_product_types: int = Field(ge=0)
    cluster_count: int = Field(ge=0)
    category_count: int = Field(ge=0)
    subcategory_count: int = Field(ge=0)
    type_count: int = Field(ge=0)
    angle_count: int = Field(ge=0)
    clusters: list[CopywritingTaxonomyRollupCluster]


class CopywritingTaxonomyProductResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_display_name: str
    match_status: CopywritingTaxonomyMatchStatus
    matched_by: Literal["PRODUCT_TYPE_CODE", "CATEGORY_SUBCATEGORY_TYPE"] | None = None
    product_fields: dict[str, str | None]
    match: CopywritingTaxonomyEntry | None = None
    candidates: list[CopywritingTaxonomyEntry] = Field(default_factory=list)


class CopywritingTaxonomySeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    mutation_performed: bool
    seed_count: int = Field(ge=0)
    planned_insert_count: int = Field(ge=0)
    planned_update_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    confirmation_required: str | None = None
