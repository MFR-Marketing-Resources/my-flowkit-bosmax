"""Extend source auto-resolution — evidence-based, fail-closed.

The live host has NO scenes-listing GET (the page uses labs.google trpc, outside
the relay host guard; only the createScene POST exists) — proven by the post-#310
live 404s and the capture request inventory. Scene candidates therefore come from
OUR OWN durable records (extend lineage + artifact scene evidence) and each one is
VERIFIED against the captured GET /v1/flow/scene/{sid}/workflows listing before use.
"""
import asyncio

import pytest

from agent.services import google_flow_native_extend_runtime as nx

CLIP = "69051c7b-1a50-4560-89a8-50795e12ff5c"
PROJ = "c6c87bdd-7af2-415b-9826-315d53fc8d9b"
SCENE = "cce593f7-8450-4461-9f82-6b207cfc5857"


class _Client:
    def __init__(self, workflows_by_scene):
        self._wf = workflows_by_scene
        self.calls: list[tuple[str, str]] = []

    async def list_scene_workflows(self, scene_id, project_id=""):
        self.calls.append((scene_id, project_id))
        return self._wf.get(scene_id, {"sceneWorkflows": [], "media": []})


def _wf_listing(media_id=CLIP):
    # captured shape: {sceneWorkflows:[{workflow{name, metadata{primaryMediaId}}}], media:[{name}]}
    return {
        "sceneWorkflows": [{
            "workflow": {"name": "366baeff-wf",
                         "metadata": {"primaryMediaId": media_id}},
            "sceneId": SCENE,
        }],
        "media": [{"name": media_id, "projectId": PROJ}],
    }


def _patch_evidence(monkeypatch, lineage_scenes=(), artifact_scenes=()):
    async def _lineage(**_kw):
        return [{"scene_id": sid} for sid in lineage_scenes]

    async def _artifacts(_project_id):
        return list(artifact_scenes)

    monkeypatch.setattr(nx._crud, "list_extend_lineage", _lineage)
    monkeypatch.setattr(nx._crud, "list_artifact_scene_ids", _artifacts,
                        raising=False)


def test_resolves_via_lineage_scene_evidence(monkeypatch):
    _patch_evidence(monkeypatch, lineage_scenes=[SCENE])
    client = _Client({SCENE: _wf_listing()})
    ctx = asyncio.run(nx.resolve_extend_source_context(
        client, media_id=CLIP, project_id=PROJ))
    assert ctx["scene_id"] == SCENE
    assert ctx["source_operation_id"] == CLIP
    assert ctx["verified"] is True
    # the workflows verification call carried the live-required projectId param
    assert client.calls == [(SCENE, PROJ)]


def test_resolves_via_artifact_scene_evidence(monkeypatch):
    _patch_evidence(monkeypatch, lineage_scenes=[], artifact_scenes=[SCENE])
    client = _Client({SCENE: _wf_listing()})
    ctx = asyncio.run(nx.resolve_extend_source_context(
        client, media_id=CLIP, project_id=PROJ))
    assert ctx["scene_id"] == SCENE


def test_skips_non_matching_scene_then_matches(monkeypatch):
    other = "other-scene"
    _patch_evidence(monkeypatch, lineage_scenes=[other, SCENE])
    client = _Client({other: _wf_listing("different-clip"), SCENE: _wf_listing()})
    ctx = asyncio.run(nx.resolve_extend_source_context(
        client, media_id=CLIP, project_id=PROJ))
    assert ctx["scene_id"] == SCENE
    assert [c[0] for c in client.calls] == [other, SCENE]


def test_fails_closed_when_no_scene_evidence_exists(monkeypatch):
    _patch_evidence(monkeypatch)
    client = _Client({})
    with pytest.raises(nx.NativeExtendError) as exc:
        asyncio.run(nx.resolve_extend_source_context(
            client, media_id=CLIP, project_id=PROJ))
    assert exc.value.code == nx.EXTEND_SOURCE_NOT_RESOLVABLE
    assert "no lineage/artifact scene evidence" in str(exc.value)


def test_fails_closed_when_clip_not_in_any_known_scene(monkeypatch):
    _patch_evidence(monkeypatch, lineage_scenes=[SCENE])
    client = _Client({SCENE: _wf_listing("someone-elses-clip")})
    with pytest.raises(nx.NativeExtendError) as exc:
        asyncio.run(nx.resolve_extend_source_context(
            client, media_id=CLIP, project_id=PROJ))
    assert exc.value.code == nx.EXTEND_SOURCE_NOT_RESOLVABLE
    assert "no-match" in str(exc.value)


def test_fails_closed_on_missing_identifiers(monkeypatch):
    _patch_evidence(monkeypatch)
    for mid, pid in (("", PROJ), (CLIP, "")):
        with pytest.raises(nx.NativeExtendError):
            asyncio.run(nx.resolve_extend_source_context(
                _Client({}), media_id=mid, project_id=pid))
