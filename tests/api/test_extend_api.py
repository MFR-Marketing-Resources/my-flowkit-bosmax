"""Native-extend API surface: ONE authoritative path (/extend-run), explicit
live/dry-run + bounded confirmation, central resolver, no direct-submit bypass."""
import pytest
from fastapi import HTTPException

from agent.api import flow


def _run(pid="p", *, dry_run=True, confirm=False, count=None, blocks=1, aspect="VIDEO_ASPECT_RATIO_PORTRAIT", source="op1"):
    return flow.ExtendRunRequest(
        project_id=pid, scene_id=f"s-{pid}", source_operation_id=source,
        aspect_ratio=aspect,
        blocks=[flow.ExtendBlockModel(block_index=i + 2, position=i + 1,
                                      prompt=f"b{i+2} {pid}", is_final=(i == blocks - 1))
                for i in range(blocks)],
        dry_run=dry_run, confirm_live_credit_burn=confirm,
        confirmed_extend_operation_count=count)


# ── no bypass: the direct-submit endpoint is gone (test req 1) ──────────────
def test_no_direct_extend_video_bypass_exists():
    assert not hasattr(flow, "extend_video")
    assert not hasattr(flow, "GenerateVideoExtendRequest")


# ── dry-run default ─────────────────────────────────────────────────────────
async def test_extend_run_dry_run_default_spends_nothing():
    out = await flow.extend_run(_run("p-apidry", dry_run=True))
    assert out["dry_run"] is True
    assert out["planned_operation_count"] == 1
    assert out["blocks"][0]["polling_state"] == "SOURCE_READY"


# ── explicit live gates (no silent downgrade) ───────────────────────────────
async def test_extend_run_live_without_confirm_is_409():
    with pytest.raises(HTTPException) as exc:
        await flow.extend_run(_run("p-apiconf", dry_run=False, confirm=False))
    assert exc.value.status_code == 409
    assert "LIVE_CREDIT_CONFIRMATION_REQUIRED" in str(exc.value.detail)


async def test_extend_run_live_flag_off_is_409(monkeypatch):
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    with pytest.raises(HTTPException) as exc:
        await flow.extend_run(_run("p-apiflag", dry_run=False, confirm=True, count=1))
    assert exc.value.status_code == 409
    assert "NATIVE_EXTEND_DISABLED" in str(exc.value.detail)


async def test_live_authorization_is_single_use_and_bound_to_planned_count(monkeypatch):
    monkeypatch.delenv("NATIVE_EXTEND_ENABLED", raising=False)
    body = _run("p-api-auth", dry_run=False, confirm=True, count=1)
    authorization = await flow.native_extend_live_authorization(body)

    assert authorization["planned_operation_count"] == 1
    assert authorization["authorization_token"]


async def test_live_authorization_requires_explicit_credit_confirmation():
    with pytest.raises(HTTPException) as exc:
        await flow.native_extend_live_authorization(
            _run("p-api-no-confirm", dry_run=False, confirm=False, count=1))
    assert exc.value.status_code == 409
    assert "LIVE_CREDIT_CONFIRMATION_REQUIRED" in str(exc.value.detail)


async def test_extend_run_count_mismatch_is_409(monkeypatch):
    monkeypatch.setenv("NATIVE_EXTEND_ENABLED", "1")
    with pytest.raises(HTTPException) as exc:
        await flow.extend_run(_run("p-apicnt", dry_run=False, confirm=True, count=5, blocks=2))
    assert exc.value.status_code == 409
    assert "EXTEND_CONFIRMATION_COUNT_MISMATCH" in str(exc.value.detail)


async def test_extend_run_missing_parent_is_422():
    with pytest.raises(HTTPException) as exc:
        await flow.extend_run(_run("p-apimp", source=""))
    assert exc.value.status_code == 422
    assert "EXTEND_PARENT_MEDIA_ID_MISSING" in str(exc.value.detail)


async def test_extend_run_unknown_aspect_is_422():
    with pytest.raises(HTTPException) as exc:
        await flow.extend_run(_run("p-apiasp", aspect="VIDEO_ASPECT_RATIO_SQUARE"))
    assert exc.value.status_code == 422
    assert "EXTEND_UNSUPPORTED_MODEL" in str(exc.value.detail)


# ── central resolver (defect 4) ─────────────────────────────────────────────
async def test_resolve_reports_blockers_when_context_missing():
    out = await flow.native_extend_resolve(
        flow.ExtendResolveRequest(project_id=None, scene_id=None,
                                  source_operation_id=None, planned_block_count=2))
    assert out["route_executable"] is False
    assert "EXTEND_PARENT_MEDIA_ID_MISSING" in out["blockers"]
    assert "EXTEND_PROJECT_CONTEXT_MISSING" in out["blockers"]
    assert "EXTEND_SCENE_CONTEXT_MISSING" in out["blockers"]
    assert out["final_concat_export_available"] is False
    assert out["transport_proven"] is True


async def test_resolve_executable_when_context_ready():
    out = await flow.native_extend_resolve(
        flow.ExtendResolveRequest(project_id="p", scene_id="s",
                                  source_operation_id="op1", planned_block_count=2,
                                  total_duration_seconds=24))
    assert out["route_executable"] is True
    assert out["blockers"] == []
    assert out["route_id"] == "GOOGLE_FLOW_NATIVE_EXTEND"
    assert out["block_plan"] == [8, 8, 8]
    assert out["final_concat_export_available"] is False   # stays fail-closed


async def test_native_extend_lineage_endpoint_empty():
    out = await flow.native_extend_lineage(project_id="p-none")
    assert out["count"] == 0 and out["lineage"] == []


async def test_native_extend_lineage_redacts_signed_output_url(monkeypatch):
    async def _rows(**_kwargs):
        return [{
            "extend_lineage_id": "lineage-1",
            "polling_state": "EXTEND_SUCCEEDED",
            "output_url": "https://flow-content.google/video?signature=private",
        }]

    monkeypatch.setattr(flow.crud, "list_extend_lineage", _rows)
    out = await flow.native_extend_lineage(project_id="p")
    assert "output_url" not in out["lineage"][0]


# ── SEV-1 source auto-inheritance: candidates + verified resolve-source ─────
async def test_source_candidates_lists_finished_clips_newest_first():
    from agent.db import crud
    await crud.insert_generated_artifact(
        "cand-old", job_id="j-old", mode="F2V", artifact_kind="video",
        project_id="proj-cand")
    await crud.insert_generated_artifact(
        "cand-skip-image", job_id="j-img", mode="IMG", artifact_kind="image",
        project_id="proj-cand")
    await crud.insert_generated_artifact(
        "cand-new", job_id="j-new", mode="F2V", artifact_kind="video",
        project_id="proj-cand")
    out = await flow.native_extend_source_candidates(limit=5)
    ids = [c["media_id"] for c in out["candidates"]]
    assert "cand-new" in ids and "cand-old" in ids
    assert "cand-skip-image" not in ids          # images are never Extend parents
    assert ids.index("cand-new") < ids.index("cand-old")  # newest first


async def test_resolve_source_returns_verified_context(monkeypatch):
    class _Client:
        connected = True

        async def list_project_scenes(self, project_id):
            return {"scene": {"sceneId": "scene-9", "displayName": "S9"},
                    "sceneWorkflows": [{
                        "workflow": {"name": "wf", "metadata": {"primaryMediaId": "clip-9"}},
                        "sceneId": "scene-9"}]}

        async def list_scene_workflows(self, scene_id):  # pragma: no cover — first pass hits
            return {"sceneWorkflows": [], "media": []}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _Client())
    out = await flow.native_extend_resolve_source(
        flow.ExtendResolveSourceRequest(media_id="clip-9", project_id="proj-9"))
    assert out == {"project_id": "proj-9", "scene_id": "scene-9",
                   "source_operation_id": "clip-9", "scene_display_name": "S9",
                   "verified": True}


async def test_resolve_source_fails_closed_when_clip_not_in_project(monkeypatch):
    class _Client:
        connected = True

        async def list_project_scenes(self, project_id):
            return {"scene": {"sceneId": "scene-x"}, "sceneWorkflows": []}

        async def list_scene_workflows(self, scene_id):
            return {"sceneWorkflows": [], "media": []}

    monkeypatch.setattr(flow, "get_flow_client", lambda: _Client())
    with pytest.raises(HTTPException) as exc:
        await flow.native_extend_resolve_source(
            flow.ExtendResolveSourceRequest(media_id="ghost", project_id="proj-x"))
    assert exc.value.status_code == 404
    assert "EXTEND_SOURCE_NOT_RESOLVABLE" in str(exc.value.detail)
