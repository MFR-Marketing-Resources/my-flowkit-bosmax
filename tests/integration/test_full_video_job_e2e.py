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
from contextlib import contextmanager

from agent.api import flow
from agent.db import crud
from agent.services import make_video as mv
from agent.services import google_flow_native_extend_runtime as nx
from agent.services import product_release_service
from agent.services import video_production_orchestrator as orch
from agent.services.flow_client import FlowClient


def _mp4(seconds: float, pad=60_000) -> bytes:
    def box(t, p):
        return struct.pack(">I", 8 + len(p)) + t + p
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mvhd = box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">II", 0, 0)
               + struct.pack(">I", 1000) + struct.pack(">I", int(seconds * 1000)) + b"\x00" * 80)
    # media-data mdat so the concat output passes the final-render honesty gate.
    mdat = box(b"mdat", b"\x11" * int(max(1, seconds) * 20_000))
    return ftyp + box(b"moov", mvhd) + mdat


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


class _RestartingProfileClient(_ExtendConcatClient, FlowClient):
    """A1 then A2+B fixture; rooted acquisitions may select only installation A."""

    def __init__(self, nonce, final_seconds=16.0):
        _ExtendConcatClient.__init__(self, nonce, final_seconds=final_seconds)
        self.identities = [
            {
                "connection_id": "connection-a1",
                "connection_epoch": 1,
                "installation_id": "installation-a",
                "extension_session_id": "session-a1",
            }
        ]
        self.active = None
        self.acquired = []
        self.released = []
        self.provider_events = []

    @property
    def connected(self):
        return bool(self.identities)

    def restart_a_with_b(self):
        self.identities = [
            {
                "connection_id": "connection-a2",
                "connection_epoch": 2,
                "installation_id": "installation-a",
                "extension_session_id": "session-a2",
            },
            {
                "connection_id": "connection-b1",
                "connection_epoch": 1,
                "installation_id": "installation-b",
                "extension_session_id": "session-b1",
            },
        ]

    def acquire_operation_lease(self, *, installation_id=None, **_kwargs):
        matches = [
            identity for identity in self.identities
            if installation_id is None or identity["installation_id"] == installation_id
        ]
        if len(matches) != 1:
            raise ConnectionError("ERR_EXTENSION_CONNECTION_AMBIGUOUS")
        lease = {**matches[0], "lease_id": f"lease-{len(self.acquired) + 1}"}
        self.acquired.append(dict(lease))
        return lease

    @contextmanager
    def activate_operation_lease(self, lease):
        previous = self.active
        self.active = dict(lease)
        try:
            yield lease
        finally:
            self.active = previous

    def release_operation_lease(self, lease):
        self.released.append(dict(lease))
        return True

    def _record(self, method):
        assert self.active is not None
        self.provider_events.append(
            (method, self.active["installation_id"], self.active["connection_id"])
        )

    async def get_credits(self):
        self._record("get_credits")
        return {"remainingCredits": 500.0}

    async def generate_video_extend(self, **kw):
        self._record("generate_video_extend")
        return await _ExtendConcatClient.generate_video_extend(self, **kw)

    async def check_video_status_by_media(self, media):
        self._record("check_video_status_by_media")
        return await _ExtendConcatClient.check_video_status_by_media(self, media)

    async def get_media(self, mid):
        self._record("get_media")
        return await _ExtendConcatClient.get_media(self, mid)

    async def run_video_concatenation(self, input_videos):
        self._record("run_video_concatenation")
        return await _ExtendConcatClient.run_video_concatenation(self, input_videos)

    async def check_video_concatenation_status(self, envelope):
        self._record("check_video_concatenation_status")
        return await _ExtendConcatClient.check_video_concatenation_status(self, envelope)


def _released_binding(project_id, *, session="a1"):
    return {
        "project_id": project_id,
        "bridge_lease": {
            "lease_id": f"preflight-{session}",
            "connection_id": f"connection-{session}",
            "connection_epoch": 1,
            "installation_id": "installation-a",
            "extension_session_id": f"session-{session}",
            "extension_build": "build-current",
            "flow_tab_id": 101,
            "flow_url": f"https://labs.google/fx/tools/flow/project/{project_id}",
            "flow_project_id": project_id,
            "released": True,
            "released_at": 1.0,
            "receipt_state": "PREFLIGHT_RELEASED",
        },
    }


def _wire_initial(monkeypatch, nonce, captured):
    binding = _released_binding(f"proj-{nonce}")

    class _AdapterClient:
        connected = True

        async def get_credits(self):
            return {"remainingCredits": 500.0}

    async def fake_start_generate(**kw):
        captured.update(kw)
        return {"job_id": "g_e2e", "status": "SUBMITTED", "mode": kw.get("mode")}

    def fake_get_job(jid):
        return {"status": "DONE", "project_id": f"proj-{nonce}",
                "video_media_id": f"init-{nonce}",
                "editor_binding_preflight": binding,
                "required_extension_installation_id": "installation-a",
                "required_extension_build": "build-current"}

    async def fake_scene(client, *, media_id, project_id):
        return {"scene_id": f"scene-{nonce}", "workflow_id": "wf-init"}

    async def ensure_binding(*_args, **_kwargs):
        return binding

    async def allow_product(*_args, **_kwargs):
        return {"operational": True}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _AdapterClient())
    monkeypatch.setattr(mv, "ensure_editor_binding", ensure_binding)
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)
    monkeypatch.setattr(mv, "get_job", fake_get_job)
    monkeypatch.setattr(nx, "resolve_extend_source_context", fake_scene)
    monkeypatch.setattr(
        product_release_service, "require_product_operational_visibility", allow_product
    )


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
                prepare_initial=flow._prepare_initial_bridge_lineage,
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


async def test_a_restart_a2_full_lineage_never_routes_to_b(monkeypatch, tmp_path):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    nonce = "lineage-a2"
    project_id = f"proj-{nonce}"
    client = _RestartingProfileClient(nonce, final_seconds=16.0)
    preflight = _released_binding(project_id)
    captured = {}

    async def allow_product(*_args, **_kwargs):
        return {"operational": True}

    async def ensure_binding(*_args, **_kwargs):
        return preflight

    async def bind_editor(bound_client, requested_project_id=None, *, bridge_lease=None,
                          **_kwargs):
        assert bound_client is client
        assert bound_client.active is not None
        lease = {
            **dict(bridge_lease or {}),
            "extension_build": "build-current",
            "flow_tab_id": 102,
            "flow_url": (
                "https://labs.google/fx/tools/flow/project/" + requested_project_id
            ),
            "flow_project_id": requested_project_id,
        }
        return {"project_id": requested_project_id, "bridge_lease": lease}

    async def fake_start_generate(**kwargs):
        client._record("start_generate")
        captured.update(kwargs)
        assert kwargs["editor_binding"] is preflight
        return {"job_id": "g_lineage_a2", "status": "SUBMITTED"}

    def fake_get_job(_job_id):
        return {
            "job_id": "g_lineage_a2",
            "status": "DONE",
            "project_id": project_id,
            "video_media_id": f"init-{nonce}",
            "editor_binding_preflight": preflight,
            "required_extension_installation_id": "installation-a",
            "required_extension_build": "build-current",
        }

    async def fake_scene(bound_client, *, media_id, project_id: str):
        bound_client._record("scene_mapping")
        bound_client.restart_a_with_b()
        return {"scene_id": f"scene-{nonce}", "workflow_id": "wf-init"}

    monkeypatch.setattr(flow, "get_flow_client", lambda: client)
    monkeypatch.setattr(mv, "ensure_editor_binding", ensure_binding)
    monkeypatch.setattr(mv, "_bind_editor_session", bind_editor)
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)
    monkeypatch.setattr(mv, "get_job", fake_get_job)
    monkeypatch.setattr(nx, "resolve_extend_source_context", fake_scene)
    monkeypatch.setattr(
        product_release_service, "require_product_operational_visibility", allow_product
    )

    planned = await orch.plan_job(_intent(nonce), trust_client_authority=True)
    auth = await orch.authorize_job(
        planned["job_id"], confirmed_plan_fingerprint=planned["plan_fingerprint"]
    )
    status = await orch.advance_job(
        client,
        planned["job_id"],
        authorization_token=auth["authorization_token"],
        prepare_initial=flow._prepare_initial_bridge_lineage,
        generate_initial=flow._production_initial_generator,
        resume_initial=flow._resume_initial_generation,
        out_dir=tmp_path,
        poll_interval_s=0,
    )

    assert status["complete"] is True
    assert captured["project_id"] == project_id
    assert [lease["connection_id"] for lease in client.acquired] == [
        "connection-a1", "connection-a2", "connection-a2"
    ]
    assert all(
        installation == "installation-a"
        for _method, installation, _connection in client.provider_events
    )
    assert all(
        connection != "connection-b1"
        for _method, _installation, connection in client.provider_events
    )
    post_restart = [
        event for event in client.provider_events
        if event[0] not in {"get_credits", "start_generate", "scene_mapping"}
    ]
    assert post_restart
    assert all(event[2] == "connection-a2" for event in post_restart)
    effects = await crud.list_video_job_side_effects(planned["job_id"])
    assert {effect["effective_submit_count"] for effect in effects} == {1}
    job = await crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] == f"init-{nonce}"
    assert job["extend_child_operation_id"] == f"child-{nonce}"


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
        prepare_initial=flow._prepare_initial_bridge_lineage,
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
        prepare_initial=flow._prepare_initial_bridge_lineage,
        generate_initial=flow._production_initial_generator,
        out_dir=tmp_path, poll_interval_s=0)
    assert status["complete"] is True

    # text-only: the one door received NO reference images
    assert captured["mode"] == "T2V"
    assert not captured["image_media_ids"]
    job = await crud.get_video_production_job(planned["job_id"])
    assert json.loads(job["segment_media_ids_json"])[0] == f"init-{nonce}"
    assert client.extend_submits == 1
