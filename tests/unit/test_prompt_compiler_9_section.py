import pytest
from agent.services.prompt_compiler_9_section import compile_9_section_prompt

@pytest.mark.asyncio
async def test_prompt_compiler_9_sections():
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
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
