"""Durable generation_result record (Results Hub) — crud behavior.

The heavy artifact FILE is purged at 48h; the generation_result record and the
social captions are NOT — so the prompt/settings/caption stay reachable for
manual Google Flow fallback + publishing after the file is gone.
"""
import json
from datetime import datetime, timedelta, timezone

from agent.db import crud


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


async def test_insert_get_roundtrip():
    await crud.insert_generation_result(
        "media-1",
        job_id="g_1", request_id="req_1", mode="T2V", artifact_kind="video",
        product_id=None, product_name="Bosmax",
        final_prompt_text="a cinematic hero shot",
        aspect_ratio="9:16", model_label="Omni Flash", duration_s=8,
        count_setting=2, reference_media_ids=["ref-a", "ref-b"],
        workspace_generation_package_id="wgp_1", project_id="proj_1",
    )
    row = await crud.get_generation_result("media-1")
    assert row is not None
    assert row["final_prompt_text"] == "a cinematic hero shot"
    assert row["aspect_ratio"] == "9:16"
    assert row["model_label"] == "Omni Flash"
    assert row["duration_s"] == 8
    assert row["count_setting"] == 2
    assert json.loads(row["reference_media_ids_json"]) == ["ref-a", "ref-b"]


async def test_upsert_updates_snapshot_but_preserves_created_at():
    await crud.insert_generation_result("media-2", final_prompt_text="first")
    first = await crud.get_generation_result("media-2")
    await crud.insert_generation_result("media-2", final_prompt_text="second")
    second = await crud.get_generation_result("media-2")
    assert second["final_prompt_text"] == "second"       # snapshot updated
    assert second["created_at"] == first["created_at"]   # ordering stays stable


async def test_record_survives_artifact_purge():
    """The whole point of the split: purging the 48h file removes the artifact
    row, but the durable record (prompt/settings) stays reachable."""
    await crud.insert_generation_result(
        "media-3", mode="IMG", artifact_kind="image",
        final_prompt_text="a product on marble")
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            """INSERT OR REPLACE INTO generated_artifact
               (media_id, job_id, mode, artifact_kind, local_path, size_mb,
                project_id, model_used, duration_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            ("media-3", "g_3", "IMG", "image", None, 0.5, None, None, None, _ts(49)))
        await db.commit()

    purged = await crud.purge_expired_artifacts(retention_hours=48)
    assert purged["purged_rows"] >= 1
    assert await crud.get_generated_artifact("media-3") is None      # file row gone
    survived = await crud.get_generation_result("media-3")
    assert survived is not None                                      # record stays
    assert survived["final_prompt_text"] == "a product on marble"


async def test_list_filters_by_kind_and_mode():
    # NOTE: the Windows test DB is not always wiped between tests (locked file),
    # so assert on membership + filter correctness, never on the global set.
    await crud.insert_generation_result("gr-v1", mode="T2V", artifact_kind="video")
    await crud.insert_generation_result("gr-i1", mode="IMG", artifact_kind="image")
    videos = await crud.list_generation_results(kind="video", limit=200)
    vids = {r["media_id"] for r in videos}
    assert "gr-v1" in vids
    assert "gr-i1" not in vids
    assert all(r["artifact_kind"] == "video" for r in videos)
    imgs = await crud.list_generation_results(mode="IMG", limit=200)
    assert "gr-i1" in {r["media_id"] for r in imgs}
    assert all(r["mode"] == "IMG" for r in imgs)


async def test_caption_summary_rollup_counts_and_approved():
    await crud.insert_generated_artifact(
        "m-cap", job_id="j", mode="IMG", artifact_kind="image")
    await crud.create_social_copy_package(
        "scp_a", artifact_media_id="m-cap", platform="tiktok", status="DRAFT")
    await crud.create_social_copy_package(
        "scp_b", artifact_media_id="m-cap", platform="instagram", status="APPROVED")
    summary = await crud.caption_summary_for_media_ids(["m-cap", "absent"])
    assert summary["m-cap"] == {"count": 2, "approved": 1}
    assert "absent" not in summary


async def test_caption_summary_empty_input():
    assert await crud.caption_summary_for_media_ids([]) == {}
    assert await crud.caption_summary_for_media_ids(None) == {}
