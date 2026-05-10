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
from agent.api.operator import _classify_flow_primary_blocker
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


@pytest.mark.asyncio
async def test_requeue_variant_from_failed_clears_blocked_reason_and_logs_event():
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    await db.execute(
        "UPDATE batch_variant SET queue_status='FAILED', blocked_reason='Timeout' WHERE variant_id=?",
        (variant_id,)
    )
    await db.commit()

    res = await batch_executor.requeue_variant(batch_id, variant_id)

    assert res["ok"] is True
    assert res["status"] == "QUEUED"

    cursor = await db.execute(
        "SELECT queue_status, blocked_reason FROM batch_variant WHERE variant_id=?",
        (variant_id,)
    )
    row = await cursor.fetchone()
    assert row["queue_status"] == "QUEUED"
    assert row["blocked_reason"] is None

    cursor = await db.execute(
        "SELECT status, message FROM batch_queue_event WHERE batch_id=? ORDER BY timestamp DESC LIMIT 1",
        (batch_id,)
    )
    event = await cursor.fetchone()
    assert event["status"] == "REQUEUED"
    assert event["message"] == "Variant explicitly requeued for controlled live execution."


@pytest.mark.asyncio
async def test_requeue_variant_rejects_when_another_variant_is_running():
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)

    batch_id = str(uuid.uuid4())
    target_variant_id = str(uuid.uuid4())
    running_variant_id = str(uuid.uuid4())

    await db.execute(
        "INSERT INTO batch (id, product_id, status, mode, interval_min_seconds, interval_max_seconds) VALUES (?, ?, 'QUEUED', 'Frames', 45, 120)",
        (batch_id, product_id),
    )
    await db.execute(
        """INSERT INTO batch_variant
               (variant_id, batch_id, product_id, variation_index, prompt_9_section, google_flow_mode, queue_status, blocked_reason)
           VALUES (?, ?, ?, 1, 'Prompt', 'F2V', 'FAILED', 'Timeout')""",
        (target_variant_id, batch_id, product_id),
    )
    await db.execute(
        """INSERT INTO batch_variant
               (variant_id, batch_id, product_id, variation_index, prompt_9_section, google_flow_mode, queue_status)
           VALUES (?, ?, ?, 2, 'Prompt', 'F2V', 'RUNNING')""",
        (running_variant_id, batch_id, product_id),
    )
    await db.commit()

    res = await batch_executor.requeue_variant(batch_id, target_variant_id)

    assert "error" in res
    assert "ABORT_CONCURRENT_VARIANT" in res["error"]


@pytest.mark.asyncio
async def test_live_eligibility_reports_ready_when_composer_and_smoke_pass():
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    client = get_flow_client()
    client.set_extension(MagicMock())

    with patch.object(client, "get_status", new_callable=AsyncMock) as mock_status, \
         patch.object(client, "check_flow_composer_ready", new_callable=AsyncMock) as mock_ready, \
         patch.object(client, "smoke_execute_flow_job", new_callable=AsyncMock) as mock_smoke:
        mock_status.return_value = {"state": "idle", "flowKeyPresent": True}
        mock_ready.return_value = {
            "ok": True,
            "flow_tab_found": True,
            "flow_url": "https://labs.google/fx/tools/flow/project",
            "signed_in_likely": True,
            "composer_found": True,
            "composer_editable": True,
            "generate_button_found": True,
            "current_mode_visible": "Video/Frames",
            "blocking_modal_detected": False,
        }
        mock_smoke.return_value = {
            "ok": True,
            "status": "PASS",
            "round_trip_ms": 321,
            "no_generation_triggered": True,
        }

        res = await batch_executor.get_live_eligibility(
            batch_id,
            variant_id=variant_id,
            expected_product_id=product_id,
        )

    assert res["selected_variant_id"] == variant_id
    assert res["eligible_queued_variant_count"] == 1
    assert res["target_variant_status"] == "QUEUED"
    assert res["has_prompt"] is True
    assert res["product_id"] == product_id
    assert res["product_id_match_expected"] is True
    assert res["extension_connected"] is True
    assert res["extension_state"] == "idle"
    assert res["flow_composer_ready"] is True
    assert res["execute_flow_job_smoke_status"] == "PASS"
    assert res["blocked_reason"] == []

    client.clear_extension()


@pytest.mark.asyncio
async def test_smoke_execute_flow_job_returns_composer_failure_without_generation():
    db = await crud.get_db()
    product_id = "test_prod_" + str(uuid.uuid4())[:8]
    await _seed_product(db, product_id)
    batch_id, variant_id = await _seed_queued_batch(db, product_id)

    client = get_flow_client()
    client.set_extension(MagicMock())

    with patch.object(client, "get_status", new_callable=AsyncMock) as mock_status, \
         patch.object(client, "check_flow_composer_ready", new_callable=AsyncMock) as mock_ready:
        mock_status.return_value = {"state": "idle", "flowKeyPresent": True}
        mock_ready.return_value = {"ok": False, "error": "ABORT_FLOW_COMPOSER_NOT_READY"}

        res = await batch_executor.smoke_execute_flow_job(batch_id, variant_id)

    assert res["ok"] is False
    assert res["status"] == "FAIL_COMPOSER_NOT_READY"
    assert res["error"] == "ABORT_FLOW_COMPOSER_NOT_READY"

    client.clear_extension()


def test_flow_primary_blocker_classifies_content_script_timeout():
    blocker = _classify_flow_primary_blocker(
        True,
        {
            "flow_tab_found": True,
            "flow_url": "https://labs.google/fx/tools/flow/project/123",
            "signed_in_likely": True,
            "composer_found": False,
            "composer_editable": False,
            "generate_button_found": False,
            "detail": "ERR_MESSAGE_RESPONSE_TIMEOUT",
        },
        None,
    )

    assert blocker == "CONTENT_SCRIPT_STALE_OR_NOT_INJECTED"
