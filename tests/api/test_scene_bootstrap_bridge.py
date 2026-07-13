"""Golden scene-bootstrap bridge (video-extension all-modes closure).

Root cause proven from the golden job vj_aa993dab70aa: the FIRST Extend in a project
must create its Flow scene from the source clip's workflow id. `_ensure_scene_membership`
fetched that id ONLY from `get_media`, which for a finished clip returns the encoded
video WITHOUT a workflowId -> INITIAL_SCENE_UNRESOLVED, and no bootstrap could ever run.
The workflow id IS carried by the media-shape status poll (captured live contract,
record 608: check_video_status_by_media -> media[{name,projectId,workflowId}]). These
tests pin the repair: identity is captured from the poll, types are never cross-filled,
and the fail-closed behaviour is preserved when the id genuinely cannot be obtained.
"""
import pytest

from agent.api import flow
from agent.api.flow import _ensure_scene_membership, InitialGenerationError
from agent.services import google_flow_native_extend_runtime as _nx


class _Base:
    """A finished clip: get_media returns encoded video, NO workflowId (real shape)."""
    async def get_media(self, mid):
        return {"name": mid, "video": {"encodedVideo": "AAAAIGZ0eXA="}}


def _patch_no_prior_scene(monkeypatch, set_calls):
    async def _no_ctx(client, *, media_id, project_id):
        raise _nx.NativeExtendError(_nx.EXTEND_SOURCE_NOT_RESOLVABLE, "no scene evidence")
    monkeypatch.setattr(_nx, "resolve_extend_source_context", _no_ctx)

    async def _set(op_id, scene_id):
        set_calls.append((op_id, scene_id))
    monkeypatch.setattr(flow.crud, "set_artifact_scene", _set)


async def test_workflow_id_captured_from_status_poll(monkeypatch):
    op, pid, wf, scene = "media-op-1", "proj-1", "wf-77", "scene-abc"
    seen = {}
    set_calls = []

    class C(_Base):
        async def check_video_status_by_media(self, media):
            seen["poll_body"] = media
            return {"media": [{"name": op, "projectId": pid, "workflowId": wf}]}

        async def create_scene(self, project_id, workflow_ids):
            seen["create"] = (project_id, list(workflow_ids))
            return {"scene": {"sceneId": scene},
                    "sceneWorkflows": [{"workflow": {"metadata": {"primaryMediaId": op}}}]}

    _patch_no_prior_scene(monkeypatch, set_calls)
    sid, got_wf, canonical = await _ensure_scene_membership(C(), op, pid, None)

    assert sid == scene and got_wf == wf
    # golden case: harvest id IS the scene member -> canonical == op_id
    assert canonical == op
    # queried the media-shape poll for exactly this clip
    assert seen["poll_body"] == [{"name": op, "projectId": pid}]
    # scene created from the REAL workflow id (never a media/response/tool id)
    assert seen["create"] == (pid, [wf])
    # durable scene evidence persisted for later resolves
    assert set_calls == [(op, scene)]


async def test_scene_copy_adopts_canonical_member(monkeypatch):
    """When Flow re-issues the timeline media id (createScene copies the workflow into a
    fresh entry so op_id != scene member — verified live), the scene is still the clip's
    own (created from ITS workflow id), and the scene's canonical member becomes the
    Extend parent. op_id + canonical are BOTH persisted so resolves match either."""
    op, pid, wf, scene, member = "harvest-id", "proj-c", "wf-c", "scene-c", "timeline-media-c"
    set_calls = []

    class C(_Base):
        async def check_video_status_by_media(self, media):
            return {"media": [{"name": op, "projectId": pid, "workflowId": wf}]}

        async def create_scene(self, project_id, workflow_ids):
            # Flow returns a FRESH primaryMediaId, not the harvest op_id
            return {"scene": {"sceneId": scene},
                    "sceneWorkflows": [{"workflow": {"metadata": {"primaryMediaId": member}}}]}

    _patch_no_prior_scene(monkeypatch, set_calls)
    sid, got_wf, canonical = await _ensure_scene_membership(C(), op, pid, None)
    assert sid == scene and got_wf == wf
    assert canonical == member  # the scene's verified member is the Extend parent
    # both ids mapped to the scene so resolve matches whichever the timeline uses
    assert (member, scene) in set_calls and (op, scene) in set_calls


async def test_supplied_workflow_id_skips_poll(monkeypatch):
    op, pid, wf, scene = "media-op-2", "proj-2", "wf-supplied", "scene-2"
    seen = {"polled": False}

    class C(_Base):
        async def check_video_status_by_media(self, media):
            seen["polled"] = True
            return {"media": []}

        async def create_scene(self, project_id, workflow_ids):
            return {"scene": {"sceneId": scene},
                    "sceneWorkflows": [{"workflow": {"metadata": {"primaryMediaId": op}}}]}

    _patch_no_prior_scene(monkeypatch, [])
    sid, got_wf, canonical = await _ensure_scene_membership(C(), op, pid, wf)
    assert sid == scene and got_wf == wf and canonical == op
    assert seen["polled"] is False  # a supplied workflow id is authoritative


async def test_fail_closed_when_no_workflow_id_anywhere(monkeypatch):
    op, pid = "media-op-3", "proj-3"

    class C(_Base):
        async def check_video_status_by_media(self, media):
            # status carries the media but NO workflowId -> cannot bootstrap
            return {"media": [{"name": op, "projectId": pid}]}

        async def create_scene(self, project_id, workflow_ids):  # pragma: no cover
            raise AssertionError("must not create a scene without a real workflow id")

    _patch_no_prior_scene(monkeypatch, [])
    with pytest.raises(InitialGenerationError) as exc:
        await _ensure_scene_membership(C(), op, pid, None)
    assert "INITIAL_SCENE_UNRESOLVED" in str(exc.value)


async def test_no_cross_type_fill_from_status_poll(monkeypatch):
    """The workflow id must come from the workflowId field only — never the media
    name / operation id, even when present."""
    op, pid = "media-op-4", "proj-4"

    class C(_Base):
        async def check_video_status_by_media(self, media):
            return {"media": [{"name": op, "projectId": pid}]}  # name present, workflowId absent

        async def create_scene(self, project_id, workflow_ids):  # pragma: no cover
            raise AssertionError("workflow id must not be cross-filled from the media name")

    _patch_no_prior_scene(monkeypatch, [])
    with pytest.raises(InitialGenerationError):
        await _ensure_scene_membership(C(), op, pid, None)


async def test_already_member_short_circuits(monkeypatch):
    """When the clip is already a verified scene member, return that scene and never
    create a duplicate (existing golden path must remain valid)."""
    op, pid, scene = "media-op-5", "proj-5", "scene-existing"

    async def _ctx(client, *, media_id, project_id):
        return {"project_id": project_id, "scene_id": scene, "source_operation_id": media_id}
    monkeypatch.setattr(_nx, "resolve_extend_source_context", _ctx)

    class C(_Base):
        async def create_scene(self, project_id, workflow_ids):  # pragma: no cover
            raise AssertionError("must not create a scene when one already verifies")

    sid, _wf, canonical = await _ensure_scene_membership(C(), op, pid, None)
    assert sid == scene and canonical == op
