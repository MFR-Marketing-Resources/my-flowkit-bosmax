"""Owner Phase-2B — CURRENT-UI driver contract tests (all zero credit)."""
import hashlib
import json
import zipfile
from unittest.mock import AsyncMock

import pytest

from agent.db import crud
from agent.services import google_flow_ui_driver as ui
from agent.services import video_production_orchestrator as orch


class _Client:
    def __init__(self, **over):
        self.calls = []
        self.over = over
        self._scene_list_idx = 0

    async def flowui_state(self, tab_id=None):
        return {"result": {"ok": True, "view": "PROJECT"}}

    async def flowui_verify_media_visible(self, media_ids, tab_id=None):
        self.calls.append(("verify", tuple(media_ids)))
        missing = [m for m in media_ids if m in self.over.get("invisible", ())]
        order_ok = self.over.get("order_ok", True)
        return {"result": {
            "ok": not missing and order_ok,
            "missing": missing,
            "order_ok": order_ok,
            "visible_count": len(media_ids) - len(missing),
            "expected_count": len(media_ids),
            "scope": "composer_reference_container",
            "composer_thumbnail_count": len(media_ids) - len(missing),
        }}

    async def flowui_verify_composer_zero(self, tab_id=None):
        if self.over.get("stale"):
            return {"result": {"ok": False, "error": "STALE_REFERENCES_PRESENT",
                               "composer_thumbnail_count": 1}}
        return {"result": {"ok": True, "composer_thumbnail_count": 0,
                           "scope": "composer_reference_container"}}

    async def flowui_composer_attach_file(self, file_path, **kw):
        self.calls.append(("attach", file_path))
        return {"result": {"ok": True}}

    async def flowui_set_composer_prompt(self, text, tab_id=None):
        self.calls.append(("composer_prompt", text))
        return {"result": {"ok": True, "read_back": text, "length": len(text)}}

    async def flowui_open_video(self, parent_media_operation_id, *,
                                expected_project_id=None, tab_id=None):
        self.calls.append(("open", parent_media_operation_id, expected_project_id))
        if self.over.get("wrong_video"):
            return {"result": {"ok": False, "error": "CURRENT_VIDEO_NOT_FOUND"}}
        if self.over.get("identity_mismatch"):
            return {"result": {"ok": False, "error": "CURRENT_VIDEO_IDENTITY_MISMATCH"}}
        if self.over.get("project_mismatch"):
            return {"result": {"ok": False, "error": "CURRENT_VIDEO_PROJECT_MISMATCH",
                               "expected": "p-exp", "actual": "p-wrong"}}
        return {"result": {"ok": True, "media_operation_id": parent_media_operation_id,
                           "project_id": expected_project_id or "proj-1",
                           "state": {"view": "VIDEO_DETAIL"}}}

    async def flowui_add_clip_extend(self, model_label, tab_id=None):
        self.calls.append(("extend_menu", model_label))
        return {"result": {"ok": True,
                           "menu_item": f"Extend ({model_label})",
                           "state": {"extend_prompt_visible": True}}}

    async def flowui_set_extend_prompt(self, text, tab_id=None):
        self.calls.append(("prompt", text))
        return {"result": {"ok": True, "read_back": text, "length": len(text)}}

    async def flowui_submit_extend(self, *, confirm, tab_id=None):
        self.calls.append(("submit", confirm))
        return {"result": {"ok": True, "submitted": True}}

    async def flowui_download_project(self, tab_id=None, timeout_ms=120000):
        self.calls.append(("download",))
        return {"result": self.over.get("download_result",
                                        {"ok": False, "error": "unset"})}

    async def list_scene_workflows(self, scene_id, project_id=""):
        self.calls.append(("scene_list", scene_id, project_id))
        phases = self.over.get("scene_phases")
        if phases:
            idx = min(self._scene_list_idx, len(phases) - 1)
            self._scene_list_idx += 1
            return phases[idx]
        return self.over.get("scene_listing", {"data": {"media": [], "sceneWorkflows": []}})

    async def get_media(self, mid):
        prompts = self.over.get("media_prompts", {})
        prompt = prompts.get(mid, self.over.get("default_child_prompt", ""))
        return {"data": {"video": {"prompt": prompt, "model": "veo_3_1", "seed": 1},
                         "encodedVideo": "x"}}


async def _job(nonce, segments=("video1-op",), **extra):
    job_id = f"vj_ui_{nonce}"
    await crud.create_video_production_job_full(
        job_id, logical_job_key=f"ljk_ui_{nonce}", status="INITIAL_READY",
        requested_duration_seconds=16, product_id="p1",
        segment_media_ids_json=json.dumps(list(segments)),
        project_id=extra.get("project_id", "proj-1"),
        scene_id=extra.get("scene_id", "scene-1"))
    return job_id


# ── composer reference gate ──────────────────────────────────────────────────
async def test_t2v_zero_composer_references():
    out = await ui.verify_references_visible(_Client(), [], 0)
    assert out["ok"] and out["expected_count"] == 0
    assert out.get("scope") == "composer_reference_container"


async def test_t2v_stale_composer_fails_closed():
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.verify_references_visible(_Client(stale=True), [], 0)
    assert e.value.code == ui.ERR_STALE_REFERENCES


async def test_hybrid_one_composer_reference_attach_and_verify():
    c = _Client()
    out = await ui.ensure_composer_references(
        c, media_ids=["m-prod"], local_file_paths=["/tmp/p.png"], expected_count=1)
    assert out["ok"]
    assert ("attach", "/tmp/p.png") in c.calls
    assert ("verify", ("m-prod",)) in c.calls


@pytest.mark.parametrize("ids,expected", [(["a"], 1), (["a", "b"], 2)])
async def test_f2v_frame_counts(ids, expected):
    assert (await ui.verify_references_visible(_Client(), ids, expected))["ok"]


async def test_wrong_order_fails_closed():
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.ensure_composer_references(
            _Client(order_ok=False), media_ids=["a", "b"],
            local_file_paths=[], expected_count=2)
    assert e.value.code == ui.ERR_REFERENCES_NOT_VISIBLE


async def test_ui_initial_lane_dry_run_never_api_generate():
    c = _Client()
    out = await ui.run_initial_block1_via_composer(
        c, prompt="Block 1 only", media_ids=[], local_file_paths=[],
        expected_count=0, dry_run=True)
    assert out["lane"] == "UI_COMPOSER_INITIAL"
    assert ("composer_prompt", "Block 1 only") in c.calls


# ── exact video identity (Blocker 2) ─────────────────────────────────────────
async def test_dry_run_walks_to_ready_and_never_submits():
    c = _Client()
    job_id = await _job("dry1")
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_media_operation_id="video1-op",
        block_index=2, position=1, prompt="Block 2 continuation", dry_run=True)
    assert out["ok"] and out["dry_run"] is True
    states = [s["state"] for s in out["states"]]
    assert ui.S_EXTEND_READY_TO_SUBMIT in states
    assert ("submit", True) not in c.calls
    assert out["parent_operation_id"] == "video1-op"
    assert ("open", "video1-op", "proj-1") in c.calls


async def test_exact_video_not_found():
    job_id = await _job("wrong1")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(wrong_video=True), job_id=job_id,
            parent_media_operation_id="video1-op",
            block_index=2, position=1, prompt="b2", dry_run=True)
    assert e.value.code == ui.ERR_CURRENT_VIDEO_NOT_FOUND


async def test_post_open_identity_mismatch():
    job_id = await _job("idmm")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(identity_mismatch=True), job_id=job_id,
            parent_media_operation_id="video1-op",
            block_index=2, position=1, prompt="b2", dry_run=True)
    assert e.value.code == ui.ERR_CURRENT_VIDEO_IDENTITY_MISMATCH


async def test_project_mismatch():
    job_id = await _job("pmm")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(project_mismatch=True), job_id=job_id,
            parent_media_operation_id="video1-op",
            block_index=2, position=1, prompt="b2", dry_run=True)
    assert e.value.code == ui.ERR_CURRENT_VIDEO_PROJECT_MISMATCH


# ── extend submit → poll → persist (Blocker 3) ───────────────────────────────
async def test_live_extend_polls_and_persists_child(monkeypatch):
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    prompt = "Extend child prompt exact"
    child_id = "child2-op"
    c = _Client(
        scene_phases=[
            {"data": {"media": [], "sceneWorkflows": []}},
            {"data": {"media": [{"name": child_id}], "sceneWorkflows": []}},
        ],
        media_prompts={child_id: prompt},
        default_child_prompt="wrong",
    )
    job_id = await _job("poll1")
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_media_operation_id="video1-op",
        block_index=2, position=1, prompt=prompt,
        dry_run=False, confirm_live_credit_burn=True,
        poll_timeout_s=5, poll_interval_s=1)
    assert out["ok"] and out["child_operation_id"] == child_id
    states = [s["state"] for s in out["states"]]
    assert ui.S_EXTEND_POLLING in states
    assert ui.S_CHILD_PERSISTED in states
    vj = await crud.get_video_production_job(job_id)
    segs = json.loads(vj["segment_media_ids_json"])
    assert segs == ["video1-op", child_id]


async def test_three_block_chain_uses_child2_as_block3_parent():
    c = _Client()
    job_id = await _job("chain1", segments=("video1-op", "child2-op"))
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_media_operation_id="",
        block_index=3, position=2, prompt="Block 3", dry_run=True)
    assert out["parent_operation_id"] == "child2-op"
    assert ("open", "child2-op", "proj-1") in c.calls


async def test_sequential_chain_dry_run_two_blocks():
    c = _Client()
    job_id = await _job("seq1")
    # simulate child2 already persisted after block2 live — here dry-run only
    out = await ui.run_sequential_ui_extend_chain(
        c, job_id=job_id,
        blocks=[
            {"block_index": 2, "position": 1, "prompt": "b2"},
            {"block_index": 3, "position": 2, "prompt": "b3"},
        ],
        dry_run=True)
    assert out["ok"] and len(out["blocks"]) == 2


async def test_ui_rpc_route_lock(monkeypatch):
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    from agent.services import google_flow_native_extend_runtime as nx
    job_id = await _job("lock1")
    job = await crud.get_video_production_job(job_id)
    prompt = "b2 shared-lock"
    idem = orch._stage_key(job, "EXTEND", f"video1-op|{nx._prompt_hash(prompt)}|pos1")
    await crud.reserve_video_job_side_effect(idem, job_id=job_id, stage="EXTEND")
    await crud.update_video_job_side_effect(idem, submission_state="SUBMITTED")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_media_operation_id="video1-op",
            block_index=2, position=1, prompt=prompt, dry_run=False,
            confirm_live_credit_burn=True)
    assert e.value.code == ui.ERR_ROUTE_LOCKED


# ── download final lineage ───────────────────────────────────────────────────
def _zip_bytes(tmp_path, inner="clip.mp4"):
    p = tmp_path / "download.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(inner, b"\x00" * 128)
    return p


async def test_download_requires_final_lineage(tmp_path):
    job_id = await _job("dlgate", segments=("v1",))
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.download_project_via_ui(
            _Client(), job_id=job_id, project_id="pr", require_final_lineage=True)
    assert "FINAL_LINEAGE" in e.value.code


async def test_download_zip_with_lineage(tmp_path):
    p = _zip_bytes(tmp_path)
    job_id = await _job("dlok", segments=("v1", "child-final"))
    c = _Client(download_result={"ok": True, "download": {
        "filename": str(p), "state": "complete", "mime": "application/zip"}})
    out = await ui.download_project_via_ui(
        c, job_id=job_id, project_id="proj-1", register=True)
    assert out["artifact_kind"] == "project_archive"
    assert out["registered"] is True


def test_kill_switch_default_off(monkeypatch):
    monkeypatch.delenv("FLOW_UI_DRIVER_ENABLED", raising=False)
    assert ui.ui_driver_enabled() is False
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    assert ui.ui_driver_enabled() is True