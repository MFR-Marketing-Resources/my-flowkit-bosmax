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
    
    category = (brief["product_intelligence"]["category"] or "").lower()

    # Product-aware mappings
    category_defaults = {
        "baby": {
            "scenes": [
                "clean nursery product table",
                "parent diaper-bag packing moment",
                "soft morning baby-care shelf",
                "product pack close-up on clean changing station"
            ],
            "cameras": [
                "front pack reveal with slow push-in",
                "macro texture close-up",
                "hand-supported pack rotation",
                "top-down comparison layout"
            ]
        },
        "fashion": {
            "scenes": [
                "wardrobe mirror try-on prep",
                "hanger fabric display",
                "outdoor modest activewear motion",
                "fold-and-texture product table"
            ],
            "cameras": [
                "hanger reveal",
                "fabric close-up",
                "medium movement shot",
                "sleeve/hem texture detail"
            ]
        },
        "perfume": {
            "scenes": [
                "vanity table",
                "handbag moment",
                "clean bathroom shelf",
                "dressing table product hero"
            ],
            "cameras": [
                "bottle rotation",
                "nozzle/cap close-up",
                "label macro",
                "hand side-hold reveal"
            ]
        },
        "food": {
            "scenes": [
                "kitchen table",
                "serving plate",
                "ingredient prep surface",
                "jar/sachet product demo"
            ],
            "cameras": [
                "overhead food setup",
                "spoon dip / texture close-up",
                "label reveal",
                "pack/jar side hold"
            ]
        }
    }

    # Fallback to generic if no category match
    matched_config = next((v for k, v in category_defaults.items() if k in category), {
        "scenes": ["Modern minimalist kitchen", "Bright living room", "Professional studio"],
        "cameras": ["Close-up tracking", "Static macro shot", "Slow pan"]
    })

    hooks = [
        "Stop scrolling if you want to save time!",
        "The secret to a better lifestyle is finally here.",
        "Why everyone is talking about this product.",
        "Don't buy another one until you see this.",
        "Your search for the perfect solution ends now."
    ]
    
    contexts = brief["creative_mapping"]["scene_context_recommendations"] or matched_config["scenes"]
    cameras = brief["creative_mapping"]["camera_recommendations"] or matched_config["cameras"]
    
    for i in range(quantity):
        variant = {
            "variant_id": str(uuid.uuid4()),
            "product_id": product_id,
            "brief_id": brief["brief_id"],
            "variation_index": i + 1,
            "hook_angle": hooks[i % len(hooks)],
            "scene_context": contexts[i % len(contexts)],
            "camera_route": cameras[i % len(cameras)],
            "copywriting_formula": brief["copywriting_route"]["formula"] or "PAS",
            "overlay_strategy": f"{brief['product_intelligence']['product_short_name']} - {brief['copywriting_route']['copywriting_angle']}",
            "cta_style": "Shop Now",
            "google_flow_mode": "Frames",
            "asset_strategy": "START_END_FRAMES",
            "diversity_fingerprint": f"v{i+1}_{product_id[:8]}",
            "readiness": "READY" if brief["readiness"]["Frames"] == "READY" else "BLOCKED",
            "blocked_reason": brief["missing_fields"] if brief["readiness"]["Frames"] != "READY" else []
        }
        variations.append(variant)
        
    return variations
