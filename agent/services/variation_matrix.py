import logging
import uuid

from agent.services.product_creative_brief import get_creative_brief
from agent.services.scene_strategy_library import (
    resolve_scene_strategy,
    select_scene_strategy_variant,
)

logger = logging.getLogger(__name__)


async def generate_variation_plan(product_id: str, quantity: int = 3) -> list:
    """Generate multiple unique video concepts for a product."""
    brief = await get_creative_brief(product_id)
    if "error" in brief:
        return []

    variations = []
    intelligence = brief["product_intelligence"]
    copy_route = brief["copywriting_route"]
    strategy = resolve_scene_strategy(
        {
            "id": product_id,
            "name": intelligence.get("product_short_name"),
            "raw_product_title": intelligence.get("raw_product_title"),
            "category": intelligence.get("category"),
            "subcategory": intelligence.get("subcategory"),
            "type": intelligence.get("type"),
            "product_type": copy_route.get("product_type"),
            "product_type_id": copy_route.get("product_type_id"),
            "silo": copy_route.get("silo"),
        }
    )
    creative_mapping = brief["creative_mapping"]
    fallback_contexts = (
        creative_mapping["scene_context_recommendations"]
        or strategy["scene_contexts"]
    )
    fallback_cameras = (
        creative_mapping["camera_recommendations"]
        or strategy["camera_routes"]
    )

    if strategy["fallback_used"] or strategy["strategy_id"] == "GENERIC_FALLBACK":
        logger.warning(
            "GENERIC_FALLBACK blocked from production variation planning for %s",
            product_id,
        )
        return []

    for i in range(quantity):
        selected = select_scene_strategy_variant(strategy, i)
        scene_context = (
            fallback_contexts[i % len(fallback_contexts)]
            if strategy["fallback_used"]
            else selected["scene_context"]
        )
        camera_route = (
            fallback_cameras[i % len(fallback_cameras)]
            if strategy["fallback_used"]
            else selected["camera_route"]
        )
        variant = {
            "variant_id": str(uuid.uuid4()),
            "product_id": product_id,
            "brief_id": brief["brief_id"],
            "variation_index": i + 1,
            "hook_angle": selected["direct_hook"],
            "scene_context": scene_context,
            "camera_route": camera_route,
            "copywriting_formula": copy_route["formula"] or "PAS",
            "overlay_strategy": selected["direct_benefit"],
            "cta_style": selected["direct_cta"],
            "google_flow_mode": "Frames",
            "asset_strategy": "START_END_FRAMES",
            "diversity_fingerprint": f"v{i+1}_{product_id[:8]}",
            "readiness": "READY" if brief["readiness"]["Frames"] == "READY" else "BLOCKED",
            "blocked_reason": brief["missing_fields"] if brief["readiness"]["Frames"] != "READY" else [],
            "scene_strategy_id": selected["scene_strategy_id"],
            "allowed_scene_strategy": selected["allowed_scene_strategy"],
            "allowed_action": selected["allowed_action"],
            "forbidden_actions": strategy["forbidden_actions"],
            "avatar_hint": selected["avatar_hint"],
            "wardrobe_hint": selected["wardrobe_hint"],
            "direct_script_slot": {
                "hook": selected["direct_hook"],
                "benefit": selected["direct_benefit"],
                "cta": selected["direct_cta"],
            },
            "sensitive_handling_rules": strategy["sensitive_handling_rules"],
        }
        variations.append(variant)

    return variations
