import pytest
from agent.services.product_creative_brief import get_creative_brief
from agent.db import crud

@pytest.mark.asyncio
async def test_sumikko_brief_readiness():
    # Sumikko product ID from previous search
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
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
