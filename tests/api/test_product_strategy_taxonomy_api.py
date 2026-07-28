from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router as creative_router
from agent.api.products import router as products_router
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTaxonomyBackfillResponse,
)
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
)


def _taxonomy(**overrides) -> ProductStrategyTaxonomy:
    payload = {
        "product_id": "p1",
        "taxonomy_version": "product_strategy_taxonomy_v1",
        "product_fingerprint": "fingerprint",
        "cluster": "beauty_makeup",
        "product_type_group": "lipstick_lip_tint",
        "matched_scene_strategy_id": "LIP_COLOR",
        "scene_coverage_status": "COVERED",
        "fallback_used": False,
        "specific_strategy": True,
        "classification_confidence": "HIGH",
        "review_status": "VERIFIED",
        "consumer_status": "READY",
        "authority_source": "MANUAL_OVERRIDE",
        "materialization_status": "MATERIALIZED",
        "review_reasons": [],
        "is_stale": False,
    }
    payload.update(overrides)
    return ProductStrategyTaxonomy.model_validate(payload)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    app.include_router(creative_router, prefix="/api")
    return TestClient(app)


def test_product_taxonomy_readback_and_verified_gate(monkeypatch):
    async def fake_read(product_id):
        assert product_id == "p1"
        return _taxonomy()

    async def fake_verified(product_id):
        assert product_id == "p1"
        return _taxonomy(authority_source="MANUAL_OVERRIDE")

    monkeypatch.setattr(
        "agent.api.products.get_product_strategy_taxonomy_read_model",
        fake_read,
    )
    monkeypatch.setattr(
        "agent.api.products.require_verified_product_strategy_taxonomy",
        fake_verified,
    )

    regular = _client().get("/api/products/strategy-taxonomy/p1")
    verified = _client().get(
        "/api/products/strategy-taxonomy/p1",
        params={"require_verified": "true"},
    )

    assert regular.status_code == 200
    assert regular.json()["cluster"] == "beauty_makeup"
    assert verified.status_code == 200
    assert verified.json()["authority_source"] == "MANUAL_OVERRIDE"


def test_product_catalog_items_include_taxonomy_contract(monkeypatch):
    product = {
        "id": "p1",
        "source": "MANUAL",
        "raw_product_title": "Velvet Lipstick",
        "product_display_name": "Velvet Lipstick",
        "product_short_name": "Velvet Lipstick",
        "lifecycle_status": "ACTIVE",
    }

    async def fake_list_products(**kwargs):
        return [product]

    async def fake_enrich(item):
        return dict(item)

    async def fake_merge(items, **kwargs):
        return items

    async def fake_refresh(item):
        return item

    async def fake_attach(items):
        return [{**item, "strategy_taxonomy": _taxonomy().model_dump()} for item in items]

    monkeypatch.setattr("agent.api.products.crud.list_products", fake_list_products)
    monkeypatch.setattr("agent.api.products._enrich_product_cached", fake_enrich)
    monkeypatch.setattr("agent.api.products._merge_catalog_products", fake_merge)
    monkeypatch.setattr(
        "agent.api.products._refresh_claim_safe_product_row_if_needed",
        fake_refresh,
    )
    monkeypatch.setattr(
        "agent.api.products.attach_product_strategy_taxonomies",
        fake_attach,
    )

    response = _client().get("/api/products", params={"limit": 50})
    assert response.status_code == 200
    assert (
        response.json()["items"][0]["strategy_taxonomy"]["product_type_group"]
        == "lipstick_lip_tint"
    )


def test_unverified_copy_contract_returns_conflict(monkeypatch):
    async def fake_verified(product_id):
        raise ProductStrategyTaxonomyError("TAXONOMY_NOT_VERIFIED")

    monkeypatch.setattr(
        "agent.api.products.require_verified_product_strategy_taxonomy",
        fake_verified,
    )
    response = _client().get(
        "/api/products/strategy-taxonomy/p1",
        params={"require_verified": "true"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "TAXONOMY_NOT_VERIFIED"


def test_backfill_defaults_to_dry_run_and_requires_explicit_service_apply(
    monkeypatch,
):
    captured = {}

    async def fake_backfill(request):
        captured["request"] = request
        return ProductStrategyTaxonomyBackfillResponse(
            dry_run=request.dry_run,
            mutation_performed=False,
            product_count=443,
            planned_insert_count=443,
            planned_update_count=0,
            unchanged_count=0,
            preserved_manual_override_count=0,
            verified_count=0,
            review_required_count=443,
            coverage_counts={
                "COVERED": 332,
                "PARTIAL": 34,
                "FALLBACK_ONLY": 77,
            },
            cluster_counts={"beauty_makeup": 12},
            review_reason_counts={"GENERIC_UNCLASSIFIED": 77},
            sample_review_required=[],
            confirmation_required="MATERIALIZE_PRODUCT_STRATEGY_TAXONOMY",
        )

    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.run_product_strategy_taxonomy_backfill",
        fake_backfill,
    )
    response = _client().post(
        "/api/creative-intelligence/product-strategy-taxonomy/backfill",
        json={},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["mutation_performed"] is False
    assert captured["request"].confirm_apply is None


def test_admin_review_contract_surfaces_stale_fingerprint(monkeypatch):
    async def fake_review(product_id, request):
        assert product_id == "p1"
        assert request.reviewer_id == "admin-1"
        raise ProductStrategyTaxonomyError("STALE_PRODUCT_FINGERPRINT")

    monkeypatch.setattr(
        "agent.api.products.review_product_strategy_taxonomy",
        fake_review,
    )
    response = _client().post(
        "/api/products/strategy-taxonomy/p1/review",
        json={
            "expected_product_fingerprint": "old",
            "cluster": "beauty_makeup",
            "product_type_group": "lipstick_lip_tint",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "COVERED",
            "review_status": "VERIFIED",
            "reviewer_id": "admin-1",
            "reviewer_note": "Verified.",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "STALE_PRODUCT_FINGERPRINT"
