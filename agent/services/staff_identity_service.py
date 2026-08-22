"""Server-authoritative staff identity resolution.

Staff identity is deliberately a small registry, not a caller-supplied label.
Generation callers submit only a stable ``staff_id`` issued by this service;
the active row and display-name snapshot are resolved on the server at each
authoritative write boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from agent.db.schema import _db_lock, get_db

STAFF_IDENTITY_REQUIRED = "STAFF_IDENTITY_REQUIRED"
STAFF_IDENTITY_UNKNOWN = "STAFF_IDENTITY_UNKNOWN"
STAFF_IDENTITY_INACTIVE = "STAFF_IDENTITY_INACTIVE"
STAFF_IDENTITY_GENERIC = "STAFF_IDENTITY_GENERIC"
STAFF_DISPLAY_NAME_REQUIRED = "STAFF_DISPLAY_NAME_REQUIRED"
STAFF_PROFILE_NOT_FOUND = "STAFF_PROFILE_NOT_FOUND"

# Existing generic actor strings are historical filters, never valid new
# authority. Keep the list centralized so API, P6, and reporting do not drift.
GENERIC_STAFF_IDS = frozenset(
    {
        "",
        "operator",
        "system",
        "p6_system",
        "p6-production-operator",
        "dashboard-operator",
        "dashboard_operator",
        "unknown",
        "unattributed",
        "null",
        "none",
    }
)
class StaffIdentityError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def is_generic_staff_id(value: Any) -> bool:
    return _text(value).casefold() in GENERIC_STAFF_IDS


def _validate_display_name(value: Any) -> str:
    display_name = _text(value)
    if not display_name:
        raise StaffIdentityError(
            STAFF_DISPLAY_NAME_REQUIRED,
            "A human staff display name is required when creating a profile.",
        )
    if display_name.casefold() in GENERIC_STAFF_IDS:
        raise StaffIdentityError(
            STAFF_IDENTITY_GENERIC,
            "Generic/system labels cannot be registered as staff identity.",
        )
    return display_name


def _row(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    item = dict(row)
    item["active"] = bool(item.get("active"))
    return item


async def resolve_staff_identity(
    staff_id: Any,
    *,
    require_active: bool = True,
) -> dict[str, Any]:
    """Resolve a profile or raise a deterministic fail-closed error."""

    normalized = _text(staff_id)
    if not normalized:
        raise StaffIdentityError(
            STAFF_IDENTITY_REQUIRED,
            "A valid active staff profile is required before production work.",
        )
    if is_generic_staff_id(normalized):
        raise StaffIdentityError(
            STAFF_IDENTITY_GENERIC,
            "Generic/system attribution is not valid staff identity.",
        )
    db = await get_db()
    cursor = await db.execute(
        "SELECT staff_id, display_name, active, created_at, updated_at "
        "FROM staff_profile WHERE staff_id=?",
        (normalized,),
    )
    profile = _row(await cursor.fetchone())
    if not profile:
        raise StaffIdentityError(
            STAFF_IDENTITY_UNKNOWN,
            f"Staff profile {normalized!r} is not registered.",
            status_code=404,
        )
    if require_active and not profile["active"]:
        raise StaffIdentityError(
            STAFF_IDENTITY_INACTIVE,
            f"Staff profile {normalized!r} is inactive.",
            status_code=409,
        )
    return profile


async def list_staff_profiles(*, include_inactive: bool = True) -> list[dict[str, Any]]:
    db = await get_db()
    query = (
        "SELECT staff_id, display_name, active, created_at, updated_at "
        "FROM staff_profile"
    )
    params: tuple[Any, ...] = ()
    if not include_inactive:
        query += " WHERE active=1"
    query += " ORDER BY active DESC, display_name COLLATE NOCASE, staff_id"
    cursor = await db.execute(query, params)
    return [_row(row) for row in await cursor.fetchall()]


async def create_staff_profile(display_name: Any) -> dict[str, Any]:
    name = _validate_display_name(display_name)
    db = await get_db()
    now = _now()
    staff_id = "staff_" + uuid.uuid4().hex[:20]
    async with _db_lock:
        await db.execute(
            "INSERT INTO staff_profile "
            "(staff_id, display_name, active, created_at, updated_at) "
            "VALUES (?,?,1,?,?)",
            (staff_id, name, now, now),
        )
        await db.commit()
    return await resolve_staff_identity(staff_id)


async def update_staff_profile(
    staff_id: Any,
    *,
    display_name: Any = None,
    active: bool | None = None,
) -> dict[str, Any]:
    profile = await resolve_staff_identity(staff_id, require_active=False)
    if display_name is None and active is None:
        return profile
    name = (
        _validate_display_name(display_name)
        if display_name is not None
        else str(profile["display_name"])
    )
    next_active = profile["active"] if active is None else bool(active)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "UPDATE staff_profile SET display_name=?, active=?, updated_at=? "
            "WHERE staff_id=?",
            (name, int(next_active), _now(), str(profile["staff_id"])),
        )
        await db.commit()
    return await resolve_staff_identity(staff_id, require_active=False)


def canonical_staff_snapshot(profile: dict[str, Any]) -> dict[str, str]:
    """Return only the stable fields safe to embed in lineage snapshots."""

    return {
        "staff_id": str(profile["staff_id"]),
        "staff_display_name": str(profile["display_name"]),
    }
