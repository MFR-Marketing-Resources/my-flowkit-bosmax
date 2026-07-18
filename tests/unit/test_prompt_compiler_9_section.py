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


# ── SECTION 9 — NO UI elements (all-out anti-leak, owner-reported) ─────────
#
# A live output rendered a social-app interface (like/share icons, an order
# button, a template-name chip) plus engine-invented marketing copy. "No
# captions" does not stop interface graphics — SECTION 9 now bans the family
# explicitly in BOTH branches (overlay allowed and NO_OVERLAY), and the
# NO_OVERLAY branch states the gem-proven "all dialogue is AUDIO ONLY".


def _s9_of(text: str) -> str:
    idx = text.find("SECTION 9")
    return text[idx:] if idx >= 0 else text


@pytest.mark.asyncio
async def test_section9_no_overlay_bans_ui_chrome_and_states_audio_only():
    product_id = await _create_sumikko_product()
    prompt = await compile_9_section_prompt(product_id, {
        "hook_angle": "Trust-led baby care",
        "scene_context": "clean nursery product table",
        "camera_route": "front pack reveal with slow push-in",
        "overlay_strategy": "soft trust overlay",
    })
    s9 = _s9_of(prompt)
    for kw in ("NO UI elements", "like/comment/share icons", "template/preset name chips",
               "invented marketing copy", "AUDIO ONLY"):
        assert kw in s9, f"missing in SECTION 9: {kw}"
    # The all-lane product-truth locks reach the compiled video prompt too.
    assert "PRODUCT NO-MODIFICATION LOCK:" in prompt
    assert "PRODUCT SCALE ANCHOR:" in prompt
