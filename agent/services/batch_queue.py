import logging
import uuid
from typing import Any
from agent.db import crud

logger = logging.getLogger(__name__)

async def queue_batch(batch_id: str) -> dict[str, Any]:
    """
    Transition a batch and its variants into the QUEUED state.
    CRITICAL: Does NOT trigger Google Flow execution in this phase.
    """
    db = await crud.get_db()
    
    # Check batch existence and status
    cursor = await db.execute("SELECT status FROM batch WHERE id = ?", (batch_id,))
    row = await cursor.fetchone()
    if not row:
        return {"error": "Batch not found"}
    
    if row["status"] == "DRAFT_BLOCKED":
        return {"error": "Cannot queue a blocked batch. Resolve safety issues first."}
    
    if row["status"] in ["QUEUED", "PROCESSING", "COMPLETED"]:
        return {"error": f"Batch is already in {row['status']} state."}

    from agent.db.schema import _db_lock
    async with _db_lock:
        # Update Batch status
        await db.execute("UPDATE batch SET status = 'QUEUED', updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE id = ?", (batch_id,))
        
        # Update Variants status
        await db.execute("UPDATE batch_variant SET queue_status = 'QUEUED', updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE batch_id = ?", (batch_id,))
        
        # Log Event
        event_id = str(uuid.uuid4())
        await db.execute("""
            INSERT INTO batch_queue_event (event_id, batch_id, status, message, source)
            VALUES (?, ?, 'QUEUED', 'Batch queued as execution plan only. Google Flow execution has not started.', 'system')
        """, (event_id, batch_id))
        
        await db.commit()
    
    logger.info(f"Batch {batch_id} successfully queued.")
    return {"ok": True, "batch_id": batch_id, "status": "QUEUED"}

async def cancel_batch(batch_id: str) -> dict[str, Any]:
    db = await crud.get_db()
    
    # Only allow cancellation if not completed
    cursor = await db.execute("SELECT status FROM batch WHERE id = ?", (batch_id,))
    row = await cursor.fetchone()
    if not row:
        return {"error": "Batch not found"}
    
    if row["status"] == "COMPLETED":
        return {"error": "Cannot cancel a completed batch."}

    from agent.db.schema import _db_lock
    async with _db_lock:
        await db.execute("UPDATE batch SET status = 'CANCELLED', updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE id = ?", (batch_id,))
        await db.execute("UPDATE batch_variant SET queue_status = 'CANCELLED', updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) WHERE batch_id = ? AND queue_status IN ('READY', 'QUEUED')", (batch_id,))
        
        event_id = str(uuid.uuid4())
        await db.execute("""
            INSERT INTO batch_queue_event (event_id, batch_id, status, message, source)
            VALUES (?, ?, 'CANCELLED', 'Batch execution cancelled by user/system.', 'system')
        """, (event_id, batch_id))
        
        await db.commit()
    return {"ok": True, "batch_id": batch_id, "status": "CANCELLED"}
