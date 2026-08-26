"""Round 3 — Creative Execution Recipe + Auto Visual Variation (provider-free)."""

import pytest

from agent.services import auto_visual_variation_service as avv
from agent.services import creative_execution_recipe_service as svc
from tests.copy_render_support import (
    StitchFake,
    bootstrap_ready_benefit,
    real_calls,
)
from agent.services import copy_render_service as crs


async def _finalized_candidate(lane: str = "HYBRID", target: int = 2, **kw):
    boot = await bootstrap_ready_benefit()
    s = await crs.create_session(product_id=boot["product_id"], benefit_id=boot["benefit_id"],
                                 lane=lane, target_count=target, duration_seconds=16, **kw)
    r = await crs.generate_suggestions(s["session_id"], "req-cer-01", provider=StitchFake())
    shown = [c for c in r["candidates"] if c["status"] == "SHOWN"]
    for c in shown[:target]:
        await crs.lock_candidate(c["candidate_id"])
    await crs.finalize_session(s["session_id"])
    sel = await crs.selected(s["session_id"])
    return boot, s, sel["selected"][0]["candidate_id"]


# -- auto visual variation resolver (deterministic, provider-free) ----------
async def test_hybrid_visual_variations_distinct_and_deterministic():
    boot = await bootstrap_ready_benefit()
    before = real_calls()
    a = await avv.resolve_visual_variations(boot["product_id"], "HYBRID", 5)
    b = await avv.resolve_visual_variations(boot["product_id"], "HYBRID", 5)
    assert len(a["variations"]) == 5
    fps = [v["visual_variation_fingerprint"] for v in a["variations"]]
    assert len(set(fps)) == 5  # distinct while capacity allows
    assert a["unique_capacity"] >= 5
    # camera follows scene: every HYBRID variation carries a scene-derived camera
    assert all(v.get("camera_preset_code") for v in a["variations"])
    # deterministic: same request -> identical fingerprint sequence
    assert [v["visual_variation_fingerprint"] for v in b["variations"]] == fps
    assert real_calls() == before  # provider-free


async def test_controlled_reuse_only_after_capacity_exhausted():
    boot = await bootstrap_ready_benefit()
    cap = (await avv.resolve_visual_variations(boot["product_id"], "HYBRID", 1))["unique_capacity"]
    r = await avv.resolve_visual_variations(boot["product_id"], "HYBRID", cap + 3)
    reused = [v for v in r["variations"] if v["reuse"]]
    assert len(reused) == 3 and all(v["reuse_reason"] == avv.VISUAL_CAPACITY_REUSE for v in reused)
    assert all(not v["reuse"] for v in r["variations"][:cap])


# -- creative execution recipe (SAME_SCRIPT_DIFF_VISUALS) --------------------
async def test_create_recipes_same_copy_distinct_visuals_provider_free():
    boot, s, cand = await _finalized_candidate("HYBRID", target=2, avatar_id="BOS_F_ALYA_01")
    before = real_calls()
    out = await svc.create_execution_recipes(
        candidate_id=cand, production_recipe="HYBRID", visual_count=5)
    recipes = out["recipes"]
    assert len(recipes) == 5
    # SAME copy identity across all 5
    assert len({r["copy_text_digest"] for r in recipes}) == 1
    assert all(r["candidate_id"] == cand for r in recipes)
    assert all(r["copy_source"] == "BENEFIT_COPY_RENDER_V1" for r in recipes)
    # DISTINCT visual identity
    assert len({r["visual_variation_fingerprint"] for r in recipes}) == 5
    assert all(r["status"] == "DRAFT" for r in recipes)
    assert real_calls() == before  # provider-free recipe creation


async def test_exact_replay_same_inputs_same_recipe_id():
    boot, s, cand = await _finalized_candidate("HYBRID", target=1, avatar_id="BOS_F_ALYA_01")
    a = await svc.create_execution_recipes(candidate_id=cand, production_recipe="HYBRID",
                                           visual_count=3, seed="fixed")
    b = await svc.create_execution_recipes(candidate_id=cand, production_recipe="HYBRID",
                                           visual_count=3, seed="fixed")
    assert [r["recipe_id"] for r in a["recipes"]] == [r["recipe_id"] for r in b["recipes"]]


async def test_remix_same_copy_new_visual_no_copy_provider_call():
    boot, s, cand = await _finalized_candidate("HYBRID", target=1, avatar_id="BOS_F_ALYA_01")
    base = (await svc.create_execution_recipes(candidate_id=cand, production_recipe="HYBRID",
                                               visual_count=1, seed="A"))["recipes"][0]
    before = real_calls()
    remixed = (await svc.remix_execution_recipe(base["recipe_id"], seed="B"))["recipes"][0]
    assert remixed["recipe_id"] != base["recipe_id"]
    assert remixed["copy_text_digest"] == base["copy_text_digest"]  # SAME copy
    assert remixed["visual_variation_fingerprint"] != base["visual_variation_fingerprint"]
    assert real_calls() == before  # no text-provider call


async def test_compile_produces_immutable_prompt_snapshot_provider_free(monkeypatch):
    # Stub the heavy canonical compiler (needs a fully-provisioned product; proven at
    # runtime) and assert the Round-3 SEAM CONTRACT: benefit-copy lineage + the
    # scene-derived HYBRID visual variation reach the compiler, and the snapshot freezes.
    import agent.services.workspace_execution_package_service as wep
    captured = []

    async def _stub(**kw):
        captured.append(kw)
        cid = kw["copy_v2_context"]["benefit_copy_render"]["candidate_id"]
        return {"workspace_execution_package_id": "wep_" + cid[-6:],
                "prompt_fingerprint": "fp_" + str(kw.get("scene_template") or ""),
                "canonical_package_fingerprint": "cpf", "compiler_version": "vX",
                "execution_allowed": False, "blockers": ["VISUALS_DEFAULT"],
                "generation_mode": kw.get("generation_mode"), "total_duration_seconds": 16}

    monkeypatch.setattr(wep, "create_workspace_execution_package", _stub)

    boot, s, cand = await _finalized_candidate("HYBRID", target=1, avatar_id="BOS_F_ALYA_01")
    recipe = (await svc.create_execution_recipes(candidate_id=cand, production_recipe="HYBRID",
                                                 visual_count=1, avatar_id="BOS_F_ALYA_01"))["recipes"][0]
    before = real_calls()
    r1 = await svc.compile_execution_recipe(recipe["recipe_id"])
    assert r1["workspace_execution_package_id"] and r1["prompt_fingerprint"]
    # seam contract
    kw = captured[-1]
    assert kw["copy_v2_context"]["lane"] == "HYBRID"
    assert kw["copy_v2_context"]["benefit_copy_render"]["candidate_id"] == cand
    assert kw["character_presence"] == "VISIBLE_CREATOR"
    assert kw["avatar_id"] == "BOS_F_ALYA_01"
    assert kw["scene_template"] is not None and kw["camera_preset"] is not None  # camera follows scene
    assert kw["generation_mode"] == "EXTEND" and kw["requested_total_duration_seconds"] == 16
    # immutable snapshot bound + FINALIZED
    fin = await svc.get_execution_recipe(recipe["recipe_id"])
    assert fin["status"] == "FINALIZED"
    assert fin["workspace_execution_package_id"] == r1["workspace_execution_package_id"]
    # exact replay: recompiling a FINALIZED recipe reuses the same frozen snapshot, no recompile
    captured.clear()
    r2 = await svc.compile_execution_recipe(recipe["recipe_id"])
    assert r2["reused"] is True
    assert r2["workspace_execution_package_id"] == r1["workspace_execution_package_id"]
    assert r2["prompt_fingerprint"] == r1["prompt_fingerprint"]
    assert captured == []  # no recompile of a finalized recipe
    assert real_calls() == before  # no text-provider call during compile


# -- FACELESS + MONTAGE (presenter-free; MONTAGE consumes FACELESS copy) -----
async def test_faceless_recipe_create_provider_free():
    boot, s, cand = await _finalized_candidate("FACELESS", target=1)
    before = real_calls()
    out = await svc.create_execution_recipes(
        candidate_id=cand, production_recipe="FACELESS", visual_count=3)
    assert len(out["recipes"]) == 3
    assert all(r["production_recipe"] == "FACELESS" for r in out["recipes"])
    assert all(r["avatar_id"] is None for r in out["recipes"])  # faceless: no avatar
    assert real_calls() == before


async def test_montage_requires_mascot_fail_closed():
    # The bootstrap product has NO governed mascot -> MONTAGE recipe creation must
    # fail closed (deterministic MASCOT_REQUIRED), never invent a mascot identity.
    boot, s, cand = await _finalized_candidate("FACELESS", target=1)
    with pytest.raises(svc.CreativeExecutionRecipeError) as e:
        await svc.create_execution_recipes(
            candidate_id=cand, production_recipe="MONTAGE", visual_count=2)
    assert e.value.code == "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


async def test_montage_with_mascot_binds_mascot_identity():
    boot, s, cand = await _finalized_candidate("FACELESS", target=1)
    from agent.services import product_mascot_service as pm
    _png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP8z8BQDwAE"
            "hQGAhKmMIQAAAABJRU5ErkJggg==")
    await pm.set_product_mascot(boot["product_id"], image_base64=_png, file_name="m.png")
    out = await svc.create_execution_recipes(
        candidate_id=cand, production_recipe="MONTAGE", visual_count=2)
    assert len(out["recipes"]) >= 1
    assert all(r["production_recipe"] == "MONTAGE" for r in out["recipes"])
    assert all(r["montage_mascot_media_id"] for r in out["recipes"])  # mascot bound


# -- lane guard + exact-replay stability ------------------------------------
async def test_hybrid_recipe_rejects_faceless_candidate_lane_mismatch():
    boot, s, cand = await _finalized_candidate("FACELESS", target=1)
    with pytest.raises(svc.CreativeExecutionRecipeError) as e:
        await svc.create_execution_recipes(
            candidate_id=cand, production_recipe="HYBRID", visual_count=1)
    assert e.value.code == "EXECUTION_RECIPE_LANE_MISMATCH"


def test_visual_fingerprint_is_deterministic_and_order_independent():
    a = avv.visual_variation_fingerprint({"x": 1, "y": 2})
    b = avv.visual_variation_fingerprint({"y": 2, "x": 1})
    assert a == b and len(a) == 64
