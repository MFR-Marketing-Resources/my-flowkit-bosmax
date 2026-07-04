"""Contract for the Product Truth Gateway endpoint GET
/api/products/catalog-state/{identifier} — the one read model every surface
can call to agree on a product's lifecycle state."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.products import router as products_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    return app


def test_catalog_state_reports_reference_only(monkeypatch):
    async def fake_get_product(pid):
        return None

    async def fake_get_bulk_queue_row(rid):
        return None

    async def fake_list_products(**kwargs):
        return []

    async def fake_refs(limit=500):
        return [{
            "id": "fastmoss-ref:zzz999",
            "source": "FASTMOSS",
            "source_lane": "FASTMOSS_REFERENCE",
            "reference_only": True,
        }]

    monkeypatch.setattr("agent.db.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_row", fake_get_bulk_queue_row)
    monkeypatch.setattr("agent.db.crud.list_products", fake_list_products)
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        fake_refs,
    )

    client = TestClient(_build_app())
    resp = client.get("/api/products/catalog-state/fastmoss-ref:zzz999")

    assert resp.status_code == 200
    body = resp.json()
    assert body["product_state"] == "REFERENCE_ONLY"
    assert body["reference_only"] is True
    assert body["production_allowed"] is False
    assert body["preview_resolvable"] is False


def test_catalog_state_reports_approved_canonical_with_authority(monkeypatch):
    product = {
        "id": "prod-uuid-1",
        "source": "MANUAL",
        "mapping_source": "FASTMOSS_PROMOTED",
        "fastmoss_reference_id": "fastmoss-ref:linked",
        "claim_risk_level": "LOW",
    }

    async def fake_get_product(pid):
        return product if pid == "prod-uuid-1" else None

    async def fake_list_products(**kwargs):
        return [product]

    monkeypatch.setattr("agent.db.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.db.crud.list_products", fake_list_products)

    client = TestClient(_build_app())
    resp = client.get("/api/products/catalog-state/prod-uuid-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["product_state"] == "APPROVED_CANONICAL"
    assert body["canonical_status"] == "CANONICAL"
    assert body["product_id"] == "prod-uuid-1"
    assert body["reference_id"] == "fastmoss-ref:linked"
    assert body["production_allowed"] is True
    # Authority reads the same product table -> cannot silently disagree.
    assert body["authority_context_available"] is True


def test_products_list_annotates_every_row_with_catalog_state(monkeypatch):
    canonical = {
        "id": "prod-canon-1",
        "source": "MANUAL",
        "reference_only": False,
        "fastmoss_reference_id": "fastmoss-ref:link1",
        "product_display_name": "Canon 1",
        "raw_product_title": "Canon 1",
        "updated_at": "2026-05-01T00:00:00Z",
        "created_at": "2026-05-01T00:00:00Z",
    }
    reference = {
        "id": "fastmoss-ref:ann1",
        "source": "FASTMOSS",
        "source_lane": "FASTMOSS_REFERENCE",
        "reference_only": True,
        "product_display_name": "Ref 1",
        "raw_product_title": "Ref 1",
        "updated_at": "2026-05-01T00:00:00Z",
        "created_at": "2026-05-01T00:00:00Z",
    }

    async def fake_list_products(**kwargs):
        return [canonical]

    async def fake_enrich(product):
        return product

    async def fake_refs(limit=500):
        return [reference]

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products._enrich_product", fake_enrich)
    monkeypatch.setattr("agent.api.products.list_fastmoss_reference_products", fake_refs)

    client = TestClient(_build_app())
    body = client.get("/api/products?limit=50").json()
    by_id = {item["id"]: item for item in body["items"]}

    assert by_id["prod-canon-1"]["catalog_state"]["product_state"] == "APPROVED_CANONICAL"
    assert by_id["prod-canon-1"]["catalog_state"]["production_allowed"] is True
    assert by_id["fastmoss-ref:ann1"]["catalog_state"]["product_state"] == "REFERENCE_ONLY"
    assert by_id["fastmoss-ref:ann1"]["catalog_state"]["production_allowed"] is False


def test_catalog_state_unknown_id_fails_closed(monkeypatch):
    async def none_(*a, **k):
        return None

    async def empty(*a, **k):
        return []

    monkeypatch.setattr("agent.db.crud.get_product", none_)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_row", none_)
    monkeypatch.setattr("agent.db.crud.list_products", empty)
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        empty,
    )

    client = TestClient(_build_app())
    resp = client.get("/api/products/catalog-state/nope-nope")
    assert resp.status_code == 200
    assert resp.json()["product_state"] == "PRODUCT_CONTEXT_NOT_FOUND"
