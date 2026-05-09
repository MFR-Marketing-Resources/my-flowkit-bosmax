import logging
import uuid
from agent.services.product_creative_brief import get_creative_brief

logger = logging.getLogger(__name__)

async def generate_variation_plan(product_id: str, quantity: int = 3) -> list:
    """Generate multiple unique video concepts for a product."""
    brief = await get_creative_brief(product_id)
    if "error" in brief:
        return []

    variations = []
    
    # Mocking variation logic
    hooks = [
        "Stop scrolling if you want to save time!",
        "The secret to a better lifestyle is finally here.",
        "Why everyone is talking about this product.",
        "Don't buy another one until you see this.",
        "Your search for the perfect solution ends now."
    ]
    
    contexts = brief["creative_mapping"]["scene_context_recommendations"] or ["Modern minimalist kitchen", "Bright living room", "Professional studio"]
    cameras = brief["creative_mapping"]["camera_recommendations"] or ["Close-up tracking", "Static macro shot", "Slow pan"]
    
    for i in range(min(quantity, len(hooks))):
        variant = {
            "variant_id": str(uuid.uuid4()),
            "product_id": product_id,
            "brief_id": brief["brief_id"],
            "variation_index": i + 1,
            "hook_angle": hooks[i],
            "scene_context": contexts[i % len(contexts)],
            "camera_route": cameras[i % len(cameras)],
            "copywriting_formula": brief["copywriting_route"]["formula"] or "PAS",
            "overlay_strategy": "Minimal text overlays",
            "cta_style": "Shop Now",
            "google_flow_mode": "Frames",
            "asset_strategy": "START_END_FRAMES",
            "diversity_fingerprint": f"v{i+1}_{product_id[:8]}",
            "readiness": "READY" if brief["readiness"]["Frames"] == "READY" else "BLOCKED",
            "blocked_reason": brief["missing_fields"] if brief["readiness"]["Frames"] != "READY" else []
        }
        variations.append(variant)
        
    return variations
