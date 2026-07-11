"""Native-extend API surface: ONE authoritative path (/extend-run), explicit
live/dry-run + bounded confirmation, central resolver, no direct-submit bypass."""
import json

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
    assert out["final_concat_export_available"] is True  # captured contract (execute-gated)
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
    assert out["final_concat_export_available"] is True   # captured; execution stays confirm-gated


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
    from agent.services import google_flow_native_extend_runtime as nx

    class _Client:
        connected = True

        async def list_scene_workflows(self, scene_id, project_id=""):
            assert (scene_id, project_id) == ("scene-9", "proj-9")
            return {"sceneWorkflows": [{
                        "workflow": {"name": "wf", "metadata": {"primaryMediaId": "clip-9"}},
                        "sceneId": "scene-9"}],
                    "media": [{"name": "clip-9"}]}

    async def _lineage(**_kw):
        return [{"scene_id": "scene-9"}]

    monkeypatch.setattr(nx._crud, "list_extend_lineage", _lineage)
    monkeypatch.setattr(flow, "get_flow_client", lambda: _Client())
    out = await flow.native_extend_resolve_source(
        flow.ExtendResolveSourceRequest(media_id="clip-9", project_id="proj-9"))
    assert out == {"project_id": "proj-9", "scene_id": "scene-9",
                   "source_operation_id": "clip-9", "scene_display_name": None,
                   "verified": True}


async def test_resolve_source_fails_closed_when_clip_not_verifiable(monkeypatch):
    from agent.services import google_flow_native_extend_runtime as nx

    class _Client:
        connected = True

        async def list_scene_workflows(self, scene_id, project_id=""):
            return {"sceneWorkflows": [], "media": []}

    async def _lineage(**_kw):
        return [{"scene_id": "scene-x"}]

    monkeypatch.setattr(nx._crud, "list_extend_lineage", _lineage)
    monkeypatch.setattr(flow, "get_flow_client", lambda: _Client())
    with pytest.raises(HTTPException) as exc:
        await flow.native_extend_resolve_source(
            flow.ExtendResolveSourceRequest(media_id="ghost", project_id="proj-x"))
    assert exc.value.status_code == 404
    assert "EXTEND_SOURCE_NOT_RESOLVABLE" in str(exc.value.detail)


# ── ONE logical video job: create + finalize gates (zero credit) ────────────
async def test_video_job_create_binds_source_and_reports_missing_segments(monkeypatch):
    from agent.services import google_flow_native_extend_runtime as nx

    class _Client:
        connected = True

        async def list_scene_workflows(self, scene_id, project_id=""):
            return {"media": [{"name": "vj-parent"}], "sceneWorkflows": []}

    async def _lineage(**kw):
        return [{"scene_id": "vj-scene", "parent_operation_id": "vj-parent",
                 "child_operation_id": "vj-child",
                 "polling_state": "EXTEND_SUCCEEDED", "block_position": 1}]

    monkeypatch.setattr(nx._crud, "list_extend_lineage", _lineage)
    monkeypatch.setattr(flow.crud, "list_extend_lineage", _lineage)
    monkeypatch.setattr(flow, "get_flow_client", lambda: _Client())
    out = await flow.create_video_job(flow.VideoJobCreateRequest(
        source_media_id="vj-parent", project_id="vj-proj",
        requested_total_duration_seconds=16))
    assert out["scene_id"] == "vj-scene"
    assert out["segments"] == ["vj-parent", "vj-child"]
    assert out["status"] == "TIMELINE_SEGMENTS_READY"
    assert out["next"] == "finalize"

    job = await flow.get_video_job(out["job_id"])
    assert job["initial_media_id"] == "vj-parent"

    # finalize dry-run: exact planned submit, nothing fired, no credit
    plan = await flow.finalize_video_job(
        out["job_id"], flow.VideoJobFinalizeRequest(dry_run=True))
    assert plan["dry_run"] is True
    assert plan["planned_render_operation_count"] == 1
    assert plan["planned_request"]["inputVideos"][0]["mediaGenerationId"] == "vj-parent"

    # live without confirm -> 409 (explicit contract, never silently downgraded)
    with pytest.raises(HTTPException) as exc:
        await flow.finalize_video_job(
            out["job_id"], flow.VideoJobFinalizeRequest(dry_run=False))
    assert exc.value.status_code == 409
    assert "LIVE_CREDIT_CONFIRMATION_REQUIRED" in str(exc.value.detail)


# ── durable full-video job API (plan / authorize / status) — zero credit ────
def _complete_body(nonce, *, duration=16):
    """A COMPLETE production plan (explicit authority → no DB/compiler needed)."""
    segs = max(2, duration // 8)
    conts = [{"position": p, "block_index": p + 1, "prompt": f"cont {p} {nonce}",
              "is_final": p == segs - 1} for p in range(1, segs)]
    return flow.VideoJobPlanRequest(
        product_id="p1", product_name="MWTCB", execution_package_id="wep_x",
        approved_asset_id="product-image:p1:subject", approved_asset_sha256="hashZ",
        initial_asset_media_id=f"asset-{nonce}", initial_mode="I2V",
        engine="GOOGLE_FLOW", model="veo", aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        requested_total_duration_seconds=duration,
        initial_prompt_text=f"reviewed initial {nonce}", continuation_prompts=conts,
        client_request_nonce=nonce)


async def test_video_job_plan_creates_before_initial_and_is_reusable():
    body = _complete_body("apinonce")
    planned = await flow.plan_video_job(body)
    assert planned["job_id"].startswith("vj_")
    assert planned["status"] == "CREATED"
    assert planned["plan"]["operation_counts"]["total"] == 3
    # job persisted BEFORE any operation, with the reviewed prompts bound
    job = await flow.crud.get_video_production_job(planned["job_id"])
    assert job["initial_operation_id"] is None
    assert job["initial_prompt_text"] == "reviewed initial apinonce"
    assert json.loads(job["continuation_prompts_json"])
    # same intent reuses the one logical job
    again = await flow.plan_video_job(body)
    assert again["job_id"] == planned["job_id"] and again["reused"] is True


async def test_video_job_plan_rejects_incomplete_authority():
    body = flow.VideoJobPlanRequest(product_id="ponly",
                                    requested_total_duration_seconds=16,
                                    client_request_nonce="apiincomplete")
    with pytest.raises(HTTPException) as exc:
        await flow.plan_video_job(body)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "INCOMPLETE_PRODUCTION_PLAN"


async def test_video_job_authorize_rejects_changed_plan():
    planned = await flow.plan_video_job(_complete_body("apiauth"))
    ok = await flow.authorize_video_job(
        planned["job_id"],
        flow.VideoJobAuthorizeRequest(confirmed_plan_fingerprint=planned["plan_fingerprint"]))
    assert ok["authorization_token"].startswith("auth_")
    assert ok["authorization_id"].startswith("authid_")
    with pytest.raises(HTTPException) as exc:
        await flow.authorize_video_job(
            planned["job_id"],
            flow.VideoJobAuthorizeRequest(confirmed_plan_fingerprint="nope"))
    assert exc.value.status_code == 409


async def test_video_job_start_requires_authorization():
    planned = await flow.plan_video_job(_complete_body("apistart"))

    class _BG:
        def add_task(self, *a, **k):
            raise AssertionError("must not enqueue an unauthorized job")

    with pytest.raises(HTTPException) as exc:
        await flow.start_video_job(planned["job_id"], _BG())
    assert exc.value.status_code == 409
    assert "NOT_AUTHORIZED" in str(exc.value.detail)


async def test_video_job_start_consumes_authorization_single_use():
    planned = await flow.plan_video_job(_complete_body("apiconsume"))
    await flow.authorize_video_job(
        planned["job_id"],
        flow.VideoJobAuthorizeRequest(confirmed_plan_fingerprint=planned["plan_fingerprint"]))

    class _BG:
        def __init__(self):
            self.enqueued = 0

        def add_task(self, *a, **k):
            self.enqueued += 1

    bg1, bg2 = _BG(), _BG()
    await flow.start_video_job(planned["job_id"], bg1)   # first start wins
    await flow.start_video_job(planned["job_id"], bg2)   # replay: no new driver
    assert bg1.enqueued == 1 and bg2.enqueued == 0
    job = await flow.crud.get_video_production_job(planned["job_id"])
    assert job["authorization_consumed_at"] is not None
    assert job["authorization_consumed_by_job_id"] == planned["job_id"]


async def test_video_job_status_projection_is_human_and_refresh_safe():
    planned = await flow.plan_video_job(_complete_body("apistatus", duration=24))
    st = await flow.video_job_status(planned["job_id"])
    assert st["human_stage"] == "Preparing video"
    assert st["complete"] is False
    assert st["plan"]["operation_counts"]["extend"] == 2  # 24s -> 3 segments -> 2 extends
    with pytest.raises(HTTPException) as exc:
        await flow.video_job_status("vj_missing")
    assert exc.value.status_code == 404
