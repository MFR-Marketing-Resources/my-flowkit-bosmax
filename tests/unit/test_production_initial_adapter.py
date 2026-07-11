"""Zero-credit test of the REAL initial-generation adapter (Mission 1 / 7).

Exercises `agent.api.flow._production_initial_generator` end-to-end with a FAKE
transport at the Flow-client / one-door boundary (no credit spent, no live Flow).
Proves: the adapter calls the authoritative one-door lane (make_video.start_generate)
with the EXACT reviewed prompt + approved asset + engine/model/aspect; polls the lane
job; resolves durable scene evidence; maps the real result into the identity the
Extend/concat stages need; and fails closed when any identity is missing.
"""
import pytest

from agent.api import flow
from agent.services import make_video as mv
from agent.services import google_flow_native_extend_runtime as nx


class _FakeClient:
    connected = True

    async def get_credits(self):
        return {"remainingCredits": 1234.0}


def _job():
    return {
        "job_id": "vj_test", "product_id": "6483d624",
        "approved_asset_id": "product-image:6483d624:subject",
        "approved_asset_sha256": "hashA", "initial_asset_media_id": "media-start-1",
        "initial_mode": "I2V", "model": "veo_3_1_extension_lite",
        "aspect_ratio": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "requested_duration_seconds": 16,
        "initial_prompt_text": "block-1 product-truth prompt: MWTCB held in palm, "
                               "label facing camera, UGC iPhone raw",
        "project_id": None,
    }


def _wire(monkeypatch, *, lane_status="DONE", lane_extra=None, scene="scene-9",
          scene_raises=False):
    captured = {}

    async def fake_start_generate(**kwargs):
        captured.update(kwargs)
        return {"job_id": "g_abc123", "status": "SUBMITTED", "mode": kwargs.get("mode")}

    def fake_get_job(job_id):
        job = {"job_id": job_id, "status": lane_status, "project_id": "proj-77",
               "video_media_id": "clip-op-1"}
        job.update(lane_extra or {})
        return job

    async def fake_scene(client, *, media_id, project_id):
        if scene_raises:
            raise nx.NativeExtendError("SCENE_EVIDENCE_MISSING")
        return {"scene_id": scene, "workflow_id": "wf-42"}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _FakeClient())
    monkeypatch.setattr(mv, "start_generate", fake_start_generate)
    monkeypatch.setattr(mv, "get_job", fake_get_job)
    monkeypatch.setattr(nx, "resolve_extend_source_context", fake_scene)
    return captured


async def test_adapter_calls_one_door_with_exact_authority(monkeypatch):
    captured = _wire(monkeypatch)
    out = await flow._production_initial_generator(_job())
    # the ONE door was called with the exact reviewed authority
    assert captured["mode"] == "I2V"
    assert captured["prompt"] == _job()["initial_prompt_text"]
    assert captured["image_media_ids"] == ["media-start-1"]
    assert captured["aspect"] == "9:16"                  # PORTRAIT → 9:16
    assert captured["model"] == "veo_3_1_extension_lite"
    assert captured["num_videos"] == 1
    # identities mapped from the real lane result
    assert out["operation_id"] == "clip-op-1"
    assert out["media_id"] == "clip-op-1"
    assert out["project_id"] == "proj-77"
    assert out["scene_id"] == "scene-9"


async def test_adapter_fails_closed_on_lane_failure(monkeypatch):
    _wire(monkeypatch, lane_status="FAILED", lane_extra={"error": "RENDER_FAILED"})
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(_job())


async def test_adapter_fails_closed_without_scene(monkeypatch):
    _wire(monkeypatch, scene_raises=True)
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(_job())


async def test_adapter_fails_closed_without_operation_id(monkeypatch):
    _wire(monkeypatch, lane_extra={"video_media_id": None, "media_id": None})
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(_job())


async def test_adapter_requires_bound_prompt(monkeypatch):
    _wire(monkeypatch)
    job = _job()
    job["initial_prompt_text"] = ""
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(job)


async def test_adapter_rejects_when_extension_disconnected(monkeypatch):
    _wire(monkeypatch)

    class _Disconnected:
        connected = False

    monkeypatch.setattr(flow, "get_flow_client", lambda: _Disconnected())
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(_job())


# ── deterministic scene attach when the clip is not yet a scene member (item 5) ─
class _AttachClient:
    connected = True

    async def get_credits(self):
        return {"remainingCredits": 1234.0}

    async def get_media(self, mid):
        return {"media": [{"name": mid, "workflowId": "wf-clip-1"}]}

    async def create_scene(self, project_id, workflow_ids):
        # captured contract: scene + sceneWorkflows carrying the clip's primaryMediaId
        return {"scene": {"sceneId": "scene-created-1"},
                "sceneWorkflows": [{"workflow": {"metadata": {
                    "primaryMediaId": "clip-op-1"}}, "sceneId": "scene-created-1"}]}


async def test_adapter_attaches_scene_deterministically_when_not_member(monkeypatch):
    _wire(monkeypatch, scene_raises=True)  # not yet a member → must attach + verify
    monkeypatch.setattr(flow, "get_flow_client", lambda: _AttachClient())
    out = await flow._production_initial_generator(_job())
    assert out["scene_id"] == "scene-created-1"   # created from the clip's workflow
    assert out["operation_id"] == "clip-op-1"


async def test_adapter_fails_closed_when_attach_unverified(monkeypatch):
    _wire(monkeypatch, scene_raises=True)

    class _BadAttach(_AttachClient):
        async def create_scene(self, project_id, workflow_ids):
            # scene created but does NOT list our clip → membership unverified
            return {"scene": {"sceneId": "scene-x"},
                    "sceneWorkflows": [{"workflow": {"metadata": {
                        "primaryMediaId": "some-other-clip"}}}]}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _BadAttach())
    with pytest.raises(flow.InitialGenerationError):
        await flow._production_initial_generator(_job())


# ── poll-only resume states (item 1) ─────────────────────────────────────────
async def test_resume_reports_recovery_when_lane_lost(monkeypatch):
    monkeypatch.setattr(flow, "get_flow_client", lambda: _FakeClient())
    monkeypatch.setattr(mv, "get_job", lambda jid: None)  # restart wiped the lane
    job = {**_job(), "initial_lane_job_id": "g_lost", "initial_lane_project_id": "proj-77"}
    state = await flow._resume_initial_generation(job)
    assert state["state"] == "RECOVERY"


async def test_resume_reports_inflight_then_done(monkeypatch):
    monkeypatch.setattr(flow, "get_flow_client", lambda: _AttachClient())
    monkeypatch.setattr(nx, "resolve_extend_source_context", _raise_scene)
    job = {**_job(), "initial_lane_job_id": "g_run", "initial_lane_project_id": "proj-77"}

    monkeypatch.setattr(mv, "get_job",
                        lambda jid: {"status": "GENERATING", "project_id": "proj-77"})
    assert (await flow._resume_initial_generation(job))["state"] == "INFLIGHT"

    monkeypatch.setattr(mv, "get_job", lambda jid: {
        "status": "DONE", "project_id": "proj-77", "video_media_id": "clip-op-1"})
    done = await flow._resume_initial_generation(job)
    assert done["state"] == "DONE"
    assert done["identity"]["scene_id"] == "scene-created-1"


async def _raise_scene(client, *, media_id, project_id):
    raise nx.NativeExtendError("SCENE_EVIDENCE_MISSING")
