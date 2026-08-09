"""Durable montage run ledger tests (M-02)."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent.services.montage_assembly_readiness import BLOCKED_INCOMPLETE_SCENE_SET
from agent.services.montage_assembly_readiness import MontageAssemblyError
from agent.services.montage_run_service import (
    KIND,
    assemble_from_montage_run,
    bind_montage_scene_result,
    create_montage_discrete_run,
    estimate_montage_run_generation,
    get_montage_discrete_run,
    readiness_from_montage_run,
    scene_jobs_to_readiness,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy
from agent.db.schema import (
    _BULK_GENERATION_ITEM_STATUSES,
    _BULK_GENERATION_ITEM_TYPES,
    _BULK_GENERATION_RUN_KINDS,
    _BULK_GENERATION_RUN_STATUSES,
    _migrate_bulk_generation_ledger,
    get_db,
)


def _beats():
    return [
        SimpleNamespace(beat_id="hook", role="HOOK", objective="o1", visual_action="v1"),
        SimpleNamespace(beat_id="body", role="BODY", objective="o2", visual_action="v2"),
    ]


@pytest.mark.asyncio
async def test_create_run_persists_scene_lifecycle() -> None:
    pkg = AsyncMock(
        side_effect=[
            {
                "workspace_execution_package_id": "wep-a",
                "prompt_text": "a",
                "execution_allowed": True,
                "asset_slots": [{
                    "slot_key": "start_frame",
                    "resolved_asset": {"download_url": "https://cdn.example/a.png"},
                }],
            },
            {
                "workspace_execution_package_id": "wep-b",
                "prompt_text": "b",
                "execution_allowed": True,
                "asset_slots": [{
                    "slot_key": "start_frame",
                    "resolved_asset": {"download_url": "https://cdn.example/b.png"},
                }],
            },
        ]
    )
    run_row = {"bulk_run_id": "r1", "kind": KIND, "status": "PREPARED", "config_json": "{}"}
    items_store: list[dict] = []

    async def create_run(rid, **kw):
        run_row["bulk_run_id"] = rid
        run_row["kind"] = kw.get("kind", KIND)
        return run_row

    async def update_run(rid, **kw):
        run_row.update(kw)
        return run_row

    async def create_item(iid, **kw):
        row = {"bulk_item_id": iid, **kw}
        items_store.append(row)
        return row

    async def list_items(rid, **kw):
        return list(items_store)

    async def get_run(rid):
        return run_row

    with (
        patch("agent.services.montage_run_service.crud.create_bulk_generation_run", side_effect=create_run),
        patch("agent.services.montage_run_service.crud.update_bulk_generation_run", side_effect=update_run),
        patch("agent.services.montage_run_service.crud.create_bulk_generation_item", side_effect=create_item),
        patch("agent.services.montage_run_service.crud.list_bulk_generation_items", side_effect=list_items),
        patch("agent.services.montage_run_service.crud.get_bulk_generation_run", side_effect=get_run),
        patch("agent.services.montage_run_service.crud.update_bulk_generation_item", new_callable=AsyncMock),
    ):
        out = await create_montage_discrete_run(
            product_id="p1",
            story_beats=_beats(),
            package_factory=pkg,
            product_media_id="pm1",
            default_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
            model="Veo 3.1 - Lite",
            duration_seconds=8,
        )
    assert out["kind"] == KIND
    assert out["total_scenes"] == 2
    assert out["credit_spend"] is False
    assert all(s.get("workspace_execution_package_id") for s in out["scenes"])
    assert pkg.await_count == 2
    assert len(items_store) == 2


@pytest.mark.asyncio
async def test_bind_result_then_readiness_and_assemble_gate() -> None:
    import json

    config = json.dumps({"product_media_id": "pm1", "model": "Veo 3.1 - Lite", "duration_seconds": 8})
    run_row = {"bulk_run_id": "run-x", "kind": KIND, "status": "PREPARED", "config_json": config}
    items = [
        {
            "bulk_item_id": "i1",
            "source_ref": "scene-1-hook",
            "status": "PACKAGE_READY",
            "payload_json": json.dumps(
                {
                    "scene_id": "scene-1-hook",
                    "beat_id": "hook",
                    "reference_policy": "PRODUCT_ANCHOR",
                    "workspace_execution_package_id": "wep-1",
                    "start_asset_snapshot": {"downloadUrl": "https://cdn.example/1.png"},
                }
            ),
        },
        {
            "bulk_item_id": "i2",
            "source_ref": "scene-2-body",
            "status": "PACKAGE_READY",
            "payload_json": json.dumps(
                {
                    "scene_id": "scene-2-body",
                    "beat_id": "body",
                    "reference_policy": "PRODUCT_ANCHOR",
                    "workspace_execution_package_id": "wep-2",
                    "start_asset_snapshot": {"downloadUrl": "https://cdn.example/2.png"},
                }
            ),
        },
    ]

    async def update_item(iid, **kw):
        for it in items:
            if it["bulk_item_id"] == iid:
                it.update(kw)
                if "payload_json" in kw:
                    pass
                return it
        return None

    with (
        patch("agent.services.montage_run_service.crud.get_bulk_generation_run", AsyncMock(return_value=run_row)),
        patch("agent.services.montage_run_service.crud.list_bulk_generation_items", AsyncMock(return_value=items)),
        patch("agent.services.montage_run_service.crud.update_bulk_generation_item", side_effect=update_item),
        patch("agent.services.montage_run_service.crud.update_bulk_generation_run", AsyncMock(return_value=run_row)),
    ):
        # incomplete → readiness fail
        ready = await readiness_from_montage_run("run-x")
        assert ready["ok"] is False

        concat = AsyncMock()
        with pytest.raises((MontageAssemblyError, Exception)) as excinfo:
            await assemble_from_montage_run("run-x", concat_fn=concat, dry_run=True)
        assert concat.await_count == 0

        # bind both videos
        await bind_montage_scene_result(
            "run-x", scene_id="scene-1-hook", media_id="clip-a", result_kind="video"
        )
        await bind_montage_scene_result(
            "run-x", scene_id="scene-2-body", media_id="clip-b", result_kind="video"
        )
        ready2 = await readiness_from_montage_run("run-x")
        assert ready2["ok"] is True
        assert ready2["clip_media_ids"] == ["clip-a", "clip-b"]

        concat2 = AsyncMock(return_value={"dry_run": True, "status": "SEGMENTS_READY"})
        assembled = await assemble_from_montage_run("run-x", concat_fn=concat2, dry_run=True)
        assert assembled["ok"] is True
        concat2.assert_awaited_once()
        assert concat2.await_args.kwargs["requested_seconds"] == 16
        assert concat2.await_args.kwargs["segment_seconds"] == 8


def test_scene_jobs_to_readiness_maps_result_bound() -> None:
    rows = [
        {
            "scene_id": "s1",
            "status": "RESULT_BOUND",
            "video_media_id": "v1",
            "reference_policy": "PRODUCT_ANCHOR",
        },
        {
            "scene_id": "s2",
            "status": "PACKAGE_READY",
            "reference_policy": "PRODUCT_ANCHOR",
        },
    ]
    ready = scene_jobs_to_readiness(rows, product_media_id="pm")
    assert ready[0].video_ready is True
    assert ready[0].clip_media_id == "v1"
    assert ready[1].video_ready is False


def _create_legacy_bulk_ledger(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
CREATE TABLE bulk_generation_run (
    bulk_run_id             TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL
                            CHECK(kind IN ('AVATAR_IMAGE','IMG','VIDEO','MIXED')),
    status                  TEXT NOT NULL DEFAULT 'PENDING'
                            CHECK(status IN ('PENDING','RUNNING','COMPLETED','PARTIAL_FAILED','FAILED','CANCELLED','PAUSED')),
    total_expected          INTEGER NOT NULL DEFAULT 0,
    total_completed         INTEGER NOT NULL DEFAULT 0,
    total_failed            INTEGER NOT NULL DEFAULT 0,
    max_parallel_images     INTEGER NOT NULL DEFAULT 2,
    max_parallel_videos     INTEGER NOT NULL DEFAULT 1,
    confirm_credit_burn     INTEGER NOT NULL DEFAULT 0,
    interval_min_seconds    INTEGER NOT NULL DEFAULT 5,
    interval_max_seconds    INTEGER NOT NULL DEFAULT 15,
    cooldown_after_n_jobs   INTEGER NOT NULL DEFAULT 5,
    cooldown_seconds        INTEGER NOT NULL DEFAULT 60,
    error_log_json          TEXT NOT NULL DEFAULT '[]',
    config_json             TEXT NOT NULL DEFAULT '{}',
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE TABLE bulk_generation_item (
    bulk_item_id            TEXT PRIMARY KEY,
    bulk_run_id             TEXT NOT NULL,
    item_type               TEXT NOT NULL
                            CHECK(item_type IN ('AVATAR_IMAGE','IMG','T2V','I2V','F2V')),
    source_ref              TEXT NOT NULL,
    prompt_snapshot         TEXT,
    payload_json            TEXT NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'QUEUED'
                            CHECK(status IN ('QUEUED','SUBMITTED','RUNNING','GENERATED','DOWNLOADED','REGISTERED','FAILED','CANCELLED')),
    job_id                  TEXT,
    media_id                TEXT,
    local_path              TEXT,
    creative_asset_id       TEXT,
    error                   TEXT,
    retry_count             INTEGER NOT NULL DEFAULT 0,
    started_at              TEXT,
    completed_at            TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX idx_bulk_generation_item_run ON bulk_generation_item(bulk_run_id);
CREATE INDEX idx_bulk_generation_item_run_status
    ON bulk_generation_item(bulk_run_id, status);
INSERT INTO bulk_generation_run (bulk_run_id, kind, status, config_json)
VALUES ('legacy-run', 'VIDEO', 'COMPLETED', '{"legacy":true}');
INSERT INTO bulk_generation_item (
    bulk_item_id, bulk_run_id, item_type, source_ref, status, payload_json
) VALUES ('legacy-item', 'legacy-run', 'F2V', 'legacy-source', 'REGISTERED', '{}');
"""
        )


def test_bulk_ledger_migration_is_complete_preserving_and_fail_closed(tmp_path) -> None:
    database = tmp_path / "legacy-bulk-ledger.sqlite"
    _create_legacy_bulk_ledger(database)

    assert _migrate_bulk_generation_ledger(str(database)) is True

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        run_row = connection.execute(
            "SELECT kind, status, config_json FROM bulk_generation_run "
            "WHERE bulk_run_id='legacy-run'"
        ).fetchone()
        item_row = connection.execute(
            "SELECT item_type, status, payload_json FROM bulk_generation_item "
            "WHERE bulk_item_id='legacy-item'"
        ).fetchone()
        assert run_row == ("VIDEO", "COMPLETED", '{"legacy":true}')
        assert item_row == ("F2V", "REGISTERED", "{}")

        run_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='bulk_generation_run'"
        ).fetchone()[0]
        item_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='bulk_generation_item'"
        ).fetchone()[0]
        for value in _BULK_GENERATION_RUN_KINDS + _BULK_GENERATION_RUN_STATUSES:
            assert f"'{value}'" in run_sql
        for value in _BULK_GENERATION_ITEM_TYPES + _BULK_GENERATION_ITEM_STATUSES:
            assert f"'{value}'" in item_sql

        for index, status in enumerate(_BULK_GENERATION_RUN_STATUSES):
            connection.execute(
                "INSERT INTO bulk_generation_run (bulk_run_id, kind, status) "
                "VALUES (?, 'MONTAGE_DISCRETE', ?)",
                (f"montage-run-{index}", status),
            )
        for index, status in enumerate(_BULK_GENERATION_ITEM_STATUSES):
            connection.execute(
                "INSERT INTO bulk_generation_item ("
                "bulk_item_id, bulk_run_id, item_type, source_ref, status"
                ") VALUES (?, 'montage-run-0', 'MONTAGE_SCENE', ?, ?)",
                (f"montage-item-{index}", f"scene-{index}", status),
            )
        connection.execute(
            "UPDATE bulk_generation_run SET status='ASSEMBLY_READY' "
            "WHERE bulk_run_id='montage-run-0'"
        )
        connection.execute(
            "UPDATE bulk_generation_item SET status='RESULT_BOUND' "
            "WHERE bulk_item_id='montage-item-0'"
        )
        connection.commit()

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bulk_generation_run (bulk_run_id, kind) "
                "VALUES ('invalid-kind', 'TOTALLY_INVALID')"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bulk_generation_item ("
                "bulk_item_id, bulk_run_id, item_type, source_ref"
                ") VALUES ('invalid-type', 'montage-run-0', 'TOTALLY_INVALID', 'x')"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO bulk_generation_item ("
                "bulk_item_id, bulk_run_id, item_type, source_ref, status"
                ") VALUES ('invalid-status', 'montage-run-0', 'MONTAGE_SCENE', 'x', 'TOTALLY_INVALID')"
            )
        connection.rollback()

        before_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            for table_name in ("bulk_generation_run", "bulk_generation_item")
        )
        assert connection.execute(
            "SELECT status FROM bulk_generation_run "
            "WHERE bulk_run_id='montage-run-0'"
        ).fetchone()[0] == "ASSEMBLY_READY"
        assert connection.execute(
            "SELECT status FROM bulk_generation_item "
            "WHERE bulk_item_id='montage-item-0'"
        ).fetchone()[0] == "RESULT_BOUND"
        index_names = {
            row[1]
            for row in connection.execute(
                "PRAGMA index_list('bulk_generation_item')"
            ).fetchall()
        }
        assert {
            "idx_bulk_generation_item_run",
            "idx_bulk_generation_item_run_status",
        }.issubset(index_names)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    assert _migrate_bulk_generation_ledger(str(database)) is False
    with sqlite3.connect(database) as connection:
        after_counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            for table_name in ("bulk_generation_run", "bulk_generation_item")
        )
        assert after_counts == before_counts


@pytest.mark.asyncio
async def test_montage_run_persists_real_sqlite_ledger_and_estimate() -> None:
    beats = [
        SimpleNamespace(beat_id="hook", role="HOOK", objective="open", visual_action="reveal"),
        SimpleNamespace(beat_id="body", role="BODY", objective="show", visual_action="use"),
        SimpleNamespace(beat_id="cta", role="CTA", objective="close", visual_action="pack shot"),
    ]
    package_index = 0

    async def package_factory(**kwargs):
        nonlocal package_index
        package_index += 1
        scene_id = f"scene-{package_index}"
        return {
            "workspace_execution_package_id": f"wep-{scene_id}",
            "prompt_text": f"prompt-{scene_id}",
            "execution_allowed": True,
            "asset_slots": [
                {
                    "slot_key": "start_frame",
                    "resolved_asset": {
                        "media_id": f"product-media-{scene_id}",
                        "download_url": f"https://example.test/{scene_id}.png",
                    },
                }
            ],
        }

    created = await create_montage_discrete_run(
        product_id="product-1",
        story_beats=beats,
        package_factory=package_factory,
        product_media_id="product-media-1",
        model="Veo 3.1 - Lite",
        duration_seconds=8,
    )

    assert created["credit_spend"] is False
    assert created["kind"] == "MONTAGE_DISCRETE"
    assert created["status"] == "PREPARED", created
    assert created["total_scenes"] == 3

    readback = await get_montage_discrete_run(created["montage_run_id"])
    assert readback["kind"] == "MONTAGE_DISCRETE"
    assert readback["status"] == "PREPARED"
    assert readback["total_scenes"] == 3
    assert all(scene["status"] == "PACKAGE_READY" for scene in readback["scenes"])
    assert all(
        scene["workspace_execution_package_id"]
        for scene in readback["scenes"]
    )

    db = await get_db()
    run_cursor = await db.execute(
        "SELECT kind, status, config_json FROM bulk_generation_run "
        "WHERE bulk_run_id=?",
        (created["montage_run_id"],),
    )
    run_row = await run_cursor.fetchone()
    item_cursor = await db.execute(
        "SELECT item_type, status FROM bulk_generation_item "
        "WHERE bulk_run_id=? ORDER BY created_at",
        (created["montage_run_id"],),
    )
    item_rows = await item_cursor.fetchall()
    assert run_row[0] == "MONTAGE_DISCRETE"
    assert run_row[1] == "PREPARED"
    assert '"duration_seconds": 8' in run_row[2]
    assert [row[0] for row in item_rows] == ["MONTAGE_SCENE"] * 3
    assert [row[1] for row in item_rows] == ["PACKAGE_READY"] * 3

    estimate = await estimate_montage_run_generation(created["montage_run_id"])
    assert estimate["expected_image_operations"] == 0
    assert estimate["expected_video_generations"] == 3
    assert estimate["expected_provider_operations"] == 3
    assert estimate["credit_spend"] is False
