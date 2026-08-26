"""On-Demand Copy Renderer service — Round-2 acceptance matrix + amendments/guards.

PROVIDER-FREE: the stitch call uses an injected StitchFake; the real adapter's
process-global request counter must never advance in this suite.
"""

import pytest

from agent.db import copy_render_crud as crud
from agent.services import copy_render_service as svc
from agent.services import creative_factory_service as cfsvc
from tests.copy_render_support import (
    SUPPORTED_BENEFIT_2,
    StitchFake,
    bootstrap_ready_benefit,
    real_calls,
)


async def _session(target: int = 5, duration: int = 16, lane: str = "HYBRID"):
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=duration)
    return boot, s


async def test_create_session_happy():
    _boot, s = await _session()
    assert s["status"] == "OPEN" and s["word_budget"] > 0
    assert s["total_unique_capacity"] == 162 and s["regenerate_enabled"] is True


async def test_lane_unsupported_rejected_provider_free():
    before = real_calls()
    boot = await bootstrap_ready_benefit()
    for lane in ("T2V", "F2V", "I2V", "MONTAGE", "P6"):
        with pytest.raises(svc.CopyRenderError) as e:
            await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                     lane=lane, target_count=3, duration_seconds=16)
        assert e.value.code == "COPY_RENDER_LANE_UNSUPPORTED"
    assert real_calls() == before


async def test_target_exceeds_capacity_rejected_provider_free():
    before = real_calls()
    boot = await bootstrap_ready_benefit()
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=163, duration_seconds=16)
    assert e.value.code == "COPY_RENDER_TARGET_EXCEEDS_CAPACITY"
    assert e.value.details["total_unique_capacity"] == 162
    assert real_calls() == before


async def test_benefit_not_ready_rejected():
    boot = await bootstrap_ready_benefit()
    b2 = await cfsvc.create_benefit(boot["product_id"], SUPPORTED_BENEFIT_2, None)  # no atom build
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.create_session(product_id=boot["product_id"], benefit_id=b2["benefit_id"],
                                 lane="HYBRID", target_count=3, duration_seconds=16)
    assert e.value.code == "COPY_RENDER_BENEFIT_NOT_READY"


async def test_generate_one_call_five_unique_valid():
    before = real_calls()
    _boot, s = await _session(target=5)
    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-gen-00001", provider=fake)
    assert fake.calls == 1 and r["provider_calls"] == 1
    assert fake.last_kwargs.get("allow_fallback") is False and fake.last_kwargs.get("lane") == "structure"
    cands = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    assert len(cands) == 5
    assert len({c["recipe_fingerprint"] for c in cands}) == 5
    assert len({c["text_digest"] for c in cands}) == 5
    for c in cands:
        art = await crud.get_artifact(c["artifact_id"])
        stages = crud.decode(art["stage_json"], [])
        assert [x["stage_key"] for x in stages] == ["problem", "agitate", "solution", "cta"]
        assert art["word_count"] <= s["word_budget"]
    assert real_calls() == before  # zero real provider calls


async def test_lock_to_target_completes_and_blocks_regenerate():
    _boot, s = await _session(target=2)
    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-lock-00001", provider=fake)
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    await svc.lock_candidate(shown[0])
    v = await svc.lock_candidate(shown[1])
    assert v["status"] == "TARGET_COMPLETE" and v["regenerate_enabled"] is False
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.lock_candidate(shown[2])
    assert e.value.code == "COPY_RENDER_LOCK_EXCEEDS_TARGET"
    with pytest.raises(svc.CopyRenderError) as e2:
        await svc.generate_suggestions(s["session_id"], "req-lock-00002", provider=fake)
    assert e2.value.code == "COPY_RENDER_SESSION_NOT_OPEN"


async def test_unlock_returns_shown_and_relockable():
    _boot, s = await _session(target=2)
    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-unl-00001", provider=fake)
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    await svc.lock_candidate(shown[0])
    await svc.lock_candidate(shown[1])
    v = await svc.unlock_candidate(shown[0])
    assert v["status"] == "OPEN" and v["locked_count"] == 1
    still = {c["candidate_id"]: c for c in v["candidates"]}
    assert still[shown[0]]["status"] == "SHOWN"  # visible, not skipped
    v2 = await svc.lock_candidate(shown[0])       # re-lockable
    assert v2["status"] == "TARGET_COMPLETE"


async def test_regenerate_moves_unlocked_shown_to_skipped_only_on_success():
    _boot, s = await _session(target=5)
    fake = StitchFake()
    r1 = await svc.generate_suggestions(s["session_id"], "req-reg-00001", provider=fake)
    b1 = {c["candidate_id"] for c in r1["candidates"] if c["status"] == "SHOWN"}
    assert len(b1) == 5
    r2 = await svc.generate_suggestions(s["session_id"], "req-reg-00002", provider=fake)
    b2 = {c["candidate_id"] for c in r2["candidates"] if c["status"] == "SHOWN"}
    assert len(b2) == 5 and b1.isdisjoint(b2)
    view_ids = {c["candidate_id"] for c in r2["candidates"]}
    assert b1.isdisjoint(view_ids)         # batch1 now SKIPPED, out of view
    assert r2["used_recipe_count"] == 10   # SKIPPED still counts as USED


async def test_failed_batch_atomic_prior_shown_untouched():
    _boot, s = await _session(target=5)
    good = StitchFake()
    r1 = await svc.generate_suggestions(s["session_id"], "req-fail-00001", provider=good)
    b1 = {c["candidate_id"] for c in r1["candidates"] if c["status"] == "SHOWN"}
    bad = StitchFake(corrupt_stage=True)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-fail-00002", provider=bad)
    assert e.value.code == "COPY_RENDER_SUGGESTION_INVALID"
    v = await svc.get_session(s["session_id"])
    shown_now = {c["candidate_id"] for c in v["candidates"] if c["status"] == "SHOWN"}
    assert shown_now == b1  # failed regenerate produced nothing; prior SHOWN intact
    r3 = await svc.generate_suggestions(s["session_id"], "req-fail-00003", provider=good)
    assert len([c for c in r3["candidates"] if c["status"] == "SHOWN"]) == 5


async def test_batch_text_uniqueness_rejects_duplicate_full_copy():
    _boot, s = await _session(target=5)
    dup = StitchFake(force_duplicate=True)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.generate_suggestions(s["session_id"], "req-dup-00001", provider=dup)
    assert e.value.code == "COPY_RENDER_DUPLICATE_COPY_TEXT"
    v = await svc.get_session(s["session_id"])
    assert not [c for c in v["candidates"] if c["status"] == "SHOWN"]


async def test_finalize_requires_target_and_prepare_selected_contract(monkeypatch):
    _boot, s = await _session(target=2)
    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-fin-00001", provider=fake)
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    await svc.lock_candidate(shown[0])
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.finalize_session(s["session_id"])
    assert e.value.code == "COPY_RENDER_TARGET_INCOMPLETE"
    await svc.lock_candidate(shown[1])
    fin = await svc.finalize_session(s["session_id"])
    assert fin["status"] == "FINALIZED" and fin["finalized_at"]

    sel = await svc.selected(s["session_id"])
    assert sel["count"] == 2 and all(x["status"] == "FINALIZED" for x in sel["selected"])

    # prepare-selected: stub the package builder to isolate the orchestration
    # contract — N candidate-exact packages, correct benefit-render context, NO
    # enqueue, idempotent re-run (amendment 2 / guard 10).
    import agent.services.workspace_execution_package_service as wep
    seen = []

    async def _stub(**kw):
        seen.append(kw.get("copy_v2_context"))
        cid = kw["copy_v2_context"]["benefit_copy_render"]["candidate_id"]
        return {"workspace_execution_package_id": "wep_" + cid[-6:], "execution_allowed": False,
                "blockers": ["VISUALS_DEFAULT"], "prompt_fingerprint": "fp"}

    monkeypatch.setattr(wep, "create_workspace_execution_package", _stub)
    # HYBRID is presenter-led (Round 2.2): bind a governed avatar so packages can
    # materialize. Visual config only — never part of copy lineage.
    await crud.update_session(s["session_id"], {"avatar_id": "BOS_F_ALYA_01"})
    prep = await svc.prepare_selected(s["session_id"])
    assert prep["enqueued"] is False and prep["package_count"] == 2
    assert all(c["lane"] == "HYBRID" and "benefit_copy_render" in c for c in seen)
    seen.clear()
    prep2 = await svc.prepare_selected(s["session_id"])
    assert all(p.get("reused") for p in prep2["packages"]) and seen == []  # idempotent, no rebuild


async def test_prepare_selected_requires_finalized():
    _boot, s = await _session(target=2)
    fake = StitchFake()
    await svc.generate_suggestions(s["session_id"], "req-pre-00001", provider=fake)
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.prepare_selected(s["session_id"])
    assert e.value.code == "COPY_RENDER_NOT_FINALIZED"


async def test_update_target_feasibility():
    _boot, s = await _session(target=3)
    fake = StitchFake()
    r = await svc.generate_suggestions(s["session_id"], "req-tgt-00001", provider=fake)
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    await svc.lock_candidate(shown[0])
    await svc.lock_candidate(shown[1])
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.update_target(s["session_id"], 1)
    assert e.value.code == "COPY_RENDER_TARGET_BELOW_LOCKED"
    with pytest.raises(svc.CopyRenderError) as e2:
        await svc.update_target(s["session_id"], 999)
    assert e2.value.code == "COPY_RENDER_TARGET_EXCEEDS_CAPACITY"
    v = await svc.update_target(s["session_id"], 4)
    assert v["target_count"] == 4 and v["status"] == "OPEN"
