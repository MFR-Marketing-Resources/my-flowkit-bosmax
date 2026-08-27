"""Provider-free Round 1 closure proofs for restart recovery and Montage worker."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent.db import crud
from agent.services import make_video
from agent.services.flow_client import FlowClient
from agent.services.montage_run_service import (
    KIND,
    _default_montage_generate_fn,
    load_montage_execution_identity,
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


class _ProjectHistoryProvider(_FakeProvider):
    def __init__(self, media_id: str, project_id: str, media: list[dict]):
        super().__init__(media_id, project_id)
        self.media = media
        self.history_reads = 0

    async def list_project_media(self, project_id):
        self.history_reads += 1
        assert project_id == self.project_id
        return {
            "status": 200,
            "project_id": self.project_id,
            "media": self.media,
        }


def _history_media(media_id: str, project_id: str, prompt: str) -> dict:
    created = datetime.now(timezone.utc)
    return {
        "name": media_id,
        "projectId": project_id,
        "workflowId": f"workflow-{media_id}",
        "mediaMetadata": {
            "createTime": created.isoformat().replace("+00:00", "Z"),
            "mediaStatus": {
                "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
            },
        },
        "video": {
            "generatedVideo": {
                "prompt": f"<root><instruction><prompt>{prompt}</prompt></instruction></root>",
                "model": "veo_3_1_t2v_lite",
                "aspectRatio": "VIDEO_ASPECT_RATIO_PORTRAIT",
                "seed": 537780,
            },
        },
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


@pytest.mark.asyncio
async def test_single_restart_recovers_one_exact_project_history_identity(
    tmp_path, monkeypatch
):
    prompt = "exact paid creation-agent prompt"
    project_id = "project-history-recovery"
    media_id = f"history-media-{uuid4().hex}"
    provider = _ProjectHistoryProvider(
        media_id,
        project_id,
        [_history_media(media_id, project_id, prompt)],
    )
    provider.submit_once()
    job_id = f"g_history_recovery_{uuid4().hex[:10]}"
    await _seed_single_job(
        job_id,
        status="RECOVERY_UNRECOVERABLE",
        prompt=prompt,
        project_id=project_id,
        mode="T2V",
        source_mode="T2V",
        aspect="9:16",
        model="veo_3_1_lite",
        provider_operation_ids=[],
        direct_media_targets=[],
        generation_identity={
            "sse_prompt": prompt,
            "expected_model": "veo_3_1_t2v_lite",
            "tool_call_id": "generate_video_from_text",
            "response_id": "response-history",
            "seed": None,
        },
        provider_generation_submit_count=1,
        recovery_unrecoverable=True,
        error="DURABLE_PROVIDER_IDENTITY_INSUFFICIENT",
    )
    make_video._JOBS.clear()
    make_video._VIDEO_LANE_JOB = None
    monkeypatch.setattr(make_video, "OUTPUT_DIR", tmp_path)
    direct_submit = AsyncMock(side_effect=AssertionError("recovery must not submit"))
    monkeypatch.setattr(make_video, "_direct_submit", direct_submit)

    recovered = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=provider,
    )

    assert recovered["status"] == "DONE"
    assert recovered["media_id"] == media_id
    assert recovered["provider_operation_ids"] == [media_id]
    assert recovered["provider_identity_recovery"]["correlation"] == (
        "EXACT_PROMPT_MODEL_ASPECT_PROJECT_TIME_UNIQUE"
    )
    assert provider.history_reads == 1
    assert provider.submit_count == 1
    assert provider.poll_count == 1
    assert provider.retrieve_count == 1
    direct_submit.assert_not_awaited()
    artifact = await crud.get_generated_artifact(media_id)
    assert artifact and artifact["job_id"] == job_id


@pytest.mark.asyncio
async def test_single_restart_refuses_ambiguous_project_history_identity():
    prompt = "repeated exact prompt"
    project_id = "project-history-ambiguous"
    media_a = f"history-a-{uuid4().hex}"
    media_b = f"history-b-{uuid4().hex}"
    provider = _ProjectHistoryProvider(
        media_a,
        project_id,
        [
            _history_media(media_a, project_id, prompt),
            _history_media(media_b, project_id, prompt),
        ],
    )
    provider.submit_once()
    job_id = f"g_history_ambiguous_{uuid4().hex[:10]}"
    await _seed_single_job(
        job_id,
        status="RECOVERY_UNRECOVERABLE",
        prompt=prompt,
        project_id=project_id,
        mode="T2V",
        source_mode="T2V",
        aspect="9:16",
        model="veo_3_1_lite",
        provider_operation_ids=[],
        direct_media_targets=[],
        generation_identity={
            "sse_prompt": prompt,
            "expected_model": "veo_3_1_t2v_lite",
        },
        provider_generation_submit_count=1,
    )
    make_video._JOBS.clear()
    make_video._VIDEO_LANE_JOB = None

    recovered = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=provider,
    )

    assert recovered["status"] == "RECOVERY_UNRECOVERABLE"
    assert recovered["provider_identity_recovery"]["error"] == (
        "PROJECT_HISTORY_IDENTITY_AMBIGUOUS"
    )
    assert recovered["provider_identity_recovery"]["candidate_count"] == 2
    assert provider.history_reads == 1
    assert provider.poll_count == 0
    assert provider.retrieve_count == 0
    assert provider.submit_count == 1


@pytest.mark.asyncio
async def test_project_history_lookup_pins_persisted_installation_with_two_connections(
    monkeypatch,
):
    job_id = f"g_history_lease_{uuid4().hex[:10]}"
    await _seed_single_job(
        job_id,
        status="RECOVERY_UNRECOVERABLE",
        provider_operation_ids=[],
        direct_media_targets=[],
        bridge_lease={
            "installation_id": "installation-paid-job",
            "extension_build": "build-paid-job",
            "flow_project_id": "project-restart",
        },
    )
    client = FlowClient()
    client.register_extension_connection(
        object(),
        installation_id="installation-paid-job",
        extension_session_id="session-paid-job",
        synthetic=True,
    )
    client.register_extension_connection(
        object(),
        installation_id="installation-other",
        extension_session_id="session-other",
        synthetic=True,
    )
    observed = {}

    async def lookup(_row, _state, selected_client):
        observed["installation_id"] = selected_client._select_connection()[
            "installation_id"
        ]
        return {
            "matched": False,
            "error": "PROJECT_HISTORY_IDENTITY_NOT_FOUND",
            "provider_calls": 1,
        }

    monkeypatch.setattr(
        make_video,
        "_recover_provider_media_from_project_history",
        lookup,
    )
    recovered = await make_video.reconcile_durable_single_job(
        job_id,
        provider_client=client,
    )

    assert observed["installation_id"] == "installation-paid-job"
    assert recovered["status"] == "RECOVERY_UNRECOVERABLE"
    assert all(lease.get("released") is True for lease in client._operation_leases.values())


def test_startup_single_recovery_is_scheduled_after_websocket_server():
    source = (Path(__file__).parents[2] / "agent" / "main.py").read_text(
        encoding="utf-8"
    )
    websocket_started = source.index("ws_task = asyncio.create_task(run_ws_server())")
    recovery_scheduled = source.index(
        "single_recovery_task = asyncio.create_task("
    )
    assert websocket_started < recovery_scheduled
    assert "recover_durable_single_jobs()" not in source[:websocket_started]


async def _seed_montage_run(run_id: str, items: list[tuple[str, str, dict]], *, status="GENERATING"):
    config = {
        "product_id": "montage-product",
        "staff_id": "staff_provider_free",
        "staff_display_name": "Provider-Free Fixture",
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
async def test_montage_generate_builders_forward_persisted_faceless_identity(monkeypatch):
    identity = {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "T2V",
        "source_mode": "T2V",
    }
    monkeypatch.setattr(
        crud,
        "get_workspace_execution_package",
        AsyncMock(
            return_value={
                "request_lineage_payload": json.dumps(
                    {"faceless_execution_identity": identity}
                )
            }
        ),
    )
    assert await load_montage_execution_identity("wep-identity") == identity

    from agent.api import flow

    captured = {}

    async def fake_generate(body):
        captured["body"] = body
        return {"job_id": "g-montage-identity", "media_id": None}

    monkeypatch.setattr(
        "agent.services.montage_run_service.get_montage_discrete_run",
        AsyncMock(
            return_value={
                "config": {
                    "staff_id": "staff-provider-free",
                    "approved_manifest_id": "manifest-provider-free",
                }
            }
        ),
    )
    monkeypatch.setattr(flow, "generate", fake_generate)

    result = await _default_montage_generate_fn(
        "montage-identity",
        product_id="product-identity",
        mode="T2V",
        source_mode="T2V",
        workspace_execution_package_id="wep-identity",
        prompt="identity forwarding fixture",
        scene_id="scene-identity",
        model="Veo 3.1 - Lite",
        duration_s=8,
    )

    assert result["job_id"] == "g-montage-identity"
    assert captured["body"].execution_identity == identity
    assert captured["body"].workspace_execution_package_id == "wep-identity"


@pytest.mark.asyncio
async def test_montage_authorize_api_builder_forwards_persisted_faceless_identity(monkeypatch):
    from agent.api import flow, montage
    from agent.api.montage import MontageAuthorizeGenerationRequest

    identity = {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "T2V",
        "source_mode": "T2V",
    }
    captured = {}
    monkeypatch.setattr(
        montage,
        "_require_montage_staff",
        AsyncMock(return_value={"staff_id": "staff-api", "display_name": "API Fixture"}),
    )
    monkeypatch.setattr(
        montage,
        "get_montage_discrete_run",
        AsyncMock(return_value={"product_id": "product-api", "config": {}}),
    )
    monkeypatch.setattr(montage, "_require_montage_product", AsyncMock())
    monkeypatch.setattr(
        montage,
        "load_montage_execution_identity",
        AsyncMock(return_value=identity),
    )
    monkeypatch.setattr(
        "agent.services.execution_approval_service.approved_manifest_id_for_run",
        AsyncMock(return_value="manifest-api"),
    )

    async def fake_generate(body):
        captured["body"] = body
        return {"job_id": "g-api-identity", "media_id": None}

    async def fake_authorize(_run_id, **kwargs):
        await kwargs["generate_fn"](
            product_id="product-api",
            mode="T2V",
            source_mode="T2V",
            workspace_execution_package_id="wep-api",
            prompt="api identity forwarding fixture",
            scene_id="scene-api",
            model="Veo 3.1 - Lite",
            duration_s=8,
        )
        return {"ok": True}

    monkeypatch.setattr(flow, "generate", fake_generate)
    monkeypatch.setattr(montage, "authorize_montage_run_generation", fake_authorize)
    result = await montage.montage_authorize_generation(
        "montage-api",
        MontageAuthorizeGenerationRequest(
            confirm_credit_burn=True,
            staff_id="staff-api",
            expected_video_generations=1,
            expected_provider_operations=1,
            dry_run=False,
        ),
        object(),
    )

    assert result["ok"] is True
    assert captured["body"].execution_identity == identity
    assert captured["body"].manifest_id == "manifest-api"


@pytest.mark.asyncio
async def test_montage_scheduler_repairs_only_pre_provider_identity_failure_and_submits_once():
    run_id = f"montage-identity-repair-{uuid4().hex}"
    failure = {
        "detail": (
            "409: {'error': 'FACELESS_EXECUTION_IDENTITY_REQUIRED', "
            "'detail': 'The persisted Faceless execution identity is required for dispatch.'}"
        )
    }
    await _seed_montage_run(
        run_id,
        [
            ("scene-1", "GENERATE_FAILED", failure),
            ("scene-2", "GENERATE_FAILED", failure),
        ],
        status="PARTIAL",
    )
    for item in await crud.list_bulk_generation_items(run_id):
        await crud.update_bulk_generation_item(
            item["bulk_item_id"], error="ERR_MONTAGE_GENERATE"
        )

    submits: list[str] = []

    async def generate_fn(**kwargs):
        submits.append(kwargs["scene_id"])
        return {"job_id": f"g-{kwargs['scene_id']}", "media_id": None}

    out = await montage_scheduler_tick(generate_fn=generate_fn)

    assert out["pre_provider_recoveries"] == 2
    assert out["provider_generation_submits"] == 1
    assert submits == ["scene-1"]
    items = await crud.list_bulk_generation_items(run_id)
    by_scene = {
        json.loads(item["payload_json"])["scene_id"]: item for item in items
    }
    first_payload = json.loads(by_scene["scene-1"]["payload_json"])
    second_payload = json.loads(by_scene["scene-2"]["payload_json"])
    assert by_scene["scene-1"]["status"] == "VIDEO_SUBMITTED"
    assert second_payload["status"] == "PACKAGE_READY"
    assert second_payload["pre_provider_recovery"]["provider_generation_submit_count"] == 0
    assert by_scene["scene-2"]["retry_count"] == 0
    assert first_payload["provider_generation_submit_count"] == 1


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
