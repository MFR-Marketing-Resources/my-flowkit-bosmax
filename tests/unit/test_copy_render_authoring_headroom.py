"""Copy Authoring Headroom (v4) — provider-facing authoring margin under the
UNCHANGED hard SweetWPS ceiling.

LAW: SYSTEM owns the hard ceiling AND the authoring safety margin; the AI still
authors every creative word. The margin lowers ONLY what the provider is TOLD to
aim at (hard_ceiling - max(2, ceil(10%))) — it NEVER weakens validation, does NOT
rewrite/trim/pad output, and derives per canonical block for multi-block durations.

PROVIDER-FREE: the stitch call uses the injected StitchFake; the real adapter's
process-global counter must never advance.
"""

import json
import types

import pytest

from agent.db import copy_render_crud as crud
from agent.models.copy_render_v1 import RENDERER_PROMPT_VERSION
from agent.services import copy_render_service as svc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls

PAS_ORDER = ["problem", "agitate", "solution", "cta"]
HSO_ORDER = ["hook", "story", "offer"]


async def _session_8s(target: int = 5):
    """A single-block 8s BM_MS session — hard ceiling 22, authoring max 19."""
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="FACELESS", target_count=target, duration_seconds=8)
    return boot, s


def _fake_prompt(hard_ceiling: int, part_ceilings: list[int], stages_order: list[str]) -> tuple[str, str]:
    """Build the stitch prompt directly with a synthetic occupancy (no DB/provider)."""
    session = {
        "word_budget": hard_ceiling,
        "target_language": "BM_MS",
        "lineage_json": json.dumps({"dialogue_occupancy": {
            "blocks": [{"required_word_count": c} for c in part_ceilings]}}),
    }
    benefit = {"canonical_text": "melembapkan kulit sepanjang hari"}
    snapshot = types.SimpleNamespace(allowed_claims_json=[], blocked_claims_json=[])
    recipes = [("S1", {"angle_text": "a", "hook_text": "h", "body_text": "b", "cta_text": "c"})]
    return svc._build_stitch_prompt(session, benefit, snapshot, stages_order, recipes)


# 2 — provider-facing authoring max resolves to 19 (and the exact headroom law).
def test_authoring_headroom_law_8s():
    assert svc.copy_authoring_headroom(22) == 3          # max(2, ceil(22*0.10)) = 3
    assert svc.copy_authoring_max_words(22) == 19        # 22 - 3
    # exact-integer ceil across a spread of ceilings
    assert svc.copy_authoring_headroom(44) == 5 and svc.copy_authoring_max_words(44) == 39
    assert svc.copy_authoring_headroom(10) == 2          # ceil(1.0)=1 -> floored to 2
    assert svc.copy_authoring_max_words(10) == 8
    assert svc.copy_authoring_headroom(30) == 3          # ceil(3.0)=3
    assert svc.copy_authoring_max_words(1) == 1          # floored at 1 (headroom 2 -> max(1,-1))


# 3 — the prompt explicitly distinguishes authoring max 19 vs hard ceiling 22.
def test_prompt_distinguishes_authoring_max_and_hard_ceiling():
    system, user = _fake_prompt(22, [22], PAS_ORDER)
    blob = system + "\n" + user
    assert "AUTHORING TARGET/MAX" in user and "19" in user
    assert "ABSOLUTE SYSTEM HARD CEILING" in user and "22" in user
    assert "AUTHORING TARGET/MAX" in system and "19" in system and "22" in system
    # StitchFake / any compliant reader still finds the hard ceiling line verbatim.
    assert "Maximum total words per complete script: 22" in user
    # It must not instruct the provider to FILL the hard ceiling.
    assert "do NOT fill it" in user


# 8 — HSO and PAS use the SAME duration-derived headroom (formula-independent).
def test_headroom_is_formula_independent_hso_equals_pas():
    _sp, up_pas = _fake_prompt(22, [22], PAS_ORDER)
    _sh, up_hso = _fake_prompt(22, [22], HSO_ORDER)
    for u in (up_pas, up_hso):
        assert "AUTHORING TARGET/MAX: aim for AT MOST 19 words" in u
        assert "Maximum total words per complete script: 22" in u
    # different formula stage sets, identical authoring/ceiling numbers
    assert "problem" in str(up_pas) and "hook" in str(up_hso)


# 9 — multi-block headroom derives per canonical block.
def test_multi_block_headroom_per_block():
    system, user = _fake_prompt(44, [22, 22], PAS_ORDER)
    blob = system + "\n" + user       # the per-part rule lives in the system section
    assert "2 equal video parts" in blob
    assert "[19, 19]" in blob          # per-part authoring targets
    assert "[22, 22]" in blob          # per-part absolute hard maxima
    # whole-script authoring target is the per-block sum, not headroom-over-total
    assert svc.copy_authoring_max_words(22) * 2 == 38


async def test_hard_ceiling_unchanged_and_headroom_end_to_end():
    """1, 4, 5, 6, 7, 10, 11, 12, 13 — end-to-end through the real service with a
    fake provider whose total word count we pin via word_override."""
    before = real_calls()

    # 1 — 8s BM_MS hard ceiling remains 22 (word_budget is the hard ceiling).
    _boot, s = await _session_8s(target=5)
    assert s["word_budget"] == 22

    # 4/5/6/13 — outputs at 18, 19, 20, 21, 22 words all PASS validation (ceiling
    # is a maximum, shorter is valid — no underrun).
    for words in (18, 19, 20, 21, 22):
        _b2, s_ok = await _session_8s(target=1)
        fake = StitchFake(word_override=words)
        r = await svc.generate_suggestions(s_ok["session_id"], f"req-ok-{words:05d}", provider=fake)
        assert fake.calls == 1 and r["provider_calls"] == 1                 # 12 — call semantics
        assert fake.last_kwargs.get("allow_fallback") is False              # 11 — no fallback
        shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
        assert shown, f"{words}-word script should PASS the {s_ok['word_budget']} ceiling"
        art = await crud.get_artifact(shown[0]["artifact_id"])
        assert art["word_count"] == words                                   # 10 — NO trim/pad mutation
        assert len(art["full_copy_text"].split()) == words

    # 7/13 — a 23-word output still FAILS DIALOGUE_OCCUPANCY_OVERRUN (validation
    # unchanged; the authoring margin never relaxes the hard ceiling).
    _b3, s_over = await _session_8s(target=5)
    over = StitchFake(word_override=23)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s_over["session_id"], "req-over-00001", provider=over)
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    v = await svc.get_session(s_over["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]       # batch atomic, nothing shown

    assert real_calls() == before  # zero real provider calls across the whole test


# 14 — the renderer prompt version is bumped to v4 (new sessions use v4; the
# existing Round-2 suites remain green — run separately in the gate).
async def test_renderer_prompt_version_is_v4():
    assert RENDERER_PROMPT_VERSION == "copy-render-prompt-v4"
    _boot, s = await _session_8s(target=1)
    row = await crud.get_session(s["session_id"])  # raw row carries the lineage version
    assert row["renderer_prompt_version"] == "copy-render-prompt-v4"
