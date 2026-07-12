"""Owner Phase-2 — CURRENT-UI driver contract tests (all zero credit).

Covers: reference-first visibility gate (per-mode counts incl. T2V zero),
timeline-Extend state machine (exact parent, Block-N-only prompt, one submit,
UI/RPC route exclusivity via the SHARED per-block idempotency key), kill-switch
default-OFF, Download Project honesty (ZIP = project archive, incomplete never
success, content-addressed idempotent registration).
"""
import hashlib
import json
import zipfile

import pytest

from agent.db import crud
from agent.services import google_flow_ui_driver as ui
from agent.services import video_production_orchestrator as orch


# ── fake relay client speaking the CAPTURED verb contract ────────────────────
class _Client:
    def __init__(self, **over):
        self.calls = []
        self.over = over

    async def flowui_state(self, tab_id=None):
        return {"result": {"ok": True, "view": "PROJECT"}}

    async def flowui_verify_media_visible(self, media_ids, tab_id=None):
        self.calls.append(("verify", tuple(media_ids)))
        missing = [m for m in media_ids if m in self.over.get("invisible", ())]
        return {"result": {"ok": not missing, "missing": missing,
                           "visible_count": len(media_ids) - len(missing),
                           "expected_count": len(media_ids)}}

    async def flowui_open_video(self, title_substr, tab_id=None):
        self.calls.append(("open", title_substr))
        if self.over.get("wrong_video"):
            return {"result": {"ok": False, "error": "VIDEO_CARD_NOT_FOUND"}}
        return {"result": {"ok": True, "state": {"view": "VIDEO_DETAIL"}}}

    async def flowui_add_clip_extend(self, model_label, tab_id=None):
        self.calls.append(("extend_menu", model_label))
        return {"result": {"ok": True,
                           "menu_item": f"keyboard_double_arrow_rightExtend ({model_label})",
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


async def _job(nonce, segments=("video1-op",)):
    job_id = f"vj_ui_{nonce}"
    await crud.create_video_production_job_full(
        job_id, logical_job_key=f"ljk_ui_{nonce}", status="INITIAL_READY",
        requested_duration_seconds=16, product_id="p1",
        segment_media_ids_json=json.dumps(list(segments)))
    return job_id


# ── reference-first gate (Boundary A) ────────────────────────────────────────
async def test_t2v_zero_references_pass():
    out = await ui.verify_references_visible(_Client(), [], 0)
    assert out["ok"] and out["expected_count"] == 0


async def test_hybrid_exactly_one_visible_reference():
    c = _Client()
    out = await ui.verify_references_visible(c, ["m-prod"], 1)
    assert out["ok"] and c.calls == [("verify", ("m-prod",))]


@pytest.mark.parametrize("ids,expected", [(["a"], 1), (["a", "b"], 2)])
async def test_f2v_one_or_two_ordered_frames(ids, expected):
    assert (await ui.verify_references_visible(_Client(), ids, expected))["ok"]


@pytest.mark.parametrize("ids,expected", [(["s", "c"], 2), (["s", "c", "st"], 3)])
async def test_i2v_two_or_three_ordered_ingredients(ids, expected):
    assert (await ui.verify_references_visible(_Client(), ids, expected))["ok"]


async def test_wrong_count_fails_closed():
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.verify_references_visible(_Client(), ["a", "b"], 1)
    assert e.value.code == ui.ERR_REFERENCES_NOT_VISIBLE


async def test_invisible_reference_fails_closed():
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.verify_references_visible(
            _Client(invisible=("m-2",)), ["m-1", "m-2"], 2)
    assert e.value.code == ui.ERR_REFERENCES_NOT_VISIBLE
    assert "m-2" in e.value.detail


# ── timeline Extend state machine (Boundary D) ───────────────────────────────
async def test_dry_run_walks_to_ready_and_never_submits():
    c = _Client()
    job_id = await _job("dry1")
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_title_substr="Woman holding bottle",
        block_index=2, position=1, prompt="Block 2 continuation", dry_run=True)
    assert out["ok"] and out["dry_run"] is True
    states = [s["state"] for s in out["states"]]
    assert states == [ui.S_CURRENT_VIDEO_OPENING, ui.S_CURRENT_VIDEO_CONFIRMED,
                      ui.S_EXTEND_CONTROL_OPENING, ui.S_EXTEND_PROMPT_READY,
                      ui.S_NEXT_BLOCK_PROMPT_CONFIRMED, ui.S_EXTEND_READY_TO_SUBMIT]
    assert ("submit", True) not in c.calls          # NEVER submitted on dry-run
    assert out["parent_operation_id"] == "video1-op"  # exact current Video 1


async def test_live_requires_kill_switch(monkeypatch):
    monkeypatch.delenv("FLOW_UI_DRIVER_ENABLED", raising=False)
    job_id = await _job("kill1")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="x",
            block_index=2, position=1, prompt="b2",
            dry_run=False, confirm_live_credit_burn=True)
    assert e.value.code == ui.ERR_DISABLED


async def test_live_requires_explicit_confirm(monkeypatch):
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    job_id = await _job("conf1")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="x",
            block_index=2, position=1, prompt="b2",
            dry_run=False, confirm_live_credit_burn=False)
    assert e.value.code == ui.ERR_CONFIRM


async def test_live_submits_exactly_once_and_reserves_block(monkeypatch):
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    c = _Client()
    job_id = await _job("live1")
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_title_substr="Woman", block_index=2,
        position=1, prompt="b2 only", dry_run=False,
        confirm_live_credit_burn=True)
    assert out["ok"] and out["dry_run"] is False
    assert c.calls.count(("submit", True)) == 1
    row = await crud.get_video_job_side_effect(out["idempotency_key"])
    assert row["submission_state"] == "SUBMITTED"
    assert row["detail"] == "UI_TIMELINE_EXTEND"


async def test_ui_and_rpc_share_the_block_lock_no_double_submit(monkeypatch):
    """Route exclusivity: the RPC orchestrator and the UI driver derive the SAME
    per-block idempotency key — once either submits, the other is locked out."""
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    from agent.services import google_flow_native_extend_runtime as nx
    job_id = await _job("lock1")
    job = await crud.get_video_production_job(job_id)
    prompt = "b2 shared-lock"
    idem = orch._stage_key(job, "EXTEND", f"video1-op|{nx._prompt_hash(prompt)}|pos1")
    # the RPC route reserved + submitted this block first
    await crud.reserve_video_job_side_effect(idem, job_id=job_id, stage="EXTEND")
    await crud.update_video_job_side_effect(idem, submission_state="SUBMITTED")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="Woman",
            block_index=2, position=1, prompt=prompt, dry_run=False,
            confirm_live_credit_burn=True)
    assert e.value.code == ui.ERR_ROUTE_LOCKED


async def test_dry_run_is_also_blocked_on_an_already_submitted_block():
    from agent.services import google_flow_native_extend_runtime as nx
    job_id = await _job("lock2")
    job = await crud.get_video_production_job(job_id)
    prompt = "b2 already"
    idem = orch._stage_key(job, "EXTEND", f"video1-op|{nx._prompt_hash(prompt)}|pos1")
    await crud.reserve_video_job_side_effect(idem, job_id=job_id, stage="EXTEND")
    await crud.update_video_job_side_effect(idem, submission_state="SUBMITTED")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="Woman",
            block_index=2, position=1, prompt=prompt, dry_run=True)
    assert e.value.code == ui.ERR_ROUTE_LOCKED


async def test_multi_block_prompt_rejected():
    job_id = await _job("mb1")
    two_blocks = ("SECTION 1 - ROLE & OBJECTIVE a\n" * 2)
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="x",
            block_index=2, position=1, prompt=two_blocks, dry_run=True)
    assert e.value.code == ui.ERR_MULTI_BLOCK_PROMPT


async def test_wrong_video_fails_closed():
    job_id = await _job("wrong1")
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(wrong_video=True), job_id=job_id,
            parent_title_substr="nope", block_index=2, position=1,
            prompt="b2", dry_run=True)
    assert e.value.code == "CURRENT_VIDEO_OPEN_FAILED"


async def test_job_without_bound_video1_fails_closed():
    job_id = await _job("nosrc", segments=())
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.extend_block_via_ui(
            _Client(), job_id=job_id, parent_title_substr="x",
            block_index=2, position=1, prompt="b2", dry_run=True)
    assert e.value.code == "EXTEND_PARENT_MISSING"


async def test_block3_uses_the_immediately_preceding_child():
    c = _Client()
    job_id = await _job("chain1", segments=("video1-op", "child2-op"))
    out = await ui.extend_block_via_ui(
        c, job_id=job_id, parent_title_substr="Woman", block_index=3,
        position=2, prompt="Block 3", dry_run=True)
    assert out["parent_operation_id"] == "child2-op"  # NOT video1 independently


# ── Download Project honesty (Boundary E) ────────────────────────────────────
def _zip_bytes(tmp_path, inner="Woman_holding_bottle_speaking.mp4"):
    p = tmp_path / "download.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(inner, b"\x00" * 4096)
    return p


async def test_download_zip_registered_honestly(tmp_path):
    p = _zip_bytes(tmp_path)
    job_id = await _job("dlreg1")
    c = _Client(download_result={"ok": True, "download": {
        "filename": str(p), "state": "complete", "mime": "application/zip",
        "bytes": p.stat().st_size}})
    out = await ui.download_project_via_ui(
        c, job_id=job_id, project_id="proj-1", register=True)
    assert out["ok"] and out["is_zip"] is True
    assert out["artifact_kind"] == "project_archive"      # NEVER "video" for a ZIP
    assert out["zip_entries"] == ["Woman_holding_bottle_speaking.mp4"]
    assert out["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert out["state"] == ui.S_ARTIFACT_REGISTERED and out["registered"] is True
    vj = await crud.get_video_production_job(job_id)
    archives = json.loads(vj["stage_state_json"])["project_archives"]
    assert archives[out["artifact_id"]]["artifact_kind"] == "project_archive"
    assert archives[out["artifact_id"]]["sha256"] == out["sha256"]


async def test_incomplete_download_never_success(tmp_path):
    c = _Client(download_result={"ok": True, "download": {
        "filename": str(tmp_path / "missing.zip"), "state": "complete"}})
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.download_project_via_ui(c, job_id="g_dl2", project_id=None)
    assert e.value.code == ui.ERR_DOWNLOAD_INCOMPLETE


async def test_interrupted_download_fails(tmp_path):
    c = _Client(download_result={"ok": False, "error": "DOWNLOAD_INTERRUPTED"})
    with pytest.raises(ui.FlowUiDriverError) as e:
        await ui.download_project_via_ui(c, job_id="g_dl3", project_id=None)
    assert "DOWNLOAD" in str(e.value)


async def test_duplicate_registration_is_idempotent(tmp_path):
    p = _zip_bytes(tmp_path)
    job_id = await _job("dlreg2")
    dl = {"ok": True, "download": {"filename": str(p), "state": "complete",
                                   "mime": "application/zip"}}
    c = _Client(download_result=dl)
    a = await ui.download_project_via_ui(c, job_id=job_id, project_id="pr")
    b = await ui.download_project_via_ui(c, job_id=job_id, project_id="pr")
    assert a["artifact_id"] == b["artifact_id"]           # content-addressed
    vj = await crud.get_video_production_job(job_id)
    archives = json.loads(vj["stage_state_json"])["project_archives"]
    assert list(archives) == [a["artifact_id"]]           # never double-registered


async def test_adhoc_download_without_job_reports_unregistered_honestly(tmp_path):
    p = _zip_bytes(tmp_path)
    c = _Client(download_result={"ok": True, "download": {
        "filename": str(p), "state": "complete", "mime": "application/zip"}})
    out = await ui.download_project_via_ui(c, job_id=None, project_id="pr")
    assert out["ok"] and out["registered"] is False
    assert out["registered_reason"] == "NO_DURABLE_JOB_ROW_FOR_JOB_ID"
    assert out["state"] == ui.S_DOWNLOAD_COMPLETED        # honest: not claimed registered


# ── kill switch default ──────────────────────────────────────────────────────
def test_kill_switch_default_off(monkeypatch):
    monkeypatch.delenv("FLOW_UI_DRIVER_ENABLED", raising=False)
    assert ui.ui_driver_enabled() is False
    monkeypatch.setenv("FLOW_UI_DRIVER_ENABLED", "1")
    assert ui.ui_driver_enabled() is True
