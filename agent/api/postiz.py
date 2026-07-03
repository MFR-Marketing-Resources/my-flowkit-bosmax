"""API router for the Postiz publishing adapter (feature-flagged).

Every endpoint fails closed with 503 POSTIZ_DISABLED / config errors while
POSTIZ_ENABLED != true — with the flag off, BOSMAX behaves exactly as before.
Publishing defaults to `draft`; nothing is posted publicly unless the
operator explicitly selects otherwise AND the provider app permits it.
"""
from __future__ import annotations

import json
import uuid

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services import postiz_client as pz

router = APIRouter(prefix="/postiz", tags=["postiz"])


def _http_exc(exc: Exception) -> HTTPException:
    if isinstance(exc, pz.PostizConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, pz.PostizValidationError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, pz.PostizApiError):
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/health")
async def health():
    """Config check — never exposes the API key."""
    return pz.health_summary()


@router.get("/setup-status")
async def setup_status():
    """Setup Doctor: onboarding checklist state for the operator.

    Deliberately NOT gated on POSTIZ_ENABLED — this endpoint exists exactly
    to guide the operator out of the disabled/misconfigured states. Never
    exposes the API key."""
    return await pz.setup_status()


@router.get("/integrations")
async def integrations():
    """Connected Postiz channels (multiple per provider is normal)."""
    try:
        channels = await pz.list_integrations()
    except Exception as exc:
        raise _http_exc(exc)
    return {"integrations": channels, "count": len(channels)}


@router.get("/provider-templates")
async def templates():
    """Safe-default provider settings templates + operator warnings."""
    return pz.provider_templates()


@router.get("/publish-records")
async def publish_records(limit: int = 50):
    records = await crud.list_postiz_publish_records(limit=limit)
    for r in records:
        for col in ("integration_ids_json", "provider_settings_json", "postiz_response_json"):
            try:
                r[col] = json.loads(r.get(col) or "null")
            except (TypeError, ValueError):
                pass
    return {"records": records, "count": len(records)}


class PublishRequest(BaseModel):
    artifact_media_id: str
    integration_ids: list[str]
    post_type: str | None = None  # draft | schedule | now (default from env: draft)
    schedule_at: str | None = None  # ISO datetime, required for schedule
    content: str = ""
    # integration_id → settings override; missing ids get the provider template
    provider_settings: dict[str, dict] = Field(default_factory=dict)
    # validate + build payload without uploading or posting
    dry_run: bool = False


@router.post("/publish")
async def publish(request: PublishRequest):
    """Send one BOSMAX-generated artifact to Postiz — no manual re-upload.

    Flow: resolve artifact → validate media → upload (file or url mode) →
    create draft/schedule/now post for every selected integration id →
    persist the audit record.
    """
    try:
        cfg = pz.ensure_enabled_and_configured()
    except pz.PostizConfigError as exc:
        raise _http_exc(exc)

    post_type = (request.post_type or cfg["default_post_type"]).strip().lower()
    if post_type not in pz.POST_TYPES:
        raise HTTPException(422, f"UNSUPPORTED_POST_TYPE:{request.post_type}")
    if post_type == "schedule":
        if not request.schedule_at:
            raise HTTPException(422, "SCHEDULE_AT_REQUIRED_FOR_SCHEDULE")
        try:
            datetime.fromisoformat(str(request.schedule_at).replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                422, f"INVALID_SCHEDULE_AT_NOT_ISO_DATETIME:{request.schedule_at}",
            )
    if not request.integration_ids:
        raise HTTPException(422, "NO_INTEGRATIONS_SELECTED")

    artifact = await crud.get_generated_artifact(request.artifact_media_id)
    if not artifact:
        raise HTTPException(404, f"ARTIFACT_NOT_FOUND:{request.artifact_media_id}")
    local_path = artifact.get("local_path") or ""

    # Resolve the media source per upload mode — fail closed, never fall back.
    public_url = None
    if cfg["upload_mode"] == "url":
        base = cfg["public_media_base_url"]
        if not base:
            raise HTTPException(
                422,
                "MEDIA_NOT_PUBLICLY_REACHABLE: POSTIZ_UPLOAD_MODE=url requires "
                "POSTIZ_PUBLIC_MEDIA_BASE_URL (public HTTPS) — localhost/private "
                "URLs are rejected by design.",
            )
        from pathlib import Path as _P
        public_url = f"{base}/{_P(local_path).name}"
        try:
            pz.validate_public_https_url(public_url)
        except pz.PostizValidationError as exc:
            raise _http_exc(exc)
    else:
        try:
            pz.validate_media_file(local_path)
        except pz.PostizValidationError as exc:
            raise _http_exc(exc)

    # Providers for template lookup (also validates the integration ids exist).
    try:
        channels = await pz.list_integrations()
    except Exception as exc:
        raise _http_exc(exc)
    providers_by_id = {c["id"]: (c.get("provider") or "") for c in channels}
    unknown = [i for i in request.integration_ids if i not in providers_by_id]
    if unknown:
        raise HTTPException(422, f"UNKNOWN_INTEGRATION_IDS:{','.join(unknown)}")

    if request.dry_run:
        payload = pz.build_post_payload(
            post_type=post_type,
            integration_ids=request.integration_ids,
            media=[{"id": "DRY_RUN_MEDIA_ID", "path": local_path}],
            content=request.content,
            schedule_at=request.schedule_at,
            provider_settings=request.provider_settings,
            integration_providers=providers_by_id,
        )
        return {"dry_run": True, "payload": payload,
                "note": "DRY RUN — nothing uploaded, nothing posted."}

    record_id = f"pzr_{uuid.uuid4().hex[:16]}"
    await crud.create_postiz_publish_record(
        record_id,
        artifact_media_id=request.artifact_media_id,
        source_local_path=local_path,
        source_public_url=public_url,
        upload_mode=cfg["upload_mode"],
        post_type=post_type,
        scheduled_at=request.schedule_at,
        content=request.content,
        integration_ids_json=json.dumps(request.integration_ids),
        provider_settings_json=json.dumps(request.provider_settings),
    )

    try:
        media = (await pz.upload_from_url(public_url)) if cfg["upload_mode"] == "url" \
            else (await pz.upload_file(local_path))
        await crud.update_postiz_publish_record(
            record_id, status="UPLOADED",
            postiz_media_id=media.get("id"), postiz_media_path=media.get("path"),
        )
        payload = pz.build_post_payload(
            post_type=post_type,
            integration_ids=request.integration_ids,
            media=[media],
            content=request.content,
            schedule_at=request.schedule_at,
            provider_settings=request.provider_settings,
            integration_providers=providers_by_id,
        )
        response = await pz.create_post(payload)
        await crud.update_postiz_publish_record(
            record_id, status="POST_CREATED",
            postiz_response_json=json.dumps(response, ensure_ascii=False, default=str)[:4000],
        )
    except Exception as exc:
        await crud.update_postiz_publish_record(
            record_id, status="FAILED", error=str(exc)[:500],
        )
        raise _http_exc(exc)

    return {
        "ok": True,
        "record_id": record_id,
        "post_type": post_type,
        "postiz_media": media,
        "postiz_response": response,
        "integration_ids": request.integration_ids,
    }
