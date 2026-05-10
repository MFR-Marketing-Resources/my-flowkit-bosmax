import pytest
from agent.services.product_creative_brief import get_creative_brief
from agent.db import crud


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
async def test_sumikko_brief_readiness():
    product_id = await _create_sumikko_product()
    brief = await get_creative_brief(product_id)
    
    assert "error" not in brief
    assert brief["product_id"] == product_id
    assert "physics_dna" in brief
    assert "copywriting_route" in brief
    assert "readiness" in brief
    
    # Sumikko should have baby care mappings
    category = brief["product_intelligence"]["category"].lower()
    assert "baby" in category or "diaper" in category
    
    # Text to Video should be READY if metadata is complete
    assert brief["readiness"]["Text to Video"] in ["READY", "READY_OR_NEEDS_REVIEW"]

@pytest.mark.asyncio
async def test_brief_missing_product():
    brief = await get_creative_brief("non-existent-id")
    assert "error" in brief
    assert brief["error"] == "Product not found"
