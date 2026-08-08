"""Montage R3 — gate real discrete concat behind assembly readiness.

SIBLING to google_flow_final_timeline_runtime.finalize_timeline.
Does NOT modify Laluan-A native-extend behavior.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Sequence

from agent.services.google_flow_final_timeline_runtime import build_concat_input
from agent.services.montage_assembly_readiness import (
    BLOCKED_INCOMPLETE_SCENE_SET,
    MontageAssemblyError,
    MontageAssemblyReport,
    MontageSceneReadiness,
    assess_montage_assembly_readiness,
)

ConcatFn = Callable[..., Awaitable[dict[str, Any]]]


async def assemble_montage_discrete(
    scenes: Sequence[MontageSceneReadiness],
    *,
    concat_fn: ConcatFn,
    job_id: str = "montage-discrete",
    requested_seconds: Optional[int] = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Readiness → concat. Incomplete mandatory sets never call concat_fn.

    concat_fn is the real boundary (e.g. client.run_video_concatenation or a
    dry-run wrapper). Tests spy this boundary.
    """
    report = assess_montage_assembly_readiness(scenes)
    if not report.ok:
        # Explicit: concat MUST NOT be invoked
        raise MontageAssemblyError(
            report.code or BLOCKED_INCOMPLETE_SCENE_SET,
            report.detail,
            blockers=report.blockers,
        )

    clip_ids = list(report.clip_media_ids)
    # Validate concat contract shape without submitting when dry_run and concat_fn
    # still builds the body — build_concat_input fails closed if <2 segments.
    input_videos = build_concat_input(clip_ids)
    seconds = requested_seconds if requested_seconds is not None else 8 * len(clip_ids)

    result = await concat_fn(
        job_id=job_id,
        segment_media_ids=clip_ids,
        input_videos=input_videos,
        requested_seconds=seconds,
        dry_run=dry_run,
    )
    return {
        "ok": True,
        "assembly_path": "DISCRETE_MONTAGE",
        "readiness": {
            "ok": report.ok,
            "ready_scene_ids": report.ready_scene_ids,
            "clip_media_ids": report.clip_media_ids,
        },
        "concat": result,
        "credit_spend": not dry_run,
    }


def readiness_from_orchestrated_jobs(
    jobs: Sequence[Any],
    *,
    default_policy: str = "PRODUCT_ANCHOR",
) -> list[MontageSceneReadiness]:
    """Map SceneJobState-like objects into readiness rows for assembly gate."""
    out: list[MontageSceneReadiness] = []
    from agent.services.montage_scene_reference_policy import parse_scene_reference_policy

    for j in jobs:
        if hasattr(j, "to_dict"):
            d = j.to_dict()
        elif isinstance(j, dict):
            d = j
        else:
            d = {
                "scene_id": getattr(j, "scene_id", ""),
                "reference_policy": getattr(j, "reference_policy", default_policy),
                "video_media_id": getattr(j, "video_media_id", None),
                "image_media_id": getattr(j, "image_media_id", None),
                "status": getattr(j, "status", ""),
            }
        policy = parse_scene_reference_policy(
            d.get("reference_policy") or default_policy
        )
        clip = d.get("video_media_id")
        video_ready = bool(clip) or str(d.get("status") or "") == "VIDEO_READY"
        image_ready = bool(d.get("image_media_id")) or video_ready
        out.append(
            MontageSceneReadiness(
                scene_id=str(d.get("scene_id") or ""),
                mandatory=True,
                reference_policy=policy,
                product_media_id=d.get("product_media_id"),
                clip_media_id=clip,
                image_ready=image_ready,
                video_ready=video_ready,
                image_generation_required=True,
                video_generation_required=True,
            )
        )
    return out


__all__ = [
    "assemble_montage_discrete",
    "readiness_from_orchestrated_jobs",
    "BLOCKED_INCOMPLETE_SCENE_SET",
    "MontageAssemblyError",
    "MontageAssemblyReport",
]
