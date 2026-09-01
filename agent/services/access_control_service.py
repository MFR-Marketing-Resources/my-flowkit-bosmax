"""Human account, session, role, and access-audit authority.

The service deliberately keeps UserAccount separate from StaffProfile. A
StaffProfile is the durable production attribution identity; this module owns
authentication and access authority that may be revoked without deleting that
historical identity.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from agent.access_control_constants import PERMISSION_CODES, ROLE_CODES
from agent.config import BASE_DIR
from agent.db.schema import _db_lock, atomic, get_db

SESSION_COOKIE_NAME = "bosmax_session"
CSRF_COOKIE_NAME = "bosmax_csrf"
FLOW_DISPATCHER_TOKEN_FILE = BASE_DIR / ".local-agent" / "bot4-flow-dispatcher.token"
SESSION_TTL_SECONDS = max(900, int(os.environ.get("BOSMAX_SESSION_TTL_SECONDS", "28800")))
SETUP_TOKEN_TTL_SECONDS = max(
    300, int(os.environ.get("BOSMAX_SETUP_TOKEN_TTL_SECONDS", "86400"))
)

_PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_AUDIT_SECRET_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "raw",
    "hash",
)


class AccessControlError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class AuthContext:
    session_id: str
    user_id: str
    staff_id: str
    display_name: str
    email: str
    account_status: str
    staff_active: bool
    role_codes: tuple[str, ...]
    permission_codes: frozenset[str]
    created_at: str
    expires_at: str
    last_seen_at: str

    @property
    def staff_profile(self) -> dict[str, Any]:
        return {
            "staff_id": self.staff_id,
            "display_name": self.display_name,
            "active": self.staff_active,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "staff_id": self.staff_id,
            "display_name": self.display_name,
            "email": self.email,
            "account_status": self.account_status,
            "staff_active": self.staff_active,
            "role_codes": list(self.role_codes),
            "permissions": sorted(self.permission_codes),
            "session": {
                "session_id": self.session_id,
                "created_at": self.created_at,
                "expires_at": self.expires_at,
                "last_seen_at": self.last_seen_at,
            },
        }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _future(seconds: int) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_email(value: Any) -> str:
    email = _text(value).casefold()
    if not email or len(email) > 320 or not _EMAIL_RE.fullmatch(email):
        raise AccessControlError("EMAIL_INVALID", "Enter a valid staff email address.")
    return email


def normalize_display_name(value: Any) -> str:
    display_name = _text(value)
    if not display_name or len(display_name) > 160:
        raise AccessControlError(
            "DISPLAY_NAME_INVALID", "A human display name is required."
        )
    from agent.services.staff_identity_service import is_generic_staff_id

    if is_generic_staff_id(display_name):
        raise AccessControlError(
            "DISPLAY_NAME_INVALID", "Generic/system labels cannot be staff names."
        )
    return display_name


def validate_password(password: Any) -> str:
    value = str(password or "")
    if len(value) < 12 or len(value) > 256:
        raise AccessControlError(
            "PASSWORD_POLICY_FAILED",
            "Password must be between 12 and 256 characters.",
        )
    if not re.search(r"[a-z]", value) or not re.search(r"[A-Z]", value):
        raise AccessControlError(
            "PASSWORD_POLICY_FAILED",
            "Password must include upper- and lower-case characters.",
        )
    if not re.search(r"\d", value):
        raise AccessControlError(
            "PASSWORD_POLICY_FAILED", "Password must include a number."
        )
    return value


def validate_password_pair(password: Any, confirmation: Any) -> str:
    value = validate_password(password)
    if not hmac.compare_digest(value, str(confirmation or "")):
        raise AccessControlError(
            "PASSWORD_CONFIRMATION_MISMATCH", "Password confirmation does not match."
        )
    return value


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        # Deliberately perform a real Argon2id operation for accounts without a
        # credential too, without embedding a password in source.
        _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
        return False
    try:
        return bool(_PASSWORD_HASHER.verify(password_hash, password))
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(password_hash))
    except (InvalidHashError, ValueError):
        return False


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _sanitize_metadata(value: Any, key: str = "") -> Any:
    key_lower = key.casefold()
    if any(part in key_lower for part in _AUDIT_SECRET_KEY_PARTS):
        return None
    if isinstance(value, dict):
        return {
            str(item_key): sanitized
            for item_key, item_value in value.items()
            if (sanitized := _sanitize_metadata(item_value, str(item_key))) is not None
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def write_audit_event(
    db: Any,
    event_type: str,
    *,
    actor: AuthContext | None = None,
    target_user_id: str | None = None,
    target_staff_id: str | None = None,
    success: bool = True,
    metadata: dict[str, Any] | None = None,
) -> None:
    safe_metadata = _sanitize_metadata(metadata or {})
    await db.execute(
        "INSERT INTO access_audit_event "
        "(event_id, event_type, actor_user_id, actor_staff_id, target_user_id, "
        "target_staff_id, success, metadata_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            _new_id("audit"),
            event_type,
            actor.user_id if actor else None,
            actor.staff_id if actor else None,
            target_user_id,
            target_staff_id,
            int(success),
            json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True),
            _now(),
        ),
    )


async def has_human_accounts() -> bool:
    db = await get_db()
    row = await (await db.execute("SELECT COUNT(*) FROM user_account")).fetchone()
    return bool(row and int(row[0]) > 0)


async def bootstrap_status() -> dict[str, bool]:
    configured = await has_human_accounts()
    return {"setup_required": not configured, "configured": configured}


async def _load_user_row(db: Any, *, user_id: str | None = None, email: str | None = None):
    if user_id:
        cursor = await db.execute(
            "SELECT ua.*, sp.display_name, sp.active AS staff_active "
            "FROM user_account ua JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
            "WHERE ua.user_id=?",
            (user_id,),
        )
    else:
        cursor = await db.execute(
            "SELECT ua.*, sp.display_name, sp.active AS staff_active "
            "FROM user_account ua JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
            "WHERE ua.email=? COLLATE NOCASE",
            (email,),
        )
    return await cursor.fetchone()


async def _permissions_for_user(db: Any, user_id: str) -> tuple[tuple[str, ...], frozenset[str]]:
    cursor = await db.execute(
        "SELECT DISTINCT r.role_code, p.permission_code "
        "FROM user_role ur "
        "JOIN role r ON r.role_id=ur.role_id "
        "LEFT JOIN role_permission rp ON rp.role_id=r.role_id "
        "LEFT JOIN permission p ON p.permission_id=rp.permission_id "
        "WHERE ur.user_id=? AND ur.revoked_at IS NULL "
        "ORDER BY r.role_code, p.permission_code",
        (user_id,),
    )
    rows = await cursor.fetchall()
    roles = tuple(sorted({str(row[0]) for row in rows if row[0]}))
    permissions = frozenset(str(row[1]) for row in rows if row[1])
    return roles, permissions


async def load_session_context(raw_token: str | None, *, touch: bool = True) -> AuthContext | None:
    token = _text(raw_token)
    if len(token) < 32:
        return None
    token_hash = hash_session_token(token)
    db = await get_db()
    cursor = await db.execute(
        "SELECT s.session_id, s.user_id, s.created_at, s.expires_at, s.last_seen_at, "
        "ua.email, ua.account_status, ua.last_login_at, sp.staff_id, sp.display_name, "
        "sp.active AS staff_active "
        "FROM auth_session s "
        "JOIN user_account ua ON ua.user_id=s.user_id "
        "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
        "WHERE s.token_hash=? AND s.revoked_at IS NULL",
        (token_hash,),
    )
    row = await cursor.fetchone()
    if not row:
        return None
    now = _now()
    if str(row[3]) <= now or str(row[6]) != "ACTIVE" or not bool(row[10]):
        return None
    last_seen = str(row[4] or "")
    if touch:
        # Avoid a write on every dashboard poll while retaining useful session
        # activity for owner review.
        should_touch = True
        try:
            previous = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            should_touch = (
                datetime.now(timezone.utc) - previous
            ).total_seconds() >= 60
        except ValueError:
            pass
        if should_touch:
            async with _db_lock:
                await db.execute(
                    "UPDATE auth_session SET last_seen_at=? WHERE session_id=? AND revoked_at IS NULL",
                    (now, str(row[0])),
                )
                await db.commit()
            last_seen = now
    roles, permissions = await _permissions_for_user(db, str(row[1]))
    return AuthContext(
        session_id=str(row[0]),
        user_id=str(row[1]),
        staff_id=str(row[8]),
        display_name=str(row[9]),
        email=str(row[5]),
        account_status=str(row[6]),
        staff_active=bool(row[10]),
        role_codes=roles,
        permission_codes=permissions,
        created_at=str(row[2]),
        expires_at=str(row[3]),
        last_seen_at=last_seen,
    )


async def load_flow_dispatcher_context(raw_token: str | None) -> AuthContext | None:
    """Resolve an owner-approved, narrowly scoped Flow dispatcher credential."""
    token = _text(raw_token)
    if len(token) < 32:
        return None
    db = await get_db()
    cursor = await db.execute(
        "SELECT t.token_id, t.created_by_user_id, t.created_at, t.last_used_at, "
        "ua.email, ua.account_status, sp.staff_id, sp.display_name, sp.active "
        "FROM auth_service_token t "
        "JOIN user_account ua ON ua.user_id=t.created_by_user_id "
        "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
        "WHERE t.token_hash=? AND t.scope='FLOW_DISPATCHER' AND t.revoked_at IS NULL",
        (hash_session_token(token),),
    )
    row = await cursor.fetchone()
    if not row or str(row[5]) != "ACTIVE" or not bool(row[8]):
        return None
    roles, permissions = await _permissions_for_user(db, str(row[1]))
    if "OWNER" not in roles:
        return None
    now = _now()
    async with _db_lock:
        await db.execute(
            "UPDATE auth_service_token SET last_used_at=? WHERE token_id=? AND revoked_at IS NULL",
            (now, str(row[0])),
        )
        await write_audit_event(
            db,
            "FLOW_DISPATCHER_TOKEN_USED",
            target_user_id=str(row[1]),
            target_staff_id=str(row[6]),
            metadata={"token_id": str(row[0]), "scope": "FLOW_DISPATCHER"},
        )
        await db.commit()
    return AuthContext(
        session_id=str(row[0]),
        user_id=str(row[1]),
        staff_id=str(row[6]),
        display_name=str(row[7]),
        email=str(row[4]),
        account_status=str(row[5]),
        staff_active=bool(row[8]),
        role_codes=roles,
        permission_codes=permissions,
        created_at=str(row[2]),
        expires_at="SERVICE_TOKEN",
        last_seen_at=now,
    )


def _require_owner(context: AuthContext | None) -> AuthContext:
    if context is None:
        raise AccessControlError("AUTHENTICATION_REQUIRED", "Sign in as an owner.", status_code=401)
    if "OWNER" not in context.role_codes:
        raise AccessControlError("OWNER_REQUIRED", "Only an owner can manage Bot 4 access.", status_code=403)
    return context


async def approve_flow_dispatcher(context: AuthContext | None) -> dict[str, Any]:
    """Rotate the local Bot 4 credential and persist only its hash in SQLite."""
    owner = _require_owner(context)
    raw_token = secrets.token_urlsafe(48)
    token_id = _new_id("svc")
    now = _now()
    async with atomic() as db:
        await db.execute(
            "UPDATE auth_service_token SET revoked_at=?, revoke_reason=? "
            "WHERE scope='FLOW_DISPATCHER' AND revoked_at IS NULL",
            (now, "OWNER_ROTATED"),
        )
        await db.execute(
            "INSERT INTO auth_service_token "
            "(token_id, label, token_hash, scope, created_by_user_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (token_id, "Bot 4 Generation Dispatcher", hash_session_token(raw_token), "FLOW_DISPATCHER", owner.user_id, now),
        )
        await write_audit_event(
            db,
            "FLOW_DISPATCHER_APPROVED",
            actor=owner,
            metadata={"token_id": token_id, "scope": "FLOW_DISPATCHER"},
        )
    FLOW_DISPATCHER_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    FLOW_DISPATCHER_TOKEN_FILE.write_text(raw_token, encoding="utf-8")
    try:
        os.chmod(FLOW_DISPATCHER_TOKEN_FILE, 0o600)
    except OSError:
        pass
    return {
        "approved": True,
        "token_id": token_id,
        "label": "Bot 4 Generation Dispatcher",
        "scope": "FLOW_DISPATCHER",
        "created_at": now,
        "credential_file": str(FLOW_DISPATCHER_TOKEN_FILE),
    }


async def flow_dispatcher_status(context: AuthContext | None) -> dict[str, Any]:
    _require_owner(context)
    db = await get_db()
    row = await (
        await db.execute(
            "SELECT token_id, label, created_at, last_used_at FROM auth_service_token "
            "WHERE scope='FLOW_DISPATCHER' AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1"
        )
    ).fetchone()
    return {
        "approved": bool(row),
        "credential_file_present": FLOW_DISPATCHER_TOKEN_FILE.is_file(),
        "token": None if not row else {
            "token_id": str(row[0]), "label": str(row[1]),
            "created_at": str(row[2]), "last_used_at": row[3],
            "scope": "FLOW_DISPATCHER",
        },
    }


async def revoke_flow_dispatcher(context: AuthContext | None) -> dict[str, bool]:
    owner = _require_owner(context)
    now = _now()
    async with atomic() as db:
        await db.execute(
            "UPDATE auth_service_token SET revoked_at=?, revoke_reason=? "
            "WHERE scope='FLOW_DISPATCHER' AND revoked_at IS NULL",
            (now, "OWNER_REVOKED"),
        )
        await write_audit_event(db, "FLOW_DISPATCHER_REVOKED", actor=owner)
    try:
        FLOW_DISPATCHER_TOKEN_FILE.unlink(missing_ok=True)
    except OSError as exc:
        raise AccessControlError("CREDENTIAL_FILE_REMOVE_FAILED", str(exc), status_code=500) from exc
    return {"revoked": True}


async def session_csrf_valid(raw_session_token: str | None, raw_csrf_token: str | None) -> bool:
    """Validate a mutation token against the active session's stored hash."""
    session_token = _text(raw_session_token)
    csrf_token = _text(raw_csrf_token)
    if len(session_token) < 32 or len(csrf_token) < 16:
        return False
    db = await get_db()
    cursor = await db.execute(
        "SELECT csrf_token_hash FROM auth_session "
        "WHERE token_hash=? AND revoked_at IS NULL",
        (hash_session_token(session_token),),
    )
    row = await cursor.fetchone()
    return bool(row and hmac.compare_digest(str(row[0] or ""), hash_session_token(csrf_token)))


async def rotate_session_csrf_token(
    raw_session_token: str | None,
    raw_csrf_token: str,
) -> bool:
    """Rotate the browser CSRF token while it remains bound to its session."""
    session_token = _text(raw_session_token)
    csrf_token = _text(raw_csrf_token)
    if len(session_token) < 32 or len(csrf_token) < 16:
        return False
    db = await get_db()
    async with _db_lock:
        cursor = await db.execute(
            "UPDATE auth_session SET csrf_token_hash=? "
            "WHERE token_hash=? AND revoked_at IS NULL",
            (hash_session_token(csrf_token), hash_session_token(session_token)),
        )
        await db.commit()
    return bool(cursor.rowcount)


async def _create_session_in_db(db: Any, user_id: str) -> tuple[str, str, dict[str, str]]:
    raw_token = secrets.token_urlsafe(32)
    raw_csrf = secrets.token_urlsafe(32)
    session_id = _new_id("sess")
    now = _now()
    expires_at = _future(SESSION_TTL_SECONDS)
    await db.execute(
        "INSERT INTO auth_session "
        "(session_id, user_id, token_hash, csrf_token_hash, created_at, expires_at, last_seen_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            session_id,
            user_id,
            hash_session_token(raw_token),
            hash_session_token(raw_csrf),
            now,
            expires_at,
            now,
        ),
    )
    return raw_token, raw_csrf, {
        "session_id": session_id,
        "created_at": now,
        "expires_at": expires_at,
        "last_seen_at": now,
    }


async def _safe_user(db: Any, user_id: str) -> dict[str, Any]:
    row = await _load_user_row(db, user_id=user_id)
    if not row:
        raise AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404)
    roles, permissions = await _permissions_for_user(db, user_id)
    return {
        "user_id": str(row["user_id"]),
        "staff_id": str(row["staff_id"]),
        "display_name": str(row["display_name"]),
        "email": str(row["email"]),
        "account_status": str(row["account_status"]),
        "staff_active": bool(row["staff_active"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "last_login_at": row["last_login_at"],
        "terminated_at": row["terminated_at"],
        "role_codes": list(roles),
        "permissions": sorted(permissions),
    }


async def _validate_role_codes(db: Any, role_codes: list[str] | tuple[str, ...]) -> list[str]:
    normalized = []
    for code in role_codes:
        value = _text(code).upper()
        if value == "SYSTEM" or value not in ROLE_CODES:
            raise AccessControlError("ROLE_INVALID", "Only built-in human roles may be assigned.")
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise AccessControlError("ROLE_REQUIRED", "At least one human role is required.")
    cursor = await db.execute(
        f"SELECT role_code FROM role WHERE role_code IN ({','.join('?' for _ in normalized)})",
        tuple(normalized),
    )
    found = {str(row[0]).upper() for row in await cursor.fetchall()}
    if found != set(normalized):
        raise AccessControlError("ROLE_INVALID", "Requested role is not configured.")
    return normalized


async def _assign_roles_in_db(
    db: Any,
    user_id: str,
    role_codes: list[str],
    *,
    actor_user_id: str | None,
) -> None:
    now = _now()
    role_ids = {f"role_{code.lower()}" for code in role_codes}
    cursor = await db.execute(
        "SELECT role_id FROM user_role WHERE user_id=? AND revoked_at IS NULL",
        (user_id,),
    )
    current = {str(row[0]) for row in await cursor.fetchall()}
    for role_code in role_codes:
        role_id = f"role_{role_code.lower()}"
        await db.execute(
            "INSERT INTO user_role (user_id, role_id, assigned_by_user_id, assigned_at, revoked_at) "
            "VALUES (?,?,?,?,NULL) "
            "ON CONFLICT(user_id, role_id) DO UPDATE SET "
            "assigned_by_user_id=excluded.assigned_by_user_id, assigned_at=excluded.assigned_at, revoked_at=NULL",
            (user_id, role_id, actor_user_id, now),
        )
    for stale_role_id in current - role_ids:
        await db.execute(
            "UPDATE user_role SET revoked_at=? WHERE user_id=? AND role_id=? AND revoked_at IS NULL",
            (now, user_id, stale_role_id),
        )


async def _active_owner_count(db: Any) -> int:
    row = await (
        await db.execute(
            "SELECT COUNT(*) FROM user_account ua "
            "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
            "JOIN user_role ur ON ur.user_id=ua.user_id AND ur.revoked_at IS NULL "
            "JOIN role r ON r.role_id=ur.role_id AND r.role_code='OWNER' "
            "WHERE ua.account_status='ACTIVE' AND sp.active=1"
        )
    ).fetchone()
    return int(row[0] if row else 0)


async def _target_has_active_owner_role(db: Any, user_id: str) -> bool:
    row = await (
        await db.execute(
            "SELECT 1 FROM user_account ua "
            "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
            "JOIN user_role ur ON ur.user_id=ua.user_id AND ur.revoked_at IS NULL "
            "JOIN role r ON r.role_id=ur.role_id AND r.role_code='OWNER' "
            "WHERE ua.user_id=? AND ua.account_status='ACTIVE' AND sp.active=1",
            (user_id,),
        )
    ).fetchone()
    return row is not None


async def _guard_last_owner(db: Any, user_id: str) -> None:
    if await _target_has_active_owner_role(db, user_id) and await _active_owner_count(db) <= 1:
        raise AccessControlError(
            "LAST_OWNER_PROTECTED",
            "The last active OWNER cannot be suspended, terminated, or demoted.",
            status_code=409,
        )


async def setup_owner(
    *, display_name: str, email: str, password: str, password_confirmation: str
) -> dict[str, Any]:
    # Once any human account exists, fail closed before validating caller
    # supplied fields. This keeps the bootstrap window permanently closed and
    # avoids using the endpoint as an account-existence oracle for malformed
    # second-owner submissions.
    if await has_human_accounts():
        raise AccessControlError(
            "OWNER_ALREADY_BOOTSTRAPPED",
            "The first-owner setup window is permanently closed.",
            status_code=409,
        )
    name = normalize_display_name(display_name)
    normalized_email = normalize_email(email)
    validated_password = validate_password_pair(password, password_confirmation)
    password_hash = hash_password(validated_password)
    async with atomic() as db:
        count_row = await (await db.execute("SELECT COUNT(*) FROM user_account")).fetchone()
        if count_row and int(count_row[0]) > 0:
            raise AccessControlError(
                "OWNER_ALREADY_BOOTSTRAPPED",
                "The first-owner setup window is permanently closed.",
                status_code=409,
            )
        staff_id = _new_id("staff")
        user_id = _new_id("user")
        now = _now()
        await db.execute(
            "INSERT INTO staff_profile (staff_id, display_name, active, created_at, updated_at) "
            "VALUES (?,?,1,?,?)",
            (staff_id, name, now, now),
        )
        await db.execute(
            "INSERT INTO user_account "
            "(user_id, staff_id, email, password_hash, account_status, created_at, updated_at, last_login_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, staff_id, normalized_email, password_hash, "ACTIVE", now, now, now),
        )
        await db.execute(
            "INSERT INTO user_role (user_id, role_id, assigned_at) VALUES (?,?,?)",
            (user_id, "role_owner", now),
        )
        await write_audit_event(
            db,
            "FIRST_OWNER_CREATED",
            target_user_id=user_id,
            target_staff_id=staff_id,
            metadata={"role_code": "OWNER"},
        )
        raw_token, raw_csrf, session = await _create_session_in_db(db, user_id)
    return {
        "user": await _safe_user(await get_db(), user_id),
        "session_token": raw_token,
        "csrf_token": raw_csrf,
        "session": session,
    }


async def login(*, email: str, password: str) -> dict[str, Any]:
    normalized_email = normalize_email(email)
    db = await get_db()
    row = await _load_user_row(db, email=normalized_email)
    password_hash = str(row["password_hash"]) if row and row["password_hash"] else None
    valid_password = verify_password(password_hash, str(password or ""))
    available = bool(
        row
        and str(row["account_status"]) == "ACTIVE"
        and bool(row["staff_active"])
        and valid_password
    )
    if not available:
        async with _db_lock:
            await write_audit_event(
                db,
                "LOGIN_FAILURE",
                success=False,
                metadata={"reason": "INVALID_CREDENTIALS"},
            )
            await db.commit()
        if not await has_human_accounts():
            raise AccessControlError(
                "SETUP_REQUIRED",
                "No human owner exists yet.",
                status_code=428,
            )
        raise AccessControlError("LOGIN_FAILED", "Email or password was not accepted.", status_code=401)

    user_id = str(row["user_id"])
    async with atomic() as db:
        now = _now()
        await db.execute(
            "UPDATE user_account SET last_login_at=?, updated_at=? WHERE user_id=?",
            (now, now, user_id),
        )
        raw_token, raw_csrf, session = await _create_session_in_db(db, user_id)
        await write_audit_event(db, "LOGIN_SUCCESS", target_user_id=user_id)
    return {
        "user": await _safe_user(await get_db(), user_id),
        "session_token": raw_token,
        "csrf_token": raw_csrf,
        "session": session,
    }


async def logout(context: AuthContext | None) -> None:
    if not context:
        return
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE auth_session SET revoked_at=?, revoke_reason=? "
            "WHERE session_id=? AND revoked_at IS NULL",
            (_now(), "LOGOUT", context.session_id),
        )
        await write_audit_event(db, "LOGOUT", actor=context, target_user_id=context.user_id)
        await db.commit()


async def change_password(context: AuthContext, *, current_password: str, password: str, password_confirmation: str) -> None:
    validated_password = validate_password_pair(password, password_confirmation)
    db = await get_db()
    row = await _load_user_row(db, user_id=context.user_id)
    if not row or not verify_password(row["password_hash"], current_password):
        raise AccessControlError("PASSWORD_CURRENT_INVALID", "Current password was not accepted.", status_code=400)
    password_hash = hash_password(validated_password)
    async with atomic() as db:
        now = _now()
        await db.execute(
            "UPDATE user_account SET password_hash=?, credential_version=credential_version+1, "
            "updated_at=?, account_status='ACTIVE' WHERE user_id=?",
            (password_hash, now, context.user_id),
        )
        await db.execute(
            "UPDATE auth_session SET revoked_at=?, revoke_reason=? "
            "WHERE user_id=? AND session_id<>? AND revoked_at IS NULL",
            (now, "PASSWORD_CHANGED", context.user_id, context.session_id),
        )
        await write_audit_event(db, "PASSWORD_CHANGED", actor=context, target_user_id=context.user_id)


async def _issue_token_in_db(
    db: Any,
    *,
    user_id: str,
    token_type: str,
    created_by_user_id: str | None,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    await db.execute(
        "UPDATE auth_setup_token SET used_at=? WHERE user_id=? AND token_type=? AND used_at IS NULL",
        (_now(), user_id, token_type),
    )
    await db.execute(
        "INSERT INTO auth_setup_token "
        "(token_id, user_id, token_type, token_hash, created_at, expires_at, created_by_user_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            _new_id("setup"),
            user_id,
            token_type,
            hash_session_token(raw_token),
            _now(),
            _future(SETUP_TOKEN_TTL_SECONDS),
            created_by_user_id,
        ),
    )
    return raw_token


async def invite_staff(context: AuthContext, *, display_name: str, email: str, role_codes: list[str]) -> dict[str, Any]:
    name = normalize_display_name(display_name)
    normalized_email = normalize_email(email)
    async with atomic() as db:
        existing = await _load_user_row(db, email=normalized_email)
        if existing:
            raise AccessControlError("EMAIL_ALREADY_REGISTERED", "That staff email is already registered.", status_code=409)
        roles = await _validate_role_codes(db, role_codes)
        now = _now()
        staff_id = _new_id("staff")
        user_id = _new_id("user")
        await db.execute(
            "INSERT INTO staff_profile (staff_id, display_name, active, created_at, updated_at) VALUES (?,?,1,?,?)",
            (staff_id, name, now, now),
        )
        await db.execute(
            "INSERT INTO user_account "
            "(user_id, staff_id, email, password_hash, account_status, created_at, updated_at, invited_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (user_id, staff_id, normalized_email, None, "INVITED", now, now, now),
        )
        await _assign_roles_in_db(db, user_id, roles, actor_user_id=context.user_id)
        raw_token = await _issue_token_in_db(
            db,
            user_id=user_id,
            token_type="ACCOUNT_SETUP",
            created_by_user_id=context.user_id,
        )
        await write_audit_event(
            db,
            "ACCOUNT_CREATED",
            actor=context,
            target_user_id=user_id,
            target_staff_id=staff_id,
            metadata={"role_codes": roles},
        )
    return {
        "user": await _safe_user(await get_db(), user_id),
        "setup_token": raw_token,
        "setup_token_expires_at": _future(SETUP_TOKEN_TTL_SECONDS),
    }


async def complete_token_flow(*, token: str, password: str, password_confirmation: str) -> dict[str, Any]:
    validated_password = validate_password_pair(password, password_confirmation)
    token_hash = hash_session_token(_text(token))
    db = await get_db()
    cursor = await db.execute(
        "SELECT t.token_id, t.user_id, t.token_type, t.expires_at, t.used_at, "
        "ua.account_status, ua.staff_id, sp.active AS staff_active "
        "FROM auth_setup_token t JOIN user_account ua ON ua.user_id=t.user_id "
        "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
        "WHERE t.token_hash=?",
        (token_hash,),
    )
    row = await cursor.fetchone()
    if (
        not row
        or row[4]
        or str(row[3]) <= _now()
        or str(row[5]) != "INVITED"
        or not bool(row[7])
    ):
        raise AccessControlError("TOKEN_INVALID_OR_EXPIRED", "The setup/reset token is invalid or expired.", status_code=400)
    password_hash = hash_password(validated_password)
    user_id = str(row[1])
    token_type = str(row[2])
    async with atomic() as db:
        recheck = await (
            await db.execute(
                "SELECT t.used_at, t.expires_at, ua.account_status, sp.active "
                "FROM auth_setup_token t "
                "JOIN user_account ua ON ua.user_id=t.user_id "
                "JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
                "WHERE t.token_id=?",
                (str(row[0]),),
            )
        ).fetchone()
        if (
            not recheck
            or recheck[0]
            or str(recheck[1]) <= _now()
            or str(recheck[2]) != "INVITED"
            or not bool(recheck[3])
        ):
            raise AccessControlError("TOKEN_INVALID_OR_EXPIRED", "The setup/reset token is invalid or expired.", status_code=400)
        now = _now()
        await db.execute(
            "UPDATE user_account SET password_hash=?, account_status='ACTIVE', "
            "updated_at=?, credential_version=credential_version+1 WHERE user_id=?",
            (password_hash, now, user_id),
        )
        await db.execute(
            "UPDATE staff_profile SET active=1, updated_at=? WHERE staff_id=?",
            (now, str(row[6])),
        )
        await db.execute(
            "UPDATE auth_setup_token SET used_at=? WHERE token_id=?",
            (now, str(row[0])),
        )
        await db.execute(
            "UPDATE auth_session SET revoked_at=?, revoke_reason=? WHERE user_id=? AND revoked_at IS NULL",
            (now, "PASSWORD_RESET_COMPLETED", user_id),
        )
        await write_audit_event(
            db,
            "PASSWORD_RESET_COMPLETED" if token_type == "PASSWORD_RESET" else "ACCOUNT_SETUP_COMPLETED",
            target_user_id=user_id,
            target_staff_id=str(row[6]),
        )
        raw_token, raw_csrf, session = await _create_session_in_db(db, user_id)
    return {
        "user": await _safe_user(await get_db(), user_id),
        "session_token": raw_token,
        "csrf_token": raw_csrf,
        "session": session,
    }


async def update_staff(context: AuthContext, user_id: str, *, display_name: str | None, email: str | None) -> dict[str, Any]:
    db = await get_db()
    row = await _load_user_row(db, user_id=user_id)
    if not row:
        raise AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404)
    name = normalize_display_name(display_name) if display_name is not None else str(row["display_name"])
    normalized_email = normalize_email(email) if email is not None else str(row["email"])
    async with atomic() as db:
        duplicate = await _load_user_row(db, email=normalized_email)
        if duplicate and str(duplicate["user_id"]) != user_id:
            raise AccessControlError("EMAIL_ALREADY_REGISTERED", "That staff email is already registered.", status_code=409)
        now = _now()
        await db.execute(
            "UPDATE staff_profile SET display_name=?, updated_at=? WHERE staff_id=?",
            (name, now, str(row["staff_id"])),
        )
        await db.execute(
            "UPDATE user_account SET email=?, updated_at=? WHERE user_id=?",
            (normalized_email, now, user_id),
        )
        await write_audit_event(
            db,
            "ACCOUNT_UPDATED",
            actor=context,
            target_user_id=user_id,
            target_staff_id=str(row["staff_id"]),
            metadata={"display_name_changed": display_name is not None, "email_changed": email is not None},
        )
    return await _safe_user(await get_db(), user_id)


async def assign_roles(context: AuthContext, user_id: str, role_codes: list[str]) -> dict[str, Any]:
    async with atomic() as db:
        row = await _load_user_row(db, user_id=user_id)
        if not row:
            raise AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404)
        if str(row["account_status"]) == "TERMINATED":
            raise AccessControlError("ACCOUNT_TERMINATED", "Terminated staff accounts cannot receive roles.", status_code=409)
        roles = await _validate_role_codes(db, role_codes)
        if "OWNER" not in roles:
            await _guard_last_owner(db, user_id)
        await _assign_roles_in_db(db, user_id, roles, actor_user_id=context.user_id)
        await write_audit_event(
            db,
            "ROLE_CHANGED",
            actor=context,
            target_user_id=user_id,
            target_staff_id=str(row["staff_id"]),
            metadata={"role_codes": roles},
        )
    return await _safe_user(await get_db(), user_id)


async def change_staff_status(context: AuthContext, user_id: str, action: str, *, reason: str = "") -> dict[str, Any]:
    normalized_action = _text(action).upper()
    if normalized_action not in {"SUSPEND", "DISABLE", "REACTIVATE", "TERMINATE"}:
        raise AccessControlError("ACCOUNT_ACTION_INVALID", "Unsupported staff account action.")
    async with atomic() as db:
        row = await _load_user_row(db, user_id=user_id)
        if not row:
            raise AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404)
        current_status = str(row["account_status"])
        if current_status == "TERMINATED":
            raise AccessControlError(
                "ACCOUNT_TERMINATED",
                "Terminated staff accounts have a terminal lifecycle state.",
                status_code=409,
            )
        if normalized_action in {"SUSPEND", "DISABLE", "TERMINATE"}:
            await _guard_last_owner(db, user_id)
        now = _now()
        if normalized_action == "TERMINATE":
            await db.execute(
                "UPDATE user_account SET account_status='TERMINATED', password_hash=NULL, "
                "terminated_at=?, termination_reason=?, updated_at=?, credential_version=credential_version+1 "
                "WHERE user_id=?",
                (now, _text(reason)[:240] or "OWNER_TERMINATED", now, user_id),
            )
            await db.execute(
                "UPDATE staff_profile SET active=0, updated_at=? WHERE staff_id=?",
                (now, str(row["staff_id"])),
            )
            await db.execute(
                "UPDATE user_role SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, user_id),
            )
            event_type = "ACCOUNT_TERMINATED"
        elif normalized_action == "SUSPEND":
            await db.execute(
                "UPDATE user_account SET account_status='SUSPENDED', updated_at=? WHERE user_id=?",
                (now, user_id),
            )
            await db.execute(
                "UPDATE staff_profile SET active=0, updated_at=? WHERE staff_id=?",
                (now, str(row["staff_id"])),
            )
            event_type = "ACCOUNT_SUSPENDED"
        elif normalized_action == "DISABLE":
            await db.execute(
                "UPDATE user_account SET account_status='DISABLED', disabled_at=?, updated_at=? WHERE user_id=?",
                (now, now, user_id),
            )
            await db.execute(
                "UPDATE staff_profile SET active=0, updated_at=? WHERE staff_id=?",
                (now, str(row["staff_id"])),
            )
            event_type = "ACCOUNT_DISABLED"
        else:
            if current_status == "TERMINATED":
                raise AccessControlError("ACCOUNT_TERMINATED", "Terminated staff accounts cannot be reactivated.", status_code=409)
            next_status = "ACTIVE" if row["password_hash"] else "INVITED"
            await db.execute(
                "UPDATE user_account SET account_status=?, disabled_at=NULL, updated_at=? WHERE user_id=?",
                (next_status, now, user_id),
            )
            await db.execute(
                "UPDATE staff_profile SET active=1, updated_at=? WHERE staff_id=?",
                (now, str(row["staff_id"])),
            )
            event_type = "ACCOUNT_REACTIVATED"
        if normalized_action in {"SUSPEND", "DISABLE", "TERMINATE"}:
            await db.execute(
                "UPDATE auth_session SET revoked_at=?, revoke_reason=? WHERE user_id=? AND revoked_at IS NULL",
                (now, f"ACCOUNT_{normalized_action}", user_id),
            )
        await write_audit_event(
            db,
            event_type,
            actor=context,
            target_user_id=user_id,
            target_staff_id=str(row["staff_id"]),
            metadata={"reason": _text(reason)[:240]} if reason else None,
        )
    return await _safe_user(await get_db(), user_id)


async def issue_password_reset(context: AuthContext, user_id: str) -> dict[str, Any]:
    async with atomic() as db:
        row = await _load_user_row(db, user_id=user_id)
        if not row:
            raise AccessControlError("ACCOUNT_NOT_FOUND", "Staff account was not found.", status_code=404)
        if str(row["account_status"]) == "TERMINATED":
            raise AccessControlError("ACCOUNT_TERMINATED", "Terminated staff accounts cannot be reset.", status_code=409)
        if str(row["account_status"]) in {"SUSPENDED", "DISABLED"}:
            raise AccessControlError(
                "ACCOUNT_NOT_ACTIVE",
                "Reactivate a suspended or disabled account before resetting its password.",
                status_code=409,
            )
        now = _now()
        await db.execute(
            "UPDATE user_account SET password_hash=NULL, account_status='INVITED', credential_version=credential_version+1, updated_at=? WHERE user_id=?",
            (now, user_id),
        )
        await db.execute(
            "UPDATE auth_session SET revoked_at=?, revoke_reason=? WHERE user_id=? AND revoked_at IS NULL",
            (now, "PASSWORD_RESET_INITIATED", user_id),
        )
        raw_token = await _issue_token_in_db(
            db,
            user_id=user_id,
            token_type="PASSWORD_RESET",
            created_by_user_id=context.user_id,
        )
        await write_audit_event(
            db,
            "PASSWORD_RESET_INITIATED",
            actor=context,
            target_user_id=user_id,
            target_staff_id=str(row["staff_id"]),
        )
    return {
        "user": await _safe_user(await get_db(), user_id),
        "reset_token": raw_token,
        "reset_token_expires_at": _future(SETUP_TOKEN_TTL_SECONDS),
    }


async def list_staff() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT ua.user_id, ua.staff_id, ua.email, ua.account_status, ua.created_at, ua.updated_at, "
        "ua.last_login_at, ua.terminated_at, sp.display_name, sp.active AS staff_active "
        "FROM user_account ua JOIN staff_profile sp ON sp.staff_id=ua.staff_id "
        "ORDER BY sp.active DESC, sp.display_name COLLATE NOCASE, ua.user_id"
    )
    rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = {
            "user_id": str(row[0]),
            "staff_id": str(row[1]),
            "email": str(row[2]),
            "account_status": str(row[3]),
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "last_login_at": row[6],
            "terminated_at": row[7],
            "display_name": str(row[8]),
            "staff_active": bool(row[9]),
        }
        roles, permissions = await _permissions_for_user(db, str(row[0]))
        item["role_codes"] = list(roles)
        item["permissions"] = sorted(permissions)
        result.append(item)
    return result


async def list_roles() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT r.role_code, r.display_name, r.description, r.built_in, "
        "p.permission_code FROM role r LEFT JOIN role_permission rp ON rp.role_id=r.role_id "
        "LEFT JOIN permission p ON p.permission_id=rp.permission_id "
        "ORDER BY r.role_code, p.permission_code"
    )
    grouped: dict[str, dict[str, Any]] = {}
    for row in await cursor.fetchall():
        code = str(row[0])
        item = grouped.setdefault(
            code,
            {
                "role_code": code,
                "display_name": str(row[1]),
                "description": str(row[2]),
                "built_in": bool(row[3]),
                "permission_codes": [],
            },
        )
        if row[4]:
            item["permission_codes"].append(str(row[4]))
    return list(grouped.values())


async def list_permissions() -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT permission_code, display_name, description FROM permission ORDER BY permission_code"
    )
    return [
        {"permission_code": str(row[0]), "display_name": str(row[1]), "description": str(row[2])}
        for row in await cursor.fetchall()
    ]


async def set_role_permissions(context: AuthContext, role_code: str, permission_codes: list[str]) -> list[dict[str, Any]]:
    normalized_role = _text(role_code).upper()
    if normalized_role == "SYSTEM" or normalized_role not in ROLE_CODES:
        raise AccessControlError("ROLE_INVALID", "Only built-in human roles may be changed.")
    normalized_permissions = sorted({_text(code) for code in permission_codes})
    if not set(normalized_permissions).issubset(PERMISSION_CODES):
        raise AccessControlError("PERMISSION_INVALID", "Requested permission is not configured.")
    if normalized_role == "OWNER" and set(normalized_permissions) != set(PERMISSION_CODES):
        raise AccessControlError(
            "OWNER_ROLE_PROTECTED",
            "The built-in OWNER role must retain every configured human permission.",
            status_code=409,
        )
    async with atomic() as db:
        role_id = f"role_{normalized_role.lower()}"
        await db.execute("DELETE FROM role_permission WHERE role_id=?", (role_id,))
        for permission_code in normalized_permissions:
            await db.execute(
                "INSERT INTO role_permission (role_id, permission_id) "
                "SELECT ?, permission_id FROM permission WHERE permission_code=?",
                (role_id, permission_code),
            )
        await write_audit_event(
            db,
            "ROLE_PERMISSIONS_CHANGED",
            actor=context,
            metadata={"role_code": normalized_role, "permission_codes": normalized_permissions},
        )
    return await list_roles()


async def list_sessions(*, active_only: bool = True) -> list[dict[str, Any]]:
    db = await get_db()
    query = (
        "SELECT s.session_id, s.user_id, s.created_at, s.expires_at, s.last_seen_at, "
        "s.revoked_at, s.revoke_reason, ua.email, sp.staff_id, sp.display_name "
        "FROM auth_session s JOIN user_account ua ON ua.user_id=s.user_id "
        "JOIN staff_profile sp ON sp.staff_id=ua.staff_id"
    )
    if active_only:
        query += " WHERE s.revoked_at IS NULL AND s.expires_at>? AND ua.account_status='ACTIVE'"
        params: tuple[Any, ...] = (_now(),)
    else:
        query += " ORDER BY s.created_at DESC LIMIT 500"
        params = ()
    if active_only:
        query += " ORDER BY s.last_seen_at DESC"
    cursor = await db.execute(query, params)
    return [
        {
            "session_id": str(row[0]),
            "user_id": str(row[1]),
            "created_at": str(row[2]),
            "expires_at": str(row[3]),
            "last_seen_at": str(row[4]),
            "revoked_at": row[5],
            "revoke_reason": row[6],
            "email": str(row[7]),
            "staff_id": str(row[8]),
            "display_name": str(row[9]),
        }
        for row in await cursor.fetchall()
    ]


async def revoke_session(context: AuthContext, session_id: str, reason: str) -> None:
    db = await get_db()
    async with _db_lock:
        row = await (
            await db.execute("SELECT user_id FROM auth_session WHERE session_id=?", (_text(session_id),))
        ).fetchone()
        if not row:
            raise AccessControlError("SESSION_NOT_FOUND", "Session was not found.", status_code=404)
        await db.execute(
            "UPDATE auth_session SET revoked_at=?, revoke_reason=? WHERE session_id=? AND revoked_at IS NULL",
            (_now(), _text(reason)[:80] or "OWNER_REVOKED", _text(session_id)),
        )
        await write_audit_event(
            db,
            "SESSION_REVOKED",
            actor=context,
            target_user_id=str(row[0]),
            metadata={"reason": _text(reason)[:80] or "OWNER_REVOKED"},
        )
        await db.commit()


async def list_audit_events(*, limit: int = 200, event_type: str | None = None) -> list[dict[str, Any]]:
    db = await get_db()
    safe_limit = min(max(int(limit), 1), 500)
    query = (
        "SELECT event_id, event_type, actor_user_id, actor_staff_id, target_user_id, "
        "target_staff_id, success, metadata_json, created_at FROM access_audit_event"
    )
    params: list[Any] = []
    if event_type:
        query += " WHERE event_type=?"
        params.append(_text(event_type)[:80])
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(safe_limit)
    cursor = await db.execute(query, tuple(params))
    result = []
    for row in await cursor.fetchall():
        try:
            metadata = json.loads(row[7] or "{}")
        except (TypeError, ValueError):
            metadata = {}
        result.append(
            {
                "event_id": str(row[0]),
                "event_type": str(row[1]),
                "actor_user_id": row[2],
                "actor_staff_id": row[3],
                "target_user_id": row[4],
                "target_staff_id": row[5],
                "success": bool(row[6]),
                "metadata": metadata,
                "created_at": str(row[8]),
            }
        )
    return result
