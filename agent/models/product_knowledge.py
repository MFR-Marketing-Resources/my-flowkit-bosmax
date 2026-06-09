from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProductKnowledgeCompleteRequest(BaseModel):
    product_name: str | None = None
    product_knowledge_text: str | None = None
    benefits_text: str | None = None
    usage_text: str | None = None
    target_customer_text: str | None = None
    ingredients_text: str | None = None
    warnings_text: str | None = None
    price: float | None = None
    currency: str | None = "MYR"
    commission_amount: float | None = None
    commission_rate: str | None = None
    size_or_volume: str | None = None
    package_notes: str | None = None
    image_notes: str | None = None
    product_form_factor: str | None = None
    packaging_description: str | None = None
    source_lane: str = "OWNED"  # OWNED / MANUAL / FASTMOSS / TIKTOKSHOP / UNKNOWN
    image_url: str | None = None
    product_url: str | None = None
    source_url: str | None = None
    tiktok_product_url: str | None = None
    tiktok_shop_url: str | None = None
    local_image_path: str | None = None
    image_base64: str | None = None
    image_filename: str | None = None
    paste_anything_about_product: str | None = None
    category: str | None = None
    allow_live_image_analysis: bool = False


class ModeReadiness(BaseModel):
    status: str
    detail: str
    missing_evidence: list[str] = Field(default_factory=list)


class ProductKnowledgeCompleteResponse(BaseModel):
    completion_status: str  # COMPLETION_READY / NEEDS_REVIEW / BLOCKED
    input_quality_status: str  # SUFFICIENT / PARTIAL / POOR
    declared_evidence_summary: str
    declared_input_fields: dict[str, Any] = Field(default_factory=dict)
    extracted_product_facts: dict[str, Any]
    
    # Suggested fields (candidates for canonical)
    suggested_normalized_name: str | None = None
    suggested_size_or_volume: str | None = None
    suggested_package_notes: str | None = None
    suggested_source_lane: str | None = None
    suggested_category: str | None = None
    suggested_subcategory: str | None = None
    suggested_type: str | None = None
    suggested_bosmax_product_family: str | None = None
    suggested_package_form: str | None = None
    suggested_physical_state: str | None = None
    suggested_product_scale_class: str | None = None
    suggested_physics_class: str | None = None
    suggested_handling_profile: str | None = None
    suggested_recommended_grip: str | None = None
    suggested_section_5_product_physics_prompt: str | None = None
    suggested_copy_route: str | None = None
    suggested_copy_formula: str | None = None
    suggested_silo: str | None = None
    suggested_trigger_id: str | None = None
    suggested_target_customer: str | None = None
    suggested_usage_summary: str | None = None
    suggested_usp_list: list[str] = Field(default_factory=list)
    suggested_hook_angles: list[str] = Field(default_factory=list)
    suggested_cta_angles: list[str] = Field(default_factory=list)
    
    # Safety and Gating
    claim_tokens: list[str] = Field(default_factory=list)
    claim_gate: str = "CLAIM_REVIEW_REQUIRED"
    claim_risk_level: str = "HIGH"
    copy_safety_notes: str | None = None

    image_analysis_status: str = "IMAGE_MISSING"
    image_analysis_provider: str = "metadata_only"
    image_analysis_visual_confidence: str = "NOT_VERIFIED"
    image_analysis_warnings: list[str] = Field(default_factory=list)
    image_analysis_detected_package: str | None = None
    image_analysis_detected_text: list[str] = Field(default_factory=list)
    image_analysis_local_image_path: str | None = None
    image_analysis_image_url: str | None = None
    extraction_status: str | None = None
    
    # Missing / Review Fields
    missing_required_evidence: list[str] = Field(default_factory=list)
    human_review_fields: list[str] = Field(default_factory=list)
    blocked_fields: list[str] = Field(default_factory=list)
    
    # Readiness
    readiness_by_mode: dict[str, ModeReadiness] = Field(default_factory=dict)
    
    provenance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AIFormImportResponse(BaseModel):
    import_id: str
    parse_status: str  # PARSED / PARSE_ERROR / VALIDATION_ERROR
    parse_error_code: str | None = None
    parse_error_detail: str | None = None
    parsed_request: ProductKnowledgeCompleteRequest | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    accepted_formats: list[str] = Field(default_factory=list)
    detected_extension: str | None = None
    detected_content_type: str | None = None
    parser_strategy_used: str | None = None
    completion_response: ProductKnowledgeCompleteResponse | None = None
    write_back_status: str = "READ_ONLY_COMPLETION_PREVIEW"
    user_review_required: bool = True
    provenance: list[str] = Field(default_factory=list)
