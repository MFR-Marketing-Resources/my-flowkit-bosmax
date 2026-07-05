"""IMG Asset Factory v1 — save-to-library governance + I2V bridge + fail-closed.

Runs each real-DB scenario in a single explicit event loop (``asyncio.run``)
that opens the DB (``init_db``), seeds a product for FK-bound saves, and always
closes the shared connection in the SAME loop (``close_db``). Proves:
  - a REAL output (generated_artifact image or base64) saves under lane-governed
    role/modes/slots/lineage,
  - a saved avatar is I2V-selectable through the exact resolver gate,
  - archived + role-mismatch are blocked, a poster is not a clean video frame,
  - the save path fails closed without a real output / unknown lane / missing
    product-truth input, and never fabricates a generation.
"""

import asyncio

import pytest

from agent.db import crud
from agent.db.schema import close_db, init_db
from agent.models.img_asset_factory import SaveImgOutputRequest
from agent.services import creative_asset_service
from agent.services.creative_asset_service import (
    archive_creative_asset,
    list_creative_assets,
    validate_selectable_asset,
)
from agent.services.img_asset_factory_service import save_img_output_to_library


async def _seed_product(product_id: str = "prod-1") -> None:
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            "INSERT OR IGNORE INTO product "
            "(id, raw_product_title, product_display_name, product_short_name) "
            "VALUES (?, ?, ?, ?)",
            (product_id, "Test Product", "Test Product", "Test"),
        )
        await db.commit()


async def _insert_artifact(media_id: str, kind: str, local_path) -> None:
    db = await crud.get_db()
    async with crud._db_lock:
        await db.execute(
            "INSERT INTO generated_artifact "
            "(media_id, job_id, mode, artifact_kind, local_path, size_mb, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (media_id, "job-1", "IMG", kind, str(local_path), 0.1, "2026-01-01T00:00:00Z"),
        )
        await db.commit()


def _run_db(scenario):
    async def wrapper():
        await init_db()
        try:
            await _seed_product()
            return await scenario()
        finally:
            await close_db()

    return asyncio.run(wrapper())


def test_save_from_generated_artifact_image(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        img = tmp_path / "out.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n-fake-bytes")
        await _insert_artifact("media-img-1", "image", img)

        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="PRODUCT_ONLY_HERO",
                display_name="Hero Shot",
                generated_artifact_media_id="media-img-1",
                product_id="prod-1",
            )
        )
        assert rec.source_type == "GENERATED_IMAGE"
        assert rec.semantic_role == "PRODUCT_REFERENCE"
        assert rec.generation_recipe_id == "PRODUCT_ONLY_HERO"
        assert rec.product_truth_status == "PRESERVED"
        # A freshly-saved asset is PENDING_REVIEW, never silently APPROVED.
        assert rec.review_status == "PENDING_REVIEW"
        assert "I2V" in rec.allowed_modes
        assert "F2V" not in rec.allowed_modes  # PRODUCT_ONLY_HERO is not an F2V frame

    _run_db(scenario)


def test_save_from_video_artifact_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        await _insert_artifact("media-vid-1", "video", tmp_path / "v.mp4")
        with pytest.raises(ValueError, match="ARTIFACT_NOT_AN_IMAGE"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="PRODUCT_ONLY_HERO",
                    display_name="x",
                    generated_artifact_media_id="media-vid-1",
                    product_id="prod-1",
                )
            )

    _run_db(scenario)


def test_save_missing_artifact_is_404_like(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        with pytest.raises(ValueError, match="GENERATED_ARTIFACT_NOT_FOUND"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="PRODUCT_ONLY_HERO",
                    display_name="x",
                    generated_artifact_media_id="does-not-exist",
                    product_id="prod-1",
                )
            )

    _run_db(scenario)


def test_save_fails_closed_without_real_output(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        with pytest.raises(ValueError, match="NO_REAL_OUTPUT_SOURCE"):
            await save_img_output_to_library(
                SaveImgOutputRequest(lane_id="AVATAR_REFERENCE", display_name="x")
            )

    _run_db(scenario)


def test_save_unknown_lane_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        with pytest.raises(ValueError, match="UNSUPPORTED_IMG_LANE"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="NOPE", display_name="x", image_base64="aGVsbG8="
                )
            )

    _run_db(scenario)


def test_save_product_lane_requires_product(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        with pytest.raises(ValueError, match="IMG_LANE_INPUT_BLOCKED"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="PRODUCT_ONLY_HERO",
                    display_name="x",
                    image_base64="aGVsbG8=",
                )
            )

    _run_db(scenario)


def test_saved_avatar_is_i2v_selectable_and_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE",
                display_name="Avatar A",
                image_base64="aGVsbG8=",
            )
        )
        assert rec.semantic_role == "CHARACTER_REFERENCE"
        assert rec.source_type == "UPLOAD"
        assert rec.product_truth_status == "NOT_APPLICABLE"

        # Bridge: the resolver's exact selection gate accepts it for the character
        # slot — character maps to 'scene' in PRODUCT_HELD_BY_CHARACTER_IN_SCENE
        # and to 'subject' in CHARACTER_FIRST_PRODUCT_DEMO; both must be eligible.
        for slot in ("scene", "subject"):
            result = await validate_selectable_asset(
                rec.asset_id,
                semantic_role="CHARACTER_REFERENCE",
                allowed_mode="I2V",
                engine_slot=slot,
            )
            assert result.valid is True, (slot, result.blockers)

        mismatch = await validate_selectable_asset(
            rec.asset_id,
            semantic_role="PRODUCT_REFERENCE",
            allowed_mode="I2V",
            engine_slot="subject",
        )
        assert "SEMANTIC_ROLE_MISMATCH" in mismatch.blockers

        await archive_creative_asset(rec.asset_id)
        archived = await validate_selectable_asset(
            rec.asset_id,
            semantic_role="CHARACTER_REFERENCE",
            allowed_mode="I2V",
            engine_slot="scene",
        )
        assert "ASSET_ARCHIVED" in archived.blockers

    _run_db(scenario)


def test_saved_poster_is_not_a_clean_video_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="PRODUCT_POSTER",
                display_name="Poster A",
                image_base64="aGVsbG8=",
                product_id="prod-1",
            )
        )
        assert rec.contains_rendered_text is True
        assert rec.approved_for_poster is True
        assert rec.approved_for_video_support is False

        result = await validate_selectable_asset(
            rec.asset_id,
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            allowed_mode="F2V",
            engine_slot="start_frame",
            disallow_rendered_text=True,
        )
        assert "RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME" in result.blockers

    _run_db(scenario)


def test_poster_fails_mode_gate_and_is_not_listed_for_video(tmp_path, monkeypatch):
    """Defense-in-depth: the poster fails the MODE gate for F2V/I2V (not only the
    rendered-text layer) and never appears in F2V/I2V library queries."""
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        poster = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="PRODUCT_POSTER",
                display_name="Poster A",
                image_base64="aGVsbG8=",
                product_id="prod-1",
            )
        )
        # Mode gate blocks F2V/I2V even WITHOUT the rendered-text check.
        for mode, slot in (("F2V", "start_frame"), ("F2V", "end_frame"), ("I2V", "subject")):
            res = await validate_selectable_asset(
                poster.asset_id,
                semantic_role="COMPOSITE_FRAME_REFERENCE",
                allowed_mode=mode,
                engine_slot=slot,
            )
            assert res.valid is False
            assert "MODE_NOT_ALLOWED" in res.blockers, (mode, slot, res.blockers)

        # Generic library queries scoped to a video mode never return the poster.
        for mode in ("F2V", "I2V"):
            items = await list_creative_assets(allowed_mode=mode)
            assert poster.asset_id not in {i.asset_id for i in items}

    _run_db(scenario)


def test_save_rejects_multiple_output_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        await _insert_artifact("media-img-2", "image", tmp_path / "o.png")
        (tmp_path / "o.png").write_bytes(b"x")
        with pytest.raises(ValueError, match="MULTIPLE_OUTPUT_SOURCES_NOT_ALLOWED"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    generated_artifact_media_id="media-img-2",
                    image_base64="aGVsbG8=",
                )
            )

    _run_db(scenario)


def test_save_product_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="PRODUCT_ONLY_HERO",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    product_id="does-not-exist",
                )
            )

    _run_db(scenario)


def test_save_rejects_invalid_lineage_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        # A real, ACTIVE character reference (valid lineage) and a style asset
        # (wrong role for the character slot).
        char = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE", display_name="Char", image_base64="aGVsbG8="
            )
        )
        style = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="STYLE_REFERENCE", display_name="Style", image_base64="aGVsbG8="
            )
        )

        # Valid lineage saves fine.
        ok = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE",
                display_name="Uses valid char",
                image_base64="aGVsbG8=",
                source_character_asset_id=char.asset_id,
            )
        )
        assert ok.source_character_asset_id == char.asset_id

        # Missing lineage asset.
        with pytest.raises(ValueError, match="SOURCE_CHARACTER_ASSET_INVALID"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    source_character_asset_id="ca_missing",
                )
            )

        # Wrong-role lineage asset (style used as character).
        with pytest.raises(ValueError, match="SOURCE_CHARACTER_ASSET_INVALID"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    source_character_asset_id=style.asset_id,
                )
            )

        # Archived lineage asset.
        await archive_creative_asset(char.asset_id)
        with pytest.raises(ValueError, match="SOURCE_CHARACTER_ASSET_INVALID"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    source_character_asset_id=char.asset_id,
                )
            )

        # Wrong-role for the scene slot (style used as scene).
        with pytest.raises(ValueError, match="SOURCE_SCENE_ASSET_INVALID"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    source_scene_asset_id=style.asset_id,
                )
            )

    _run_db(scenario)


def test_save_approved_requires_truth_review(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        # APPROVED while truth/safety statuses are UNVERIFIED must fail closed.
        with pytest.raises(ValueError, match="APPROVAL_REQUIRES_TRUTH_REVIEW"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    review_status="APPROVED",
                )
            )

        # APPROVED with explicit truth statuses succeeds and persists them.
        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE",
                display_name="Reviewed",
                image_base64="aGVsbG8=",
                review_status="APPROVED",
                identity_lock_status="LOCKED",
                scale_truth_status="PRESERVED",
                claim_safety_status="SAFE",
            )
        )
        assert rec.review_status == "APPROVED"
        assert rec.identity_lock_status == "LOCKED"
        assert rec.scale_truth_status == "PRESERVED"
        assert rec.claim_safety_status == "SAFE"

    _run_db(scenario)


def test_default_save_is_pending_review_with_unverified_truth(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE", display_name="x", image_base64="aGVsbG8="
            )
        )
        assert rec.review_status == "PENDING_REVIEW"
        assert rec.identity_lock_status == "UNVERIFIED"
        assert rec.scale_truth_status == "UNVERIFIED"
        assert rec.claim_safety_status == "UNVERIFIED"

    _run_db(scenario)
