from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_recipes_endpoint_returns_authority():
    response = _client().get("/api/poster/recipes")
    assert response.status_code == 200
    body = response.json()
    recipes = body["recipes"]
    ids = {r["recipe_id"] for r in recipes}
    assert {"product_hero_night_routine", "heritage_infographic"}.issubset(ids)
    # Structured, not just labels: each recipe exposes zones + placement.
    hero = next(r for r in recipes if r["recipe_id"] == "product_hero_night_routine")
    assert hero["archetype"] == "PRODUCT_HERO"
    assert hero["product_placement"]
    assert len(hero["zones"]) >= 1
    assert any(z["role"] == "HEADLINE" for z in hero["zones"])
