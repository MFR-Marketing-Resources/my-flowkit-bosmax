"""Google Flow bulk generation orchestrator (V1).

Avatar image bulk: limited parallel IMG jobs (default 2).
Video bulk: serial single-flight via make_video video lane (max_parallel_videos=1).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services import make_video

logger = logging.getLogger(__name__)

_AVATAR_ASSET_MARKER = "AVATAR_CODE:"
_run_control: dict[str, str] = {}
_worker_tasks: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


async def _generated_avatar_asset_ids() -> dict[str, str]:
    from agent.services.creative_asset_service import list_creative_assets

    assets = await list_creative_assets(
        semantic_role="CHARACTER_REFERENCE", status="ACTIVE", limit=1000,
    )
    mapping: dict[str, str] = {}
    for asset in assets:
        description = str(getattr(asset, "description", "") or "")
        if _AVATAR_ASSET_MARKER in description:
            code = description.split(_AVATAR_ASSET_MARKER, 1)[1].split()[0].strip()
            if code:
                mapping[code.upper()] = asset.asset_id
    return mapping


async def _append_error_log(run_id: str, entry: dict) -> None:
    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        return
    log = _loads(run.get("error_log_json"), [])
    if not isinstance(log, list):
        log = []
    log.append({**entry, "at": _now()})
    await crud.update_bulk_generation_run(run_id, error_log_json=json.dumps(log))


def _clamp_parallel_images(n: int) -> int:
    return max(1, min(3, int(n or 2)))


def _clamp_parallel_videos(n: int) -> int:
    return 1 if int(n or 1) != 1 else 1


async def _serialize_run(run: dict) -> dict:
    rid = run["bulk_run_id"]
    counts = await crud.bulk_item_status_counts(rid)
    out = dict(run)
    out["status_counts"] = counts
    out["confirm_credit_burn"] = bool(run.get("confirm_credit_burn"))
    out["config"] = _loads(run.get("config_json"), {})
    return out


async def create_avatar_image_bulk_run(
    avatar_codes: list[str],
    *,
    aspect: str = "9:16",
    count: int = 1,
    image_model: str | None = None,
    max_parallel_images: int = 2,
    skip_already_generated: bool = True,
    allow_regenerate: bool = False,
    interval_min_seconds: int = 5,
    interval_max_seconds: int = 15,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 60,
    confirm_credit_burn: bool = False,
) -> dict:
    from agent.services import avatar_registry

    codes = [str(c).strip().upper() for c in avatar_codes if str(c).strip()]
    if not codes:
        raise ValueError("AVATAR_CODES_REQUIRED")

    generated = await _generated_avatar_asset_ids()
    skipped: list[dict] = []
    queued_codes: list[str] = []
    for code in codes:
        if generated.get(code) and skip_already_generated and not allow_regenerate:
            skipped.append({"avatar_code": code, "reason": "ALREADY_GENERATED"})
            continue
        try:
            avatar_registry.get_generation_prompt(code)
        except ValueError as exc:
            skipped.append({"avatar_code": code, "reason": str(exc)})
            continue
        queued_codes.append(code)

    if not queued_codes:
        raise ValueError("NO_ELIGIBLE_AVATARS")

    run_id = str(uuid.uuid4())
    config = {
        "aspect": aspect,
        "count": max(1, min(4, int(count or 1))),
        "image_model": image_model,
        "skip_already_generated": skip_already_generated,
        "allow_regenerate": allow_regenerate,
    }
    await crud.create_bulk_generation_run(
        run_id,
        kind="AVATAR_IMAGE",
        total_expected=len(queued_codes),
        max_parallel_images=_clamp_parallel_images(max_parallel_images),
        max_parallel_videos=1,
        confirm_credit_burn=confirm_credit_burn,
        interval_min_seconds=interval_min_seconds,
        interval_max_seconds=interval_max_seconds,
        cooldown_after_n_jobs=cooldown_after_n_jobs,
        cooldown_seconds=cooldown_seconds,
        config_json=json.dumps(config),
    )

    for code in queued_codes:
        identity = avatar_registry.get_generation_prompt(code)
        await crud.create_bulk_generation_item(
            str(uuid.uuid4()),
            bulk_run_id=run_id,
            item_type="AVATAR_IMAGE",
            source_ref=code,
            prompt_snapshot=identity.get("prompt"),
            payload_json=json.dumps({
                "avatar_code": code,
                "aspect": aspect,
                "count": config["count"],
                "image_model": image_model,
            }),
        )

    run = await crud.get_bulk_generation_run(run_id)
    return {
        "bulk_run_id": run_id,
        "kind": "AVATAR_IMAGE",
        "status": run["status"],
        "total_expected": len(queued_codes),
        "skipped": skipped,
        "max_parallel_images": _clamp_parallel_images(max_parallel_images),
    }


async def create_video_bulk_run(
    package_ids: list[str],
    *,
    model: str | None = None,
    aspect: str = "9:16",
    duration_s: int | None = None,
    interval_min_seconds: int = 5,
    interval_max_seconds: int = 15,
    cooldown_after_n_jobs: int = 5,
    cooldown_seconds: int = 60,
    confirm_credit_burn: bool = False,
) -> dict:
    from agent.services import production_queue_service as pq

    ids = [str(p).strip() for p in package_ids if str(p).strip()]
    if not ids:
        raise ValueError("PACKAGE_IDS_REQUIRED")

    refused: list[dict] = []
    eligible: list[dict] = []
    for pid in ids:
        pkg = await crud.get_workspace_generation_package(pid)
        if not pkg:
            refused.append({"package_id": pid, "reason": "PACKAGE_NOT_FOUND"})
            continue
        st = (pkg.get("production_status") or "NONE").upper()
        if st in ("RUNNING", "QUEUED"):
            refused.append({"package_id": pid, "reason": f"ALREADY_{st}"})
            continue
        if st != "APPROVED":
            refused.append({"package_id": pid, "reason": f"NOT_APPROVED:{st}"})
            continue
        eligible.append(pkg)

    if not eligible:
        raise ValueError("NO_ELIGIBLE_PACKAGES")

    run_id = str(uuid.uuid4())
    config = {"model": model, "aspect": aspect, "duration_s": duration_s}
    await crud.create_bulk_generation_run(
        run_id,
        kind="VIDEO",
        total_expected=len(eligible),
        max_parallel_images=2,
        max_parallel_videos=1,
        confirm_credit_burn=confirm_credit_burn,
        interval_min_seconds=interval_min_seconds,
        interval_max_seconds=interval_max_seconds,
        cooldown_after_n_jobs=cooldown_after_n_jobs,
        cooldown_seconds=cooldown_seconds,
        config_json=json.dumps(config),
    )

    for pkg in eligible:
        logical = (pkg.get("logical_mode") or pkg.get("mode") or "T2V").upper()
        item_type = "T2V" if logical in ("T2V", "HYBRID") else logical
        if item_type not in ("T2V", "I2V", "F2V"):
            item_type = "T2V"
        await crud.create_bulk_generation_item(
            str(uuid.uuid4()),
            bulk_run_id=run_id,
            item_type=item_type,
            source_ref=pkg["workspace_generation_package_id"],
            prompt_snapshot=(pkg.get("final_prompt_text") or "")[:2000],
            payload_json=json.dumps({
                "package_id": pkg["workspace_generation_package_id"],
                "model": model,
                "aspect": aspect,
                "duration_s": duration_s,
            }),
        )

    return {
        "bulk_run_id": run_id,
        "kind": "VIDEO",
        "status": "PENDING",
        "total_expected": len(eligible),
        "refused": refused,
        "max_parallel_videos": 1,
    }


async def start_bulk_run(
    bulk_run_id: str,
    *,
    confirm_credit_burn: bool = False,
    dry_run: bool = False,
) -> dict:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        raise ValueError("BULK_RUN_NOT_FOUND")
    if run["status"] in ("COMPLETED", "CANCELLED"):
        raise ValueError(f"BULK_RUN_NOT_STARTABLE:{run['status']}")
    if run["status"] == "RUNNING":
        task = _worker_tasks.get(bulk_run_id)
        if task and not task.done():
            raise ValueError("BULK_RUN_ALREADY_RUNNING")

    items = await crud.list_bulk_generation_items(bulk_run_id)
    queued = [i for i in items if i.get("status") == "QUEUED"]
    if not queued:
        raise ValueError("NO_QUEUED_ITEMS")

    if dry_run or not confirm_credit_burn:
        return {
            "bulk_run_id": bulk_run_id,
            "dry_run": True,
            "would_process": len(queued),
            "kind": run["kind"],
            "confirm_credit_burn_required": True,
            "max_parallel_images": run.get("max_parallel_images"),
            "max_parallel_videos": run.get("max_parallel_videos"),
            "items_preview": [
                {"bulk_item_id": i["bulk_item_id"], "source_ref": i["source_ref"], "item_type": i["item_type"]}
                for i in queued[:20]
            ],
        }

    await crud.update_bulk_generation_run(
        bulk_run_id,
        status="RUNNING",
        confirm_credit_burn=1,
        updated_at=_now(),
    )
    _run_control.pop(bulk_run_id, None)

    kind = (run.get("kind") or "").upper()
    if kind in ("AVATAR_IMAGE", "IMG"):
        task = asyncio.create_task(_live_avatar_image_loop(bulk_run_id))
    else:
        task = asyncio.create_task(_live_video_loop(bulk_run_id))
    _worker_tasks[bulk_run_id] = task

    return {
        "bulk_run_id": bulk_run_id,
        "status": "RUNNING",
        "queued_items": len(queued),
        "kind": kind,
    }


async def get_bulk_run_detail(bulk_run_id: str) -> dict | None:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        return None
    serialized = await _serialize_run(run)
    items = await crud.list_bulk_generation_items(bulk_run_id, limit=500)
    serialized["items"] = items
    return serialized


async def pause_bulk_run(bulk_run_id: str) -> dict:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        raise ValueError("BULK_RUN_NOT_FOUND")
    _run_control[bulk_run_id] = "PAUSE"
    await crud.update_bulk_generation_run(bulk_run_id, status="PAUSED", updated_at=_now())
    return {"bulk_run_id": bulk_run_id, "status": "PAUSED"}


async def cancel_bulk_run(bulk_run_id: str) -> dict:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        raise ValueError("BULK_RUN_NOT_FOUND")
    _run_control[bulk_run_id] = "CANCEL"
    cancelled_queued = 0
    for st in ("QUEUED", "SUBMITTED"):
        items = await crud.list_bulk_generation_items(bulk_run_id, status=st)
        for item in items:
            await crud.update_bulk_generation_item(
                item["bulk_item_id"], status="CANCELLED", updated_at=_now(),
            )
            cancelled_queued += 1
    await crud.update_bulk_generation_run(bulk_run_id, status="CANCELLED", updated_at=_now())
    task = _worker_tasks.pop(bulk_run_id, None)
    if task and not task.done():
        task.cancel()
    return {"bulk_run_id": bulk_run_id, "status": "CANCELLED", "cancelled_queued": cancelled_queued}


async def retry_failed_bulk_run(bulk_run_id: str) -> dict:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        raise ValueError("BULK_RUN_NOT_FOUND")
    if run["status"] == "RUNNING":
        task = _worker_tasks.get(bulk_run_id)
        if task and not task.done():
            raise ValueError("BULK_RUN_STILL_RUNNING")

    items = await crud.list_bulk_generation_items(bulk_run_id, limit=500)
    retried = 0
    for item in items:
        if item.get("status") != "FAILED":
            continue
        rc = int(item.get("retry_count") or 0) + 1
        await crud.update_bulk_generation_item(
            item["bulk_item_id"],
            status="QUEUED",
            error=None,
            job_id=None,
            media_id=None,
            local_path=None,
            retry_count=rc,
            updated_at=_now(),
        )
        retried += 1
    if retried == 0:
        raise ValueError("NO_FAILED_ITEMS")

    counts = await crud.bulk_item_status_counts(bulk_run_id)
    failed_left = int(counts.get("FAILED", 0))
    await crud.update_bulk_generation_run(
        bulk_run_id,
        status="PENDING",
        total_failed=failed_left,
        updated_at=_now(),
    )
    return {"bulk_run_id": bulk_run_id, "retried": retried, "status": "PENDING"}


async def recover_stuck_bulk_runs() -> dict:
    """After agent restart: pause RUNNING runs with no live worker; re-queue stuck items."""
    runs = await crud.list_bulk_generation_runs(limit=100)
    recovered: list[str] = []
    for run in runs:
        if (run.get("status") or "").upper() != "RUNNING":
            continue
        rid = run["bulk_run_id"]
        task = _worker_tasks.get(rid)
        if task is not None and not task.done():
            continue
        items = await crud.list_bulk_generation_items(rid, limit=500)
        for item in items:
            if item.get("status") in ("RUNNING", "SUBMITTED"):
                await crud.update_bulk_generation_item(
                    item["bulk_item_id"],
                    status="QUEUED",
                    error="RECOVERED_AFTER_AGENT_RESTART",
                    job_id=None,
                    updated_at=_now(),
                )
        await crud.update_bulk_generation_run(rid, status="PAUSED", updated_at=_now())
        _run_control.pop(rid, None)
        _worker_tasks.pop(rid, None)
        recovered.append(rid)
        await _append_error_log(
            rid,
            {"event": "RECOVER_STUCK_RUN", "note": "Worker lost after restart; run paused, items re-queued"},
        )
    return {"recovered_runs": recovered, "count": len(recovered)}


async def register_avatar_assets_bulk(bulk_run_id: str) -> dict:
    run = await crud.get_bulk_generation_run(bulk_run_id)
    if not run:
        raise ValueError("BULK_RUN_NOT_FOUND")

    items = await crud.list_bulk_generation_items(bulk_run_id, limit=500)
    registered = 0
    failed = 0
    results: list[dict] = []

    for item in items:
        if item.get("status") not in ("GENERATED", "DOWNLOADED"):
            continue
        if item.get("creative_asset_id"):
            continue
        try:
            asset_id = await _register_avatar_item(item)
            await crud.update_bulk_generation_item(
                item["bulk_item_id"],
                status="REGISTERED",
                creative_asset_id=asset_id,
                updated_at=_now(),
            )
            registered += 1
            results.append({"bulk_item_id": item["bulk_item_id"], "creative_asset_id": asset_id, "ok": True})
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results.append({"bulk_item_id": item["bulk_item_id"], "ok": False, "error": str(exc)})

    return {"bulk_run_id": bulk_run_id, "registered": registered, "failed": failed, "results": results}


async def _register_avatar_item(item: dict) -> str:
    import base64
    from pathlib import Path

    from agent.models.creative_asset import CreativeAssetCreateRequest
    from agent.services import avatar_registry
    from agent.services.creative_asset_service import create_creative_asset

    code = str(item.get("source_ref") or "").upper()
    media_id = item.get("media_id")
    if not media_id:
        raise ValueError("NO_MEDIA_FOR_REGISTER")

    identity = avatar_registry.get_generation_prompt(code)
    artifacts = await crud.list_generated_artifacts(limit=200, kind="image")
    artifact = next((a for a in artifacts if a.get("media_id") == media_id), None)
    if artifact is None and item.get("local_path"):
        artifact = {"local_path": item.get("local_path"), "media_id": media_id}
    if artifact is None:
        raise ValueError("GENERATED_ARTIFACT_NOT_FOUND")

    artifact_path = Path(str(artifact.get("local_path") or ""))
    if not artifact_path.is_file():
        raise ValueError("GENERATED_ARTIFACT_FILE_MISSING")

    image_base64 = base64.b64encode(artifact_path.read_bytes()).decode("ascii")
    record = await create_creative_asset(
        CreativeAssetCreateRequest(
            semantic_role="CHARACTER_REFERENCE",
            display_name=f"{identity['character_name']} — {identity['avatar_code']}",
            description=(
                f"{_AVATAR_ASSET_MARKER}{identity['avatar_code']} — bulk orchestrator IMG lane"
            ),
            source_type="GENERATED_IMAGE",
            storage_kind="LOCAL_FILE",
            media_id=media_id,
            image_base64=image_base64,
            file_name=artifact_path.name,
        ),
    )
    return record.asset_id


async def _finalize_run(run_id: str) -> None:
    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        return
    items = await crud.list_bulk_generation_items(run_id, limit=500)
    completed = sum(1 for i in items if i.get("status") in ("GENERATED", "DOWNLOADED", "REGISTERED"))
    failed = sum(1 for i in items if i.get("status") == "FAILED")
    cancelled = sum(1 for i in items if i.get("status") == "CANCELLED")
    total = len(items)
    if failed and completed:
        status = "PARTIAL_FAILED"
    elif failed and not completed:
        status = "FAILED"
    elif completed + cancelled >= total:
        status = "COMPLETED"
    else:
        status = "PARTIAL_FAILED"
    await crud.update_bulk_generation_run(
        run_id,
        status=status,
        total_completed=completed,
        total_failed=failed,
        updated_at=_now(),
    )
    _worker_tasks.pop(run_id, None)
    _run_control.pop(run_id, None)


async def _live_avatar_image_loop(run_id: str) -> None:
    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        return
    max_p = _clamp_parallel_images(int(run.get("max_parallel_images") or 2))
    interval_min = int(run.get("interval_min_seconds") or 5)
    interval_max = int(run.get("interval_max_seconds") or 15)
    cooldown_after = int(run.get("cooldown_after_n_jobs") or 5)
    cooldown_sec = int(run.get("cooldown_seconds") or 60)
    config = _loads(run.get("config_json"), {})
    jobs_since_cooldown = 0

    sem = asyncio.Semaphore(max_p)

    async def worker() -> None:
        nonlocal jobs_since_cooldown
        while True:
            if _run_control.get(run_id) == "CANCEL":
                return
            while _run_control.get(run_id) == "PAUSE":
                await asyncio.sleep(2)
                if _run_control.get(run_id) == "CANCEL":
                    return

            item = await crud.claim_next_bulk_item(run_id)
            if not item:
                return

            async with sem:
                await _process_avatar_image_item(run_id, item, config)
            jobs_since_cooldown += 1
            if jobs_since_cooldown >= cooldown_after:
                await asyncio.sleep(cooldown_sec)
                jobs_since_cooldown = 0
            else:
                await asyncio.sleep(random.uniform(interval_min, interval_max))

    try:
        await asyncio.gather(*[worker() for _ in range(max_p)])
    except asyncio.CancelledError:
        pass
    finally:
        await _finalize_run(run_id)


async def _process_avatar_image_item(run_id: str, item: dict, config: dict) -> None:
    from agent.services import avatar_registry

    item_id = item["bulk_item_id"]
    code = item["source_ref"]
    await crud.update_bulk_generation_item(
        item_id, status="RUNNING", started_at=_now(), updated_at=_now(),
    )
    try:
        identity = avatar_registry.get_generation_prompt(code)
        payload = _loads(item.get("payload_json"), {})
        aspect = payload.get("aspect") or config.get("aspect") or "9:16"
        count = int(payload.get("count") or config.get("count") or 1)
        image_model = payload.get("image_model") or config.get("image_model")

        result = await make_video.start_generate(
            "IMG",
            identity["prompt"],
            aspect=aspect,
            num_videos=count,
            image_model=image_model,
        )
        if result.get("status") == "REJECTED":
            raise RuntimeError(result.get("error") or "REJECTED")

        job_id = result.get("job_id")
        await crud.update_bulk_generation_item(
            item_id, job_id=job_id, status="SUBMITTED", updated_at=_now(),
        )

        deadline = asyncio.get_event_loop().time() + 600
        while asyncio.get_event_loop().time() < deadline:
            if _run_control.get(run_id) == "CANCEL":
                return
            job = make_video.get_job(job_id)
            if not job:
                await asyncio.sleep(2)
                continue
            st = (job.get("status") or "").upper()
            if st == "DONE":
                media_id = job.get("media_id")
                local_path = job.get("local_path")
                await crud.update_bulk_generation_item(
                    item_id,
                    status="GENERATED",
                    media_id=media_id,
                    local_path=local_path,
                    completed_at=_now(),
                    updated_at=_now(),
                )
                run = await crud.get_bulk_generation_run(run_id)
                tc = int(run.get("total_completed") or 0) + 1
                await crud.update_bulk_generation_run(run_id, total_completed=tc, updated_at=_now())
                return
            if st == "FAILED":
                raise RuntimeError(job.get("error") or "IMG_JOB_FAILED")
            await asyncio.sleep(3)

        raise RuntimeError("IMG_JOB_TIMEOUT")
    except Exception as exc:  # noqa: BLE001
        await crud.update_bulk_generation_item(
            item_id,
            status="FAILED",
            error=str(exc),
            completed_at=_now(),
            updated_at=_now(),
        )
        run = await crud.get_bulk_generation_run(run_id)
        tf = int(run.get("total_failed") or 0) + 1
        await crud.update_bulk_generation_run(run_id, total_failed=tf, updated_at=_now())
        await _append_error_log(run_id, {"bulk_item_id": item_id, "error": str(exc)})


_VIDEO_POLL_SECONDS = 5
_VIDEO_JOB_TIMEOUT_SECONDS = 30 * 60
_VIDEO_INFLIGHT_RETRY_SECONDS = 30
_VIDEO_INFLIGHT_MAX_RETRIES = 20


async def _fire_video_payload(payload: dict, wgp_id: str) -> dict:
    """Serial video lane: honour VIDEO_JOB_IN_FLIGHT retries like production queue."""
    attempts = 0
    while True:
        result = await make_video.start_generate(
            payload["mode"],
            payload["prompt"],
            image_media_ids=payload.get("image_media_ids"),
            aspect=payload.get("aspect") or "9:16",
            model=payload.get("model"),
            duration_s=payload.get("duration_s"),
            num_videos=payload.get("num_videos") or 1,
        )
        if result.get("status") == "REJECTED" and result.get("error") == "VIDEO_JOB_IN_FLIGHT":
            attempts += 1
            if attempts > _VIDEO_INFLIGHT_MAX_RETRIES:
                await crud.update_workspace_generation_package(
                    wgp_id,
                    production_status="FAILED",
                    production_error="VIDEO_LANE_BUSY_TIMEOUT",
                )
                return {"ok": False, "error": "VIDEO_LANE_BUSY_TIMEOUT"}
            await asyncio.sleep(_VIDEO_INFLIGHT_RETRY_SECONDS)
            continue
        break

    job_id = result.get("job_id")
    if not job_id:
        err = result.get("error") or "NO_JOB_ID"
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error=str(err),
        )
        return {"ok": False, "error": str(err)}

    await crud.update_workspace_generation_package(wgp_id, production_job_id=job_id)

    waited = 0
    while waited < _VIDEO_JOB_TIMEOUT_SECONDS:
        job = make_video.get_job(job_id) or {}
        status = job.get("status")
        if status in ("DONE", "FAILED", "REJECTED", "GENERATED_BUT_UNRETRIEVED"):
            break
        await asyncio.sleep(_VIDEO_POLL_SECONDS)
        waited += _VIDEO_POLL_SECONDS
    else:
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error="JOB_TIMEOUT",
        )
        return {"ok": False, "error": "JOB_TIMEOUT", "job_id": job_id}

    job = make_video.get_job(job_id) or {}
    if job.get("status") in ("FAILED", "REJECTED"):
        err = job.get("error") or "VIDEO_JOB_FAILED"
        await crud.update_workspace_generation_package(
            wgp_id, production_status="FAILED", production_error=str(err),
        )
        return {"ok": False, "error": str(err), "job_id": job_id}

    media_id = job.get("media_id")
    local_path = job.get("local_path")
    await crud.update_workspace_generation_package(
        wgp_id, production_status="GENERATED", production_error=None,
    )
    return {"ok": True, "job_id": job_id, "media_id": media_id, "local_path": local_path}


async def _live_video_loop(run_id: str) -> None:
    from agent.services import production_queue_service as pq

    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        return
    config = _loads(run.get("config_json"), {})
    run_config = {
        "model": config.get("model"),
        "aspect": config.get("aspect") or "9:16",
        "count": 1,
    }
    interval_min = int(run.get("interval_min_seconds") or 5)
    interval_max = int(run.get("interval_max_seconds") or 15)
    cooldown_after = int(run.get("cooldown_after_n_jobs") or 5)
    cooldown_sec = int(run.get("cooldown_seconds") or 60)
    jobs_since_cooldown = 0

    try:
        while True:
            if _run_control.get(run_id) == "CANCEL":
                break
            while _run_control.get(run_id) == "PAUSE":
                await asyncio.sleep(2)
                if _run_control.get(run_id) == "CANCEL":
                    break

            item = await crud.claim_next_bulk_item(run_id)
            if not item:
                break

            item_id = item["bulk_item_id"]
            wgp_id = item["source_ref"]
            await crud.update_bulk_generation_item(
                item_id, status="RUNNING", started_at=_now(), updated_at=_now(),
            )
            try:
                pkg = await crud.get_workspace_generation_package(wgp_id)
                if not pkg:
                    raise RuntimeError("PACKAGE_NOT_FOUND")
                prod_st = (pkg.get("production_status") or "NONE").upper()
                if prod_st != "APPROVED":
                    raise RuntimeError(f"NOT_APPROVED:{prod_st}")

                await crud.update_workspace_generation_package(
                    wgp_id, production_status="RUNNING", production_error=None,
                )
                payload, blockers = await pq.build_execution_payload(pkg, run_config)
                if blockers:
                    raise RuntimeError(",".join(blockers))

                outcome = await _fire_video_payload(payload, wgp_id)
                if not outcome.get("ok"):
                    raise RuntimeError(outcome.get("error") or "VIDEO_FAILED")

                await crud.update_bulk_generation_item(
                    item_id,
                    status="GENERATED",
                    job_id=outcome.get("job_id"),
                    media_id=outcome.get("media_id"),
                    local_path=outcome.get("local_path"),
                    completed_at=_now(),
                    updated_at=_now(),
                )
                run_row = await crud.get_bulk_generation_run(run_id)
                tc = int(run_row.get("total_completed") or 0) + 1
                await crud.update_bulk_generation_run(run_id, total_completed=tc, updated_at=_now())
            except Exception as exc:  # noqa: BLE001
                await crud.update_bulk_generation_item(
                    item_id,
                    status="FAILED",
                    error=str(exc),
                    completed_at=_now(),
                    updated_at=_now(),
                )
                run_row = await crud.get_bulk_generation_run(run_id)
                tf = int(run_row.get("total_failed") or 0) + 1
                await crud.update_bulk_generation_run(run_id, total_failed=tf, updated_at=_now())
                await _append_error_log(run_id, {"bulk_item_id": item_id, "error": str(exc)})
                pkg = await crud.get_workspace_generation_package(wgp_id)
                if pkg and (pkg.get("production_status") or "").upper() == "RUNNING":
                    await crud.update_workspace_generation_package(
                        wgp_id, production_status="FAILED", production_error=str(exc),
                    )

            jobs_since_cooldown += 1
            if jobs_since_cooldown >= cooldown_after:
                await asyncio.sleep(cooldown_sec)
                jobs_since_cooldown = 0
            else:
                await asyncio.sleep(random.uniform(interval_min, interval_max))
    except asyncio.CancelledError:
        pass
    finally:
        await _finalize_run(run_id)