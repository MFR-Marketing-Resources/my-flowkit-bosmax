"""Results Hub API — the DURABLE deliverable view for finished generations.

One place per finished video/image where the operator can (a) copy the exact
prompt + settings used, to manually re-drive Google Flow if automation breaks,
and (b) reach the per-platform social captions to publish. It composes three
sources by Flow media_id — WITHOUT changing the proven generation lane:

  - generation_result   DURABLE snapshot (prompt / settings / product / refs)
  - generated_artifact   video 48h FILE; image persistent FILE
  - social_copy_package  DURABLE captions (per-platform status)

Video files expire at 48h; image files and the record + captions do not — so
the manual fallback + caption never silently vanish. Artifacts that have a file
   but no durable record appear only when an existing lane binding proves that
   media id is final; ambiguous history remains hidden.

Endpoints (registered under /api):
  GET /api/results             list (kind/mode filter) + file status + caption rollup
  GET /api/results/{media_id}  detail: full snapshot + file + captions
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from agent.db import crud
from agent.security.access_control import get_current_auth_context
from agent.services.video_surface_provenance import surface_display_label

router = APIRouter(prefix="/results", tags=["results"])

# Matches the artifact FILE retention in agent/api/flow.py — the record outlives it.
ARTIFACT_RETENTION_HOURS = 48
_RETRIEVED_URL = "/api/flow/retrieved/{}"
_CAPTION_JSON_COLUMNS = ("hashtags_json", "blockers_json", "warnings_json")


def _staff_scope(requested_staff_id: str | None = None) -> str | None:
    """Bind human result reads to the authenticated StaffProfile."""
    context = get_current_auth_context()
    if context is None:
        return requested_staff_id
    if {"OWNER", "MANAGER"} & {str(role).upper() for role in context.role_codes}:
        return requested_staff_id
    if requested_staff_id and requested_staff_id != context.staff_id:
        raise HTTPException(status_code=403, detail="RESULT_STAFF_SCOPE_DENIED")
    return context.staff_id


def _expiry(
    created_at: str | None, artifact_kind: str | None = "video"
) -> tuple[str | None, float | None]:
    """Return expiry only for video artifacts; images are manual-delete."""
    if str(artifact_kind or "video").lower() != "video":
        return None, None
    try:
        created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None, None
    expires = created + timedelta(hours=ARTIFACT_RETENTION_HOURS)
    hours = max(
        0.0, round((expires - datetime.now(timezone.utc)).total_seconds() / 3600, 1))
    return expires.strftime("%Y-%m-%dT%H:%M:%SZ"), hours


def _refs(record: dict) -> list:
    try:
        value = json.loads(record.get("reference_media_ids_json") or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _entry_from_record(record: dict, artifact: dict | None) -> dict:
    """A hub row backed by a durable record; file fields come from the artifact
    when its file is still present, otherwise file_available is False."""
    expires_at, expires_in = (
        _expiry(artifact["created_at"], artifact.get("artifact_kind"))
        if artifact else (None, None)
    )
    return {
        "media_id": record["media_id"],
        "mode": record.get("mode"),
        "surface_lane": record.get("surface_lane") or (artifact or {}).get("surface_lane"),
        "surface_label": surface_display_label(
            record.get("surface_lane") or (artifact or {}).get("surface_lane"),
            mode=record.get("mode"),
        ),
        "transport_mode": record.get("transport_mode") or (artifact or {}).get("transport_mode"),
        "source_mode": record.get("source_mode") or (artifact or {}).get("source_mode"),
        "provider_generation_type": record.get("provider_generation_type") or (artifact or {}).get("provider_generation_type"),
        "artifact_kind": record.get("artifact_kind") or "video",
        "product_name": record.get("product_name"),
        "model_label": record.get("model_label"),
        "aspect_ratio": record.get("aspect_ratio"),
        "created_at": record.get("created_at"),
        "duration_s": record.get("duration_s"),
        "has_record": True,
        "file_available": artifact is not None,
        "size_mb": (artifact or {}).get("size_mb"),
        "retrieved_url": _RETRIEVED_URL.format(record["media_id"]) if artifact else None,
        "expires_at": expires_at,
        "expires_in_hours": expires_in,
    }


def _entry_from_artifact(artifact: dict) -> dict:
    """A hub row for a file that has no durable record yet (older/direct lane)."""
    expires_at, expires_in = _expiry(
        artifact.get("created_at"), artifact.get("artifact_kind")
    )
    return {
        "media_id": artifact["media_id"],
        "mode": artifact.get("mode"),
        "surface_lane": artifact.get("surface_lane"),
        "surface_label": surface_display_label(
            artifact.get("surface_lane"), mode=artifact.get("mode")
        ),
        "transport_mode": artifact.get("transport_mode"),
        "source_mode": artifact.get("source_mode"),
        "provider_generation_type": artifact.get("provider_generation_type"),
        "artifact_kind": artifact.get("artifact_kind") or "video",
        "product_name": None,
        "model_label": artifact.get("model_used"),
        "aspect_ratio": None,
        "created_at": artifact.get("created_at"),
        "duration_s": artifact.get("duration_used"),
        "has_record": False,
        "file_available": True,
        "size_mb": artifact.get("size_mb"),
        "retrieved_url": _RETRIEVED_URL.format(artifact["media_id"]),
        "expires_at": expires_at,
        "expires_in_hours": expires_in,
    }


@router.get("")
async def list_results(
    limit: int = 60,
    mode: str | None = None,
    kind: str | None = None,
    surface_lane: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    staff_id: str | None = None,
):
    """Newest-first deliverable list. Runs the lazy video 48h purge first (so
    file availability is accurate), then merges durable records with only
    correlation-compatible file artifacts, and attaches a one-query caption
    rollup per media id. A request filter can never discover file-only history
    because generated_artifact has no request_id authority."""
    limit = max(1, min(200, int(limit or 60)))
    purged = await crud.purge_expired_artifacts(ARTIFACT_RETENTION_HOURS)
    effective_staff_id = _staff_scope(staff_id)
    records = await crud.list_generation_results(
        limit=limit, mode=mode, kind=kind, surface_lane=surface_lane,
        request_id=request_id, job_id=job_id, staff_id=effective_staff_id,
        final_only=True,
    )
    artifacts = await crud.list_generated_artifacts(
        limit=max(limit, 200), mode=mode, kind=kind, surface_lane=surface_lane,
        final_only=True)
    record_ids = {str(row["media_id"]) for row in records}
    artifacts = [
        artifact
        for artifact in artifacts
        if (
            not effective_staff_id
            or artifact.get("staff_id") == effective_staff_id
            or str(artifact.get("media_id") or "") in record_ids
        )
        and (
            not job_id
            or artifact.get("job_id") == job_id
            or str(artifact.get("media_id") or "") in record_ids
        )
        and (
            not request_id
            or str(artifact.get("media_id") or "") in record_ids
        )
    ]
    artifact_map = {a["media_id"]: a for a in artifacts}

    entries: list[dict] = []
    seen: set[str] = set()
    for record in records:
        seen.add(record["media_id"])
        entries.append(_entry_from_record(record, artifact_map.get(record["media_id"])))
    for artifact in artifacts:
        if artifact["media_id"] not in seen:
            entries.append(_entry_from_artifact(artifact))

    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    entries = entries[:limit]

    summary = await crud.caption_summary_for_media_ids(
        [e["media_id"] for e in entries])
    for entry in entries:
        entry["caption_summary"] = summary.get(
            entry["media_id"], {"count": 0, "approved": 0})

    return {
        "results": entries,
        "count": len(entries),
        "retention_hours": ARTIFACT_RETENTION_HOURS,
        "retention_policy": {"video": "48h", "image": "manual_delete"},
        "purged": purged,
    }


@router.get("/recover")
async def recover_results(
    request_id: str | None = None,
    job_id: str | None = None,
    surface_lane: str | None = None,
    staff_id: str | None = None,
    limit: int = 60,
):
    """Reload-safe lookup for a generation request/job.

    This endpoint is deliberately read-only. It lets an operator recover a
    durable media id after the browser or backend process lost its in-memory
    polling state; it never starts or retries a provider operation.
    """
    if not request_id and not job_id:
        raise HTTPException(422, "RECOVERY_FILTER_REQUIRED")
    rows = await crud.list_generation_results(
        limit=max(1, min(200, int(limit or 60))),
        request_id=request_id,
        job_id=job_id,
        surface_lane=surface_lane,
        staff_id=_staff_scope(staff_id),
        final_only=True,
    )
    entries = []
    for row in rows:
        artifact = await crud.get_generated_artifact(row["media_id"])
        entry = _entry_from_record(row, artifact)
        entry.update({
            "request_id": row.get("request_id"),
            "job_id": row.get("job_id"),
            "snapshot": {
                "final_prompt_text": row.get("final_prompt_text") or "",
                "mode": row.get("mode"),
                "surface_lane": row.get("surface_lane"),
                "surface_label": surface_display_label(
                    row.get("surface_lane"), mode=row.get("mode")
                ),
                "transport_mode": row.get("transport_mode"),
                "source_mode": row.get("source_mode"),
                "provider_generation_type": row.get("provider_generation_type"),
                "model_label": row.get("model_label"),
                "aspect_ratio": row.get("aspect_ratio"),
                "duration_s": row.get("duration_s"),
                "count_setting": row.get("count_setting"),
                "project_id": row.get("project_id"),
            },
        })
        entries.append(entry)
    return {
        "results": entries,
        "count": len(entries),
        "request_id": request_id,
        "job_id": job_id,
        "provider_calls": 0,
    }


@router.get("/{media_id}")
async def get_result(media_id: str):
    """Full deliverable detail: the durable prompt/settings snapshot (manual Flow
    fallback), current file availability + download URL, and the captions."""
    record = await crud.get_generation_result(media_id)
    artifact = await crud.get_generated_artifact(media_id)
    if not record and not artifact:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND")
    kind = str((record or artifact or {}).get("artifact_kind") or "video").lower()
    if kind == "video" and not await crud.is_final_video_media_id(media_id):
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND")
    scoped_staff = _staff_scope()
    if scoped_staff and (record or artifact or {}).get("staff_id") != scoped_staff:
        raise HTTPException(status_code=404, detail="RESULT_NOT_FOUND")

    captions = await crud.list_social_copy_packages(artifact_media_id=media_id)
    for caption in captions:
        for col in _CAPTION_JSON_COLUMNS:
            try:
                caption[col] = json.loads(caption.get(col) or "[]")
            except (TypeError, ValueError):
                caption[col] = []

    base = record or artifact or {}
    file_available = artifact is not None
    expires_at, expires_in = (
        _expiry(artifact["created_at"], artifact.get("artifact_kind"))
        if artifact else (None, None)
    )

    snapshot = None
    if record:
        snapshot = {
            "final_prompt_text": record.get("final_prompt_text") or "",
            "mode": record.get("mode"),
            "surface_lane": record.get("surface_lane"),
            "surface_label": surface_display_label(
                record.get("surface_lane"), mode=record.get("mode")
            ),
            "transport_mode": record.get("transport_mode"),
            "source_mode": record.get("source_mode"),
            "provider_generation_type": record.get("provider_generation_type"),
            "model_label": record.get("model_label"),
            "aspect_ratio": record.get("aspect_ratio"),
            "duration_s": record.get("duration_s"),
            "count_setting": record.get("count_setting"),
            "reference_media_ids": _refs(record),
            "product_id": record.get("product_id"),
            "product_name": record.get("product_name"),
            "workspace_generation_package_id": record.get(
                "workspace_generation_package_id"),
            "project_id": record.get("project_id"),
            "job_id": record.get("job_id"),
            "request_id": record.get("request_id"),
        }

    return {
        "media_id": media_id,
        "mode": base.get("mode"),
        "surface_lane": base.get("surface_lane"),
        "surface_label": surface_display_label(
            base.get("surface_lane"), mode=base.get("mode")
        ),
        "transport_mode": base.get("transport_mode"),
        "source_mode": base.get("source_mode"),
        "provider_generation_type": base.get("provider_generation_type"),
        "artifact_kind": base.get("artifact_kind") or "video",
        "has_record": record is not None,
        "product_name": (record or {}).get("product_name"),
        "created_at": base.get("created_at"),
        "file_available": file_available,
        "retrieved_url": _RETRIEVED_URL.format(media_id) if file_available else None,
        "size_mb": (artifact or {}).get("size_mb"),
        "expires_at": expires_at,
        "expires_in_hours": expires_in,
        "snapshot": snapshot,
        "captions": captions,
    }
