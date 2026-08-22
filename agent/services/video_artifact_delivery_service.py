"""Durable final-video delivery boundary.

Provider runtimes produce a media identity and a local file. This module is the
small, shared boundary that turns that pair into a durable library/Results Hub
record. It deliberately performs no provider work and raises on any missing or
failed local write, so callers cannot promote a final render to COMPLETE while
its artifact is absent.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent.db import crud


FINAL_ARTIFACT_DELIVERY_FAILED = "FINAL_ARTIFACT_DELIVERY_FAILED"


class FinalArtifactDeliveryError(RuntimeError):
    code = FINAL_ARTIFACT_DELIVERY_FAILED

    def __init__(self, detail: str):
        self.detail = str(detail)
        super().__init__(f"{self.code}:{self.detail}")


def _final_media_id(result: dict[str, Any]) -> str:
    return str(
        result.get("final_media_id")
        or result.get("media_id")
        or ""
    ).strip()


def _final_local_path(result: dict[str, Any]) -> str:
    return str(result.get("local_path") or result.get("final_local_path") or "").strip()


def file_delivery_evidence(local_path: str) -> dict[str, Any]:
    """Validate and hash a local artifact without touching a provider."""
    path = Path(str(local_path or "").strip())
    if not str(path):
        raise FinalArtifactDeliveryError("local artifact path is empty")
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            raise FinalArtifactDeliveryError(
                f"local artifact is missing or empty: {path}"
            )
        size_bytes = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except FinalArtifactDeliveryError:
        raise
    except OSError as exc:
        raise FinalArtifactDeliveryError(f"local artifact read failed: {exc}") from exc
    return {
        "local_path": str(path),
        "size_bytes": int(size_bytes),
        "sha256": digest.hexdigest(),
    }


async def register_final_video_artifact(
    result: dict[str, Any],
    *,
    job_id: str,
    mode: str = "EXTEND",
    surface_lane: str | None = None,
    transport_mode: str | None = None,
    source_mode: str | None = None,
    provider_generation_type: str | None = None,
    project_id: str | None = None,
    request_id: str | None = None,
    product_id: str | None = None,
    prompt: str = "",
    aspect_ratio: str | None = None,
    staff_id: str | None = None,
    staff_display_name_snapshot: str | None = None,
) -> dict[str, Any]:
    """Register one final video and return its durable identity.

    Both writes are idempotent on media id. If either write fails, the caller
    receives a structured error and must leave the owning lifecycle non-complete;
    a retry of this function is local-only and does not re-submit generation.
    """
    if not isinstance(result, dict):
        raise FinalArtifactDeliveryError("final render returned no result envelope")
    media_id = _final_media_id(result)
    local_path = _final_local_path(result)
    if not media_id:
        raise FinalArtifactDeliveryError("final render returned no media id")
    if not local_path:
        raise FinalArtifactDeliveryError("final render returned no local artifact path")
    evidence = file_delivery_evidence(local_path)

    existing_job = await crud.get_video_production_job(job_id)
    from agent.services.video_surface_provenance import build_video_surface_provenance
    provenance = build_video_surface_provenance(
        surface_lane=surface_lane or (existing_job or {}).get("surface_lane"),
        transport_mode=(
            transport_mode
            or (existing_job or {}).get("transport_mode")
            or mode
        ),
        source_mode=source_mode or (existing_job or {}).get("source_mode"),
        provider_type=(
            provider_generation_type
            or (existing_job or {}).get("provider_generation_type")
        ),
        mode=mode,
        existing=existing_job,
    )

    size_mb = result.get("size_mb")
    if size_mb is None:
        size_mb = round(evidence["size_bytes"] / 1024 / 1024, 2)
    duration_s = result.get("measured_duration_s") or result.get("duration_s")
    try:
        readback = await crud.insert_generated_artifact(
            media_id,
            job_id=job_id,
            mode=mode,
            surface_lane=provenance["surface_lane"],
            transport_mode=provenance["transport_mode"],
            source_mode=provenance["source_mode"],
            provider_generation_type=provenance["provider_generation_type"],
            artifact_kind="video",
            local_path=local_path,
            size_mb=size_mb,
            project_id=project_id,
            duration_used=int(duration_s or 0),
            file_size_bytes=evidence["size_bytes"],
            file_sha256=evidence["sha256"],
            delivery_status="REGISTERED",
            readback_verified=True,
            staff_id=staff_id,
            staff_display_name_snapshot=staff_display_name_snapshot,
        )
        await crud.insert_generation_result(
            media_id,
            job_id=job_id,
            request_id=request_id,
            mode=mode,
            surface_lane=provenance["surface_lane"],
            transport_mode=provenance["transport_mode"],
            source_mode=provenance["source_mode"],
            provider_generation_type=provenance["provider_generation_type"],
            artifact_kind="video",
            product_id=product_id,
            final_prompt_text=prompt or "",
            aspect_ratio=aspect_ratio,
            duration_s=int(duration_s or 0),
            project_id=project_id,
            staff_id=staff_id,
            staff_display_name_snapshot=staff_display_name_snapshot,
        )
        if readback is not None and str(readback.get("local_path") or "") != local_path:
            raise FinalArtifactDeliveryError(
                "generated_artifact read-back path does not match final artifact"
            )
    except FinalArtifactDeliveryError:
        raise
    except Exception as exc:  # noqa: BLE001 — callers must fail closed
        raise FinalArtifactDeliveryError(str(exc)) from exc
    return {
        "media_id": media_id,
        "local_path": local_path,
        "size_mb": size_mb,
        "size_bytes": evidence["size_bytes"],
        "sha256": evidence["sha256"],
        "duration_s": int(duration_s or 0),
        "provider_calls": 0,
        **provenance,
        "readback_verified": True,
    }
