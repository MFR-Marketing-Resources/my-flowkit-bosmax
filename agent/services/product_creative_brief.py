import logging
import json
import uuid
from agent.db import crud
from agent.services.product_intelligence import enrich_product

logger = logging.getLogger(__name__)

async def get_creative_brief(product_id: str) -> dict:
    """Generate a canonical creative brief from product intelligence."""
    raw_product = await crud.get_product(product_id)
    if not raw_product:
        return {"error": "Product not found"}
    
    product = await enrich_product(raw_product)

    # Calculate readiness from canonical enrichment
    mode_status = product.get("mode_readiness", {})
    missing = product.get("prompt_missing_fields") or []

    brief = {
        "brief_id": str(uuid.uuid4()),
        "product_id": product_id,
        "product_intelligence": {
            "product_short_name": product.get("product_short_name"),
            "raw_product_title": product.get("raw_product_title"),
            "category": product.get("category"),
            "subcategory": product.get("subcategory"),
            "type": product.get("type"),
            "price": product.get("price"),
            "commission_rate": product.get("commission_rate"),
            "image_readiness_status": product.get("image_readiness_status"),
            "source_url": product.get("source_url"),
            "tiktok_product_url": product.get("tiktok_product_url")
        },
        "commercial_signals": {
            "price": product.get("price"),
            "commission_rate": product.get("commission_rate"),
            "shop_name": product.get("shop_name")
        },
        "physics_dna": {
            "physics_class": product.get("physics_class"),
            "product_scale": product.get("product_scale"),
            "recommended_grip": product.get("recommended_grip"),
            "hand_object_interaction": product.get("hand_object_interaction"),
            "material_behavior": product.get("material_behavior"),
            "surface_behavior": product.get("surface_behavior"),
            "unsafe_handling_rules": product.get("unsafe_handling_rules") or [],
            "section_5_product_physics_prompt": product.get("section_5_product_physics_prompt")
        },
        "copywriting_route": {
            "product_type": product.get("product_type"),
            "product_type_id": product.get("product_type_id"),
            "silo": product.get("silo"),
            "trigger_id": product.get("trigger_id"),
            "formula": product.get("formula"),
            "copywriting_angle": product.get("copywriting_angle"),
            "claim_risk_level": product.get("claim_risk_level")
        },
        "creative_mapping": {
            "character_recommendations": product.get("character_recommendations") or [],
            "scene_context_recommendations": product.get("scene_context_recommendations") or [],
            "camera_recommendations": product.get("camera_recommendations") or [],
            "mode_recommendations": product.get("mode_recommendations") or [],
            "scene_context": product.get("scene_context"),
            "camera_style": product.get("camera_style"),
            "camera_behavior": product.get("camera_behavior"),
            "camera_shot": product.get("camera_shot"),
            "section_4_hint": product.get("section_4_hint"),
            "section_5_physics_hint": product.get("section_5_physics_hint"),
            "section_6_copy_hint": product.get("section_6_copy_hint"),
            "section_9_overlay_hint": product.get("section_9_overlay_hint"),
        },
        "readiness": {
            "Images": mode_status.get("Images", {}).get("status", "BLOCKED"),
            "Ingredients": mode_status.get("Ingredients", {}).get("status", "BLOCKED"),
            "Frames": mode_status.get("Frames", {}).get("status", "BLOCKED"),
            "Text to Video": mode_status.get("Text to Video", {}).get("status", "NEEDS_REVIEW")
        },
        "claim_boundaries": {
            "risk_level": product.get("claim_risk_level"),
            "restricted_keywords": ["guaranteed", "cure", "instant results"] if product.get("claim_risk_level") == "HIGH" else []
        },
        "missing_fields": missing
    }
    
    return brief

async def refresh_creative_brief(product_id: str) -> dict:
    """Re-run product intelligence to update the brief."""
    # In a real implementation, this might call an LLM or analyzer service.
    # For now, we return the current brief.
    return await get_creative_brief(product_id)
