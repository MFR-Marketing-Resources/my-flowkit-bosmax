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
    
    # Check for exactly 9 sections
    lines = [l.strip() for l in prompt.split("\n") if l.strip()]
    sections = [l for l in lines if any(l.startswith(f"{i}.") for i in range(1, 10))]
    assert len(sections) == 9
    
    # Check content
    assert "Physics DNA" in prompt # Section 5
    assert "hook style" in prompt # Section 6
    assert "soft trust overlay" in prompt # Section 9
    
    # Metadata leak check
    assert "<" not in prompt
    assert ">" not in prompt
    assert "{" not in prompt
    assert "}" not in prompt
