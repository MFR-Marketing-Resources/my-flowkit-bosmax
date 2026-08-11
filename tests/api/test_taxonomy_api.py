from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from agent.api.products import router as products_router
from agent.api.taxonomy import router as taxonomy_router
from agent.db import crud
from agent.services.copywriting_taxonomy_service import (
    seed_copywriting_taxonomy_registry,
)


def _client() -> FastAPI:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    app.include_router(taxonomy_router, prefix="/api")
    return app


@pytest.mark.asyncio
async def test_taxonomy_tree_endpoint_shape_and_collision_winner():
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    transport = httpx.ASGITransport(app=_client())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/taxonomy/tree")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "categories",
        "subcategoriesByCategory",
        "typesBySubcategory",
        "recordByType",
    }
    assert (
        body["recordByType"][
            "Beauty & Personal Care::Facial Cleansing::Brightening Facial Soap"
        ]["product_type_code"]
        == "facial_cleansing_soap"
    )


@pytest.mark.asyncio
async def test_product_patch_fails_closed_and_valid_save_resolves_angle():
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )
    product = await crud.create_product(
        "Taxonomy Test Product",
        source="MANUAL",
        product_display_name="Taxonomy Test Product",
        product_short_name="Taxonomy Test",
    )
    transport = httpx.ASGITransport(app=_client())

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.patch(
            f"/api/products/{product['id']}",
            json={
                "category": "Kitchenware",
                "subcategory": "Not in SSOT",
                "type": "Invalid",
            },
        )
        assert invalid.status_code == 422
        assert (
            invalid.json()["detail"]["error_code"]
            == "COPYWRITING_TAXONOMY_SELECTION_INVALID"
        )

        unchanged = await crud.get_product(product["id"])
        assert unchanged["category"] is None

        valid = await client.patch(
            f"/api/products/{product['id']}",
            json={
                "category": "Toys & Games",
                "subcategory": "Creative Play",
                "type": "3D Scene Sticker Books",
                "copywriting_angle": "not accepted without override",
            },
        )
        assert valid.status_code == 200, valid.text

        resolved = await client.get(f"/api/taxonomy/product/{product['id']}")
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["match_status"] == "EXACT_CODE"

    stored = await crud.get_product(product["id"])
    assert stored["copywriting_product_type_code"] == "3d_sticker_book"
    assert stored["copywriting_angle"] == (
        "Creativity-led city-scene storytelling, reusable play, and "
        "screen-free engagement"
    )
