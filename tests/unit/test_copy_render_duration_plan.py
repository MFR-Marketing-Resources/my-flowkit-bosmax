"""Round 2.1 — copy TOTAL duration → canonical video execution plan (SINGLE/EXTEND).

The live UAT exposed that prepare-selected passed the session TOTAL duration (16s)
as a single video block, which the canonical compiler rejects. The fix reuses the
EXISTING model-duration authority (``video_models.resolve_orchestration``) so 16s
resolves to a governed EXTEND whose block chain the canonical compiler derives
(8+8). No block table is duplicated in Copy Render. PROVIDER-FREE.
"""

import pytest

from agent.services import canonical_prompt_compiler as _canon
from agent.services import copy_render_service as svc
from tests.copy_render_support import StitchFake, bootstrap_ready_benefit, real_calls


async def _finalized_session(target: int, duration: int, lane: str = "HYBRID"):
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=duration)
    r = await svc.generate_suggestions(s["session_id"], f"req-dp-{duration}-00001", provider=StitchFake())
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    for cid in shown[:target]:
        await svc.lock_candidate(cid)
    await svc.finalize_session(s["session_id"])
    return boot, s


# -- the canonical mapping (reused authority, not a Copy Render table) ------
def test_16s_maps_to_canonical_extend_and_compiler_derives_8_8():
    plan = svc._resolve_execution_duration_plan(16)
    assert plan["generation_mode"] == "EXTEND"
    assert plan["engine_block_duration_seconds"] == 8
    assert plan["requested_total_duration_seconds"] == 16
    assert plan["segment_count"] == 2
    # The block chain is DERIVED by the canonical authority — asserted here, never
    # hardcoded/constructed inside Copy Render.
    assert _canon.resolve_block_plan("GOOGLE_FLOW", 16) == [8, 8]


def test_single_shot_durations_remain_single():
    for d in (4, 6, 8):
        p = svc._resolve_execution_duration_plan(d)
        assert p["generation_mode"] == "SINGLE"
        assert p["engine_block_duration_seconds"] == d
        assert p["requested_total_duration_seconds"] == d


def test_governed_extend_totals_via_same_planner_and_unsupported_rejected():
    p24 = svc._resolve_execution_duration_plan(24)
    assert p24["generation_mode"] == "EXTEND" and p24["segment_count"] == 3
    assert _canon.resolve_block_plan("GOOGLE_FLOW", 24) == [8, 8, 8]
    # A total the governed model-duration authority cannot represent raises — Copy
    # Render never invents a plan (15s is a valid *block* size but not a governed
    # single-shot/EXTEND total for this model, proving the fix is model-governed,
    # NOT "duration in ALLOWED_BLOCK_DURATIONS_SECONDS").
    for bad in (7, 15, 100):
        with pytest.raises(ValueError):
            svc._resolve_execution_duration_plan(bad)


# -- session-create preflight (provider-free) ------------------------------
async def test_create_session_rejects_unrepresentable_total_before_any_provider_call():
    # 10s has a valid copy word budget (27) AND is a valid video *block* size, but is
    # NOT a governed model single-shot/EXTEND total for this lane's model — so the
    # NEW representability preflight (not the word-budget check) must reject it.
    before = real_calls()
    boot = await bootstrap_ready_benefit()
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=3, duration_seconds=10)
    assert e.value.code == "COPY_RENDER_DURATION_NOT_REPRESENTABLE"
    assert real_calls() == before  # rejected provider-free, before any text call


async def test_create_session_accepts_governed_extend_total_16s():
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="HYBRID", target_count=5, duration_seconds=16)
    assert s["status"] == "OPEN" and s["duration_seconds"] == 16


# -- prepare-selected passes the canonical mapping -------------------------
async def test_prepare_selected_16s_passes_extend_and_yields_five_packages(monkeypatch):
    _boot, s = await _finalized_session(target=5, duration=16, lane="HYBRID")
    import agent.services.workspace_execution_package_service as wep
    captured = []

    async def _stub(**kw):
        captured.append(kw)
        cid = kw["copy_v2_context"]["benefit_copy_render"]["candidate_id"]
        return {"workspace_execution_package_id": "wep_" + cid[-6:], "execution_allowed": False,
                "blockers": ["VISUALS_DEFAULT"], "prompt_fingerprint": "fp"}

    monkeypatch.setattr(wep, "create_workspace_execution_package", _stub)
    prep = await svc.prepare_selected(s["session_id"])

    assert prep["package_count"] == 5 and prep["enqueued"] is False
    assert all(p["status"] == "READY" for p in prep["packages"])
    assert len({p["candidate_id"] for p in prep["packages"]}) == 5  # candidate-exact
    assert len(captured) == 5
    for kw in captured:
        assert kw["generation_mode"] == "EXTEND"
        assert kw["duration_seconds"] == 8                     # canonical block base
        assert kw["requested_total_duration_seconds"] == 16    # total -> compiler derives 8+8
        assert kw["engine_duration_target"] == "GOOGLE_FLOW"
        assert "benefit_copy_render" in kw["copy_v2_context"]  # BENEFIT_COPY_RENDER_V1 lineage
        assert kw["copy_v2_context"]["lane"] == "HYBRID"
    # idempotent re-run: reuse existing bindings, NO rebuild
    captured.clear()
    prep2 = await svc.prepare_selected(s["session_id"])
    assert prep2["package_count"] == 5 and all(p.get("reused") for p in prep2["packages"])
    assert captured == []


async def test_prepare_selected_single_duration_passes_single(monkeypatch):
    _boot, s = await _finalized_session(target=2, duration=8, lane="FACELESS")
    import agent.services.workspace_execution_package_service as wep
    captured = []

    async def _stub(**kw):
        captured.append(kw)
        return {"workspace_execution_package_id": "wep_single", "execution_allowed": False,
                "blockers": [], "prompt_fingerprint": "fp"}

    monkeypatch.setattr(wep, "create_workspace_execution_package", _stub)
    await svc.prepare_selected(s["session_id"])
    assert len(captured) == 2
    for kw in captured:
        assert kw["generation_mode"] == "SINGLE"
        assert kw["duration_seconds"] == 8
        assert kw["requested_total_duration_seconds"] is None
