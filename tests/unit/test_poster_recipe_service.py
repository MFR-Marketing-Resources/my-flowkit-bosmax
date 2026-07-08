"""Poster recipe authority (PR B1) — loads, exposes minimum recipes, and seeds
NO unsafe/medical/therapeutic claims."""

from agent.services import poster_recipe_service
from agent.services.poster_prompt_draft_service import UNSAFE_CLAIM_TERMS

MIN_RECIPES = {"product_hero_night_routine", "heritage_infographic"}


def test_recipes_load_and_include_minimum_set():
    recipes = poster_recipe_service.list_recipes()
    ids = {r.recipe_id for r in recipes}
    assert MIN_RECIPES.issubset(ids), ids
    # Each recipe carries real structure, not just a label.
    for r in recipes:
        assert r.archetype
        assert r.layout_template
        assert r.product_placement
        assert r.zones, f"{r.recipe_id} has no zones"


def test_get_recipe_and_unknown_returns_none():
    assert poster_recipe_service.get_recipe("product_hero_night_routine") is not None
    assert poster_recipe_service.get_recipe("does_not_exist") is None
    assert poster_recipe_service.get_recipe("") is None


def test_recipe_summaries_shape():
    summaries = poster_recipe_service.list_recipe_summaries()
    ids = {s.recipe_id for s in summaries}
    assert MIN_RECIPES.issubset(ids)
    for s in summaries:
        assert s.label and s.archetype


def test_no_recipe_seeds_unsafe_claims():
    # SAFETY LAW: recipes must never hardcode disease/symptom/therapeutic wording.
    for r in poster_recipe_service.list_recipes():
        blob = " ".join(str(v) for v in r.model_dump().values()).lower()
        # include the zone placeholders explicitly
        blob += " " + " ".join(z.placeholder.lower() for z in r.zones)
        hits = [term for term in UNSAFE_CLAIM_TERMS if term in blob]
        assert not hits, f"{r.recipe_id} seeds unsafe terms: {hits}"


def test_heritage_placeholders_are_neutral():
    heritage = poster_recipe_service.get_recipe("heritage_infographic")
    assert heritage is not None
    placeholders = " ".join(z.placeholder for z in heritage.zones).lower()
    for banned in ("rawat", "sembuh", "ubat", "penyakit", "sakit", "lega", "pening", "resdung"):
        assert banned not in placeholders
