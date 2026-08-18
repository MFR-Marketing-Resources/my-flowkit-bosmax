"""Fail-closed tombstone guard for retired pre-V2 copy storage surfaces."""

from fastapi import HTTPException


def require_legacy_copy_maintenance() -> None:
    """Tombstone (Task D4): legacy copy storage routes are permanently retired.

    Always raises 410 LEGACY_COPY_STORAGE_DISABLED; no legacy service or DB is
    reached. The dependency is retained so the historical legacy routers stay
    mounted as thin 410 tombstones for backward compatibility."""

    raise HTTPException(
        status_code=410,
        detail={
            "error": "LEGACY_COPY_STORAGE_DISABLED",
            "detail": (
                "Legacy copy storage is archived and cannot be read, selected, "
                "authored, approved, or mutated. Use /api/copy-register/v2."
            ),
        },
    )


__all__ = ["require_legacy_copy_maintenance"]
