"""Contracts for the workbook-backed copywriting taxonomy authority."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CopywritingTaxonomyRegistryStatus = Literal["ACTIVE", "REVIEW_REQUIRED"]
CopywritingTaxonomyMatchStatus = Literal[
    "EXACT_CODE",
    "EXACT_TAXONOMY",
    "AMBIGUOUS",
    "UNMATCHED",
    "NEEDS_RECONCILIATION",
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
    source_category: str | None = None
    source_subcategory: str | None = None
    source_type: str | None = None
    canonicalization_rules: list[str] = Field(default_factory=list)
    source_header_row: int = Field(default=2, ge=1)
    authority_version: str = "copywriting-taxonomy-v2"
    registry_status: CopywritingTaxonomyRegistryStatus
    created_at: str | None = None
    updated_at: str | None = None


class CopywritingTaxonomyListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["copywriting-taxonomy-v2"]
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

    schema_version: Literal["copywriting-taxonomy-v2"]
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
    needs_reconciliation: bool = False
    current: dict[str, str | None] = Field(default_factory=dict)
    match: dict[str, Any] | None = None
    nearest_match: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class CopywritingTaxonomyTreeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    copywriting_angle: str
    product_type_code: str
    cluster: str
    display_name: str
    category: str
    subcategory: str
    type: str


class CopywritingTaxonomyTreeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    categories: list[str]
    subcategories_by_category: dict[str, list[str]] = Field(
        alias="subcategoriesByCategory"
    )
    types_by_subcategory: dict[str, list[str]] = Field(alias="typesBySubcategory")
    record_by_type: dict[str, CopywritingTaxonomyTreeRecord] = Field(
        alias="recordByType"
    )


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
