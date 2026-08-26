"""Round 2.3 — copy dialogue occupancy authority alignment (exact SweetWPS).

Copy Render must accept/finalize only copy that is materializable under the SAME
canonical temporal-occupancy authority the final video validator uses: the
complete script must contain EXACTLY the required total dialogue words (per-block
SweetWPS sum), not merely stay under a ceiling. PROVIDER-FREE — the real adapter's
process-global counter never moves.
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


# -- (A/B/C/L/M) shared canonical occupancy authority ----------------------
def test_16s_extend_targets_derive_from_canonical_authority():
    occ = vc.resolve_dialogue_occupancy_targets(16, "BM_MS")
    assert occ["generation_mode"] == "EXTEND"
    assert occ["block_plan_seconds"] == [8, 8]
    assert [b["required_word_count"] for b in occ["blocks"]] == [22, 22]
    assert occ["required_total_word_count"] == 44
    assert occ["contract_version"] == vc.VIDEO_CONTINUITY_CONTRACT_VERSION
    # the SAME per-block target the final validator uses (one calculation, not two)
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
    assert lin["dialogue_target_word_count"] == 44
    assert lin["execution_generation_mode"] == "EXTEND"
    assert lin["execution_block_plan_seconds"] == [8, 8]
    assert lin["occupancy_authority_version"] == vc.VIDEO_CONTINUITY_CONTRACT_VERSION
    assert lin["occupancy_authority_digest"]
    assert s["word_budget"] == 44  # exact target, not a ceiling


# -- (D/E/F/G/H) exact occupancy enforced at authoring ---------------------
async def test_underrun_19_words_rejected_batch_atomic_provider_free():
    before = real_calls()
    _boot, s = await _open(target=5)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-under19", provider=StitchFake(word_override=19))
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    assert "OCCUPANCY_UNDERRUN" in (e.value.message or "") or "OCCUPANCY_UNDERRUN" in str(e.value.details)
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]  # zero new SHOWN
    assert real_calls() == before


async def test_43_underrun_and_45_overrun_rejected():
    for wc, kind in ((43, "UNDERRUN"), (45, "OVERRUN")):
        _boot, s = await _open(target=5)
        with pytest.raises(svc.CopyRenderError) as e:
            await svc.generate_suggestions(s["session_id"], f"req-occ-{wc}", provider=StitchFake(word_override=wc))
        assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"


async def test_exactly_44_words_five_shown():
    _boot, s = await _open(target=5)
    r = await svc.generate_suggestions(s["session_id"], "req-occ-exact44", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    assert len(shown) == 5
    for c in shown:
        art = await crud.get_artifact(c["artifact_id"])
        assert art["word_count"] == 44  # EXACT canonical occupancy


# -- (K) exact total is necessary but NOT sufficient: materializability ----
async def test_44_words_total_but_unsplittable_rejected_by_feasibility():
    """A script that hits the EXACT 44-word total but does NOT divide into the
    canonical per-block occupancy (one run-on with no sentence boundaries) is
    rejected by the provider-free feasibility gate — proving the gate enforces
    downstream materializability, not merely a word ceiling. Batch-atomic,
    provider-free: zero SHOWN, real adapter counter unmoved."""
    before = real_calls()
    _boot, s = await _open(target=5)

    class _RunOn:
        """Emits exactly 44 words as one un-punctuated run — total-valid, but the
        canonical block allocator cannot fill 22+22 from it (block 2 underruns)."""
        def complete_json_with_receipt(self, system, user, **kw):
            assert kw.get("allow_fallback") is False and kw.get("lane") == "structure"
            words = [f"perkataan{i}" for i in range(44)]
            keys = ["problem", "agitate", "solution", "cta"]
            suggestions = []
            for slot in re.findall(r"- (S\d+):", user):
                stages = [{"stage_key": k, "text": " ".join(words[j * 11:(j + 1) * 11])}
                          for j, k in enumerate(keys)]
                suggestions.append({"slot": slot, "stages": stages})
            return {"suggestions": suggestions}, {"provider": "fake", "model": "m", "call_id": "c", "usage": {}}

    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-runon44", provider=_RunOn())
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    assert "BLOCK_OCCUPANCY" in str(e.value.details) or "BLOCK_OCCUPANCY" in (e.value.message or "")
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]  # exact total, still zero SHOWN
    assert real_calls() == before


# -- (I) one bad suggestion fails the whole batch atomically ---------------
async def test_one_bad_suggestion_fails_whole_batch_atomically():
    _boot, s = await _open(target=5)

    class _MostlyGood:
        """4 exact-occupancy scripts + 1 underrun (19 words)."""
        def __init__(self):
            self.calls = 0
        def complete_json_with_receipt(self, system, user, **kw):
            self.calls += 1
            good = StitchFake()
            body, _ = good.complete_json_with_receipt(system, user, **kw)
            bad = StitchFake(word_override=19)
            bad_body, _ = bad.complete_json_with_receipt(system, user, **kw)
            # replace the first slot's stages with the underrun version
            body["suggestions"][0]["stages"] = bad_body["suggestions"][0]["stages"]
            return body, {"provider": "fake", "model": "fake-model", "call_id": "c", "usage": {}}

    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-occ-mixed", provider=_MostlyGood())
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]  # atomic: zero SHOWN


# -- (J) old ceiling-only cache artifacts never hit under the new authority
def test_render_key_binds_occupancy_authority_identity():
    base = {
        "product_id": "p", "pi_snapshot_id": "s", "pi_snapshot_version": 1, "benefit_digest": "b" * 64,
        "formula_id": "PAS", "formula_version": "v", "duration_seconds": 16, "target_language": "BM_MS",
        "wps_mode": "SWEET", "wps_authority_version": "wv", "wps_authority_digest": "wd",
        "renderer_prompt_version": "copy-render-prompt-v2", "safety_policy_version": "sp",
        "lineage_json": json.dumps({"occupancy_authority_version": "VIDEO_CONTINUITY_V1",
                                    "occupancy_authority_digest": "DIGEST_A"}),
    }
    fp = "f" * 64
    k_new = svc._render_key(base, fp)
    # An old ceiling-only render (v1 prompt, no occupancy digest) must NOT collide.
    old = dict(base, renderer_prompt_version="copy-render-prompt-v1", lineage_json=json.dumps({}))
    assert svc._render_key(old, fp) != k_new
    # A different occupancy authority digest also changes the key.
    diff = dict(base, lineage_json=json.dumps({"occupancy_authority_version": "VIDEO_CONTINUITY_V1",
                                               "occupancy_authority_digest": "DIGEST_B"}))
    assert svc._render_key(diff, fp) != k_new


# -- (P/Q) avatar remains visual-only; Faceless stays avatar-exempt --------
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
