"""Poster recipe authority — expert e-commerce archetypes with poster-native
density; seeded COPY carries no unsafe/medical/symptom wording.
(POSTER_EXPERT_SYSTEM_REDESIGN_V1; was PR B1.)"""

from agent.services import poster_recipe_service
from agent.services.poster_prompt_draft_service import UNSAFE_CLAIM_TERMS

# The 6 expert archetypes the poster expert system requires.
EXPECTED_ARCHETYPES = {
    "PRODUCT_HERO",
    "PORTABILITY",
    "HERITAGE_TRUST",
    "ROUTINE_USE",
    "OFFER",
    "PROBLEM_AWARE_SAFE",
}
MIN_RECIPES = {"product_hero_night_routine", "heritage_infographic"}


def test_expert_archetypes_present():
    recipes = poster_recipe_service.list_recipes()
    archetypes = {r.archetype for r in recipes}
    assert EXPECTED_ARCHETYPES <= archetypes, archetypes
    assert MIN_RECIPES <= {r.recipe_id for r in recipes}
    for r in recipes:
        assert r.archetype and r.layout_template and r.product_placement
        assert r.zones, f"{r.recipe_id} has no zones"


def test_poster_native_density_caps():
    for r in poster_recipe_service.list_recipes():
        # An expert poster allows at most 3 chips.
        assert 1 <= r.max_chips <= 3, f"{r.recipe_id} max_chips={r.max_chips}"
        for z in r.zones:
            if z.role == "HEADLINE":
                assert 0 < z.max_words <= 7, f"{r.recipe_id} headline max_words {z.max_words}"
            if z.role == "CHIP":
                assert 0 < z.max_words <= 5
            if z.role == "CTA":
                assert 0 < z.max_words <= 4


def test_problem_aware_recipe_has_safe_posture():
    r = poster_recipe_service.get_recipe("problem_aware_safe")
    assert r is not None
    assert r.safety_posture == "PROBLEM_AWARE_SAFE"


def test_get_recipe_and_unknown_returns_none():
    assert poster_recipe_service.get_recipe("product_hero_night_routine") is not None
    assert poster_recipe_service.get_recipe("does_not_exist") is None
    assert poster_recipe_service.get_recipe("") is None


def test_seeded_copy_has_no_unsafe_claims():
    # SAFETY LAW: the SEEDED COPY (zone placeholders + selling angles) must never
    # hardcode disease/symptom/therapeutic wording. (Recipe safety-rule text may
    # legitimately NAME forbidden terms to forbid them — that is not seeded copy.)
    banned = tuple(UNSAFE_CLAIM_TERMS) + (
        "kembung", "legakan", "lega", "simptom", "tidur terganggu",
    )
    for r in poster_recipe_service.list_recipes():
        seeded = " ".join(z.placeholder for z in r.zones)
        seeded += " " + " ".join(r.main_selling_angles)
        low = seeded.lower()
        hits = [t for t in banned if t in low]
        assert not hits, f"{r.recipe_id} seeds unsafe copy: {hits}"
