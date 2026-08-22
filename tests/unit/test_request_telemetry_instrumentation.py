"""Cost/engine instrumentation on the durable request_telemetry ledger.

Additive, nullable columns captured on every generation outcome so the (deferred) cost
dashboard has history. These tests prove: the migration ran and is idempotent, the new
columns persist through the allowlisted upsert, the pre-existing call shape is unchanged
(new columns stay NULL), and the flow helper drops nulls / missing snapshots safely.
"""
from agent.api.flow import _telemetry_cost_kwargs
from agent.db import crud
from agent.db.schema import get_db, init_db

_NEW_COLS = (
    "provider",
    "engine",
    "model_label",
    "credits_spent",
    "estimated_credits",
    "estimated_cost",
    "actual_cost",
)

_RECONCILED_COLUMNS = (
    "workspace_generation_package_id",
    "content_build_id",
)


async def _seed_request(rid: str):
    db = await get_db()
    now = crud._now()
    # INSERT OR REPLACE so the test is robust to the (Windows-flaky) per-test DB reset;
    # the FK cascade clears any stale telemetry row.
    await db.execute(
        "INSERT OR REPLACE INTO request (id, type, status, created_at, updated_at) VALUES (?,?,?,?,?)",
        (rid, "GENERATE_VIDEO", "PENDING", now, now),
    )
    await db.commit()


async def test_migration_added_cost_columns_and_is_idempotent():
    db = await get_db()
    cur = await db.execute("PRAGMA table_info(request_telemetry)")
    cols = {row[1] for row in await cur.fetchall()}
    for c in _NEW_COLS:
        assert c in cols, f"missing instrumentation column: {c}"
    for c in _RECONCILED_COLUMNS:
        assert c in cols, f"missing request telemetry reconciliation column: {c}"
    # Re-running init_db must be a no-op (PRAGMA-guarded ALTERs), never raise.
    await init_db()


async def test_upsert_persists_instrumentation_columns():
    await _seed_request("r-instr-1")
    await crud.upsert_request_telemetry(
        "r-instr-1",
        request_type="GENERATE_VIDEO",
        status="COMPLETED",
        provider="google_flow",
        engine="omni_flash",
        model_label="Omni Flash",
        estimated_credits=15.0,
    )
    row = await crud.get_request_telemetry("r-instr-1")
    assert row["provider"] == "google_flow"
    assert row["engine"] == "omni_flash"
    assert row["model_label"] == "Omni Flash"
    assert row["estimated_credits"] == 15.0
    # Reserved monetary columns have no source yet — they stay NULL.
    assert row["estimated_cost"] is None
    assert row["actual_cost"] is None


async def test_upsert_without_instrumentation_is_unchanged():
    # Behaviour guarantee: the pre-existing call shape still succeeds and leaves every
    # new column NULL (no silent default, no failure).
    await _seed_request("r-instr-2")
    await crud.upsert_request_telemetry(
        "r-instr-2", request_type="GENERATE_VIDEO", status="QUEUED"
    )
    row = await crud.get_request_telemetry("r-instr-2")
    assert row["status"] == "QUEUED"
    for c in _NEW_COLS:
        assert row[c] is None, f"{c} should be NULL when not provided"


def test_cost_kwargs_helper_drops_nulls_and_missing():
    assert _telemetry_cost_kwargs(None) == {}
    assert _telemetry_cost_kwargs({}) == {}
    assert _telemetry_cost_kwargs({"instrumentation": {}}) == {}
    assert _telemetry_cost_kwargs(
        {"instrumentation": {"provider": "google_flow", "engine": None, "estimated_credits": 15}}
    ) == {"provider": "google_flow", "estimated_credits": 15}
