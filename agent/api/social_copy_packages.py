"""Social Copy Package API — author, validate, approve platform copy.

Endpoints (registered under ``/api``):
  GET   /api/social-copy-packages            list (filter by artifact/platform/status)
  GET   /api/social-copy-packages/profiles   per-platform copy scaffolding metadata
  GET   /api/social-copy-packages/suggest    claim-safe copy suggestion for a platform
  POST  /api/social-copy-packages/generate   create a copy variant (claim-safe checked)
  GET   /api/social-copy-packages/{id}        fetch one
  PATCH /api/social-copy-packages/{id}        edit (re-validates, un-approves)
  POST  /api/social-copy-packages/{id}/approve
  POST  /api/social-copy-packages/{id}/reject

Feature-flag / secrets: none. No social OAuth, no posting happens here — this
layer only stores copy that Postiz Publish later prefills into its caption field.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services import ai_caption_assist_service as ai_caption_svc
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import social_copy_package_service as svc

router = APIRouter(prefix="/social-copy-packages", tags=["social-copy-packages"])

_JSON_COLUMNS = ("hashtags_json", "blockers_json", "warnings_json")


def _parse(pkg: dict) -> dict:
    """Decode the *_json columns into real arrays for the client."""
    out = dict(pkg)
    for col in _JSON_COLUMNS:
        try:
            out[col] = json.loads(out.get(col) or "[]")
        except (TypeError, ValueError):
            out[col] = []
    return out


def _map_svc_error(exc: svc.SocialCopyError) -> HTTPException:
    code = str(exc)
    if code in ("ARTIFACT_NOT_FOUND", "PACKAGE_NOT_FOUND"):
        return HTTPException(status_code=404, detail=code)
    if code == "CLAIM_UNSAFE_CANNOT_APPROVE":
        return HTTPException(status_code=409, detail=code)
    return HTTPException(status_code=422, detail=code)


class GenerateRequest(BaseModel):
    artifact_media_id: str
    platform: str
    caption: str = ""
    first_comment: str = ""
    hashtags: list[str] = Field(default_factory=list)
    call_to_action: str = ""
    tone: str = ""
    language: str = "ms"
    source_mode: str | None = None


class UpdateRequest(BaseModel):
    caption: str | None = None
    first_comment: str | None = None
    hashtags: list[str] | None = None
    call_to_action: str | None = None
    tone: str | None = None
    language: str | None = None


class ApprovalRequest(BaseModel):
    approval_note: str | None = None


class AICaptionAssistRequest(BaseModel):
    platform: str
    artifact_media_id: str | None = None
    product_id: str | None = None
    source_mode: str | None = None
    language: str | None = None
    tone: str | None = None
    operator_notes: str | None = None
    candidate_count: int = 1


@router.get("")
async def list_packages(
    artifact_media_id: str | None = Query(None),
    platform: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    pkgs = await crud.list_social_copy_packages(
        artifact_media_id=artifact_media_id,
        platform=platform,
        status=status,
        limit=limit,
    )
    return {"packages": [_parse(p) for p in pkgs], "count": len(pkgs)}


@router.get("/profiles")
async def get_profiles():
    return {"platforms": list(svc.SUPPORTED_PLATFORMS), "profiles": svc.platform_profiles()}


@router.get("/suggest")
async def suggest(
    platform: str = Query(...),
    source_mode: str | None = Query(None),
    product_name: str | None = Query(None),
):
    try:
        return svc.suggest_copy(
            platform=platform, source_mode=source_mode, product_name=product_name
        )
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)


@router.post("/generate")
async def generate(request: GenerateRequest):
    try:
        pkg = await svc.generate_social_copy_package(
            artifact_media_id=request.artifact_media_id,
            platform=request.platform,
            caption=request.caption,
            first_comment=request.first_comment,
            hashtags=request.hashtags,
            call_to_action=request.call_to_action,
            tone=request.tone,
            language=request.language,
            source_mode=request.source_mode,
        )
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)
    return _parse(pkg)


@router.post("/ai-assist")
async def ai_assist(request: AICaptionAssistRequest):
    """Grounded AI caption candidate(s) for review — reuses the text_assist lane +
    product/avatar grounding. Governance: returns suggestions only, never persists
    or approves (the operator still Saves and Approves). Fails closed (409) when the
    provider lane is not configured; the free deterministic /suggest stays available."""
    try:
        return await ai_caption_svc.generate_caption_candidates(request.model_dump())
    except ai_provider.AICopyProviderNotConfigured as error:
        raise HTTPException(status_code=409, detail={"error": error.code}) from error
    except ai_provider.AICopyProviderError as error:
        raise HTTPException(
            status_code=502, detail={"error": error.code, "detail": error.detail}
        ) from error
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)


@router.get("/{package_id}")
async def get_package(package_id: str):
    pkg = await crud.get_social_copy_package(package_id)
    if not pkg:
        raise HTTPException(status_code=404, detail="PACKAGE_NOT_FOUND")
    return _parse(pkg)


@router.patch("/{package_id}")
async def update_package(package_id: str, request: UpdateRequest):
    try:
        pkg = await svc.update_social_copy_package(
            package_id,
            caption=request.caption,
            first_comment=request.first_comment,
            hashtags=request.hashtags,
            call_to_action=request.call_to_action,
            tone=request.tone,
            language=request.language,
        )
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)
    return _parse(pkg)


@router.post("/{package_id}/approve")
async def approve_package(package_id: str, request: ApprovalRequest):
    try:
        pkg = await svc.approve_social_copy_package(package_id, request.approval_note)
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)
    return _parse(pkg)


@router.post("/{package_id}/reject")
async def reject_package(package_id: str, request: ApprovalRequest):
    try:
        pkg = await svc.reject_social_copy_package(package_id, request.approval_note)
    except svc.SocialCopyError as exc:
        raise _map_svc_error(exc)
    return _parse(pkg)
