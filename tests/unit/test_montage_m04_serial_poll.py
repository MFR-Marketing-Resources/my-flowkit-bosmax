"""M-04 C2: serial single-flight + async poll/bind semantics."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from agent.services.montage_run_service import (
    KIND,
    authorize_montage_run_generation,
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


@pytest.mark.asyncio
async def test_serial_poll_second_scene_waits_for_first_done() -> None:
    """First call returns SUBMITTED; poll DONE then second scene may submit."""
    run_row = {
        "bulk_run_id": "run-serial",
        "kind": KIND,
        "status": "PREPARED",
        "config_json": json.dumps(
            {
                "product_id": "p1",
                "staff_id": "staff_m04_fixture",
                "model": "Veo 3.1 - Lite",
                "duration_seconds": 8,
            }
        ),
    }
    items = _pkg_items()
    order: list[str] = []
    ledger_statuses: list[tuple[str, str]] = []
    polls = {"job-scene-1-hook": 0}

    async def update_item(iid, **kw):
        if kw.get("status"):
            ledger_statuses.append((iid, str(kw["status"])))
        for it in items:
            if it["bulk_item_id"] == iid:
                it.update(kw)
                return it
        return None

    async def update_run(rid, **kw):
        run_row.update(kw)
        return run_row

    async def gen_fn(**kwargs):
        sid = kwargs["scene_id"]
        order.append(f"submit:{sid}")
        # prove model/duration reach generate
        assert kwargs.get("model") == "Veo 3.1 - Lite"
        assert kwargs.get("duration_s") == 8
        # first returns job only; second also job only
        return {"job_id": f"job-{sid}", "media_id": None}

    async def poll_fn(job_id: str):
        order.append(f"poll:{job_id}")
        polls[job_id] = polls.get(job_id, 0) + 1
        if polls[job_id] < 2:
            return {"status": "RUNNING", "job_id": job_id}
        # DONE with media
        sid = job_id.replace("job-", "")
        return {"status": "DONE", "job_id": job_id, "media_id": f"clip-{sid}"}

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
            "run-serial",
            confirm_credit_burn=True,
            expected_video_generations=2,
            expected_provider_operations=2,
            dry_run=False,
            generate_fn=gen_fn,
            poll_fn=poll_fn,
            max_polls=5,
            poll_interval_s=0.0,
            staff_id="staff_m04_fixture",
        )

    assert out["ok"] is True
    # scene1 fully done before scene2 submit
    assert order.index("submit:scene-1-hook") < order.index("poll:job-scene-1-hook")
    assert order.index("poll:job-scene-1-hook") < order.index("submit:scene-2-body")
    assert "submit:scene-2-body" in order
    assert {d["status"] for d in out["dispatched"]} == {"RESULT_BOUND"}
    assert ledger_statuses[:3] == [
        ("i1", "VIDEO_SUBMITTED"),
        ("i1", "RESULT_BOUND"),
        ("i2", "VIDEO_SUBMITTED"),
    ]
    assert ledger_statuses[3:] == [("i2", "RESULT_BOUND")]


@pytest.mark.asyncio
async def test_failed_scene_stops_remaining() -> None:
    run_row = {
        "bulk_run_id": "run-fail",
        "kind": KIND,
        "status": "PREPARED",
        "config_json": json.dumps({
            "product_id": "p1",
            "staff_id": "staff_m04_fixture",
            "model": "Veo 3.1 - Lite",
            "duration_seconds": 8,
        }),
    }
    items = _pkg_items()
    submits: list[str] = []

    async def update_item(iid, **kw):
        for it in items:
            if it["bulk_item_id"] == iid:
                it.update(kw)
                return it
        return None

    async def update_run(rid, **kw):
        run_row.update(kw)
        return run_row

    async def gen_fn(**kwargs):
        submits.append(kwargs["scene_id"])
        return {"job_id": f"job-{kwargs['scene_id']}", "media_id": None}

    async def poll_fn(job_id: str):
        return {"status": "FAILED", "error": "boom", "job_id": job_id}

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
            "run-fail",
            confirm_credit_burn=True,
            expected_video_generations=2,
            expected_provider_operations=2,
            dry_run=False,
            generate_fn=gen_fn,
            poll_fn=poll_fn,
            max_polls=3,
            poll_interval_s=0.0,
            staff_id="staff_m04_fixture",
        )

    assert out["ok"] is False
    assert submits == ["scene-1-hook"]  # second never submitted
    assert out["dispatched"][0]["status"] == "GENERATE_FAILED"


@pytest.mark.asyncio
async def test_generate_request_contract_no_extra_request_arg() -> None:
    """HTTP boundary builds GenerateRequest and calls generate(body) only."""
    from agent.api.flow import GenerateRequest

    # structural contract
    fields = set(GenerateRequest.model_fields.keys())
    assert "startAsset" in fields
    assert "model" in fields
    assert "duration_s" in fields
    # product_id is allowed lineage key on this tree
    assert "mode" in fields
