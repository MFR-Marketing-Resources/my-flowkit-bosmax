from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException

from agent.services import product_lifecycle_service as svc


def _product(**overrides):
    payload = {
        "id": "prod-001",
        "source": "MANUAL",
        "raw_product_title": "Atlas Product",
        "product_display_name": "Atlas Product",
        "product_short_name": "Atlas Product",
        "lifecycle_status": "ACTIVE",
        "sales_metrics_source": "NOT_FOUND",
        "product_sold_count": None,
    }
    payload.update(overrides)
    return payload


def _wire_crud(monkeypatch, store: dict[str, dict]):
    async def fake_get(product_id: str):
        row = store.get(product_id)
        return deepcopy(row) if row else None

    async def fake_update(product_id: str, **kwargs):
        store[product_id].update(kwargs)
        return deepcopy(store[product_id])

    async def fake_delete(product_id: str):
        return store.pop(product_id, None) is not None

    monkeypatch.setattr(svc.crud, "get_product", fake_get)
    monkeypatch.setattr(svc.crud, "update_product", fake_update)
    monkeypatch.setattr(svc.crud, "delete_product", fake_delete)


async def test_archive_product_sets_archived_state_and_preserves_source(monkeypatch):
    store = {
        "prod-001": _product(source="FASTMOSS", raw_product_title="Bosmax Proof", product_sold_count=91, shop_total_sold_count=1200),
    }
    _wire_crud(monkeypatch, store)

    result = await svc.archive_product(
        "prod-001",
        reason="Legacy/stale row.",
        confirmation_phrase="ARCHIVE_PRODUCT",
    )

    assert result["lifecycle_status"] == "ARCHIVED"
    assert result["source"] == "FASTMOSS"
    assert store["prod-001"]["product_sold_count"] == 91
    assert store["prod-001"]["archived_reason"] == "Legacy/stale row."


async def test_unarchive_product_restores_active_status(monkeypatch):
    store = {
        "prod-001": _product(
            lifecycle_status="ARCHIVED",
            archived_at="2026-05-16T12:00:00Z",
            archived_reason="Legacy row",
        )
    }
    _wire_crud(monkeypatch, store)

    result = await svc.unarchive_product(
        "prod-001",
        reason="Restore for review.",
        confirmation_phrase="UNARCHIVE_PRODUCT",
    )

    assert result["lifecycle_status"] == "ACTIVE"
    assert store["prod-001"]["unarchived_reason"] == "Restore for review."


async def test_delete_test_row_blocks_normal_products(monkeypatch):
    store = {"prod-001": _product(raw_product_title="Atlas Product")}
    _wire_crud(monkeypatch, store)

    with pytest.raises(HTTPException) as exc:
        await svc.delete_test_row(
            "prod-001",
            reason="cleanup",
            confirmation_phrase="DELETE_TEST_ROW_ONLY",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "TEST_ROW_DELETE_FORBIDDEN"


async def test_delete_test_row_allows_non_fastmoss_test_suffix_only(monkeypatch):
    store = {
        "prod-001": _product(
            raw_product_title="PR59_RUNTIME_TEST_DO_NOT_USE",
            product_display_name="PR59_RUNTIME_TEST_DO_NOT_USE",
            product_short_name="PR59_RUNTIME_TEST_DO_NOT_USE",
        )
    }
    _wire_crud(monkeypatch, store)

    result = await svc.delete_test_row(
        "prod-001",
        reason="cleanup",
        confirmation_phrase="DELETE_TEST_ROW_ONLY",
    )

    assert result["deleted"] is True
    assert result["lifecycle_status"] == "DELETED_TEST_ONLY"
    assert "prod-001" not in store


async def test_lifecycle_payload_exposes_capabilities(monkeypatch):
    store = {
        "prod-001": _product(raw_product_title="PR59_RUNTIME_TEST_DO_NOT_USE"),
        "prod-002": _product(id="prod-002", source="FASTMOSS", lifecycle_status="ARCHIVED"),
    }
    _wire_crud(monkeypatch, store)

    active = await svc.get_product_lifecycle("prod-001")
    archived = await svc.get_product_lifecycle("prod-002")

    assert active["can_archive"] is True
    assert active["can_delete_test_only"] is True
    assert archived["can_unarchive"] is True
    assert archived["lifecycle_status"] == "ARCHIVED"
