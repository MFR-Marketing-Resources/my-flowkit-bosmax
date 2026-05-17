from __future__ import annotations

import base64
import json
import uuid
import re
from dataclasses import dataclass, field
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
from agent.services.product_mapping import normalize_mapping_text, resolve_product_mapping
from agent.config import BASE_DIR


AI_FORM_ACCEPTED_FORMATS = [
    ".md with fenced ```json block",
    ".markdown with fenced ```json block",
    ".json raw object",
    ".JSON raw object",
    ".txt raw JSON text",
]

SOURCE_LANE_ALIASES = {
    "OWNED": "OWNED",
    "MANUAL": "MANUAL",
    "FASTMOSS": "FASTMOSS",
    "FASTMOSS_REFERENCE": "FASTMOSS",
    "TIKTOKSHOP": "TIKTOKSHOP",
    "TIKTOKSHOP_DRAFT": "TIKTOKSHOP",
    "UNKNOWN": "UNKNOWN",
    "UNKNOWN_REVIEW_REQUIRED": "UNKNOWN",
}


@dataclass
class _AIFormParseResult:
    parsed_json: dict[str, Any] | None = None
    strategy_used: str | None = None
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None


def _normalize_source_lane(value: str | None) -> str:
    normalized = str(value or "OWNED").strip().upper()
    return SOURCE_LANE_ALIASES.get(normalized, normalized or "OWNED")


def _infer_image_extension(filename: str | None) -> str:
    if filename and "." in filename:
        suffix = filename.rsplit(".", 1)[-1].strip().lower()
        if suffix:
            return suffix
    return "jpg"


def _persist_intake_image(image_base64: str | None, image_filename: str | None) -> str | None:
    if not image_base64:
        return None
    payload = image_base64.split(",", 1)[-1]
    data = base64.b64decode(payload)
    intake_dir = BASE_DIR / "data" / "product_registration" / "intake_images"
    intake_dir.mkdir(parents=True, exist_ok=True)
    dest = intake_dir / f"{uuid.uuid4().hex}.{_infer_image_extension(image_filename)}"
    dest.write_bytes(data)
    return str(dest)


def _normalize_completion_request(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteRequest:
    local_image_path = request.local_image_path
    if not local_image_path and request.image_base64:
        local_image_path = _persist_intake_image(request.image_base64, request.image_filename)

    source_url = request.source_url or request.product_url or request.tiktok_product_url or request.tiktok_shop_url
    product_url = request.product_url or request.source_url or request.tiktok_product_url
    tiktok_product_url = request.tiktok_product_url or (
        source_url if _normalize_source_lane(request.source_lane) == "TIKTOKSHOP" else None
    )

    return request.model_copy(
        update={
            "source_lane": _normalize_source_lane(request.source_lane),
            "local_image_path": local_image_path,
            "source_url": source_url,
            "product_url": product_url,
            "tiktok_product_url": tiktok_product_url,
            "currency": request.currency or "MYR",
        }
    )


def _resolve_extraction_status(request: ProductKnowledgeCompleteRequest) -> str | None:
    if request.source_lane == "TIKTOKSHOP" and (
        request.tiktok_product_url or request.tiktok_shop_url or request.product_url or request.source_url
    ):
        return "NOT_IMPLEMENTED"
    return None


def complete_product_knowledge(
    request: ProductKnowledgeCompleteRequest,
) -> ProductKnowledgeCompleteResponse:
    request = _normalize_completion_request(request)

    # 1. Fact Extraction from messy text
    extracted_facts = _extract_facts(request)

    # 2. Claim Analysis first so manual-owned sensitive lanes can influence taxonomy safely.
    claim_gate, claim_tokens, claim_risk, copy_safety = _analyze_claims(request, extracted_facts)
    taxonomy_candidate = _resolve_taxonomy_candidate(request, extracted_facts, claim_tokens)

    # 3. Build temporary product dictionary for inference
    temp_product = _build_temp_product(request, extracted_facts, taxonomy_candidate)

    # 4. Resolve Intelligence and Physics
    intelligence = resolve_product_intelligence_profile(temp_product)
    physics_seed = dict(temp_product)
    physics_seed["bosmax_product_family"] = intelligence.get("bosmax_product_family")
    physics = resolve_product_physics(product=physics_seed)

    # 5. Determine Completion Status
    completion_status, input_quality, missing_evidence = _evaluate_completion_status(request, extracted_facts, intelligence)

    # 6. Build Readiness
    readiness = _evaluate_mode_readiness(intelligence, physics, missing_evidence)
    
    # 7. Map suggested fields
    suggested_usp_list = extracted_facts.get("usp_list", [])
    if not suggested_usp_list and request.benefits_text:
        # Basic split by newline or bullet
        suggested_usp_list = [line.strip("- *•").strip() for line in request.benefits_text.split("\n") if line.strip()]

    normalized_name = _build_normalized_name(request, extracted_facts)
    image_analysis = dict(intelligence.get("image_analysis") or {})
    warnings = list(intelligence.get("warnings", []))
    extraction_status = _resolve_extraction_status(request)
    if extraction_status == "NOT_IMPLEMENTED":
        warnings.append("TIKTOKSHOP_EXTRACTION_NOT_IMPLEMENTED")
        if "TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED" not in missing_evidence:
            missing_evidence.append("TIKTOKSHOP_MANUAL_COMPLETION_REQUIRED")

    return ProductKnowledgeCompleteResponse(
        completion_status=completion_status,
        input_quality_status=input_quality,
        declared_evidence_summary=_build_evidence_summary(request, extracted_facts),
        declared_input_fields=_build_declared_input_fields(request),
        extracted_product_facts=extracted_facts,
        suggested_normalized_name=normalized_name,
        suggested_size_or_volume=extracted_facts.get("size_or_volume") or request.size_or_volume,
        suggested_package_notes=request.package_notes,
        suggested_source_lane=request.source_lane,
        suggested_category=taxonomy_candidate.get("category"),
        suggested_subcategory=taxonomy_candidate.get("subcategory"),
        suggested_type=taxonomy_candidate.get("type"),
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
        suggested_silo=taxonomy_candidate.get("silo"),
        suggested_trigger_id=taxonomy_candidate.get("trigger_id"),
        suggested_usp_list=suggested_usp_list[:5],
        claim_tokens=claim_tokens,
        claim_gate=claim_gate,
        claim_risk_level=claim_risk,
        copy_safety_notes=copy_safety,
        image_analysis_status=str(image_analysis.get("status") or "IMAGE_MISSING"),
        image_analysis_provider=str(image_analysis.get("provider") or "metadata_only"),
        image_analysis_visual_confidence=str(image_analysis.get("visual_confidence") or "NOT_VERIFIED"),
        image_analysis_warnings=list(image_analysis.get("warnings") or []),
        image_analysis_detected_package=image_analysis.get("detected_package"),
        image_analysis_detected_text=list(image_analysis.get("detected_text") or []),
        image_analysis_local_image_path=image_analysis.get("local_image_path"),
        image_analysis_image_url=image_analysis.get("image_url"),
        extraction_status=extraction_status,
        missing_required_evidence=missing_evidence,
        human_review_fields=_identify_review_fields(intelligence, physics, claim_gate),
        readiness_by_mode=readiness,
        provenance=["product_knowledge_completion_service:v1"],
        warnings=warnings + (["AFFILIATE_LANE_CONTAMINATION_RISK"] if request.source_lane in ["FASTMOSS", "TIKTOKSHOP"] else []),
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


def _build_temp_product(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
    taxonomy_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = _build_normalized_name(request, extracted_facts) or "Unknown Manual Product"
    taxonomy_candidate = taxonomy_candidate or {}
    return {
        "raw_product_title": name,
        "product_display_name": name,
        "source": request.source_lane or "MANUAL",
        "category": taxonomy_candidate.get("category"),
        "subcategory": taxonomy_candidate.get("subcategory"),
        "type": taxonomy_candidate.get("type"),
        "price": extracted_facts.get("price") or request.price,
        "size_or_volume": extracted_facts.get("size_or_volume") or request.size_or_volume,
        "ingredients": request.ingredients_text,
        "benefits": request.benefits_text,
        "usage": request.usage_text,
        "warnings": request.warnings_text,
        "target_customer": request.target_customer_text,
        "product_knowledge_text": request.product_knowledge_text,
        "package_notes": request.package_notes,
        "currency": request.currency,
        "commission_amount": request.commission_amount,
        "commission_rate": request.commission_rate,
        "image_url": request.image_url,
        "local_image_path": request.local_image_path,
        "source_url": request.source_url or request.product_url,
        "tiktok_product_url": request.tiktok_product_url or request.tiktok_shop_url,
    }


def _build_normalized_name(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
) -> str | None:
    base_name = (request.product_name or "").strip()
    if not base_name:
        return None
    size = str(extracted_facts.get("size_or_volume") or request.size_or_volume or "").strip()
    if not size:
        return base_name
    if normalize_mapping_text(size) in normalize_mapping_text(base_name):
        return base_name
    return f"{base_name} {size}".strip()


def _build_declared_input_fields(request: ProductKnowledgeCompleteRequest) -> dict[str, Any]:
    payload = request.model_dump()
    return {
        key: value
        for key, value in payload.items()
        if key not in {"image_base64"} and value not in (None, "", [], {})
    }


def _resolve_taxonomy_candidate(
    request: ProductKnowledgeCompleteRequest,
    extracted_facts: dict[str, Any],
    claim_tokens: list[str],
) -> dict[str, Any]:
    mapping_seed_text = " ".join(
        filter(
            None,
            [
                request.product_name,
                request.product_knowledge_text,
                request.benefits_text,
                request.usage_text,
                request.target_customer_text,
                request.paste_anything_about_product,
            ],
        )
    ).strip()
    normalized_name = _build_normalized_name(request, extracted_facts) or request.product_name or "Unknown Manual Product"
    base_product = {
        "raw_product_title": mapping_seed_text or normalized_name,
        "product_display_name": normalized_name,
        "product_short_name": normalized_name,
        "source": request.source_lane or "MANUAL",
    }
    mapping = resolve_product_mapping(product=base_product, source_hint=request.source_lane)
    candidate = {
        "category": mapping.get("category") or None,
        "subcategory": mapping.get("subcategory") or None,
        "type": mapping.get("type") or None,
        "silo": mapping.get("silo") or None,
        "trigger_id": mapping.get("trigger_id") or None,
    }

    combined_text = normalize_mapping_text(
        " ".join(
            filter(
                None,
                [
                    request.product_name,
                    request.product_knowledge_text,
                    request.benefits_text,
                    request.usage_text,
                    request.target_customer_text,
                    request.paste_anything_about_product,
                ],
            )
        )
    )
    male_health_tokens = {
        "tenaga batin",
        "batin lelaki",
        "bahagian intim",
        "ketegangan",
        "kelelakian",
        "stamina lelaki",
        "prestasi fizikal lelaki",
        "otot kelelakian",
        "male_health_sensitive",
    }
    female_health_tokens = {
        "jamu perapat",
        "jamu wanita",
        "kewanitaan",
        "miss v",
        "faraj",
        "vagina",
        "keputihan",
        "bau",
        "gatal",
        "rapat",
        "ketat",
        "anjal",
        "postpartum",
        "selepas bersalin",
        "intimate",
        "feminine hygiene",
        "feminine care",
        "female_health_sensitive",
    }
    owned_lane = str(request.source_lane or "").upper() in {"OWNED", "MANUAL"}
    if owned_lane and (
        any(token in male_health_tokens for token in claim_tokens)
        or any(token in combined_text for token in male_health_tokens if token != "male_health_sensitive")
    ):
        candidate.update(
            {
                "category": "Health",
                "subcategory": "Supplements",
                "type": "Male Health",
                "silo": "health_supp_stealth_01",
                "trigger_id": "EGO_01",
            }
        )
    elif owned_lane and (
        any(token in female_health_tokens for token in claim_tokens)
        or any(token in combined_text for token in female_health_tokens if token != "female_health_sensitive")
    ):
        candidate.update(
            {
                "category": "Health",
                "subcategory": "Feminine Care",
                "type": "Female Health",
                "silo": "female_health_stealth_01",
                "trigger_id": "FEMALE_01",
            }
        )
    return candidate


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
    if request.price is None:
        missing.append("PRICE_EVIDENCE")
    if not request.currency:
        missing.append("CURRENCY_EVIDENCE")
    if request.commission_amount is None and (
        not request.commission_rate or str(request.commission_rate).strip().upper() == "UNKNOWN"
    ):
        missing.append("COMMISSION_EVIDENCE")
    if not request.commission_rate or str(request.commission_rate).strip().upper() == "UNKNOWN":
        missing.append("COMMISSION_RATE_EVIDENCE")
    
    if intelligence.get("bosmax_product_family") == "UNKNOWN_REVIEW_REQUIRED":
        missing.append("CLEAR_PRODUCT_FAMILY_INFERENCE")

    if not missing:
        return "COMPLETION_READY", "SUFFICIENT", []
    
    status = "NEEDS_REVIEW"
    quality = "PARTIAL" if len(missing) < 3 else "POOR"
    return status, quality, missing


def _analyze_claims(request: ProductKnowledgeCompleteRequest, facts: dict[str, Any]) -> tuple[str, list[str], str, str]:
    combined_text = normalize_mapping_text(" ".join(filter(None, [
        request.product_name,
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

    image_analysis = dict(intelligence.get("image_analysis") or {})
    has_image_reference = bool(image_analysis.get("image_url") or image_analysis.get("local_image_path"))
    image_missing = [] if has_image_reference else ["IMAGE_REFERENCE_REQUIRED"]
    t2v_status = "READY" if not missing_evidence else "NEEDS_REVIEW"
    image_mode_status = "READY" if has_image_reference else "IMAGE_REFERENCE_REQUIRED"

    readiness["T2V"] = ModeReadiness(
        status=t2v_status,
        detail="Identity and taxonomy are sufficient for text-first video drafting." if t2v_status == "READY" else "Requires reviewed taxonomy/claims or missing evidence resolution.",
        missing_evidence=missing_evidence,
    )
    readiness["IMG"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for visual/media generation lanes.",
        missing_evidence=image_missing,
    )
    readiness["I2V"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied for ingredient/reference-driven video." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for ingredient/reference-driven video.",
        missing_evidence=image_missing,
    )
    readiness["F2V"] = ModeReadiness(
        status=image_mode_status,
        detail="Image reference supplied for frames-first video." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for frames-first video.",
        missing_evidence=image_missing,
    )
    readiness["Ingredients"] = ModeReadiness(
        status=image_mode_status,
        detail="Ingredient lane has required reference." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for Ingredients lane.",
        missing_evidence=image_missing,
    )
    readiness["Frames"] = ModeReadiness(
        status=image_mode_status,
        detail="Frames lane has required reference." if has_image_reference else "IMAGE_REFERENCE_REQUIRED for Frames lane.",
        missing_evidence=image_missing,
    )
    readiness["prompt_generation"] = ModeReadiness(
        status="READY" if t2v_status == "READY" else "NEEDS_REVIEW",
        detail="Prompt generation may proceed with safe identity fields only." if t2v_status == "READY" else "Prompt generation remains review-gated until taxonomy/claims evidence is settled.",
        missing_evidence=missing_evidence,
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
    if request.currency:
        summary.append(f"Currency: {request.currency}")
    if request.commission_amount is not None:
        summary.append(f"Commission Amount: {request.commission_amount}")
    if request.commission_rate:
        summary.append(f"Commission Rate: {request.commission_rate}")
    if request.product_url or request.source_url:
        summary.append(f"Source URL: {request.product_url or request.source_url}")
    if request.image_url or request.local_image_path:
        summary.append("Image Evidence: PRESENT")
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
  "currency": "MYR",
  "commission_amount": null,
  "commission_rate": "",
  "size_or_volume": "",
  "package_notes": "",
  "image_url": "",
  "product_url": "",
  "source_url": "",
  "tiktok_product_url": "",
  "tiktok_shop_url": "",
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

def import_ai_form(
    file_content: str,
    file_name: str,
    content_type: str | None = None,
) -> AIFormImportResponse:
    import_id = str(uuid.uuid4())
    detected_extension = _detect_extension(file_name)
    
    # 1. Save raw file for audit trail
    import_dir = BASE_DIR / "data" / "product_knowledge" / "imports" / import_id / "raw"
    import_dir.mkdir(parents=True, exist_ok=True)
    with open(import_dir / file_name, "w", encoding="utf-8") as f:
        f.write(file_content)
    
    # 2. Parse JSON block
    parse_result = _parse_ai_form_content(
        file_content,
        file_name=file_name,
        content_type=content_type,
    )
    if not parse_result.parsed_json:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="PARSE_ERROR",
            parse_error_code=parse_result.error_code,
            parse_error_detail=parse_result.error_detail,
            parse_errors=[parse_result.error_detail or "Could not parse uploaded AI-assisted form."],
            parse_warnings=parse_result.warnings,
            accepted_formats=AI_FORM_ACCEPTED_FORMATS,
            detected_extension=detected_extension,
            detected_content_type=content_type,
            parser_strategy_used=parse_result.strategy_used,
            provenance=["product_knowledge_import_service:v1"]
        )
    parsed_json = parse_result.parsed_json
    
    # 3. Validate version
    validation_errors: list[str] = []
    version = parsed_json.get("bosmax_product_knowledge_form_version")
    if not version:
        validation_errors.append("MISSING_REQUIRED_KEYS")
    elif version != "1.0":
        validation_errors.append(f"UNSUPPORTED_VERSION: {version}")
    
    if validation_errors:
        return AIFormImportResponse(
            import_id=import_id,
            parse_status="VALIDATION_ERROR",
            parse_error_code="UNSUPPORTED_VERSION" if version else "MISSING_REQUIRED_KEYS",
            parse_error_detail=(
                f"Unsupported bosmax_product_knowledge_form_version: {version}"
                if version
                else "Required key missing: bosmax_product_knowledge_form_version"
            ),
            parse_errors=validation_errors,
            parse_warnings=parse_result.warnings,
            accepted_formats=AI_FORM_ACCEPTED_FORMATS,
            detected_extension=detected_extension,
            detected_content_type=content_type,
            parser_strategy_used=parse_result.strategy_used,
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
        currency=parsed_json.get("currency"),
        commission_amount=parsed_json.get("commission_amount"),
        commission_rate=parsed_json.get("commission_rate"),
        size_or_volume=parsed_json.get("size_or_volume"),
        package_notes=parsed_json.get("package_notes"),
        source_lane=parsed_json.get("source_lane", "OWNED"),
        image_url=parsed_json.get("image_url"),
        product_url=parsed_json.get("product_url"),
        source_url=parsed_json.get("source_url"),
        tiktok_product_url=parsed_json.get("tiktok_product_url"),
        tiktok_shop_url=parsed_json.get("tiktok_shop_url"),
        paste_anything_about_product=parsed_json.get("paste_anything_about_product")
    )
    request = _normalize_completion_request(request)
    
    # 5. Handle AI inference warnings
    warnings = list(parse_result.warnings)
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
        accepted_formats=AI_FORM_ACCEPTED_FORMATS,
        detected_extension=detected_extension,
        detected_content_type=content_type,
        parser_strategy_used=parse_result.strategy_used,
        completion_response=completion,
        provenance=["product_knowledge_import_service:v1"]
    )

def _detect_extension(file_name: str | None) -> str:
    if not file_name or "." not in file_name:
        return ""
    return file_name.rsplit(".", 1)[-1]


def _json_error_detail(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg} (line {exc.lineno}, column {exc.colno})"


def _find_balanced_json_object_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                spans.append((start, index + 1))
                start = None
    return spans


def _parse_ai_form_content(
    text: str,
    *,
    file_name: str | None = None,
    content_type: str | None = None,
) -> _AIFormParseResult:
    normalized = text.lstrip("\ufeff").strip()
    extension = _detect_extension(file_name).lower()
    decoder = json.JSONDecoder()

    fenced_blocks = [
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", normalized, re.IGNORECASE | re.DOTALL)
    ]
    if fenced_blocks:
        if len(fenced_blocks) > 1:
            return _AIFormParseResult(
                strategy_used="FENCED_JSON",
                error_code="MULTIPLE_JSON_OBJECTS_FOUND",
                error_detail="Multiple fenced JSON objects were found. Keep only one canonical JSON object in the uploaded file.",
            )
        try:
            parsed = json.loads(fenced_blocks[0])
            if isinstance(parsed, dict):
                return _AIFormParseResult(parsed_json=parsed, strategy_used="FENCED_JSON")
        except json.JSONDecodeError as exc:
            return _AIFormParseResult(
                strategy_used="FENCED_JSON",
                error_code="INVALID_JSON",
                error_detail=f"Malformed fenced JSON block: {_json_error_detail(exc)}",
            )

    if normalized.startswith("{"):
        try:
            parsed = json.loads(normalized)
            if isinstance(parsed, dict):
                strategy = "RAW_JSON_TEXT" if extension == "txt" or (content_type or "").startswith("text/plain") else "RAW_JSON"
                return _AIFormParseResult(parsed_json=parsed, strategy_used=strategy)
        except json.JSONDecodeError as exc:
            direct_error = _json_error_detail(exc)
        else:
            direct_error = None
    else:
        direct_error = None

    spans = _find_balanced_json_object_spans(normalized)
    if len(spans) > 1:
        return _AIFormParseResult(
            strategy_used="BALANCED_OBJECT_EXTRACTION",
            error_code="MULTIPLE_JSON_OBJECTS_FOUND",
            error_detail="Multiple JSON objects were found in the uploaded text. Keep only one canonical object.",
        )
    if len(spans) == 1:
        start, end = spans[0]
        candidate = normalized[start:end]
        try:
            parsed, parsed_end = decoder.raw_decode(candidate)
        except json.JSONDecodeError as exc:
            return _AIFormParseResult(
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                error_code="INVALID_JSON",
                error_detail=f"Balanced JSON object extraction failed: {_json_error_detail(exc)}",
            )
        trailing = candidate[parsed_end:].strip()
        if trailing:
            return _AIFormParseResult(
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                error_code="INVALID_JSON",
                error_detail="Balanced JSON object contains trailing content after the parsed object.",
            )
        if isinstance(parsed, dict):
            warning = "FALLBACK_BALANCED_OBJECT_EXTRACTION_USED"
            return _AIFormParseResult(
                parsed_json=parsed,
                strategy_used="BALANCED_OBJECT_EXTRACTION",
                warnings=[warning],
            )

    if direct_error:
        return _AIFormParseResult(
            strategy_used="RAW_JSON_TEXT" if extension == "txt" else "RAW_JSON",
            error_code="INVALID_JSON",
            error_detail=f"Raw JSON parse failed: {direct_error}",
        )

    return _AIFormParseResult(
        strategy_used="RAW_JSON_TEXT" if extension == "txt" else "BALANCED_OBJECT_EXTRACTION",
        error_code="NO_JSON_FOUND",
        error_detail="No valid JSON object was found. Accepted formats: fenced ```json markdown, raw .json/.JSON, or raw JSON in .txt.",
    )
