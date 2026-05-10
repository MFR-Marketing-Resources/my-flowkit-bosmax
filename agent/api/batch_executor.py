from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from agent.services import batch_executor

router = APIRouter(prefix="/batches", tags=["batches"])

@router.post("/{batch_id}/execute-next")
async def execute_next(
    batch_id: str,
    dry_run: bool = Query(True),
    max_variants: int = Query(1)
):
    """
    Pick the next queued variant and execute it.
    Default is dry_run=True, max_variants=1.
    """
    try:
        res = await batch_executor.execute_next_variant(batch_id, dry_run=dry_run, max_variants=max_variants)
        if "error" in res:
            return {"ok": False, "error": res["error"]}
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{batch_id}/execute-variant/{variant_id}")
async def execute_variant(
    batch_id: str,
    variant_id: str,
    dry_run: bool = Query(True)
):
    """
    Execute a specific variant from the batch queue.
    """
    try:
        res = await batch_executor.execute_variant(variant_id, dry_run=dry_run)
        if "error" in res:
            return {"ok": False, "error": res["error"]}
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{batch_id}/variants/{variant_id}/requeue")
async def requeue_variant(batch_id: str, variant_id: str):
    """Explicitly requeue a single variant for controlled live execution."""
    try:
        res = await batch_executor.requeue_variant(batch_id, variant_id)
        if "error" in res:
            return {"ok": False, "error": res["error"]}
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{batch_id}/live-eligibility")
async def get_live_eligibility(
    batch_id: str,
    variant_id: Optional[str] = Query(None),
    expected_product_id: Optional[str] = Query(None),
):
    """Report whether a batch can safely attempt one controlled live execution."""
    try:
        res = await batch_executor.get_live_eligibility(
            batch_id,
            variant_id=variant_id,
            expected_product_id=expected_product_id,
        )
        if "error" in res:
            return {"ok": False, "error": res["error"]}
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{batch_id}/variants/{variant_id}/smoke-execute-flow-job")
async def smoke_execute_flow_job(batch_id: str, variant_id: str):
    """Run a non-generating websocket smoke check for EXECUTE_FLOW_JOB."""
    try:
        res = await batch_executor.smoke_execute_flow_job(batch_id, variant_id)
        if "error" in res and not res.get("ok"):
            return {"ok": False, "error": res["error"], **{k: v for k, v in res.items() if k not in {"error"}}}
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{batch_id}/execution-status")
async def get_status(batch_id: str):
    """
    Get live execution status and recent events for a batch.
    """
    try:
        return await batch_executor.get_execution_status(batch_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
