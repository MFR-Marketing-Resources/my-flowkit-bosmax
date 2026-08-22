from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request

from agent.models.access_control import (
    InviteStaffRequest,
    RoleAssignmentRequest,
    RolePermissionsRequest,
    SessionRevokeRequest,
    UpdateStaffRequest,
)
from agent.security.access_control import get_current_auth_context
from agent.services import access_control_service as access

router = APIRouter(prefix="/system/staff-access", tags=["staff-access"])


def _raise(exc: access.AccessControlError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message},
    ) from exc


def _context(request: Request):
    context = get_current_auth_context() or getattr(request.state, "auth_context", None)
    if context is None:
        _raise(access.AccessControlError("AUTHENTICATION_REQUIRED", "Sign in first.", status_code=401))
    return context


def _owner(request: Request):
    context = _context(request)
    if "OWNER" not in context.role_codes:
        _raise(
            access.AccessControlError(
                "OWNER_REQUIRED", "Only an active OWNER may administer staff access.", status_code=403
            )
        )
    return context


@router.get("/overview")
async def overview(request: Request) -> dict[str, Any]:
    context = _context(request)
    return {
        "current_user": context.to_safe_dict(),
        "staff_count": len(await access.list_staff()),
        "active_session_count": len(await access.list_sessions(active_only=True)),
        "tabs": ["staff", "roles", "sessions", "audit"],
    }


@router.get("/staff")
async def list_staff(request: Request) -> dict[str, Any]:
    _context(request)
    return {"staff": await access.list_staff()}


@router.post("/staff", status_code=201)
async def invite_staff(body: InviteStaffRequest, request: Request) -> dict[str, Any]:
    context = _owner(request)
    try:
        return await access.invite_staff(
            context,
            display_name=body.display_name,
            email=body.email,
            role_codes=body.role_codes,
        )
    except access.AccessControlError as exc:
        _raise(exc)


@router.get("/staff/{user_id}")
async def get_staff(request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    _context(request)
    for item in await access.list_staff():
        if item["user_id"] == user_id:
            return item
    _raise(access.AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404))


@router.patch("/staff/{user_id}")
async def update_staff(body: UpdateStaffRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    context = _owner(request)
    try:
        return {"user": await access.update_staff(context, user_id, display_name=body.display_name, email=body.email)}
    except access.AccessControlError as exc:
        _raise(exc)


@router.post("/staff/{user_id}/roles")
async def assign_roles(body: RoleAssignmentRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    context = _owner(request)
    try:
        return {"user": await access.assign_roles(context, user_id, body.role_codes)}
    except access.AccessControlError as exc:
        _raise(exc)


async def _status_action(action: str, user_id: str, body: SessionRevokeRequest, request: Request) -> dict[str, Any]:
    context = _owner(request)
    try:
        return {"user": await access.change_staff_status(context, user_id, action, reason=body.reason)}
    except access.AccessControlError as exc:
        _raise(exc)


@router.post("/staff/{user_id}/suspend")
async def suspend_staff(body: SessionRevokeRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    return await _status_action("SUSPEND", user_id, body, request)


@router.post("/staff/{user_id}/disable")
async def disable_staff(body: SessionRevokeRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    return await _status_action("DISABLE", user_id, body, request)


@router.post("/staff/{user_id}/reactivate")
async def reactivate_staff(body: SessionRevokeRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    return await _status_action("REACTIVATE", user_id, body, request)


@router.post("/staff/{user_id}/terminate")
async def terminate_staff(body: SessionRevokeRequest, request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    return await _status_action("TERMINATE", user_id, body, request)


@router.post("/staff/{user_id}/reset")
async def reset_staff_password(request: Request, user_id: str = Path(min_length=1, max_length=100)) -> dict[str, Any]:
    context = _owner(request)
    try:
        return await access.issue_password_reset(context, user_id)
    except access.AccessControlError as exc:
        _raise(exc)


@router.get("/roles")
async def list_roles(request: Request) -> dict[str, Any]:
    _context(request)
    return {"roles": await access.list_roles(), "permissions": await access.list_permissions()}


@router.put("/roles/{role_code}/permissions")
async def set_role_permissions(body: RolePermissionsRequest, request: Request, role_code: str = Path(min_length=1, max_length=80)) -> dict[str, Any]:
    context = _owner(request)
    try:
        return {"roles": await access.set_role_permissions(context, role_code, body.permission_codes)}
    except access.AccessControlError as exc:
        _raise(exc)


@router.get("/sessions")
async def list_sessions(request: Request) -> dict[str, Any]:
    _owner(request)
    return {"sessions": await access.list_sessions(active_only=True)}


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(body: SessionRevokeRequest, request: Request, session_id: str = Path(min_length=1, max_length=120)) -> dict[str, bool]:
    context = _owner(request)
    try:
        await access.revoke_session(context, session_id, body.reason)
    except access.AccessControlError as exc:
        _raise(exc)
    return {"ok": True}


@router.get("/audit")
async def audit(
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    event_type: str | None = Query(default=None, max_length=80),
) -> dict[str, Any]:
    _owner(request)
    return {"events": await access.list_audit_events(limit=limit, event_type=event_type)}
