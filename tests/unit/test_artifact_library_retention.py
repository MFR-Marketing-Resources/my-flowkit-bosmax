"""Kind-aware library retention (video 48h, image manual delete) + filtering.

Video results collect in the LIBRARY pages, retained 48 hours, then the FILE and
DB record are auto-deleted (lazily, on every listing). Image artifacts remain
until an explicit manual delete. Workspace pages stay workplaces.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

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


def test_expired_image_survives_retention_sweep(tmp_path):
    image_id = f"test-old-image-{uuid.uuid4().hex[:8]}"
    image_file = tmp_path / f"{image_id}.jpg"
    image_file.write_bytes(b"persistent-image")

    async def scenario():
        await _insert(
            image_id,
            kind="image",
            created_at=_ts(49),
            local_path=str(image_file),
        )
        await crud.purge_expired_artifacts(retention_hours=48)
        assert await _fetch(image_id) is not None, "expired images remain until manual delete"
        assert image_file.exists(), "retention sweep must not delete image files"
        db = await crud.get_db()
        async with crud._db_lock:
            await db.execute(
                "DELETE FROM generated_artifact WHERE media_id = ?", (image_id,)
            )
            await db.commit()

    _run(scenario())
    assert image_file.exists(), "the test image was not deleted by retention"


async def test_purged_final_is_not_repaired_or_resubmitted_after_restart(tmp_path, monkeypatch):
    from agent.services import video_production_orchestrator as orch

    media_id = "final-retention-restart"
    job_id = "vj_retention_restart"
    path = tmp_path / "final.mp4"
    path.write_bytes(b"delivered-video")
    await crud.create_video_production_job_full(
        job_id, logical_job_key=job_id, status=orch.S_COMPLETE,
        stage_state_json=json.dumps({"existing_evidence": {"keep": True}}),
    )
    await crud.update_video_production_job_full(
        job_id, final_media_id=media_id, final_local_path=str(path),
        final_concat_job_name="projects/test/jobs/final",
    )
    await _insert(media_id, kind="video", created_at=_ts(49), local_path=str(path))
    await crud.insert_generation_result(media_id, job_id=job_id, artifact_kind="video")

    await crud.purge_expired_artifacts()
    job = await crud.get_video_production_job(job_id)
    state = json.loads(job["stage_state_json"])
    assert state["existing_evidence"] == {"keep": True}
    assert state["artifact_retention_v1"]["media_id"] == media_id
    assert state["artifact_retention_v1"]["status"] == "EXPIRED"
    assert not path.exists()
    assert await crud.get_generation_result(media_id) is not None
    assert await crud.list_incomplete_final_video_deliveries() == []

    register = AsyncMock(side_effect=AssertionError("expired output must not be repaired"))
    generate = AsyncMock(side_effect=AssertionError("retention must not submit"))
    monkeypatch.setattr(orch, "_register_and_bind_final_delivery", register)
    summary = await orch.reconcile_incomplete_final_deliveries()
    assert summary["provider_submits"] == summary["failed"] == 0
    result = await orch.advance_job(
        None, job_id, authorization_token="", generate_initial=generate, resume_only=True,
    )
    assert result["status"] == orch.S_COMPLETE
    assert result["artifact_availability"] == "EXPIRED"
    register.assert_not_awaited()
    generate.assert_not_awaited()
    before = await crud.get_video_production_job(job_id)
    await crud.purge_expired_artifacts()
    assert await crud.get_video_production_job(job_id) == before


async def test_missing_final_without_retention_evidence_is_not_called_expired(tmp_path, monkeypatch):
    from agent.services import video_production_orchestrator as orch

    job_id = "vj_missing_final"
    await crud.create_video_production_job_full(job_id, logical_job_key=job_id)
    await crud.update_video_production_job_full(
        job_id, final_media_id="final-missing", final_local_path=str(tmp_path / "missing.mp4"),
        final_concat_job_name="projects/test/jobs/missing",
    )
    real_register = orch._register_and_bind_final_delivery
    register = AsyncMock(side_effect=AssertionError("no final bytes to register"))
    monkeypatch.setattr(orch, "_register_and_bind_final_delivery", register)
    summary = await orch.reconcile_incomplete_final_deliveries()
    job = await crud.get_video_production_job(job_id)
    assert summary["missing_files"] == 1
    assert summary["provider_submits"] == 0
    assert job["status"] == orch.F_FINAL_ARTIFACT
    assert job["error_code"] == "FINAL_ARTIFACT_FILE_MISSING"
    assert "artifact_retention_v1" not in json.loads(job["stage_state_json"] or "{}")
    register.assert_not_awaited()
    await orch.reconcile_incomplete_final_deliveries()
    assert await crud.get_video_production_job(job_id) == job

    # Restoring existing bytes re-enables local delivery; the diagnostic must
    # not permanently exclude the job or require a new provider submission.
    (tmp_path / "missing.mp4").write_bytes(b"recovered-existing-final")
    monkeypatch.setattr(orch, "_register_and_bind_final_delivery", real_register)
    summary = await orch.reconcile_incomplete_final_deliveries()
    assert summary["repaired"] == 1
    assert summary["provider_submits"] == 0
    recovered = await crud.get_video_production_job(job_id)
    assert recovered["status"] == orch.S_COMPLETE
    assert recovered["error_code"] is None
    assert (await crud.get_final_video_delivery("final-missing"))["complete"]


async def test_expiry_receipt_for_another_media_does_not_hide_current_final(tmp_path):
    from agent.services import video_production_orchestrator as orch

    job_id = "vj_rebound_final"
    await crud.create_video_production_job_full(
        job_id, logical_job_key=job_id,
        stage_state_json=json.dumps({
            "artifact_retention_v1": {"media_id": "old-final", "status": "EXPIRED"},
        }),
    )
    await crud.update_video_production_job_full(
        job_id, final_media_id="current-final", final_local_path=str(tmp_path / "current.mp4"),
        final_concat_job_name="projects/test/jobs/current",
    )
    candidates = await crud.list_incomplete_final_video_deliveries()
    assert [j["job_id"] for j in candidates] == [job_id]
    assert not orch._final_artifact_expired(candidates[0])
    await crud.update_video_production_job_full(job_id, stage_state_json="invalid-legacy-json")
    candidates = await crud.list_incomplete_final_video_deliveries()
    assert [j["job_id"] for j in candidates] == [job_id]
    assert not orch._final_artifact_expired(candidates[0])
