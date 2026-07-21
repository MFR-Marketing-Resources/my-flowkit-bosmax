"""SEV-0 retrieval-freshness + steer-wording regression guards.

Live incident g_09ced57d5d4b (2026-07-11 17:08Z): the shared initial-generation lane
uploaded the approved product image (fresh media id + sha256 recorded), negotiated
correctly (model veo_3_1_r2v_lite, 8s, count 1, approved), and Google Flow generated
a real reference-anchored video — but RETRIEVAL delivered OLD clip 0af072c9 (recorded
in our own DB since 10:23Z) as the run's result, because the DOM-diff freshness
snapshot under-reports in a history-laden project: it saw 2 ids pre-poll, then the
periodic tab reload surfaced older project media that were never in the snapshot.

These tests pin the durable, DOM-independent exclusion: every media id BOSMAX has
EVER recorded (artifacts / results / extend lineage) can never be accepted as a
fresh run's output — a genuinely new clip mints a brand-new Flow id.

Also pins the steer-wording law (Mission 8): a correction must never say "no images"
(the previous incident proved the agent reads that as "drop the attached reference").
"""
import base64

import pytest

from agent.db import crud
from agent.services import agent_video as av
from agent.services import make_video as mv

OLD_CLIP = "0af072c9-270a-48dc-8811-fe6f4a968e08"


# ── durable DB exclusion set ─────────────────────────────────────────────────
async def test_known_media_ids_cover_artifacts_results_and_lineage():
    await crud.insert_generated_artifact("art-media-1", job_id="g_a", mode="F2V",
                                         artifact_kind="video", local_path="x.mp4")
    await crud.insert_generation_result(OLD_CLIP, job_id="g_old", mode="F2V")
    await crud.insert_extend_lineage(
        "el_test1", parent_operation_id="parent-op-1", child_operation_id="child-op-1",
        parent_primary_media_id="parent-pm-1", child_primary_media_id="child-pm-1")
    known = await crud.list_known_media_ids()
    assert {"art-media-1", OLD_CLIP, "parent-op-1", "child-op-1",
            "parent-pm-1", "child-pm-1"} <= known
    # a brand-new Flow id can never be pre-known
    assert "freshly-minted-new-clip" not in known


async def test_known_media_ids_cover_workspace_package_only_artifacts():
    await crud.create_workspace_generation_package(
        "wgp_durable_media", mode="T2V", product_id="p", product_name_snapshot="P",
        source_lane="test", prompt_package_snapshot_id="pps", workspace_execution_package_id=None,
        generation_mode="T2V", final_prompt_text="prompt", prompt_blocks_json="[]",
        selected_assets_json="[]", resolved_engine_slots_json="{}", resolver_output_json="{}",
        image_assets_json="[]", manual_handoff_json="{}", dom_handoff_payload_json="{}",
        blockers_json="[]", warnings_json="[]", status="READY_MANUAL")
    await crud.update_workspace_generation_package(
        "wgp_durable_media",
        artifact_media_ids_json='["wgp-only-old-media", 7, null]')
    assert "wgp-only-old-media" in await crud.list_known_media_ids()


async def test_durable_exclusion_helper_fail_soft(monkeypatch):
    async def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(crud, "list_known_media_ids", boom)
    assert await mv._durable_media_exclusion() == set()


async def test_durable_exclusion_helper_passthrough():
    await crud.insert_generation_result(OLD_CLIP, job_id="g_old2", mode="F2V")
    assert OLD_CLIP in await mv._durable_media_exclusion()


# ── the incident scenario: an OLD harvestable clip must never be accepted ────
class _PromptMediaClient:
    """get_media serves finished videos whose resource carries the CAPTURED live
    contract shape (video.prompt/model/seed) — the deterministic binding authority.

    `prompts` maps media_id -> generation prompt (None = no prompt metadata);
    `seeds` maps media_id -> the media's own seed (default 7; None = seed absent)."""
    def __init__(self, prompts, seeds=None):
        self.fetched = []
        self._prompts = prompts
        self._seeds = seeds or {}

    async def get_media(self, mid):
        self.fetched.append(mid)
        video = {"encodedVideo": base64.b64encode(b"\x00" * 2048).decode(),
                 "model": "veo_3_1_r2v_lite"}
        seed = self._seeds.get(mid, 7)
        if seed is not None:
            video["seed"] = seed
        if self._prompts.get(mid) is not None:
            video["prompt"] = self._prompts[mid]
        return {"name": mid, "video": video}


def _corr(prompt="THIS RUN prompt", sse=None, model=None, seed=7):
    return {"submitted_prompt": prompt, "sse_prompt": sse, "expected_model": model,
            "tool_call_id": "tc-1", "response_id": "r-1", "seed": seed}


def _stats():
    return {"unverifiable": 0, "prompt_mismatched": 0, "model_mismatched": 0,
            "seed_mismatched": 0, "unverifiable_ids": []}


async def test_incident_old_clip_is_skipped_when_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({OLD_CLIP: "some other run"})
    # incident shape: harvest offers ONLY the old clip; it is DB-known → excluded
    # (defensive prefilter — never even fetched, let alone accepted)
    mid, path, size, ev = await mv._accept_correlated_output(
        client, [OLD_CLIP], {OLD_CLIP}, _corr(), _stats())
    assert mid is None and path is None and ev is None
    assert client.fetched == []


async def test_fresh_clip_is_accepted_next_to_old_one(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({OLD_CLIP: "old prompt",
                                 "fresh-new-clip": "THIS RUN prompt"})
    mid, path, size, ev = await mv._accept_correlated_output(
        client, [OLD_CLIP, "fresh-new-clip"], {OLD_CLIP}, _corr(), _stats())
    assert mid == "fresh-new-clip"       # the old clip is skipped, the new one lands
    assert client.fetched == ["fresh-new-clip"]
    assert ev["matched_on"] == "submitted_prompt" and ev["media_id"] == "fresh-new-clip"


# ── deterministic correlation IS the acceptance authority (PR321 closure) ────
async def test_old_and_new_unrelated_clips_are_never_accepted_without_exclusion(
        tmp_path, monkeypatch):
    """Required test 9: old AND newer unrelated videos in the project, NO
    exclusion covering them — neither may become current output, because
    neither carries THIS run's prompt."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"old-unrelated": "ancient prompt",
                                 "newer-unrelated": "yesterday prompt"})
    stats = _stats()
    mid, path, size, ev = await mv._accept_correlated_output(
        client, ["newer-unrelated", "old-unrelated"], set(), _corr(), stats)
    assert mid is None and ev is None
    assert stats["prompt_mismatched"] == 2


async def test_only_the_operation_linked_output_is_accepted(tmp_path, monkeypatch):
    """Required test 10: among mixed candidates, ONLY the clip whose own media
    resource carries this run's exact prompt is bound — order/newness never
    decide."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"decoy-newest": "other job",
                                 "ours": "THIS RUN prompt",
                                 "decoy-old": "older job"})
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["decoy-newest", "ours", "decoy-old"], set(), _corr(), _stats())
    assert mid == "ours"
    assert ev["media_model"] == "veo_3_1_r2v_lite" and ev["media_seed"] == 7


async def test_sse_tool_prompt_is_the_strongest_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"ours": "AGENT REWRITTEN prompt"})
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["ours"], set(),
        _corr(prompt="user block prompt", sse="AGENT REWRITTEN prompt"), _stats())
    assert mid == "ours" and ev["matched_on"] == "sse_tool_prompt"


async def test_confirmed_model_mismatch_rejects_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"ours": "THIS RUN prompt"})
    stats = _stats()
    mid, _, _, _ = await mv._accept_correlated_output(
        client, ["ours"], set(), _corr(model="veo_3_1_fast"), stats)
    assert mid is None and stats["model_mismatched"] == 1


async def test_missing_prompt_metadata_counts_unverifiable_never_accepts(
        tmp_path, monkeypatch):
    """Required test 11: a finished video whose resource exposes NO generation
    prompt can never be bound — counted so the job fails closed
    OUTPUT_CORRELATION_UNAVAILABLE (zero false success)."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"metadata-less": None})
    stats = _stats()
    mid, path, size, ev = await mv._accept_correlated_output(
        client, ["metadata-less"], set(), _corr(), stats)
    assert mid is None and ev is None
    assert stats["unverifiable"] == 1
    assert stats["unverifiable_ids"] == ["metadata-less"]
    assert "OUTPUT_CORRELATION_UNAVAILABLE" in mv._RETRIEVAL_PHASE_MARKERS


# ── steer wording law (Mission 8) ────────────────────────────────────────────
def _perm(cost, nv=1, ni=0):
    return {"num_videos": nv, "num_images": ni, "total_cost": cost}


def test_steer_never_says_no_images():
    for perm in (None, _perm(10, nv=0, ni=4), _perm(10, nv=2), _perm(10, ni=2)):
        kind, msg, _ = av.decide(perm, "veo_3_1_lite", 8, 1, has_reference=True)
        assert "no images" not in (msg or "")


def test_steer_preserves_attached_reference():
    _, msg, _ = av.decide(None, "veo_3_1_lite", 8, 1, has_reference=True)
    assert "using the attached reference image" in msg
    # image-only proposal: rejected AND the correction keeps the reference
    kind, msg, _ = av.decide(_perm(8, nv=0, ni=4), "veo_3_1_lite", 8, 1, has_reference=True)
    assert kind == "reject"
    assert "using the attached reference image" in msg


def test_steer_t2v_without_reference_makes_no_reference_claim():
    _, msg, _ = av.decide(None, "veo_3_1_lite", 8, 1, has_reference=False)
    assert "attached reference" not in msg
    assert "no images" not in msg


def test_decisions_unchanged_by_wording_fix():
    # the proven cap-gate decisions stay byte-identical in KIND
    assert av.decide(_perm(10), "veo_3_1_lite", 8, 1, has_reference=True)[0] == "approve"
    assert av.decide(_perm(10, nv=2), "veo_3_1_lite", 8, 1)[0] == "reject"
    assert av.decide(_perm(8, nv=0, ni=4), "veo_3_1_lite", 8, 1)[0] == "reject"
    assert av.decide(_perm(15), "veo_3_1_lite", 8, 1)[0] == "reject"  # over ceiling


# ── T2V-fallback detection (Mission 11, captured veo_3_1 contract) ───────────
def test_reference_run_t2v_fallback_detected():
    # refs attached but a plain (text-only) veo key fired → the image was dropped
    assert mv._reference_run_dropped_reference(["m1"], "veo_3_1_lite") is True
    # the captured reference key from the live incident → correct reference run
    assert mv._reference_run_dropped_reference(["m1"], "veo_3_1_r2v_lite") is False


def test_reference_run_fallback_never_guessed():
    assert mv._reference_run_dropped_reference([], "veo_3_1_lite") is None       # T2V run
    assert mv._reference_run_dropped_reference(["m1"], None) is None             # no evidence
    assert mv._reference_run_dropped_reference(["m1"], "abra_fast") is None      # uncaptured engine


# ── PR322 final closure: EXACT seed correlation (same prompt+model ambiguity) ─
async def test_same_prompt_and_model_wrong_seed_first_is_rejected(tmp_path, monkeypatch):
    """Mandatory tests 1+2: two candidates share this run's exact prompt AND
    model; the wrong-seed clip appears FIRST and must be rejected — only the
    exact prompt+model+seed candidate is bound."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient(
        {"wrong-seed-first": "THIS RUN prompt", "ours": "THIS RUN prompt"},
        seeds={"wrong-seed-first": 999, "ours": 4242})
    stats = _stats()
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["wrong-seed-first", "ours"], set(), _corr(seed=4242), stats)
    assert mid == "ours"
    assert stats["seed_mismatched"] == 1          # the same-prompt decoy was rejected
    assert ev["seed_matched"] is True
    assert ev["media_seed"] == 4242 and ev["gen_seed"] == 4242


async def test_same_prompt_missing_media_seed_is_rejected_when_gen_seed_known(
        tmp_path, monkeypatch):
    """Mandatory test 3: a same-prompt clip whose resource exposes NO seed can
    never be bound while this generation's seed is known."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"seedless": "THIS RUN prompt"},
                                seeds={"seedless": None})
    stats = _stats()
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["seedless"], set(), _corr(seed=4242), stats)
    assert mid is None and ev is None
    assert stats["seed_mismatched"] == 1


async def test_missing_sse_seed_is_evidence_only_owner_contract(
        tmp_path, monkeypatch):
    """OWNER PHASE-1 CONTRACT (supersedes the PR#323 fail-closed rule, which the
    incident manual_faf40cf6 proved produced a PAID false negative): when the
    approved SSE exposes NO usable seed, the proven composite (normalized
    provider prompt + model + project/snapshot guards) is the acceptance
    authority; the provider media seed is recorded as EVIDENCE ONLY — never
    used to manufacture a link, never a reason to reject."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _PromptMediaClient({"prompt-match": "THIS RUN prompt"})
    stats = _stats()
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["prompt-match"], set(), _corr(seed=None), stats)
    assert mid == "prompt-match"
    assert ev["seed_matched"] == "EVIDENCE_ONLY_SSE_SEED_ABSENT"
    assert ev["media_seed"] == 7          # provider seed preserved as evidence
    assert stats["unverifiable"] == 0


def test_seed_value_normalization():
    assert mv._seed_value(4242) == 4242
    assert mv._seed_value("4242") == 4242
    assert mv._seed_value(4242.0) == 4242
    assert mv._seed_value(None) is None
    assert mv._seed_value("") is None
    assert mv._seed_value(True) is None    # booleans are never seeds


# ═══ Owner Phase-1: provider XML-envelope normalization (proven lossless) ═══
import os as _os

_FIXDIR = _os.path.join(_os.path.dirname(__file__), "..", "fixtures",
                        "google_flow_media_resource")


def _fixture(name):
    with open(_os.path.join(_FIXDIR, name), encoding="utf-8") as f:
        return f.read()


def test_extract_provider_prompt_plain_text():
    path, val = mv._extract_provider_prompt("  plain prompt text ")
    assert path == "PLAIN" and val == "plain prompt text"


def test_extract_provider_prompt_absent():
    assert mv._extract_provider_prompt(None) == ("ABSENT", None)


def test_extract_provider_prompt_real_captured_envelope_is_lossless():
    """THE incident contract: the REAL captured media prompt of the paid output
    f0f865d6 normalizes to the REAL captured SSE tool prompt VERBATIM."""
    xml = _fixture("initial_r2v_prompt_envelope.sanitized.txt")
    sse = _fixture("initial_r2v_sse_prompt.sanitized.txt")
    path, val = mv._extract_provider_prompt(xml)
    assert path == "XML_INNER_PROMPT"
    assert val == sse.strip()


def test_extract_provider_prompt_entity_decoding_lossless():
    xml = ("<root><context></context><instruction>"
           "<prompt>A &amp; B &lt;fast&gt; \"quotes\"</prompt></instruction></root>")
    path, val = mv._extract_provider_prompt(xml)
    assert path == "XML_INNER_PROMPT"
    assert val == 'A & B <fast> "quotes"'


def test_extract_provider_prompt_malformed_fails_safe():
    path, val = mv._extract_provider_prompt(
        "<root><instruction><prompt>broken")
    assert path == "MALFORMED_XML" and val is None


def test_extract_provider_prompt_conflicting_nodes_ambiguous():
    xml = ("<root><instruction><prompt>one</prompt>"
           "<prompt>two</prompt></instruction></root>")
    path, val = mv._extract_provider_prompt(xml)
    assert path == "AMBIGUOUS_PROMPT_NODES" and val is None


def test_extract_provider_prompt_duplicate_identical_nodes_ok():
    xml = ("<root><instruction><prompt>same</prompt>"
           "<prompt>same</prompt></instruction></root>")
    assert mv._extract_provider_prompt(xml) == ("XML_INNER_PROMPT", "same")


class _XmlMediaClient:
    """Media resources whose prompt is the PROVEN XML envelope (or overrides)."""
    def __init__(self, entries):
        self.fetched = []
        self._entries = entries  # mid -> {"prompt":..., "seed":..., "model":...}

    async def get_media(self, mid):
        self.fetched.append(mid)
        e = self._entries[mid]
        video = {"encodedVideo": base64.b64encode(b"\x00" * 2048).decode(),
                 "model": e.get("model", "veo_3_1_r2v_lite")}
        if e.get("seed") is not None:
            video["seed"] = e["seed"]
        if e.get("prompt") is not None:
            video["prompt"] = e["prompt"]
        return {"name": mid, "video": video}


def _envelope(inner):
    return ("<root>\n  <context>\n  </context>\n  <instruction>\n"
            f"    <prompt>{inner}</prompt>\n  </instruction>\n</root>")


async def test_xml_wrapped_current_output_binds(tmp_path, monkeypatch):
    """Phase-1 core repair: the paid incident shape — XML-wrapped provider prompt
    + SSE seed absent — BINDS through the normalized composite (project guard +
    snapshot/exclusion prefilter are enforced by the caller; here the identity
    core: normalized prompt + model, seed evidence-only)."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _XmlMediaClient({"ours": {"prompt": _envelope("THIS RUN prompt"),
                                       "seed": 308957}})
    stats = _stats()
    mid, path, size, ev = await mv._accept_correlated_output(
        client, ["ours"], set(), _corr(seed=None, model="veo_3_1_r2v_lite"), stats)
    assert mid == "ours"
    assert ev["prompt_normalization"] == "XML_INNER_PROMPT"
    assert ev["seed_matched"] == "EVIDENCE_ONLY_SSE_SEED_ABSENT"
    assert ev["media_seed"] == 308957      # provider seed recorded as evidence
    assert stats["prompt_mismatched"] == 0


async def test_real_captured_incident_output_binds(tmp_path, monkeypatch):
    """End-to-end with the REAL captured artifacts: the exact media prompt and
    exact SSE prompt from manual_faf40cf6 — the output rejected 31 times must
    now bind."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    xml = _fixture("initial_r2v_prompt_envelope.sanitized.txt")
    sse = _fixture("initial_r2v_sse_prompt.sanitized.txt").strip()
    client = _XmlMediaClient({
        "f0f865d6": {"prompt": xml, "seed": 308957, "model": "veo_3_1_r2v_lite"}})
    corr = {"submitted_prompt": "original submitted block", "sse_prompt": sse,
            "expected_model": "veo_3_1_r2v_lite", "tool_call_id": "t", "response_id": "r",
            "seed": None}
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["f0f865d6"], set(), corr, _stats())
    assert mid == "f0f865d6"
    assert ev["matched_on"] == "sse_tool_prompt"


async def test_xml_old_clip_with_different_inner_prompt_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _XmlMediaClient({"old": {"prompt": _envelope("some OTHER run"), "seed": 7}})
    stats = _stats()
    mid, _, _, _ = await mv._accept_correlated_output(
        client, ["old"], set(), _corr(seed=None), stats)
    assert mid is None and stats["prompt_mismatched"] == 1


async def test_raw_xml_markup_is_never_compared(tmp_path, monkeypatch):
    """The regression that caused the incident: an anchor that happens to EQUAL
    the raw XML markup must NOT match (only the normalized inner value counts)."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    raw = _envelope("inner value")
    client = _XmlMediaClient({"m": {"prompt": raw, "seed": 7}})
    stats = _stats()
    mid, _, _, _ = await mv._accept_correlated_output(
        client, ["m"], set(), _corr(prompt=raw, seed=7), stats)
    assert mid is None and stats["prompt_mismatched"] == 1


async def test_malformed_xml_counts_unverifiable_with_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _XmlMediaClient({"bad": {"prompt": "<root><instruction><prompt>x", "seed": 7}})
    stats = _stats()
    mid, _, _, ev = await mv._accept_correlated_output(
        client, ["bad"], set(), _corr(), stats)
    assert mid is None and ev is None
    assert stats["unverifiable"] == 1
    assert stats["normalization_failures"] == {"bad": "MALFORMED_XML"}


async def test_ambiguous_prompt_nodes_count_unverifiable(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    xml = "<root><instruction><prompt>a</prompt><prompt>b</prompt></instruction></root>"
    client = _XmlMediaClient({"amb": {"prompt": xml, "seed": 7}})
    stats = _stats()
    mid, _, _, _ = await mv._accept_correlated_output(
        client, ["amb"], set(), _corr(), stats)
    assert mid is None
    assert stats["normalization_failures"] == {"amb": "AMBIGUOUS_PROMPT_NODES"}


async def test_seed_still_required_when_both_sides_expose_it(tmp_path, monkeypatch):
    """PR#323 protection retained: SSE seed present + media seed different → reject."""
    monkeypatch.setattr(mv, "OUTPUT_DIR", tmp_path)
    client = _XmlMediaClient({"m": {"prompt": _envelope("THIS RUN prompt"), "seed": 999}})
    stats = _stats()
    mid, _, _, _ = await mv._accept_correlated_output(
        client, ["m"], set(), _corr(seed=4242), stats)
    assert mid is None and stats["seed_mismatched"] == 1


def test_fastfail_marker_registered():
    assert "CURRENT_OUTPUT_IDENTITY_MISMATCH" in mv._RETRIEVAL_PHASE_MARKERS
    assert mv._IDENTITY_MISMATCH_FASTFAIL_ROUNDS >= 2
    assert mv._IDENTITY_MISMATCH_MIN_TRIES >= 3
