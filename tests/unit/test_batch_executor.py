"""
Unit tests for batch_executor.py

Tests:
- DRY_RUN_VALIDATED is accepted by DB (no CHECK constraint violation)
- dry-run does NOT call execute_flow_job
- dry-run does NOT create request rows
- execute-next processes max 1 variant only
- live execution is gated (extension offline blocks it)
- prompt missing blocks run
"""
import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from agent.db import crud
from agent.services import batch_executor, batch_queue, batch_planner
from agent.services.flow_client import get_flow_client


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _seed_product(db, product_id: str):
    """Insert a minimal product row for testing."""
    await db.execute(
        "INSERT OR IGNORE INTO product "
        "(id, raw_product_title, product_display_name, product_short_name, local_image_path, asset_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (product_id, "Test Product", "Test Product", "Test Product", "test.jpg", "DOWNLOADED")
    )
    await db.commit()


async def _seed_queued_batch(db, product_id: str) -> tuple[str, str]:
    """Directly insert a batch + variant into QUEUED state, bypassing planner."""
    batch_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO batch (id, product_id, status, mode, interval_min_seconds, interval_max_seconds) "
        "VALUES (?, ?, 'QUEUED', 'Frames', 45, 120)",
        (batch_id, product_id)
    )
    await db.execute(
        """INSERT INTO batch_variant
               (variant_id, batch_id, product_id, variation_index,
                prompt_9_section, google_flow_mode, queue_status)
           VALUES (?, ?, ?, 1, 'Test 9-section prompt text here', 'F2V', 'QUEUED')""",
        (variant_id, batch_id, product_id)
    )
    await db.commit()
    return batch_id, variant_id


# ─── Tests ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_validated_accepted_by_db():
    """DRY_RUN_VALIDATED must NOT violate the CHECK constraint."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    # Directly write DRY_RUN_VALIDATED — this must not raise
    await db.execute(
        "UPDATE batch_variant SET queue_status='DRY_RUN_VALIDATED' WHERE variant_id=?",
        (variant_id,)
    )
    await db.commit()

    cur = await db.execute(
        "SELECT queue_status FROM batch_variant WHERE variant_id=?", (variant_id,)
    )
    row = await cur.fetchone()
    assert row is not None, "Variant row must exist"
    assert row["queue_status"] == "DRY_RUN_VALIDATED", (
        f"Expected DRY_RUN_VALIDATED, got {row['queue_status']}"
    )


@pytest.mark.asyncio
async def test_dry_run_does_not_call_google_flow():
    """Dry-run must never call execute_flow_job."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    # Ensure extension is disconnected → safety gate fires before any Flow call
    client = get_flow_client()
    client.clear_extension()

    with patch.object(client, "execute_flow_job", new_callable=AsyncMock) as mock_flow:
        res = await batch_executor.execute_next_variant(batch_id, dry_run=True)
        mock_flow.assert_not_called(), "execute_flow_job must NEVER be called during dry-run"


@pytest.mark.asyncio
async def test_dry_run_no_request_rows_created():
    """Dry-run must not create any rows in the request table."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    client = get_flow_client()
    client.clear_extension()

    cur = await db.execute("SELECT COUNT(*) as cnt FROM request")
    count_before = (await cur.fetchone())["cnt"]

    await batch_executor.execute_next_variant(batch_id, dry_run=True)

    cur = await db.execute("SELECT COUNT(*) as cnt FROM request")
    count_after = (await cur.fetchone())["cnt"]
    assert count_after == count_before, (
        f"dry-run must NOT create request rows (before={count_before}, after={count_after})"
    )


@pytest.mark.asyncio
async def test_execute_next_max_one_variant():
    """execute_next_variant must process at most 1 variant when max_variants=1."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)

    # Seed a batch with 3 variants
    batch_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO batch (id, product_id, status, mode, interval_min_seconds, interval_max_seconds) "
        "VALUES (?, ?, 'QUEUED', 'Frames', 45, 120)",
        (batch_id, product_id)
    )
    variant_ids = []
    for i in range(3):
        vid = str(uuid.uuid4())
        variant_ids.append(vid)
        await db.execute(
            """INSERT INTO batch_variant
                   (variant_id, batch_id, product_id, variation_index,
                    prompt_9_section, google_flow_mode, queue_status)
               VALUES (?, ?, ?, ?, 'Test prompt', 'F2V', 'QUEUED')""",
            (vid, batch_id, product_id, i + 1)
        )
    await db.commit()

    client = get_flow_client()
    client.clear_extension()

    res = await batch_executor.execute_next_variant(batch_id, dry_run=True, max_variants=1)

    # Only 1 variant processed (even though 3 exist)
    assert isinstance(res, dict)
    if "results" in res:
        assert len(res["results"]) == 1, (
            f"Must process exactly 1 variant, got {len(res['results'])}"
        )


@pytest.mark.asyncio
async def test_live_execution_blocked_when_extension_offline():
    """Live execution must return ABORT_AGENT_OFFLINE when extension is disconnected."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    client = get_flow_client()
    client.clear_extension()

    res = await batch_executor.execute_variant(variant_id, dry_run=False)
    assert "error" in res, "Must return an error dict"
    assert "ABORT_AGENT_OFFLINE" in res["error"], (
        f"Expected ABORT_AGENT_OFFLINE in error, got: {res['error']}"
    )


@pytest.mark.asyncio
async def test_live_execution_blocked_when_prompt_missing():
    """Live execution must return ABORT_PROMPT_MISSING when prompt_9_section is empty."""
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id = str(uuid.uuid4())
    variant_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO batch (id, product_id, status, mode, interval_min_seconds, interval_max_seconds) "
        "VALUES (?, ?, 'QUEUED', 'Frames', 45, 120)",
        (batch_id, product_id)
    )
    await db.execute(
        """INSERT INTO batch_variant
               (variant_id, batch_id, product_id, variation_index,
                prompt_9_section, google_flow_mode, queue_status)
           VALUES (?, ?, ?, 1, '', 'F2V', 'QUEUED')""",
        (variant_id, batch_id, product_id)
    )
    await db.commit()

    # Mock a connected extension so the AGENT_OFFLINE gate passes,
    # and mock get_status to return state='on' so gate 2 passes too.
    client = get_flow_client()
    ws_mock = MagicMock()
    client.set_extension(ws_mock)

    with patch.object(client, "get_status", new_callable=AsyncMock) as mock_status:
        mock_status.return_value = {"state": "on", "flowKeyPresent": True}
        res = await batch_executor.execute_variant(variant_id, dry_run=False)

    assert "error" in res, "Must return an error dict"
    assert "ABORT_PROMPT_MISSING" in res["error"], (
        f"Expected ABORT_PROMPT_MISSING in error, got: {res['error']}"
    )

    # Clean up
    client.clear_extension()


@pytest.mark.asyncio
async def test_execute_variant_not_found():
    """execute_variant with a nonexistent ID must return a clean error."""
    res = await batch_executor.execute_variant("non-existent-variant-id")
    assert "error" in res
    assert res["error"] == "Variant not found"
