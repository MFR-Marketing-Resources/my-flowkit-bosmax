"""Deterministic recipe selector (copy_render_combination_service) — ZERO provider.

Proves recipe enumeration matches the Round-1 compat-narrowed capacity, fingerprints
are stable, and selection is reproducible + diversity-preferring + excludes the
session-USED set.
"""

from agent.services import copy_render_combination_service as comb
from tests.copy_render_support import bootstrap_ready_benefit, real_calls


async def test_enumerate_matches_capacity_and_fingerprints_stable():
    before = real_calls()
    boot = await bootstrap_ready_benefit()
    recipes = await comb.enumerate_recipes(boot["benefit_id"])
    assert len(recipes) == boot["combinations"] == 162
    # recipe_fingerprint is a pure function of the 5 ids
    r = recipes[0]
    assert r["recipe_fingerprint"] == comb.recipe_fingerprint(
        r["benefit_id"], r["angle_id"], r["hook_id"], r["body_id"], r["cta_id"])
    # unique fingerprints across the whole enumeration
    assert len({x["recipe_fingerprint"] for x in recipes}) == len(recipes)
    assert await comb.unique_capacity(boot["benefit_id"]) == 162
    assert real_calls() == before  # provider-free


async def test_select_diverse_is_deterministic_and_excludes_used():
    boot = await bootstrap_ready_benefit()
    recipes = await comb.enumerate_recipes(boot["benefit_id"])
    a = comb.select_diverse(recipes, set(), seed="S:1", count=5)
    b = comb.select_diverse(recipes, set(), seed="S:1", count=5)
    assert [x["recipe_fingerprint"] for x in a] == [x["recipe_fingerprint"] for x in b]
    # a different seed generally reorders the picks (not asserting inequality of the
    # SET, only that selection is seed-driven, hence reproducible per seed)
    used = {x["recipe_fingerprint"] for x in a}
    nxt = comb.select_diverse(recipes, used, seed="S:2", count=5)
    assert used.isdisjoint({x["recipe_fingerprint"] for x in nxt})


async def test_select_diverse_prefers_distinct_angles():
    boot = await bootstrap_ready_benefit()
    recipes = await comb.enumerate_recipes(boot["benefit_id"])
    picked = comb.select_diverse(recipes, set(), seed="S:1", count=3)
    # 3 angles exist; the diversity strategy should surface all three first
    assert len({x["angle_id"] for x in picked}) == 3


async def test_select_diverse_caps_at_available_pool():
    boot = await bootstrap_ready_benefit()
    recipes = await comb.enumerate_recipes(boot["benefit_id"])
    used = {x["recipe_fingerprint"] for x in recipes[:-2]}  # only 2 left
    picked = comb.select_diverse(recipes, used, seed="S:9", count=5)
    assert len(picked) == 2
