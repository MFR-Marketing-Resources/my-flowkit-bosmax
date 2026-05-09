import pytest
import uuid
from agent.db import crud
from agent.services import batch_executor, batch_queue, batch_planner
from agent.services.flow_client import get_flow_client

@pytest.mark.asyncio
async def test_execute_dry_run_safety_gates():
    # Setup: Create a product
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    db = await crud.get_db()
    await db.execute("INSERT INTO product (id, product_short_name, local_image_path, asset_status) VALUES (?, ?, ?, ?)", 
                     (product_id, "Test Product", "test.jpg", "READY"))
    await db.commit()
    
    # Create batch draft using planner
    batch_res = await batch_planner.create_batch_draft({
        "product_id": product_id,
        "quantity": 1,
        "mode": "Frames",
        "approval_required": True
    })
    
    if "error" in batch_res:
        # If it fails due to brief not found, we can't test planner easily without mocking
        # So we'll fallback to manual insert but with LOCK
        batch_id = str(uuid.uuid4())
        variant_id = str(uuid.uuid4())
        from agent.db.schema import _db_lock
        async with _db_lock:
            await db.execute("INSERT INTO batch (id, product_id, status, mode) VALUES (?, ?, 'DRAFT', 'Frames')", (batch_id, product_id))
            await db.execute("""
                INSERT INTO batch_variant (variant_id, batch_id, product_id, variation_index, prompt_9_section, google_flow_mode, queue_status)
                VALUES (?, ?, ?, 1, 'test prompt', 'F2V', 'READY')
            """, (variant_id, batch_id, product_id))
            await db.commit()
    else:
        batch_id = batch_res["batch_id"]

    # Ensure batch is QUEUED
    await batch_queue.queue_batch(batch_id)
    
    # Test execution safety gates with extension disconnected
    client = get_flow_client()
    client.clear_extension()
    
    res = await batch_executor.execute_next_variant(batch_id, dry_run=True)
    
    assert res["ok"] is True
    assert len(res["results"]) > 0

@pytest.mark.asyncio
async def test_execute_variant_not_found():
    res = await batch_executor.execute_variant("non-existent-id")
    assert "error" in res
