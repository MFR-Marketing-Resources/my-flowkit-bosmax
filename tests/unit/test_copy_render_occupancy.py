"""Round 2 — copy dialogue occupancy CEILING alignment.

Copy Render binds to the SAME canonical temporal-occupancy authority the final
video validator uses, under CEILING semantics: SweetWPS is a per-block hard
MAXIMUM, not an exact target. Copy is valid when dialogue is non-empty and does
NOT exceed the maximum (total and per-block); shorter natural copy is fine
because the remaining block time is filled by the visual/action occupancy
authority. This mirrors ``video_continuity_contract`` (which raises
DIALOGUE_REQUIRED_MISSING for empty and SWEETWPS_OVERRUN for over-max only —
there is NO underrun). PROVIDER-FREE: the real adapter's process-global counter
never moves.
"""

import json
import re

import pytest

from agent.db import copy_render_crud as crud
from agent.services import canonical_prompt_compiler as cp
from agent.services import copy_render_service as svc
from agent.services import video_continuity_contract as vc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


async def _open(target: int = 5, duration: int = 16, lane: str = "HYBRID", **kw):
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=duration, **kw)
    return boot, s


# -- shared canonical occupancy authority (the values are per-block MAXIMUMS) ----
def test_16s_extend_maximums_derive_from_canonical_authority():
    occ = vc.resolve_dialogue_occupancy_targets(16, "BM_MS")
    assert occ["generation_mode"] == "EXTEND"
    assert occ["block_plan_seconds"] == [8, 8]
    assert [b["required_word_count"] for b in occ["blocks"]] == [22, 22]  # per-block CEILINGS
    assert occ["required_total_word_count"] == 44  # total CEILING (max), not an exact target
    assert occ["contract_version"] == vc.VIDEO_CONTINUITY_CONTRACT_VERSION
    # the SAME per-block maximum the final validator uses (one calculation, not two)
    assert vc._sweet_target_for_duration(cp, 8, "BM_MS") == 22
    assert vc._sweet_target_for_duration(cp, 16, "BM_MS") == 44


def test_8s_single_and_24s_extend_from_same_authority():
    o8 = vc.resolve_dialogue_occupancy_targets(8, "BM_MS")
    assert o8["generation_mode"] == "SINGLE" and o8["required_total_word_count"] == 22
    o24 = vc.resolve_dialogue_occupancy_targets(24, "BM_MS")
    assert o24["generation_mode"] == "EXTEND" and o24["required_total_word_count"] == 66
    assert [b["required_word_count"] for b in o24["blocks"]] == [22, 22, 22]


# -- session captures the occupancy contract as immutable lineage ----------
async def test_create_session_captures_occupancy_contract():
    _boot, s = await _open(duration=16)
    row = await crud.get_session(s["session_id"])
    lin = crud.decode(row["lineage_json"], {})
    assert lin["dialogue_target_word_count"] == 44  # the canonical maximum
    assert lin["execution_generation_mode"] == "EXTEND"
    assert lin["execution_block_plan_seconds"] == [8, 8]
    assert lin["occupancy_authority_version"] == vc.VIDEO_CONTINUITY_CONTRACT_VERSION
    assert lin["occupancy_authority_digest"]
    assert s["word_budget"] == 44  # the ceiling (hard maximum), not an exact target


# -- CEILING: shorter-than-max copy is VALID (no underrun) ------------------
async def test_short_copy_under_ceiling_is_valid_and_shown():
    """A 19-word complete script (well under the 44 max) that still splits into
    non-empty per-block dialogue is VALID and SHOWN — SweetWPS is a ceiling, and
    the remaining block time is visual/action occupancy. This is the exact case
    the old exact-== contract wrongly rejected."""
    _boot, s = await _open(target=5)
    r = await svc.generate_suggestions(s["session_id"], "req-occ-short19", provider=StitchFake(word_override=19))
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    assert len(shown) == 5
    for c in shown:
        art = await crud.get_artifact(c["artifact_id"])
        assert art["word_count"] == 19  # shorter-than-ceiling copy accepted verbatim (never padded)


async def test_at_ceiling_44_words_five_shown():
    _boot, s = await _open(target=5)
    r = await svc.generate_suggestions(s["session_id"], "req-occ-ceil44", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    assert len(shown) == 5
    for c in shown:
        art = await crud.get_artifact(c["artifact_id"])
        assert art["word_count"] == 44  # exactly AT the ceiling is allowed (== max)


# -- CEILING: over-max copy is rejected (batch-atomic, provider-free) -------
async def test_over_ceiling_rejected_batch_atomic_provider_free():
    before = real_calls()
    _boot, s = await _open(target=5)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-over60", provider=StitchFake(word_override=60))
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    assert "OVERRUN" in (e.value.message or "") or "OVERRUN" in str(e.value.details)
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]  # zero new SHOWN
    assert real_calls() == before


# -- materializability still guards: a block with NO speech is rejected -----
async def test_script_that_cannot_fill_all_dialogue_blocks_rejected():
    """A one-sentence script cannot supply non-empty dialogue to BOTH 8s blocks of
    a 16s EXTEND — the second block would carry no speech, which the downstream
    contract rejects as DIALOGUE_REQUIRED_MISSING. Ceiling semantics accept short
    copy, but every dialogue block must still be non-empty. Provider-free."""
    before = real_calls()
    _boot, s = await _open(target=5)

    class _OneSentence:
        """12 words, no sentence boundary -> one sentence -> block 2 gets no speech."""
        def complete_json_with_receipt(self, system, user, **kw):
            assert kw.get("allow_fallback") is False and kw.get("lane") == "structure"
            frag = {"problem": "buka soalan ringkas", "agitate": "terang guna harian",
                    "solution": "lega perut kembung", "cta": "cuba rutin ini"}
            keys = ["problem", "agitate", "solution", "cta"]
            suggestions = []
            for slot in re.findall(r"- (S\d+):", user):
                stages = [{"stage_key": k, "text": frag[k]} for k in keys]
                suggestions.append({"slot": slot, "stages": stages})
            return {"suggestions": suggestions}, {"provider": "fake", "model": "m", "call_id": "c", "usage": {}}

    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-onesent", provider=_OneSentence())
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    detail = str(e.value.details) + (e.value.message or "")
    assert "DIALOGUE_REQUIRED_MISSING" in detail or "BLOCK_" in detail
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]
    assert real_calls() == before


# -- one bad (over-max) suggestion fails the whole batch atomically ---------
async def test_one_bad_suggestion_fails_whole_batch_atomically():
    _boot, s = await _open(target=5)

    class _MostlyGood:
        """4 within-ceiling scripts + 1 over-max (60 words)."""
        def complete_json_with_receipt(self, system, user, **kw):
            good = StitchFake()
            body, _ = good.complete_json_with_receipt(system, user, **kw)
            bad = StitchFake(word_override=60)
            bad_body, _ = bad.complete_json_with_receipt(system, user, **kw)
            body["suggestions"][0]["stages"] = bad_body["suggestions"][0]["stages"]
            return body, {"provider": "fake", "model": "fake-model", "call_id": "c", "usage": {}}

    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-mixed", provider=_MostlyGood())
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]  # atomic: zero SHOWN


# -- occupancy authority identity participates in the cache key -------------
def test_render_key_binds_occupancy_authority_identity():
    base = {
        "product_id": "p", "pi_snapshot_id": "s", "pi_snapshot_version": 1, "benefit_digest": "b" * 64,
        "formula_id": "PAS", "formula_version": "v", "duration_seconds": 16, "target_language": "BM_MS",
        "wps_mode": "SWEET", "wps_authority_version": "wv", "wps_authority_digest": "wd",
        "renderer_prompt_version": "copy-render-prompt-v3", "safety_policy_version": "sp",
        "lineage_json": json.dumps({"occupancy_authority_version": "VIDEO_CONTINUITY_V1",
                                    "occupancy_authority_digest": "DIGEST_A"}),
    }
    fp = "f" * 64
    k_new = svc._render_key(base, fp)
    # An earlier prompt-version render (no occupancy digest) must NOT collide.
    old = dict(base, renderer_prompt_version="copy-render-prompt-v2", lineage_json=json.dumps({}))
    assert svc._render_key(old, fp) != k_new
    # A different occupancy authority digest also changes the key.
    diff = dict(base, lineage_json=json.dumps({"occupancy_authority_version": "VIDEO_CONTINUITY_V1",
                                               "occupancy_authority_digest": "DIGEST_B"}))
    assert svc._render_key(diff, fp) != k_new


# -- avatar remains visual-only; Faceless stays avatar-exempt --------------
async def test_avatar_bind_is_visual_only_and_does_not_touch_copy():
    _boot, s = await _open(target=2, lane="HYBRID")
    r = await svc.generate_suggestions(s["session_id"], "req-occ-avatar", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    before = {c["candidate_id"]: c["text_digest"] for c in shown}
    for cid in list(before)[:2]:
        await svc.lock_candidate(cid)
    await svc.finalize_session(s["session_id"])
    v = await svc.set_visual_config(s["session_id"], avatar_id="BOS_F_ALYA_01")
    assert v["status"] == "FINALIZED"
    after = {c["candidate_id"]: c["text_digest"] for c in v["candidates"]}
    for cid, td in before.items():
        assert after.get(cid) == td  # copy digests unchanged by avatar binding


async def test_faceless_is_avatar_exempt():
    boot = await bootstrap_ready_benefit()
    with pytest.raises(svc.CopyRenderError):
        await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="FACELESS", target_count=2, duration_seconds=16, avatar_id="BOS_F_ALYA_01")
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="FACELESS", target_count=2, duration_seconds=16)
    assert s["status"] == "OPEN"
