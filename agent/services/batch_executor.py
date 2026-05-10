import logging
import uuid
from typing import Any, Optional
from datetime import datetime, timezone
from agent.db import crud
from agent.services.flow_client import get_flow_client
from agent.services.scheduler_safety import validate_batch_safety

logger = logging.getLogger(__name__)

ALLOWED_REQUEUE_STATUSES = {"FAILED", "DRY_RUN_VALIDATED", "RETRY_PENDING"}
ACTIVE_VARIANT_STATUSES = (
    "WAITING_INTERVAL",
    "RUNNING",
    "FLOW_MODE_VERIFIED",
    "PROMPT_INSERTED",
    "GENERATION_STARTED",
)
ALLOWED_FLOW_STATES = {"on", "idle", "running"}
FLOW_MODE_MAP = {
    "Frames": "F2V",
    "Ingredients": "I2V",
    "Images": "IMG",
    "Text to Video": "T2V",
    "F2V": "F2V",
    "I2V": "I2V",
    "IMG": "IMG",
    "T2V": "T2V",
}

async def execute_next_variant(batch_id: str, dry_run: bool = True, max_variants: int = 1) -> dict[str, Any]:
    """
    Find the next QUEUED variant in a batch and execute it.
    """
    db = await crud.get_db()
    
    # Check if batch is QUEUED
    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,))
    batch = await cursor.fetchone()
    if not batch:
        return {"error": "Batch not found"}
    
    if batch["status"] != "QUEUED":
        return {"error": f"Batch status is {batch['status']}, must be QUEUED to execute."}

    # Find next variant
    cursor = await db.execute("""
        SELECT * FROM batch_variant 
        WHERE batch_id = ? AND queue_status = 'QUEUED'
        ORDER BY variation_index ASC
        LIMIT ?
    """, (batch_id, max_variants))
    variants = await cursor.fetchall()
    
    if not variants:
        return {"ok": True, "message": "No QUEUED variants remaining in this batch."}

    results = []
    for variant in variants:
        res = await execute_variant(variant["variant_id"], dry_run=dry_run)
        results.append(res)
        if not res.get("ok"):
            break # Stop if one fails safety gates
            
    return {
        "ok": True,
        "batch_id": batch_id,
        "results": results
    }


async def requeue_variant(batch_id: str, variant_id: str) -> dict[str, Any]:
    """Explicitly requeue one variant for a controlled live execution."""
    db = await crud.get_db()

    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,))
    batch = await cursor.fetchone()
    if not batch:
        return {"error": "Batch not found"}

    cursor = await db.execute(
        "SELECT * FROM batch_variant WHERE batch_id = ? AND variant_id = ?",
        (batch_id, variant_id),
    )
    variant = await cursor.fetchone()
    if not variant:
        return {"error": "Variant not found"}

    if variant["queue_status"] not in ALLOWED_REQUEUE_STATUSES:
        return {
            "error": (
                f"Variant {variant_id} status is {variant['queue_status']}, must be one of "
                f"{', '.join(sorted(ALLOWED_REQUEUE_STATUSES))}."
            )
        }

    cursor = await db.execute(
        f"""
        SELECT COUNT(*) as cnt FROM batch_variant
        WHERE batch_id = ? AND variant_id != ?
          AND queue_status IN ({','.join(['?'] * len(ACTIVE_VARIANT_STATUSES))})
        """,
        (batch_id, variant_id, *ACTIVE_VARIANT_STATUSES),
    )
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        return {"error": "ABORT_CONCURRENT_VARIANT: Another variant is already being processed for this batch."}

    from agent.db.schema import _db_lock

    async with _db_lock:
        await db.execute(
            """
            UPDATE batch_variant
            SET queue_status = 'QUEUED', blocked_reason = NULL,
                updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            WHERE variant_id = ?
            """,
            (variant_id,),
        )
        await _log_event(
            batch_id,
            variant_id,
            "REQUEUED",
            "Variant explicitly requeued for controlled live execution.",
        )
        await db.commit()

    return {"ok": True, "batch_id": batch_id, "variant_id": variant_id, "status": "QUEUED"}


async def get_live_eligibility(
    batch_id: str,
    variant_id: Optional[str] = None,
    expected_product_id: Optional[str] = None,
) -> dict[str, Any]:
    """Report whether a batch is eligible for one controlled live execution."""
    db = await crud.get_db()

    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,))
    batch = await cursor.fetchone()
    if not batch:
        return {"error": "Batch not found"}

    if variant_id:
        cursor = await db.execute(
            "SELECT * FROM batch_variant WHERE batch_id = ? AND variant_id = ?",
            (batch_id, variant_id),
        )
    else:
        cursor = await db.execute(
            """
            SELECT * FROM batch_variant
            WHERE batch_id = ?
            ORDER BY CASE WHEN queue_status = 'QUEUED' THEN 0 ELSE 1 END, variation_index ASC
            LIMIT 1
            """,
            (batch_id,),
        )
    variant = await cursor.fetchone()

    return await _assess_live_eligibility(
        batch,
        variant,
        expected_product_id=expected_product_id,
        include_smoke=True,
    )


async def smoke_execute_flow_job(batch_id: str, variant_id: str) -> dict[str, Any]:
    """Run a lightweight EXECUTE_FLOW_JOB smoke test without generating output."""
    db = await crud.get_db()

    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (batch_id,))
    batch = await cursor.fetchone()
    if not batch:
        return {"error": "Batch not found"}

    cursor = await db.execute(
        "SELECT * FROM batch_variant WHERE batch_id = ? AND variant_id = ?",
        (batch_id, variant_id),
    )
    variant = await cursor.fetchone()
    if not variant:
        return {"error": "Variant not found"}

    client = get_flow_client()
    if not client.connected:
        return {
            "ok": False,
            "status": "FAIL_ERROR",
            "error": "ABORT_AGENT_OFFLINE: Chrome extension not connected.",
        }

    status = await client.get_status()
    if status.get("state") not in ALLOWED_FLOW_STATES:
        return {
            "ok": False,
            "status": "FAIL_ERROR",
            "error": f"ABORT_FLOW_TAB_MISSING: Google Flow tab is not active or ready (state: {status.get('state')}).",
        }

    flow_mode = _resolve_flow_mode(variant["google_flow_mode"] or batch["mode"])
    composer = await client.check_flow_composer_ready(flow_mode)
    if not composer.get("ok"):
        return {
            "ok": False,
            "status": "FAIL_COMPOSER_NOT_READY",
            "error": composer.get("error") or "ABORT_FLOW_COMPOSER_NOT_READY",
            "composer": composer,
        }

    smoke = await client.smoke_execute_flow_job(_build_flow_job(variant, batch["mode"], smoke_test=True))
    smoke.setdefault("composer", composer)
    return smoke

async def execute_variant(variant_id: str, dry_run: bool = True) -> dict[str, Any]:
    """
    Execute a specific variant from the queue.
    """
    db = await crud.get_db()
    
    # Load variant
    cursor = await db.execute("SELECT * FROM batch_variant WHERE variant_id = ?", (variant_id,))
    variant = await cursor.fetchone()
    if not variant:
        return {"error": "Variant not found"}
    
    if variant["queue_status"] != "QUEUED":
        return {"error": f"Variant {variant_id} status is {variant['queue_status']}, must be QUEUED."}

    from agent.db.schema import _db_lock
    async with _db_lock:
        # 1. Safety Gates
        gates_res = await _check_execution_safety(variant, dry_run)
        if not gates_res["ok"]:
            # Update variant with blocked reason
            await db.execute("""
                UPDATE batch_variant 
                SET blocked_reason = ?, updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                WHERE variant_id = ?
            """, (gates_res["error"], variant_id))
            await _log_event(variant["batch_id"], variant_id, "DRAFT_BLOCKED", gates_res["error"])
            await db.commit()
            return gates_res

    # 2. Execution Logic
    if dry_run:
        from agent.db.schema import _db_lock
        async with _db_lock:
            await db.execute("""
                UPDATE batch_variant 
                SET queue_status = 'DRY_RUN_VALIDATED', updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                WHERE variant_id = ?
            """, (variant_id,))
            await _log_event(variant["batch_id"], variant_id, "DRY_RUN_VALIDATED", "Dry run safety gates passed. No Google Flow call made.")
            await db.commit()
        return {"ok": True, "variant_id": variant_id, "status": "DRY_RUN_VALIDATED"}

    # Live Run - State Transitions
    return await _run_live_execution(variant)

async def _check_execution_safety(variant: dict, dry_run: bool) -> dict[str, Any]:
    db = await crud.get_db()
    client = get_flow_client()
    
    # Gate: Local Agent / Extension
    if not client.connected:
        return {"ok": False, "error": "ABORT_AGENT_OFFLINE: Chrome extension not connected."}
    
    # Gate: Flow Tab Available
    status = await client.get_status()
    if status.get("state") not in ["on", "idle", "running"]:
        return {"ok": False, "error": f"ABORT_FLOW_TAB_MISSING: Google Flow tab is not active or ready (state: {status.get('state')})."}

    # Gate: Prompt Existence
    if not variant["prompt_9_section"]:
        return {"ok": False, "error": "ABORT_PROMPT_MISSING: 9-Section prompt has not been compiled."}

    # Gate: Flow Mode
    mode = variant["google_flow_mode"]
    if not mode:
        return {"ok": False, "error": "ABORT_MODE_MISSING: Google Flow execution mode not specified."}

    # Gate: Product Image Readiness
    cursor = await db.execute("SELECT * FROM batch WHERE id = ?", (variant["batch_id"],))
    batch = await cursor.fetchone()
    from agent.services.product_creative_brief import get_creative_brief
    brief = await get_creative_brief(variant["product_id"])
    if "error" in brief:
        return {"ok": False, "error": f"ABORT_BRIEF_INVALID: {brief.get('error')}"}
    
    mode_readiness = brief.get("readiness", {}).get(batch["mode"], "PENDING")
    if mode_readiness != "READY":
         return {"ok": False, "error": f"ABORT_MODE_READINESS_FAIL: Product image status is {mode_readiness} for mode {batch['mode']}."}

    # Gate: No other variant running for same batch
    cursor = await db.execute("""
        SELECT COUNT(*) as cnt FROM batch_variant 
        WHERE batch_id = ? AND queue_status IN ('WAITING_INTERVAL', 'RUNNING', 'FLOW_MODE_VERIFIED', 'PROMPT_INSERTED', 'GENERATION_STARTED')
    """, (variant["batch_id"],))
    row = await cursor.fetchone()
    if row["cnt"] > 0:
        return {"ok": False, "error": "ABORT_CONCURRENT_VARIANT: Another variant is already being processed for this batch."}

    if not dry_run:
        eligibility = await _assess_live_eligibility(batch, variant, include_smoke=True)
        if eligibility["blocked_reason"]:
            return {"ok": False, "error": eligibility["blocked_reason"][0], "eligibility": eligibility}

    # Gate: Interval Safety (Only for Live)
    if not dry_run:
        cursor = await db.execute("""
            SELECT updated_at FROM batch_variant 
            WHERE batch_id = ? AND queue_status IN ('GENERATED', 'DOWNLOADED', 'QA_PASSED', 'FAILED')
            ORDER BY updated_at DESC LIMIT 1
        """, (variant["batch_id"],))
        last_run = await cursor.fetchone()
        if last_run:
            try:
                last_time = datetime.strptime(last_run["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
                interval_min = batch["interval_min_seconds"] or 30
                if elapsed < interval_min:
                    return {"ok": False, "error": f"ABORT_INTERVAL_SAFETY: Cooldown active. {int(interval_min - elapsed)}s remaining."}
            except Exception:
                pass

    return {"ok": True}

async def _run_live_execution(variant: dict) -> dict[str, Any]:
    db = await crud.get_db()
    client = get_flow_client()
    batch_id = variant["batch_id"]
    variant_id = variant["variant_id"]
    
    # 1. WAITING_INTERVAL
    await _update_variant_status(variant_id, "WAITING_INTERVAL")
    await _log_event(batch_id, variant_id, "WAITING_INTERVAL", "Preparing for execution...")
    
    # 2. RUNNING
    await _update_variant_status(variant_id, "RUNNING")
    await _log_event(batch_id, variant_id, "RUNNING", "Sending job to Google Flow automation worker.")

    # Determine mode for automation job
    cursor = await db.execute("SELECT mode FROM batch WHERE id = ?", (batch_id,))
    batch_mode = (await cursor.fetchone())["mode"]
    job = _build_flow_job(variant, batch_mode)
    
    report = await client.execute_flow_job(job)
    if report.get("error"):
        error_msg = report["error"]
        await _update_variant_status(variant_id, "FAILED", blocked_reason=error_msg)
        await _log_event(batch_id, variant_id, "FAILED", f"Automation failed: {error_msg}")
        return {"ok": False, "error": error_msg}

    # 4. State updates based on automation report
    # The extension should report stages: MODE_VERIFIED, PROMPT_INSERTED, GENERATION_STARTED
    stages = report.get("result", {}).get("stages", [])
    
    # We'll walk through the stages and log them
    current_status = "RUNNING"
    if "MODE_VERIFIED" in stages:
        current_status = "FLOW_MODE_VERIFIED"
        await _update_variant_status(variant_id, current_status)
        await _log_event(batch_id, variant_id, current_status, "Google Flow UI mode verified correctly.")

    if "PROMPT_INSERTED" in stages:
        current_status = "PROMPT_INSERTED"
        await _update_variant_status(variant_id, current_status)
        await _log_event(batch_id, variant_id, current_status, "9-Section prompt inserted and editable.")

    if "GENERATION_STARTED" in stages:
        current_status = "GENERATION_STARTED"
        await _update_variant_status(variant_id, current_status)
        await _log_event(batch_id, variant_id, current_status, "Generate button clicked. Monitoring for output.")

    await db.commit()
    return {"ok": True, "variant_id": variant_id, "status": current_status, "report": report}

async def _update_variant_status(variant_id: str, status: str, blocked_reason: str = None):
    db = await crud.get_db()
    from agent.db.schema import _db_lock
    async with _db_lock:
        await db.execute("""
            UPDATE batch_variant 
            SET queue_status = ?, blocked_reason = ?, updated_at = (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
            WHERE variant_id = ?
        """, (status, blocked_reason, variant_id))
        await db.commit()


def _resolve_flow_mode(mode_value: Optional[str]) -> str:
    return FLOW_MODE_MAP.get(mode_value or "", "F2V")


def _build_flow_job(variant: dict, batch_mode: str, smoke_test: bool = False) -> dict[str, Any]:
    return {
        "variant_id": variant["variant_id"],
        "request_id": f"{'smoke' if smoke_test else 'live'}-{variant['variant_id']}",
        "mode": _resolve_flow_mode(variant["google_flow_mode"] or batch_mode),
        "prompt": None if smoke_test else variant["prompt_9_section"],
        "aspectRatio": "9:16",
        "modelLabel": "Veo 3.1 - Lite",
        "smoke_test": smoke_test,
    }


async def _assess_live_eligibility(
    batch: dict,
    variant: Optional[dict],
    expected_product_id: Optional[str] = None,
    include_smoke: bool = True,
) -> dict[str, Any]:
    db = await crud.get_db()
    client = get_flow_client()

    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM batch_variant WHERE batch_id = ? AND queue_status = 'QUEUED'",
        (batch["id"],),
    )
    queued_row = await cursor.fetchone()
    eligible_queued_variant_count = queued_row["cnt"]

    product = await crud.get_product(batch["product_id"])
    product_short_name = product.get("product_short_name") if product else None
    target_variant_status = variant["queue_status"] if variant else None
    has_prompt = bool(variant and variant["prompt_9_section"] and variant["prompt_9_section"].strip())
    product_id_match_expected = True if expected_product_id is None else batch["product_id"] == expected_product_id

    blocked_reason: list[str] = []
    if eligible_queued_variant_count < 1:
        blocked_reason.append("NO_QUEUED_VARIANT")
    if not variant:
        blocked_reason.append("TARGET_VARIANT_NOT_FOUND")
    elif variant["queue_status"] != "QUEUED":
        blocked_reason.append(f"TARGET_VARIANT_NOT_QUEUED:{variant['queue_status']}")
    if not has_prompt:
        blocked_reason.append("ABORT_PROMPT_MISSING")
    if not product_id_match_expected:
        blocked_reason.append(f"PRODUCT_ID_MISMATCH:{batch['product_id']}")

    extension_connected = client.connected
    extension_status = await client.get_status() if extension_connected else {"state": "off", "metrics": {}}
    extension_state = extension_status.get("state", "off")

    if not extension_connected:
        blocked_reason.append("ABORT_AGENT_OFFLINE")
    if extension_state not in ALLOWED_FLOW_STATES:
        blocked_reason.append(f"ABORT_FLOW_TAB_MISSING:{extension_state}")

    composer_result: dict[str, Any] = {
        "ok": False,
        "flow_tab_found": extension_state in ALLOWED_FLOW_STATES,
        "flow_url": None,
        "signed_in_likely": False,
        "composer_found": False,
        "composer_editable": False,
        "generate_button_found": False,
        "current_mode_visible": "UNKNOWN",
        "blocking_modal_detected": False,
    }
    execute_flow_job_smoke_status = "NOT_RUN"
    smoke_result: Optional[dict[str, Any]] = None

    if variant and extension_connected and extension_state in ALLOWED_FLOW_STATES:
        composer_result = await client.check_flow_composer_ready(_resolve_flow_mode(variant["google_flow_mode"] or batch["mode"]))
        if not composer_result.get("ok"):
            blocked_reason.append(composer_result.get("error") or "ABORT_FLOW_COMPOSER_NOT_READY")

        if include_smoke:
            if composer_result.get("ok"):
                smoke_result = await client.smoke_execute_flow_job(_build_flow_job(variant, batch["mode"], smoke_test=True))
                execute_flow_job_smoke_status = smoke_result.get(
                    "status",
                    "PASS" if smoke_result.get("ok") else "FAIL_ERROR",
                )
                if not smoke_result.get("ok"):
                    smoke_error = smoke_result.get("error") or "ABORT_RUNTIME_LASTERROR"
                    if execute_flow_job_smoke_status == "FAIL_TIMEOUT" or "Timeout" in smoke_error:
                        smoke_error = "ABORT_RUNTIME_LASTERROR: EXECUTE_FLOW_JOB smoke timeout"
                    blocked_reason.append(smoke_error)
            else:
                execute_flow_job_smoke_status = "SKIPPED"

    return {
        "batch_id": batch["id"],
        "selected_variant_id": variant["variant_id"] if variant else None,
        "eligible_queued_variant_count": eligible_queued_variant_count,
        "target_variant_status": target_variant_status,
        "has_prompt": has_prompt,
        "product_id": batch["product_id"],
        "product_short_name": product_short_name,
        "product_id_match_expected": product_id_match_expected,
        "extension_connected": extension_connected,
        "extension_state": extension_state,
        "flow_composer_ready": bool(composer_result.get("ok")),
        "composer_check": composer_result,
        "execute_flow_job_smoke_status": execute_flow_job_smoke_status,
        "smoke_result": smoke_result,
        "blocked_reason": blocked_reason,
    }

async def _log_event(batch_id: str, variant_id: str, status: str, message: str):
    db = await crud.get_db()
    event_id = str(uuid.uuid4())
    await db.execute("""
        INSERT INTO batch_queue_event (event_id, batch_id, variant_id, status, message, source)
        VALUES (?, ?, ?, ?, ?, 'executor')
    """, (event_id, batch_id, variant_id, status, message))
    await db.commit()

async def get_execution_status(batch_id: str) -> dict[str, Any]:
    db = await crud.get_db()
    
    # Find current running variant
    cursor = await db.execute("""
        SELECT * FROM batch_variant 
        WHERE batch_id = ? AND queue_status NOT IN ('READY', 'QUEUED', 'GENERATED', 'DOWNLOADED', 'QA_PASSED', 'FAILED', 'CANCELLED', 'DRY_RUN_VALIDATED')
        LIMIT 1
    """, (batch_id,))
    running = await cursor.fetchone()
    
    # Get last 10 events
    cursor = await db.execute("""
        SELECT * FROM batch_queue_event 
        WHERE batch_id = ?
        ORDER BY timestamp DESC
        LIMIT 10
    """, (batch_id,))
    events = await cursor.fetchall()
    
    return {
        "batch_id": batch_id,
        "running_variant": dict(running) if running else None,
        "events": [dict(e) for e in events]
    }
