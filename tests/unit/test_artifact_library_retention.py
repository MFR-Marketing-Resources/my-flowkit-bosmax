"""Library retention law (48h) + kind filtering.

Results collect in the LIBRARY pages, retained 48 hours, then the FILE and the
DB record are auto-deleted (lazily, on every listing). Workspace pages stay
workplaces.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.db import crud
from agent.db.schema import init_db


def _run(coro):
    return asyncio.run(coro)


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


async def _insert(media_id: str, *, kind: str, created_at: str, local_path: str):
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            """INSERT OR REPLACE INTO generated_artifact
               (media_id, job_id, mode, artifact_kind, local_path, size_mb,
                project_id, model_used, duration_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (media_id, "g_test", "F2V", kind, local_path, 1.0,
             "p_test", None, None, created_at),
        )
        await db.commit()


async def _fetch(media_id: str):
    db = await crud.get_db()
    cursor = await db.execute(
        "SELECT media_id FROM generated_artifact WHERE media_id = ?", (media_id,))
    return await cursor.fetchone()


def test_purge_deletes_expired_file_and_row_keeps_fresh(tmp_path):
    _run(init_db())
    old_id = f"test-old-{uuid.uuid4().hex[:8]}"
    fresh_id = f"test-fresh-{uuid.uuid4().hex[:8]}"
    old_file = tmp_path / f"{old_id}.mp4"
    fresh_file = tmp_path / f"{fresh_id}.mp4"
    old_file.write_bytes(b"expired")
    fresh_file.write_bytes(b"fresh")

    async def scenario():
        await _insert(old_id, kind="video", created_at=_ts(49), local_path=str(old_file))
        await _insert(fresh_id, kind="video", created_at=_ts(1), local_path=str(fresh_file))
        result = await crud.purge_expired_artifacts(retention_hours=48)
        assert result["purged_rows"] >= 1
        assert await _fetch(old_id) is None, "expired row must be deleted"
        assert await _fetch(fresh_id) is not None, "fresh row must survive"
        # cleanup the fresh test row
        db = await crud.get_db()
        async with crud._db_lock:
            await db.execute("DELETE FROM generated_artifact WHERE media_id = ?", (fresh_id,))
            await db.commit()

    _run(scenario())
    assert not old_file.exists(), "expired FILE must be deleted from disk"
    assert fresh_file.exists(), "fresh file must survive"


def test_list_filters_by_kind(tmp_path):
    _run(init_db())
    vid_id = f"test-vid-{uuid.uuid4().hex[:8]}"
    img_id = f"test-img-{uuid.uuid4().hex[:8]}"

    async def scenario():
        await _insert(vid_id, kind="video", created_at=_ts(1),
                      local_path=str(tmp_path / "v.mp4"))
        await _insert(img_id, kind="image", created_at=_ts(1),
                      local_path=str(tmp_path / "i.jpg"))
        videos = await crud.list_generated_artifacts(limit=100, kind="video")
        images = await crud.list_generated_artifacts(limit=100, kind="image")
        video_ids = {a["media_id"] for a in videos}
        image_ids = {a["media_id"] for a in images}
        assert vid_id in video_ids and vid_id not in image_ids
        assert img_id in image_ids and img_id not in video_ids
        db = await crud.get_db()
        async with crud._db_lock:
            await db.execute(
                "DELETE FROM generated_artifact WHERE media_id IN (?, ?)",
                (vid_id, img_id))
            await db.commit()

    _run(scenario())


def test_purge_does_not_touch_canonical_avatar_or_product_assets(tmp_path):
    _run(init_db())
    temp_id = f"temp-img-{uuid.uuid4().hex[:8]}"
    temp_file = tmp_path / f"{temp_id}.jpg"
    avatar_file = tmp_path / "canonical-avatar.jpg"
    product_file = tmp_path / "canonical-product.jpg"
    temp_file.write_bytes(b"temp")
    avatar_file.write_bytes(b"avatar")
    product_file.write_bytes(b"product")

    async def scenario():
        await _insert(temp_id, kind="image", created_at=_ts(72), local_path=str(temp_file))
        await crud.create_creative_asset(
            asset_id="ca_avatar_keep",
            semantic_role="CHARACTER_REFERENCE",
            display_name="Avatar Keep",
            description="AVATAR_CODE:BOS_F_KEEP_01 canonical",
            source_type="GENERATED_IMAGE",
            storage_kind="LOCAL_FILE",
            preview_url="/api/creative-assets/ca_avatar_keep/preview",
            download_url="/api/creative-assets/ca_avatar_keep/download",
            media_id=None,
            local_file_path=str(avatar_file),
            remote_source_url=None,
            product_id=None,
            category=None,
            silo=None,
            product_type=None,
            allowed_modes="[]",
            engine_slot_eligibility="[]",
            mode_a_metadata_handoff=None,
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            asset_subtype=None,
            generation_recipe_id=None,
            source_character_asset_id=None,
            source_scene_asset_id=None,
            source_style_asset_id=None,
            contains_rendered_text=False,
            approved_for_video_support=False,
            approved_for_poster=False,
            product_truth_status=None,
            identity_lock_status=None,
            scale_truth_status=None,
            claim_safety_status=None,
            review_status="APPROVED",
            asset_lifecycle="CANONICAL_AVATAR_ASSET",
            retention_policy="PERSISTENT",
            expires_at=None,
            is_reusable=True,
            is_canonical=True,
            source_job_id=None,
            avatar_code="BOS_F_KEEP_01",
            status="ACTIVE",
        )
        await crud.create_creative_asset(
            asset_id="ca_product_keep",
            semantic_role="PRODUCT_REFERENCE",
            display_name="Product Keep",
            description="canonical product asset",
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            preview_url="/api/creative-assets/ca_product_keep/preview",
            download_url="/api/creative-assets/ca_product_keep/download",
            media_id=None,
            local_file_path=str(product_file),
            remote_source_url=None,
            product_id=None,
            category=None,
            silo=None,
            product_type=None,
            allowed_modes="[]",
            engine_slot_eligibility="[]",
            mode_a_metadata_handoff=None,
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            asset_subtype=None,
            generation_recipe_id=None,
            source_character_asset_id=None,
            source_scene_asset_id=None,
            source_style_asset_id=None,
            contains_rendered_text=False,
            approved_for_video_support=False,
            approved_for_poster=False,
            product_truth_status=None,
            identity_lock_status=None,
            scale_truth_status=None,
            claim_safety_status=None,
            review_status="APPROVED",
            asset_lifecycle="CANONICAL_PRODUCT_ASSET",
            retention_policy="PERSISTENT",
            expires_at=None,
            is_reusable=True,
            is_canonical=True,
            source_job_id=None,
            avatar_code=None,
            status="ACTIVE",
        )

        result = await crud.purge_expired_artifacts(retention_hours=48)
        assert result["purged_rows"] >= 1

        avatar_row = await crud.get_creative_asset("ca_avatar_keep")
        product_row = await crud.get_creative_asset("ca_product_keep")
        assert avatar_row is not None
        assert product_row is not None

    _run(scenario())
    assert not temp_file.exists(), "expired temp artifact file must be deleted"
    assert avatar_file.exists(), "canonical avatar asset file must survive cleanup"
    assert product_file.exists(), "canonical product asset file must survive cleanup"
