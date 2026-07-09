from pathlib import Path

import pytest

from agent.models.creative_asset import (
    CreativeAssetCreateRequest,
    CreativeAssetUpdateRequest,
)
from agent.services import creative_asset_service


def _creative_asset_row(**over):
    """A minimal creative_asset DB row for update_creative_asset gate tests."""
    base = {
        "asset_id": "ca_x",
        "semantic_role": "COMPOSITE_FRAME_REFERENCE",
        "display_name": "Frame X",
        "source_type": "GENERATED_IMAGE",
        "storage_kind": "LOCAL_FILE",
        "preview_url": "/p",
        "download_url": "/d",
        "local_file_path": "C:/tmp/x.png",
        "allowed_modes": '["F2V"]',
        "engine_slot_eligibility": '["start_frame"]',
        "review_status": "PENDING_REVIEW",
        "identity_lock_status": None,
        "scale_truth_status": None,
        "claim_safety_status": None,
        "status": "ACTIVE",
        "created_at": "2026-07-09T00:00:00Z",
        "updated_at": "2026-07-09T00:00:00Z",
    }
    base.update(over)
    return base


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
async def test_validate_selectable_asset_blocks_missing_source(monkeypatch):
    async def fake_get(asset_id: str):
        return creative_asset_service.CreativeAssetRecord(
            asset_id=asset_id,
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            display_name="Composite A",
            description=None,
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            preview_url=None,
            download_url=None,
            media_id=None,
            local_file_path=None,
            remote_source_url=None,
            product_id=None,
            category=None,
            silo=None,
            product_type=None,
            allowed_modes=["F2V"],
            engine_slot_eligibility=["start_frame"],
            mode_a_metadata_handoff=None,
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            contains_rendered_text=False,
            approved_for_video_support=False,
            approved_for_poster=False,
            review_status="APPROVED",
            status="ACTIVE",
            created_at="2026-05-18T00:00:00Z",
            updated_at="2026-05-18T00:00:00Z",
        )

    monkeypatch.setattr(creative_asset_service, "get_creative_asset", fake_get)

    result = await creative_asset_service.validate_selectable_asset(
        "ca_frame",
        semantic_role="COMPOSITE_FRAME_REFERENCE",
        allowed_mode="F2V",
        engine_slot="start_frame",
        require_approved=True,
    )

    assert result.valid is False
    assert "PREVIEW_OR_FILE_MISSING" in result.blockers


@pytest.mark.asyncio
async def test_f2v_eligibility_audit_counts_exclusions(monkeypatch):
    def build_asset(
        asset_id: str,
        *,
        semantic_role: str = "COMPOSITE_FRAME_REFERENCE",
        allowed_modes: list[str] | None = None,
        engine_slots: list[str] | None = None,
        review_status: str = "APPROVED",
        status: str = "ACTIVE",
        contains_rendered_text: bool = False,
        approved_for_video_support: bool = False,
        preview_url: str | None = "https://example.com/preview.png",
    ):
        return creative_asset_service.CreativeAssetRecord(
            asset_id=asset_id,
            semantic_role=semantic_role,  # type: ignore[arg-type]
            display_name=asset_id,
            description=None,
            source_type="UPLOAD",
            storage_kind="LOCAL_FILE",
            preview_url=preview_url,
            download_url=preview_url,
            media_id=None,
            local_file_path=None,
            remote_source_url=None,
            product_id=None,
            category=None,
            silo=None,
            product_type=None,
            allowed_modes=allowed_modes or ["F2V"],  # type: ignore[arg-type]
            engine_slot_eligibility=engine_slots or ["start_frame"],  # type: ignore[arg-type]
            mode_a_metadata_handoff=None,
            visual_dna_summary=None,
            character_dna=None,
            scene_context_dna=None,
            style_mood_dna=None,
            source_prompt_fingerprint=None,
            source_workspace_execution_package_id=None,
            source_prompt_package_snapshot_id=None,
            contains_rendered_text=contains_rendered_text,
            approved_for_video_support=approved_for_video_support,
            approved_for_poster=False,
            review_status=review_status,
            status=status,  # type: ignore[arg-type]
            created_at="2026-05-18T00:00:00Z",
            updated_at="2026-05-18T00:00:00Z",
        )

    async def fake_list(*, limit: int = 1000, **kwargs):
        return [
            build_asset("eligible"),
            build_asset("pending", review_status="PENDING_REVIEW"),
            build_asset("poster", contains_rendered_text=True),
            build_asset("wrong_mode", allowed_modes=["IMG"]),
            build_asset("wrong_slot", engine_slots=["end_frame"]),
            build_asset("missing_source", preview_url=None),
            build_asset("style_asset", semantic_role="STYLE_REFERENCE"),
        ]

    monkeypatch.setattr(creative_asset_service, "list_creative_assets", fake_list)

    audit = await creative_asset_service.get_creative_asset_eligibility_audit(
        surface="F2V_START_FRAME_PICKER",
    )

    assert audit.library_total_count == 7
    assert audit.matching_role_total_count == 6
    assert audit.eligible_count == 1
    assert audit.excluded_count == 5
    assert audit.review_status_counts["PENDING_REVIEW"] == 1
    assert audit.excluded_by_reason["NOT_APPROVED_FOR_REUSE"] == 1
    assert audit.excluded_by_reason["RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME"] == 1
    assert audit.excluded_by_reason["MODE_NOT_ALLOWED"] == 1
    assert audit.excluded_by_reason["ENGINE_SLOT_NOT_ALLOWED"] == 1
    assert audit.excluded_by_reason["PREVIEW_OR_FILE_MISSING"] == 1
    assert "SEMANTIC_ROLE_MISMATCH" not in audit.excluded_by_reason
    assert [asset.asset_id for asset in audit.eligible_assets] == ["eligible"]


@pytest.mark.asyncio
async def test_update_approval_blocked_when_truth_gates_not_pass(monkeypatch):
    # Governance parity with the save gate: a bare review_status=APPROVED PATCH on an
    # asset whose truth/safety gates are not PASS must be rejected (closes the bypass).
    async def fake_get(asset_id):
        return _creative_asset_row()

    monkeypatch.setattr(creative_asset_service.crud, "get_creative_asset", fake_get)

    with pytest.raises(ValueError, match="APPROVAL_REQUIRES_ALL_TRUTH_PASS"):
        await creative_asset_service.update_creative_asset(
            "ca_x", CreativeAssetUpdateRequest(review_status="APPROVED")
        )


@pytest.mark.asyncio
async def test_update_approval_allowed_when_truth_gates_attested(monkeypatch):
    captured = {}

    async def fake_get(asset_id):
        return _creative_asset_row()

    async def fake_update(asset_id, **kw):
        captured.update(kw)
        return _creative_asset_row(
            review_status="APPROVED",
            identity_lock_status="PASS",
            scale_truth_status="PASS",
            claim_safety_status="PASS",
        )

    monkeypatch.setattr(creative_asset_service.crud, "get_creative_asset", fake_get)
    monkeypatch.setattr(creative_asset_service.crud, "update_creative_asset", fake_update)

    result = await creative_asset_service.update_creative_asset(
        "ca_x",
        CreativeAssetUpdateRequest(
            review_status="APPROVED",
            identity_lock_status="PASS",
            scale_truth_status="PASS",
            claim_safety_status="PASS",
        ),
    )

    assert result.review_status == "APPROVED"
    assert captured["review_status"] == "APPROVED"
    assert captured["identity_lock_status"] == "PASS"
    assert captured["scale_truth_status"] == "PASS"
    assert captured["claim_safety_status"] == "PASS"


@pytest.mark.asyncio
async def test_update_non_review_edit_on_approved_asset_is_not_regated(monkeypatch):
    # Editing a NON-review field on an already-APPROVED asset (whose truth gates are
    # NULL) must NOT be re-gated — the gate fires only when THIS PATCH sets APPROVED.
    captured = {}

    async def fake_get(asset_id):
        return _creative_asset_row(review_status="APPROVED")

    async def fake_update(asset_id, **kw):
        captured.update(kw)
        return _creative_asset_row(review_status="APPROVED", display_name=kw.get("display_name", "Frame X"))

    monkeypatch.setattr(creative_asset_service.crud, "get_creative_asset", fake_get)
    monkeypatch.setattr(creative_asset_service.crud, "update_creative_asset", fake_update)

    result = await creative_asset_service.update_creative_asset(
        "ca_x", CreativeAssetUpdateRequest(display_name="Renamed")
    )

    assert result.review_status == "APPROVED"
    assert captured["display_name"] == "Renamed"
    assert "review_status" not in captured
