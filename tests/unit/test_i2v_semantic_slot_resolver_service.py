import pytest

from agent.models.i2v_semantic_slot_resolver import I2VSemanticSlotResolverRequest
from agent.services.i2v_semantic_slot_resolver_service import (
    resolve_i2v_semantic_slots,
)


@pytest.mark.asyncio
async def test_i2v_resolver_maps_product_character_scene_recipe(monkeypatch):
    async def fake_package(product_id: str, mode: str):
        return {
            "product_id": product_id,
            "asset_slots": [
                {
                    "slot_key": "subject",
                    "resolved_asset": {
                        "asset_id": f"product-image:{product_id}:subject",
                        "asset_fingerprint": "asset_product_subject",
                        "slot_key": "subject",
                        "asset_source": "PRODUCT_IMAGE_URL",
                        "label": "Product image",
                        "file_name": "product.jpg",
                        "preview_url": "https://example.com/product.jpg",
                        "download_url": "https://example.com/product.jpg",
                        "media_id": None,
                        "local_image_path_present": False,
                        "remote_image_url_present": True,
                    },
                }
            ],
        }

    async def fake_validate(asset_id: str, **kwargs):
        labels = {
            "ca_character": "Creator A",
            "ca_scene": "Scene A",
            "ca_style": "Style A",
        }
        return type(
            "ValidationResult",
            (),
            {
                "valid": True,
                "blockers": [],
                "warnings": [],
                "asset": {
                    "ca_character": type(
                        "Asset",
                        (),
                        {
                            "asset_id": "ca_character",
                            "display_name": labels["ca_character"],
                            "semantic_role": "CHARACTER_REFERENCE",
                            "status": "ACTIVE",
                            "allowed_modes": ["I2V"],
                            "engine_slot_eligibility": ["scene"],
                            "local_file_path": "C:/tmp/creator.png",
                            "remote_source_url": None,
                            "preview_url": "/api/creative-assets/ca_character/preview",
                            "download_url": "/api/creative-assets/ca_character/download",
                            "media_id": None,
                            "source_type": "UPLOAD",
                        },
                    )(),
                    "ca_scene": type(
                        "Asset",
                        (),
                        {
                            "asset_id": "ca_scene",
                            "display_name": labels["ca_scene"],
                            "semantic_role": "SCENE_CONTEXT_REFERENCE",
                            "status": "ACTIVE",
                            "allowed_modes": ["I2V"],
                            "engine_slot_eligibility": ["style"],
                            "local_file_path": "C:/tmp/scene.png",
                            "remote_source_url": None,
                            "preview_url": "/api/creative-assets/ca_scene/preview",
                            "download_url": "/api/creative-assets/ca_scene/download",
                            "media_id": None,
                            "source_type": "UPLOAD",
                        },
                    )(),
                    "ca_style": type(
                        "Asset",
                        (),
                        {
                            "asset_id": "ca_style",
                            "display_name": labels["ca_style"],
                            "semantic_role": "STYLE_REFERENCE",
                            "status": "ACTIVE",
                            "allowed_modes": ["I2V"],
                            "engine_slot_eligibility": ["style"],
                            "local_file_path": "C:/tmp/style.png",
                            "remote_source_url": None,
                            "preview_url": "/api/creative-assets/ca_style/preview",
                            "download_url": "/api/creative-assets/ca_style/download",
                            "media_id": None,
                            "source_type": "UPLOAD",
                        },
                    )(),
                }[asset_id],
            },
        )()

    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.get_approved_product_package",
        fake_package,
    )
    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.validate_selectable_asset",
        fake_validate,
    )

    result = await resolve_i2v_semantic_slots(
        I2VSemanticSlotResolverRequest(
            product_id="prod_001",
            character_reference_asset_id="ca_character",
            scene_context_reference_asset_id="ca_scene",
            recipe_id="PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
        )
    )

    assert result.blockers == []
    assert result.engine_slot_mapping["subject"] == "product_reference"
    assert result.engine_slot_mapping["scene"] == "character_reference"
    assert result.engine_slot_mapping["style"] == "scene_context_reference"
    assert result.resolved_assets[1].slot_key == "scene"
    assert result.semantic_roles["product_reference"] == "product-image:prod_001:subject"


@pytest.mark.asyncio
async def test_i2v_resolver_blocks_when_style_recipe_missing_style(monkeypatch):
    async def fake_package(product_id: str, mode: str):
        return {
            "product_id": product_id,
            "asset_slots": [
                {
                    "slot_key": "subject",
                    "resolved_asset": {
                        "asset_id": f"product-image:{product_id}:subject",
                        "asset_fingerprint": "asset_product_subject",
                        "slot_key": "subject",
                        "asset_source": "PRODUCT_IMAGE_URL",
                        "label": "Product image",
                        "file_name": "product.jpg",
                        "preview_url": "https://example.com/product.jpg",
                        "download_url": "https://example.com/product.jpg",
                        "media_id": None,
                        "local_image_path_present": False,
                        "remote_image_url_present": True,
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.get_approved_product_package",
        fake_package,
    )

    result = await resolve_i2v_semantic_slots(
        I2VSemanticSlotResolverRequest(
            product_id="prod_001",
            scene_context_reference_asset_id="ca_scene",
            recipe_id="STYLE_MOOD_DOMINANT_PRODUCT_SPOT",
        )
    )

    assert "MISSING_STYLE_REFERENCE" in result.blockers


@pytest.mark.asyncio
async def test_i2v_resolver_propagates_semantic_mismatch_blocker(monkeypatch):
    async def fake_package(product_id: str, mode: str):
        return {
            "product_id": product_id,
            "asset_slots": [
                {
                    "slot_key": "subject",
                    "resolved_asset": {
                        "asset_id": f"product-image:{product_id}:subject",
                        "asset_fingerprint": "asset_product_subject",
                        "slot_key": "subject",
                        "asset_source": "PRODUCT_IMAGE_URL",
                        "label": "Product image",
                        "file_name": "product.jpg",
                        "preview_url": "https://example.com/product.jpg",
                        "download_url": "https://example.com/product.jpg",
                        "media_id": None,
                        "local_image_path_present": False,
                        "remote_image_url_present": True,
                    },
                }
            ],
        }

    async def fake_validate(asset_id: str, **kwargs):
        return type(
            "ValidationResult",
            (),
            {
                "valid": False,
                "blockers": ["SEMANTIC_ROLE_MISMATCH"],
                "warnings": [],
                "asset": None,
            },
        )()

    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.get_approved_product_package",
        fake_package,
    )
    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.validate_selectable_asset",
        fake_validate,
    )

    result = await resolve_i2v_semantic_slots(
        I2VSemanticSlotResolverRequest(
            product_id="prod_001",
            character_reference_asset_id="ca_style",
            scene_context_reference_asset_id="ca_scene",
        )
    )

    assert "CHARACTER_REFERENCE_SEMANTIC_ROLE_MISMATCH" in result.blockers


@pytest.mark.asyncio
async def test_i2v_resolver_blocks_pending_reference_reuse(monkeypatch):
    async def fake_package(product_id: str, mode: str):
        return {
            "product_id": product_id,
            "asset_slots": [
                {
                    "slot_key": "subject",
                    "resolved_asset": {
                        "asset_id": f"product-image:{product_id}:subject",
                        "asset_fingerprint": "asset_product_subject",
                        "slot_key": "subject",
                        "asset_source": "PRODUCT_IMAGE_URL",
                        "label": "Product image",
                        "file_name": "product.jpg",
                        "preview_url": "https://example.com/product.jpg",
                        "download_url": "https://example.com/product.jpg",
                        "media_id": None,
                        "local_image_path_present": False,
                        "remote_image_url_present": True,
                    },
                }
            ],
        }

    async def fake_validate(asset_id: str, **kwargs):
        if asset_id == "ca_pending":
            return type(
                "ValidationResult",
                (),
                {
                    "valid": False,
                    "blockers": ["NOT_APPROVED_FOR_REUSE"],
                    "warnings": [],
                    "asset": None,
                },
            )()
        return type(
            "ValidationResult",
            (),
            {
                "valid": True,
                "blockers": [],
                "warnings": [],
                "asset": type(
                    "Asset",
                    (),
                    {
                        "asset_id": asset_id,
                        "display_name": "Scene A",
                        "semantic_role": "SCENE_CONTEXT_REFERENCE",
                        "status": "ACTIVE",
                        "allowed_modes": ["I2V"],
                        "engine_slot_eligibility": ["style"],
                        "local_file_path": "C:/tmp/scene.png",
                        "remote_source_url": None,
                        "preview_url": "/api/creative-assets/ca_scene/preview",
                        "download_url": "/api/creative-assets/ca_scene/download",
                        "media_id": None,
                        "source_type": "UPLOAD",
                    },
                )(),
            },
        )()

    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.get_approved_product_package",
        fake_package,
    )
    monkeypatch.setattr(
        "agent.services.i2v_semantic_slot_resolver_service.validate_selectable_asset",
        fake_validate,
    )

    result = await resolve_i2v_semantic_slots(
        I2VSemanticSlotResolverRequest(
            product_id="prod_001",
            character_reference_asset_id="ca_pending",
            scene_context_reference_asset_id="ca_scene",
        )
    )

    assert "CHARACTER_REFERENCE_NOT_APPROVED_FOR_REUSE" in result.blockers
