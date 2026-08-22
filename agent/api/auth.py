from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, Request, Response

from agent.models.access_control import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordTokenRequest,
    SetupOwnerRequest,
)
from agent.security.access_control import get_current_auth_context
from agent.services import access_control_service as access

router = APIRouter(prefix="/auth", tags=["authentication"])


def _raise(exc: access.AccessControlError) -> None:
    from fastapi import HTTPException

    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message},
    ) from exc


def _secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https" or os.environ.get("BOSMAX_COOKIE_SECURE") == "1"


def _set_auth_cookies(response: Response, request: Request, result: dict[str, Any]) -> None:
    response.set_cookie(
        access.SESSION_COOKIE_NAME,
        str(result["session_token"]),
        max_age=access.SESSION_TTL_SECONDS,
        httponly=True,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        access.CSRF_COOKIE_NAME,
        str(result["csrf_token"]),
        max_age=access.SESSION_TTL_SECONDS,
        httponly=False,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )


def _safe_session_response(result: dict[str, Any]) -> dict[str, Any]:
    # Raw session/CSRF tokens are set only as cookies and never returned in the
    # JSON body, logs, audit records, or persistent database fields.
    return {"authenticated": True, "user": result["user"], "session": result["session"]}


@router.get("/csrf")
async def csrf(request: Request, response: Response) -> dict[str, bool]:
    csrf_token = secrets.token_urlsafe(32)
    await access.rotate_session_csrf_token(
        request.cookies.get(access.SESSION_COOKIE_NAME),
        csrf_token,
    )
    response.set_cookie(
        access.CSRF_COOKIE_NAME,
        csrf_token,
        max_age=access.SESSION_TTL_SECONDS,
        httponly=False,
        secure=_secure_cookie(request),
        samesite="lax",
        path="/",
    )
    return {"ok": True}

@router.get("/bootstrap-status")
async def bootstrap_status() -> dict[str, bool]:
    return await access.bootstrap_status()


@router.get("/current-session")
@router.get("/me")
async def current_session(request: Request, response: Response) -> dict[str, Any]:
    status = await access.bootstrap_status()
    context = await access.load_session_context(
        request.cookies.get(access.SESSION_COOKIE_NAME), touch=False
    )
    if context is None:
        return {
            "authenticated": False,
            "setup_required": status["setup_required"],
            "user": None,
        }
    return {
        "authenticated": True,
        "setup_required": False,
        "user": context.to_safe_dict(),
    }


@router.post("/setup-owner")
async def setup_owner(body: SetupOwnerRequest, request: Request, response: Response) -> dict[str, Any]:
    try:
        result = await access.setup_owner(
            display_name=body.display_name,
            email=body.email,
            password=body.password,
            password_confirmation=body.password_confirmation,
        )
    except access.AccessControlError as exc:
        _raise(exc)
    _set_auth_cookies(response, request, result)
    return _safe_session_response(result)


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    try:
        result = await access.login(email=body.email, password=body.password)
    except access.AccessControlError as exc:
        _raise(exc)
    _set_auth_cookies(response, request, result)
    return _safe_session_response(result)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    context = await access.load_session_context(
        request.cookies.get(access.SESSION_COOKIE_NAME), touch=False
    )
    await access.logout(context)
    response.delete_cookie(access.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(access.CSRF_COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/activate-account")
@router.post("/reset-password")
async def complete_password_token_flow(body: PasswordTokenRequest, request: Request, response: Response) -> dict[str, Any]:
    try:
        result = await access.complete_token_flow(
            token=body.token,
            password=body.password,
            password_confirmation=body.password_confirmation,
        )
    except access.AccessControlError as exc:
        _raise(exc)
    _set_auth_cookies(response, request, result)
    return _safe_session_response(result)


@router.post("/change-password")
async def change_password(body: ChangePasswordRequest, request: Request) -> dict[str, bool]:
    context = get_current_auth_context() or await access.load_session_context(
        request.cookies.get(access.SESSION_COOKIE_NAME), touch=False
    )
    if context is None:
        _raise(
            access.AccessControlError(
                "AUTHENTICATION_REQUIRED", "Sign in to change a password.", status_code=401
            )
        )
    try:
        await access.change_password(
            context,
            current_password=body.current_password,
            password=body.password,
            password_confirmation=body.password_confirmation,
        )
    except access.AccessControlError as exc:
        _raise(exc)
    return {"ok": True}
