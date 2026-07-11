"""Extend source auto-resolution — SEV-1 regression for the raw-id operator UX.

A finished clip's library media id IS its operation id (captured contract:
child op == media[0].name == workflows[0].metadata.primaryMediaId), so
resolve_extend_source_context only has to locate the clip's scene — verified
against the project's scene/workflow listings, fail-closed when absent.
Shapes mirror CAPTURE_20260711_100555 (single-scene envelope, {scenes:[...]}
list, and the workflowIds-only variant that forces the per-scene second pass).
"""
import asyncio

import pytest

from agent.services import google_flow_native_extend_runtime as nx

CLIP = "0af072c9-270a-48dc-8811-fe6f4a968e08"
PROJ = "7347fceb-a208-4fae-9b81-5994e5a8c85a"
SCENE = "cce593f7-8450-4461-9f82-6b207cfc5857"


def _scene_entry(scene_id=SCENE, media_id=CLIP, display="Scene 1"):
    return {
        "scene": {"sceneId": scene_id, "displayName": display},
        "sceneWorkflows": [{
            "workflow": {"name": "wf-1", "projectId": PROJ,
                         "metadata": {"primaryMediaId": media_id, "batchId": "b"}},
            "sceneId": scene_id,
        }],
    }


class _Client:
    def __init__(self, scenes_response, scene_workflows=None):
        self._scenes = scenes_response
        self._wf = scene_workflows or {}
        self.scene_calls: list[str] = []

    async def list_project_scenes(self, project_id):
        assert project_id == PROJ
        return self._scenes

    async def list_scene_workflows(self, scene_id, project_id=""):
        # live contract: the workflows listing requires the projectId query param
        assert project_id == PROJ
        self.scene_calls.append(scene_id)
        return self._wf.get(scene_id, {"sceneWorkflows": [], "media": []})


def test_resolves_from_single_scene_envelope():
    ctx = asyncio.run(nx.resolve_extend_source_context(
        _Client(_scene_entry()), media_id=CLIP, project_id=PROJ))
    assert ctx == {
        "project_id": PROJ, "scene_id": SCENE, "source_operation_id": CLIP,
        "scene_display_name": "Scene 1", "verified": True,
    }


def test_resolves_from_scenes_list_and_data_envelope():
    resp = {"data": {"scenes": [_scene_entry("other-scene", "other-clip"),
                                _scene_entry()]}}
    ctx = asyncio.run(nx.resolve_extend_source_context(
        _Client(resp), media_id=CLIP, project_id=PROJ))
    assert ctx["scene_id"] == SCENE
    assert ctx["source_operation_id"] == CLIP


def test_second_pass_queries_each_scene_when_listing_is_sparse():
    # Sparse listing: scene ids only, no inline workflows -> per-scene lookup.
    sparse = {"scenes": [{"scene": {"sceneId": SCENE, "displayName": "S"},
                          "sceneWorkflows": []}]}
    client = _Client(sparse, scene_workflows={
        SCENE: {"sceneWorkflows": [], "media": [{"name": CLIP, "projectId": PROJ}]},
    })
    ctx = asyncio.run(nx.resolve_extend_source_context(
        client, media_id=CLIP, project_id=PROJ))
    assert ctx["scene_id"] == SCENE
    assert client.scene_calls == [SCENE]


def test_fails_closed_when_clip_is_not_in_the_project():
    client = _Client(_scene_entry(media_id="someone-elses-clip"))
    with pytest.raises(nx.NativeExtendError) as exc:
        asyncio.run(nx.resolve_extend_source_context(
            client, media_id=CLIP, project_id=PROJ))
    assert exc.value.code == nx.EXTEND_SOURCE_NOT_RESOLVABLE


def test_fails_closed_on_missing_identifiers():
    with pytest.raises(nx.NativeExtendError):
        asyncio.run(nx.resolve_extend_source_context(
            _Client({}), media_id="", project_id=PROJ))
    with pytest.raises(nx.NativeExtendError):
        asyncio.run(nx.resolve_extend_source_context(
            _Client({}), media_id=CLIP, project_id=""))
