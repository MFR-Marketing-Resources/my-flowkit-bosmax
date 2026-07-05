"""IMG Asset Factory v1 — F2V start/end frame source resolver contract.

Runs each real-DB scenario in a single explicit event loop (``asyncio.run``)
that opens the DB (``init_db``), seeds a product for FK-bound saves, and always
closes the shared connection in the SAME loop (``close_db``).
"""

import asyncio

from agent.db import crud
from agent.db.schema import close_db, init_db
from agent.models.f2v_frame_source_resolver import F2VFrameSourceResolverRequest
from agent.models.img_asset_factory import SaveImgOutputRequest
from agent.services import creative_asset_service
from agent.services.creative_asset_service import archive_creative_asset
from agent.services.f2v_frame_source_resolver_service import resolve_f2v_frame_sources
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


def _run_db(scenario):
    async def wrapper():
        await init_db()
        try:
            await _seed_product()
            return await scenario()
        finally:
            await close_db()

    return asyncio.run(wrapper())


async def _make_composite(display_name: str = "Composite A"):
    return await save_img_output_to_library(
        SaveImgOutputRequest(
            lane_id="AVATAR_PRODUCT_COMPOSITE",
            display_name=display_name,
            image_base64="aGVsbG8=",
            product_id="prod-1",
        )
    )


async def _make_poster():
    return await save_img_output_to_library(
        SaveImgOutputRequest(
            lane_id="PRODUCT_POSTER",
            display_name="Poster A",
            image_base64="aGVsbG8=",
            product_id="prod-1",
        )
    )


def test_composite_asset_selectable_as_start_and_end(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        comp = await _make_composite()
        resp = await resolve_f2v_frame_sources(
            F2VFrameSourceResolverRequest(
                start_frame_asset_id=comp.asset_id,
                end_frame_asset_id=comp.asset_id,
            )
        )
        assert resp.blockers == []
        assert resp.start_frame is not None
        assert resp.start_frame.source_kind == "COMPOSITE_FRAME_REFERENCE"
        assert resp.end_frame is not None
        assert resp.end_frame.source_kind == "COMPOSITE_FRAME_REFERENCE"
        assert len(resp.resolved_frames) == 2

    _run_db(scenario)


def test_poster_rejected_as_video_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        poster = await _make_poster()
        resp = await resolve_f2v_frame_sources(
            F2VFrameSourceResolverRequest(start_frame_asset_id=poster.asset_id)
        )
        assert resp.start_frame is None
        assert any("RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME" in b for b in resp.blockers)

    _run_db(scenario)


def test_archived_composite_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(creative_asset_service, "CREATIVE_ASSET_UPLOAD_DIR", tmp_path)

    async def scenario():
        comp = await _make_composite()
        await archive_creative_asset(comp.asset_id)
        resp = await resolve_f2v_frame_sources(
            F2VFrameSourceResolverRequest(start_frame_asset_id=comp.asset_id)
        )
        assert resp.start_frame is None
        assert any("ASSET_ARCHIVED" in b for b in resp.blockers)

    _run_db(scenario)


def test_manual_upload_start_frame_and_optional_end():
    async def scenario():
        resp = await resolve_f2v_frame_sources(
            F2VFrameSourceResolverRequest(start_frame_manual_upload_present=True)
        )
        assert resp.blockers == []
        assert resp.start_frame is not None
        assert resp.start_frame.source_kind == "MANUAL_UPLOAD"
        assert "END_FRAME_OPTIONAL_NOT_SELECTED" in resp.warnings

    _run_db(scenario)


def test_start_frame_required_when_no_source():
    async def scenario():
        resp = await resolve_f2v_frame_sources(F2VFrameSourceResolverRequest())
        assert "START_FRAME_REQUIRED" in resp.blockers

    _run_db(scenario)
