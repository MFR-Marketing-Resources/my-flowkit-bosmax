"""Provider-free Round 1 closure proofs for restart recovery and Montage worker."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent.db import crud
from agent.services import make_video
from agent.services.montage_run_service import (
    KIND,
    montage_scheduler_tick,
)


def _stamp(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _FakeProvider:
    def __init__(self, media_id: str, project_id: str):
        self.media_id = media_id
        self.project_id = project_id
        self.submit_count = 0
        self.poll_count = 0
        self.retrieve_count = 0

    def submit_once(self) -> dict:
        """Represent the one accepted provider generation in the fixture."""
        self.submit_count += 1
        return {
            "media_id": self.media_id,
            "project_id": self.project_id,
        }

    async def check_video_status_by_media(self, targets):
        self.poll_count += 1
        assert targets == [{"name": self.media_id, "projectId": self.project_id}]
        return {
            "media": [{
                "name": self.media_id,
                "projectId": self.project_id,
                "mediaStatus": {
                    "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
                },
            }]
        }

    async def get_media(self, media_id, media_generation_id=None):
        self.retrieve_count += 1
        assert media_id == self.media_id
        return {
            "encodedVideo": base64.b64encode(b"provider-free-video-bytes").decode(),
        }


async def _seed_single_job(job_id: str, **updates) -> dict:
    job = {
        "job_id": job_id,
        "status": "GENERATING",
        "mode": "F2V",
        "source_mode": "HYBRID",
        "prompt": "provider-free restart fixture",
        "project_id": "project-restart",
        "duration_s": 8,
        "aspect": "9:16",
        "model": "Veo 3.1 - Lite",
        "request_id": f"request-{job_id}",
        "provider_operation_ids": [],
        "direct_media_targets": [],
        "generation_identity": {
            "seed": 7,
            "expected_model": "veo-3.1-lite",
        },
        "provider_generation_submit_count": 1,
        "provider_resubmission": False,
        "artifacts": [],
        **updates,
    }
    row, owner = await make_video._prepare_durable_single_job(
        job,
        idempotency_key=f"key-{job_id}",
        strict=True,
    )
    assert owner is True
    await make_video._sync_durable_single_job(job)
    return row


@pytest.mark.asyncio
async def test_single_restart_resumes_persisted_media_handle_once(tmp_path, monkeypatch):
    media_id = f"restart-media-{uuid4().hex}"
    provider = _FakeProvider(media_id, "project-restart")
    accepted = provider.submit_once()
    job_id = f"g_restart_resume_{uuid4().hex[:10]}"
    await _seed_single_job(
        job_id,
        direct_media_targets=[{
            "name": accepted["media_id"],
            "projectId": accepted["project_id"],
        }],
        provider_operation_ids=[accepted["media_id"]],
        generation_identity={
            "seed": 7,
            "expected_model": "veo-3.1-lite",
            "operation_names": [accepted["media_id"]],
            "provider_generation_submit_count": 1,
        },
    )
    make_video._JOBS.clear()
    make_video._VIDEO_LANE_JOB = None
    monkeypatch.setattr(make_video, "OUTPUT_DIR", tmp_path)
    direct_submit = AsyncMock(side_effect=AssertionError("restart must not submit"))
    monkeypatch.setattr(make_video, "_direct_submit", direct_submit)

    recovered = await make_video.get_durable_job(
        job_id,
        provider_client=provider,
    )

    assert recovered["status"] == "DONE"
    assert provider.submit_count == 1
    assert provider.poll_count == 1
    assert provider.retrieve_count == 1
    direct_submit.assert_not_awaited()
    assert recovered["provider_generation_submit_count"] == 1
    artifact = await crud.get_generated_artifact(media_id)
    assert artifact and artifact["readback_verified"] == 1
    assert artifact["job_id"] == job_id


@pytest.mark.asyncio
async def test_single_restart_after_provider_terminal_retries_artifact_only(tmp_path, monkeypatch):
    media_id = f"terminal-media-{uuid4().hex}"
    provider = _FakeProvider(media_id, "project-terminal")
    provider.submit_once()
    artifact_path = tmp_path / f"{media_id}.mp4"
    artifact_path.write_bytes(b"already-retrieved-provider-free-video")
    job_id = f"g_restart_terminal_{uuid4().hex[:10]}"
    await _seed_single_job(
        job_id,
        status="ARTIFACT_PERSISTENCE_FAILED",
        media_id=media_id,
        local_path=str(artifact_path),
        provider_terminal=True,
        artifacts=[{
            "media_id": media_id,
            "local_path": str(artifact_path),
            "size_mb": 0.1,
        }],
        direct_media_targets=[{"name": media_id, "projectId": "project-terminal"}],
        provider_operation_ids=[media_id],
    )
    make_video._JOBS.clear()
    make_video._VIDEO_LANE_JOB = None
    original_insert = crud.insert_generated_artifact

    async def fail_once(*args, **kwargs):
        raise RuntimeError("forced registration gap")

    monkeypatch.setattr(crud, "insert_generated_artifact", fail_once)
    failed = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=provider,
    )
    assert failed["status"] == "ARTIFACT_PERSISTENCE_FAILED"
    assert provider.poll_count == 0
    assert provider.submit_count == 1

    monkeypatch.setattr(crud, "insert_generated_artifact", original_insert)
    repaired = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=provider,
    )
    assert repaired["status"] == "DONE"
    assert provider.poll_count == 0
    assert provider.submit_count == 1
    assert await crud.get_generated_artifact(media_id)


@pytest.mark.asyncio
async def test_single_restart_without_provider_identity_is_explicitly_unrecoverable():
    job_id = f"g_restart_unrecoverable_{uuid4().hex[:10]}"
    await _seed_single_job(job_id, provider_operation_ids=[], direct_media_targets=[])
    make_video._JOBS.clear()
    make_video._VIDEO_LANE_JOB = None

    provider = AsyncMock()
    recovered = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=provider,
    )

    assert recovered["status"] == "RECOVERY_UNRECOVERABLE"
    assert recovered["recovery_unrecoverable"] is True
    provider.check_video_status_by_media.assert_not_awaited()
    provider.check_video_status.assert_not_awaited()


async def _seed_montage_run(run_id: str, items: list[tuple[str, str, dict]], *, status="GENERATING"):
    config = {
        "product_id": "montage-product",
        "model": "Veo 3.1 - Lite",
        "duration_seconds": 8,
        "async_worker_authorized": True,
        "approved_manifest_id": "manifest-provider-free",
        "worker_poll_interval_s": 5.0,
    }
    await crud.create_bulk_generation_run(
        run_id,
        kind=KIND,
        total_expected=len(items),
        max_parallel_images=1,
        max_parallel_videos=1,
        config_json=json.dumps(config),
    )
    await crud.update_bulk_generation_run(
        run_id,
        status=status,
        config_json=json.dumps(config),
    )
    for scene_id, item_status, extra in items:
        payload = {
            "scene_id": scene_id,
            "beat_id": scene_id,
            "transport_mode": "F2V",
            "workspace_execution_package_id": f"package-{scene_id}",
            "package_prompt": f"prompt-{scene_id}",
            "start_asset_snapshot": {"downloadUrl": f"https://example.test/{scene_id}.png"},
            **extra,
        }
        await crud.create_bulk_generation_item(
            f"item-{uuid4().hex}",
            bulk_run_id=run_id,
            item_type="MONTAGE_SCENE",
            source_ref=scene_id,
            prompt_snapshot=payload["package_prompt"],
            payload_json=json.dumps(payload),
            status=item_status,
        )


@pytest.mark.asyncio
async def test_montage_scheduler_restart_binds_scene_then_dispatches_scene_two_once():
    run_id = f"montage-restart-{uuid4().hex}"
    first_job = f"g_montage_scene_one_{uuid4().hex[:8]}"
    await _seed_montage_run(
        run_id,
        [
            (
                "scene-1",
                "VIDEO_SUBMITTED",
                {
                    "provider_job_id": first_job,
                    "video_job_id": first_job,
                    "provider_identity": {
                        "provider_job_id": first_job,
                        "provider_generation_submit_count": 1,
                        "generation_resubmission_allowed": False,
                    },
                    "async_worker": True,
                    "next_action": "POLL",
                    "next_poll_at": _stamp(datetime.now(timezone.utc) - timedelta(seconds=1)),
                    "poll_deadline_at": _stamp(datetime.now(timezone.utc) + timedelta(minutes=30)),
                    "poll_backoff_s": 5,
                    "resubmission_allowed": False,
                },
            ),
            ("scene-2", "PACKAGE_READY", {}),
        ],
    )
    scene_one_submits = 1  # the submit happened before the simulated restart
    scene_two_submits: list[str] = []
    polled: list[str] = []

    async def poll_fn(job_id: str):
        polled.append(job_id)
        assert job_id == first_job
        return {"status": "DONE", "job_id": job_id, "media_id": "scene-one-media"}

    async def generate_fn(**kwargs):
        scene_two_submits.append(kwargs["scene_id"])
        return {"job_id": "g_montage_scene_two", "media_id": None}

    out = await montage_scheduler_tick(
        poll_fn=poll_fn,
        generate_fn=generate_fn,
    )
    run = out["runs_advanced"]
    assert run == 1
    assert polled == [first_job]
    assert scene_one_submits == 1
    assert scene_two_submits == ["scene-2"]
    assert out["provider_generation_submits"] == 1

    scenes = (await crud.list_bulk_generation_items(run_id))
    by_scene = {
        json.loads(item["payload_json"])["scene_id"]: item
        for item in scenes
    }
    assert by_scene["scene-1"]["status"] == "RESULT_BOUND"
    assert by_scene["scene-2"]["status"] == "VIDEO_SUBMITTED"
    assert json.loads(by_scene["scene-2"]["payload_json"])["provider_generation_submit_count"] == 1


@pytest.mark.asyncio
async def test_montage_scheduler_180_second_render_is_not_premature_timeout():
    run_id = f"montage-long-render-{uuid4().hex}"
    await _seed_montage_run(
        run_id,
        [
            (
                "scene-long",
                "VIDEO_SUBMITTED",
                {
                    "provider_job_id": "g_montage_long",
                    "video_job_id": "g_montage_long",
                    "provider_identity": {"provider_job_id": "g_montage_long"},
                    "async_worker": True,
                    "next_action": "POLL",
                    "next_poll_at": _stamp(datetime.now(timezone.utc) - timedelta(seconds=1)),
                    "poll_deadline_at": _stamp(datetime.now(timezone.utc) + timedelta(minutes=27)),
                    "poll_backoff_s": 5,
                    "render_elapsed_s": 180,
                    "resubmission_allowed": False,
                },
            ),
        ],
    )

    async def pending(_job_id):
        return {"status": "RUNNING", "job_id": "g_montage_long"}

    generate = AsyncMock(side_effect=AssertionError("pending render must not dispatch"))
    await montage_scheduler_tick(poll_fn=pending, generate_fn=generate)

    item = (await crud.list_bulk_generation_items(run_id))[0]
    payload = json.loads(item["payload_json"])
    assert item["status"] == "VIDEO_SUBMITTED"
    assert payload["render_elapsed_s"] == 180
    assert payload["last_poll_status"] == "RUNNING"
    assert payload["next_action"] == "POLL"
    generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_montage_scheduler_skips_poll_until_next_poll_at():
    run_id = f"montage-not-due-{uuid4().hex}"
    await _seed_montage_run(
        run_id,
        [
            (
                "scene-not-due",
                "VIDEO_SUBMITTED",
                {
                    "provider_job_id": "g_montage_not_due",
                    "video_job_id": "g_montage_not_due",
                    "provider_identity": {"provider_job_id": "g_montage_not_due"},
                    "async_worker": True,
                    "next_action": "POLL",
                    "next_poll_at": _stamp(datetime.now(timezone.utc) + timedelta(minutes=10)),
                    "poll_deadline_at": _stamp(datetime.now(timezone.utc) + timedelta(minutes=30)),
                    "poll_backoff_s": 5,
                    "resubmission_allowed": False,
                },
            ),
        ],
    )
    poll = AsyncMock(side_effect=AssertionError("not-due work must not poll"))
    generate = AsyncMock(side_effect=AssertionError("not-due work must not submit"))

    out = await montage_scheduler_tick(poll_fn=poll, generate_fn=generate)

    assert out["provider_calls"] == 0
    assert out["provider_generation_submits"] == 0
    poll.assert_not_awaited()
    generate.assert_not_awaited()
    item = (await crud.list_bulk_generation_items(run_id))[0]
    assert item["status"] == "VIDEO_SUBMITTED"


@pytest.mark.asyncio
async def test_montage_known_provider_job_survives_lost_local_map_without_resubmit(monkeypatch):
    run_id = f"montage-known-provider-{uuid4().hex}"
    job_id = f"g_montage_known_{uuid4().hex[:8]}"
    await _seed_montage_run(
        run_id,
        [
            (
                "scene-known",
                "VIDEO_SUBMITTED",
                {
                    "provider_job_id": job_id,
                    "video_job_id": job_id,
                    "provider_identity": {
                        "provider_job_id": job_id,
                        "provider_generation_submit_count": 1,
                    },
                    "async_worker": True,
                    "next_action": "POLL",
                    "next_poll_at": _stamp(datetime.now(timezone.utc) - timedelta(seconds=1)),
                    "poll_deadline_at": _stamp(datetime.now(timezone.utc) + timedelta(minutes=30)),
                    "poll_backoff_s": 5,
                    "resubmission_allowed": False,
                },
            ),
        ],
    )
    from agent.services import make_video

    monkeypatch.setattr(make_video, "get_job", lambda _job_id: None)
    reconcile = AsyncMock(return_value={
        "job_id": job_id,
        "status": "DONE",
        "media_id": "known-provider-media",
    })
    monkeypatch.setattr(make_video, "reconcile_durable_single_job", reconcile)
    generate = AsyncMock(side_effect=AssertionError("restart must not submit"))

    out = await montage_scheduler_tick(generate_fn=generate)

    reconcile.assert_awaited_once_with(job_id)
    generate.assert_not_awaited()
    assert out["provider_calls"] == 1
    item = (await crud.list_bulk_generation_items(run_id))[0]
    assert item["status"] == "RESULT_BOUND"
