"""HTTP authentication, CSRF, route classification, and permission policy."""

from __future__ import annotations

import contextvars
import hmac
from urllib.parse import urlsplit
from typing import Any, Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from agent.services.access_control_service import (
    AuthContext,
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    has_human_accounts,
    load_session_context,
    write_audit_event,
)

_AUTH_CONTEXT: contextvars.ContextVar[AuthContext | None] = contextvars.ContextVar(
    "bosmax_auth_context", default=None
)

PUBLIC_AUTH_PREFIX = "/api/auth/"
PROVENANCE_PATHS = frozenset(
    {
        "/health",
        "/api/local-agent/version-proof",
        "/api/operator/runtime-storage-status",
        "/api/flow/bind-check",
    }
)

# These are service/transport or health surfaces. They are deliberately
# explicit: a human-facing /api route is protected by default below.
INTERNAL_ROUTE_PREFIXES = (
    "/api/ext/",
    "/api/local-agent/capture-video-payload",
    "/api/local-agent/status",
    "/api/local-agent/registration",
    "/api/local-agent/repair",
    "/api/operator/content-pack",
    "/api/telemetry/stage",
    "/api/flow/materialize-remote-file",
    "/api/flow/materialize-local-file",
    "/api/assets/product-images/",
)

MODULE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/system/staff-access", "staff"),
    ("/api/staff", "staff"),
    ("/api/roles", "roles"),
    ("/api/sessions", "sessions"),
    ("/api/access-audit", "audit"),
    ("/api/reporting", "reporting"),
    ("/api/ai-providers", "provider"),
    ("/api/postiz", "publishing"),
    ("/api/social-copy-packages", "copy"),
    ("/api/copy", "copy"),
    ("/api/copy-", "copy"),
    ("/api/copywriting", "copy"),
    ("/api/storyboard", "copy"),
    ("/api/landbank", "copy"),
    ("/api/prompt", "copy"),
    ("/api/creative-treatments", "copy"),
    ("/api/creative-supply", "copy"),
    ("/api/products", "products"),
    ("/api/product-", "products"),
    ("/api/characters", "products"),
    ("/api/projects", "products"),
    ("/api/videos", "products"),
    ("/api/scenes", "products"),
    ("/api/materials", "products"),
    ("/api/taxonomy", "products"),
    ("/api/product_truth", "products"),
    ("/api/fastmoss", "products"),
    ("/api/kalodata", "products"),
    ("/api/asset", "assets"),
    ("/api/creative-assets", "assets"),
    ("/api/scene-context", "assets"),
    ("/api/workspace/avatar-registry", "assets"),
    ("/api/results", "assets"),
    ("/api/flow/artifacts", "assets"),
    ("/api/poster", "poster"),
    ("/api/img-factory", "assets"),
    ("/api/faceless", "production"),
    ("/api/montage", "production"),
    ("/api/creative-production", "production"),
    ("/api/workspace/production-queue", "jobs"),
    ("/api/workspace", "production"),
    ("/api/bulk", "jobs"),
    ("/api/bulk-generation", "jobs"),
    ("/api/batches", "jobs"),
    ("/api/production-queue", "jobs"),
    ("/api/flow", "production"),
    ("/api/execution-approval", "production"),
    ("/api/reviews", "production"),
    ("/api/tts", "production"),
    ("/api/music", "production"),
    ("/api/telemetry", "reporting"),
    ("/api/operator", "production"),
    ("/api/jobs", "jobs"),
)


def _path_has_prefix(path: str, prefix: str) -> bool:
    base = prefix.rstrip("/") or "/"
    if base.endswith(("-", "_")):
        return path.startswith(base)
    return path == base or path.startswith(f"{base}/")


def classify_route(path: str) -> str:
    normalized = path.rstrip("/") or "/"
    if normalized.startswith(PUBLIC_AUTH_PREFIX):
        return "A_PUBLIC_AUTH"
    if normalized in PROVENANCE_PATHS:
        return "D_HEALTH_PROVENANCE"
    if any(_path_has_prefix(normalized, prefix) for prefix in INTERNAL_ROUTE_PREFIXES):
        return "C_INTERNAL_SERVICE"
    if normalized.startswith("/api/"):
        return "B_AUTHENTICATED_HUMAN"
    return "D_HEALTH_PROVENANCE"


def _module_for_path(path: str) -> str | None:
    normalized = path.rstrip("/") or "/"
    for prefix, module in MODULE_PREFIXES:
        if _path_has_prefix(normalized, prefix):
            return module
    return None


def _action_for_path(path: str, method: str, module: str) -> str:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    lower_path = path.casefold()
    if any(marker in lower_path for marker in ("/approve", "/approval", "/publish")):
        return "approve" if module in {"copy", "production", "poster"} else "execute"
    if "/unarchive" in lower_path:
        return "archive"
    if any(marker in lower_path for marker in ("/archive", "/delete", "/retire", "/remove")):
        return "archive"
    if any(marker in lower_path for marker in ("/start", "/generate", "/execute", "/dispatch", "/compose", "/commit", "/fire")):
        if module == "publishing":
            return "execute"
        if module == "jobs":
            return "control"
        if module == "poster" and "/compose" in lower_path:
            return "create"
        if module == "production":
            return "execute"
    if method == "POST":
        if module == "production":
            return "plan"
        if module == "jobs":
            return "control"
        return "create"
    return "update"


def required_permission(path: str, method: str) -> str:
    normalized = path.rstrip("/") or "/"
    upper_method = method.upper()
    # Visual Truth approval remains a Product Truth update, not a production
    # execution permission. The endpoint performs its stricter OWNER role check
    # in the handler after middleware authentication.
    if _path_has_prefix(normalized, "/api/product-visual-onboarding/review-queue/approve-selected"):
        return "products.update"
    # Product release is a separate owner-governed authority.  It must never
    # inherit products.create/update from the generic /api/product-* mapper.
    if _path_has_prefix(normalized, "/api/product-release"):
        return "products.release"
    if _path_has_prefix(normalized, "/api/system/staff-access"):
        if "/roles" in normalized:
            return "roles.read" if upper_method == "GET" else "roles.manage"
        if "/sessions" in normalized:
            return "sessions.read" if upper_method == "GET" else "sessions.revoke"
        if "/audit" in normalized:
            return "audit.read"
        return "staff.read" if upper_method in {"GET", "HEAD"} else "staff.manage"
    if _path_has_prefix(normalized, "/api/staff"):
        return "staff.read" if upper_method in {"GET", "HEAD"} else "staff.manage"
    if _path_has_prefix(normalized, "/api/ai-providers"):
        return "provider.read" if upper_method in {"GET", "HEAD"} else "provider.manage"
    module = _module_for_path(normalized)
    if module is None:
        # Unknown human API paths fail closed instead of inheriting a broad role.
        return "system.settings.manage"
    action = _action_for_path(normalized, upper_method, module)
    return f"{module}.{action}"


def get_current_auth_context() -> AuthContext | None:
    return _AUTH_CONTEXT.get()


async def resolve_request_staff(staff_id: Any) -> dict[str, Any]:
    """Resolve production staff from the authenticated session.

    The no-context branch exists only for isolated service/router unit tests and
    non-HTTP worker calls. The main HTTP middleware always installs a context for
    human-facing requests before production handlers execute.
    """

    from agent.services.staff_identity_service import (
        StaffIdentityError,
        resolve_staff_identity,
    )

    context = get_current_auth_context()
    candidate = str(staff_id or "").strip()
    if context is not None:
        if candidate and candidate != context.staff_id:
            raise StaffIdentityError(
                "STAFF_IDENTITY_SPOOF_ATTEMPT",
                "Production attribution must match the authenticated staff session.",
                status_code=403,
            )
        return context.staff_profile
    return await resolve_staff_identity(candidate)


_LOCAL_DASHBOARD_ORIGINS = frozenset(
    {
        "http://localhost:8100",
        "http://127.0.0.1:8100",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
)


def _same_origin_or_local_dev(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin:
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        # SameSite cookies are shared by local ports. Accept only the API and
        # dashboard origins we explicitly ship; an arbitrary localhost page
        # must not be able to CSRF bootstrap, login, or mutate a session.
        return origin == expected or origin in _LOCAL_DASHBOARD_ORIGINS
    referer = request.headers.get("referer")
    if referer:
        try:
            parsed = urlsplit(referer)
            referer_origin = f"{parsed.scheme}://{parsed.netloc}"
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            return referer_origin == expected or referer_origin in _LOCAL_DASHBOARD_ORIGINS
        except ValueError:
            return False
    return False


def csrf_valid(request: Request) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_token = request.headers.get("x-csrf-token", "")
    if cookie_token and header_token and hmac.compare_digest(cookie_token, header_token):
        return True
    # Same-origin fetches carry Origin/Referer and are safe for the browser UI;
    # the double-submit token remains the path used by the explicit client.
    return _same_origin_or_local_dev(request)


def _error(status_code: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": code, "message": message, **extra},
    )


async def _record_permission_denied(context: AuthContext, path: str, method: str, permission: str) -> None:
    try:
        from agent.db.schema import _db_lock
        from agent.db.schema import get_db

        db = await get_db()
        async with _db_lock:
            await write_audit_event(
                db,
                "PERMISSION_DENIED",
                actor=context,
                success=False,
                metadata={"method": method, "path": path, "required_permission": permission},
            )
            await db.commit()
    except Exception:
        # Access denial is already fail-closed; audit persistence must not turn a
        # safe 403 into a server error.
        return


async def access_control_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Any]],
):
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    route_class = classify_route(request.url.path)
    is_mutation = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    if route_class == "A_PUBLIC_AUTH":
        if is_mutation and not csrf_valid(request):
            return _error(403, "CSRF_REQUIRED", "A valid same-origin CSRF proof is required.")
        return await call_next(request)
    if route_class in {"C_INTERNAL_SERVICE", "D_HEALTH_PROVENANCE"}:
        return await call_next(request)

    context = await load_session_context(request.cookies.get(SESSION_COOKIE_NAME))
    if context is None:
        setup_required = not await has_human_accounts()
        return _error(
            428 if setup_required else 401,
            "SETUP_REQUIRED" if setup_required else "AUTHENTICATION_REQUIRED",
            "Complete first-owner setup before using BOSMAX." if setup_required else "Sign in to use this BOSMAX API.",
            setup_required=setup_required,
        )
    permission = required_permission(request.url.path, request.method)
    if permission not in context.permission_codes:
        await _record_permission_denied(context, request.url.path, request.method, permission)
        return _error(403, "PERMISSION_DENIED", "The authenticated role cannot perform this action.", permission=permission)
    if is_mutation:
        from agent.services.access_control_service import session_csrf_valid

        if not await session_csrf_valid(
            request.cookies.get(SESSION_COOKIE_NAME),
            request.headers.get("x-csrf-token", ""),
        ):
            return _error(403, "CSRF_REQUIRED", "A valid session-bound CSRF proof is required.")
    request.state.auth_context = context
    token = _AUTH_CONTEXT.set(context)
    try:
        return await call_next(request)
    finally:
        _AUTH_CONTEXT.reset(token)
