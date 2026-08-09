"""M-04: operator-authorized multi-scene generation + credit count gate."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.services.montage_run_service import (
    KIND,
    authorize_montage_run_generation,
    estimate_montage_generation_from_scenes,
    estimate_montage_run_generation,
    readiness_from_montage_run,
)


def _pkg_items():
    return [
        {
            "bulk_item_id": "i1",
            "source_ref": "scene-1-hook",
            "status": "PACKAGE_READY",
            "payload_json": json.dumps(
                {
                    "scene_id": "scene-1-hook",
                    "beat_id": "hook",
                    "transport_mode": "F2V",
                    "reference_policy": "PRODUCT_ANCHOR",
                    "workspace_execution_package_id": "wep-1",
                    "package_prompt": "hook prompt",
                    "start_asset_snapshot": {
                        "assetId": "ca_start",
                        "mediaId": None,
                        "downloadUrl": "https://cdn.example/start.png",
                    },
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
                    "transport_mode": "F2V",
                    "reference_policy": "PRODUCT_ANCHOR",
                    "workspace_execution_package_id": "wep-2",
                    "package_prompt": "body prompt",
                    "start_asset_snapshot": {
                        "assetId": "ca_body",
                        "downloadUrl": "https://cdn.example/body.png",
                    },
                }
            ),
        },
    ]


def test_estimate_counts_pending_packages() -> None:
    scenes = [
        {
            "scene_id": "a",
            "status": "PACKAGE_READY",
            "workspace_execution_package_id": "w1",
        },
        {
            "scene_id": "b",
            "status": "RESULT_BOUND",
            "workspace_execution_package_id": "w2",
            "video_media_id": "v1",
        },
        {
            "scene_id": "c",
            "status": "PACKAGE_READY",
            "workspace_execution_package_id": "w3",
        },
    ]
    est = estimate_montage_generation_from_scenes(scenes)
    assert est["expected_video_generations"] == 2
    assert est["pending_scene_ids"] == ["a", "c"]
    assert est["summary"] == "2 pending scene video(s) = 2 provider operation(s)"


@pytest.mark.asyncio
async def test_authorize_requires_confirm_and_matching_count() -> None:
    run_row = {
        "bulk_run_id": "run-m04",
        "kind": KIND,
        "status": "PREPARED",
        "config_json": json.dumps({"product_id": "p1", "model": "Veo 3.1 - Lite", "duration_seconds": 8}),
    }
    items = _pkg_items()

    with (
        patch(
            "agent.services.montage_run_service.crud.get_bulk_generation_run",
            AsyncMock(return_value=run_row),
        ),
        patch(
            "agent.services.montage_run_service.crud.list_bulk_generation_items",
            AsyncMock(return_value=items),
        ),
    ):
        with pytest.raises(ValueError, match="CREDIT_CONFIRM"):
            await authorize_montage_run_generation(
                "run-m04",
                confirm_credit_burn=False,
                expected_video_generations=2,
                expected_provider_operations=2,
                dry_run=True,
            )
        with pytest.raises(ValueError, match="CREDIT_COUNT_MISMATCH"):
            await authorize_montage_run_generation(
                "run-m04",
                confirm_credit_burn=True,
                expected_video_generations=99,
                expected_provider_operations=99,
                dry_run=True,
            )
        dry = await authorize_montage_run_generation(
            "run-m04",
            confirm_credit_burn=True,
            expected_video_generations=2,
            expected_provider_operations=2,
            dry_run=True,
        )
        assert dry["ok"] is True
        assert dry["authorized"] is True
        assert dry["credit_spend"] is False
        assert dry["dispatched"] == []
        assert dry["summary"] == "2 pending scene video(s) = 2 provider operation(s)"


@pytest.mark.asyncio
async def test_authorize_dispatch_calls_generate_with_start_asset_and_binds() -> None:
    run_row = {
        "bulk_run_id": "run-m04b",
        "kind": KIND,
        "status": "PREPARED",
        "config_json": json.dumps({"product_id": "p1", "product_media_id": "pm1", "model": "Veo 3.1 - Lite", "duration_seconds": 8}),
    }
    items = _pkg_items()

    async def update_item(iid, **kw):
        for it in items:
            if it["bulk_item_id"] == iid:
                it.update(kw)
                return it
        return None

    async def update_run(rid, **kw):
        run_row.update(kw)
        return run_row

    calls: list[dict] = []

    async def gen_fn(**kwargs):
        calls.append(kwargs)
        sid = kwargs["scene_id"]
        return {"job_id": f"job-{sid}", "media_id": f"clip-{sid}"}

    with (
        patch(
            "agent.services.montage_run_service.crud.get_bulk_generation_run",
            AsyncMock(return_value=run_row),
        ),
        patch(
            "agent.services.montage_run_service.crud.list_bulk_generation_items",
            AsyncMock(return_value=items),
        ),
        patch(
            "agent.services.montage_run_service.crud.update_bulk_generation_item",
            side_effect=update_item,
        ),
        patch(
            "agent.services.montage_run_service.crud.update_bulk_generation_run",
            side_effect=update_run,
        ),
    ):
        out = await authorize_montage_run_generation(
            "run-m04b",
            confirm_credit_burn=True,
            expected_video_generations=2,
            expected_provider_operations=2,
            dry_run=False,
            generate_fn=gen_fn,
        )
        assert out["ok"] is True
        assert out["credit_spend"] is True
        assert len(out["dispatched"]) == 2
        assert len(calls) == 2
        # F-05-style transport: start_asset present, not package-id-only
        assert calls[0]["start_asset"]["downloadUrl"].startswith("https://")
        assert calls[0]["workspace_execution_package_id"]
        assert calls[0]["mode"] == "F2V"

        ready = await readiness_from_montage_run("run-m04b")
        assert ready["ok"] is True
        assert set(ready["clip_media_ids"]) == {
            "clip-scene-1-hook",
            "clip-scene-2-body",
        }


@pytest.mark.asyncio
async def test_authorize_live_without_generate_fn_fails_closed() -> None:
    run_row = {
        "bulk_run_id": "run-m04c",
        "kind": KIND,
        "status": "PREPARED",
        "config_json": "{}",
    }
    items = _pkg_items()
    with (
        patch(
            "agent.services.montage_run_service.crud.get_bulk_generation_run",
            AsyncMock(return_value=run_row),
        ),
        patch(
            "agent.services.montage_run_service.crud.list_bulk_generation_items",
            AsyncMock(return_value=items),
        ),
    ):
        with pytest.raises(ValueError, match="GENERATE_BOUNDARY"):
            await authorize_montage_run_generation(
                "run-m04c",
                confirm_credit_burn=True,
                expected_video_generations=2,
                expected_provider_operations=2,
                dry_run=False,
                generate_fn=None,
            )
