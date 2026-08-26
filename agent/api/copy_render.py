"""HTTP surface for the On-Demand Copy Renderer (Round 2).

Product → Benefit → Duration → Generate 5 suggestions → lock/regenerate to target
→ finalize → prepare N READY packages. Thin handlers delegate to
``copy_render_service``.

Auth (amendment 8): EVERY endpoint requires an authenticated human session (401);
mutations additionally require ``products.update`` (403). Benefit copy is strictly
HYBRID/FACELESS (enforced in the service). prepare-selected returns READY packages
only — it NEVER enqueues production, runs video, or touches the Copy-V2 binding.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent.models.copy_render_v1 import (
    CreateCopyRenderSessionRequest,
    GenerateSuggestionsRequest,
    SetVisualConfigRequest,
    UpdateTargetRequest,
)
from agent.security.access_control import get_current_auth_context
from agent.services import copy_render_service as svc

router = APIRouter(prefix="/copy-render", tags=["copy-render"])

_MUTATION_PERMISSION = "products.update"


def _raise(exc: svc.CopyRenderError):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message, "details": exc.details,
                "provider_calls": exc.provider_calls},
    ) from exc


def _require_actor():
    actor = get_current_auth_context()
    if actor is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "AUTHENTICATION_REQUIRED", "message": "An authenticated session is required."},
        )
    return actor


def _require_mutation_actor():
    actor = _require_actor()
    if _MUTATION_PERMISSION not in actor.permission_codes:
        raise HTTPException(
            status_code=403,
            detail={"error": "PERMISSION_DENIED",
                    "message": f"This action requires the {_MUTATION_PERMISSION} permission."},
        )
    return actor


# --------------------------------------------------------------------------
# session lifecycle
# --------------------------------------------------------------------------
@router.post("/sessions")
async def create_session(req: CreateCopyRenderSessionRequest) -> dict[str, Any]:
    actor = _require_mutation_actor()
    try:
        return await svc.create_session(
            product_id=req.product_id, benefit_id=req.benefit_id, lane=req.lane,
            target_count=req.target_count, duration_seconds=req.duration_seconds,
            target_language=req.target_language, formula_id=req.formula_id,
            created_by=actor.user_id, avatar_id=req.avatar_id,
        )
    except svc.CopyRenderError as exc:
        _raise(exc)


@router.patch("/sessions/{session_id}/visual-config")
async def set_visual_config(session_id: str, req: SetVisualConfigRequest) -> dict[str, Any]:
    """Bind the governed presenter identity (Avatar Registry avatar) for HYBRID.

    Visual config only: provider-free, never triggers a copy provider call and
    never mutates generated copy text or lineage. FACELESS is avatar-exempt.
    """
    _require_mutation_actor()
    try:
        return await svc.set_visual_config(session_id, avatar_id=req.avatar_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    _require_actor()
    session = await svc.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "COPY_RENDER_SESSION_NOT_FOUND", "message": "Unknown session_id."},
        )
    return session


@router.patch("/sessions/{session_id}/target")
async def update_target(session_id: str, req: UpdateTargetRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.update_target(session_id, req.target_count)
    except svc.CopyRenderError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# suggestions (the ONLY provider-spending endpoint; idempotent + single-flight)
# --------------------------------------------------------------------------
@router.post("/sessions/{session_id}/suggestions")
async def generate_suggestions(session_id: str, req: GenerateSuggestionsRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.generate_suggestions(session_id, req.request_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# lock / unlock / finalize (ZERO provider calls)
# --------------------------------------------------------------------------
@router.post("/candidates/{candidate_id}/lock")
async def lock_candidate(candidate_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.lock_candidate(candidate_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


@router.post("/candidates/{candidate_id}/unlock")
async def unlock_candidate(candidate_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.unlock_candidate(candidate_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/finalize")
async def finalize_session(session_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.finalize_session(session_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


# --------------------------------------------------------------------------
# selected reads + prepare-selected (N READY packages; NO production/queue/video)
# --------------------------------------------------------------------------
@router.get("/sessions/{session_id}/selected")
async def selected(session_id: str) -> dict[str, Any]:
    _require_actor()
    try:
        return await svc.selected(session_id)
    except svc.CopyRenderError as exc:
        _raise(exc)


@router.post("/sessions/{session_id}/prepare-selected")
async def prepare_selected(session_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.prepare_selected(session_id)
    except svc.CopyRenderError as exc:
        _raise(exc)
