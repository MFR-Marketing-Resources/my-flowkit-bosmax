import pytest
from agent.services.batch_planner import create_batch_draft, get_batch_detail

@pytest.mark.asyncio
async def test_create_batch_draft_sumikko():
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
    data = {
        "product_id": product_id,
        "quantity": 5,
        "platform": "TikTok",
        "mode": "Frames",
        "approval_required": True,
        "interval_min_seconds": 45,
        "interval_max_seconds": 120
    }
    res = await create_batch_draft(data)
    
    assert "batch_id" in res
    assert res["status"] == "DRAFT"
    assert len(res["variants"]) == 5
    assert res["variant_count"] == 5
    
    # Check one variant
    v = res["variants"][0]
    assert v["batch_id"] == res["batch_id"]
    assert v["variation_index"] == 1
    assert "prompt_9_section" in v
    assert len(v["prompt_9_section"]) > 100
    from agent.db.schema import close_db
    await close_db()

@pytest.mark.asyncio
async def test_batch_draft_blocked_on_safety():
    # Quantity > 20
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
    data = {
        "product_id": product_id,
        "quantity": 25,
        "mode": "Frames"
    }
    res = await create_batch_draft(data)
    assert res["status"] == "DRAFT_BLOCKED"
    assert not res["safety"]["is_safe"]
