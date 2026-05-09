import logging
from agent.services.product_creative_brief import get_creative_brief

logger = logging.getLogger(__name__)

async def compile_9_section_prompt(product_id: str, variant_plan: dict) -> str:
    """Compile a clean 9-section video prompt for Google Flow."""
    brief = await get_creative_brief(product_id)
    if "error" in brief:
        return "Error: Product brief not found."

    physics = brief["physics_dna"]
    copy = brief["copywriting_route"]
    
    sections = [
        f"1. Biometric Anchor DNA & Temporal Persistence: Professional subject demonstration, consistent facial features, centered framing.",
        f"2. Lighting & Scene Physics: Soft studio lighting, realistic shadows, high-quality rendering, cinematic atmosphere.",
        f"3. Camera & Framing: {variant_plan.get('camera_route', 'Static shot')}. {variant_plan.get('scene_context', 'Professional environment')}.",
        f"4. Visual Action & Expansion: Dynamic interaction with the product. {variant_plan.get('hook_angle', '')}.",
        f"5. Product Physics & HOI: {physics.get('section_5_product_physics_prompt') or 'Standard product physics, realistic interaction.'}",
        f"6. Dialogue & Silo Purity: {copy.get('formula', 'Standard')} hook. Focus on {copy.get('copywriting_angle', 'product benefits')}. Trigger: {copy.get('trigger_id', 'curiosity')}.",
        f"7. Audio Sync & Tone: Clean ambient sound, upbeat background music, professional narration tone.",
        f"8. Temporal Chaining & Manifold Logic: Smooth transition between start and end states, consistent motion path.",
        f"9. Overlay & Typography: {variant_plan.get('overlay_strategy', 'Standard overlays')}. Clean typography, readable text blocks."
    ]
    
    # Return as single clean block, no metadata or tags
    return "\n\n".join(sections)
