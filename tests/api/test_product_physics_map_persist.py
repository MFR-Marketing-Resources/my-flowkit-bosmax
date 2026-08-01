"""B-586-06: POST /physics-map with persist=true must actually persist.

The endpoint previously called an undefined `_persist_intelligence` (NameError -> 500).
The first repair only created an intelligence draft, which removed the crash but left
persist=true semantically dishonest: physics and readiness were computed, returned in the
response, and never written to the product.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agent.db import crud
from agent.main import app


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _make_product() -> str:
    row = await crud.create_product(
        raw_product_title="Physics Persist Fixture Cream 50ml",
        product_display_name="Physics Persist Fixture",
        product_short_name="Physics Persist Fixture",
        source="MANUAL",
        category="Beauty",
        subcategory="Skincare",
        type="Facial Cleansers",
    )
    return str(row["id"])


@pytest.mark.asyncio
async def test_physics_map_persist_true_writes_and_survives_reread():
    pid = await _make_product()
    async with await _client() as c:
        r = await c.post("/api/products/physics-map", json={
            "product_id": pid,
            "product_name": "Physics Persist Fixture Cream 50ml",
            "category": "Beauty",
            "subcategory": "Skincare",
            "type": "Facial Cleansers",
            "persist": True,
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("persisted_fields"), "nothing was persisted"

    # re-read from the DB, not from the response
    stored = await crud.get_product(pid)
    for field in body["persisted_fields"]:
        assert stored[field] == body[field], f"{field} did not survive the re-read"
    assert "prompt_readiness_status" in body["persisted_fields"]
    assert stored["prompt_readiness_status"], "readiness not persisted"


@pytest.mark.asyncio
async def test_physics_map_persist_never_blanks_stored_values_with_empty_strings():
    """resolve_product_physics returns "" for an unclassifiable product; writing those
    would destroy real stored physics."""
    pid = await _make_product()
    await crud.update_product(pid, physics_class="BEAUTY_BOTTLE_OR_TUBE")
    async with await _client() as c:
        r = await c.post("/api/products/physics-map", json={
            "product_id": pid, "product_name": "Unclassifiable Thing",
            "persist": True})
    assert r.status_code == 200, r.text
    stored = await crud.get_product(pid)
    assert stored["physics_class"] == "BEAUTY_BOTTLE_OR_TUBE", "existing physics blanked"


@pytest.mark.asyncio
async def test_physics_map_persist_false_is_read_only():
    pid = await _make_product()
    before = await crud.get_product(pid)
    async with await _client() as c:
        r = await c.post("/api/products/physics-map", json={
            "product_id": pid,
            "product_name": "Physics Persist Fixture Cream 50ml",
            "category": "Beauty",
            "persist": False,
        })
    assert r.status_code == 200, r.text
    assert "persisted_fields" not in r.json()
    after = await crud.get_product(pid)
    for field in ("physics_class", "product_scale", "recommended_grip",
                  "prompt_readiness_status"):
        assert after[field] == before[field], f"{field} changed under persist=false"
