"""End-to-end durable full-video job with captured/fixture transport (Mission 8).

Wires the REAL initial adapter (`flow._production_initial_generator`) + the REAL
orchestrator + the REAL native-extend and final-timeline runtimes together, faking
ONLY the Flow-client / one-door boundary. Proves the whole chain
CREATED → INITIAL → EXTEND → CONCAT → COMPLETE runs, spends zero credit, and is
exactly-once under re-entry and a restart sweep — with the exact reviewed prompts
and product asset bound throughout.
"""
import base64
import json
import struct

from agent.api import flow
from agent.db import crud
from agent.services import make_video as mv
from agent.services import google_flow_native_extend_runtime as nx
from agent.services import video_production_orchestrator as orch


def _mp4(seconds: float, pad=60_000) -> bytes:
    def box(t, p):
        return struct.pack(">I", 8 + len(p)) + t + p
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", 0, 0)
               + struct.pack(">I", 1000) + struct.pack(">I", int(seconds * 1000)) + b"\x00" * 80)
    return ftyp + box(b"moov", mvhd) + b"\x00" * pad


class _ExtendConcatClient:
    """Fixture transport for the extend + concat runtimes."""
    def __init__(self, nonce, final_seconds=16.0):
        self.extend_submits = 0
        self.concat_submits = 0
        self._child = f"child-{nonce}"
        self._encoded = base64.b64encode(_mp4(final_seconds)).decode()
        self._concat_job = f"projects/1/locations/us/jobs/cj-{nonce}"

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
        # Each segment is a real ~8s block for the pre-concat duration preflight.
        return {"encodedVideo": base64.b64encode(_mp4(8.0)).decode(),
                "fifeUrl": f"https://flow-content/{mid}"}

    async def run_video_concatenation(self, input_videos):
        self.concat_submits += 1
        return {"operation": {"operation": {"name": self._concat_job}}}

    async def check_video_concatenation_status(self, envelope):
        return {"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "outputUri": "",
                "mediaGenerationId": "", "inputsCount": 3, "encodedVideo": self._encoded}


def _wire_initial(monkeypatch, nonce, captured):
    class _AdapterClient:
        connected = True

        async def get_credits(self):
            return {"remainingCredits": 500.0}

    async def fake_start_generate(**kw):
        captured.update(kw)
        return {"job_id": "g_e2e", "status": "SUBMITTED", "mode": kw.get("mode")}

    def fake_get_job(jid):
        return {"status": "DONE", "project_id": f"proj-{nonce}",
                "video_media_id": f"init-{nonce}"}

    async def fake_scene(client, *, media_id, project_id):
        return {"scene_id": f"scene-{nonce}", "workflow_id": "wf-init"}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _AdapterClient())
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)
    monkeypatch.setattr(mv, "get_job", fake_get_job)
    monkeypatch.setattr(nx, "resolve_extend_source_context", fake_scene)


def _intent(nonce):
    return {
        "product_id": "6483d624", "product_name": "MWTCB 25ml",
        "execution_package_id": "wep_1", "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "hashA", "initial_asset_media_id": f"asset-{nonce}",
        "requested_duration_seconds": 16, "engine": "GOOGLE_FLOW", "model": "veo",
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT", "initial_mode": "I2V",
        "initial_prompt_text": f"reviewed block-1 prompt {nonce}",
        "continuation_prompts": [{"position": 1, "block_index": 2,
                                  "prompt": f"reviewed continuation {nonce}", "is_final": True}],
        "execution_mode": "HYBRID_EXTEND", "client_request_nonce": nonce,
    }


async def test_full_video_job_end_to_end_zero_credit(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    nonce = "e2e"
    captured: dict = {}
    _wire_initial(monkeypatch, nonce, captured)
    client = _ExtendConcatClient(nonce, final_seconds=16.0)

    planned = await orch.plan_job(_intent(nonce), trust_client_authority=True)
    # created before any operation, reviewed prompts bound
    job0 = await crud.get_video_production_job(planned["job_id"])
    assert job0["status"] == orch.S_CREATED and job0["initial_operation_id"] is None
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])

    args = dict(authorization_token=auth["authorization_token"],
                generate_initial=flow._production_initial_generator,  # the REAL adapter
                out_dir=tmp_path, poll_interval_s=0)
    status = await orch.advance_job(client, planned["job_id"], **args)
    assert status["complete"] is True and status["human_stage"] == "Video ready"

    # the real adapter drove the ONE door with the exact reviewed authority
    assert captured["mode"] == "I2V"
    assert captured["prompt"] == f"reviewed block-1 prompt {nonce}"
    assert captured["image_media_ids"] == [f"asset-{nonce}"]
    assert captured["aspect"] == "9:16"
    assert client.extend_submits == 1 and client.concat_submits == 1

    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == f"init-{nonce}"
    assert job["extend_child_operation_id"] == f"child-{nonce}"
    assert json.loads(job["segment_media_ids_json"]) == [f"init-{nonce}", f"child-{nonce}"]
    assert job["final_duration_s"] and 14.5 <= job["final_duration_s"] <= 17.5

    # every stage effective_submit_count == 1
    effects = await crud.list_video_job_side_effects(planned["job_id"])
    assert {e["stage"] for e in effects} == {"INITIAL", "EXTEND", "CONCAT"}
    for e in effects:
        assert e["effective_submit_count"] == 1

    # re-entry (refresh) does not duplicate anything
    again = await orch.advance_job(client, planned["job_id"], **args)
    assert again["complete"] is True
    assert client.extend_submits == 1 and client.concat_submits == 1

    # restart sweep resumes without any new credit submit
    resumed = await orch.resume_in_flight_jobs(
        client, generate_initial=flow._production_initial_generator, out_dir=tmp_path)
    assert isinstance(resumed, list)
    assert client.extend_submits == 1 and client.concat_submits == 1


async def test_full_video_job_i2v_two_reference_initial(monkeypatch, tmp_path):
    """Multi-block I2V: the initial segment carries BOTH ordered ingredient refs
    through the SAME one-door service, then extends its own Video 1."""
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    nonce = "e2e-i2v2"
    captured: dict = {}
    _wire_initial(monkeypatch, nonce, captured)
    client = _ExtendConcatClient(nonce, final_seconds=16.0)

    intent = _intent(nonce)
    intent["initial_source_mode"] = "I2V"
    intent["initial_reference_media_ids"] = [f"asset-{nonce}", f"asset2-{nonce}"]
    planned = await orch.plan_job(intent, trust_client_authority=True)
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=flow._production_initial_generator,
        out_dir=tmp_path, poll_interval_s=0)
    assert status["complete"] is True

    # BOTH refs reached the one door, in the user's order — never reduced to one
    assert captured["mode"] == "I2V"
    assert captured["image_media_ids"] == [f"asset-{nonce}", f"asset2-{nonce}"]
    # Extend used THIS job's own Video 1 (structural current-run binding)
    job = await crud.get_video_production_job(planned["job_id"])
    assert json.loads(job["segment_media_ids_json"])[0] == f"init-{nonce}"
    assert client.extend_submits == 1


async def test_full_video_job_t2v_text_only_initial(monkeypatch, tmp_path):
    """Multi-block T2V: block-1 goes to the SAME service with ZERO images and no
    asset authority, then extends its own Video 1."""
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    nonce = "e2e-t2v"
    captured: dict = {}
    _wire_initial(monkeypatch, nonce, captured)
    client = _ExtendConcatClient(nonce, final_seconds=16.0)

    intent = _intent(nonce)
    intent["initial_mode"] = "T2V"
    intent["initial_source_mode"] = "T2V"
    intent["approved_asset_id"] = None
    intent["approved_asset_sha256"] = None
    intent["initial_asset_media_id"] = None
    planned = await orch.plan_job(intent, trust_client_authority=True)
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"])
    status = await orch.advance_job(
        client, planned["job_id"], authorization_token=auth["authorization_token"],
        generate_initial=flow._production_initial_generator,
        out_dir=tmp_path, poll_interval_s=0)
    assert status["complete"] is True

    # text-only: the one door received NO reference images
    assert captured["mode"] == "T2V"
    assert not captured["image_media_ids"]
    job = await crud.get_video_production_job(planned["job_id"])
    assert json.loads(job["segment_media_ids_json"])[0] == f"init-{nonce}"
    assert client.extend_submits == 1
