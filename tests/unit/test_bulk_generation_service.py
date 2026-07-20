"""Deep unit tests for bulk generation orchestrator V1."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.services import bulk_generation_service as svc


@pytest.mark.asyncio
async def test_create_avatar_bulk_persists_items(monkeypatch):
    created_items: list[dict] = []

    async def fake_create_bulk_generation_item(bulk_item_id, **kwargs):
        created_items.append({"bulk_item_id": bulk_item_id, **kwargs})
        return bulk_item_id

    async def fake_create_bulk_generation_run(bulk_run_id, **kwargs):
        return {"bulk_run_id": bulk_run_id, **kwargs}

    monkeypatch.setattr(svc.crud, "create_bulk_generation_run", fake_create_bulk_generation_run)
    monkeypatch.setattr(svc.crud, "create_bulk_generation_item", fake_create_bulk_generation_item)
    monkeypatch.setattr(svc.crud, "list_creative_assets", AsyncMock(return_value=[]))

    from agent.services import avatar_registry

    monkeypatch.setattr(
        avatar_registry,
        "get_generation_prompt",
        lambda code: {"prompt": f"prompt for {code}", "avatar_code": code},
    )
    monkeypatch.setattr(
        svc.crud,
        "get_bulk_generation_run",
        AsyncMock(return_value={"bulk_run_id": "x", "status": "PENDING"}),
    )

    result = await svc.create_avatar_image_bulk_run(
        ["AV1", "AV2"],
        max_parallel_images=9,
        skip_already_generated=False,
    )
    assert result["total_expected"] == 2
    assert result["max_parallel_images"] == 3
    assert len(created_items) == 2
    assert {i["source_ref"] for i in created_items} == {"AV1", "AV2"}


@pytest.mark.asyncio
async def test_start_requires_credit_confirmation(monkeypatch):
    async def fake_get_run(_id):
        return {
            "bulk_run_id": _id,
            "kind": "AVATAR_IMAGE",
            "status": "PENDING",
            "max_parallel_images": 2,
            "max_parallel_videos": 1,
        }

    async def fake_list_items(_id, limit=500):
        return [{"bulk_item_id": "i1", "status": "QUEUED", "source_ref": "AV1", "item_type": "AVATAR_IMAGE"}]

    monkeypatch.setattr(svc.crud, "get_bulk_generation_run", fake_get_run)
    monkeypatch.setattr(svc.crud, "list_bulk_generation_items", fake_list_items)

    dry = await svc.start_bulk_run("run-1", confirm_credit_burn=False)
    assert dry["dry_run"] is True
    assert dry["confirm_credit_burn_required"] is True

    monkeypatch.setattr(svc.crud, "update_bulk_generation_run", AsyncMock())
    monkeypatch.setattr(asyncio, "create_task", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(svc, "_live_avatar_image_loop", AsyncMock())

    live = await svc.start_bulk_run("run-1", confirm_credit_burn=True)
    assert live["status"] == "RUNNING"


@pytest.mark.asyncio
async def test_dry_run_does_not_spawn_worker(monkeypatch):
    async def fake_get_run(_id):
        return {
            "bulk_run_id": _id,
            "kind": "AVATAR_IMAGE",
            "status": "PENDING",
            "max_parallel_images": 2,
            "max_parallel_videos": 1,
        }

    async def fake_list_items(_id, limit=500):
        return [{"bulk_item_id": "i1", "status": "QUEUED", "source_ref": "AV1", "item_type": "AVATAR_IMAGE"}]

    monkeypatch.setattr(svc.crud, "get_bulk_generation_run", fake_get_run)
    monkeypatch.setattr(svc.crud, "list_bulk_generation_items", fake_list_items)
    create_task = MagicMock()
    monkeypatch.setattr(asyncio, "create_task", create_task)

    await svc.start_bulk_run("run-1", dry_run=True)
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_video_bulk_rejects_non_approved(monkeypatch):
    async def fake_get_pkg(pid):
        return {
            "package_id": pid,
            "production_status": "NONE",
            "product_id": "P1",
            "workspace_id": "W1",
        }

    monkeypatch.setattr(svc.crud, "get_workspace_generation_package", fake_get_pkg)

    with pytest.raises(ValueError, match="NO_ELIGIBLE_PACKAGES"):
        await svc.create_video_bulk_run(["pkg-1"])


@pytest.mark.asyncio
async def test_video_bulk_serial_parallel_cap(monkeypatch):
    async def fake_get_pkg(pid):
        return {
            "package_id": pid,
            "workspace_generation_package_id": pid,
            "production_status": "APPROVED",
            "product_id": "P1",
            "workspace_id": "W1",
        }

    async def fake_create_run(bulk_run_id, **kwargs):
        return {"bulk_run_id": bulk_run_id, **kwargs}

    async def fake_create_item(bulk_item_id, **kwargs):
        return {"bulk_item_id": bulk_item_id, **kwargs}

    monkeypatch.setattr(svc.crud, "get_workspace_generation_package", fake_get_pkg)
    monkeypatch.setattr(svc.crud, "create_bulk_generation_run", fake_create_run)
    monkeypatch.setattr(svc.crud, "create_bulk_generation_item", fake_create_item)

    result = await svc.create_video_bulk_run(["pkg-1", "pkg-2"])
    assert result["max_parallel_videos"] == 1
    assert result["total_expected"] == 2


@pytest.mark.asyncio
async def test_retry_failed_requeues_and_increments_retry(monkeypatch):
    items_state = [
        {
            "bulk_item_id": "i1",
            "status": "FAILED",
            "retry_count": 0,
            "source_ref": "AV1",
        }
    ]

    async def fake_get_run(_id):
        return {"bulk_run_id": _id, "status": "PARTIAL_FAILED", "total_failed": 1}

    async def fake_list_items(_id, limit=500):
        return list(items_state)

    async def fake_update_item(item_id, **fields):
        for it in items_state:
            if it["bulk_item_id"] == item_id:
                it.update(fields)

    async def fake_counts(_id):
        return {"FAILED": 0, "QUEUED": 1}

    monkeypatch.setattr(svc.crud, "get_bulk_generation_run", fake_get_run)
    monkeypatch.setattr(svc.crud, "list_bulk_generation_items", fake_list_items)
    monkeypatch.setattr(svc.crud, "update_bulk_generation_item", fake_update_item)
    monkeypatch.setattr(svc.crud, "bulk_item_status_counts", fake_counts)
    monkeypatch.setattr(svc.crud, "update_bulk_generation_run", AsyncMock())

    out = await svc.retry_failed_bulk_run("run-1")
    assert out["retried"] == 1
    assert items_state[0]["status"] == "QUEUED"
    assert items_state[0]["retry_count"] == 1


@pytest.mark.asyncio
async def test_cancel_marks_queued_cancelled(monkeypatch):
    async def fake_get_run(_id):
        return {"bulk_run_id": _id, "status": "RUNNING"}

    queued = [{"bulk_item_id": "q1", "status": "QUEUED"}]

    async def fake_list_items(_id, status=None, limit=500):
        if status == "QUEUED":
            return queued
        if status == "SUBMITTED":
            return []
        return []

    monkeypatch.setattr(svc.crud, "get_bulk_generation_run", fake_get_run)
    monkeypatch.setattr(svc.crud, "list_bulk_generation_items", fake_list_items)
    monkeypatch.setattr(svc.crud, "update_bulk_generation_item", AsyncMock())
    monkeypatch.setattr(svc.crud, "update_bulk_generation_run", AsyncMock())

    out = await svc.cancel_bulk_run("run-1")
    assert out["status"] == "CANCELLED"
    assert out["cancelled_queued"] == 1


@pytest.mark.asyncio
async def test_recover_stuck_run_after_restart(monkeypatch):
    runs = [{"bulk_run_id": "stuck-1", "status": "RUNNING"}]
    items = [{"bulk_item_id": "i1", "status": "RUNNING", "source_ref": "AV1"}]

    monkeypatch.setattr(svc.crud, "list_bulk_generation_runs", AsyncMock(return_value=runs))
    monkeypatch.setattr(svc.crud, "list_bulk_generation_items", AsyncMock(return_value=items))
    monkeypatch.setattr(svc.crud, "update_bulk_generation_item", AsyncMock())
    monkeypatch.setattr(svc.crud, "update_bulk_generation_run", AsyncMock())
    monkeypatch.setattr(svc, "_append_error_log", AsyncMock())
    svc._worker_tasks.clear()

    out = await svc.recover_stuck_bulk_runs()
    assert out["count"] == 1
    assert "stuck-1" in out["recovered_runs"]


@pytest.mark.asyncio
async def test_live_video_loop_uses_build_execution_payload(monkeypatch):
    """Regression: build_execution_payload(pkg, run_config) not wrong kwargs."""
    pkg = {
        "package_id": "wgp-1",
        "production_status": "APPROVED",
        "dom_handoff_payload_json": '{"mode":"T2V","prompt":"hi"}',
        "product_id": "P1",
        "workspace_id": "W1",
    }
    run = {
        "bulk_run_id": "run-v",
        "kind": "VIDEO",
        "config_json": "{}",
        "interval_min_seconds": 0,
        "interval_max_seconds": 0,
        "cooldown_after_n_jobs": 99,
        "cooldown_seconds": 0,
    }
    item = {"bulk_item_id": "bi1", "source_ref": "wgp-1", "status": "QUEUED"}

    calls: list[tuple] = []

    async def fake_get_run(rid):
        return run if rid == "run-v" else run

    async def fake_claim(rid):
        if calls:
            return None
        calls.append(("claim",))
        return item

    async def fake_build(pkg_arg, run_config):
        calls.append(("build", pkg_arg["package_id"], run_config))
        return (
            {"mode": "T2V", "prompt": "hi", "aspect": "9:16", "num_videos": 1},
            [],
        )

    async def fake_fire(payload, wgp_id):
        calls.append(("fire", wgp_id))
        return {"ok": True, "job_id": "j1", "media_id": "m1", "local_path": "/tmp/v.mp4"}

    monkeypatch.setattr(svc.crud, "get_bulk_generation_run", fake_get_run)
    monkeypatch.setattr(svc.crud, "claim_next_bulk_item", fake_claim)
    monkeypatch.setattr(svc.crud, "get_workspace_generation_package", AsyncMock(return_value=pkg))
    monkeypatch.setattr(svc.crud, "update_workspace_generation_package", AsyncMock())
    monkeypatch.setattr(svc.crud, "update_bulk_generation_item", AsyncMock())
    monkeypatch.setattr(svc.crud, "update_bulk_generation_run", AsyncMock())
    monkeypatch.setattr(svc, "_append_error_log", AsyncMock())
    monkeypatch.setattr(svc, "_finalize_run", AsyncMock())
    monkeypatch.setattr(svc, "_fire_video_payload", fake_fire)

    import agent.services.production_queue_service as pq

    monkeypatch.setattr(pq, "build_execution_payload", fake_build)

    await svc._live_video_loop("run-v")
    assert any(c[0] == "build" for c in calls)
    assert any(c[0] == "fire" for c in calls)


@pytest.mark.asyncio
async def test_avatar_bulk_prompt_snapshot_includes_free_hand_law(monkeypatch):
    """Bulk avatar create must snapshot the runtime-hardened free-hand prompt."""
    created_items: list[dict] = []

    async def fake_create_bulk_generation_item(bulk_item_id, **kwargs):
        created_items.append({"bulk_item_id": bulk_item_id, **kwargs})
        return bulk_item_id

    async def fake_create_bulk_generation_run(bulk_run_id, **kwargs):
        return {"bulk_run_id": bulk_run_id, **kwargs}

    monkeypatch.setattr(svc.crud, "create_bulk_generation_run", fake_create_bulk_generation_run)
    monkeypatch.setattr(svc.crud, "create_bulk_generation_item", fake_create_bulk_generation_item)
    monkeypatch.setattr(svc.crud, "list_creative_assets", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        svc.crud,
        "get_bulk_generation_run",
        AsyncMock(return_value={"bulk_run_id": "x", "status": "PENDING"}),
    )

    # Use the real get_generation_prompt (not mocked) so free-hand hardening is proven.
    result = await svc.create_avatar_image_bulk_run(
        ["BOS_F_ALYA_01"],
        skip_already_generated=False,
    )
    assert result["total_expected"] == 1
    assert len(created_items) == 1
    snap = created_items[0]["prompt_snapshot"] or ""
    assert "AVATAR REFERENCE FREE-HAND LAW" in snap
    assert "empty and free" in snap.lower()
    assert "no cup, bottle, phone" in snap.lower()
