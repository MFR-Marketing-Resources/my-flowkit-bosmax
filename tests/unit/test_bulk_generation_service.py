"""Unit tests for bulk generation orchestrator service."""
from __future__ import annotations

import pytest

from agent.db import crud
from agent.services import bulk_generation_service as svc


@pytest.mark.asyncio
async def test_create_avatar_bulk_run_persists_items(monkeypatch):
    def fake_prompt(code: str):
        return {
            "avatar_code": code,
            "character_name": "Test",
            "prompt": f"prompt for {code}",
            "prompt_version": "v1",
        }

    async def fake_generated():
        return {}

    monkeypatch.setattr(
        "agent.services.bulk_generation_service._generated_avatar_asset_ids",
        fake_generated,
    )
    monkeypatch.setattr(
        "agent.services.avatar_registry.get_generation_prompt",
        fake_prompt,
    )

    result = await svc.create_avatar_image_bulk_run(
        ["AVT001", "AVT002"],
        max_parallel_images=5,
    )
    assert result["bulk_run_id"]
    assert result["total_expected"] == 2
    assert result["max_parallel_images"] == 3

    run = await crud.get_bulk_generation_run(result["bulk_run_id"])
    assert run is not None
    assert run["kind"] == "AVATAR_IMAGE"
    items = await crud.list_bulk_generation_items(result["bulk_run_id"])
    assert len(items) == 2
    assert {i["source_ref"] for i in items} == {"AVT001", "AVT002"}


@pytest.mark.asyncio
async def test_start_bulk_run_dry_run_without_confirm(monkeypatch):
    def fake_prompt(code: str):
        return {"avatar_code": code, "character_name": "T", "prompt": "p", "prompt_version": "v1"}

    async def fake_generated():
        return {}

    monkeypatch.setattr(
        "agent.services.bulk_generation_service._generated_avatar_asset_ids",
        fake_generated,
    )
    monkeypatch.setattr(
        "agent.services.avatar_registry.get_generation_prompt",
        fake_prompt,
    )

    created = await svc.create_avatar_image_bulk_run(["AVT010"])
    preview = await svc.start_bulk_run(created["bulk_run_id"], dry_run=True)
    assert preview["dry_run"] is True
    assert preview["would_process"] == 1
    assert preview["confirm_credit_burn_required"] is True

    run = await crud.get_bulk_generation_run(created["bulk_run_id"])
    assert run["status"] == "PENDING"


@pytest.mark.asyncio
async def test_bulk_item_status_counts():
    run_id = "bulk-test-counts-001"
    await crud.create_bulk_generation_run(run_id, kind="AVATAR_IMAGE", total_expected=2)
    await crud.create_bulk_generation_item("item-a", bulk_run_id=run_id, item_type="AVATAR_IMAGE", source_ref="A")
    await crud.create_bulk_generation_item("item-b", bulk_run_id=run_id, item_type="AVATAR_IMAGE", source_ref="B")
    await crud.update_bulk_generation_item("item-a", status="FAILED")

    counts = await crud.bulk_item_status_counts(run_id)
    assert counts.get("QUEUED") == 1
    assert counts.get("FAILED") == 1