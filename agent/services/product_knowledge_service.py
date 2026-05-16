from __future__ import annotations

import json
import uuid
import re
from pathlib import Path
from typing import Any

from agent.models.product_knowledge import (
    ModeReadiness,
    ProductKnowledgeCompleteRequest,
    ProductKnowledgeCompleteResponse,
    AIFormImportResponse,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_intelligence_service import (
    BLOCKED_CLAIM_TOKENS,
    REVIEW_CLAIM_TOKENS,
    resolve_product_intelligence_profile,
)
from agent.services.product_physics import resolve_product_physics
from agent.services.product_mapping import normalize_mapping_text
from agent.config import BASE_DIR


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
        "target_customer": request.target_customer_text,
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


# --- AI-Assisted Form Pack ---

AI_FORM_TEMPLATE_V1 = """# BOSMAX Product Knowledge Intake Form v1.0

This form is designed to be completed by an AI assistant during a user interview.
The goal is to normalize unstructured product information into a structured JSON block.

## Instructions for AI Assistant:
1. Interview the user to collect all required fields.
2. Ask questions one-by-one or in small groups to avoid overwhelming the user.
3. If the user doesn't know a fact, use `null` or `"UNKNOWN"`. Do NOT hallucinate.
4. Detect risky medical/health/beauty claims and list them in `claim_safety_notes`.
5. When complete, provide the full Markdown content back to the user including the JSON block.

## Required Checklist:
- Product Identity (Name, Lane)
- Product Specs (Price, Size, Volume, Packaging)
- Product Knowledge (Description, Benefits, Usage, Ingredients, Warnings)
- Target Customer
- Evidence/Inference notes

## Structured Data (DO NOT MODIFY SCHEMA):

```json
{
  "bosmax_product_knowledge_form_version": "1.0",
  "completion_mode": "AI_ASSISTED_USER_INTERVIEW",
  "source_lane": "OWNED",
  "product_name": "",
  "product_knowledge_text": "",
  "benefits_text": "",
  "usage_text": "",
  "target_customer_text": "",
  "ingredients_text": "",
  "warnings_text": "",
  "price": null,
  "commission_rate": "",
  "size_or_volume": "",
  "package_notes": "",
  "image_url": "",
  "product_url": "",
  "paste_anything_about_product": "",
  "evidence_notes": {
    "what_user_confirmed": [],
    "what_ai_inferred": [],
    "unknown_or_unverified": [],
    "questions_still_unanswered": []
  },
  "claim_safety_notes": {
    "possible_claim_tokens": [],
    "risky_claims_detected": [],
    "safe_rewording_suggestions": []
  },
  "user_review_status": "USER_REVIEW_REQUIRED"
}
```
"""

AI_COACHING_PROMPT_V1 = """You are the BOSMAX Product Intelligence Coach. Your mission is to help the user complete their product registration by interviewing them and filling out a structured form.

I will provide you with a Markdown template called "BOSMAX_PRODUCT_KNOWLEDGE_INTAKE_FORM_v1.md".

Your process:
1. Greet the user and explain that you will help them register their product.
2. Look at the JSON schema in the template.
3. Start interviewing the user to fill in the missing fields:
   - What is the product name?
   - What does it do? (Description/Benefits)
   - How do people use it?
   - Who is it for?
   - What are the ingredients and warnings?
   - What is the price and size?
4. If the user provides messy text (e.g., WhatsApp chats, raw notes), extract the facts yourself but list them in "what_ai_inferred".
5. NEVER hallucinate facts. If the user doesn't provide it, keep it null or "UNKNOWN".
6. Be vigilant for risky claims (medical, "cure", "miracle", "whitening", "slimming"). Flag these in "risky_claims_detected".
7. Once you have enough information, generate the final Markdown file content with the completed JSON block.
8. Tell the user: "Here is your completed intake form. Copy this entire message, save it as a .md file, and upload it back to the BOSMAX dashboard."

Let's begin. What product are we registering today?
"""

def get_ai_form_template() -> dict[str, str]:
    return {
        "filename": "BOSMAX_PRODUCT_KNOWLEDGE_INTAKE_FORM_v1.md",
        "content_type": "text/markdown",
        "content": AI_FORM_TEMPLATE_V1
    }

def get_ai_coaching_prompt() -> str:
    return AI_COACHING_PROMPT_V1

def import_ai_form(file_content: str, file_name: str) -> AIFormImportResponse:
    import_id = str(uuid.uuid4())
    warnings = []
    errors = []
    
    # 1. Save raw file for audit trail
    import_dir = BASE_DIR / "data" / "product_knowledge" / "imports" / import_id / "raw"
    import_dir.mkdir(parents=True, exist_ok=True)
    with open(import_dir / file_name, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    # 2. Parse JSON block
    parsed_json = _parse_ai_form_content(file_content)
    if not parsed_json:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="PARSE_ERROR",
            parse_errors=["Could not find or parse a valid JSON block in the uploaded file."],
            provenance=["product_knowledge_import_service:v1"]
        )
    
    # 3. Validate version
    version = parsed_json.get("bosmax_product_knowledge_form_version")
    if not version:
        errors.append("MISSING_VERSION_FIELD")
    elif version != "1.0":
        errors.append(f"UNSUPPORTED_VERSION: {version}")
    
    if errors:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="VALIDATION_ERROR",
            parse_errors=errors,
            provenance=["product_knowledge_import_service:v1"]
        )
    
    # 4. Map to request
    request = ProductKnowledgeCompleteRequest(
        product_name=parsed_json.get("product_name"),
        product_knowledge_text=parsed_json.get("product_knowledge_text"),
        benefits_text=parsed_json.get("benefits_text"),
        usage_text=parsed_json.get("usage_text"),
        target_customer_text=parsed_json.get("target_customer_text"),
        ingredients_text=parsed_json.get("ingredients_text"),
        warnings_text=parsed_json.get("warnings_text"),
        price=parsed_json.get("price"),
        commission_rate=parsed_json.get("commission_rate"),
        size_or_volume=parsed_json.get("size_or_volume"),
        package_notes=parsed_json.get("package_notes"),
        source_lane=parsed_json.get("source_lane", "OWNED"),
        image_url=parsed_json.get("image_url"),
        product_url=parsed_json.get("product_url"),
        paste_anything_about_product=parsed_json.get("paste_anything_about_product")
    )
    
    # 5. Handle AI inference warnings
    evidence_notes = parsed_json.get("evidence_notes", {})
    inferred = evidence_notes.get("what_ai_inferred", [])
    if inferred:
        warnings.append(f"AI_INFERRED_FACTS_DETECTED: {', '.join(inferred)}")
    
    if parsed_json.get("user_review_status") != "USER_APPROVED":
        warnings.append("USER_REVIEW_NOT_EXPLICITLY_APPROVED_IN_FORM")
        
    # 6. Run completion
    completion = complete_product_knowledge(request)
    
    # Add affiliate warning if lane matches
    if request.source_lane in ["FASTMOSS", "TIKTOKSHOP"]:
        warnings.append("AFFILIATE_LANE_CONTAMINATION_RISK")

    return AIFormImportResponse(
        import_id=import_id,
        parse_status="PARSED",
        parsed_request=request,
        parse_warnings=warnings,
        completion_response=completion,
        provenance=["product_knowledge_import_service:v1"]
    )

def _parse_ai_form_content(text: str) -> dict[str, Any] | None:
    # Try to find fenced JSON block
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    # Fallback: try to find any JSON object
    match = re.search(r"(\{.*?\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
            
    return None
