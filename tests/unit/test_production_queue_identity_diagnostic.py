"""Output-identity diagnostic timing — the verdict must come AFTER the poll loop.

`_persist_generation_identity` runs the instant `start_generate` returns a job id,
while `_run_generate` is still async and has not parsed the approve stream. So at
that moment anchors/tools/binding are EMPTY on every healthy run. Emitting the
final `OUTPUT_IDENTITY_NOT_CAPTURED` verdict there produced a false alarm ~1s
after submit that misdiagnosed its own cause — it blamed a missing
`agent_video._GEN_TOOLS` entry for a value that simply did not exist yet
(Stage 3B T2V `g_ba62f180717c`: tools_seen=[], project_id/flow_tab_id null,
identity_gap_sse null, logged 0.98s after fire, while
`generate_video_from_text` was ALREADY registered).

These tests pin the corrected contract:
  * early snapshot NEVER emits the final verdict, however empty it is;
  * the post-loop read emits the verdict, and only there;
  * a genuinely uncaptured identity STILL fails closed and still logs the
    observed toolNames + terminal status so it stays adjudicable.

Nothing here calls a provider, Flow, or spends credit — make_video and crud are
faked.
"""
import asyncio
import json
import logging

import pytest

from agent.services import production_queue_service as pq


def _fake_crud(monkeypatch, row=None):
    """Capture what gets written to the package row."""
    written: dict = {}

    async def _get(wgp_id):
        return dict(row or {})

    async def _update(wgp_id, **kw):
        written.update(kw)
        return {}

    monkeypatch.setattr(pq.crud, "get_workspace_generation_package", _get)
    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", _update)
    return written


def _fake_make_video(monkeypatch, job: dict):
    import agent.services.make_video as mv

    monkeypatch.setattr(mv, "get_job", lambda job_id: dict(job))
    return mv


# ── the submit-time snapshot: evidence, never a verdict ──────────────────────
def test_early_snapshot_on_an_empty_job_does_not_emit_the_verdict(monkeypatch, caplog):
    """The exact shape that produced the false alarm: a job that exists but has
    parsed nothing yet."""
    _fake_crud(monkeypatch)
    _fake_make_video(monkeypatch, {"mode": "T2V", "model": "Veo 3.1 - Lite", "num_videos": 1})

    with caplog.at_level(logging.INFO, logger=pq.logger.name):
        identity = asyncio.run(pq._persist_generation_identity("wgp_1", "g_job1"))

    assert identity["identity_captured"] is False
    assert identity["tools_seen"] == []
    text = caplog.text
    assert "OUTPUT_IDENTITY_NOT_CAPTURED" not in text, "final verdict emitted at submit time"
    assert "IDENTITY_PENDING_EARLY_SNAPSHOT" in text
    # and it must NOT blame _GEN_TOOLS for a value that does not exist yet
    assert "_GEN_TOOLS" not in text


def test_early_snapshot_still_records_evidence_durably(monkeypatch):
    """Durability is the reason the early write exists — keep it."""
    written = _fake_crud(monkeypatch)
    _fake_make_video(monkeypatch, {"mode": "T2V", "model": "Veo 3.1 - Lite"})

    asyncio.run(pq._persist_generation_identity("wgp_1", "g_job1"))

    stored = json.loads(written["generation_identity_json"])
    assert stored["provider_job_id"] == "g_job1"
    assert stored["mode"] == "T2V"
    assert stored["identity_captured"] is False
    assert "submitted_at" in stored


# ── the post-loop read: the only place the verdict belongs ───────────────────
_EARLY_ROW = {
    "generation_identity_json": json.dumps({
        "provider_job_id": "g_job1", "mode": "T2V", "anchors": {},
        "identity_captured": False, "gen_tool_matched": False,
        "tools_seen": [], "identity_gap_sse": None,
    })
}


def test_post_loop_captured_t2v_binds_and_emits_no_verdict(monkeypatch, caplog):
    """A healthy T2V run: generate_video_from_text was seen, anchors exist."""
    written = _fake_crud(monkeypatch, _EARLY_ROW)
    _fake_make_video(monkeypatch, {
        "status": "DONE", "media_id": "media_abc",
        "generation_identity": {"sse_prompt": "hello", "tool_call_id": "tc_1"},
        "identity_captured": True, "gen_tool_matched": True,
        "tools_seen": ["ask_for_permission", "generate_video_from_text"],
        "output_correlation": {"matched_on": "prompt+model"},
    })

    with caplog.at_level(logging.WARNING, logger=pq.logger.name):
        asyncio.run(pq._persist_binding_outcome("wgp_1", "g_job1"))

    stored = json.loads(written["generation_identity_json"])
    assert stored["identity_captured"] is True
    assert stored["gen_tool_matched"] is True
    assert "generate_video_from_text" in stored["tools_seen"]
    assert stored["binding_outcome"]["bound"] is True
    assert stored["binding_outcome"]["bound_media_id"] == "media_abc"
    assert "OUTPUT_IDENTITY_NOT_CAPTURED" not in caplog.text


def test_post_loop_unknown_tool_still_fails_closed(monkeypatch, caplog):
    """A REAL gap: a generation fired under a name not in _GEN_TOOLS. Must warn,
    name the tool, and never claim the output is bindable."""
    written = _fake_crud(monkeypatch, _EARLY_ROW)
    _fake_make_video(monkeypatch, {
        "status": "DONE",
        "generation_identity": {"sse_prompt": None, "tool_call_id": None},
        "identity_captured": False, "gen_tool_matched": False,
        "tools_seen": ["ask_for_permission", "totally_new_generation_tool"],
        "identity_gap_sse": "data: {...}",
    })

    with caplog.at_level(logging.WARNING, logger=pq.logger.name):
        asyncio.run(pq._persist_binding_outcome("wgp_1", "g_job1"))

    stored = json.loads(written["generation_identity_json"])
    assert stored["identity_captured"] is False
    assert "OUTPUT_IDENTITY_NOT_CAPTURED" in caplog.text
    assert "totally_new_generation_tool" in caplog.text, "observed tool must be named"
    assert "_GEN_TOOLS" in caplog.text, "actionable remedy must be stated"


def test_post_loop_empty_tools_points_at_the_stream_not_at_gen_tools(monkeypatch, caplog):
    """The Stage 3B shape. If NOTHING was seen the run never reached the approve
    stream — the message must say so instead of blaming _GEN_TOOLS alone."""
    _fake_crud(monkeypatch, _EARLY_ROW)
    _fake_make_video(monkeypatch, {
        "status": "FAILED",
        "generation_identity": {"sse_prompt": None},
        "identity_captured": False, "gen_tool_matched": False,
        "tools_seen": [],
        "error": "process died",
    })

    with caplog.at_level(logging.WARNING, logger=pq.logger.name):
        asyncio.run(pq._persist_binding_outcome("wgp_1", "g_job1"))

    text = caplog.text
    assert "OUTPUT_IDENTITY_NOT_CAPTURED" in text
    assert "never reached" in text, "empty tools must point at the stream"
    assert "FAILED" in text, "terminal job status must be reported for adjudication"


def test_post_loop_never_overwrites_submission_anchors_when_job_is_gone(monkeypatch):
    """Merge-only: a lost in-memory job must not erase the durable early record."""
    written = _fake_crud(monkeypatch, _EARLY_ROW)
    _fake_make_video(monkeypatch, {})  # job GC'd / process restarted

    asyncio.run(pq._persist_binding_outcome("wgp_1", "g_job1"))

    stored = json.loads(written["generation_identity_json"])
    assert stored["provider_job_id"] == "g_job1", "early evidence was clobbered"
    assert stored["mode"] == "T2V"
    assert "binding_outcome" in stored


def test_diagnostic_change_did_not_touch_gen_tools():
    """Guardrail: this was a diagnostic timing fix, not a generation fix."""
    from agent.services.agent_video import _GEN_TOOLS
    assert "generate_video_from_text" in _GEN_TOOLS, "already registered before this fix"


def test_certification_flag_untouched():
    assert pq.BULK_LIVE_EXECUTION_CERTIFIED is False
