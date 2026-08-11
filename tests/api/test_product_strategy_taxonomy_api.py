from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.creative_intelligence import router as creative_router
from agent.api.products import router as products_router
from agent.db import crud
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTaxonomyBackfillResponse,
    ProductStrategyTypeRegistrySeedRequest,
    ProductStrategyTypeRegistryEntry,
    ProductStrategyTypeRegistryListResponse,
    ProductStrategyTypeRegistrySeedResponse,
)
from agent.services import product_strategy_taxonomy_service as taxonomy_service
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
    ProductStrategyTaxonomyNotFound,
)
from agent.services.copywriting_taxonomy_service import (
    seed_copywriting_taxonomy_registry,
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


@pytest.mark.asyncio
async def test_registry_backed_review_persists_and_api_reads_verified_taxonomy():
    await taxonomy_service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=taxonomy_service.REGISTRY_SEED_CONFIRMATION,
        )
    )
    product = await crud.create_product(
        "Velvet Lipstick",
        source="MANUAL",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
        product_type="Lipstick",
    )
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        preview = await client.get(
            f"/api/products/strategy-taxonomy/{product['id']}"
        )
        current_product = await crud.get_product(product["id"])
        assert preview.json()["product_fingerprint"] == (
            taxonomy_service.product_strategy_fingerprint(current_product)
        ), {
            "preview": preview.json()["product_fingerprint"],
            "current": taxonomy_service.product_strategy_fingerprint(
                current_product
            ),
            "product": current_product,
        }
        reviewed = await client.post(
            f"/api/products/strategy-taxonomy/{product['id']}/review",
            json={
                "expected_product_fingerprint": preview.json()[
                    "product_fingerprint"
                ],
                "cluster": "beauty_makeup",
                "product_type_group": "lipstick_lip_tint",
                "matched_scene_strategy_id": "LIP_COLOR",
                "scene_coverage_status": "COVERED",
                "review_status": "VERIFIED",
                "reviewer_id": "admin-1",
                "reviewer_note": "Registry binding verified.",
            },
        )
        readback = await client.get(
            f"/api/products/strategy-taxonomy/{product['id']}",
            params={"require_verified": "true"},
        )

    assert preview.status_code == 200
    assert reviewed.status_code == 200, reviewed.text
    assert readback.status_code == 200
    assert readback.json()["consumer_status"] == "READY"
    assert readback.json()["authority_source"] == "MANUAL_OVERRIDE"


@pytest.mark.asyncio
async def test_manual_product_patch_persists_source_taxonomy_fields():
    """The product editor persists only a canonical taxonomy selection."""

    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply="SEED_COPYWRITING_TAXONOMY_REGISTRY",
    )

    product = await crud.create_product(
        "Manual Sink Strainer",
        source="MANUAL",
        product_display_name="Manual Sink Strainer",
        product_short_name="Manual Sink Strainer",
    )
    app = FastAPI()
    app.include_router(products_router, prefix="/api")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.patch(
            f"/api/products/{product['id']}",
            json={
                "category": "Toys & Games",
                "subcategory": "Creative Play",
                "type": "3D Scene Sticker Books",
                "copywriting_angle": "operator text is ignored when override is off",
            },
        )

    assert response.status_code == 200, response.text
    stored = await crud.get_product(product["id"])
    assert stored is not None
    assert stored["category"] == "Toys & Games"
    assert stored["subcategory"] == "Creative Play"
    assert stored["type"] == "3D Scene Sticker Books"
    assert stored["copywriting_product_type_code"] == "3d_sticker_book"
    assert stored["copywriting_angle"] == (
        "Creativity-led city-scene storytelling, reusable play, and "
        "screen-free engagement"
    )


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


def test_registry_list_register_and_dry_run_seed_contracts(monkeypatch):
    entry = ProductStrategyTypeRegistryEntry(
        cluster="beauty_makeup",
        product_type_group="custom_palette",
        display_name="Custom Palette",
        matched_scene_strategy_id="LIP_COLOR",
        scene_coverage_status="COVERED",
        registry_status="ACTIVE",
        auto_classification_enabled=False,
        authority_source="MANUAL_REGISTRATION",
        reviewer_id="admin-1",
        reviewer_note="Reviewed binding.",
    )
    captured = {}

    async def fake_list(cluster=None):
        captured["cluster"] = cluster
        return ProductStrategyTypeRegistryListResponse(
            items=[entry],
            clusters=["beauty_makeup"],
            scene_strategy_ids=["GENERIC_FALLBACK", "LIP_COLOR"],
        )

    async def fake_register(request):
        captured["register"] = request
        return entry

    async def fake_seed(request):
        captured["seed"] = request
        return ProductStrategyTypeRegistrySeedResponse(
            dry_run=request.dry_run,
            mutation_performed=False,
            seed_count=30,
            planned_insert_count=30,
            planned_update_count=0,
            unchanged_count=0,
            preserved_manual_registration_count=0,
            active_count=23,
            review_required_count=7,
            confirmation_required="SEED_PRODUCT_STRATEGY_TYPE_REGISTRY",
        )

    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.list_product_strategy_type_registry",
        fake_list,
    )
    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.register_product_strategy_type",
        fake_register,
    )
    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.seed_product_strategy_type_registry",
        fake_seed,
    )

    listed = _client().get(
        "/api/creative-intelligence/product-strategy-type-registry",
        params={"cluster": "beauty_makeup"},
    )
    registered = _client().post(
        "/api/creative-intelligence/product-strategy-type-registry",
        json={
            "cluster": "beauty_makeup",
            "product_type_group": "custom_palette",
            "display_name": "Custom Palette",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "COVERED",
            "registry_status": "ACTIVE",
            "reviewer_id": "admin-1",
            "reviewer_note": "Reviewed binding.",
        },
    )
    seed = _client().post(
        "/api/creative-intelligence/product-strategy-type-registry/seed",
        json={},
    )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["product_type_group"] == "custom_palette"
    assert captured["cluster"] == "beauty_makeup"
    assert registered.status_code == 200
    assert captured["register"].auto_classification_enabled is False
    assert seed.status_code == 200
    assert seed.json()["dry_run"] is True
    assert captured["seed"].confirm_apply is None


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


def test_registry_update_and_delete_routes_map_success(monkeypatch):
    entry = ProductStrategyTypeRegistryEntry(
        cluster="beauty_makeup",
        product_type_group="custom_palette",
        display_name="Renamed Palette",
        matched_scene_strategy_id="LIP_COLOR",
        scene_coverage_status="PARTIAL",
        registry_status="REVIEW_REQUIRED",
        auto_classification_enabled=False,
        authority_source="MANUAL_REGISTRATION",
        reviewer_id="admin-2",
        reviewer_note="Edited binding.",
    )
    captured = {}

    async def fake_update(cluster, product_type_group, request):
        captured["update"] = (cluster, product_type_group, request)
        return entry

    async def fake_delete(cluster, product_type_group):
        captured["delete"] = (cluster, product_type_group)
        return entry

    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.update_product_strategy_type",
        fake_update,
    )
    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.delete_product_strategy_type",
        fake_delete,
    )

    updated = _client().patch(
        "/api/creative-intelligence/product-strategy-type-registry/beauty_makeup/custom_palette",
        json={
            "display_name": "Renamed Palette",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "PARTIAL",
            "registry_status": "REVIEW_REQUIRED",
            "reviewer_id": "admin-2",
            "reviewer_note": "Edited binding.",
        },
    )
    removed = _client().delete(
        "/api/creative-intelligence/product-strategy-type-registry/beauty_makeup/custom_palette"
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "Renamed Palette"
    assert captured["update"][0] == "beauty_makeup"
    assert captured["update"][1] == "custom_palette"
    assert captured["update"][2].registry_status == "REVIEW_REQUIRED"
    assert removed.status_code == 200, removed.text
    assert captured["delete"] == ("beauty_makeup", "custom_palette")


def test_registry_update_not_found_and_delete_seed_guard_map_errors(monkeypatch):
    async def fake_update(cluster, product_type_group, request):
        raise ProductStrategyTaxonomyNotFound("PRODUCT_STRATEGY_TYPE_NOT_FOUND")

    async def fake_delete(cluster, product_type_group):
        raise ProductStrategyTaxonomyError("CANNOT_DELETE_SYSTEM_SEED_ENTRY")

    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.update_product_strategy_type",
        fake_update,
    )
    monkeypatch.setattr(
        "agent.api.creative_intelligence._strategy_taxonomy.delete_product_strategy_type",
        fake_delete,
    )

    not_found = _client().patch(
        "/api/creative-intelligence/product-strategy-type-registry/beauty_makeup/ghost_pair",
        json={
            "display_name": "Ghost",
            "matched_scene_strategy_id": "LIP_COLOR",
            "scene_coverage_status": "COVERED",
            "registry_status": "ACTIVE",
            "reviewer_id": "admin-1",
            "reviewer_note": "note",
        },
    )
    guarded = _client().delete(
        "/api/creative-intelligence/product-strategy-type-registry/beauty_makeup/seed_pair"
    )

    assert not_found.status_code == 404
    assert not_found.json()["detail"] == "PRODUCT_STRATEGY_TYPE_NOT_FOUND"
    assert guarded.status_code == 409
    assert guarded.json()["detail"] == "CANNOT_DELETE_SYSTEM_SEED_ENTRY"


@pytest.mark.asyncio
async def test_registry_crud_update_delete_roundtrip():
    record = {
        "cluster": "beauty_makeup",
        "product_type_group": "crud_roundtrip_pair",
        "display_name": "CRUD Roundtrip",
        "matched_scene_strategy_id": "LIP_COLOR",
        "scene_coverage_status": "COVERED",
        "registry_status": "ACTIVE",
        "auto_classification_enabled": 0,
        "authority_source": "MANUAL_REGISTRATION",
        "reviewer_id": "admin-1",
        "reviewer_note": "seed",
        "reviewed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    created = await crud.create_product_strategy_type_registry_entry(record)
    assert created["display_name"] == "CRUD Roundtrip"

    updated = await crud.update_product_strategy_type_registry_entry(
        "beauty_makeup",
        "crud_roundtrip_pair",
        {
            "display_name": "CRUD Renamed",
            "scene_coverage_status": "PARTIAL",
            "registry_status": "REVIEW_REQUIRED",
            "updated_at": "2026-02-02T00:00:00Z",
        },
    )
    assert updated is not None
    assert updated["display_name"] == "CRUD Renamed"
    assert updated["scene_coverage_status"] == "PARTIAL"
    assert updated["registry_status"] == "REVIEW_REQUIRED"
    # Untouched columns are preserved by the partial update.
    assert updated["matched_scene_strategy_id"] == "LIP_COLOR"

    deleted = await crud.delete_product_strategy_type_registry_entry(
        "beauty_makeup", "crud_roundtrip_pair"
    )
    assert deleted is True
    assert (
        await crud.get_product_strategy_type_registry_entry(
            "beauty_makeup", "crud_roundtrip_pair"
        )
        is None
    )
    # Deleting a missing pair is idempotent and reports False.
    assert (
        await crud.delete_product_strategy_type_registry_entry(
            "beauty_makeup", "crud_roundtrip_pair"
        )
        is False
    )
