import pytest
from agent.services.batch_planner import create_batch_draft
from agent.services.batch_queue import queue_batch, cancel_batch
from agent.db import crud

@pytest.mark.asyncio
async def test_queue_batch_workflow():
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
    draft = await create_batch_draft({
        "product_id": product_id,
        "quantity": 3,
        "mode": "Frames",
        "interval_min_seconds": 45,
        "interval_max_seconds": 120
    })
    batch_id = draft["batch_id"]
    
    # Get count before
    db = await crud.get_db()
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM request")
    count_before = (await cursor.fetchone())["cnt"]

    # Queue it
    res = await queue_batch(batch_id)
    assert res["ok"]
    assert res["status"] == "QUEUED"
    
    # Verify DB state
    db = await crud.get_db()
    cursor = await db.execute("SELECT status FROM batch WHERE id = ?", (batch_id,))
    assert (await cursor.fetchone())["status"] == "QUEUED"
    
    cursor = await db.execute("SELECT queue_status FROM batch_variant WHERE batch_id = ?", (batch_id,))
    variants = await cursor.fetchall()
    for v in variants:
        assert v["queue_status"] == "QUEUED"

    # Verify event message
    cursor = await db.execute("SELECT message FROM batch_queue_event WHERE batch_id = ?", (batch_id,))
    event = await cursor.fetchone()
    assert "Google Flow execution has not started" in event["message"]

    # Verify NO request records created
    cursor = await db.execute("SELECT COUNT(*) as cnt FROM request")
    row = await cursor.fetchone()
    assert row["cnt"] == count_before

@pytest.mark.asyncio
async def test_cancel_batch_workflow():
    product_id = "3bc08dc9-02b8-44d5-bdcd-086a62cbfd34"
    draft = await create_batch_draft({
        "product_id": product_id,
        "quantity": 2,
        "mode": "Frames",
        "interval_min_seconds": 45,
        "interval_max_seconds": 120
    })
    batch_id = draft["batch_id"]
    
    # Cancel it
    res = await cancel_batch(batch_id)
    assert res["ok"]
    assert res["status"] == "CANCELLED"
