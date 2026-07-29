"""Strict P4 generalized product-type copy preview and report contracts."""
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductTypeCopyDurationSeconds(IntEnum):
    SECONDS_8 = 8
    SECONDS_10 = 10
    SECONDS_16 = 16


class ProductTypeCopyStrategyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    copy_strategy_id: str
    duration_seconds: ProductTypeCopyDurationSeconds
    hook_line: str
    demo_line: str
    benefit_line: str
    cta_line: str
    overlay_text: str
    scene_action: str
    source_strategy: Literal["PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"]
    blocked_reasons: list[str] = Field(default_factory=list)


class ProductTypeCopyReportProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    blocked_reasons: list[str] = Field(default_factory=list)


class ProductTypeCopyReportGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: str
    product_type_group: str
    scene_strategy_id: str
    count: int = Field(ge=0)


class ProductTypeCopyEligibleReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_products: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    eligible_by_product_type: list[ProductTypeCopyReportGroup]
    blocked_by_reason: dict[str, int]
    missing_copy_strategy_groups: list[ProductTypeCopyReportGroup]
    sample_eligible: list[ProductTypeCopyReportProduct]
    sample_blocked: list[ProductTypeCopyReportProduct]


class CatalogCoverageMatrixProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    product_name: str
    lifecycle_status: str
    source_category: str | None = None
    source_subcategory: str | None = None
    source_product_type: str | None = None
    product_truth_mapped: bool
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    registry_status: Literal["ACTIVE", "REVIEW_REQUIRED", "UNREGISTERED"]
    review_status: Literal["VERIFIED", "REVIEW_REQUIRED"]
    consumer_status: Literal["READY", "BLOCKED_REVIEW_REQUIRED"]
    scene_coverage_status: Literal["COVERED", "PARTIAL", "FALLBACK_ONLY"]
    taxonomy_stale: bool
    fallback_used: bool
    specific_strategy: bool
    p4_support_status: Literal["P4_SUPPORTED", "P4_UNSUPPORTED"]
    p6_launch_cohort: bool
    blockers: list[str] = Field(default_factory=list)


class CatalogCoverageMatrixGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: str
    cluster: str
    product_type_group: str
    scene_strategy_id: str
    registry_status: Literal["ACTIVE", "REVIEW_REQUIRED", "UNREGISTERED"]
    scene_coverage_status: Literal["COVERED", "PARTIAL", "FALLBACK_ONLY"]
    p4_support_status: Literal["P4_SUPPORTED", "P4_UNSUPPORTED"]
    product_count: int = Field(ge=0)
    p6_launch_count: int = Field(ge=0)


class CatalogCoverageMatrixReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: Literal["p5.7_catalog_coverage_v1"]
    total_products: int = Field(ge=0)
    active_products: int = Field(ge=0)
    archived_products: int = Field(ge=0)
    product_truth_mapped_count: int = Field(ge=0)
    p4_supported_count: int = Field(ge=0)
    unknown_product_type_count: int = Field(ge=0)
    unknown_product_type_p4_supported_count: int = Field(ge=0)
    p6_launch_cohort_count: int = Field(ge=0)
    p6_launch_cohort_product_ids: list[str]
    blocked_by_reason: dict[str, int]
    coverage_groups: list[CatalogCoverageMatrixGroup]
    products: list[CatalogCoverageMatrixProduct]
    matrix_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CatalogAuthorityMatrixProduct(CatalogCoverageMatrixProduct):
    mapping_provenance: Literal[
        "SOURCE_TAXONOMY",
        "P5_8_PRODUCT_TRUTH_REVIEW",
        "MANUAL_TAXONOMY_REVIEW",
        "UNRESOLVED",
    ]
    mapping_reviewer_id: str | None = None
    mapping_reviewer_note: str | None = None
    taxonomy_reviewer_id: str | None = None
    taxonomy_reviewed_at: str | None = None
    terminal_state: Literal[
        "P6_READY",
        "REVIEW_BLOCKED_WITH_EXACT_REASON",
        "INSUFFICIENT_PRODUCT_TRUTH",
        "ARCHIVED_NOT_IN_SCOPE",
    ]
    terminal_reasons: list[str] = Field(default_factory=list)


class CatalogAuthorityMatrixReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version: Literal["p5.8_final_catalog_authority_v1"]
    total_products: int = Field(ge=0)
    active_products: int = Field(ge=0)
    archived_products: int = Field(ge=0)
    product_truth_mapped_count: int = Field(ge=0)
    p4_supported_count: int = Field(ge=0)
    unknown_product_type_count: int = Field(ge=0)
    unknown_product_type_p4_supported_count: int = Field(ge=0)
    terminal_state_counts: dict[str, int]
    p6_launch_cohort_count: int = Field(ge=0)
    p6_launch_cohort_product_ids: list[str]
    blocked_by_reason: dict[str, int]
    coverage_groups: list[CatalogCoverageMatrixGroup]
    products: list[CatalogAuthorityMatrixProduct]
    matrix_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
