from pathlib import Path

import pytest

from agent.models.creative_asset import CreativeAssetCreateRequest
from agent.services import creative_asset_service


@pytest.mark.asyncio
async def test_create_creative_asset_upload_persists_local_preview(tmp_path, monkeypatch):
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {
            **kwargs,
            "description": kwargs["description"],
            "created_at": "2026-05-18T00:00:00Z",
            "updated_at": "2026-05-18T00:00:00Z",
        }

    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        creative_asset_service.crud,
        "create_creative_asset",
        fake_create,
    )

    result = await creative_asset_service.create_creative_asset(
        CreativeAssetCreateRequest(
            semantic_role="CHARACTER_REFERENCE",
            display_name="Creator A",
            description="UGC creator",
            image_base64="data:image/png;base64,aGVsbG8=",
            file_name="creator.png",
            allowed_modes=["I2V"],
            engine_slot_eligibility=["scene"],
        )
    )

    assert result.asset_id.startswith("ca_")
    assert result.preview_url == f"/api/creative-assets/{result.asset_id}/preview"
    assert result.download_url == f"/api/creative-assets/{result.asset_id}/download"
    assert Path(captured["local_file_path"]).exists()
    assert captured["storage_kind"] == "LOCAL_FILE"


@pytest.mark.asyncio
async def test_list_creative_assets_respects_mode_and_slot_filters(monkeypatch):
    async def fake_list(**kwargs):
        return [
            {
                "asset_id": "ca_character",
                "semantic_role": "CHARACTER_REFERENCE",
                "display_name": "Creator A",
                "description": None,
                "source_type": "UPLOAD",
                "storage_kind": "LOCAL_FILE",
                "preview_url": "/api/creative-assets/ca_character/preview",
                "download_url": "/api/creative-assets/ca_character/download",
                "media_id": None,
                "local_file_path": "C:/tmp/creator.png",
                "remote_source_url": None,
                "product_id": None,
                "category": None,
                "silo": None,
                "product_type": None,
                "allowed_modes": '["I2V"]',
                "engine_slot_eligibility": '["scene"]',
                "mode_a_metadata_handoff": None,
                "visual_dna_summary": None,
                "character_dna": None,
                "scene_context_dna": None,
                "style_mood_dna": None,
                "source_prompt_fingerprint": None,
                "source_workspace_execution_package_id": None,
                "source_prompt_package_snapshot_id": None,
                "status": "ACTIVE",
                "created_at": "2026-05-18T00:00:00Z",
                "updated_at": "2026-05-18T00:00:00Z",
            },
            {
                "asset_id": "ca_style",
                "semantic_role": "STYLE_REFERENCE",
                "display_name": "Style A",
                "description": None,
                "source_type": "UPLOAD",
                "storage_kind": "LOCAL_FILE",
                "preview_url": "/api/creative-assets/ca_style/preview",
                "download_url": "/api/creative-assets/ca_style/download",
                "media_id": None,
                "local_file_path": "C:/tmp/style.png",
                "remote_source_url": None,
                "product_id": None,
                "category": None,
                "silo": None,
                "product_type": None,
                "allowed_modes": '["IMG"]',
                "engine_slot_eligibility": '["style"]',
                "mode_a_metadata_handoff": None,
                "visual_dna_summary": None,
                "character_dna": None,
                "scene_context_dna": None,
                "style_mood_dna": None,
                "source_prompt_fingerprint": None,
                "source_workspace_execution_package_id": None,
                "source_prompt_package_snapshot_id": None,
                "status": "ACTIVE",
                "created_at": "2026-05-18T00:00:00Z",
                "updated_at": "2026-05-18T00:00:00Z",
            },
        ]

    monkeypatch.setattr(creative_asset_service.crud, "list_creative_assets", fake_list)

    items = await creative_asset_service.list_creative_assets(
        allowed_mode="I2V",
        engine_slot="scene",
    )

    assert len(items) == 1
    assert items[0].asset_id == "ca_character"


@pytest.mark.asyncio
async def test_create_creative_asset_requires_remote_source_for_remote_url():
    with pytest.raises(ValueError, match="REMOTE_SOURCE_URL_REQUIRED"):
        await creative_asset_service.create_creative_asset(
            CreativeAssetCreateRequest(
                semantic_role="STYLE_REFERENCE",
                display_name="Style A",
                storage_kind="REMOTE_URL",
                source_type="REMOTE_URL",
            )
        )


@pytest.mark.asyncio
async def test_validate_selectable_asset_blocks_archived_and_semantic_mismatch(monkeypatch):
    async def fake_get(asset_id: str):
        return creative_asset_service.CreativeAssetRecord(
            asset_id=asset_id,
            semantic_role="STYLE_REFERENCE",
            display_name="Style A",
            description=None,
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            preview_url="/api/creative-assets/style/preview",
            download_url="/api/creative-assets/style/download",
            media_id=None,
            local_file_path="C:/tmp/style.png",
            remote_source_url=None,
            product_id=None,
            category=None,
            silo=None,
            product_type=None,
            allowed_modes=["I2V"],
            engine_slot_eligibility=["style"],
            mode_a_metadata_handoff=None,
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            status="ARCHIVED",
            created_at="2026-05-18T00:00:00Z",
            updated_at="2026-05-18T00:00:00Z",
        )

    monkeypatch.setattr(creative_asset_service, "get_creative_asset", fake_get)

    result = await creative_asset_service.validate_selectable_asset(
        "ca_style",
        semantic_role="CHARACTER_REFERENCE",
        allowed_mode="I2V",
        engine_slot="scene",
    )

    assert result.valid is False
    assert "ASSET_ARCHIVED" in result.blockers
    assert "SEMANTIC_ROLE_MISMATCH" in result.blockers
