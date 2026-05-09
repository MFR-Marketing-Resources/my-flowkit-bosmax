import logging
import json
import uuid
from agent.db import crud

logger = logging.getLogger(__name__)

async def get_creative_brief(product_id: str) -> dict:
    """Generate a canonical creative brief from product intelligence."""
    product = await crud.get_product(product_id)
    if not product:
        return {"error": "Product not found"}

    # Calculate readiness
    image_ready = product.get("asset_status") in ["DOWNLOADED", "UPLOADED_TO_FLOW"]
    
    # Missing fields check
    missing = []
    if not product.get("category"): missing.append("category")
    if not product.get("product_type"): missing.append("product_type")
    if not product.get("silo"): missing.append("silo")
    if not product.get("physics_class"): missing.append("physics_class")

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
            "image_readiness_status": product.get("asset_status"),
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
            "unsafe_handling_rules": json.loads(product.get("unsafe_handling_rules") or "[]"),
            "section_5_product_physics_prompt": product.get("section_5_product_physics_prompt")
        },
        "copywriting_route": {
            "product_type": product.get("product_type"),
            "silo": product.get("silo"),
            "trigger_id": product.get("trigger_id"),
            "formula": product.get("formula"),
            "copywriting_angle": product.get("copywriting_angle"),
            "claim_risk_level": product.get("claim_risk_level")
        },
        "creative_mapping": {
            "character_recommendations": json.loads(product.get("character_recommendations") or "[]"),
            "scene_context_recommendations": json.loads(product.get("scene_context_recommendations") or "[]"),
            "camera_recommendations": json.loads(product.get("camera_recommendations") or "[]"),
            "mode_recommendations": json.loads(product.get("mode_recommendations") or "[]")
        },
        "readiness": {
            "Images": "READY" if image_ready else "BLOCKED",
            "Ingredients": "READY" if image_ready else "BLOCKED",
            "Frames": "READY" if image_ready else "BLOCKED",
            "Text to Video": "READY" if (not missing) else "NEEDS_REVIEW"
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
