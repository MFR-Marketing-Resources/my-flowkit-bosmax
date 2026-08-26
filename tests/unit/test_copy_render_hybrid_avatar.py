"""Round 2.2 — HYBRID governed-avatar handoff for Copy Render prepare-selected.

HYBRID is presenter-led: the canonical compiler correctly requires an explicit
Avatar Registry identity for VISIBLE_CREATOR. The defect was that prepare-selected
carried no avatar_id, surfacing an opaque AVATAR_REGISTRY_SELECTION_REQUIRED. This
suite proves the minimal visual-config handoff: a clean fail-closed when HYBRID has
no avatar, the avatar flowing into materialization, FACELESS staying avatar-exempt,
and — crucially — that a visual-config change never calls the copy provider or
rewrites copy text.

PROVIDER-FREE: the stitch uses StitchFake; the real adapter's process-global
request counter must never advance in this suite.
"""

import pytest

from agent.db import copy_render_crud as crud
from agent.services import avatar_registry as _avatars
from agent.services import copy_render_service as svc
from tests.copy_render_support import (
    StitchFake,
    bootstrap_ready_benefit,
    real_calls,
)

_AVATAR = "BOS_F_ALYA_01"  # a real adult AvatarCode in the governed pool


async def _finalized(target: int = 2, duration: int = 16, lane: str = "HYBRID",
                     avatar_id: str | None = None):
    boot = await bootstrap_ready_benefit()
    s = await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=duration,
                                 avatar_id=avatar_id)
    r = await svc.generate_suggestions(s["session_id"], f"req-av-{lane}-00001", provider=StitchFake())
    shown = [c["candidate_id"] for c in r["candidates"] if c["status"] == "SHOWN"]
    for cid in shown[:target]:
        await svc.lock_candidate(cid)
    await svc.finalize_session(s["session_id"])
    return boot, s


def _stub_wep(monkeypatch):
    import agent.services.workspace_execution_package_service as wep
    captured: list[dict] = []

    async def _stub(**kw):
        captured.append(kw)
        cid = kw["copy_v2_context"]["benefit_copy_render"]["candidate_id"]
        return {"workspace_execution_package_id": "wep_" + cid[-6:], "execution_allowed": False,
                "blockers": ["VISUALS_DEFAULT"], "prompt_fingerprint": "fp"}

    monkeypatch.setattr(wep, "create_workspace_execution_package", _stub)
    return captured


# ── A: HYBRID prepare-selected without avatar → clean fail-closed, zero provider calls
async def test_A_hybrid_without_avatar_fails_closed_provider_free(monkeypatch):
    captured = _stub_wep(monkeypatch)
    _boot, s = await _finalized(lane="HYBRID", avatar_id=None)
    before = real_calls()
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.prepare_selected(s["session_id"])
    assert e.value.code == "COPY_RENDER_HYBRID_AVATAR_REQUIRED"
    assert e.value.status_code == 422
    assert e.value.details.get("status") == "VISUAL_CONFIG_REQUIRED"
    assert real_calls() == before          # zero provider calls
    assert captured == []                   # never reached materialization


# ── B: HYBRID with a valid explicit avatar → packages materialize
async def test_B_hybrid_with_valid_avatar_materializes(monkeypatch):
    captured = _stub_wep(monkeypatch)
    _boot, s = await _finalized(target=2, lane="HYBRID", avatar_id=_AVATAR)
    prep = await svc.prepare_selected(s["session_id"])
    assert prep["enqueued"] is False and prep["package_count"] == 2
    assert all(p["status"] == "READY" for p in prep["packages"])
    assert len(captured) == 2


# ── C: the presenter carried into materialization equals the selected avatar_id
async def test_C_resolved_presenter_equals_selected_avatar(monkeypatch):
    captured = _stub_wep(monkeypatch)
    _boot, s = await _finalized(target=1, lane="HYBRID", avatar_id=_AVATAR)
    await svc.prepare_selected(s["session_id"])
    assert captured, "materialization must be invoked"
    for kw in captured:
        assert kw["avatar_id"] == _AVATAR
        assert kw["character_presence"] == "VISIBLE_CREATOR"


# ── D: changing avatar visual config does NOT rewrite copy text
async def test_D_avatar_change_does_not_rewrite_copy(monkeypatch):
    monkeypatch.setattr(_avatars, "resolve_presenter", lambda code=None, **_: {"AvatarCode": code})
    _boot, s = await _finalized(target=2, lane="HYBRID", avatar_id=_AVATAR)
    before = await svc.selected(s["session_id"])
    copy_before = [(c["recipe_fingerprint"], c["full_copy_text"]) for c in before["selected"]]
    await svc.set_visual_config(s["session_id"], avatar_id="BOS_M_RIZAL_01")  # different presenter
    after = await svc.selected(s["session_id"])
    copy_after = [(c["recipe_fingerprint"], c["full_copy_text"]) for c in after["selected"]]
    assert copy_after == copy_before          # copy text + recipe identity unchanged


# ── E: changing avatar does NOT increment the text-provider call ledger
async def test_E_avatar_change_no_provider_call(monkeypatch):
    monkeypatch.setattr(_avatars, "resolve_presenter", lambda code=None, **_: {"AvatarCode": code})
    _boot, s = await _finalized(target=1, lane="HYBRID", avatar_id=_AVATAR)
    before = real_calls()
    v = await svc.set_visual_config(s["session_id"], avatar_id="BOS_M_RIZAL_01")
    assert v["avatar_id"] == "BOS_M_RIZAL_01"
    assert real_calls() == before           # provider ledger unchanged


# ── F: FACELESS prepare-selected remains avatar-exempt
async def test_F_faceless_is_avatar_exempt(monkeypatch):
    captured = _stub_wep(monkeypatch)
    _boot, s = await _finalized(target=2, lane="FACELESS", avatar_id=None)
    prep = await svc.prepare_selected(s["session_id"])
    assert prep["package_count"] == 2 and all(p["status"] == "READY" for p in prep["packages"])
    for kw in captured:
        assert kw["avatar_id"] is None      # no presenter forced onto FACELESS
        assert kw["character_presence"] == "FACELESS"


async def test_F2_faceless_rejects_supplied_avatar():
    boot = await bootstrap_ready_benefit()
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane="FACELESS", target_count=2, duration_seconds=16,
                                 avatar_id=_AVATAR)
    assert e.value.code == "COPY_RENDER_FACELESS_AVATAR_NOT_ALLOWED"


# ── J: READY cannot be emitted while the avatar requirement is unresolved
async def test_J_ready_blocked_until_avatar_bound(monkeypatch):
    captured = _stub_wep(monkeypatch)
    _boot, s = await _finalized(target=2, lane="HYBRID", avatar_id=None)
    view = await svc.get_session(s["session_id"])
    assert view["visual_config_required"] is True and not view["avatar_id"]
    with pytest.raises(svc.CopyRenderError) as e:
        await svc.prepare_selected(s["session_id"])
    assert e.value.code == "COPY_RENDER_HYBRID_AVATAR_REQUIRED"
    # Bind the presenter, then packages materialize READY.
    monkeypatch.setattr(_avatars, "resolve_presenter", lambda code=None, **_: {"AvatarCode": code})
    v = await svc.set_visual_config(s["session_id"], avatar_id=_AVATAR)
    assert v["visual_config_required"] is False and v["avatar_id"] == _AVATAR
    prep = await svc.prepare_selected(s["session_id"])
    assert prep["package_count"] == 2 and all(p["status"] == "READY" for p in prep["packages"])


# ── G/H/I: the compiled HYBRID prompt carries the presenter contract.
# The avatar handoff (VISIBLE_CREATOR + avatar_id, proven reaching materialization
# in test C) drives the canonical compiler; this asserts the resulting HYBRID
# prompt is presenter-led with Section 6/7 dialogue and lip-sync — never a
# product-only fallback. Compiler-direct (no full WEP claim-safe gate), matching
# the established compiler coverage.
def _compiled_hybrid_prompt() -> str:
    from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
    result = compile_ugc_video_prompt(
        product={"id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
                 "product_display_name": "Minyak Warisan Cap Burung 25ml",
                 "raw_product_title": "Minyak Warisan Cap Burung 25ml"},
        approved_package={"mode": "F2V",
                          "claim_safe_rewrite": "Frame the traditional oil as an everyday comfort routine, no guaranteed outcomes."},
        avatar_id="BOS_F_AINA_01",              # a real governed presenter identity
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        camera_style="UGC_IPHONE_RAW",
        character_presence="VISIBLE_CREATOR",   # HYBRID = presenter-led
        creator_persona="DEFAULT_CREATOR",
        target_language="BM_MS",
        safe_hook_angles=["Mulakan dengan creator tunjuk rutin harian yang natural dan claim-safe."],
        safe_cta_angles=["Akhiri dengan CTA lembut untuk cuba rutin ini."],
    )
    return str(result["final_compiled_prompt_text"])


def test_G_hybrid_prompt_has_section_6_and_7():
    up = _compiled_hybrid_prompt().upper()
    assert "SECTION 6 - SPOKEN DIALOGUE" in up
    assert "SECTION 7 - VOICE & DELIVERY" in up


def test_H_hybrid_prompt_has_visible_presenter_not_product_only():
    prompt = _compiled_hybrid_prompt()
    assert "The presenter is a Malaysian" in prompt          # concrete presenter, not product-only
    assert "one visible creator" not in prompt.lower()       # never the generic placeholder


def test_I_hybrid_prompt_has_lipsync_contract():
    low = _compiled_hybrid_prompt().lower()
    # presenter face/mouth synchronized to spoken words (lip-sync contract)
    assert ("lip" in low) or ("mouth" in low and "sync" in low) or ("synchroni" in low and "spoken" in low)
