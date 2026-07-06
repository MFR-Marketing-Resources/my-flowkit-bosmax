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
async def test_avatar_asset_index_prefers_repaired_retrievable_asset(monkeypatch):
    async def fake_list_creative_assets(**kwargs):
        return [
            CreativeAssetRecord(
                asset_id="ca_avatar_repaired",
                semantic_role="CHARACTER_REFERENCE",
                display_name="Avatar Repaired",
                description="AVATAR_CODE:BOS_F_TEST_02 generated from avatar registry PromptV1 via IMG lane",
                source_type="GENERATED_IMAGE",
                storage_kind="LOCAL_FILE",
                preview_url="/api/creative-assets/ca_avatar_repaired/preview",
                download_url="/api/creative-assets/ca_avatar_repaired/download",
                media_id="m_repaired",
                local_file_path=__file__,
                avatar_code="BOS_F_TEST_02",
                asset_lifecycle="CANONICAL_AVATAR_ASSET",
                retention_policy="PERSISTENT",
                is_reusable=True,
                is_canonical=True,
                status="ACTIVE",
                created_at="2026-07-04T00:00:00Z",
                updated_at="2026-07-04T00:00:00Z",
            ),
            CreativeAssetRecord(
                asset_id="ca_avatar_broken",
                semantic_role="CHARACTER_REFERENCE",
                display_name="Avatar Broken",
                description="AVATAR_CODE:BOS_F_TEST_02 generated from avatar registry PromptV1 via IMG lane",
                source_type="GENERATED_IMAGE",
                storage_kind="LOCAL_FILE",
                preview_url="/api/creative-assets/ca_avatar_broken/preview",
                download_url="/api/creative-assets/ca_avatar_broken/download",
                media_id="m_broken",
                local_file_path="C:/does/not/exist.jpg",
                avatar_code="BOS_F_TEST_02",
                asset_lifecycle="CANONICAL_AVATAR_ASSET",
                retention_policy="PERSISTENT",
                is_reusable=True,
                is_canonical=True,
                status="ACTIVE",
                created_at="2026-07-03T00:00:00Z",
                updated_at="2026-07-03T00:00:00Z",
            ),
        ]

    monkeypatch.setattr(
        creative_asset_service,
        "list_creative_assets",
        fake_list_creative_assets,
    )

    result = await creative_asset_service.list_avatar_asset_index()

    assert result["BOS_F_TEST_02"]["asset_id"] == "ca_avatar_repaired"
    assert result["BOS_F_TEST_02"]["avatar_status"] == "GENERATED"
    assert result["BOS_F_TEST_02"]["retrievable"] is True


def test_audit_creative_asset_remote_url_marks_reference_without_overclaim():
    asset = CreativeAssetRecord(
        asset_id="ca_remote_only",
        semantic_role="STYLE_REFERENCE",
        display_name="Remote Style",
        description="remote image",
        source_type="REMOTE_URL",
        storage_kind="REMOTE_URL",
        preview_url="https://example.com/source.png",
        download_url="https://example.com/source.png",
        media_id=None,
        local_file_path=None,
        remote_source_url="https://example.com/source.png",
        status="ACTIVE",
        created_at="2026-07-04T00:00:00Z",
        updated_at="2026-07-04T00:00:00Z",
    )

    audit = creative_asset_service.audit_creative_asset(asset)

    assert audit["retrievable"] is False
    assert audit["integrity_status"] == "REMOTE_RETRIEVABILITY_UNVERIFIED"
    assert audit["avatar_status"] == "BROKEN_LINK"


def test_normalized_remote_url_asset_does_not_become_generated_from_reference_strings():
    asset = creative_asset_service._normalize_record(
        {
            "asset_id": "ca_remote_normalized",
            "semantic_role": "CHARACTER_REFERENCE",
            "display_name": "Remote Normalized",
            "description": "AVATAR_CODE:BOS_F_REMOTE_01 remote image",
            "source_type": "REMOTE_URL",
            "storage_kind": "REMOTE_URL",
            "preview_url": "/api/creative-assets/ca_remote_normalized/preview",
            "download_url": "/api/creative-assets/ca_remote_normalized/download",
            "media_id": None,
            "local_file_path": None,
            "remote_source_url": "https://example.com/remote-avatar.png",
            "product_id": None,
            "category": None,
            "silo": None,
            "product_type": None,
            "allowed_modes": "[]",
            "engine_slot_eligibility": "[]",
            "mode_a_metadata_handoff": None,
            "visual_dna_summary": None,
            "character_dna": None,
            "scene_context_dna": None,
            "style_mood_dna": None,
            "source_prompt_fingerprint": None,
            "source_workspace_execution_package_id": None,
            "source_prompt_package_snapshot_id": None,
            "asset_subtype": None,
            "generation_recipe_id": None,
            "source_character_asset_id": None,
            "source_scene_asset_id": None,
            "source_style_asset_id": None,
            "contains_rendered_text": 0,
            "approved_for_video_support": 0,
            "approved_for_poster": 0,
            "product_truth_status": None,
            "identity_lock_status": None,
            "scale_truth_status": None,
            "claim_safety_status": None,
            "review_status": "PENDING_REVIEW",
            "asset_lifecycle": "CANONICAL_AVATAR_ASSET",
            "retention_policy": "PERSISTENT",
            "expires_at": None,
            "is_reusable": 1,
            "is_canonical": 1,
            "source_job_id": None,
            "avatar_code": "BOS_F_REMOTE_01",
            "status": "ACTIVE",
            "created_at": "2026-07-04T00:00:00Z",
            "updated_at": "2026-07-04T00:00:00Z",
        }
    )

    audit = creative_asset_service.audit_creative_asset(asset)

    assert asset.preview_url == "https://example.com/remote-avatar.png"
    assert asset.download_url == "https://example.com/remote-avatar.png"
    assert audit["retrievable"] is False
    assert audit["avatar_status"] != "GENERATED"


def test_audit_creative_asset_product_cache_requires_preview_or_download():
    asset = CreativeAssetRecord(
        asset_id="ca_product_cache_only",
        semantic_role="PRODUCT_REFERENCE",
        display_name="Product Cache",
        description="product cache metadata only",
        source_type="PRODUCT_CACHE",
        storage_kind="PRODUCT_IMAGE_CACHE",
        preview_url=None,
        download_url=None,
        media_id=None,
        local_file_path=None,
        remote_source_url=None,
        product_id="prod_123",
        status="ACTIVE",
        created_at="2026-07-04T00:00:00Z",
        updated_at="2026-07-04T00:00:00Z",
    )

    audit = creative_asset_service.audit_creative_asset(asset)

    assert audit["retrievable"] is False
    assert audit["integrity_status"] == "PRODUCT_CACHE_PRODUCT_LINK_ONLY"
    assert audit["avatar_status"] == "GENERATED_METADATA_ONLY"


@pytest.mark.asyncio
async def test_image_library_includes_old_canonical_avatar_asset_and_matches_avatar_index(
    tmp_path,
    monkeypatch,
):
    purge_calls = []
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
        purge_calls.append(retention_hours)
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
    assert purge_calls == [48]


@pytest.mark.asyncio
async def test_image_library_excludes_metadata_only_and_non_library_lifecycle_assets(
    monkeypatch,
):
    async def fake_generated_artifacts(limit=50, mode=None, kind=None):
        return []

    async def fake_purge(retention_hours=48):
        return {"purged_rows": 0, "purged_files": 0}

    async def fake_list_creative_assets(**kwargs):
        return [
            CreativeAssetRecord(
                asset_id="ca_metadata_only",
                semantic_role="STYLE_REFERENCE",
                display_name="Metadata Only",
                description="no preview or download",
                source_type="REMOTE_URL",
                storage_kind="REMOTE_URL",
                preview_url="https://example.com/metadata-only.png",
                download_url="https://example.com/metadata-only.png",
                media_id=None,
                local_file_path=None,
                remote_source_url="https://example.com/metadata-only.png",
                asset_lifecycle="SAVED_REUSABLE_ASSET",
                retention_policy="PERSISTENT",
                status="ACTIVE",
                created_at="2026-07-04T00:00:00Z",
                updated_at="2026-07-04T00:00:00Z",
            ),
            CreativeAssetRecord(
                asset_id="ca_broken_lifecycle",
                semantic_role="CHARACTER_REFERENCE",
                display_name="Broken Lifecycle",
                description="AVATAR_CODE:BOS_F_TEST_03 generated from avatar registry PromptV1 via IMG lane",
                source_type="GENERATED_IMAGE",
                storage_kind="REMOTE_URL",
                preview_url="/api/creative-assets/ca_broken_lifecycle/preview",
                download_url="/api/creative-assets/ca_broken_lifecycle/download",
                media_id=None,
                local_file_path=None,
                remote_source_url="https://example.com/broken.png",
                avatar_code="BOS_F_TEST_03",
                asset_lifecycle="BROKEN_OR_MISSING_ASSET",
                retention_policy="PERSISTENT",
                status="ACTIVE",
                created_at="2026-07-04T01:00:00Z",
                updated_at="2026-07-04T01:00:00Z",
            ),
        ]

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

    assert library["items"] == []
    assert library["diagnostics"]["reusable_image_assets"] == 0


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
