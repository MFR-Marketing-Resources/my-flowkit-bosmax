"""Montage durable discrete run ledger (M-02).

Persists beat → scene job lifecycle on existing bulk_generation_run/item tables
(kind=MONTAGE_DISCRETE). Orchestration reuses montage_scene_orchestrator →
canonical workspace package factory. Result identity via bind_scene_result.

No second video engine. No DOM lane. Credit fire is never automatic.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Sequence

from agent.db import crud
from agent.services.montage_assembly_readiness import (
    BLOCKED_INCOMPLETE_SCENE_SET,
    MontageAssemblyError,
    MontageSceneReadiness,
    assess_montage_assembly_readiness,
)
from agent.services.montage_discrete_assembly import (
    assemble_montage_discrete,
    validate_final_edit_cadence,
)
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

MONTAGE_SCHEDULER_POLL_SECONDS = 5.0
MONTAGE_ASSEMBLY_CLAIM_SECONDS = 35 * 60
_MONTAGE_SCHEDULER_LOCK = asyncio.Lock()
logger = logging.getLogger(__name__)


def _resolve_montage_single_settings(
    model: str | None,
    duration_seconds: int | None,
) -> tuple[str, int]:
    """Resolve the operator tuple through the shared capability authority."""
    model_label = str(model or "").strip()
    try:
        duration = int(duration_seconds) if duration_seconds is not None else 0
    except (TypeError, ValueError) as exc:
        raise ValueError("ERR_MONTAGE_MODEL_DURATION_REQUIRED") from exc
    if not model_label or duration <= 0:
        raise ValueError("ERR_MONTAGE_MODEL_DURATION_REQUIRED")

    from agent.services import video_capability_matrix

    valid, code = video_capability_matrix.validate_single(
        "GOOGLE_FLOW", model_label, duration
    )
    if not valid:
        raise ValueError(f"ERR_MONTAGE_{code}")
    return model_label, duration


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


async def load_montage_execution_identity(
    workspace_execution_package_id: str | None,
) -> dict[str, Any] | None:
    """Load the immutable Faceless identity persisted with a Montage package.

    The identity is package lineage, not scene-local input. Returning ``None``
    when it is absent keeps the canonical Flow gate fail-closed instead of
    allowing a Montage builder to invent or silently downgrade the identity.
    """
    package_id = str(workspace_execution_package_id or "").strip()
    if not package_id:
        return None
    package = await crud.get_workspace_execution_package(package_id)
    if not isinstance(package, dict):
        return None

    identity = package.get("faceless_execution_identity")
    if isinstance(identity, str):
        identity = _loads(identity, None)
    if not isinstance(identity, dict):
        lineage = _loads(package.get("request_lineage_payload"), {})
        identity = lineage.get("faceless_execution_identity") if isinstance(lineage, dict) else None
    return copy.deepcopy(identity) if isinstance(identity, dict) else None


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
    model: str | None = None,
    duration_seconds: int | None = None,
    copy_v2_context: dict[str, Any] | None = None,
    mascot_start_asset: Optional[dict[str, Any]] = None,
    mascot_scene_context: Optional[str] = None,
    mascot_block_count: Optional[int] = None,
    mascot_atomic_seconds: Optional[int] = None,
    mascot_has_dialogue: bool = True,
    faceless_resolution: Optional[dict[str, Any]] = None,
    staff_id: str | None = None,
    staff_display_name_snapshot: str | None = None,
    treatment_block_plan: Optional[dict[str, Any]] = None,
    creative_treatment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Orchestrate packages and persist a durable run + per-scene jobs."""
    pid = str(product_id or "").strip()
    if not pid:
        raise ValueError("ERR_MONTAGE_PRODUCT_REQUIRED")
    if not story_beats:
        raise ValueError("ERR_MONTAGE_BEATS_REQUIRED")

    # Resolve Hook/Background canonically — never compile raw AUTO into scene direction
    from agent.services.creative_lane_settings_service import (
        resolve_background as _resolve_bg,
        resolve_hook as _resolve_hook,
    )

    hook_res = _resolve_hook(hook_id)
    bg_res = _resolve_bg(background_id)
    resolved_hook_id = str(hook_res.get("setting_id") or hook_id)
    resolved_bg_id = str(bg_res.get("setting_id") or background_id)
    hook_label = str(hook_res.get("display_label") or resolved_hook_id)
    bg_label = str(bg_res.get("display_label") or resolved_bg_id)

    context_bits = [
        f"HOOK: {hook_label} (resolved={resolved_hook_id}; {hook_res.get('resolution')})",
        f"BACKGROUND: {bg_label} (resolved={resolved_bg_id}; {bg_res.get('resolution')})",
        "Montage discrete clips — one short SINGLE clip per scene; no native extend.",
    ]
    if scene_context_override:
        context_bits.append(str(scene_context_override).strip())
    composed_context = "\n".join(context_bits)

    model_label, dur = _resolve_montage_single_settings(model, duration_seconds)
    treatment_segments: list[dict[str, Any]] = []
    if str((treatment_block_plan or {}).get("generation_mode") or "SINGLE").upper() == "EXTEND":
        treatment_segments = copy.deepcopy((treatment_block_plan or {}).get("segments") or [])
        hashes = [str(segment.get("segment_sha256") or "") for segment in treatment_segments]
        if (
            len(treatment_segments) != len(story_beats)
            or len(treatment_segments) != int((treatment_block_plan or {}).get("segment_count") or 0)
            or hashes != list((treatment_block_plan or {}).get("ordered_segment_sha256s") or [])
            or any(int(segment.get("duration_seconds") or 0) != dur for segment in treatment_segments)
        ):
            raise ValueError("ERR_MONTAGE_TREATMENT_BLOCK_PLAN_INVALID")

    effective_package_factory = package_factory
    if treatment_segments:
        segment_iter = iter(treatment_segments)

        async def _segment_package_factory(**kwargs: Any) -> dict[str, Any]:
            segment = next(segment_iter)
            scoped = copy.deepcopy(creative_treatment or {})
            scoped.update({
                "master_generation_mode": "EXTEND",
                "generation_mode": "SINGLE",
                "duration_seconds": segment["duration_seconds"],
                "action_sequence": segment.get("action_sequence") or [],
                "shot_grammar": segment.get("shot_grammar") or [],
                "dialogue_text": segment.get("exact_dialogue_slice") or "",
                "active_segment": copy.deepcopy(segment),
                "segment_plan": copy.deepcopy(treatment_block_plan),
            })
            return await package_factory(**kwargs, creative_treatment=scoped)

        effective_package_factory = _segment_package_factory
    mascot_duration_plan: dict[str, Any] | None = None
    if mascot_start_asset is not None or mascot_block_count:
        from agent.services.montage_mascot_creative_grammar import (
            resolve_final_duration_plan,
        )

        final_seconds = dur * int(mascot_block_count or len(story_beats))
        mascot_duration_plan = resolve_final_duration_plan(
            final_seconds,
            engine="GOOGLE_FLOW",
            language="BM_MS",
            wps_mode="SWEET",
        ).to_dict()

    report = await orchestrate_montage_scenes(
        product_id=pid,
        staff_id=staff_id,
        staff_display_name_snapshot=staff_display_name_snapshot,
        story_beats=story_beats,
        package_factory=effective_package_factory,
        default_policy=default_policy,
        per_beat_policy=per_beat_policy,
        product_media_id=product_media_id,
        generate_fn=None,
        scene_context_override=composed_context,
        copy_fallback_confirmed=copy_fallback_confirmed,
        model=model_label,
        duration_seconds=dur,
        copy_v2_context=copy_v2_context,
        mascot_start_asset=mascot_start_asset,
        mascot_scene_context=mascot_scene_context,
        mascot_block_count=mascot_block_count,
        mascot_atomic_seconds=mascot_atomic_seconds,
        mascot_has_dialogue=mascot_has_dialogue,
        faceless_resolution=faceless_resolution,
    )

    run_id = str(uuid.uuid4())
    policy_val = (
        default_policy.value
        if isinstance(default_policy, SceneReferencePolicy)
        else str(default_policy)
    )
    config = {
        "product_id": pid,
        "staff_id": staff_id,
        "staff_display_name": staff_display_name_snapshot,
        "product_media_id": product_media_id,
        "default_policy": policy_val,
        "per_beat_policy": per_beat_policy or {},
        "hook_id": hook_id,
        "background_id": background_id,
        "hook_resolved": {
            "selected_id": hook_id,
            "setting_id": resolved_hook_id,
            "display_label": hook_label,
            "resolution": hook_res.get("resolution"),
        },
        "background_resolved": {
            "selected_id": background_id,
            "setting_id": resolved_bg_id,
            "display_label": bg_label,
            "resolution": bg_res.get("resolution"),
        },
        "model": model_label,
        "duration_seconds": dur,
        "scene_context_override": scene_context_override,
        "orchestration_ok": report.ok,
        "copy_architecture_v2": next(
            (
                scene.copy_architecture_v2
                for scene in report.scenes
                if scene.copy_architecture_v2
            ),
            None,
        ),
        # Montage keeps its own surface identity while persisting the exact
        # product scaffold/custody receipt used by the shared package factory.
        # This is the restart/audit source of truth; it is never a provider
        # reference and never a user-facing T2V surface selection.
        "surface_lane": "MONTAGE",
        "faceless_resolution": faceless_resolution,
        "treatment_block_plan": (
            copy.deepcopy(treatment_block_plan)
            if isinstance(treatment_block_plan, dict)
            else None
        ),
        "exact_product_video": (
            faceless_resolution.get("exact_product_video")
            if isinstance(faceless_resolution, dict)
            else None
        ),
        "final_edit_cadence": (
            {
                "segment_count": mascot_duration_plan["final_edit_segment_count"],
                "segments": mascot_duration_plan["final_edit_segments"],
                "internal_final_edit_only": True,
            }
            if mascot_duration_plan
            else None
        ),
    }
    await crud.create_bulk_generation_run(
        run_id,
        kind=KIND,
        staff_id=staff_id,
        staff_display_name_snapshot=staff_display_name_snapshot,
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
    for scene_index, state in enumerate(report.scenes):
        item_id = str(uuid.uuid4())
        payload = _scene_payload(
            state,
            product_media_id=product_media_id,
            treatment_block_plan=(
                treatment_block_plan if treatment_segments else None
            ),
            treatment_segment=(
                treatment_segments[scene_index]
                if scene_index < len(treatment_segments)
                else None
            ),
        )
        await crud.create_bulk_generation_item(
            item_id,
            bulk_run_id=run_id,
            staff_id=staff_id,
            staff_display_name_snapshot=staff_display_name_snapshot,
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
        "copy_architecture_v2": config.get("copy_architecture_v2"),
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


def _has_transportable_plate(scene: dict[str, Any]) -> bool:
    if scene.get("image_media_id"):
        return True
    snapshot = scene.get("start_asset_snapshot")
    if not isinstance(snapshot, dict):
        return False
    return bool(
        snapshot.get("mediaId")
        or snapshot.get("media_id")
        or snapshot.get("downloadUrl")
        or snapshot.get("download_url")
        or snapshot.get("previewUrl")
        or snapshot.get("preview_url")
        or snapshot.get("localFilePath")
        or snapshot.get("local_file_path")
    )


def _is_provider_free_identity_failure(
    item: dict[str, Any], payload: dict[str, Any]
) -> bool:
    """Recognize only the known pre-provider identity wiring failure.

    This guard is deliberately narrower than a generic failed-scene retry. Any
    provider handle, media target, generation count, or retry history makes the
    item ineligible, so accepted/uncertain provider work remains fail-closed.
    """
    if str(item.get("status") or "").upper() != "GENERATE_FAILED":
        return False
    if str(item.get("error") or "") != "ERR_MONTAGE_GENERATE":
        return False
    detail = str(payload.get("detail") or payload.get("error") or "")
    if "FACELESS_EXECUTION_IDENTITY_REQUIRED" not in detail:
        return False

    provider_fields = (
        "provider_job_id",
        "video_job_id",
        "job_id",
        "provider_identity",
        "provider_operation_ids",
        "direct_media_targets",
        "video_media_id",
        "media_id",
    )
    if item.get("job_id") or item.get("media_id"):
        return False
    if any(payload.get(field) for field in provider_fields):
        return False
    try:
        submit_count = int(payload.get("provider_generation_submit_count") or 0)
        retry_count = int(item.get("retry_count") or 0)
    except (TypeError, ValueError):
        return False
    return submit_count == 0 and retry_count == 0


async def recover_provider_free_montage_failures(run_id: str) -> list[str]:
    """Restore only known pre-submit Montage failures to the durable work queue.

    The server-owned worker uses this transition after a code-only gate repair.
    It never resets a provider-touched row and does not increment retry_count;
    the original failure is retained in ``pre_provider_recovery`` for audit.
    """
    recovered: list[str] = []
    items = await crud.list_bulk_generation_items(run_id)
    for item in items:
        payload = _loads(item.get("payload_json"), {})
        if not isinstance(payload, dict) or not _is_provider_free_identity_failure(item, payload):
            continue
        scene_id = str(payload.get("scene_id") or item.get("source_ref") or "").strip()
        if not scene_id or not payload.get("workspace_execution_package_id"):
            continue
        failure_detail = str(payload.get("detail") or payload.get("error") or "")[:400]
        updated_payload = {
            **payload,
            "status": "PACKAGE_READY",
            "detail": "",
            "error_code": None,
            "provider_identity": {},
            "provider_generation_submit_count": 0,
            "provider_resubmission": False,
            "resubmission_allowed": False,
            "pre_provider_recovery": {
                "error_code": "FACELESS_EXECUTION_IDENTITY_REQUIRED",
                "detail": failure_detail,
                "recovered_at": _now(),
                "provider_generation_submit_count": 0,
                "provider_resubmission": False,
            },
        }
        for key in (
            "next_action",
            "next_poll_at",
            "poll_deadline_at",
            "poll_backoff_s",
            "poll_attempts",
            "last_poll_status",
        ):
            updated_payload.pop(key, None)
        await crud.update_bulk_generation_item(
            item["bulk_item_id"],
            status="PACKAGE_READY",
            job_id=None,
            media_id=None,
            retry_count=0,
            error=None,
            payload_json=json.dumps(updated_payload),
            completed_at=None,
            updated_at=_now(),
        )
        recovered.append(scene_id)
    return recovered


def estimate_montage_generation_from_scenes(
    scenes: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Count pending provider ops for operator credit authorization.

    Includes pending scene-image work (IMAGE_FIRST without bound image) plus
    pending video generations. Already-bound images/videos are not counted again.
    """
    pending_video: list[dict[str, Any]] = []
    pending_image: list[dict[str, Any]] = []
    for s in scenes:
        status = str(s.get("status") or "").upper()
        if status in _TERMINAL_NO_GEN:
            continue
        # Image ops: IMAGE_FIRST-ish without a bound/transportable plate.
        needs_image = (
            str(s.get("route") or "").upper() == "IMAGE_FIRST"
            and not _has_transportable_plate(s)
            and status not in _TERMINAL_NO_GEN
        )
        if needs_image:
            pending_image.append(s)
        if s.get("video_media_id"):
            continue
        if status in _TERMINAL_NO_GEN:
            continue
        # A missing package is still a pending video operation once the
        # package/plate boundary is repaired; do not undercount it.
        pending_video.append(s)
    nv = len(pending_video)
    ni = len(pending_image)
    total = ni + nv
    summary = (
        f"{ni} pending scene image(s) + {nv} pending scene video(s)"
        f" = {total} provider operation(s)"
        if ni
        else f"{nv} pending scene video(s) = {total} provider operation(s)"
    )
    return {
        "expected_video_generations": nv,
        "expected_image_operations": ni,
        "expected_provider_operations": ni + nv,
        "pending_scene_ids": [str(s.get("scene_id") or "") for s in pending_video],
        "pending_image_scene_ids": [str(s.get("scene_id") or "") for s in pending_image],
        "pending_scenes": pending_video,
        "pending_image_scenes": pending_image,
        "summary": summary,
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


async def build_montage_manifest_items(run_id: str) -> dict[str, Any]:
    """Derive the per-scene Approved Generation Manifest items with the SAME
    derivation the authorize-generation run loop uses (mode / prompt / model /
    duration / product), so each approved item's execution-envelope hash matches
    the scene's dispatch EXACTLY. A montage dispatch binds on the stable envelope
    (prompt + settings + product); the volatile per-session Flow media id never
    enters the hash (see make_video.start_generate manifest asset rule).
    Provider-free — no scene is generated here."""
    estimate = await estimate_montage_run_generation(run_id)
    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    product_id = str(cfg.get("product_id") or state.get("product_id") or "").strip() or None
    model, duration_s = _resolve_montage_single_settings(
        cfg.get("model"), cfg.get("duration_seconds")
    )
    items: list[dict[str, Any]] = []
    for scene in estimate["pending_scenes"]:
        scene_id = str(scene.get("scene_id") or "")
        mode = str(scene.get("transport_mode") or "F2V")
        prompt = str(
            scene.get("package_prompt")
            or scene.get("detail")
            or f"Montage scene {scene_id}"
        )
        items.append({
            "item_key": scene_id,
            "mode": mode,
            "final_prompt_text": prompt,
            "product_id": product_id,
            # Preserve the scene's source lineage (e.g. FRAMES for a mascot
            # start-frame scene) — the run loop threads scene.source_mode into the
            # dispatch, so the frozen item must carry it too or the canonical
            # envelope SHA won't match (FRAMES locks explicit assets; non-FRAMES
            # product-backed resolves the product-visual SHA).
            "source_mode": scene.get("source_mode"),
            "model": model,
            "aspect": "9:16",
            "duration_s": duration_s,
            "count": 1,
        })
    return {
        "product_id": product_id,
        "items": items,
        "pending_scene_count": len(items),
    }


async def authorize_montage_run_generation(
    run_id: str,
    *,
    confirm_credit_burn: bool,
    expected_video_generations: int,
    expected_provider_operations: int | None = None,
    dry_run: bool = True,
    generate_fn: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    poll_fn: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
    max_polls: int = 120,
    poll_interval_s: float = 5.0,
    async_worker: bool = False,
    staff_id: str | None = None,
    staff_display_name_snapshot: str | None = None,
    manifest_id: str | None = None,
    origin_surface_lane: str | None = None,
    origin_request_id_prefix: str | None = None,
    origin_project_id: str | None = None,
) -> dict[str, Any]:
    """M-04: explicit operator-authorized multi-scene generation.

    Single-flight serial loop. With ``async_worker=True`` it submits at most one
    scene, persists its poll lease/backoff/deadline, and returns immediately;
    ``resume_montage_run`` performs one poll-only reconciliation later. This
    prevents a request from holding a tight provider polling loop or resubmitting
    a job after a process restart.
    """
    if not confirm_credit_burn:
        raise ValueError("ERR_MONTAGE_CREDIT_CONFIRM_REQUIRED")

    estimate = await estimate_montage_run_generation(run_id)
    needed = int(estimate["expected_video_generations"])
    needed_provider = int(estimate["expected_provider_operations"])
    try:
        claimed = int(expected_video_generations)
    except (TypeError, ValueError) as exc:
        raise ValueError("ERR_MONTAGE_CREDIT_COUNT_INVALID") from exc
    if claimed != needed:
        raise ValueError(
            f"ERR_MONTAGE_CREDIT_COUNT_MISMATCH: claimed={claimed} needed={needed}"
        )
    if expected_provider_operations is None:
        raise ValueError("ERR_MONTAGE_PROVIDER_COUNT_REQUIRED")
    try:
        claimed_provider = int(expected_provider_operations)
    except (TypeError, ValueError) as exc:
        raise ValueError("ERR_MONTAGE_PROVIDER_COUNT_INVALID") from exc
    if claimed_provider != needed_provider:
        raise ValueError(
            "ERR_MONTAGE_PROVIDER_COUNT_MISMATCH: "
            f"claimed={claimed_provider} needed={needed_provider}"
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

    if int(estimate.get("expected_image_operations") or 0) > 0:
        raise ValueError(
            "ERR_MONTAGE_IMAGE_BOUNDARY_REQUIRED: bind or prepare every scene "
            "image plate before video dispatch"
        )

    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    persisted_staff_id = str(cfg.get("staff_id") or "").strip()
    if not persisted_staff_id:
        raise ValueError("STAFF_IDENTITY_REQUIRED")
    if persisted_staff_id != str(staff_id or "").strip():
        raise ValueError("STAFF_IDENTITY_MISMATCH")
    product_id = str(cfg.get("product_id") or state.get("product_id") or "").strip()
    model, duration_s = _resolve_montage_single_settings(
        cfg.get("model"), cfg.get("duration_seconds")
    )

    # The API request that originally held the approved manifest callback may
    # disappear on restart. Persist the authorization context needed by the
    # server-owned worker before it returns from the first submit.
    worker_config = dict(cfg)
    worker_config.update({
        "async_worker_authorized": bool(async_worker),
        "approved_manifest_id": manifest_id or cfg.get("approved_manifest_id"),
        "authorized_expected_video_generations": needed,
        "authorized_expected_provider_operations": needed_provider,
        "worker_poll_interval_s": float(poll_interval_s or 5.0),
        "authorized_at": _now(),
        "origin_surface_lane": (
            str(origin_surface_lane or cfg.get("origin_surface_lane") or "MONTAGE")
            .strip()
            .upper()
        ),
        "origin_request_id_prefix": (
            str(
                origin_request_id_prefix
                or cfg.get("origin_request_id_prefix")
                or f"montage:{run_id}"
            ).strip()
        ),
        "origin_project_id": (
            str(origin_project_id or cfg.get("origin_project_id") or "").strip()
            or None
        ),
    })

    await crud.update_bulk_generation_run(
        run_id,
        status="GENERATING",
        config_json=json.dumps(worker_config),
        updated_at=_now(),
    )

    async def _mark_scene(scene_id: str, *, status: str, **extra: Any) -> None:
        items = await crud.list_bulk_generation_items(run_id)
        for it in items:
            payload = _loads(it.get("payload_json"), {})
            if payload.get("scene_id") == scene_id or it.get("source_ref") == scene_id:
                payload.update(extra)
                payload["status"] = status
                await crud.update_bulk_generation_item(
                    it["bulk_item_id"],
                    status=status,
                    job_id=extra.get("video_job_id") or it.get("job_id"),
                    payload_json=json.dumps(payload),
                    error=extra.get("error_code"),
                    updated_at=_now(),
                )
                return

    dispatched: list[dict[str, Any]] = []
    any_fail = False
    active_job: Optional[str] = None

    for scene in estimate["pending_scenes"]:
        # Single-flight invariant: never submit while previous job active
        if active_job is not None:
            any_fail = True
            dispatched.append(
                {
                    "scene_id": str(scene.get("scene_id") or ""),
                    "status": "BLOCKED_SINGLE_FLIGHT",
                    "error": f"previous job still active: {active_job}",
                }
            )
            break

        scene_id = str(scene.get("scene_id") or "")
        # Resume: skip if already bound (ledger re-read)
        fresh = await get_montage_discrete_run(run_id)
        already = next(
            (
                s
                for s in fresh["scenes"]
                if str(s.get("scene_id") or "") == scene_id and s.get("video_media_id")
            ),
            None,
        )
        if already:
            dispatched.append(
                {
                    "scene_id": scene_id,
                    "status": "SKIPPED_ALREADY_BOUND",
                    "media_id": already.get("video_media_id"),
                }
            )
            continue

        mode = str(scene.get("transport_mode") or "F2V")
        if not scene.get("workspace_execution_package_id"):
            raise ValueError(
                f"ERR_MONTAGE_PACKAGE_REQUIRED:{scene_id}"
            )
        if not _has_transportable_plate(scene) and str(scene.get("route") or "").upper() == "IMAGE_FIRST":
            raise ValueError(f"ERR_MONTAGE_IMAGE_REQUIRED:{scene_id}")
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
            "model": model,
            "duration_s": duration_s,
        }
        try:
            gen = await generate_fn(
                product_id=product_id,
                mode=mode,
                # Preserve the scene's source lineage (e.g. FRAMES for a mascot
                # start-frame scene) so the flow product-visual gate applies its
                # existing FRAMES exemption instead of overwriting the operator
                # start asset with the Official Product Visual.
                source_mode=scene.get("source_mode"),
                workspace_execution_package_id=scene.get(
                    "workspace_execution_package_id"
                ),
                prompt=prompt,
                scene_id=scene_id,
                start_asset=scene.get("start_asset_snapshot"),
                image_media_id=scene.get("image_media_id"),
                model=model,
                duration_s=duration_s,
            )
            media_id = str(
                gen.get("media_id") or gen.get("video_media_id") or ""
            ).strip() or None
            job_id = str(gen.get("job_id") or gen.get("id") or "").strip() or None
            entry["job_id"] = job_id
            entry["media_id"] = media_id
            active_job = job_id

            provider_identity = {
                **(
                    gen.get("provider_identity")
                    if isinstance(gen.get("provider_identity"), dict)
                    else {}
                ),
                "provider_job_id": job_id,
                "provider_generation_submit_count": 1,
                "generation_resubmission_allowed": False,
            }
            for identity_key in (
                "provider_operation_ids",
                "direct_media_targets",
                "generation_identity",
            ):
                if gen.get(identity_key) is not None:
                    provider_identity[identity_key] = gen.get(identity_key)
            # The canonical SINGLE row may already have captured the direct
            # provider target by the time the generate boundary returns. Copy
            # that identity into the Montage item as an audit convenience; the
            # SINGLE row remains the authoritative recovery source.
            if job_id and str(job_id).startswith("g_"):
                try:
                    from agent.services import make_video as _make_video

                    memory_identity = _make_video.get_job(job_id) or {}
                    durable_row = await crud.get_video_production_job(job_id)
                    durable_state = _loads(
                        (durable_row or {}).get("stage_state_json"), {}
                    )
                    for source in (memory_identity, durable_state):
                        if not isinstance(source, dict):
                            continue
                        for identity_key in (
                            "provider_operation_ids",
                            "direct_media_targets",
                            "generation_identity",
                        ):
                            if source.get(identity_key) is not None:
                                provider_identity[identity_key] = source.get(identity_key)
                except Exception:  # noqa: BLE001 — item still has the durable g_ id
                    pass

            await _mark_scene(
                scene_id,
                status="VIDEO_SUBMITTED",
                video_job_id=job_id,
                provider_job_id=job_id,
                provider_identity=provider_identity,
            )

            if async_worker and not media_id and job_id:
                deadline = datetime.now(timezone.utc) + timedelta(minutes=30)
                await _mark_scene(
                    scene_id,
                    status="VIDEO_SUBMITTED",
                    video_job_id=job_id,
                    provider_job_id=job_id,
                    async_worker=True,
                    poll_attempts=0,
                    next_poll_at=_now(),
                    poll_deadline_at=deadline.replace(microsecond=0).isoformat().replace(
                        "+00:00", "Z"
                    ),
                    poll_backoff_s=max(5.0, float(poll_interval_s or 5.0)),
                    next_action="POLL",
                    resubmission_allowed=False,
                    provider_generation_submit_count=1,
                )
                entry.update({
                    "status": "VIDEO_SUBMITTED",
                    "async_worker": True,
                    "next_action": "POLL",
                    "resubmission_allowed": False,
                    "next_poll_at": _now(),
                })
                dispatched.append(entry)
                await crud.update_bulk_generation_run(
                    run_id, status="GENERATING", updated_at=_now()
                )
                final = await get_montage_discrete_run(run_id)
                return {
                    **estimate,
                    "ok": True,
                    "authorized": True,
                    "dry_run": False,
                    "credit_spend": True,
                    "provider_generation_submits": 1,
                    "async_worker": True,
                    "next_action": "POLL",
                    "dispatched": dispatched,
                    "run": final,
                    "detail": (
                        f"Scene {scene_id} submitted once; durable worker will poll "
                        "without resubmission."
                    ),
                }

            # Async semantics: if no immediate media, poll to terminal before next scene
            if not media_id and job_id and poll_fn is not None:
                import asyncio

                terminal = False
                for _ in range(max(1, int(max_polls))):
                    if poll_interval_s and poll_interval_s > 0:
                        await asyncio.sleep(float(poll_interval_s))
                    polled = await poll_fn(job_id)
                    st = str(
                        polled.get("status") or polled.get("state") or ""
                    ).upper()
                    entry["poll_status"] = st
                    if st in ("DONE", "COMPLETED", "SUCCESS"):
                        media_id = str(
                            polled.get("media_id")
                            or polled.get("video_media_id")
                            or ""
                        ).strip() or None
                        entry["media_id"] = media_id
                        terminal = True
                        break
                    if st in ("FAILED", "ERROR", "GENERATED_BUT_UNRETRIEVED"):
                        any_fail = True
                        entry["status"] = "GENERATE_FAILED"
                        entry["error"] = str(polled.get("error") or st)[:400]
                        await _mark_scene(
                            scene_id,
                            status="GENERATE_FAILED",
                            error_code="ERR_MONTAGE_GENERATE",
                            detail=entry["error"],
                            video_job_id=job_id,
                        )
                        dispatched.append(entry)
                        active_job = None
                        # fail-closed: stop remaining scenes
                        await crud.update_bulk_generation_run(
                            run_id, status="PARTIAL", updated_at=_now()
                        )
                        final = await get_montage_discrete_run(run_id)
                        return {
                            **estimate,
                            "ok": False,
                            "authorized": True,
                            "dry_run": False,
                            "credit_spend": True,
                            "dispatched": dispatched,
                            "run": final,
                            "detail": f"Scene {scene_id} failed — remaining scenes not submitted.",
                        }
                if not terminal and not media_id:
                    any_fail = True
                    entry["status"] = "GENERATE_FAILED"
                    entry["error"] = "ERR_MONTAGE_POLL_TIMEOUT"
                    await _mark_scene(
                        scene_id,
                        status="GENERATE_FAILED",
                        error_code="ERR_MONTAGE_POLL_TIMEOUT",
                        video_job_id=job_id,
                    )
                    dispatched.append(entry)
                    active_job = None
                    break

            if media_id:
                await bind_montage_scene_result(
                    run_id,
                    scene_id=scene_id,
                    media_id=media_id,
                    result_kind="video",
                    job_id=job_id,
                )
                entry["status"] = "RESULT_BOUND"
            elif job_id and poll_fn is None:
                # Caller returned SUBMITTED only (tests may bind immediately via media_id)
                entry["status"] = "VIDEO_SUBMITTED"
            active_job = None
            dispatched.append(entry)
        except Exception as exc:  # noqa: BLE001
            any_fail = True
            active_job = None
            entry["status"] = "GENERATE_FAILED"
            entry["error"] = str(exc)[:400]
            dispatched.append(entry)
            try:
                await _mark_scene(
                    scene_id,
                    status="GENERATE_FAILED",
                    error_code="ERR_MONTAGE_GENERATE",
                    detail=str(exc)[:400],
                )
            except Exception:  # noqa: BLE001
                pass
            # fail-closed — do not continue to next scene
            break

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
            f"Serial dispatch {len(dispatched)} scene(s) after operator credit confirm "
            f"({estimate['summary']})."
        ),
    }


async def resume_montage_run(
    run_id: str,
    *,
    poll_fn: Callable[[str], Awaitable[dict[str, Any]]],
    max_items: int = 1,
    generate_fn: Optional[Callable[..., Awaitable[dict[str, Any]]]] = None,
) -> dict[str, Any]:
    """Reconcile active Montage scene jobs with bounded provider calls.

    The durable item already owns the provider job id. Polling never creates a
    new provider job. When a server-owned worker supplies ``generate_fn``, the
    next scene is dispatched only after the current scene's ``RESULT_BOUND``
    update has committed.
    """
    if poll_fn is None:
        raise ValueError("ERR_MONTAGE_POLL_BOUNDARY_REQUIRED")
    state = await get_montage_discrete_run(run_id)
    items = await crud.list_bulk_generation_items(run_id)
    now_dt = datetime.now(timezone.utc)
    reconciled: list[dict[str, Any]] = []
    provider_calls = 0
    bound_any = False

    for item in items:
        if len(reconciled) >= max(1, int(max_items or 1)):
            break
        status = str(item.get("status") or "").upper()
        payload = _loads(item.get("payload_json"), {})
        if status not in ("VIDEO_SUBMITTED", "GENERATING", "VIDEO_POLLING"):
            continue
        job_id = str(
            payload.get("provider_job_id")
            or payload.get("video_job_id")
            or item.get("job_id")
            or ""
        ).strip()
        scene_id = str(payload.get("scene_id") or item.get("source_ref") or "")
        if not job_id:
            await crud.update_bulk_generation_item(
                item["bulk_item_id"],
                status="GENERATE_FAILED",
                error="ERR_MONTAGE_PROVIDER_JOB_ID_MISSING",
                updated_at=_now(),
            )
            reconciled.append({
                "scene_id": scene_id,
                "status": "GENERATE_FAILED",
                "error": "ERR_MONTAGE_PROVIDER_JOB_ID_MISSING",
            })
            continue

        next_poll_raw = payload.get("next_poll_at")
        if next_poll_raw:
            try:
                next_poll_dt = datetime.fromisoformat(
                    str(next_poll_raw).replace("Z", "+00:00")
                )
                if next_poll_dt > now_dt:
                    continue
            except (TypeError, ValueError):
                pass
        deadline_raw = payload.get("poll_deadline_at")
        if deadline_raw:
            try:
                deadline_dt = datetime.fromisoformat(
                    str(deadline_raw).replace("Z", "+00:00")
                )
                if deadline_dt <= now_dt:
                    await crud.update_bulk_generation_item(
                        item["bulk_item_id"],
                        status="GENERATE_FAILED",
                        error="ERR_MONTAGE_POLL_DEADLINE_EXPIRED",
                        updated_at=_now(),
                    )
                    reconciled.append({
                        "scene_id": scene_id,
                        "status": "GENERATE_FAILED",
                        "error": "ERR_MONTAGE_POLL_DEADLINE_EXPIRED",
                    })
                    continue
            except (TypeError, ValueError):
                pass

        polled = await poll_fn(job_id)
        provider_calls += 1
        polled = polled if isinstance(polled, dict) else {}
        polled_status = str(
            polled.get("status") or polled.get("state") or ""
        ).upper()
        media_id = str(
            polled.get("media_id")
            or polled.get("video_media_id")
            or ""
        ).strip() or None
        if polled_status in ("DONE", "COMPLETED", "SUCCESS") and media_id:
            await bind_montage_scene_result(
                run_id,
                scene_id=scene_id,
                media_id=media_id,
                result_kind="video",
                job_id=job_id,
            )
            bound_any = True
            reconciled.append({
                "scene_id": scene_id,
                "job_id": job_id,
                "status": "RESULT_BOUND",
                "media_id": media_id,
                "resubmission_allowed": False,
            })
        elif polled_status in ("FAILED", "ERROR", "GENERATED_BUT_UNRETRIEVED"):
            error = str(polled.get("error") or polled_status)[:400]
            await crud.update_bulk_generation_item(
                item["bulk_item_id"],
                status="GENERATE_FAILED",
                error=error,
                payload_json=json.dumps({**payload, "last_poll_status": polled_status}),
                updated_at=_now(),
            )
            reconciled.append({
                "scene_id": scene_id,
                "job_id": job_id,
                "status": "GENERATE_FAILED",
                "error": error,
                "resubmission_allowed": False,
            })
        else:
            attempts = int(payload.get("poll_attempts") or 0) + 1
            backoff = min(60.0, max(5.0, float(payload.get("poll_backoff_s") or 5.0) * 2))
            next_poll = now_dt + timedelta(seconds=backoff)
            next_poll_text = next_poll.replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
            updated_payload = {
                **payload,
                "status": "VIDEO_SUBMITTED",
                "provider_job_id": job_id,
                "poll_attempts": attempts,
                "poll_backoff_s": backoff,
                "next_poll_at": next_poll_text,
                "last_poll_status": polled_status or "PENDING",
                "resubmission_allowed": False,
            }
            await crud.update_bulk_generation_item(
                item["bulk_item_id"],
                status="VIDEO_SUBMITTED",
                job_id=job_id,
                payload_json=json.dumps(updated_payload),
                updated_at=_now(),
            )
            reconciled.append({
                "scene_id": scene_id,
                "job_id": job_id,
                "status": "VIDEO_SUBMITTED",
                "last_poll_status": polled_status or "PENDING",
                "next_poll_at": next_poll_text,
                "resubmission_allowed": False,
            })

    continuation = None
    if bound_any and generate_fn is not None:
        continuation = await _dispatch_next_authorized_scene(
            run_id,
            generate_fn=generate_fn,
        )

    refreshed = await get_montage_discrete_run(run_id)
    scene_rows = refreshed.get("scenes") or []
    if scene_rows and all(
        str(s.get("status") or "").upper() in ("RESULT_BOUND", "VIDEO_READY")
        for s in scene_rows
    ):
        refreshed_cfg = refreshed.get("config") or {}
        refreshed_assembly = (
            refreshed_cfg.get("assembly")
            if isinstance(refreshed_cfg.get("assembly"), dict)
            else {}
        )
        run_status = (
            "COMPLETE"
            if refreshed_cfg.get("assembly_delivery_pair_bound")
            and _montage_final_media_id(refreshed_assembly)
            else str(refreshed.get("status") or "GENERATING").upper()
        )
        if run_status not in {"GENERATING", "ASSEMBLY_READY", "COMPLETE"}:
            run_status = "GENERATING"
    elif any(str(s.get("status") or "").upper() == "GENERATE_FAILED" for s in scene_rows):
        run_status = "PARTIAL"
    else:
        run_status = "GENERATING"
    await crud.update_bulk_generation_run(run_id, status=run_status, updated_at=_now())
    refreshed = await get_montage_discrete_run(run_id)
    return {
        "ok": not any(r.get("status") == "GENERATE_FAILED" for r in reconciled),
        "montage_run_id": run_id,
        "run": refreshed,
        "reconciled": reconciled,
        "provider_calls": provider_calls,
        "provider_generation_submits": int(
            (continuation or {}).get("provider_generation_submits") or 0
        ),
        "resubmission_allowed": False,
        "continuation": continuation,
        "next_action": (
            "ASSEMBLE"
            if scene_rows
            and all(
                str(s.get("status") or "").upper()
                in ("RESULT_BOUND", "VIDEO_READY")
                for s in scene_rows
            )
            and run_status != "COMPLETE"
            else "POLL" if run_status == "GENERATING" else None
        ),
    }


async def _default_montage_poll_fn(job_id: str) -> dict[str, Any]:
    """Canonical worker poll: memory first, durable provider reconciliation second."""
    from agent.services import make_video

    memory = make_video.get_job(job_id)
    if isinstance(memory, dict):
        status = str(memory.get("status") or "").upper()
        if status in {"DONE", "ARTIFACT_PERSISTENCE_FAILED", "PRODUCT_FIDELITY_REVIEW_REQUIRED"}:
            return memory
        # A live process-local task still owns its in-flight state. On a restart
        # this branch is absent and the durable provider handle below is used.
        if status not in {"RECOVERY_REQUIRED", "RECOVERY_UNRECOVERABLE"}:
            return memory
    durable = await make_video.reconcile_durable_single_job(job_id)
    return durable or {
        "job_id": job_id,
        "status": "FAILED",
        "error": "ERR_MONTAGE_CANONICAL_JOB_NOT_FOUND",
    }


async def _default_montage_generate_fn(run_id: str, **kwargs: Any) -> dict[str, Any]:
    """Recreate the approved API-first Montage scene dispatch after a restart."""
    from agent.api.flow import GenerateRequest, generate as flow_generate

    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    execution_identity = await load_montage_execution_identity(
        kwargs.get("workspace_execution_package_id")
    )
    start_asset = kwargs.get("start_asset")
    image_media_ids: list[str] = []
    mid = kwargs.get("image_media_id")
    if mid:
        image_media_ids.append(str(mid))
    if isinstance(start_asset, dict):
        start_mid = start_asset.get("mediaId") or start_asset.get("media_id")
        if start_mid and str(start_mid) not in image_media_ids:
            image_media_ids.append(str(start_mid))
    body = GenerateRequest(
        mode=str(kwargs.get("mode") or "F2V"),
        prompt=str(kwargs.get("prompt") or f"Montage scene {kwargs.get('scene_id')}"),
        request_id=(
            f"{str(cfg.get('origin_request_id_prefix') or f'montage:{run_id}')}"
            f":{str(kwargs.get('scene_id') or '')}"
        ),
        project_id=cfg.get("origin_project_id") or None,
        product_id=kwargs.get("product_id") or None,
        production_recipe="MONTAGE",
        staff_id=cfg.get("staff_id") or None,
        aspect="9:16",
        source_mode=kwargs.get("source_mode") or None,
        surface_lane=str(cfg.get("origin_surface_lane") or "MONTAGE"),
        workspace_execution_package_id=kwargs.get("workspace_execution_package_id") or None,
        execution_identity=execution_identity,
        model=kwargs.get("model") or None,
        duration_s=kwargs.get("duration_s"),
        generation_mode="SINGLE",
        engine="GOOGLE_FLOW",
        startAsset=start_asset if isinstance(start_asset, dict) else None,
        image_media_ids=image_media_ids or None,
        manifest_id=cfg.get("approved_manifest_id") or None,
        manifest_item_key=str(kwargs.get("scene_id") or "") or None,
    )
    result = await flow_generate(body)
    if not isinstance(result, dict):
        return {"job_id": None, "media_id": None}
    return {
        "job_id": result.get("job_id") or result.get("id"),
        "media_id": result.get("media_id")
        or result.get("video_media_id")
        or (result.get("result") or {}).get("media_id"),
        **result,
    }


async def _montage_has_active_poll(run_id: str) -> bool:
    for item in await crud.list_bulk_generation_items(run_id):
        status = str(item.get("status") or "").upper()
        payload = _loads(item.get("payload_json"), {})
        if status in ("VIDEO_SUBMITTED", "GENERATING", "VIDEO_POLLING") and (
            payload.get("next_action") == "POLL" or payload.get("async_worker")
        ):
            return True
    return False


async def _dispatch_next_authorized_scene(
    run_id: str,
    *,
    generate_fn: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Continue an already-authorized run exactly once after RESULT_BOUND."""
    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    if not cfg.get("async_worker_authorized"):
        return None
    if await _montage_has_active_poll(run_id):
        return {"status": "WAITING_ACTIVE_SCENE", "provider_generation_submits": 0}
    estimate = await estimate_montage_run_generation(run_id)
    if int(estimate.get("expected_image_operations") or 0) > 0:
        # The original authorization explicitly excluded image work. Keep the
        # worker fail-closed instead of silently inventing an image boundary.
        return {
            "status": "IMAGE_BOUNDARY_REQUIRED",
            "error": "ERR_MONTAGE_IMAGE_BOUNDARY_REQUIRED",
            "provider_generation_submits": 0,
        }
    if int(estimate.get("expected_video_generations") or 0) <= 0:
        scene_statuses = {
            str(scene.get("status") or "").upper()
            for scene in state.get("scenes") or []
        }
        if not scene_statuses or not scene_statuses.issubset(
            {"RESULT_BOUND", "VIDEO_READY"}
        ):
            await crud.update_bulk_generation_run(
                run_id,
                status="PARTIAL",
                updated_at=_now(),
            )
            return {"status": "PARTIAL", "provider_generation_submits": 0}
        from agent.services import creative_production_scheduler_service as p6_scheduler

        assembly = await p6_scheduler.resume_p6_montage_assembly(run_id)
        final_media_id = str(
            assembly.get("final_media_id")
            or assembly.get("media_id")
            or ((assembly.get("assembly") or {}).get("final_media_id"))
            or ""
        ).strip() or None
        if not final_media_id and assembly.get("status") == "ASSEMBLY_OWNER_NOT_FOUND":
            await crud.update_bulk_generation_run(
                run_id, status="ASSEMBLY_READY", updated_at=_now()
            )
        return {
            "status": (
                "COMPLETE"
                if final_media_id
                else str(assembly.get("status") or "ASSEMBLY_IN_PROGRESS")
            ),
            "final_media_id": final_media_id,
            "assembly_job_id": assembly.get("assembly_job_id"),
            "assembly": assembly,
            "provider_generation_submits": 0,
        }
    return await authorize_montage_run_generation(
        run_id,
        confirm_credit_burn=True,
        expected_video_generations=int(estimate["expected_video_generations"]),
        expected_provider_operations=int(estimate["expected_provider_operations"]),
        dry_run=False,
        generate_fn=generate_fn,
        poll_fn=None,
        async_worker=True,
        staff_id=str(cfg.get("staff_id") or "").strip() or None,
        staff_display_name_snapshot=(
            str(cfg.get("staff_display_name") or "").strip() or None
        ),
        poll_interval_s=float(cfg.get("worker_poll_interval_s") or 5.0),
        manifest_id=cfg.get("approved_manifest_id"),
    )


async def montage_scheduler_tick(
    *,
    poll_fn: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
    generate_fn: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    max_runs: int = 50,
) -> dict[str, Any]:
    """Advance due, server-authorized Montage work without an API/button call."""
    async with _MONTAGE_SCHEDULER_LOCK:
        runs = await crud.list_bulk_generation_runs(limit=max(1, int(max_runs or 1)))
        scanned = 0
        advanced = 0
        provider_calls = 0
        provider_generation_submits = 0
        pre_provider_recoveries = 0
        errors: list[dict[str, Any]] = []
        for run in runs:
            if str(run.get("kind") or "").upper() != KIND:
                continue
            cfg = _loads(run.get("config_json"), {})
            if not cfg.get("async_worker_authorized"):
                continue
            run_status = str(run.get("status") or "").upper()
            assembly = cfg.get("assembly") if isinstance(cfg.get("assembly"), dict) else {}
            assembly_complete = bool(
                cfg.get("assembly_delivery_pair_bound")
                and _montage_final_media_id(assembly)
            )
            if run_status == "COMPLETE" and assembly_complete:
                continue
            if run_status not in {
                "GENERATING",
                "PARTIAL",
                "PREPARED",
                "ASSEMBLY_READY",
                "COMPLETE",
            }:
                continue
            run_id = str(run.get("bulk_run_id") or "")
            if not run_id:
                continue
            scanned += 1
            effective_poll = poll_fn or _default_montage_poll_fn
            if generate_fn is None:
                async def _generate(**kwargs: Any) -> dict[str, Any]:
                    return await _default_montage_generate_fn(run_id, **kwargs)
                effective_generate = _generate
            else:
                effective_generate = generate_fn
            try:
                recovered = await recover_provider_free_montage_failures(run_id)
                pre_provider_recoveries += len(recovered)
                active = await _montage_has_active_poll(run_id)
                if active:
                    result = await resume_montage_run(
                        run_id,
                        poll_fn=effective_poll,
                        max_items=1,
                        generate_fn=effective_generate,
                    )
                    provider_calls += int(result.get("provider_calls") or 0)
                    continuation = result.get("continuation") or {}
                    provider_generation_submits += int(
                        result.get("provider_generation_submits") or 0
                    )
                    if result.get("reconciled") or result.get("continuation"):
                        advanced += 1
                else:
                    continuation = await _dispatch_next_authorized_scene(
                        run_id,
                        generate_fn=effective_generate,
                    )
                    provider_generation_submits += int(
                        (continuation or {}).get("provider_generation_submits") or 0
                    )
                    if continuation:
                        advanced += 1
            except Exception as exc:  # noqa: BLE001 — one run cannot stop the worker
                errors.append({"montage_run_id": run_id, "error": str(exc)[:400]})
                logger.exception("Montage scheduler failed for %s", run_id)
        return {
            "ok": not errors,
            "runs_scanned": scanned,
            "runs_advanced": advanced,
            "provider_calls": provider_calls,
            "provider_generation_submits": provider_generation_submits,
            "pre_provider_recoveries": pre_provider_recoveries,
            "errors": errors,
        }


async def montage_scheduler_loop(
    poll_seconds: float = MONTAGE_SCHEDULER_POLL_SECONDS,
) -> None:
    """Server-owned Montage worker; durable rows are the restart cursor."""
    while True:
        try:
            await montage_scheduler_tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep the backend alive for the next tick
            logger.exception("Montage scheduler tick failed")
        await asyncio.sleep(max(0.5, float(poll_seconds or MONTAGE_SCHEDULER_POLL_SECONDS)))


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
        image_ready = bool(image_id) or _has_transportable_plate(s)
        pm = s.get("product_media_id") or product_media_id
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


def _montage_final_media_id(result: dict[str, Any] | None) -> str:
    envelope = result if isinstance(result, dict) else {}
    concat = envelope.get("concat") if isinstance(envelope.get("concat"), dict) else {}
    return str(
        envelope.get("final_media_id")
        or envelope.get("media_id")
        or concat.get("final_media_id")
        or concat.get("media_id")
        or ""
    ).strip()


async def _cas_montage_assembly_claim(
    job_id: str,
    token: str,
    status: str,
    *,
    final_media_id: str | None = None,
) -> bool:
    for _ in range(3):
        row = await crud.get_video_production_job(job_id)
        if row is None:
            return False
        raw = row.get("stage_state_json")
        state = _loads(raw, {})
        current = state.get("montage_assembly_claim") or {}
        if status == "CLAIMED":
            if current.get("status") == "COMPLETE" or (
                current.get("status") == "CLAIMED"
                and str(current.get("expires_at") or "") > _now()
            ):
                return False
            expires = datetime.now(timezone.utc) + timedelta(
                seconds=MONTAGE_ASSEMBLY_CLAIM_SECONDS
            )
            claim = {
                "status": status,
                "claim_token": token,
                "expires_at": expires.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }
        else:
            if str(current.get("claim_token") or "") != token:
                return False
            claim = {**current, "status": status, "expires_at": _now()}
            if final_media_id:
                claim["final_media_id"] = final_media_id
        state["montage_assembly_claim"] = claim
        if await crud.compare_and_swap_video_production_job_stage_state(
            job_id, expected_stage_state_json=raw, stage_state_json=json.dumps(state)
        ):
            return True
    return False


async def _claim_montage_assembly(
    run_id: str,
    cfg: dict[str, Any],
    *,
    segment_media_ids: list[str],
    requested_seconds: int,
) -> dict[str, str] | None:
    logical_key = f"montage:{run_id}"
    owner = await crud.get_video_production_job_by_logical_key(logical_key)
    if owner is None:
        await crud.create_video_production_job_full(
            f"montage-final-{run_id}",
            logical_job_key=logical_key,
            requested_duration_seconds=requested_seconds,
            product_id=cfg.get("product_id"),
            staff_id=cfg.get("staff_id"),
            surface_lane=cfg.get("origin_surface_lane") or "MONTAGE",
            segment_media_ids_json=json.dumps(segment_media_ids),
            stage_state_json="{}",
        )
        owner = await crud.get_video_production_job_by_logical_key(logical_key)
    if owner is None:
        raise MontageAssemblyError("MONTAGE_ASSEMBLY_OWNER_REQUIRED", run_id)
    job_id, token = str(owner["job_id"]), uuid.uuid4().hex
    if not await _cas_montage_assembly_claim(job_id, token, "CLAIMED"):
        return None
    return {"job_id": job_id, "claim_token": token}


async def _finalize_single_block_montage_run(
    run_id: str,
    scenes: list["MontageSceneReadiness"],
    cfg: dict[str, Any],
    *,
    job_id: Optional[str],
    dry_run: bool,
) -> dict[str, Any]:
    """8s / 10s Mascot Montage finalization WITHOUT provider concat.

    A single-block final video has exactly one scene, and the concat boundary
    requires >= 2 clips. So the single finished clip IS the final deliverable:
    promote it as the run's final artifact via the existing generated_artifact
    mechanism — zero extra provider operation.
    """
    report = assess_montage_assembly_readiness(scenes)
    if not report.ok:
        raise MontageAssemblyError(
            getattr(report, "code", None) or BLOCKED_INCOMPLETE_SCENE_SET,
            getattr(report, "detail", "") or "single-block montage clip not ready",
            blockers=report.blockers,
        )
    clip_media_id = (report.clip_media_ids or [None])[0]
    if not clip_media_id:
        raise MontageAssemblyError(
            BLOCKED_INCOMPLETE_SCENE_SET,
            "single-block montage has no finished clip to promote",
            blockers=[{"error_code": "ERR_MONTAGE_MISSING_SCENE_CLIP"}],
        )
    effective_job = job_id or f"montage-run-{run_id[:8]}"
    cadence_receipt = (
        validate_final_edit_cadence(
            cfg["final_edit_cadence"],
            requested_seconds=int(cfg.get("duration_seconds") or 0),
        )
        if isinstance(cfg.get("final_edit_cadence"), dict)
        else None
    )
    payload: dict[str, Any] = {
        "ok": True,
        "assembly_path": "SINGLE_FINALIZE",
        "montage_run_id": run_id,
        "final_media_id": clip_media_id,
        "segment_count": 1,
        "requested_seconds": int(cfg.get("duration_seconds") or 0),
        "concat": {"status": "SINGLE_CLIP_PROMOTED", "invoked": False},
        "credit_spend": False,
        "dry_run": bool(dry_run),
        "final_edit_cadence": cadence_receipt,
    }
    if not dry_run:
        persisted_staff_id = str(cfg.get("staff_id") or "").strip()
        if not persisted_staff_id:
            raise MontageAssemblyError(
                "STAFF_IDENTITY_REQUIRED",
                "A Montage final output cannot be promoted without its initiating staff identity.",
                blockers=[{"error_code": "STAFF_IDENTITY_REQUIRED"}],
            )
        source_artifact = await crud.get_generated_artifact(clip_media_id)
        source_local_path = str(
            (source_artifact or {}).get("local_path") or ""
        ).strip()
        if not source_local_path:
            raise MontageAssemblyError(
                "FINAL_ARTIFACT_DELIVERY_FAILED",
                "The single Montage clip has no persisted local file evidence.",
                blockers=[{"error_code": "FINAL_ARTIFACT_DELIVERY_FAILED"}],
            )
        from agent.services.video_artifact_delivery_service import (
            register_final_video_artifact,
        )

        delivery = await register_final_video_artifact(
            {
                "final_media_id": clip_media_id,
                "local_path": source_local_path,
                "size_mb": (source_artifact or {}).get("size_mb"),
                "duration_s": (
                    (source_artifact or {}).get("duration_used")
                    or cfg.get("duration_seconds")
                ),
            },
            job_id=effective_job,
            staff_id=persisted_staff_id,
            staff_display_name_snapshot=(
                str(cfg.get("staff_display_name") or "").strip() or None
            ),
            mode="MONTAGE",
            surface_lane=str(cfg.get("origin_surface_lane") or "MONTAGE"),
            transport_mode="MONTAGE",
            source_mode=cfg.get("source_mode"),
            provider_generation_type="montage_single_block_final",
            project_id=cfg.get("origin_project_id"),
            request_id=str(
                cfg.get("origin_request_id_prefix") or f"montage:{run_id}"
            ),
            product_id=cfg.get("product_id"),
            prompt=str(cfg.get("scene_context_override") or ""),
            aspect_ratio="9:16",
        )
        payload.update(
            {
                "local_path": delivery.get("local_path"),
                "size_mb": delivery.get("size_mb"),
                "file_size_bytes": delivery.get("size_bytes"),
                "file_sha256": delivery.get("sha256"),
                "delivery": delivery,
            }
        )
        payload["concat"]["status"] = "COMPLETE"
    return payload


async def assemble_from_montage_run(
    run_id: str,
    *,
    concat_fn: Callable[..., Awaitable[dict[str, Any]]],
    dry_run: bool = True,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """M-03 path from durable run: readiness → gated concat.

    Single-block (8s/10s) runs finalize the one clip WITHOUT concat; multi-block
    (16/20/24/30) runs go through discrete readiness + concat.
    """
    state = await get_montage_discrete_run(run_id)
    cfg = state.get("config") or {}
    model, duration_s = _resolve_montage_single_settings(
        cfg.get("model"), cfg.get("duration_seconds")
    )
    _ = model
    scenes = scene_jobs_to_readiness(
        state["scenes"], product_media_id=cfg.get("product_media_id")
    )
    scene_count = len(scenes)
    if scene_count <= 0:
        raise ValueError("ERR_MONTAGE_EMPTY_PLAN")
    requested_seconds = duration_s * scene_count
    readiness = assess_montage_assembly_readiness(scenes)
    if not readiness.ok:
        raise MontageAssemblyError(
            readiness.code or BLOCKED_INCOMPLETE_SCENE_SET,
            readiness.detail,
            blockers=readiness.blockers,
        )

    if dry_run:
        if scene_count == 1:
            result = await _finalize_single_block_montage_run(
                run_id, scenes, cfg, job_id=job_id, dry_run=True
            )
        else:
            result = await assemble_montage_discrete(
                scenes,
                concat_fn=concat_fn,
                job_id=job_id or f"montage-run-{run_id[:8]}",
                requested_seconds=requested_seconds,
                segment_seconds=duration_s,
                final_edit_cadence=cfg.get("final_edit_cadence"),
                dry_run=True,
            )
            result["montage_run_id"] = run_id
        await persist_montage_assembly_result(run_id, result)
        return result

    existing_assembly = (
        cfg.get("assembly") if isinstance(cfg.get("assembly"), dict) else {}
    )
    if cfg.get("assembly_delivery_pair_bound") and _montage_final_media_id(
        existing_assembly
    ):
        return existing_assembly

    claim = await _claim_montage_assembly(
        run_id,
        cfg,
        segment_media_ids=list(readiness.clip_media_ids),
        requested_seconds=requested_seconds,
    )
    if claim is None:
        owner = await crud.get_video_production_job_by_logical_key(
            f"montage:{run_id}"
        )
        return {
            "ok": True,
            "assembly_path": "ASSEMBLY_CLAIMED",
            "montage_run_id": run_id,
            "assembly_job_id": (owner or {}).get("job_id"),
            "status": "ASSEMBLY_IN_PROGRESS",
            "final_media_id": None,
            "credit_spend": False,
            "dry_run": False,
        }

    owner_job_id = str(claim["job_id"])
    claim_token = str(claim["claim_token"])
    try:
        if scene_count == 1:
            result = await _finalize_single_block_montage_run(
                run_id,
                scenes,
                cfg,
                job_id=owner_job_id,
                dry_run=False,
            )
        else:
            result = await assemble_montage_discrete(
                scenes,
                concat_fn=concat_fn,
                job_id=owner_job_id,
                requested_seconds=requested_seconds,
                segment_seconds=duration_s,
                final_edit_cadence=cfg.get("final_edit_cadence"),
                dry_run=False,
            )
            result["montage_run_id"] = run_id

        concat = result.get("concat") if isinstance(result.get("concat"), dict) else {}
        final_media_id = _montage_final_media_id(result)
        if not final_media_id:
            raise MontageAssemblyError(
                "MONTAGE_FINAL_MEDIA_ID_REQUIRED",
                "Montage assembly returned no final media identity.",
            )
        result.update(
            {
                "assembly_job_id": owner_job_id,
                "final_media_id": final_media_id,
                "local_path": result.get("local_path") or concat.get("local_path"),
                "file_sha256": result.get("file_sha256") or concat.get("sha256"),
                "file_size_bytes": (
                    result.get("file_size_bytes") or concat.get("size_bytes")
                ),
                "segment_count": scene_count,
                "requested_seconds": requested_seconds,
            }
        )
        artifact, generation_result = await asyncio.gather(
            crud.get_generated_artifact(final_media_id),
            crud.get_generation_result(final_media_id),
        )
        if artifact is None or generation_result is None:
            raise MontageAssemblyError(
                "FINAL_DELIVERY_PAIR_REQUIRED",
                "Montage final assembly requires both durable delivery rows.",
            )
        await persist_montage_assembly_result(run_id, result)
        await _cas_montage_assembly_claim(
            owner_job_id, claim_token, "COMPLETE", final_media_id=final_media_id
        )
        await crud.update_video_production_job_full(
            owner_job_id,
            status="COMPLETE",
            final_media_id=final_media_id,
            final_local_path=artifact.get("local_path"),
            final_sha256=artifact.get("file_sha256"),
            final_duration_s=(
                artifact.get("duration_used") or requested_seconds
            ),
        )
        return result
    except Exception as exc:
        await _cas_montage_assembly_claim(owner_job_id, claim_token, "RETRYABLE")
        await crud.update_bulk_generation_run(
            run_id,
            status="ASSEMBLY_READY",
            updated_at=_now(),
        )
        raise


async def persist_montage_assembly_result(
    run_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Persist final-timeline identity/status on the existing Montage run row."""
    run = await crud.get_bulk_generation_run(run_id)
    if not run:
        raise ValueError("ERR_MONTAGE_RUN_NOT_FOUND")
    config = _loads(run.get("config_json"), {})
    config["assembly"] = result
    concat = result.get("concat") if isinstance(result, dict) else None
    final_media_id = str(
        result.get("final_media_id")
        or ((concat or {}).get("final_media_id") if isinstance(concat, dict) else "")
        or ""
    ).strip()
    delivery_pair_bound = False
    if final_media_id:
        artifact, generation_result = await asyncio.gather(
            crud.get_generated_artifact(final_media_id),
            crud.get_generation_result(final_media_id),
        )
        delivery_pair_bound = artifact is not None and generation_result is not None
    config["assembly_delivery_pair_bound"] = delivery_pair_bound
    status = "COMPLETE" if delivery_pair_bound else "ASSEMBLY_READY"
    await crud.update_bulk_generation_run(
        run_id,
        status=status,
        config_json=json.dumps(config),
        updated_at=_now(),
    )
    return config["assembly"]


def _scene_payload(
    state: SceneJobState,
    *,
    product_media_id: Optional[str],
    treatment_block_plan: Optional[dict[str, Any]] = None,
    treatment_segment: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    d = state.to_dict()
    d["product_media_id"] = d.get("product_media_id") or product_media_id
    if isinstance(treatment_block_plan, dict):
        d["treatment_block_plan"] = copy.deepcopy(treatment_block_plan)
    if isinstance(treatment_segment, dict):
        d["treatment_segment"] = copy.deepcopy(treatment_segment)
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
        "provider_job_id": payload.get("provider_job_id"),
        "provider_identity": payload.get("provider_identity") or {},
        "async_worker": bool(payload.get("async_worker")),
        "poll_attempts": int(payload.get("poll_attempts") or 0),
        "next_poll_at": payload.get("next_poll_at"),
        "poll_deadline_at": payload.get("poll_deadline_at"),
        "poll_backoff_s": payload.get("poll_backoff_s"),
        "next_action": payload.get("next_action"),
        "resubmission_allowed": payload.get("resubmission_allowed", True),
        "video_media_id": video_media,
        "error_code": item.get("error") or payload.get("error_code"),
        "detail": payload.get("detail") or "",
        "product_media_id": payload.get("product_media_id"),
        "copy_architecture_v2": payload.get("copy_architecture_v2"),
        "product_visual_custody": payload.get("product_visual_custody"),
        "treatment_block_plan": payload.get("treatment_block_plan"),
        "treatment_segment": payload.get("treatment_segment"),
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
