from __future__ import annotations

import re
from typing import Any

from agent.models.product_knowledge import (
    ModeReadiness,
    ProductKnowledgeCompleteRequest,
    ProductKnowledgeCompleteResponse,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_intelligence_service import (
    BLOCKED_CLAIM_TOKENS,
    REVIEW_CLAIM_TOKENS,
    resolve_product_intelligence_profile,
)
from agent.services.product_physics import resolve_product_physics
from agent.services.product_mapping import normalize_mapping_text


def complete_product_knowledge(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteResponse:
    # 1. Fact Extraction from messy text
    extracted_facts = _extract_facts(request)
    
    # 2. Build temporary product dictionary for inference
    temp_product = _build_temp_product(request, extracted_facts)
    
    # 3. Resolve Intelligence and Physics
    intelligence = resolve_product_intelligence_profile(temp_product)
    physics = resolve_product_physics(product=temp_product)
    
    # 4. Determine Completion Status
    completion_status, input_quality, missing_evidence = _evaluate_completion_status(request, extracted_facts, intelligence)
    
    # 5. Claim Analysis
    claim_gate, claim_tokens, claim_risk, copy_safety = _analyze_claims(request, extracted_facts)
    
    # 6. Build Readiness
    readiness = _evaluate_mode_readiness(intelligence, physics, missing_evidence)
    
    # 7. Map suggested fields
    suggested_usp_list = extracted_facts.get("usp_list", [])
    if not suggested_usp_list and request.benefits_text:
        # Basic split by newline or bullet
        suggested_usp_list = [line.strip("- *•").strip() for line in request.benefits_text.split("\n") if line.strip()]

    return ProductKnowledgeCompleteResponse(
        completion_status=completion_status,
        input_quality_status=input_quality,
        declared_evidence_summary=_build_evidence_summary(request, extracted_facts),
        extracted_product_facts=extracted_facts,
        suggested_normalized_name=temp_product.get("product_display_name"),
        suggested_category=intelligence.get("group"),
        suggested_subcategory=intelligence.get("sub_group"),
        suggested_type=intelligence.get("type_of_product"),
        suggested_bosmax_product_family=intelligence.get("bosmax_product_family"),
        suggested_package_form=intelligence.get("package_form"),
        suggested_physical_state=intelligence.get("physical_state"),
        suggested_product_scale_class=intelligence.get("product_scale_class"),
        suggested_physics_class=physics.get("physics_class"),
        suggested_handling_profile=intelligence.get("handling_profile"),
        suggested_recommended_grip=physics.get("recommended_grip"),
        suggested_section_5_product_physics_prompt=physics.get("section_5_product_physics_prompt"),
        suggested_copy_route=intelligence.get("copy_route"),
        suggested_copy_formula=intelligence.get("copy_formula"),
        suggested_usp_list=suggested_usp_list[:5],
        claim_tokens=claim_tokens,
        claim_gate=claim_gate,
        claim_risk_level=claim_risk,
        copy_safety_notes=copy_safety,
        missing_required_evidence=missing_evidence,
        human_review_fields=_identify_review_fields(intelligence, physics, claim_gate),
        readiness_by_mode=readiness,
        provenance=["product_knowledge_completion_service:v1"],
        warnings=intelligence.get("warnings", []) + (["AFFILIATE_LANE_CONTAMINATION_RISK"] if request.source_lane in ["FASTMOSS", "TIKTOKSHOP"] else []),
        errors=intelligence.get("errors", [])
    )


def _extract_facts(request: ProductKnowledgeCompleteRequest) -> dict[str, Any]:
    facts = {}
    combined_text = " ".join(filter(None, [
        request.product_name,
        request.product_knowledge_text,
        request.paste_anything_about_product,
        request.benefits_text,
        request.ingredients_text
    ]))
    
    # Simple regex for price
    price_match = re.search(r"(?:RM|Price|Harga)\s*[:=]?\s*(\d+(?:\.\d{2})?)", combined_text, re.I)
    if price_match:
        facts["price"] = float(price_match.group(1))
    elif request.price:
        facts["price"] = request.price
        
    # Simple regex for size/volume
    size_match = re.search(r"(\d+(?:\.\d+)?\s*(?:ml|g|kg|cm|mm|oz|liter|litre))", combined_text, re.I)
    if size_match:
        facts["size_or_volume"] = size_match.group(1)
    elif request.size_or_volume:
        facts["size_or_volume"] = request.size_or_volume
        
    # Extraction of USP/Benefits from text
    usp_list = []
    if request.benefits_text:
        # Already handled in main loop if needed, but let's look for keywords
        pass
        
    facts["usp_list"] = usp_list
    return facts


def _build_temp_product(request: ProductKnowledgeCompleteRequest, extracted_facts: dict[str, Any]) -> dict[str, Any]:
    name = request.product_name or "Unknown Manual Product"
    return {
        "raw_product_title": name,
        "product_display_name": name,
        "source": request.source_lane or "MANUAL",
        "category": None,  # Will be inferred
        "price": extracted_facts.get("price") or request.price,
        "size_or_volume": extracted_facts.get("size_or_volume") or request.size_or_volume,
        "ingredients": request.ingredients_text,
        "benefits": request.benefits_text,
        "usage": request.usage_text,
        "warnings": request.warnings_text,
    }


def _evaluate_completion_status(
    request: ProductKnowledgeCompleteRequest, 
    facts: dict[str, Any],
    intelligence: dict[str, Any]
) -> tuple[str, str, list[str]]:
    missing = []
    if not request.product_name:
        missing.append("PRODUCT_NAME")
    if not request.product_knowledge_text and not request.paste_anything_about_product:
        missing.append("PRODUCT_DESCRIPTION_OR_KNOWLEDGE")
    if not facts.get("size_or_volume") and not request.size_or_volume:
        missing.append("SIZE_OR_VOLUME_EVIDENCE")
    
    if intelligence.get("bosmax_product_family") == "UNKNOWN_REVIEW_REQUIRED":
        missing.append("CLEAR_PRODUCT_FAMILY_INFERENCE")

    if not missing:
        return "COMPLETION_READY", "SUFFICIENT", []
    
    status = "NEEDS_REVIEW"
    quality = "PARTIAL" if len(missing) < 3 else "POOR"
    return status, quality, missing


def _analyze_claims(request: ProductKnowledgeCompleteRequest, facts: dict[str, Any]) -> tuple[str, list[str], str, str]:
    combined_text = normalize_mapping_text(" ".join(filter(None, [
        request.product_knowledge_text,
        request.benefits_text,
        request.ingredients_text,
        request.warnings_text,
        request.paste_anything_about_product
    ])))
    
    found_blocked = [token for token in BLOCKED_CLAIM_TOKENS if token in combined_text]
    found_review = [token for token in REVIEW_CLAIM_TOKENS if token in combined_text]
    
    all_tokens = list(set(found_blocked + found_review))
    
    if found_blocked:
        return "CLAIM_BLOCKED", all_tokens, "CRITICAL", "Medical cure or hard claims detected. NOT ALLOWED for direct copy."
    
    if found_review:
        return "CLAIM_REVIEW_REQUIRED", all_tokens, "HIGH", "Sensitive health/beauty claims detected. Requires human verification."
        
    return "CLAIM_SAFE", [], "LOW", "No high-risk claims detected in text."


def _evaluate_mode_readiness(intelligence: dict[str, Any], physics: dict[str, Any], missing_evidence: list[str]) -> dict[str, ModeReadiness]:
    readiness = {}
    
    # Registration readiness
    reg_status = "READY" if not missing_evidence else "NEEDS_EVIDENCE"
    readiness["registration"] = ModeReadiness(
        status=reg_status,
        detail="Enough structured data for draft registration" if reg_status == "READY" else "Requires more evidence for canonical truth",
        missing_evidence=missing_evidence
    )
    
    # Asset generator readiness
    asset_status = "READY" if physics.get("section_5_product_physics_prompt") else "NEEDS_PHYSICS"
    readiness["product_asset_generator"] = ModeReadiness(
        status=asset_status,
        detail="Physics profile derived successfully" if asset_status == "READY" else "Missing physical evidence for prompt generation",
        missing_evidence=[m for m in missing_evidence if "PHYSICS" in m or "SIZE" in m]
    )
    
    return readiness


def _build_evidence_summary(request: ProductKnowledgeCompleteRequest, facts: dict[str, Any]) -> str:
    summary = []
    if request.product_name:
        summary.append(f"Name: {request.product_name}")
    if facts.get("price"):
        summary.append(f"Price: RM{facts['price']}")
    if facts.get("size_or_volume"):
        summary.append(f"Size: {facts['size_or_volume']}")
    if request.source_lane:
        summary.append(f"Source: {request.source_lane}")
    return " | ".join(summary)


def _identify_review_fields(intelligence: dict[str, Any], physics: dict[str, Any], claim_gate: str) -> list[str]:
    fields = []
    if intelligence.get("confidence") == "LOW":
        fields.extend(["category", "subcategory", "type", "bosmax_product_family"])
    if claim_gate != "CLAIM_SAFE":
        fields.append("claims")
    if not physics.get("section_5_product_physics_prompt"):
        fields.append("physics_profile")
    return list(set(fields))
