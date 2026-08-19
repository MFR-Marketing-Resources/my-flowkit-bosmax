"""API router for the Production Queue (prompt/production split).

Approved prompt packages are enqueued here and executed through the one
hardened generate lane with interval + cooldown. Fail-closed: every run
starts as a dry run; live execution requires confirm_live_credit_burn=true.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from agent.db import crud
from agent.services import execution_approval_service as eas
from agent.services import production_queue_service as pq

router = APIRouter(prefix="/workspace/production-queue", tags=["production-queue"])

# Operator-facing Approved Generation Manifest materialization. A dedicated
# /production-queue prefix keeps the path at /api/production-queue/... while the
# existing send-to-production router keeps its /workspace/production-queue prefix.
materialize_router = APIRouter(prefix="/production-queue", tags=["production-queue"])


class SendToProductionRequest(BaseModel):
    package_ids: List[str]
    interval_min_seconds: int = 45
    interval_max_seconds: int = 120
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 300
    aspect: str = "9:16"
    model: str | None = None
    count: int = 1


class StartRunRequest(BaseModel):
    confirm_live_credit_burn: bool = False
    # Round F one-serial live lanes: 'ONE_SERIAL_T2V' or 'ONE_SERIAL_F2V', each
    # with its own DISTINCT confirm_phrase. Opt-in: omitting live_gate leaves the
    # pre-existing bulk live path (a protected system, G0 §3) unchanged and
    # strictly T2V-only.
    live_gate: str | None = None
    confirm_phrase: str | None = None
    expect_package_id: str | None = None
    # Stage 2A BULK_FANOUT gate only: the caller must pin the EXACT itemized set
    # it previewed — package ids AND the dialogue fingerprints the operator saw.
    # Unused by the one-serial lanes, which stay singular.
    expect_package_ids: list[str] | None = None
    expect_dialogue_fingerprints: list[str] | None = None


@router.post("")
async def send_to_production(request: SendToProductionRequest):
    """Enqueue APPROVED prompt packages into a new production run (no firing yet)."""
    try:
        run = await pq.send_to_production(
            request.package_ids,
            interval_min_seconds=request.interval_min_seconds,
            interval_max_seconds=request.interval_max_seconds,
            cooldown_after_n_jobs=request.cooldown_after_n_jobs,
            cooldown_seconds=request.cooldown_seconds,
            aspect=request.aspect,
            model=request.model,
            count=request.count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return run


@router.get("")
async def list_runs(limit: int = 50):
    runs = await crud.list_production_runs(limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.get("/{run_id}")
async def get_run(run_id: str):
    run = await pq.get_production_run_detail(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    return run


@router.post("/{run_id}/start")
async def start_run(run_id: str, request: StartRunRequest):
    """Start a run. Without confirm_live_credit_burn this is a DRY RUN:
    payloads are validated and reported, nothing fires, no credits burn."""
    try:
        return await pq.run_production_queue(
            run_id, confirm_live_credit_burn=request.confirm_live_credit_burn,
            live_gate=request.live_gate,
            confirm_phrase=request.confirm_phrase,
            expect_package_id=request.expect_package_id,
            expect_package_ids=request.expect_package_ids,
            expect_dialogue_fingerprints=request.expect_dialogue_fingerprints,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "RUN_NOT_FOUND":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=409, detail=message)


@router.post("/{run_id}/pause")
async def pause_run(run_id: str):
    run = await crud.get_production_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    if run.get("status") != "RUNNING":
        raise HTTPException(status_code=409, detail=f"RUN_NOT_RUNNING:{run.get('status')}")
    pq.pause_production_run(run_id)
    return {"ok": True, "run_id": run_id, "signal": "PAUSE"}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = await crud.get_production_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
    if run.get("status") in ("COMPLETED", "CANCELLED", "FAILED"):
        raise HTTPException(status_code=409, detail=f"RUN_ALREADY_TERMINAL:{run.get('status')}")
    if run.get("status") == "RUNNING":
        pq.cancel_production_run_signal(run_id)
        return {"ok": True, "run_id": run_id, "signal": "CANCEL"}
    # PENDING / PAUSED runs cancel synchronously.
    await pq._cancel_remaining(run_id)
    await crud.update_production_run(run_id, status="CANCELLED")
    return {"ok": True, "run_id": run_id, "status": "CANCELLED"}


@router.post("/{run_id}/retry")
async def retry_run(run_id: str):
    try:
        return await pq.retry_failed_items(run_id)
    except ValueError as exc:
        message = str(exc)
        if message == "RUN_NOT_FOUND":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=409, detail=message)


@materialize_router.post("/packages/{wgp_id}/materialize-approval-manifest")
async def materialize_package_approval_manifest(
    wgp_id: str, surface: str = "production_queue",
):
    """Freeze a 1-item Approved Generation Manifest whose execution-envelope hash
    matches this package's queue/studio dispatch (run_ref = the package id — the
    exact key the dispatch uses to look up its approved manifest).

    Provider-free: nothing fires and no credit is spent here. The manifest starts
    REVIEW_REQUIRED; the operator still approves it before any dispatch can resolve
    it. Returns HTTP 422 when the package cannot be dispatched (build blockers)."""
    if surface not in ("production_queue", "production_studio"):
        raise HTTPException(status_code=422, detail=f"UNSUPPORTED_SURFACE:{surface}")
    try:
        item = await pq.build_package_manifest_item(wgp_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await eas.create_manifest(
        surface=surface, run_ref=wgp_id, items=[item], created_by="operator",
    )
