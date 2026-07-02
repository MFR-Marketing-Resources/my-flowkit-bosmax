import pytest
from agent.db import crud
from agent.services.prompt_compiler_9_section import compile_9_section_prompt


async def _create_sumikko_product() -> str:
    created = await crud.create_product(
        raw_product_title="Sumikko 50PCS Premium Baby Diaper pants disposable diaper tape diaper pants pull-ups Ultra-thin and breathable All size S/M/L/XL/XXL/XXXL",
        source="FASTMOSS",
        product_display_name="Sumikko Baby Diaper pants",
        product_short_name="Sumikko Baby Diaper pants",
        image_url="https://example.com/sumikko-diaper.jpg",
        commission_rate="10%",
        price=29.9,
    )
    return created["id"]

@pytest.mark.asyncio
async def test_prompt_compiler_9_sections():
    product_id = await _create_sumikko_product()
    variant = {
        "hook_angle": "Trust-led baby care",
        "scene_context": "clean nursery product table",
        "camera_route": "front pack reveal with slow push-in",
        "overlay_strategy": "soft trust overlay"
    }
    prompt = await compile_9_section_prompt(product_id, variant)
    
    # ADR-008: the shim now delegates to THE canonical compiler — exactly the
    # nine retained canonical section headers, in order.
    from agent.services.canonical_prompt_compiler import CANONICAL_SECTIONS
    positions = [prompt.find(h) for h in CANONICAL_SECTIONS]
    assert all(pos >= 0 for pos in positions)
    assert positions == sorted(positions)
    assert "Biometric Anchor" not in prompt          # old taxonomy is dead
    assert "SECTION 9 - NO_OVERLAY" in prompt        # NO_OVERLAY law
    assert "soft trust overlay" not in prompt        # overlay strategy no longer leaks
    
    # Metadata leak check
    assert "<" not in prompt
    assert ">" not in prompt
    assert "{" not in prompt
    assert "}" not in prompt
