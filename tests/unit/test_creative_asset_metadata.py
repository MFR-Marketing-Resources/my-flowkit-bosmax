"""IMG Asset Factory v1 — creative_asset governance metadata persistence.

Runs each real-DB scenario in a single explicit event loop (``asyncio.run``)
that opens the DB with ``init_db()`` and always closes the shared connection in
the SAME loop (``close_db()``), so no orphaned WAL handle survives to lock the
next test. Proves the new columns persist and the INTEGER->bool round-trip is
honest.
"""

import asyncio

from agent.db import crud
from agent.db.schema import close_db, init_db
from agent.models.creative_asset import (
	CreativeAssetCreateRequest,
	CreativeAssetUpdateRequest,
)
from agent.services import creative_asset_service
from agent.services.creative_asset_service import (
	create_creative_asset,
	get_creative_asset,
	update_creative_asset,
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


def _run_db(scenario):
    async def wrapper():
        await init_db()
        try:
            await _seed_product()
            return await scenario()
        finally:
            await close_db()

    return asyncio.run(wrapper())


def test_governance_metadata_persists_and_bool_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        created = await create_creative_asset(
            CreativeAssetCreateRequest(
                semantic_role="COMPOSITE_FRAME_REFERENCE",
                display_name="Poster A",
                image_base64="aGVsbG8=",
                file_name="poster.png",
                allowed_modes=[],
                engine_slot_eligibility=[],
                generation_recipe_id="PRODUCT_POSTER",
                asset_subtype="POSTER_AD",
                contains_rendered_text=True,
                approved_for_poster=True,
                approved_for_video_support=False,
                product_id="prod-1",
                source_character_asset_id="ca_char",
                product_truth_status="PRESERVED",
                review_status="APPROVED",
            )
        )

        assert created.contains_rendered_text is True
        assert created.approved_for_poster is True
        assert created.approved_for_video_support is False
        assert created.generation_recipe_id == "PRODUCT_POSTER"
        assert created.asset_subtype == "POSTER_AD"
        assert created.source_character_asset_id == "ca_char"
        assert created.review_status == "APPROVED"

        reloaded = await get_creative_asset(created.asset_id)
        assert reloaded is not None
        assert reloaded.contains_rendered_text is True
        assert reloaded.approved_for_video_support is False
        assert reloaded.approved_for_poster is True
        assert reloaded.product_truth_status == "PRESERVED"
        assert reloaded.generation_recipe_id == "PRODUCT_POSTER"

    _run_db(scenario)


def test_defaults_are_clean_when_not_supplied(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        created = await create_creative_asset(
            CreativeAssetCreateRequest(
                semantic_role="CHARACTER_REFERENCE",
                display_name="Avatar A",
                image_base64="aGVsbG8=",
                file_name="avatar.png",
                allowed_modes=["I2V"],
                engine_slot_eligibility=["scene"],
            )
        )
        assert created.contains_rendered_text is False
        assert created.approved_for_video_support is False
        assert created.approved_for_poster is False
        # Direct create_creative_asset (NOT the factory) must default to
        # PENDING_REVIEW when review_status is omitted — never silently APPROVED.
        assert created.review_status == "PENDING_REVIEW"
        assert created.generation_recipe_id is None

    _run_db(scenario)


def test_review_status_update_persists_via_patch_path(tmp_path, monkeypatch):
    """Regression: the crud _COLUMNS whitelist for creative_asset omitted the
    governance columns (review_status + truth statuses), so update_creative_asset
    silently DROPPED them — a PATCH bumped updated_at but never changed
    review_status, so an asset could never be APPROVED via the review endpoint.
    This asserts the PATCH/update path actually persists those columns."""
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        created = await create_creative_asset(
            CreativeAssetCreateRequest(
                semantic_role="CHARACTER_REFERENCE",
                display_name="Avatar To Approve",
                image_base64="aGVsbG8=",
                file_name="avatar.png",
                allowed_modes=["IMG"],
                engine_slot_eligibility=["subject"],
            )
        )
        assert created.review_status == "PENDING_REVIEW"

        updated = await update_creative_asset(
            created.asset_id,
            CreativeAssetUpdateRequest(
                review_status="APPROVED",
                identity_lock_status="PASS",
                scale_truth_status="PASS",
                claim_safety_status="PASS",
            ),
        )
        assert updated.review_status == "APPROVED"
        assert updated.identity_lock_status == "PASS"

        # Must survive a fresh read (not just the in-memory update return value).
        reloaded = await get_creative_asset(created.asset_id)
        assert reloaded is not None
        assert reloaded.review_status == "APPROVED"
        assert reloaded.scale_truth_status == "PASS"
        assert reloaded.claim_safety_status == "PASS"

    _run_db(scenario)
