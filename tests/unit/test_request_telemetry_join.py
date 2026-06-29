import pytest
import json
from agent.db import crud
from agent.db.schema import get_db

@pytest.mark.asyncio
async def test_no_telemetry_returns_base_request_status():
    db = await get_db()
    req_id = "test_no_telemetry"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    retrieved = await crud.get_request(req_id)
    assert retrieved is not None
    assert retrieved["status"] == "WAITING_FLOW"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "WAITING_FLOW"


@pytest.mark.asyncio
async def test_telemetry_status_waiting_flow_with_extension_stage_error_returns_failed():
    db = await get_db()
    req_id = "test_ext_error"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        extension_stage="ERROR",
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "FAILED"


@pytest.mark.asyncio
async def test_telemetry_status_waiting_flow_with_google_flow_stage_error_returns_failed():
    db = await get_db()
    req_id = "test_flow_error"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        google_flow_stage="ERROR",
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "FAILED"


@pytest.mark.asyncio
async def test_telemetry_queued_at_only_returns_queued():
    db = await get_db()
    req_id = "test_queued_only"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        queued_at=now,
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "QUEUED"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_telemetry_started_at_returns_processing():
    db = await get_db()
    req_id = "test_started"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        queued_at=now,
        started_at=now,
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "PROCESSING"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "PROCESSING"


@pytest.mark.asyncio
async def test_telemetry_completed_at_returns_completed():
    db = await get_db()
    req_id = "test_completed"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        queued_at=now,
        started_at=now,
        completed_at=now,
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "COMPLETED"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_error_message_or_code_overrides_base_null_error():
    db = await get_db()
    req_id = "test_error_override"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, error_message, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", None, now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        error_message="ERR_CONTENT_SCRIPT_STALE",
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    assert retrieved["error_message"] == "ERR_CONTENT_SCRIPT_STALE"
    
    listed = await crud.list_requests(limit=10)
    req = next(r for r in listed if r["id"] == req_id)
    assert req["status"] == "FAILED"
    assert req["error_message"] == "ERR_CONTENT_SCRIPT_STALE"


@pytest.mark.asyncio
async def test_error_stage_with_null_error_fields_returns_synthesized_error_message():
    db = await get_db()
    req_id = "test_null_error_synthesized"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        google_flow_stage="ERROR",
        extension_stage="ERROR",
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    assert "Flow automation failed: google_flow_stage=ERROR, extension_stage=ERROR" in retrieved["error_message"]


@pytest.mark.asyncio
async def test_error_stage_with_real_telemetry_error_preserves_real_error_message():
    db = await get_db()
    req_id = "test_real_error_preserved"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="FAILED",
        google_flow_stage="ERROR",
        extension_stage="ERROR",
        error_message="ERR_WRONG_MODE_IMAGE_SELECTED"
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    assert retrieved["error_message"] == "ERR_WRONG_MODE_IMAGE_SELECTED"


@pytest.mark.asyncio
async def test_error_stage_extracts_error_from_request_lineage_payload():
    db = await get_db()
    req_id = "test_error_from_lineage"
    now = crud._now()
    
    async with crud._db_lock:
        await db.execute(
            """INSERT INTO request (id, type, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (req_id, "MANUAL_FLOW_JOB", "WAITING_FLOW", now, now)
        )
        await db.commit()

    lineage = {"error_message": "ERR_COMPILER_FAILED_TO_RESOLVE"}
    await crud.upsert_request_telemetry(
        req_id,
        request_type="MANUAL_FLOW_JOB",
        status="WAITING_FLOW",
        google_flow_stage="ERROR",
        extension_stage="ERROR",
        request_lineage_payload=json.dumps(lineage)
    )

    retrieved = await crud.get_request(req_id)
    assert retrieved["status"] == "FAILED"
    assert retrieved["error_message"] == "ERR_COMPILER_FAILED_TO_RESOLVE"
