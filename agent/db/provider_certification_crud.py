"""Persistence boundary for shared provider execution certification evidence.

The profile digest is the sole provider-proof identity.  This module is the
only SQL boundary used by the certification service; API handlers never mutate
the certification table directly.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.db.schema import _db_lock, get_db


def _dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


_UPDATE_COLUMNS = {
    "status",
    "provider_operation_id",
    "job_id",
    "snapshot_id",
    "target_ack_digest",
    "target_ack_json",
    "target_acknowledged_at",
    "artifact_media_id",
    "source_sha256",
    "output_sha256",
    "credit_delta",
    "runtime_sha",
    "frame_qc_json",
    "failure_code",
    "failure_detail",
    "updated_at",
}

_INSERT_COLUMNS = {
    "certification_id",
    "profile_digest",
    "profile_json",
    "status",
    "representative_lane",
    "provider",
    "model_key",
    "duration_s",
    "prompt_block_durations_json",
    "aspect_ratio",
    "audio_dialogue_route",
    "transport_key_provenance",
    "capability_matrix_version",
    "execution_transport",
    "generation_mode",
    "execution_route",
    "product_id",
    "copy_id",
    "product_digest",
    "copy_digest",
    "sweetwps_digest",
    "compositor_digest",
    "compiler_digest",
    "lane_adapter_digest",
    "runtime_sha",
    "snapshot_id",
    "created_at",
    "updated_at",
}


async def get_by_profile_digest(profile_digest: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM provider_execution_certification WHERE profile_digest=?",
        (profile_digest,),
    )
    return _dict(await cursor.fetchone())


async def get_by_id(certification_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM provider_execution_certification WHERE certification_id=?",
        (certification_id,),
    )
    return _dict(await cursor.fetchone())


async def get_by_job_id(job_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM provider_execution_certification WHERE job_id=? "
        "ORDER BY created_at DESC, certification_id DESC LIMIT 1",
        (job_id,),
    )
    return _dict(await cursor.fetchone())


async def create_reservation(values: dict[str, Any]) -> dict[str, Any]:
    required = {
        "certification_id",
        "profile_digest",
        "profile_json",
        "representative_lane",
        "provider",
        "model_key",
        "duration_s",
        "aspect_ratio",
        "audio_dialogue_route",
        "transport_key_provenance",
        "capability_matrix_version",
        "execution_transport",
        "generation_mode",
        "execution_route",
        "product_id",
        "copy_id",
        "product_digest",
        "copy_digest",
        "sweetwps_digest",
        "compositor_digest",
        "compiler_digest",
        "lane_adapter_digest",
        "runtime_sha",
        "snapshot_id",
    }
    missing = sorted(required - set(values))
    if missing:
        raise ValueError(f"provider certification reservation missing: {missing}")
    unknown = set(values) - _INSERT_COLUMNS
    if unknown:
        raise ValueError(f"unsupported provider certification columns: {sorted(unknown)}")
    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    db = await get_db()
    async with _db_lock:
        await db.execute(
            f"INSERT INTO provider_execution_certification ({','.join(columns)}) "
            f"VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )
        await db.commit()
    row = await get_by_id(str(values["certification_id"]))
    if row is None:
        raise RuntimeError("PROVIDER_CERTIFICATION_RESERVATION_MISSING")
    return row


async def archive_failed_pre_provider_and_create_reservation(
    existing: dict[str, Any],
    values: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Archive one terminal provider-free attempt and create a fresh reservation.

    The profile digest remains unique in the live certification table.  A
    reconciled pre-provider failure is therefore moved, with its complete row
    and lineage, to the append-only history table before the explicitly new
    reservation is inserted.  This is the persistence boundary for a new
    attempt; callers never mutate either table directly.
    """

    required = {
        "certification_id",
        "profile_digest",
        "profile_json",
        "representative_lane",
        "provider",
        "model_key",
        "duration_s",
        "aspect_ratio",
        "audio_dialogue_route",
        "transport_key_provenance",
        "capability_matrix_version",
        "execution_transport",
        "generation_mode",
        "execution_route",
        "product_id",
        "copy_id",
        "product_digest",
        "copy_digest",
        "sweetwps_digest",
        "compositor_digest",
        "compiler_digest",
        "lane_adapter_digest",
        "runtime_sha",
        "snapshot_id",
    }
    missing = sorted(required - set(values))
    if missing:
        raise ValueError(f"provider certification reservation missing: {missing}")
    unknown = set(values) - _INSERT_COLUMNS
    if unknown:
        raise ValueError(f"unsupported provider certification columns: {sorted(unknown)}")
    if str(existing.get("status") or "").upper() != "FAILED":
        raise ValueError("only terminal FAILED certifications may be archived")
    if str(existing.get("profile_digest") or "") != str(values["profile_digest"]):
        raise ValueError("provider certification profile digest mismatch")

    columns = tuple(values)
    placeholders = ",".join("?" for _ in columns)
    history_id = "pech_" + uuid.uuid4().hex[:20]
    archived_at = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    async with _db_lock:
        try:
            await db.execute(
                "INSERT INTO provider_execution_certification_history "
                "(history_id, certification_id, profile_digest, row_json, archive_reason, archived_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    history_id,
                    existing.get("certification_id"),
                    existing.get("profile_digest"),
                    json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    str(reason or "NEW_EXPLICIT_CAPTURE")[:1000],
                    archived_at,
                ),
            )
            await db.execute(
                "DELETE FROM provider_execution_certification WHERE certification_id=?",
                (existing.get("certification_id"),),
            )
            await db.execute(
                f"INSERT INTO provider_execution_certification ({','.join(columns)}) "
                f"VALUES ({placeholders})",
                tuple(values[column] for column in columns),
            )
            await db.commit()
        except Exception:
            # A competing reopen already archived this exact terminal row and
            # inserted the fresh reservation under the shared unique
            # profile_digest.  Roll back this duplicate attempt and return the
            # winner's live row so a shared profile yields EXACTLY ONE fresh
            # reservation under concurrency (never two captures).
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            winner = await get_by_profile_digest(str(values["profile_digest"]))
            if winner is not None and str(winner.get("status") or "").upper() != "FAILED":
                return winner
            raise
    row = await get_by_id(str(values["certification_id"]))
    if row is None:
        raise RuntimeError("PROVIDER_CERTIFICATION_RESERVATION_MISSING")
    return row


async def update_certification(certification_id: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - _UPDATE_COLUMNS
    if unknown:
        raise ValueError(f"unsupported provider certification columns: {sorted(unknown)}")
    if values:
        db = await get_db()
        async with _db_lock:
            assignments = ", ".join(f"{column}=?" for column in values)
            await db.execute(
                "UPDATE provider_execution_certification SET "
                f"{assignments}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') "
                "WHERE certification_id=?",
                (*values.values(), certification_id),
            )
            await db.commit()
    row = await get_by_id(certification_id)
    if row is None:
        raise KeyError(certification_id)
    return row


async def list_certifications(*, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    db = await get_db()
    if status:
        cursor = await db.execute(
            "SELECT * FROM provider_execution_certification "
            "WHERE status=? ORDER BY created_at DESC, certification_id DESC LIMIT ?",
            (status, limit),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM provider_execution_certification "
            "ORDER BY created_at DESC, certification_id DESC LIMIT ?",
            (limit,),
        )
    return [dict(row) for row in await cursor.fetchall()]
