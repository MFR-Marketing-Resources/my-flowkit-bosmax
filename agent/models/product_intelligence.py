from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProductIntelligenceResolveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str | None = None
    product_payload: dict[str, Any] | None = None


class ProductImageAnalysisResolveRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    product_id: str | None = None
    product_payload: dict[str, Any] | None = None
    image_url: str | None = None
    local_image_path: str | None = None
    raw_product_title: str | None = None


class ProductIntelligenceSalesMetrics(BaseModel):
    sold_count: int | None = None
    product_sold_count: int | None = None
    shop_total_sold_count: int | None = None
    shop_count: int | None = None
    shop_names: list[str] = Field(default_factory=list)
    source_status: str = "NOT_FOUND"
    sold_count_metric_scope: str = "UNKNOWN"
    sold_count_truth_status: str = "NOT_VERIFIED"
    sales_metric_warnings: list[str] = Field(default_factory=list)
    sales_metric_provenance: list[str] = Field(default_factory=list)
    sales_metrics_source: str = "NOT_FOUND"
    sales_metrics_batch_id: str | None = None
    matched_file_type: str | None = None
    matched_by: str | None = None
    raw_metric_column: str | None = None


class ProductIntelligenceImageAnalysis(BaseModel):
    status: str
    image_url: str | None = None
    local_image_path: str | None = None
    detected_package: str | None = None
    detected_text: list[str] = Field(default_factory=list)
    detected_brand: str | None = None
    detected_size_text: str | None = None
    detected_form_factor: str | None = None
    visual_confidence: str = "NOT_VERIFIED"
    evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider: str = "not_configured"
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


class AllProductMappingAuditExample(BaseModel):
    product_id: str
    title: str
    source_category: str | None = None
    source_subcategory: str | None = None
    source_type: str | None = None
    bosmax_group: str
    bosmax_family: str
    confidence: str
    copy_route: str
    claim_gate: str
    reason: str


class AllProductMappingAuditResponse(BaseModel):
    total_products: int
    source_distribution: dict[str, int] = Field(default_factory=dict)
    image_readiness_distribution: dict[str, int] = Field(default_factory=dict)
    image_analysis_status_distribution: dict[str, int] = Field(default_factory=dict)
    group_distribution: dict[str, int] = Field(default_factory=dict)
    sub_group_distribution: dict[str, int] = Field(default_factory=dict)
    type_of_product_distribution: dict[str, int] = Field(default_factory=dict)
    bosmax_family_distribution: dict[str, int] = Field(default_factory=dict)
    copy_route_distribution: dict[str, int] = Field(default_factory=dict)
    claim_gate_distribution: dict[str, int] = Field(default_factory=dict)
    intelligence_confidence_distribution: dict[str, int] = Field(default_factory=dict)
    taxonomy_conflict_count: int = 0
    needs_review_count: int = 0
    unknown_review_required_count: int = 0
    low_confidence_count: int = 0
    suspicious_high_confidence_count: int = 0
    source_taxonomy_contradiction_count: int = 0
    image_missing_count: int = 0
    semantic_unavailable_count: int = 0
    missing_sales_metrics_count: int = 0
    examples: list[AllProductMappingAuditExample] = Field(default_factory=list)
    write_back_status: str = "READ_ONLY_NO_DB_WRITES"
