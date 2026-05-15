from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductIntelligenceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str | None = None
    product_payload: dict[str, Any] | None = None


class ProductIntelligenceSalesMetrics(BaseModel):
    sold_count: int | None = None
    shop_count: int | None = None
    shop_names: list[str] = Field(default_factory=list)
    source_status: str = "NOT_FOUND"


class ProductIntelligenceImageAnalysis(BaseModel):
    status: str
    image_url: str | None = None
    local_image_path: str | None = None
    detected_package: str | None = None
    detected_text: str | None = None
    confidence: str = "NOT_VERIFIED"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductIntelligenceDestinationReadiness(BaseModel):
    TEXT_TO_VIDEO: str
    FRAMES: str
    INGREDIENTS: str
    IMAGE: str


class ProductIntelligenceProfile(BaseModel):
    product_id: str | None = None
    source: str = "UNKNOWN"
    normalized_title: str = ""
    brand: str | None = None
    group: str = "UNKNOWN_REVIEW_REQUIRED"
    sub_group: str = "UNKNOWN_REVIEW_REQUIRED"
    type_of_product: str = "UNKNOWN_REVIEW_REQUIRED"
    bosmax_product_family: str = "UNKNOWN_REVIEW_REQUIRED"
    package_form: str = "unknown"
    physical_state: str = "unknown"
    product_scale_class: str = "unknown"
    handling_profile: str = "review_required"
    scene_profile: str = "review_required"
    camera_profile: str = "review_required"
    copy_route: str = "REVIEW_REQUIRED"
    claim_gate: str = "CLAIM_REVIEW_REQUIRED"
    claim_tokens: list[str] = Field(default_factory=list)
    copy_formula: str = "REVIEW_REQUIRED"
    destination_readiness: ProductIntelligenceDestinationReadiness
    sales_metrics: ProductIntelligenceSalesMetrics
    image_analysis: ProductIntelligenceImageAnalysis
    confidence: str = "LOW"
    warnings: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    intelligence_status: str = "NEEDS_REVIEW"
    taxonomy_conflict: bool = False
    taxonomy_conflict_reason: str | None = None
    source_taxonomy: dict[str, str | None] = Field(default_factory=dict)


class ProductIntelligenceSummaryResponse(BaseModel):
    total_products: int
    products_by_source: dict[str, int] = Field(default_factory=dict)
    products_by_current_category: dict[str, int] = Field(default_factory=dict)
    products_by_current_type: dict[str, int] = Field(default_factory=dict)
    products_with_missing_category_or_type: int = 0
    products_with_source_taxonomy_conflict_risk: int = 0
    products_with_image_available: int = 0
    products_with_image_not_available: int = 0
    products_with_image_not_analyzed: int = 0
    products_with_sold_count_available: int = 0
    products_with_shop_count_available: int = 0
    products_with_shop_names_available: int = 0
    group_distribution: dict[str, int] = Field(default_factory=dict)
    copy_route_distribution: dict[str, int] = Field(default_factory=dict)
    claim_gate_distribution: dict[str, int] = Field(default_factory=dict)
    confidence_distribution: dict[str, int] = Field(default_factory=dict)
    sample_conflicts: list[dict[str, Any]] = Field(default_factory=list)


class ProductIntelligenceBackfillPreviewResponse(BaseModel):
    total_products: int
    resolved: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    needs_review: int
    taxonomy_conflicts: int
    copy_route_distribution: dict[str, int] = Field(default_factory=dict)
    claim_gate_distribution: dict[str, int] = Field(default_factory=dict)
    group_distribution: dict[str, int] = Field(default_factory=dict)
    sample_failures: list[dict[str, Any]] = Field(default_factory=list)
    sample_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    write_back_status: str = "READ_ONLY_NO_DB_WRITES"
