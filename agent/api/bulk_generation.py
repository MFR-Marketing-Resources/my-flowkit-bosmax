"""Bulk generation orchestrator API (Google Flow V1)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.services import bulk_generation_service as svc

router = APIRouter(prefix="/bulk-generation", tags=["bulk-generation"])


class AvatarImageBulkRequest(BaseModel):
    avatar_codes: list[str] = Field(..., min_length=1)
    aspect: str = "9:16"
    count: int = 1
    image_model: str | None = None
    max_parallel_images: int = 2
    skip_already_generated: bool = True
    allow_regenerate: bool = False
    interval_min_seconds: int = 5
    interval_max_seconds: int = 15
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 60
    confirm_credit_burn: bool = False


class VideoBulkRequest(BaseModel):
    package_ids: list[str] = Field(..., min_length=1)
    model: str | None = None
    aspect: str = "9:16"
    duration_s: int | None = None
    interval_min_seconds: int = 5
    interval_max_seconds: int = 15
    cooldown_after_n_jobs: int = 5
    cooldown_seconds: int = 60
    confirm_credit_burn: bool = False


class StartBulkRequest(BaseModel):
    confirm_credit_burn: bool = False
    dry_run: bool = False


@router.get("/runs")
async def list_bulks(limit: int = 20):
    from agent.db import crud

    runs = await crud.list_bulk_generation_runs(limit=limit)
    return {"runs": runs, "count": len(runs)}


@router.post("/recover-stuck")
async def recover_stuck():
    return await svc.recover_stuck_bulk_runs()


@router.post("/avatar-images")
async def create_avatar_image_bulk(body: AvatarImageBulkRequest):
    try:
        return await svc.create_avatar_image_bulk_run(
            body.avatar_codes,
            aspect=body.aspect,
            count=body.count,
            image_model=body.image_model,
            max_parallel_images=body.max_parallel_images,
            skip_already_generated=body.skip_already_generated,
            allow_regenerate=body.allow_regenerate,
            interval_min_seconds=body.interval_min_seconds,
            interval_max_seconds=body.interval_max_seconds,
            cooldown_after_n_jobs=body.cooldown_after_n_jobs,
            cooldown_seconds=body.cooldown_seconds,
            confirm_credit_burn=body.confirm_credit_burn,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/videos")
async def create_video_bulk(body: VideoBulkRequest):
    try:
        return await svc.create_video_bulk_run(
            body.package_ids,
            model=body.model,
            aspect=body.aspect,
            duration_s=body.duration_s,
            interval_min_seconds=body.interval_min_seconds,
            interval_max_seconds=body.interval_max_seconds,
            cooldown_after_n_jobs=body.cooldown_after_n_jobs,
            cooldown_seconds=body.cooldown_seconds,
            confirm_credit_burn=body.confirm_credit_burn,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{bulk_run_id}")
async def get_bulk(bulk_run_id: str):
    detail = await svc.get_bulk_run_detail(bulk_run_id)
    if not detail:
        raise HTTPException(404, "BULK_RUN_NOT_FOUND")
    return detail


@router.post("/{bulk_run_id}/start")
async def start_bulk(bulk_run_id: str, body: StartBulkRequest):
    try:
        return await svc.start_bulk_run(
            bulk_run_id,
            confirm_credit_burn=body.confirm_credit_burn,
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{bulk_run_id}/pause")
async def pause_bulk(bulk_run_id: str):
    try:
        return await svc.pause_bulk_run(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{bulk_run_id}/cancel")
async def cancel_bulk(bulk_run_id: str):
    try:
        return await svc.cancel_bulk_run(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{bulk_run_id}/retry-failed")
async def retry_failed_bulk(bulk_run_id: str):
    try:
        return await svc.retry_failed_bulk_run(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{bulk_run_id}/register-avatar-assets")
async def register_avatar_assets(bulk_run_id: str):
    try:
        return await svc.register_avatar_assets_bulk(bulk_run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/runs/{run_id}/materialize-approval-manifest")
async def materialize_bulk_approval_manifest(run_id: str):
    """Freeze one Approved Generation Manifest (run_ref = the bulk run id) whose
    per-item execution-envelope hashes match what the bulk live loop dispatches.

    VIDEO runs freeze one item per package built from the BULK run's config (the
    same config the video loop dispatches with: model/aspect, count forced to 1),
    so materialize==dispatch parity is exact even when a package's own production
    run differs. AVATAR_IMAGE runs freeze one IMG item per avatar, mirroring the
    exact ``start_generate('IMG', prompt, aspect=..., num_videos=count,
    image_model=...)`` shape (no product_id; asset_fingerprints=[]).

    Provider-free: nothing fires; the manifest starts REVIEW_REQUIRED and must be
    approved before any dispatch resolves it. HTTP 422 on build blockers."""
    import json

    from agent.db import crud
    from agent.services import execution_approval_service as eas
    from agent.services import production_queue_service as pq

    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        raise HTTPException(404, "BULK_RUN_NOT_FOUND")

    cfg = json.loads(run.get("config_json") or "{}")
    if not isinstance(cfg, dict):
        cfg = {}
    kind = (run.get("kind") or "").upper()
    bulk_items = await crud.list_bulk_generation_items(run_id, limit=500)

    items: list[dict] = []
    try:
        if kind in ("AVATAR_IMAGE", "IMG"):
            from agent.services import avatar_registry

            for it in bulk_items:
                if (it.get("item_type") or "").upper() != "AVATAR_IMAGE":
                    continue
                code = str(it.get("source_ref") or "")
                identity = avatar_registry.get_generation_prompt(code)
                # Mirror _process_avatar_image_item EXACTLY: per-item payload
                # overrides win over run config (payload.get(...) or cfg.get(...)),
                # else the frozen item's hash won't match the dispatch.
                ipayload = json.loads(it.get("payload_json") or "{}")
                if not isinstance(ipayload, dict):
                    ipayload = {}
                items.append({
                    "item_key": code,
                    "mode": "IMG",
                    "final_prompt_text": identity["prompt"],
                    "aspect": ipayload.get("aspect") or cfg.get("aspect") or "9:16",
                    "count": int(ipayload.get("count") or cfg.get("count") or 1),
                    "image_model": ipayload.get("image_model") or cfg.get("image_model"),
                })
        else:
            # Bulk video loop dispatches every item with THIS run_config
            # (count forced to 1) — freeze the items against the same config.
            run_config = {
                "model": cfg.get("model"),
                "aspect": cfg.get("aspect") or "9:16",
                "count": 1,
            }
            for it in bulk_items:
                if (it.get("item_type") or "").upper() not in ("T2V", "I2V", "F2V"):
                    continue
                items.append(await pq.build_package_manifest_item(
                    str(it.get("source_ref") or ""), run_config=run_config,
                ))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if not items:
        raise HTTPException(422, "NO_ELIGIBLE_ITEMS")
    return await eas.create_manifest(
        surface="bulk", run_ref=run_id, items=items, created_by="operator",
    )