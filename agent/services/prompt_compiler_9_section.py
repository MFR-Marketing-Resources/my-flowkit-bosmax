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
        f"1. Biometric Anchor DNA & Temporal Persistence: Professional subject demonstration, consistent facial features, centered framing. Focus on high-retention visual stability.",
        f"2. Lighting & Scene Physics: Soft studio lighting, realistic shadows, high-quality rendering, cinematic atmosphere. Volumetric lighting and natural color grading.",
        f"3. Camera & Framing: {variant_plan.get('camera_route', 'Static shot')}. Perspective: {variant_plan.get('scene_context', 'Professional environment')}.",
        f"4. Visual Action & Expansion: {variant_plan.get('hook_angle', 'Product reveal action')}. The subject interacts naturally within the {variant_plan.get('scene_context', 'scene')}, highlighting the product's primary use case.",
        f"5. Product Physics & HOI: {physics.get('section_5_product_physics_prompt') or 'Standard product physics, realistic interaction.'}",
        f"6. Dialogue & Silo Purity: {copy.get('formula', 'Standard')} hook style. Focus: {copy.get('copywriting_angle', 'product benefits')}. Trigger: {copy.get('trigger_id', 'curiosity')}. Claim boundaries: {brief.get('claim_boundaries', {}).get('risk_level', 'LOW')} risk.",
        f"7. Audio Sync & Tone: Clean ambient sound, upbeat background music, professional narration tone. Synchronized visemes for talking head segments if applicable.",
        f"8. Temporal Chaining & Manifold Logic: Smooth transition between start and end states, consistent motion path. No temporal artifacts or flickering.",
        f"9. Overlay & Typography: {variant_plan.get('overlay_strategy', 'Standard overlays')}. Branding: {brief['product_intelligence'].get('product_short_name', 'BOSMAX')}. Clean typography, readable text blocks, optimized for mobile viewing."
    ]
    
    # Return as single clean block, no metadata or tags
    return "\n\n".join(sections)
