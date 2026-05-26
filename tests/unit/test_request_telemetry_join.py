import pytest

from agent.db import crud
from agent.db.schema import get_db


@pytest.mark.asyncio
async def test_terminal_resume_failure_overrides_waiting_request_snapshot():
    db = await get_db()
    request_id = "navigation_resume_timeout_001"
    now = crud._now()

    async with crud._db_lock:
        await db.execute(
            """
            INSERT INTO request (id, type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (request_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now),
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        request_id,
        request_type="MANUAL_FLOW_JOB",
        status="FAILED",
        extension_stage="FAILED",
        error_code="ERR_FLOW_NAVIGATION_RESUME_TIMEOUT",
        error_message="ERR_FLOW_NAVIGATION_RESUME_TIMEOUT - editor URL did not load",
        failed_at=now,
    )

    rows = await crud.list_requests(project_id=None, limit=20)
    request = next(row for row in rows if row["id"] == request_id)

    assert request["status"] == "FAILED"
    assert request["error_message"].startswith("ERR_FLOW_NAVIGATION_RESUME_TIMEOUT")
