"""Output identity capture + fail-closed binding.

Live g_e71cd329b524 (one serial T2V, credits spent) ended GENERATED_BUT_UNRETRIEVED
with EVERY correlation anchor null. The report blamed the polling window, but the
run was unbindable from the moment it fired: agent_video.parse_agent_sse only captures
identity inside `elif name in _GEN_TOOLS`, and T2V's text-only generation tool is
not in that tuple. With sse_prompt=None the only remaining anchor is the RAW
submitted prompt, which can never equal the compiled prompt the provider stores —
so every candidate is rejected as prompt_mismatched, forever.

These tests pin that distinction: "could not find it" vs "could never have bound
it", and prove no artifact is registered on ambiguous output. No provider is ever
called — make_video/crud are fakes, so a regression shows up as a recorded write
rather than a real credit burn.
"""
import pytest

from agent.services import make_video as mv
from agent.services import production_queue_service as pq


# ── _identity_captured: the decisive signal ───────────────────────────────


def test_identity_absent_when_generation_tool_never_matched():
    """The exact shape live g_e71cd329b524 produced — all anchors null."""
    identity = {"sse_prompt": None, "expected_model": None,
                "tool_call_id": None, "response_id": None, "seed": None}
    assert mv._identity_captured(identity) is False


@pytest.mark.parametrize(
    "identity",
    [
        {"sse_prompt": "a compiled provider prompt"},
        {"seed": 705032},
        {"expected_model": "veo_3_1_lite"},
        {"tool_call_id": "tc_123"},
    ],
)
def test_identity_present_when_any_anchor_survives(identity):
    assert mv._identity_captured(identity) is True


@pytest.mark.parametrize("identity", [{}, None, {"response_id": "r_1"}, "not-a-dict"])
def test_identity_absent_for_empty_or_evidence_only(identity):
    # response_id alone is evidence, not an anchor: nothing can be matched on it.
    assert mv._identity_captured(identity) is False


def test_identity_not_captured_is_a_retrieval_phase_error():
    """Credits were spent, so this must classify GENERATED_BUT_UNRETRIEVED —
    never a plain generation FAILED (locked make_video contract)."""
    assert mv._is_retrieval_phase_error(
        "OUTPUT_IDENTITY_NOT_CAPTURED: the generation fired but exposed no "
        "correlation anchor") is True


# ── The SSE parser is the capture site ────────────────────────────────────


def test_parse_agent_sse_captures_identity_for_a_known_generation_tool():
    from agent.services import agent_video as av

    sse = (
        'data: {"agentMessage": {"responseId": "resp_1", "agentEvents": [{"toolInvocation": '
        '{"toolName": "generate_video", "toolCallId": "tc_9", "toolArguments": '
        '{"prompt": "compiled provider prompt", "seed": 705032, '
        '"model_usage_key": "veo_3_1_lite", "duration": 8}}}]}}'
    )
    out = av.parse_agent_sse(sse)
    assert out["gen_prompt"] == "compiled provider prompt"
    assert out["gen_seed"] == 705032
    assert out["started_tool"] is True
    assert "generate_video" in out["tools"]


def test_parse_agent_sse_captures_nothing_for_an_unknown_tool_but_records_its_name():
    """The live failure mode: a generation fires under a toolName outside
    _GEN_TOOLS, so every anchor is None. The NAME must still be recorded — that
    is what lets the gap be closed without paying for another capture."""
    from agent.services import agent_video as av

    sse = (
        'data: {"agentMessage": {"responseId": "resp_1", "agentEvents": [{"toolInvocation": '
        '{"toolName": "some_unmapped_t2v_tool", "toolCallId": "tc_9", "toolArguments": '
        '{"prompt": "compiled provider prompt", "seed": 705032}}}]}}'
    )
    out = av.parse_agent_sse(sse)
    assert out["gen_prompt"] is None
    assert out["gen_seed"] is None
    assert out["started_tool"] is False
    # The diagnostic that closes the loop.
    assert "some_unmapped_t2v_tool" in out["tools"]


# ── Durable persistence of the identity (or of its absence) ───────────────


@pytest.fixture
def wgp_writes(monkeypatch):
    writes = []

    async def update_wgp(wgp_id, **kw):
        writes.append({"wgp_id": wgp_id, **kw})
        return {}

    monkeypatch.setattr(pq.crud, "update_workspace_generation_package", update_wgp)
    return writes


def _fake_job(**over):
    job = {
        "job_id": "g_test1", "mode": "T2V", "model": "Veo 3.1 - Lite", "num_videos": 1,
        "binding": {"project_id": "proj_1", "flow_tab_id": 42},
        "generation_identity": {"sse_prompt": "compiled", "seed": 705032,
                                "expected_model": "veo_3_1_lite",
                                "tool_call_id": "tc_1", "response_id": "r_1"},
        "identity_captured": True, "gen_tool_matched": True,
        "tools_seen": ["ask_for_permission", "generate_video"],
    }
    job.update(over)
    return job


@pytest.mark.asyncio
async def test_persists_identity_snapshot_on_submission(monkeypatch, wgp_writes):
    import agent.services.make_video as _mv
    monkeypatch.setattr(_mv, "get_job", lambda jid: _fake_job())

    identity = await pq._persist_generation_identity("wgp_1", "g_test1")

    assert identity["identity_captured"] is True
    assert identity["provider_job_id"] == "g_test1"
    assert identity["project_id"] == "proj_1"
    assert identity["anchors"]["seed"] == 705032
    # It was actually written durably, not just returned.
    written = [w for w in wgp_writes if "generation_identity_json" in w]
    assert len(written) == 1
    assert "g_test1" in written[0]["generation_identity_json"]


@pytest.mark.asyncio
async def test_persists_the_ABSENCE_of_identity_rather_than_inventing_one(monkeypatch, wgp_writes):
    """The live case. The record must say 'unbindable', not go missing."""
    import agent.services.make_video as _mv
    monkeypatch.setattr(_mv, "get_job", lambda jid: _fake_job(
        generation_identity={"sse_prompt": None, "expected_model": None,
                             "tool_call_id": None, "response_id": None, "seed": None},
        identity_captured=False, gen_tool_matched=False,
        tools_seen=["ask_for_permission"],
    ))

    identity = await pq._persist_generation_identity("wgp_1", "g_e71cd329b524")

    assert identity["identity_captured"] is False
    assert identity["gen_tool_matched"] is False
    assert identity["tools_seen"] == ["ask_for_permission"]
    # No anchor is fabricated to paper over the gap.
    assert all(v is None for v in identity["anchors"].values())
    written = [w for w in wgp_writes if "generation_identity_json" in w]
    assert len(written) == 1
    assert '"identity_captured": false' in written[0]["generation_identity_json"]


@pytest.mark.asyncio
async def test_identity_snapshot_never_aborts_a_paid_submission(monkeypatch, wgp_writes):
    """Identity is evidence, not a gate. A snapshot error must not raise into a
    submission whose credits are already spent."""
    import agent.services.make_video as _mv

    def boom(jid):
        raise RuntimeError("job store exploded")

    monkeypatch.setattr(_mv, "get_job", boom)
    identity = await pq._persist_generation_identity("wgp_1", "g_test1")
    assert identity == {}  # fail-soft, no exception escapes


# ── Binding refuses foreign / dirty-timeline media ────────────────────────


class _FakeClient:
    def __init__(self, media):
        self._media = media

    async def get_media(self, mid):
        return self._media.get(mid, {})


def _media(prompt, model="veo_3_1_lite", seed=705032):
    import base64
    return {"video": {"prompt": prompt, "model": model, "seed": seed},
            "encodedVideo": base64.b64encode(b"fake-mp4-bytes").decode()}


def _stats():
    return {"unverifiable": 0, "prompt_mismatched": 0, "model_mismatched": 0,
            "seed_mismatched": 0, "unverifiable_ids": [], "normalization_failures": {},
            "round_rejected_ids": []}


@pytest.mark.asyncio
async def test_binding_accepts_the_matching_candidate_once(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_ours": _media("compiled provider prompt")})
    stats = _stats()
    mid, path, size, evidence = await mv._accept_correlated_output(
        client, ["m_ours"], set(),
        {"submitted_prompt": "raw 9-section", "sse_prompt": "compiled provider prompt",
         "expected_model": "veo_3_1_lite", "seed": 705032},
        stats,
    )
    assert mid == "m_ours"
    assert evidence["matched_on"] == "sse_tool_prompt"
    assert evidence["seed_matched"] is True


@pytest.mark.asyncio
async def test_binding_refuses_foreign_media_from_a_dirty_timeline(tmp_path, monkeypatch):
    """The bosmax f2v manual case: old media sitting in the bound project."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_old_f2v": _media("SOMEONE ELSE's old f2v prompt")})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_old_f2v"], set(),
        {"submitted_prompt": "raw 9-section", "sse_prompt": "compiled provider prompt",
         "expected_model": "veo_3_1_lite", "seed": 705032},
        stats,
    )
    assert mid is None
    assert stats["prompt_mismatched"] == 1


@pytest.mark.asyncio
async def test_binding_refuses_a_model_mismatch(tmp_path, monkeypatch):
    """T2V expects the plain key; an r2v candidate is another lane's output."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_r2v": _media("compiled provider prompt",
                                          model="veo_3_1_r2v_lite")})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_r2v"], set(),
        {"submitted_prompt": "raw", "sse_prompt": "compiled provider prompt",
         "expected_model": "veo_3_1_lite", "seed": 705032},
        stats,
    )
    assert mid is None
    assert stats["model_mismatched"] == 1


@pytest.mark.asyncio
async def test_binding_refuses_a_seed_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_x": _media("compiled provider prompt", seed=999999)})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_x"], set(),
        {"submitted_prompt": "raw", "sse_prompt": "compiled provider prompt",
         "expected_model": "veo_3_1_lite", "seed": 705032},
        stats,
    )
    assert mid is None
    assert stats["seed_mismatched"] == 1


@pytest.mark.asyncio
async def test_binding_refuses_media_without_prompt_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_bare": _media(None)})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_bare"], set(),
        {"submitted_prompt": "raw", "sse_prompt": "compiled", "seed": None},
        stats,
    )
    assert mid is None
    assert stats["unverifiable"] == 1
    assert "m_bare" in stats["unverifiable_ids"]


@pytest.mark.asyncio
async def test_excluded_preexisting_media_is_never_bound(tmp_path, monkeypatch):
    """The pre-existing snapshot / durable exclusion is the freshness authority."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_ours": _media("compiled provider prompt")})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_ours"], {"m_ours"},  # already present before this render
        {"submitted_prompt": "raw", "sse_prompt": "compiled provider prompt",
         "expected_model": "veo_3_1_lite", "seed": 705032},
        stats,
    )
    assert mid is None


@pytest.mark.asyncio
async def test_t2v_without_sse_prompt_can_never_bind_the_compiled_output(tmp_path, monkeypatch):
    """The whole live failure, pinned.

    With no sse_prompt the only anchor is the RAW submitted prompt. The provider
    stores the agent's COMPILED prompt. They can never be equal, so no candidate
    is bindable — which is why this must fail closed as an identity gap, not as a
    retrieval timeout.
    """
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _FakeClient({"m_probably_ours": _media("compiled provider prompt")})
    stats = _stats()
    mid, *_ = await mv._accept_correlated_output(
        client, ["m_probably_ours"], set(),
        {"submitted_prompt": "SECTION 1 - ROLE & OBJECTIVE ...the raw 9-section prompt",
         "sse_prompt": None, "expected_model": None, "seed": None},
        stats,
    )
    assert mid is None
    assert stats["prompt_mismatched"] == 1


# ── The binding OUTCOME is persisted, not just the submission identity ────


@pytest.mark.asyncio
async def test_persists_refusal_evidence_when_nothing_bound(monkeypatch, wgp_writes):
    """A refusal must leave the same audit trail as an acceptance.

    Before this, the rejection evidence lived only in the in-memory _JOBS dict and
    vanished on restart — which is exactly why g_e71cd329b524 could not be
    adjudicated after the fact.
    """
    import agent.services.make_video as _mv

    monkeypatch.setattr(_mv, "get_job", lambda jid: {
        "status": "GENERATED_BUT_UNRETRIEVED", "media_id": None,
        "credit_spent_likely": True,
        "error": "OUTPUT_IDENTITY_NOT_CAPTURED: the generation fired but exposed no anchor",
        "correlation_stats": {"prompt_mismatched": 2, "model_mismatched": 1,
                              "seed_mismatched": 0, "unverifiable": 1,
                              "round_rejected_ids": ["m_old_1", "m_old_2"],
                              "unverifiable_ids": ["m_bare"]},
    })

    async def get_wgp(wgp_id):
        return {"generation_identity_json": '{"provider_job_id": "g_x", "identity_captured": false}'}

    monkeypatch.setattr(pq.crud, "get_workspace_generation_package", get_wgp)

    await pq._persist_binding_outcome("wgp_1", "g_x")

    written = [w for w in wgp_writes if "generation_identity_json" in w]
    assert len(written) == 1
    import json as _json_mod
    saved = _json_mod.loads(written[0]["generation_identity_json"])
    outcome = saved["binding_outcome"]
    assert outcome["bound"] is False
    assert outcome["bound_media_id"] is None
    assert outcome["rejected_candidate_ids"] == ["m_old_1", "m_old_2"]
    assert outcome["unverifiable_ids"] == ["m_bare"]
    assert outcome["prompt_mismatched"] == 2
    assert outcome["credit_spent_likely"] is True
    assert "OUTPUT_IDENTITY_NOT_CAPTURED" in outcome["reason"]
    # The submission anchors must survive — outcome is merged, never overwriting.
    assert saved["provider_job_id"] == "g_x"


@pytest.mark.asyncio
async def test_persists_acceptance_receipt_when_bound(monkeypatch, wgp_writes):
    import agent.services.make_video as _mv
    import json as _json_mod

    monkeypatch.setattr(_mv, "get_job", lambda jid: {
        "status": "DONE", "media_id": "m_ours",
        "output_correlation": {"media_id": "m_ours", "matched_on": "sse_tool_prompt",
                               "seed_matched": True},
        "correlation_stats": {"round_rejected_ids": []},
    })

    async def get_wgp(wgp_id):
        return {"generation_identity_json": '{"provider_job_id": "g_ok"}'}

    monkeypatch.setattr(pq.crud, "get_workspace_generation_package", get_wgp)

    await pq._persist_binding_outcome("wgp_1", "g_ok")

    saved = _json_mod.loads(
        [w for w in wgp_writes if "generation_identity_json" in w][0]["generation_identity_json"])
    outcome = saved["binding_outcome"]
    assert outcome["bound"] is True
    assert outcome["bound_media_id"] == "m_ours"
    assert outcome["evidence"]["matched_on"] == "sse_tool_prompt"


@pytest.mark.asyncio
async def test_binding_outcome_snapshot_never_raises(monkeypatch, wgp_writes):
    import agent.services.make_video as _mv

    def boom(jid):
        raise RuntimeError("job store exploded")

    monkeypatch.setattr(_mv, "get_job", boom)
    await pq._persist_binding_outcome("wgp_1", "g_x")  # must not raise


# ── The uncorrelated harvest diagnostic cannot masquerade as retrieval ────


def test_harvest_video_is_tagged_uncorrelated_at_every_exit():
    """/api/flow/harvest-video takes whatever the tab shows, with NO identity
    check — it is how a dirty timeline yields foreign media that looks retrieved
    (live: it returned an r2v clip for a text-only T2V investigation). Every
    response must say so."""
    import inspect
    from agent.api import flow as flow_api

    src = inspect.getsource(flow_api.harvest_video)
    # Every return path carries the tag, so no caller can mistake it for a bind.
    assert src.count('"correlated": False') == 3
    assert src.count("_UNCORRELATED_WARNING") == 3
    assert "NO output correlation" in (flow_api.harvest_video.__doc__ or "")
    assert "must never be registered" in flow_api._UNCORRELATED_WARNING
