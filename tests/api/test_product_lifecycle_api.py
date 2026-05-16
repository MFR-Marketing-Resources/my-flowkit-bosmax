from __future__ import annotations

from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router
from agent.services import product_lifecycle_service as lifecycle_service


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def _product(**overrides):
    payload = {
        "id": "prod-001",
        "source": "MANUAL",
        "raw_product_title": "Atlas Product",
        "product_display_name": "Atlas Product",
        "product_short_name": "Atlas Product",
        "lifecycle_status": "ACTIVE",
        "created_at": "2026-05-16T12:00:00Z",
        "updated_at": "2026-05-16T12:00:00Z",
        "prompt_readiness_status": "READY",
        "image_readiness_status": "IMAGE_READY",
        "is_test_product": False,
    }
    payload.update(overrides)
    return payload


def _wire_lifecycle_crud(monkeypatch, store: dict[str, dict]):
    async def fake_get(product_id: str):
        row = store.get(product_id)
        return deepcopy(row) if row else None

    async def fake_update(product_id: str, **kwargs):
        store[product_id].update(kwargs)
        return deepcopy(store[product_id])

    async def fake_delete(product_id: str):
        return store.pop(product_id, None) is not None

    monkeypatch.setattr(lifecycle_service.crud, "get_product", fake_get)
    monkeypatch.setattr(lifecycle_service.crud, "update_product", fake_update)
    monkeypatch.setattr(lifecycle_service.crud, "delete_product", fake_delete)


def test_archive_requires_confirmation_phrase(monkeypatch):
    store = {"prod-001": _product()}
    _wire_lifecycle_crud(monkeypatch, store)
    client = TestClient(_build_app())

    response = client.post(
        "/api/products/prod-001/archive",
        json={"reason": "cleanup", "confirmation_phrase": "WRONG"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ARCHIVE_CONFIRMATION_REQUIRED"


def test_archived_products_are_hidden_by_default_and_returned_when_requested(monkeypatch):
    rows = [
        _product(id="active-001", raw_product_title="Active Product", product_short_name="Active Product", lifecycle_status="ACTIVE"),
        _product(id="archived-001", raw_product_title="Archived Product", product_short_name="Archived Product", lifecycle_status="ARCHIVED"),
    ]

    async def fake_list_products(source=None, query=None, limit=None, offset=None, include_archived=True, lifecycle_status=None):
        filtered = deepcopy(rows)
        if lifecycle_status:
            filtered = [row for row in filtered if row.get("lifecycle_status") == lifecycle_status]
        elif not include_archived:
            filtered = [row for row in filtered if row.get("lifecycle_status") != "ARCHIVED"]
        return filtered

    async def fake_enrich(product, persist=False):
        return deepcopy(product)

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products._enrich_product", fake_enrich)

    client = TestClient(_build_app())

    default_response = client.get("/api/products")
    assert default_response.status_code == 200
    assert [item["id"] for item in default_response.json()["items"]] == ["active-001"]

    include_response = client.get("/api/products?include_archived=true")
    assert include_response.status_code == 200
    assert {item["id"] for item in include_response.json()["items"]} == {"active-001", "archived-001"}

    archived_only_response = client.get("/api/products?include_archived=true&lifecycle_status=ARCHIVED")
    assert archived_only_response.status_code == 200
    assert [item["id"] for item in archived_only_response.json()["items"]] == ["archived-001"]


def test_unarchive_requires_confirmation_phrase(monkeypatch):
    store = {"prod-001": _product(lifecycle_status="ARCHIVED")}
    _wire_lifecycle_crud(monkeypatch, store)
    client = TestClient(_build_app())

    response = client.post(
        "/api/products/prod-001/unarchive",
        json={"reason": "restore", "confirmation_phrase": "WRONG"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "UNARCHIVE_CONFIRMATION_REQUIRED"


def test_fastmoss_archive_preserves_source_and_sales_metrics(monkeypatch):
    store = {
        "prod-001": _product(
            source="FASTMOSS",
            raw_product_title="Bosmax Proof",
            sold_count=74561117,
            shop_total_sold_count=74561117,
        )
    }
    _wire_lifecycle_crud(monkeypatch, store)
    client = TestClient(_build_app())

    response = client.post(
        "/api/products/prod-001/archive",
        json={"reason": "Legacy stale row", "confirmation_phrase": "ARCHIVE_PRODUCT"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "FASTMOSS"
    assert store["prod-001"]["source"] == "FASTMOSS"
    assert store["prod-001"]["shop_total_sold_count"] == 74561117


def test_normal_product_hard_delete_is_blocked(monkeypatch):
    store = {"prod-001": _product()}
    _wire_lifecycle_crud(monkeypatch, store)
    client = TestClient(_build_app())

    response = client.post(
        "/api/products/prod-001/delete-test-row",
        json={"reason": "cleanup", "confirmation_phrase": "DELETE_TEST_ROW_ONLY"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "TEST_ROW_DELETE_FORBIDDEN"


def test_test_row_delete_allowed_only_for_exact_test_pattern(monkeypatch):
    store = {
        "prod-001": _product(
            raw_product_title="PR59_RUNTIME_TEST_DO_NOT_USE",
            product_display_name="PR59_RUNTIME_TEST_DO_NOT_USE",
            product_short_name="PR59_RUNTIME_TEST_DO_NOT_USE",
        )
    }
    _wire_lifecycle_crud(monkeypatch, store)
    client = TestClient(_build_app())

    response = client.post(
        "/api/products/prod-001/delete-test-row",
        json={"reason": "cleanup", "confirmation_phrase": "DELETE_TEST_ROW_ONLY"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert "prod-001" not in store


def test_archived_product_prompt_route_returns_product_archived(monkeypatch):
    async def fake_find(_product_id: str):
        return _product(id="archived-001", lifecycle_status="ARCHIVED")

    monkeypatch.setattr("agent.api.products._find_product_by_lookup", fake_find)
    client = TestClient(_build_app())

    response = client.get("/api/products/archived-001/prompt")

    assert response.status_code == 409
    assert response.json()["detail"]["blocker"] == "PRODUCT_ARCHIVED"
