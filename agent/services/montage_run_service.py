"""Montage durable discrete run ledger (M-02).

Persists beat → scene job lifecycle on existing bulk_generation_run/item tables
(kind=MONTAGE_DISCRETE). Orchestration reuses montage_scene_orchestrator →
canonical workspace package factory. Result identity via bind_scene_result.

No second video engine. No DOM lane. Credit fire is never automatic.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence

from agent.db import crud
from agent.services.montage_assembly_readiness import (
    MontageSceneReadiness,
    assess_montage_assembly_readiness,
)
from agent.services.montage_discrete_assembly import assemble_montage_discrete
from agent.services.montage_scene_orchestrator import (
    MontageOrchestrationReport,
    SceneJobState,
    orchestrate_montage_scenes,
)
from agent.services.montage_scene_reference_policy import (
    SceneReferencePolicy,
    parse_scene_reference_policy,
)

KIND = "MONTAGE_DISCRETE"
ITEM_TYPE = "MONTAGE_SCENE"

PackageFactory = Callable[..., Awaitable[dict[str, Any]]]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _loads(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return {} if default is None else default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {} if default is None else default


async def create_montage_discrete_run(
    *,
    product_id: str,
    story_beats: Sequence[Any],
    package_factory: PackageFactory,
    default_policy: SceneReferencePolicy | str = SceneReferencePolicy.PRODUCT_ANCHOR,
    per_beat_policy: Optional[dict[str, str]] = None,
    product_media_id: Optional[str] = None,
    scene_context_override: Optional[str] = None,
    copy_fallback_confirmed: bool = True,
    hook_id: str = "AUTO",
    background_id: str = "AUTO",
) -> dict[str, Any]:
    """Orchestrate packages and persist a durable run + per-scene jobs."""
    pid = str(product_id or "").strip()
    if not pid:
        raise ValueError("ERR_MONTAGE_PRODUCT_REQUIRED")
    if not story_beats:
        raise ValueError("ERR_MONTAGE_BEATS_REQUIRED")

    report = await orchestrate_montage_scenes(
        product_id=pid,
        story_beats=story_beats,
        package_factory=package_factory,
        default_policy=default_policy,
        per_beat_policy=per_beat_policy,
        product_media_id=product_media_id,
        generate_fn=None,
        scene_context_override=scene_context_override,
        copy_fallback_confirmed=copy_fallback_confirmed,
    )

    run_id = str(uuid.uuid4())
    policy_val = (
        default_policy.value
        if isinstance(default_policy, SceneReferencePolicy)
        else str(default_policy)
    )
    config = {
        "product_id": pid,
        "product_media_id": product_media_id,
        "default_policy": policy_val,
        "per_beat_policy": per_beat_policy or {},
        "hook_id": hook_id,
        "background_id": background_id,
        "scene_context_override": scene_context_override,
        "orchestration_ok": report.ok,
    }
    await crud.create_bulk_generation_run(
        run_id,
        kind=KIND,
        total_expected=len(report.scenes),
        max_parallel_images=1,
        max_parallel_videos=1,
        confirm_credit_burn=False,
        config_json=json.dumps(config),
    )
    await crud.update_bulk_generation_run(
        run_id, status="PREPARED" if report.ok else "PARTIAL", updated_at=_now()
    )

    scenes_out: list[dict[str, Any]] = []
    for state in report.scenes:
        item_id = str(uuid.uuid4())
        payload = _scene_payload(state, product_media_id=product_media_id)
        await crud.create_bulk_generation_item(
            item_id,
            bulk_run_id=run_id,
            item_type=ITEM_TYPE,
            source_ref=state.scene_id,
            prompt_snapshot=(state.detail or state.beat_id or "")[:2000],
            payload_json=json.dumps(payload),
            status=state.status,
        )
        if state.error_code:
            await crud.update_bulk_generation_item(
                item_id, error=state.error_code, updated_at=_now()
            )
        row = state.to_dict()
        row["bulk_item_id"] = item_id
        row["montage_run_id"] = run_id
        scenes_out.append(row)

    return {
        "montage_run_id": run_id,
        "kind": KIND,
        "status": "PREPARED" if report.ok else "PARTIAL",
        "product_id": pid,
        "ok": report.ok,
        "detail": report.detail,
        "total_scenes": len(scenes_out),
        "scenes": scenes_out,
        "execution_supported": True,
        "credit_spend": False,
        "assembly_path": "DISCRETE_MONTAGE",
        "lifecycle": [
            "PLANNED",
            "PACKAGE_READY",
            "IMAGE_BOUND",
            "VIDEO_READY",
            "RESULT_BOUND",
        ],
    }


async def get_montage_discrete_run(run_id: str) -> dict[str, Any]:
    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        raise ValueError("ERR_MONTAGE_RUN_NOT_FOUND")
    if (run.get("kind") or "").upper() != KIND:
        raise ValueError("ERR_MONTAGE_RUN_WRONG_KIND")
    items = await crud.list_bulk_generation_items(run_id)
    scenes = [_item_to_public(i) for i in items]
    return {
        "montage_run_id": run_id,
        "kind": KIND,
        "status": run.get("status"),
        "config": _loads(run.get("config_json"), {}),
        "total_scenes": len(scenes),
        "scenes": scenes,
        "status_counts": _count_statuses(scenes),
        "execution_supported": True,
        "credit_spend": False,
        "assembly_path": "DISCRETE_MONTAGE",
    }


async def bind_montage_scene_result(
    run_id: str,
    *,
    scene_id: str,
    media_id: str,
    result_kind: str = "video",
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Attach result identity to a durable scene job after canonical generate."""
    mid = str(media_id or "").strip()
    if not mid:
        raise ValueError("ERR_MONTAGE_MEDIA_REQUIRED")
    kind = str(result_kind or "video").strip().lower()
    if kind not in ("video", "image"):
        raise ValueError("ERR_MONTAGE_RESULT_KIND")

    await get_montage_discrete_run(run_id)  # validate
    items = await crud.list_bulk_generation_items(run_id)
    target = None
    for it in items:
        payload = _loads(it.get("payload_json"), {})
        if payload.get("scene_id") == scene_id or it.get("source_ref") == scene_id:
            target = it
            break
    if not target:
        raise ValueError("ERR_MONTAGE_SCENE_NOT_FOUND")

    payload = _loads(target.get("payload_json"), {})
    item_id = target["bulk_item_id"]
    if kind == "image":
        payload["image_media_id"] = mid
        if job_id:
            payload["image_job_id"] = job_id
        new_status = "IMAGE_BOUND"
        await crud.update_bulk_generation_item(
            item_id,
            status=new_status,
            media_id=mid,
            payload_json=json.dumps(payload),
            updated_at=_now(),
        )
    else:
        payload["video_media_id"] = mid
        if job_id:
            payload["video_job_id"] = job_id
        new_status = "RESULT_BOUND"
        await crud.update_bulk_generation_item(
            item_id,
            status=new_status,
            media_id=mid,
            job_id=job_id,
            payload_json=json.dumps(payload),
            completed_at=_now(),
            updated_at=_now(),
        )

    state = await get_montage_discrete_run(run_id)
    state["bound_scene_id"] = scene_id
    state["bound_media_id"] = mid
    state["bound_kind"] = kind
    state["bound_status"] = new_status
    return state



_TERMINAL_NO_GEN = frozenset(
    {
        "VIDEO_READY",
        "RESULT_BOUND",
        "SKIPPED_VIDEO",
        "BLOCKED",
        "PACKAGE_FAILED",
        "GENERATE_FAILED",
    }
)


def estimate_montage_generation_from_scenes(
    scenes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Count pending video generations for operator credit authorization."""
    pending: list[dict[str, Any]] = []
    for s in scenes:
        status = str(s.get("status") or "").upper()
        if s.get("video_media_id"):
            continue
        if status in _TERMINAL_NO_GEN:
            continue
        if not s.get("workspace_execution_package_id"):
            continue
        pending.append(s)
    n = len(pending)
    return {
        "expected_video_generations": n,
        "pending_scene_ids": [str(s.get("scene_id") or "") for s in pending],
        "pending_scenes": pending,
        "summary": f"{n} scenes → {n} video generations",
        "authorization_required": True,
        "credit_spend": False,
    }


async def estimate_montage_run_generation(run_id: str) -> dict[str, Any]:
    state = await get_montage_discrete_run(run_id)
    est = estimate_montage_generation_from_scenes(state["scenes"])
    est["montage_run_id"] = run_id
    est["run_status"] = state.get("status")
    est["total_scenes"] = state.get("total_scenes")
    return est


async def authorize_montage_run_generation(
    run_id: str,
    *,
    confirm_credit_burn: bool,
    expected_video_generations: int,
    dry_run: bool = True,
    generate_fn: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """M-04: explicit operator-authorized multi-scene generation.

    - Requires confirm_credit_burn=True
    - expected_video_generations must match pending count (fail-closed mismatch)
    - dry_run=True: authorization only, no generate boundary
    - dry_run=False: invoke generate_fn per pending scene, bind media when returned
    """
    if not confirm_credit_burn:
        raise ValueError("ERR_MONTAGE_CREDIT_CONFIRM_REQUIRED")

    estimate = await estimate_montage_run_generation(run_id)
    needed = int(estimate["expected_video_generations"])
    try:
        claimed = int(expected_video_generations)
    except (TypeError, ValueError) as exc:
        raise ValueError("ERR_MONTAGE_CREDIT_COUNT_INVALID") from exc
    if claimed != needed:
        raise ValueError(
            f"ERR_MONTAGE_CREDIT_COUNT_MISMATCH: claimed={claimed} needed={needed}"
        )

    if dry_run:
        return {
            **estimate,
            "ok": True,
            "authorized": True,
            "dry_run": True,
            "credit_spend": False,
            "dispatched": [],
            "detail": (
                f"Authorized dry-run: {estimate['summary']}. "
                "No generate boundary invoked."
            ),
        }

    if generate_fn is None:
        raise ValueError("ERR_MONTAGE_GENERATE_BOUNDARY_REQUIRED")

    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    product_id = str(cfg.get("product_id") or state.get("product_id") or "").strip()

    await crud.update_bulk_generation_run(
        run_id, status="GENERATING", updated_at=_now()
    )

    dispatched: list[dict[str, Any]] = []
    any_fail = False
    for scene in estimate["pending_scenes"]:
        scene_id = str(scene.get("scene_id") or "")
        mode = str(scene.get("transport_mode") or "F2V")
        prompt = str(
            scene.get("package_prompt")
            or scene.get("detail")
            or f"Montage scene {scene_id}"
        )
        entry: dict[str, Any] = {
            "scene_id": scene_id,
            "workspace_execution_package_id": scene.get(
                "workspace_execution_package_id"
            ),
            "mode": mode,
        }
        try:
            gen = await generate_fn(
                product_id=product_id,
                mode=mode,
                workspace_execution_package_id=scene.get(
                    "workspace_execution_package_id"
                ),
                prompt=prompt,
                scene_id=scene_id,
                start_asset=scene.get("start_asset_snapshot"),
                image_media_id=scene.get("image_media_id"),
            )
            media_id = str(
                gen.get("media_id") or gen.get("video_media_id") or ""
            ).strip() or None
            job_id = str(gen.get("job_id") or gen.get("id") or "").strip() or None
            entry["job_id"] = job_id
            entry["media_id"] = media_id
            if media_id:
                await bind_montage_scene_result(
                    run_id,
                    scene_id=scene_id,
                    media_id=media_id,
                    result_kind="video",
                    job_id=job_id,
                )
                entry["status"] = "RESULT_BOUND"
            else:
                items = await crud.list_bulk_generation_items(run_id)
                target = None
                for it in items:
                    payload = _loads(it.get("payload_json"), {})
                    if (
                        payload.get("scene_id") == scene_id
                        or it.get("source_ref") == scene_id
                    ):
                        target = it
                        break
                if target:
                    payload = _loads(target.get("payload_json"), {})
                    payload["video_job_id"] = job_id
                    payload["status"] = "VIDEO_SUBMITTED"
                    await crud.update_bulk_generation_item(
                        target["bulk_item_id"],
                        status="VIDEO_SUBMITTED",
                        job_id=job_id,
                        payload_json=json.dumps(payload),
                        updated_at=_now(),
                    )
                entry["status"] = "VIDEO_SUBMITTED"
            dispatched.append(entry)
        except Exception as exc:  # noqa: BLE001
            any_fail = True
            entry["status"] = "GENERATE_FAILED"
            entry["error"] = str(exc)[:400]
            dispatched.append(entry)
            try:
                items = await crud.list_bulk_generation_items(run_id)
                for it in items:
                    payload = _loads(it.get("payload_json"), {})
                    if (
                        payload.get("scene_id") == scene_id
                        or it.get("source_ref") == scene_id
                    ):
                        payload["error_code"] = "ERR_MONTAGE_GENERATE"
                        payload["detail"] = str(exc)[:400]
                        await crud.update_bulk_generation_item(
                            it["bulk_item_id"],
                            status="GENERATE_FAILED",
                            error="ERR_MONTAGE_GENERATE",
                            payload_json=json.dumps(payload),
                            updated_at=_now(),
                        )
                        break
            except Exception:  # noqa: BLE001
                pass

    final = await get_montage_discrete_run(run_id)
    bound = sum(
        1
        for s in final["scenes"]
        if s.get("video_media_id")
        or str(s.get("status") or "").upper() in ("RESULT_BOUND", "VIDEO_READY")
    )
    total = int(final.get("total_scenes") or 0)
    if bound >= total and total > 0 and not any_fail:
        run_status = "COMPLETE"
    elif bound or dispatched:
        run_status = "PARTIAL"
    else:
        run_status = "GENERATING"
    await crud.update_bulk_generation_run(run_id, status=run_status, updated_at=_now())
    final = await get_montage_discrete_run(run_id)

    return {
        **estimate,
        "ok": not any_fail,
        "authorized": True,
        "dry_run": False,
        "credit_spend": True,
        "dispatched": dispatched,
        "run": final,
        "detail": (
            f"Dispatched {len(dispatched)} generation(s) after operator credit confirm "
            f"({estimate['summary']})."
        ),
    }


def scene_jobs_to_readiness(
    scenes: Sequence[dict[str, Any]],
    *,
    product_media_id: Optional[str] = None,
) -> list[MontageSceneReadiness]:
    out: list[MontageSceneReadiness] = []
    for s in scenes:
        status = str(s.get("status") or "").upper()
        video_id = s.get("video_media_id") or (
            s.get("media_id") if status in ("RESULT_BOUND", "VIDEO_READY") else None
        )
        image_id = s.get("image_media_id")
        policy_raw = s.get("reference_policy") or s.get("policy_mode") or "PRODUCT_ANCHOR"
        try:
            policy = parse_scene_reference_policy(str(policy_raw))
        except ValueError:
            policy = SceneReferencePolicy.PRODUCT_ANCHOR
        video_ready = bool(video_id) and status in (
            "RESULT_BOUND",
            "VIDEO_READY",
            "GENERATE_RETURNED",
        )
        # Once a video result is bound, the image plate is satisfied for assembly
        # (image may have been product-start-frame without a separate image job).
        image_ready = (
            bool(image_id)
            or video_ready
            or status in ("IMAGE_BOUND", "IMAGE_READY", "PACKAGE_READY", "RESULT_BOUND", "VIDEO_READY")
        )
        pm = product_media_id or s.get("product_media_id") or "product-truth-bound"
        out.append(
            MontageSceneReadiness(
                scene_id=str(s.get("scene_id") or ""),
                mandatory=True,
                reference_policy=policy,
                product_media_id=str(pm) if pm else None,
                clip_media_id=video_id if video_ready else None,
                image_ready=image_ready,
                video_ready=video_ready,
                dialogue_required=False,
                dialogue_text=s.get("dialogue"),
                image_generation_required=True,
                video_generation_required=True,
            )
        )
    return out


async def readiness_from_montage_run(run_id: str) -> dict[str, Any]:
    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    scenes = scene_jobs_to_readiness(
        state["scenes"], product_media_id=cfg.get("product_media_id")
    )
    report = assess_montage_assembly_readiness(scenes)
    return {
        "montage_run_id": run_id,
        "ok": report.ok,
        "code": report.code,
        "detail": report.detail,
        "blockers": report.blockers,
        "ready_scene_ids": report.ready_scene_ids,
        "clip_media_ids": report.clip_media_ids,
        "scenes": state["scenes"],
        "assembly_path": "DISCRETE_MONTAGE",
    }


async def assemble_from_montage_run(
    run_id: str,
    *,
    concat_fn: Callable[..., Awaitable[dict[str, Any]]],
    dry_run: bool = True,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """M-03 path from durable run: readiness → gated concat."""
    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    scenes = scene_jobs_to_readiness(
        state["scenes"], product_media_id=cfg.get("product_media_id")
    )
    result = await assemble_montage_discrete(
        scenes,
        concat_fn=concat_fn,
        job_id=job_id or f"montage-run-{run_id[:8]}",
        dry_run=dry_run,
    )
    result["montage_run_id"] = run_id
    return result


def _scene_payload(
    state: SceneJobState, *, product_media_id: Optional[str]
) -> dict[str, Any]:
    d = state.to_dict()
    d["product_media_id"] = product_media_id
    return d


def _item_to_public(item: dict[str, Any]) -> dict[str, Any]:
    payload = _loads(item.get("payload_json"), {})
    status = str(item.get("status") or payload.get("status") or "PLANNED")
    video_media = payload.get("video_media_id")
    image_media = payload.get("image_media_id")
    if status in ("RESULT_BOUND", "VIDEO_READY") and not video_media:
        video_media = item.get("media_id")
    if status == "IMAGE_BOUND" and not image_media:
        image_media = item.get("media_id")
    return {
        "bulk_item_id": item.get("bulk_item_id"),
        "scene_id": payload.get("scene_id") or item.get("source_ref"),
        "beat_id": payload.get("beat_id"),
        "block_index": payload.get("block_index"),
        "route": payload.get("route"),
        "transport_mode": payload.get("transport_mode"),
        "source_mode": payload.get("source_mode"),
        "reference_policy": payload.get("reference_policy"),
        "status": status,
        "workspace_execution_package_id": payload.get("workspace_execution_package_id"),
        "package_prompt": payload.get("package_prompt"),
        "start_asset_snapshot": payload.get("start_asset_snapshot"),
        "image_job_id": payload.get("image_job_id"),
        "image_media_id": image_media,
        "video_job_id": payload.get("video_job_id") or item.get("job_id"),
        "video_media_id": video_media,
        "error_code": item.get("error") or payload.get("error_code"),
        "detail": payload.get("detail") or "",
        "product_media_id": payload.get("product_media_id"),
    }


def _count_statuses(scenes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scenes:
        st = str(s.get("status") or "?")
        counts[st] = counts.get(st, 0) + 1
    return counts


def report_to_durable_preview(report: MontageOrchestrationReport) -> dict[str, Any]:
    """Helper for tests — shape without DB."""
    return {
        "ok": report.ok,
        "scenes": [s.to_dict() for s in report.scenes],
        "credit_spend": report.credit_spend,
    }
