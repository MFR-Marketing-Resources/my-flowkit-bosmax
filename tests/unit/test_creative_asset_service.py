from pathlib import Path

import pytest

from agent.models.creative_asset import CreativeAssetCreateRequest, CreativeAssetRecord
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


@pytest.mark.asyncio
async def test_avatar_asset_index_marks_missing_local_file_as_missing_asset(monkeypatch):
    async def fake_list_creative_assets(**kwargs):
        return [
            CreativeAssetRecord(
                asset_id="ca_missing_avatar",
                semantic_role="CHARACTER_REFERENCE",
                display_name="Avatar Missing",
                description="AVATAR_CODE:BOS_F_TEST_01 generated from avatar registry PromptV1 via IMG lane",
                source_type="GENERATED_IMAGE",
                storage_kind="LOCAL_FILE",
                preview_url="/api/creative-assets/ca_missing_avatar/preview",
                download_url="/api/creative-assets/ca_missing_avatar/download",
                media_id="m_missing",
                local_file_path="C:/does/not/exist.jpg",
                avatar_code="BOS_F_TEST_01",
                asset_lifecycle="CANONICAL_AVATAR_ASSET",
                retention_policy="PERSISTENT",
                is_reusable=True,
                is_canonical=True,
                status="ACTIVE",
                created_at="2026-07-03T00:00:00Z",
                updated_at="2026-07-03T00:00:00Z",
            )
        ]

    monkeypatch.setattr(
        creative_asset_service,
        "list_creative_assets",
        fake_list_creative_assets,
    )

    result = await creative_asset_service.list_avatar_asset_index()

    assert result["BOS_F_TEST_01"]["retrievable"] is False
    assert result["BOS_F_TEST_01"]["avatar_status"] == "MISSING_ASSET"


@pytest.mark.asyncio
async def test_image_library_includes_old_canonical_avatar_asset_and_matches_avatar_index(
    tmp_path,
    monkeypatch,
):
    avatar_file = tmp_path / "avatar.jpg"
    avatar_file.write_bytes(b"avatar")
    avatar_asset = CreativeAssetRecord(
        asset_id="ca_avatar_001",
        semantic_role="CHARACTER_REFERENCE",
        display_name="Alya - BOS_F_ALYA_01",
        description="AVATAR_CODE:BOS_F_ALYA_01 generated from avatar registry PromptV1 via IMG lane",
        source_type="GENERATED_IMAGE",
        storage_kind="LOCAL_FILE",
        preview_url="/api/creative-assets/ca_avatar_001/preview",
        download_url="/api/creative-assets/ca_avatar_001/download",
        media_id="media_avatar_001",
        local_file_path=str(avatar_file),
        avatar_code="BOS_F_ALYA_01",
        asset_lifecycle="CANONICAL_AVATAR_ASSET",
        retention_policy="PERSISTENT",
        is_reusable=True,
        is_canonical=True,
        status="ACTIVE",
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )

    async def fake_generated_artifacts(limit=50, mode=None, kind=None):
        return []

    async def fake_purge(retention_hours=48):
        return {"purged_rows": 0, "purged_files": 0}

    async def fake_list_creative_assets(**kwargs):
        return [avatar_asset]

    monkeypatch.setattr(
        creative_asset_service.crud,
        "list_generated_artifacts",
        fake_generated_artifacts,
    )
    monkeypatch.setattr(
        creative_asset_service.crud,
        "purge_expired_artifacts",
        fake_purge,
    )
    monkeypatch.setattr(
        creative_asset_service,
        "list_creative_assets",
        fake_list_creative_assets,
    )

    library = await creative_asset_service.list_image_library_items(limit=20)
    avatar_index = await creative_asset_service.list_avatar_asset_index()

    assert library["items"][0]["asset_lifecycle"] == "CANONICAL_AVATAR_ASSET"
    assert library["items"][0]["retention_policy"] == "PERSISTENT"
    assert library["items"][0]["expires_at"] is None
    assert library["items"][0]["source_asset_id"] == "ca_avatar_001"
    assert library["items"][0]["avatar_code"] == "BOS_F_ALYA_01"
    assert avatar_index["BOS_F_ALYA_01"]["asset_id"] == library["items"][0]["source_asset_id"]


def test_build_resolved_workspace_asset_keeps_preview_and_download_for_canonical_avatar():
    asset = CreativeAssetRecord(
        asset_id="ca_avatar_usable",
        semantic_role="CHARACTER_REFERENCE",
        display_name="Alya - BOS_F_ALYA_02",
        description="AVATAR_CODE:BOS_F_ALYA_02 generated from avatar registry PromptV1 via IMG lane",
        source_type="GENERATED_IMAGE",
        storage_kind="LOCAL_FILE",
        preview_url="/api/creative-assets/ca_avatar_usable/preview",
        download_url="/api/creative-assets/ca_avatar_usable/download",
        media_id="media_avatar_usable",
        local_file_path="C:/tmp/avatar_usable.jpg",
        avatar_code="BOS_F_ALYA_02",
        asset_lifecycle="CANONICAL_AVATAR_ASSET",
        retention_policy="PERSISTENT",
        is_reusable=True,
        is_canonical=True,
        status="ACTIVE",
        created_at="2026-07-03T00:00:00Z",
        updated_at="2026-07-03T00:00:00Z",
    )

    resolved = creative_asset_service.build_resolved_workspace_asset(
        asset=asset,
        slot_key="subject",
    )

    assert resolved["preview_url"] == "/api/creative-assets/ca_avatar_usable/preview"
    assert resolved["download_url"] == "/api/creative-assets/ca_avatar_usable/download"
    assert resolved["media_id"] == "media_avatar_usable"
