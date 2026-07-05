import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router
from agent.db import crud


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_product_patch_rejects_rich_product_knowledge_fields():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Patch Guardrail",
            source="MANUAL",
            product_display_name="Bosmax Patch Guardrail",
            product_short_name="Bosmax Patch Guardrail",
        )
    )

    response = _client().patch(
        f"/api/products/{product['id']}",
        json={
            "brand": "Bosmax",
            "benefits_text": "Portable routine support",
            "usage_text": "Apply externally",
            "ingredients_text": "Herbal blend",
            "warnings_text": "External use only",
            "target_customer_text": "Busy adults",
            "paste_anything_about_product": "Long-form messy notes",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    forbidden_fields = {entry["loc"][-1] for entry in detail if entry.get("type") == "extra_forbidden"}
    assert forbidden_fields >= {
        "benefits_text",
        "usage_text",
        "ingredients_text",
        "warnings_text",
        "target_customer_text",
        "paste_anything_about_product",
    }


def test_product_patch_allows_normal_catalog_fields():
    product = asyncio.run(
        crud.create_product(
            raw_product_title="Bosmax Patch Positive",
            source="MANUAL",
            product_display_name="Bosmax Patch Positive",
            product_short_name="Bosmax Patch Positive",
        )
    )

    response = _client().patch(
        f"/api/products/{product['id']}",
        json={
            "brand": "Bosmax",
            "category": "Beauty",
            "price": 19.9,
            "commission_rate": "12%",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["brand"] == "Bosmax"
    assert payload["category"] == "Beauty"
    assert payload["price"] == 19.9
    assert payload["commission_rate"] == "12%"
