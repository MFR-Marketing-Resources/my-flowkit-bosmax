"""Flow artifact API retention and explicit image-delete contract."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from agent.api import flow
from agent.db import crud


def _run(coro):
    return asyncio.run(coro)


def _ts(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


async def _insert_at(media_id: str, *, kind: str, created_at: str, local_path: str):
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            """INSERT OR REPLACE INTO generated_artifact
               (media_id, job_id, mode, artifact_kind, local_path, size_mb,
                project_id, model_used, duration_used, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (media_id, "api-test-job", "IMG", kind, local_path, 0.1,
             None, None, None, created_at),
        )
        await db.commit()


def test_image_listing_is_persistent_and_has_no_expiry(tmp_path):
    media_id = f"api-old-image-{uuid.uuid4().hex[:8]}"
    image_file = tmp_path / f"{media_id}.jpg"
    image_file.write_bytes(b"image")

    async def scenario():
        await _insert_at(
            media_id,
            kind="image",
            created_at=_ts(49),
            local_path=str(image_file),
        )
        response = await flow.list_artifacts(kind="image", limit=100)
        item = next(row for row in response["artifacts"] if row["media_id"] == media_id)
        assert item["expires_at"] is None
        assert item["expires_in_hours"] is None
        db = await crud.get_db()
        async with crud._db_lock:
            await db.execute(
                "DELETE FROM generated_artifact WHERE media_id = ?", (media_id,)
            )
            await db.commit()

    _run(scenario())
    assert image_file.exists()


def test_manual_delete_endpoint_removes_images_but_not_videos(tmp_path):
    image_id = f"api-delete-image-{uuid.uuid4().hex[:8]}"
    video_id = f"api-delete-video-{uuid.uuid4().hex[:8]}"
    image_file = tmp_path / f"{image_id}.jpg"
    image_file.write_bytes(b"image")

    async def scenario():
        await _insert_at(
            image_id,
            kind="image",
            created_at=_ts(1),
            local_path=str(image_file),
        )
        await _insert_at(
            video_id,
            kind="video",
            created_at=_ts(1),
            local_path=str(tmp_path / f"{video_id}.mp4"),
        )

        deleted = await flow.delete_image_artifact(image_id)
        assert deleted["deleted"] == 1
        assert not image_file.exists()
        assert await crud.get_generated_artifact(image_id) is None

        with pytest.raises(HTTPException) as exc:
            await flow.delete_image_artifact(video_id)
        assert exc.value.status_code == 409
        assert await crud.get_generated_artifact(video_id) is not None
        await crud.delete_generated_artifact(video_id)

    _run(scenario())


def test_video_library_requests_final_projection_while_image_is_unchanged(monkeypatch):
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(crud, "list_generated_artifacts", listing)
    monkeypatch.setattr(
        crud, "purge_expired_artifacts", AsyncMock(return_value={"purged": 0})
    )

    _run(flow.list_artifacts(kind="video", limit=17))
    assert listing.await_args.kwargs["final_only"] is True

    _run(flow.list_artifacts(kind="image", limit=17))
    assert listing.await_args.kwargs["final_only"] is False
