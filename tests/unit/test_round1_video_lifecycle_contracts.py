"""Provider-free Round 1 lifecycle regressions.

These tests exercise the new boundaries directly.  They deliberately do not
construct a Flow client or call a provider.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.db import crud
from agent.services import make_video
from agent.services import video_production_orchestrator as video_jobs
from agent.services.creative_production_scheduler_service import (
    _attempt_identity_snapshot,
    _pre_provider_rejection,
    _record_pre_provider_rejection,
)
from agent.services.video_artifact_delivery_service import (
    FinalArtifactDeliveryError,
    register_final_video_artifact,
)


def test_direct_readiness_keeps_omni_flash_10s_blocked_before_provider() -> None:
    direct_plan = make_video._direct_lane_plan(
        "F2V",
        "HYBRID",
        "Omni Flash",
        10,
        "9:16",
        ref_count=1,
        num_videos=1,
        require_flag=True,
    )
    assert direct_plan["reason"] == make_video.DIRECT_10S_CONTRACT_NOT_CERTIFIED
    readiness = make_video.direct_video_readiness(
        "F2V",
        source_mode="HYBRID",
        model="Omni Flash",
        duration_s=8,
        ref_count=1,
    )

    assert readiness["provider_calls"] == 0
    assert readiness["credit_spend"] is False
    assert readiness["ten_second"] == {
        "duration_s": 10,
        "status": "NOT_CERTIFIED",
        "blocker_code": make_video.DIRECT_10S_CONTRACT_NOT_CERTIFIED,
        "provider_calls": 0,
    }


@pytest.mark.asyncio
async def test_single_job_is_idempotent_and_recoverable_from_durable_row() -> None:
    first = {
        "job_id": "g_round1_single_a",
        "status": "SUBMITTED",
        "mode": "F2V",
        "source_mode": "HYBRID",
        "prompt": "provider-free lifecycle fixture",
        "project_id": "project-a",
        "duration_s": 8,
        "aspect": "9:16",
        "model": "Veo 3.1 - Lite",
        "image_media_ids": ["reference-a"],
        "artifacts": [],
    }
    row, owner = await make_video._prepare_durable_single_job(
        first, idempotency_key="round1-request-a", strict=True
    )
    assert owner is True
    assert row and row["job_id"] == first["job_id"]

    replay = {**first, "job_id": "g_round1_single_replay"}
    existing, replay_owner = await make_video._prepare_durable_single_job(
        replay, idempotency_key="round1-request-a", strict=True
    )
    assert replay_owner is False
    assert existing and existing["job_id"] == first["job_id"]

    recovered = await make_video.get_durable_job(first["job_id"])
    assert recovered and recovered["durable"] is True
    assert recovered["status"] == "RECOVERY_UNRECOVERABLE"
    assert recovered["recovery_required"] is True
    assert recovered["recovery_unrecoverable"] is True


@pytest.mark.asyncio
async def test_single_video_lane_lease_is_durable_and_released() -> None:
    first = await crud.acquire_video_generation_lane_lease(
        "g_round1_lease_a", lane_id="ROUND1_SINGLE_LANE"
    )
    assert first["acquired"] is True
    blocked = await crud.acquire_video_generation_lane_lease(
        "g_round1_lease_b", lane_id="ROUND1_SINGLE_LANE"
    )
    assert blocked["acquired"] is False
    assert (blocked["row"] or {}).get("job_id") == "g_round1_lease_a"
    assert blocked["provider_calls"] == 0
    await crud.release_video_generation_lane_lease(
        "g_round1_lease_a", lane_id="ROUND1_SINGLE_LANE"
    )
    reclaimed = await crud.acquire_video_generation_lane_lease(
        "g_round1_lease_b", lane_id="ROUND1_SINGLE_LANE"
    )
    assert reclaimed["acquired"] is True
    await crud.release_video_generation_lane_lease(
        "g_round1_lease_b", lane_id="ROUND1_SINGLE_LANE"
    )


@pytest.mark.asyncio
async def test_artifact_registration_failure_is_retried_without_provider(monkeypatch, tmp_path: Path) -> None:
    artifact_path = tmp_path / "round1.mp4"
    artifact_path.write_bytes(b"provider-free-mp4-fixture")
    job = {
        "job_id": "g_round1_artifact",
        "request_id": "round1-artifact-request",
        "durable": True,
        "status": "DONE",
        "mode": "F2V",
        "prompt": "artifact fixture",
        "aspect": "9:16",
        "duration_s": 8,
        "artifacts": [
            {"media_id": "round1-media", "local_path": str(artifact_path), "size_mb": 0.1}
        ],
    }
    make_video._JOBS[job["job_id"]] = dict(job)
    original_insert = crud.insert_generated_artifact

    async def fail_insert(*args, **kwargs):
        raise RuntimeError("forced artifact registration failure")

    monkeypatch.setattr(crud, "insert_generated_artifact", fail_insert)
    await make_video._record_artifacts(job, "F2V", job["artifacts"])
    assert job["status"] == "ARTIFACT_PERSISTENCE_FAILED"
    assert job["recovery_required"] is True
    monkeypatch.setattr(crud, "insert_generated_artifact", original_insert)
    recovered = await make_video.retry_artifact_delivery(job["job_id"])
    assert recovered["status"] == "DONE"
    assert recovered["artifact_file_evidence"]["round1-media"]["sha256"]
    row = await crud.get_generated_artifact("round1-media")
    assert row and row["readback_verified"] == 1
    assert row["file_sha256"] == recovered["artifact_file_evidence"]["round1-media"]["sha256"]
    make_video._JOBS.pop(job["job_id"], None)


@pytest.mark.asyncio
async def test_final_delivery_wrapper_requires_bytes_and_registers_readback(tmp_path: Path) -> None:
    with pytest.raises(FinalArtifactDeliveryError, match="local artifact"):
        await register_final_video_artifact(
            {"final_media_id": "missing", "local_path": str(tmp_path / "missing.mp4")},
            job_id="vj_round1_missing",
        )

    final_path = tmp_path / "final.mp4"
    final_path.write_bytes(b"final-video-fixture")
    result = await register_final_video_artifact(
        {"final_media_id": "round1-final", "local_path": str(final_path), "duration_s": 8},
        job_id="vj_round1_final",
        request_id="round1-final-request",
    )
    assert result["provider_calls"] == 0
    assert result["readback_verified"] is True
    assert (await crud.get_generated_artifact("round1-final"))["file_sha256"] == result["sha256"]


@pytest.mark.asyncio
async def test_native_extend_delivery_failure_stays_non_complete_and_repairs_locally(
    monkeypatch, tmp_path: Path
) -> None:
    final_path = tmp_path / "extend-final.mp4"
    final_path.write_bytes(b"native-extend-final-fixture")
    await crud.create_video_production_job_full(
        "vj_round1_delivery",
        logical_job_key="round1-extend-key",
        status=video_jobs.S_FINAL_SAVING,
        requested_duration_seconds=16,
    )
    await crud.update_video_production_job_full(
        "vj_round1_delivery",
        final_media_id="round1-extend-media",
        final_local_path=str(final_path),
        final_duration_s=16,
    )

    async def fail_delivery(*args, **kwargs):
        raise RuntimeError("forced final delivery failure")

    import agent.services.video_artifact_delivery_service as delivery

    monkeypatch.setattr(delivery, "register_final_video_artifact", fail_delivery)
    failed = await video_jobs.advance_job(
        None,
        "vj_round1_delivery",
        authorization_token="unused",
        generate_initial=AsyncMock(side_effect=AssertionError("must not resubmit")),
    )
    assert failed["status"] == video_jobs.F_FINAL_ARTIFACT
    assert failed["complete"] is False

    monkeypatch.setattr(
        delivery,
        "register_final_video_artifact",
        register_final_video_artifact,
    )
    repaired = await video_jobs.advance_job(
        None,
        "vj_round1_delivery",
        authorization_token="unused",
        generate_initial=AsyncMock(side_effect=AssertionError("must not resubmit")),
    )
    assert repaired["status"] == video_jobs.S_COMPLETE
    assert repaired["complete"] is True


def test_p6_provider_identity_does_not_invent_missing_targets() -> None:
    identity = _attempt_identity_snapshot(
        {"source_mode": "HYBRID", "engine": "make_video.start_generate"},
        product_id="product-1",
        project_id=None,
        provider_targets=[],
    )
    assert identity["identity_state"] == "UNRESOLVED_PRE_PROVIDER"
    assert "project_id" in identity["unresolved_fields"]
    assert "provider_targets" in identity["unresolved_fields"]


def test_p6_known_rejection_is_machine_readable_pre_provider() -> None:
    rejection = _pre_provider_rejection(
        {
            "status": "REJECTED",
            "error": "DIRECT_10S_CONTRACT_NOT_CERTIFIED",
            "detail": "10s reference transport is not live-certified",
            "pre_provider": {"classification": "BLOCKED", "provider_calls": 0},
        }
    )
    assert rejection is not None
    assert rejection[0] == "DIRECT_10S_CONTRACT_NOT_CERTIFIED"
    assert "not live-certified" in rejection[1]


@pytest.mark.asyncio
async def test_p6_rejection_persists_zero_provider_touch(monkeypatch) -> None:
    updates = []
    item_updates = []
    releases = []
    outcomes = []

    async def update_attempt(attempt_id, **values):
        updates.append(values)
        return {"attempt_id": attempt_id, **values}

    monkeypatch.setattr(
        "agent.services.creative_production_scheduler_service.p6db.update_attempt",
        update_attempt,
    )
    monkeypatch.setattr(
        "agent.services.creative_production_scheduler_service.p6db.update_item",
        AsyncMock(side_effect=lambda item_id, **values: item_updates.append(values)),
    )
    monkeypatch.setattr(
        "agent.services.creative_production_scheduler_service.p6db.release_lease",
        AsyncMock(side_effect=lambda attempt_id, **values: releases.append(values)),
    )
    monkeypatch.setattr(
        "agent.services.creative_production_scheduler_service.p6db.record_lane_outcome",
        AsyncMock(side_effect=lambda lane_id, **values: outcomes.append(values)),
    )

    error = await _record_pre_provider_rejection(
        {"attempt_id": "a1", "item_id": "i1", "provider_identity_json": "{}"},
        {"lane_id": "lane-1", "cooldown_seconds": 0},
        blocker_code="DIRECT_10S_CONTRACT_NOT_CERTIFIED",
        detail="uncertified",
    )
    assert error.code == "REJECTED_PRE_PROVIDER"
    assert updates[0]["provider_touch_classification"] == "PRE_PROVIDER"
    assert updates[0]["failure_code"] == "DIRECT_10S_CONTRACT_NOT_CERTIFIED"
    assert updates[0]["recovery_class"] == "REJECTED_PRE_PROVIDER"
    assert item_updates[0]["status"] == "FAILED"
    assert releases and outcomes
