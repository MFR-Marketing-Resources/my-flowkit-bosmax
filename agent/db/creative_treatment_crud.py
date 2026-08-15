"""Durable P7.5 Creative Treatment persistence.

The CRUD surface is intentionally narrow: authored treatment content has no
update operation. Only lifecycle metadata may transition after creation.
"""

import json
import uuid
from typing import Any

from agent.db.schema import get_db


def _event_values(
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str,
    source_status: str | None,
    target_status: str | None,
    evidence: dict[str, Any] | None = None,
) -> tuple[str, str, str, str, str, str | None, str | None, str]:
    return (
        str(uuid.uuid4()),
        entity_type,
        entity_id,
        action,
        actor_id,
        source_status,
        target_status,
        json.dumps(evidence or {}, sort_keys=True, separators=(",", ":")),
    )


async def create_variation_group(row: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        await db.execute(
            """
            INSERT INTO creative_variation_group (
                group_id, product_id, copy_set_id, dialogue_sha256, status,
                group_sha256, member_count, supersedes_group_id, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["group_id"],
                row["product_id"],
                row["copy_set_id"],
                row["dialogue_sha256"],
                row["status"],
                row.get("group_sha256"),
                row.get("member_count", 0),
                row.get("supersedes_group_id"),
                row["created_by"],
            ),
        )
        await db.execute(
            """
            INSERT INTO creative_treatment_audit_event (
                event_id, entity_type, entity_id, action, actor_id,
                source_status, target_status, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _event_values(
                entity_type="VARIATION_GROUP",
                entity_id=row["group_id"],
                action="CREATED",
                actor_id=row["created_by"],
                source_status=None,
                target_status=row["status"],
                evidence={"dialogue_sha256": row["dialogue_sha256"]},
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_variation_group(row["group_id"]) or {}


async def get_variation_group(group_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_variation_group WHERE group_id=?",
        (group_id,),
    )
    result = await cursor.fetchone()
    return dict(result) if result else None


async def list_variation_groups(
    *,
    product_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM creative_variation_group WHERE 1=1"
    params: list[Any] = []
    if product_id:
        query += " AND product_id=?"
        params.append(product_id)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC, group_id DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    return [dict(row) for row in await cursor.fetchall()]


async def create_treatment(row: dict[str, Any]) -> dict[str, Any]:
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        cursor = await db.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM creative_treatment
            WHERE product_id=?
            """,
            (row["product_id"],),
        )
        version = int((await cursor.fetchone())[0])
        await db.execute(
            """
            INSERT INTO creative_treatment (
                treatment_id, product_id, version, status, format,
                generation_mode, duration_seconds,
                product_truth_snapshot_id, product_truth_sha256,
                copy_set_id, copy_set_sha256, copy_execution_binding_id_v2,
                creative_selection_id, creative_selection_sha256,
                scene_strategy_id, scene_strategy_sha256,
                content_angle, dialogue_text, dialogue_sha256,
                avatar_code, avatar_sha256, wardrobe_text, wardrobe_sha256,
                scene_template_id, scene_template_sha256,
                camera_preset_code, camera_preset_sha256,
                asset_bindings_json, action_sequence_json, shot_grammar_json,
                compatibility_profile_json, segment_plan_json, visual_fingerprint_sha256,
                variation_group_id, variation_ordinal, treatment_sha256,
                supersedes_treatment_id, created_by
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                row["treatment_id"],
                row["product_id"],
                version,
                row["status"],
                row["format"],
                row["generation_mode"],
                row["duration_seconds"],
                row["product_truth_snapshot_id"],
                row["product_truth_sha256"],
                row.get("copy_set_id") or "",
                row.get("copy_set_sha256") or "",
                row.get("copy_execution_binding_id_v2") or "",
                row["creative_selection_id"],
                row["creative_selection_sha256"],
                row["scene_strategy_id"],
                row["scene_strategy_sha256"],
                row["content_angle"],
                row["dialogue_text"],
                row["dialogue_sha256"],
                row.get("avatar_code"),
                row.get("avatar_sha256"),
                row.get("wardrobe_text"),
                row.get("wardrobe_sha256"),
                row.get("scene_template_id"),
                row.get("scene_template_sha256"),
                row.get("camera_preset_code"),
                row.get("camera_preset_sha256"),
                row["asset_bindings_json"],
                row["action_sequence_json"],
                row["shot_grammar_json"],
                row["compatibility_profile_json"],
                row.get("segment_plan_json", "[]"),
                row["visual_fingerprint_sha256"],
                row.get("variation_group_id"),
                row.get("variation_ordinal"),
                row["treatment_sha256"],
                row.get("supersedes_treatment_id"),
                row["created_by"],
            ),
        )
        await db.execute(
            """
            INSERT INTO creative_treatment_audit_event (
                event_id, entity_type, entity_id, action, actor_id,
                source_status, target_status, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _event_values(
                entity_type="TREATMENT",
                entity_id=row["treatment_id"],
                action="CREATED",
                actor_id=row["created_by"],
                source_status=None,
                target_status=row["status"],
                evidence={
                    "version": version,
                    "treatment_sha256": row["treatment_sha256"],
                },
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_treatment(row["treatment_id"]) or {}


async def get_treatment(treatment_id: str) -> dict[str, Any] | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM creative_treatment WHERE treatment_id=?",
        (treatment_id,),
    )
    result = await cursor.fetchone()
    return dict(result) if result else None


async def list_treatments(
    *,
    product_id: str | None = None,
    status: str | None = None,
    variation_group_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = await get_db()
    query = "SELECT * FROM creative_treatment WHERE 1=1"
    params: list[Any] = []
    if product_id:
        query += " AND product_id=?"
        params.append(product_id)
    if status:
        query += " AND status=?"
        params.append(status)
    if variation_group_id:
        query += " AND variation_group_id=?"
        params.append(variation_group_id)
    query += " ORDER BY product_id, version DESC, treatment_id DESC LIMIT ?"
    params.append(limit)
    cursor = await db.execute(query, params)
    return [dict(row) for row in await cursor.fetchall()]


async def list_group_members(group_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT *
        FROM creative_treatment
        WHERE variation_group_id=?
        ORDER BY variation_ordinal, treatment_id
        """,
        (group_id,),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def list_approved_same_dialogue(
    *,
    product_id: str,
    dialogue_sha256: str,
    exclude_treatment_id: str,
) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT *
        FROM creative_treatment
        WHERE product_id=?
          AND dialogue_sha256=?
          AND treatment_id<>?
          AND status='APPROVED'
        ORDER BY treatment_id
        """,
        (product_id, dialogue_sha256, exclude_treatment_id),
    )
    return [dict(row) for row in await cursor.fetchall()]


async def transition_treatment(
    *,
    treatment_id: str,
    source_status: str,
    target_status: str,
    actor_id: str,
    reviewer_note: str | None,
    evidence: dict[str, Any],
    supersede_treatment_id: str | None = None,
) -> dict[str, Any] | None:
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        timestamp_fields = (
            "submitted_by=?, submitted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            if target_status == "REVIEW_REQUIRED"
            else (
                "reviewed_by=?, reviewer_note=?, "
                "reviewed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            )
        )
        params: list[Any] = [target_status, actor_id]
        if target_status != "REVIEW_REQUIRED":
            params.append(reviewer_note)
        params.extend([treatment_id, source_status])
        cursor = await db.execute(
            f"""
            UPDATE creative_treatment
            SET status=?, {timestamp_fields},
                updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE treatment_id=? AND status=?
            """,
            params,
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return None
        if target_status == "APPROVED" and supersede_treatment_id:
            predecessor = await db.execute(
                """
                UPDATE creative_treatment
                SET status='SUPERSEDED',
                    updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                WHERE treatment_id=? AND status='APPROVED'
                """,
                (supersede_treatment_id,),
            )
            if predecessor.rowcount != 1:
                raise ValueError("SUPERSEDED_TREATMENT_NOT_APPROVED")
            await db.execute(
                """
                INSERT INTO creative_treatment_audit_event (
                    event_id, entity_type, entity_id, action, actor_id,
                    source_status, target_status, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _event_values(
                    entity_type="TREATMENT",
                    entity_id=supersede_treatment_id,
                    action="SUPERSEDED",
                    actor_id=actor_id,
                    source_status="APPROVED",
                    target_status="SUPERSEDED",
                    evidence={"successor_treatment_id": treatment_id},
                ),
            )
        await db.execute(
            """
            INSERT INTO creative_treatment_audit_event (
                event_id, entity_type, entity_id, action, actor_id,
                source_status, target_status, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _event_values(
                entity_type="TREATMENT",
                entity_id=treatment_id,
                action=target_status,
                actor_id=actor_id,
                source_status=source_status,
                target_status=target_status,
                evidence=evidence,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_treatment(treatment_id)


async def transition_variation_group(
    *,
    group_id: str,
    source_status: str,
    target_status: str,
    actor_id: str,
    reviewer_note: str | None,
    group_sha256: str,
    member_count: int,
    evidence: dict[str, Any],
    supersede_group_id: str | None = None,
) -> dict[str, Any] | None:
    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        timestamp_fields = (
            "submitted_by=?, submitted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            if target_status == "REVIEW_REQUIRED"
            else (
                "reviewed_by=?, reviewer_note=?, "
                "reviewed_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')"
            )
        )
        params: list[Any] = [
            target_status,
            group_sha256,
            member_count,
            actor_id,
        ]
        if target_status != "REVIEW_REQUIRED":
            params.append(reviewer_note)
        params.extend([group_id, source_status])
        cursor = await db.execute(
            f"""
            UPDATE creative_variation_group
            SET status=?, group_sha256=?, member_count=?, {timestamp_fields},
                updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
            WHERE group_id=? AND status=?
            """,
            params,
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return None
        if target_status == "APPROVED" and supersede_group_id:
            predecessor = await db.execute(
                """
                UPDATE creative_variation_group
                SET status='SUPERSEDED',
                    updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                WHERE group_id=? AND status='APPROVED'
                """,
                (supersede_group_id,),
            )
            if predecessor.rowcount != 1:
                raise ValueError("SUPERSEDED_VARIATION_GROUP_NOT_APPROVED")
            await db.execute(
                """
                INSERT INTO creative_treatment_audit_event (
                    event_id, entity_type, entity_id, action, actor_id,
                    source_status, target_status, evidence_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _event_values(
                    entity_type="VARIATION_GROUP",
                    entity_id=supersede_group_id,
                    action="SUPERSEDED",
                    actor_id=actor_id,
                    source_status="APPROVED",
                    target_status="SUPERSEDED",
                    evidence={"successor_group_id": group_id},
                ),
            )
        await db.execute(
            """
            INSERT INTO creative_treatment_audit_event (
                event_id, entity_type, entity_id, action, actor_id,
                source_status, target_status, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _event_values(
                entity_type="VARIATION_GROUP",
                entity_id=group_id,
                action=target_status,
                actor_id=actor_id,
                source_status=source_status,
                target_status=target_status,
                evidence=evidence,
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return await get_variation_group(group_id)


async def list_audit_events(
    *,
    entity_type: str,
    entity_id: str,
) -> list[dict[str, Any]]:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT *
        FROM creative_treatment_audit_event
        WHERE entity_type=? AND entity_id=?
        ORDER BY rowid
        """,
        (entity_type, entity_id),
    )
    return [dict(row) for row in await cursor.fetchall()]
