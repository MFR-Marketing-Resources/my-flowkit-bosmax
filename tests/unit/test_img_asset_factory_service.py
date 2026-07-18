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
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.db.schema import close_db, init_db
from agent.models.img_asset_factory import (
    ImgFastlanePromptPreviewRequest,
    SaveImgOutputRequest,
)
from agent.services import creative_asset_service
from agent.services.creative_asset_service import (
    archive_creative_asset,
    list_creative_assets,
    validate_selectable_asset,
)
from agent.services.img_asset_factory_service import (
    compile_img_fastlane_prompt_preview,
    list_img_fastlane_presets,
    save_img_output_to_library,
)


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


def test_save_approved_requires_all_truth_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        # APPROVED with any UNVERIFIED status must fail closed.
        with pytest.raises(ValueError, match="APPROVAL_REQUIRES_ALL_TRUTH_PASS"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    review_status="APPROVED",
                )
            )

        # APPROVED with a FAIL status must ALSO fail closed (not only UNVERIFIED).
        with pytest.raises(ValueError, match="APPROVAL_REQUIRES_ALL_TRUTH_PASS"):
            await save_img_output_to_library(
                SaveImgOutputRequest(
                    lane_id="AVATAR_REFERENCE",
                    display_name="x",
                    image_base64="aGVsbG8=",
                    review_status="APPROVED",
                    identity_lock_status="PASS",
                    scale_truth_status="FAIL",
                    claim_safety_status="PASS",
                )
            )

        # APPROVED only when EVERY truth gate PASSes.
        rec = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE",
                display_name="Reviewed",
                image_base64="aGVsbG8=",
                review_status="APPROVED",
                identity_lock_status="PASS",
                scale_truth_status="PASS",
                claim_safety_status="PASS",
            )
        )
        assert rec.review_status == "APPROVED"
        assert rec.identity_lock_status == "PASS"
        assert rec.scale_truth_status == "PASS"
        assert rec.claim_safety_status == "PASS"

    _run_db(scenario)


def test_only_approved_assets_are_reusable(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        # PENDING_REVIEW (default) avatar: selectable WITHOUT the approval gate,
        # blocked WITH it.
        pending = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE", display_name="Pending", image_base64="aGVsbG8="
            )
        )
        lax = await validate_selectable_asset(
            pending.asset_id,
            semantic_role="CHARACTER_REFERENCE",
            allowed_mode="I2V",
            engine_slot="scene",
        )
        assert lax.valid is True
        gated = await validate_selectable_asset(
            pending.asset_id,
            semantic_role="CHARACTER_REFERENCE",
            allowed_mode="I2V",
            engine_slot="scene",
            require_approved=True,
        )
        assert gated.valid is False
        assert "NOT_APPROVED_FOR_REUSE" in gated.blockers

        # APPROVED avatar passes the reuse gate.
        approved = await save_img_output_to_library(
            SaveImgOutputRequest(
                lane_id="AVATAR_REFERENCE",
                display_name="Approved",
                image_base64="aGVsbG8=",
                review_status="APPROVED",
                identity_lock_status="PASS",
                scale_truth_status="PASS",
                claim_safety_status="PASS",
            )
        )
        ok = await validate_selectable_asset(
            approved.asset_id,
            semantic_role="CHARACTER_REFERENCE",
            allowed_mode="I2V",
            engine_slot="scene",
            require_approved=True,
        )
        assert ok.valid is True

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


def test_fastlane_preset_listing_contains_required_presets():
    response = list_img_fastlane_presets()
    preset_ids = {item.preset_id for item in response.items}
    assert {
        "BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF",
        "BOSMAX_SERUM_AVATAR_PRODUCT_2REF",
        "MWCB_WG40_AVATAR_BOTTLE",
        "MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
        "MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
    }.issubset(preset_ids)


def test_compile_bosmax_three_ref_preview_uses_product_truth_and_template_rules(monkeypatch):
    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-bosmax",
            "product_display_name": "Bosmax Herbs 5 ML",
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_short_name": "BOSMAX",
            "media_id": "media-bosmax",
        }

    async def fake_get_asset(asset_id: str):
        labels = {
            "char-1": "Aina Presenter Identity",
            "style-1": "Clean modern wardrobe context",
        }
        return SimpleNamespace(display_name=labels.get(asset_id, asset_id))

    monkeypatch.setattr(crud, "get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.img_asset_factory_service.get_creative_asset",
        fake_get_asset,
    )

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="BOSMAX_SERUM_AVATAR_PRODUCT_SCENE_3REF",
                route="FRAMES",
                product_id="prod-bosmax",
                character_reference_asset_id="char-1",
                style_reference_asset_id="style-1",
            )
        )
    )

    assert preview.blockers == []
    assert "Ref 1 = avatar identity lock: Aina Presenter Identity" in preview.reference_map
    assert "Ref 3 = product truth: Bosmax Herbs 5 ML" in preview.reference_map
    assert "Typography and branding lock" in preview.prompt_text
    assert "Spatial math lock" in preview.prompt_text
    assert "PRODUCT SCALE LOCK:" in preview.prompt_text
    assert "real size outranks label readability" in preview.prompt_text
    assert "FRAME PERSISTENCE LOCK" in preview.prompt_text


def test_compile_wg40_video_lock_preview_emits_exact_bottle_truth(monkeypatch):
    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-wg40",
            "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
            "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
            "media_id": "media-wg40",
        }

    async def fake_get_asset(asset_id: str):
        labels = {
            "char-1": "Mak Cik Host Identity",
            "style-1": "Traditional herbal presentation",
        }
        return SimpleNamespace(display_name=labels.get(asset_id, asset_id))

    monkeypatch.setattr(crud, "get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.img_asset_factory_service.get_creative_asset",
        fake_get_asset,
    )

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="MWCB_WG40_VIDEO_LOCK_FRAMES_INGREDIENTS",
                route="FRAMES",
                product_id="prod-wg40",
                character_reference_asset_id="char-1",
                style_reference_asset_id="style-1",
            )
        )
    )

    assert preview.blockers == []
    assert "Exact bottle truth: Minyak Warisan Tok Cap Burung 25ml" in preview.reference_map
    assert "red ribbed cap" in preview.prompt_text
    assert "emerald herbal green oil" in preview.prompt_text
    assert "Sejak 1958" in preview.prompt_text
    assert "Petua Turun Temurun" in preview.prompt_text


def test_compile_product_lock_preview_warns_and_blocks_without_product():
    # The generic INGREDIENTS product-lock presets were purged with the Ingredients
    # sub-module; the surviving INGREDIENTS + PRODUCT_REFERENCE path is the kept
    # poster-lock preset, which exercises the same warns-and-blocks-without-product
    # contract (lane PRODUCT_POSTER).
    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
                route="INGREDIENTS",
                ingredient_role="PRODUCT_REFERENCE",
            )
        )
    )

    assert "PRODUCT_REQUIRED" in preview.blockers
    assert "PRODUCT_CONTEXT_RECOMMENDED_FOR_PRODUCT_LOCK" in preview.warnings
    assert preview.lane_id == "PRODUCT_POSTER"


def test_frames_preview_enforces_clean_frame_no_text_negative(monkeypatch):
    """A composite FRAMES lane must forbid baked-in text so the plate stays clean
    for the social-copy layer (user report: avatar+product image had text on it)."""

    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-wg40",
            "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
            "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
            "media_id": "media-wg40",
        }

    async def fake_get_asset(asset_id: str):
        return SimpleNamespace(display_name=asset_id)

    monkeypatch.setattr(crud, "get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.img_asset_factory_service.get_creative_asset",
        fake_get_asset,
    )

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="GENERIC_FRAMES_AVATAR_PRODUCT",
                route="FRAMES",
                product_id="prod-wg40",
                character_reference_asset_id="char-1",
            )
        )
    )

    assert preview.lane_id == "AVATAR_PRODUCT_COMPOSITE"
    # baked-in text guard reaches BOTH the prompt sent to Flow and the structured field
    assert "No rendered text" in preview.prompt_text
    assert "clean commercial frame" in preview.prompt_text
    assert any("clean commercial frame" in rule for rule in preview.negative_rules)
    # original preset negatives are preserved (additive, not a rewrite)
    assert any("No product drift" in rule for rule in preview.negative_rules)


def test_poster_lane_is_exempt_from_clean_frame_no_text_negative(monkeypatch):
    """The poster lane's whole purpose is a text-bearing terminal asset, so the
    clean-frame no-text guard must NOT be injected there."""

    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-wg40",
            "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
            "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
            "media_id": "media-wg40",
        }

    monkeypatch.setattr(crud, "get_product", fake_get_product)

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="MWCB_WG40_PRODUCT_ONLY_POSTER_LOCK",
                route="INGREDIENTS",
                ingredient_role="PRODUCT_REFERENCE",
                product_id="prod-wg40",
            )
        )
    )

    assert preview.lane_id == "PRODUCT_POSTER"
    assert "clean commercial frame" not in preview.prompt_text
    assert not any("clean commercial frame" in rule for rule in preview.negative_rules)


def test_engine_prompt_is_clean_portable_and_leak_free(monkeypatch):
    """engine_prompt_text is the payload actually sent to the generator and must be
    portable across engines (Flow / ChatGPT / Grok): it carries the substantive
    creative brief but ZERO internal routing metadata. The labeled prompt_text
    breakdown is preserved separately for the operator."""

    async def fake_get_product(_product_id: str):
        return {
            "id": "prod-wg40",
            "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
            "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
            "media_id": "media-wg40",
        }

    async def fake_get_asset(asset_id: str):
        return SimpleNamespace(display_name=asset_id)

    monkeypatch.setattr(crud, "get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.img_asset_factory_service.get_creative_asset",
        fake_get_asset,
    )

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="GENERIC_FRAMES_AVATAR_PRODUCT",
                route="FRAMES",
                product_id="prod-wg40",
                character_reference_asset_id="char-1",
            )
        )
    )

    engine = preview.engine_prompt_text
    assert engine, "engine_prompt_text must be populated"

    # NO internal routing metadata may leak into the payload sent to any engine.
    for leaked in (
        "TEMPLATE PRESET",
        "FASTLANE ROUTE",
        "TARGET LANE",
        "TARGET INGREDIENT ROLE",
        "GENERIC_FRAMES_AVATAR_PRODUCT",  # preset id
        "AVATAR_PRODUCT_COMPOSITE",  # lane id
        "System composes the prompt",  # operator-facing workflow meta
    ):
        assert leaked not in engine, f"internal metadata leaked into engine prompt: {leaked!r}"

    # ...but the substantive creative brief IS present, incl. the clean-frame guard.
    assert "PRODUCT SCALE LOCK" in engine
    assert "REFERENCES:" in engine
    assert "AVOID:" in engine
    assert any("clean commercial frame" in line for line in engine.splitlines())

    # The labeled operator breakdown is unchanged and still carries the scaffold.
    assert "TEMPLATE PRESET:" in preview.prompt_text
    assert "NEGATIVE RULES:" in preview.prompt_text


def test_scene_context_code_injects_background_into_prompt(monkeypatch):
    """Selecting a registry SceneCode injects the scene's Background: text into both
    the engine prompt and the labeled breakdown — usable immediately, no scene image
    needed."""

    async def fake_get_product(_pid):
        return None

    monkeypatch.setattr(crud, "get_product", fake_get_product)

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="GENERIC_FRAMES_AVATAR_PRODUCT",
                route="FRAMES",
                scene_context_code="SCN_RAYA_KAMPUNG",
            )
        )
    )
    # engine prompt carries the scene Background (right after the output-spec lead)
    engine = preview.engine_prompt_text.lower()
    assert "background:" in engine
    assert "kampung" in engine and "pelita" in engine  # from the Raya Kampung scene
    # labeled breakdown carries a dedicated SCENE CONTEXT section
    assert "SCENE CONTEXT (background)" in preview.prompt_text
    assert "Raya Kampung" in preview.prompt_text


def test_unknown_scene_context_code_warns_not_crashes(monkeypatch):
    async def fake_get_product(_pid):
        return None

    monkeypatch.setattr(crud, "get_product", fake_get_product)

    preview = asyncio.run(
        compile_img_fastlane_prompt_preview(
            ImgFastlanePromptPreviewRequest(
                preset_id="GENERIC_FRAMES_AVATAR_PRODUCT",
                route="FRAMES",
                scene_context_code="SCN_DOES_NOT_EXIST",
            )
        )
    )
    assert "SCENE_CONTEXT_NOT_FOUND" in preview.warnings
    assert "SCENE CONTEXT" not in preview.prompt_text  # nothing injected on miss


# ── Clean-frame anti-leak hardening (owner-reported live leak) ─────────────
#
# A frames output rendered social-app UI (like/share icons, an order button, a
# template-name chip) + engine-invented garbled Malay marketing copy. Root
# nudges: the output spec literally asked for a "TikTok" image, and the clean
# rules banned text but not the interface family.


def test_fastlane_output_spec_never_names_a_platform_and_declares_clean_frame():
    from agent.services.img_asset_factory_service import _FASTLANE_OUTPUT_SPEC
    assert "tiktok" not in _FASTLANE_OUTPUT_SPEC.lower()
    for kw in ("no text", "no captions", "no buttons", "no icons", "no interface elements"):
        assert kw in _FASTLANE_OUTPUT_SPEC.lower(), f"missing: {kw}"


def test_clean_frame_rules_ban_the_social_ui_family_and_invented_copy():
    from agent.services.img_asset_factory_service import _CLEAN_FRAME_NEGATIVE_RULES
    joined = " ".join(_CLEAN_FRAME_NEGATIVE_RULES).lower()
    for kw in ("like/comment/share icons", "order buttons", "template/preset name chips",
               "phone status bars", "invented marketing copy"):
        assert kw in joined, f"missing: {kw}"


@pytest.mark.asyncio
async def test_generic_frames_engine_prompt_carries_all_locks_and_no_platform_word(monkeypatch):
    """End-to-end compile of the exact preset from the leak: the engine brief must
    carry the no-modification + scale-anchor locks, the interface-family ban, and
    must never contain 'TikTok' or the preset id."""
    from agent.services import img_asset_factory_service as svc
    from agent.models.img_asset_factory import ImgFastlanePromptPreviewRequest

    async def fake_get_product(pid):
        return {"id": pid, "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
                "product_truth_ref": "MWTCB_25ML_CAP_BURUNG", "media_id": "m1",
                "local_image_path": "x.png"}
    monkeypatch.setattr(svc.crud, "get_product", fake_get_product)

    preview = await svc.compile_img_fastlane_prompt_preview(ImgFastlanePromptPreviewRequest(
        preset_id="GENERIC_FRAMES_AVATAR_PRODUCT", route="FRAMES", product_id="p1",
    ))
    ep = preview.engine_prompt_text
    assert "PRODUCT NO-MODIFICATION LOCK:" in ep
    assert "PRODUCT SCALE ANCHOR:" in ep
    assert "like/comment/share icons" in ep
    assert "tiktok" not in ep.lower()
    assert "GENERIC_FRAMES_AVATAR_PRODUCT" not in ep   # routing metadata never leaks
