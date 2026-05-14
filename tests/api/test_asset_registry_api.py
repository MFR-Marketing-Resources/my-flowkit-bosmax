from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.asset_registry import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_api_routes_are_read_only_and_return_dropdown_ready_shapes(monkeypatch):
    async def fake_list_characters():
        return []

    async def fake_list_products(*args, **kwargs):
        return [
            {
                "id": "prod-001",
                "scene_context": "Premium vanity table.",
                "camera_style": "Medium shot.",
                "camera_behavior": "Slow push-in.",
                "section_9_overlay_hint": "Minimal lower-third.",
                "product_display_name": "Atlas Bottle",
                "product_short_name": "Atlas",
                "raw_product_title": "Atlas Bottle",
                "category": "Beauty",
                "subcategory": "Skincare",
                "type": "Bottle",
                "product_type": "Serum",
                "claim_risk_level": "LOW",
            }
        ]

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_characters", fake_list_characters)
    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    client = TestClient(_build_app())

    catalog_response = client.get("/api/asset-registry/catalog")
    assets_response = client.get("/api/asset-registry/assets", params={"asset_type": "PRODUCT_REFERENCE"})
    detail_response = client.get("/api/asset-registry/assets/product:prod-001")
    resolve_response = client.post(
        "/api/asset-registry/resolve-selection",
        json={"selected_assets": {"LANGUAGE": "language:Malay"}},
    )
    compatibility_response = client.post(
        "/api/asset-registry/compatibility-check",
        json={"selected_assets": {"LANGUAGE": "language:Malay", "PLATFORM": "platform:TikTok"}},
    )

    assert catalog_response.status_code == 200
    catalog_payload = catalog_response.json()
    assert len(catalog_payload["catalog"]) == 15
    assert any(entry["asset_type"] == "CHARACTER" for entry in catalog_payload["catalog"])

    assert assets_response.status_code == 200
    assets_payload = assets_response.json()
    assert assets_payload["asset_type"] == "PRODUCT_REFERENCE"
    assert assets_payload["source_status"] == "DERIVED_FROM_PRODUCT_DATA"
    assert assets_payload["options"][0]["asset_id"] == "product:prod-001"
    assert assets_payload["options"][0]["is_canonical"] is False

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["asset"]["asset_id"] == "product:prod-001"
    assert detail_payload["asset"]["source_status"] == "DERIVED_FROM_PRODUCT_DATA"

    assert resolve_response.status_code == 200
    resolve_payload = resolve_response.json()
    assert resolve_payload["selection_status"] == "WARN"
    assert "FULL_TUPLE_LEGALITY_NOT_PROVEN" in resolve_payload["warnings"]

    assert compatibility_response.status_code == 200
    compatibility_payload = compatibility_response.json()
    assert compatibility_payload["compatibility_status"] == "NOT_VERIFIED"
    assert "FULL_TUPLE_LEGALITY_NOT_PROVEN" in compatibility_payload["warnings"]


def test_api_routes_do_not_expose_write_crud_or_runtime_execution(monkeypatch):
    async def fake_list_characters():
        return []

    async def fake_list_products(*args, **kwargs):
        return []

    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_characters", fake_list_characters)
    monkeypatch.setattr("agent.services.asset_registry_service.crud.list_products", fake_list_products)

    app = _build_app()
    client = TestClient(app)
    methods = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/api/asset-registry")
    }

    assert ("/api/asset-registry/catalog", "GET") in methods
    assert ("/api/asset-registry/assets", "GET") in methods
    assert ("/api/asset-registry/assets/{asset_id}", "GET") in methods
    assert ("/api/asset-registry/resolve-selection", "POST") in methods
    assert ("/api/asset-registry/compatibility-check", "POST") in methods
    assert all(method not in {"PUT", "PATCH", "DELETE"} for _, method in methods)

    failure = client.post(
        "/api/asset-registry/resolve-selection",
        json={"selected_assets": {"LANGUAGE": "language:Malay"}, "canonical_registry_write": True},
    )
    payload = failure.json()

    assert failure.status_code == 200
    assert payload["selection_status"] == "FAIL"
    assert payload["errors"] == ["CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_8"]
