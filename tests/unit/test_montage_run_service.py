"""Durable montage run ledger tests (M-02)."""
from __future__ import annotations

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
    get_montage_discrete_run,
    readiness_from_montage_run,
    scene_jobs_to_readiness,
)
from agent.services.montage_scene_reference_policy import SceneReferencePolicy


def _beats():
    return [
        SimpleNamespace(beat_id="hook", role="HOOK", objective="o1", visual_action="v1"),
        SimpleNamespace(beat_id="body", role="BODY", objective="o2", visual_action="v2"),
    ]


@pytest.mark.asyncio
async def test_create_run_persists_scene_lifecycle() -> None:
    pkg = AsyncMock(
        side_effect=[
            {"workspace_execution_package_id": "wep-a", "prompt_text": "a"},
            {"workspace_execution_package_id": "wep-b", "prompt_text": "b"},
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

    config = json.dumps({"product_media_id": "pm1"})
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
