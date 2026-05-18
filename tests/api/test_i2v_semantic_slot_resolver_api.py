from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.workspace_packages import router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_i2v_semantic_slot_resolver_api_returns_mapping(monkeypatch):
    async def fake_resolve(request):
        return {
            "mode": "I2V",
            "recipe_id": request.recipe_id,
            "semantic_roles": {
                "product_reference": "product-image:prod_001:subject",
                "character_reference": request.character_reference_asset_id,
                "scene_context_reference": request.scene_context_reference_asset_id,
                "style_reference": request.style_reference_asset_id,
            },
            "engine_slot_mapping": {
                "subject": "product_reference",
                "scene": "character_reference",
                "style": "scene_context_reference",
            },
            "creative_asset_ids": {
                "product_reference": "product-image:prod_001:subject",
                "character_reference": request.character_reference_asset_id,
                "scene_context_reference": request.scene_context_reference_asset_id,
                "style_reference": request.style_reference_asset_id,
            },
            "resolved_assets": [],
            "compiler_context_summary": "Product reference is paired with selected creator and scene context.",
            "warnings": [],
            "blockers": [],
        }

    monkeypatch.setattr(
        "agent.api.workspace_packages.resolve_i2v_semantic_slots",
        fake_resolve,
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/workspace/i2v/resolve-slots",
        json={
            "product_id": "prod_001",
            "recipe_id": "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
            "character_reference_asset_id": "ca_character",
            "scene_context_reference_asset_id": "ca_scene",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_slot_mapping"]["scene"] == "character_reference"
    assert payload["semantic_roles"]["character_reference"] == "ca_character"
