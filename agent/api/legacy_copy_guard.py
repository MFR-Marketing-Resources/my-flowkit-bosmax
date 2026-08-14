"""Fail-closed guard for archived pre-V2 copy storage surfaces."""

from fastapi import HTTPException

from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled


def require_legacy_copy_maintenance() -> None:
    """Allow legacy routes only during an explicit offline recovery window."""

    if legacy_copy_maintenance_enabled():
        return
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
