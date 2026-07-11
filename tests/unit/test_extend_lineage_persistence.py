"""Durable extend_lineage — four separate id columns, idempotency, durability."""
import uuid

import pytest

from agent.db import crud


async def test_insert_update_list_keeps_four_id_columns():
    lid = str(uuid.uuid4())
    row = await crud.insert_extend_lineage(
        lid, workspace_generation_package_id="wgp1", project_id="p", scene_id="s",
        block_index=2, block_position=1,
        parent_operation_id="b6371e69", parent_primary_media_id="69051c7b",
        child_operation_id="164c65b0", child_primary_media_id="164c65b0",
        child_workflow_id="737b10c8", model_key="veo_3_1_extension_lite",
        aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT", start_frame_index=1,
        end_frame_index=24, continuation_prompt_hash="h", idempotency_key="idem-1",
        polling_state="EXTEND_SUBMITTED",
    )
    # parent op id and primary media id are DISTINCT columns, never collapsed
    assert row["parent_operation_id"] == "b6371e69"
    assert row["parent_primary_media_id"] == "69051c7b"
    assert row["parent_operation_id"] != row["parent_primary_media_id"]
    assert row["child_operation_id"] == "164c65b0"
    assert row["child_workflow_id"] == "737b10c8"

    upd = await crud.update_extend_lineage(
        lid, polling_state="EXTEND_SUCCEEDED", output_url="https://flow-content.google/video/164c65b0")
    assert upd["polling_state"] == "EXTEND_SUCCEEDED"
    assert upd["output_url"].startswith("https://flow-content.google/")

    by_child = await crud.get_extend_lineage_by_child("164c65b0")
    assert by_child["extend_lineage_id"] == lid
    rows = await crud.list_extend_lineage(workspace_generation_package_id="wgp1")
    assert len(rows) == 1 and rows[0]["extend_lineage_id"] == lid


async def test_idempotency_key_unique_blocks_duplicate_row():
    await crud.insert_extend_lineage(
        str(uuid.uuid4()), project_id="p", scene_id="s", block_position=1,
        idempotency_key="dup")
    with pytest.raises(Exception):  # sqlite IntegrityError on UNIQUE idempotency_key
        await crud.insert_extend_lineage(
            str(uuid.uuid4()), project_id="p", scene_id="s", block_position=1,
            idempotency_key="dup")
    assert await crud.get_extend_lineage_by_idempotency("dup") is not None


async def test_durable_survives_artifact_purge():
    lid = str(uuid.uuid4())
    await crud.insert_extend_lineage(lid, project_id="p", scene_id="s",
                                     idempotency_key="dur")
    # purge_expired_artifacts touches ONLY generated_artifact — lineage is durable
    await crud.purge_expired_artifacts(retention_hours=0)
    assert await crud.get_extend_lineage(lid) is not None
