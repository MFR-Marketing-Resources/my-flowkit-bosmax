"""Durable full-video job — the credit-safety core.

Proves (zero-credit; the three credit-consuming side effects are injected/mocked):
job-before-initial, durable logical identity, whole-plan fingerprint authorization,
DB-atomic idempotency for INITIAL/EXTEND/CONCAT, refresh/restart resume without
double-submit, effective_submit_count==1 per operation, structured credit state,
completed job returns the existing asset, fail-closed 8s-vs-16s duration.

Every test uses a UNIQUE nonce so its extend-lineage idempotency key (project/scene/
position/prompt/parent) never collides with another test in the shared module DB.
"""
import asyncio
import base64
import json
import struct

import pytest

from agent.db import crud
from agent.services import video_production_orchestrator as orch


def _mp4(seconds: float, pad=60_000) -> bytes:
    def box(t, p):
        return struct.pack(">I", 8 + len(p)) + t + p
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", 0, 0)
               + struct.pack(">I", 1000) + struct.pack(">I", int(seconds * 1000)) + b"\x00" * 80)
    return ftyp + box(b"moov", mvhd) + b"\x00" * pad


def _intent(nonce, duration=16):
    return {
        "product_id": "6483d624", "product_name": "MWTCB 25ml",
        "execution_package_id": "wep_1", "approved_asset_sha256": "hashA",
        "requested_duration_seconds": duration, "engine": "GOOGLE_FLOW",
        "model": "veo_3_1_extension_lite", "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "initial_prompt_fingerprint": "fp_init", "execution_mode": "HYBRID_EXTEND",
        "client_request_nonce": nonce,
    }


class FakeClient:
    """The extend runtime and finalize runtime both call this; counts real submits."""
    def __init__(self, nonce, *, final_seconds=16.0):
        self.extend_submits = 0
        self.concat_submits = 0
        self._child = f"child-{nonce}"
        self._concat_job = f"projects/1/locations/us/jobs/cj-{nonce}"
        self._encoded = base64.b64encode(_mp4(final_seconds)).decode()

    async def generate_video_extend(self, **kw):
        self.extend_submits += 1
        cid = self._child
        return {"remainingCredits": 1, "workflows": [{"name": f"wf-{cid}",
                "metadata": {"primaryMediaId": cid, "batchId": "b"}}],
                "media": [{"name": cid, "projectId": kw["project_id"],
                           "workflowId": f"wf-{cid}", "mediaMetadata": {"mediaStatus": {
                               "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SCHEDULED"}}}]}

    async def check_video_status_by_media(self, media):
        return {"media": [{"name": media[0]["name"], "mediaStatus": {
            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}}]}

    async def get_media(self, mid):
        return {"fifeUrl": f"https://flow-content/{mid}"}

    async def run_video_concatenation(self, input_videos):
        self.concat_submits += 1
        return {"operation": {"operation": {"name": self._concat_job}}}

    async def check_video_concatenation_status(self, envelope):
        return {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "outputUri": "",
                "mediaGenerationId": "", "inputsCount": 3, "encodedVideo": self._encoded}


def _initial_gen(calls, nonce):
    async def gen(job):
        calls.append(job["job_id"])
        return {"operation_id": f"init-{nonce}", "media_id": f"media-{nonce}",
                "workflow_id": f"wf-{nonce}", "project_id": f"proj-{nonce}",
                "scene_id": f"scene-{nonce}"}
    return gen


async def _plan_authorize(monkeypatch, nonce, duration=16):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    planned = await orch.plan_job(_intent(nonce, duration))
    job = await crud.get_video_production_job(planned["job_id"])
    # Mission 1: job exists BEFORE any credit-consuming operation.
    assert job["status"] == orch.S_CREATED
    assert job["initial_operation_id"] is None
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    return planned, auth


# ── identity + plan + authorization ─────────────────────────────────────────
async def test_job_created_before_initial_generation(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "created")
    assert planned["job_id"].startswith("vj_")
    assert planned["plan"]["operation_counts"] == {
        "initial_generation": 1, "extend": 1, "final_render": 1, "total": 3}
    assert planned["plan"]["credit_estimate"]["final_render"] == "unknown"
    assert planned["plan"]["credit_estimate"]["total"] == "unknown"


async def test_same_intent_reuses_one_logical_job(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    a = await orch.plan_job(_intent("same"))
    b = await orch.plan_job(_intent("same"))
    assert a["job_id"] == b["job_id"] and b["reused"] is True


async def test_changed_plan_rejects_authorization(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "chg")
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.authorize_job(planned["job_id"], confirmed_plan_fingerprint="tampered")
    assert exc.value.code == "PLAN_FINGERPRINT_MISMATCH"


async def test_advance_requires_valid_authorization(monkeypatch, tmp_path):
    planned, _ = await _plan_authorize(monkeypatch, "wa")
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.advance_job(FakeClient("wa"), planned["job_id"],
                               authorization_token="wrong",
                               generate_initial=_initial_gen([], "wa"), out_dir=tmp_path)
    assert exc.value.code == orch.F_AUTH


# ── full happy path CREATED → COMPLETE ──────────────────────────────────────
async def test_full_lifecycle_created_to_complete(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "full")
    client = FakeClient("full", final_seconds=16.0)
    calls = []
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "full"), out_dir=tmp_path, poll_interval_s=0)
    assert status["complete"] is True
    assert status["human_stage"] == "Video ready"
    assert calls == [planned["job_id"]]           # initial generated once, by the job
    assert client.extend_submits == 1
    assert client.concat_submits == 1
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == "init-full"
    assert job["extend_child_operation_id"] == "child-full"
    assert job["final_media_id"] and job["final_duration_s"] == pytest.approx(16.0, abs=0.05)
    assert json.loads(job["segment_media_ids_json"]) == ["init-full", "child-full"]


# ── idempotency: re-advance never double-submits any side effect ────────────
async def test_reentry_never_double_submits(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "idem")
    client = FakeClient("idem")
    calls = []
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "idem"), out_dir=tmp_path, poll_interval_s=0)
    await orch.advance_job(client, planned["job_id"], **args)
    status2 = await orch.advance_job(client, planned["job_id"], **args)   # duplicate start
    assert status2["complete"] is True
    assert len(calls) == 1
    assert client.extend_submits == 1
    assert client.concat_submits == 1              # the critical guarantee
    job = await crud.get_video_production_job(planned["job_id"])
    for stage, payload in (("INITIAL", planned["logical_job_key"]),
                           ("CONCAT", "+".join(sorted(["init-idem", "child-idem"])))):
        se = await crud.get_video_job_side_effect(orch._stage_key(job, stage, payload))
        assert se["effective_submit_count"] == 1
        assert se["submission_state"] == orch.SUB_TERMINAL


async def test_concurrent_advance_single_concat(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "conc")
    client = FakeClient("conc")
    calls = []
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "conc"), out_dir=tmp_path, poll_interval_s=0)
    await asyncio.gather(
        orch.advance_job(client, planned["job_id"], **args),
        orch.advance_job(client, planned["job_id"], **args),
    )
    assert len(calls) == 1
    assert client.extend_submits == 1
    assert client.concat_submits == 1


# ── restart resume: resume_only never fresh-submits ─────────────────────────
async def test_resume_only_waits_before_fresh_submit(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "ro")
    client = FakeClient("ro")
    calls = []
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=_initial_gen(calls, "ro"), out_dir=tmp_path, resume_only=True)
    assert calls == [] and client.extend_submits == 0 and client.concat_submits == 0
    assert status["complete"] is False


async def test_restart_sweep_adds_no_new_credit(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "sweep")
    client = FakeClient("sweep")
    calls = []
    await orch.advance_job(client, planned["job_id"],
                           authorization_token=auth["authorization_token"],
                           generate_initial=_initial_gen(calls, "sweep"), out_dir=tmp_path,
                           poll_interval_s=0)
    before = (client.extend_submits, client.concat_submits)
    resumed = await orch.resume_in_flight_jobs(
        client, generate_initial=_initial_gen(calls, "sweep"), out_dir=tmp_path)
    assert isinstance(resumed, list)
    assert (client.extend_submits, client.concat_submits) == before


# ── completed job returns the existing asset ────────────────────────────────
async def test_completed_job_returns_existing_asset(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "done")
    client = FakeClient("done")
    calls = []
    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=_initial_gen(calls, "done"), out_dir=tmp_path, poll_interval_s=0)
    first = await orch.advance_job(client, planned["job_id"], **args)
    again = await orch.advance_job(client, planned["job_id"], **args)
    assert first["final_media_id"] == again["final_media_id"]
    assert client.concat_submits == 1


# ── fail-closed 8s output for a 16s request ─────────────────────────────────
async def test_eight_second_final_fails_closed(monkeypatch, tmp_path):
    planned, auth = await _plan_authorize(monkeypatch, "short", duration=16)
    client = FakeClient("short", final_seconds=8.0)
    with pytest.raises(orch.OrchestratorError) as exc:
        await orch.advance_job(
            client, planned["job_id"], authorization_token=auth["authorization_token"],
            generate_initial=_initial_gen([], "short"), out_dir=tmp_path, poll_interval_s=0)
    assert exc.value.code == orch.F_FINAL
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["status"] == orch.F_FINAL
    assert job["final_media_id"] is None
