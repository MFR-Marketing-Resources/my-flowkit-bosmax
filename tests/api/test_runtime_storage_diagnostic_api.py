"""Contract for GET /api/operator/runtime-storage-status.

The wiring audit could not prove which database the live backend was bound to
(live API showed zero products while a repo-local DB held hundreds). This
endpoint runs inside the live process and reports the effective storage path plus
live row counts, so an operator can prove/refute the binding. These tests lock
that it reports enough binding data and surfaces the empty-storage warning."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.operator import router as operator_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(operator_router)
    return app


def _patch_counts(monkeypatch, *, products, manual, queue_total):
    async def fake_count_products(source=None, query=None):
        return manual if source == "MANUAL" else products

    async def fake_queue_stats():
        return {"total": queue_total, "by_status": {}, "by_risk": {}}

    monkeypatch.setattr("agent.db.crud.count_products", fake_count_products)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_stats", fake_queue_stats)


def test_runtime_storage_status_reports_binding_fields(monkeypatch):
    _patch_counts(monkeypatch, products=508, manual=210, queue_total=298)

    client = TestClient(_build_app())
    resp = client.get("/api/operator/runtime-storage-status")

    assert resp.status_code == 200
    body = resp.json()
    for key in (
        "cwd",
        "base_dir",
        "config_db_path",
        "effective_db_path",
        "product_count",
        "manual_product_count",
        "queue_count",
        "canonical_product_count",
        "authority_context_count_ceiling",
        "authority_context_count",
        "authority_context_count_source",
        "warnings",
        "timestamp",
    ):
        assert key in body, f"missing diagnostic field: {key}"
    assert body["product_count"] == 508
    assert body["manual_product_count"] == 210
    assert body["queue_count"] == 298
    assert body["canonical_product_count"] == 508
    # CEILING is honest (authority builds <= one context per product row).
    assert body["authority_context_count_ceiling"] == 508
    # The REAL authority count is NOT computed unless explicitly requested —
    # it is not overstated as the product count.
    assert body["authority_context_count"] is None
    assert body["authority_context_count_source"] == "NOT_COMPUTED"
    assert isinstance(body["warnings"], list)


def test_runtime_storage_status_warns_on_empty_storage_with_queue(monkeypatch):
    # The exact cross-worktree split the audit hit: queue rows present but zero
    # products in the bound storage.
    _patch_counts(monkeypatch, products=0, manual=0, queue_total=5)

    client = TestClient(_build_app())
    body = client.get("/api/operator/runtime-storage-status").json()

    assert "ACTIVE_STORAGE_HAS_QUEUE_BUT_ZERO_PRODUCTS" in body["warnings"]
    assert "ACTIVE_STORAGE_HAS_ZERO_MANUAL_PRODUCTS" in body["warnings"]
