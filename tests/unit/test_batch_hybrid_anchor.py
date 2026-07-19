"""Batch HYBRID product anchor (padded 9:16 PRODUCT_REFERENCE).

The queue's aspect gate refuses a raw catalog image as the start frame, so a
batch HYBRID item must anchor to the product's padded 9:16 PRODUCT_REFERENCE
asset. These tests pin: the planner carries the anchor CONSTANT across items
(visuals rotate via avatar/scene, never via product truth); the auto-resolver
picks only an APPROVED asset whose local image parses to 9:16 (+-3%,
deterministic by asset_id) and warns instead of guessing when none exists;
the creator mapping rides the F2V start-frame slot.
"""
import pytest

from agent.services import batch_prompt_planner as planner
from agent.services import workspace_generation_package_service as wgps

PID = "prod-hyb-anchor"


def test_planner_carries_constant_anchor_for_hybrid_only():
    items = planner.plan_batch_items(
        logical_mode="HYBRID",
        variation_strategy="SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        quantity=3,
        product_id=PID,
        avatar_codes=["AV1", "AV2"],
        hook_angles=["hook"],
        product_reference_asset_id="ca_pad916",
    )
    assert all(i["product_reference_asset_id"] == "ca_pad916" for i in items)
    # Visuals still rotate.
    assert {i["avatar_code"] for i in items} == {"AV1", "AV2"}

    t2v = planner.plan_batch_items(
        logical_mode="T2V",
        variation_strategy="SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
        quantity=2,
        product_id=PID,
        avatar_codes=["AV1"],
        hook_angles=["hook"],
        product_reference_asset_id="ca_pad916",
    )
    assert all("product_reference_asset_id" not in i for i in t2v)


def test_creator_kwargs_maps_anchor_to_start_frame_slot():
    plan = {
        "logical_mode": "HYBRID",
        "product_reference_asset_id": "ca_pad916",
        "avatar_code": "AV1",
    }
    cache = {"ca_pad916": {"preview_url": "/p.png", "download_url": "/d.png"}}
    kwargs = wgps._plan_creator_kwargs(plan, cache)
    assert kwargs["start_frame_asset_id"] == "ca_pad916"
    assert kwargs["start_frame_preview_url"] == "/p.png"
    assert kwargs["start_frame_download_url"] == "/d.png"
    assert kwargs["avatar_id"] == "AV1"


# ── Auto-resolver ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolver_picks_only_approved_916_asset(monkeypatch, tmp_path):
    # Two real PNGs: one 9:16 (1080x1920), one raw catalog ratio (1122x1402).
    import struct, zlib

    def png(path, w, h):
        ihdr = struct.pack(">II5B", w, h, 8, 2, 0, 0, 0)
        chunk = b"IHDR" + ihdr
        data = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        )
        path.write_bytes(data)
        return str(path)

    good = png(tmp_path / "pad916.png", 1080, 1920)
    raw = png(tmp_path / "raw.png", 1122, 1402)

    rows = [
        {"asset_id": "ca_b_raw", "review_status": "APPROVED", "local_file_path": raw},
        {"asset_id": "ca_c_916_unapproved", "review_status": "PENDING", "local_file_path": good},
        {"asset_id": "ca_d_916", "review_status": "APPROVED", "local_file_path": good},
    ]

    async def list_assets(**kw):
        assert kw == {"semantic_role": "PRODUCT_REFERENCE", "product_id": PID}
        return rows

    monkeypatch.setattr(wgps.crud, "list_creative_assets", list_assets)
    asset_id, warnings = await wgps._resolve_hybrid_anchor_916(PID)
    assert asset_id == "ca_d_916"  # approved + parses 9:16
    assert warnings == []


@pytest.mark.asyncio
async def test_resolver_warns_instead_of_guessing_when_no_916(monkeypatch, tmp_path):
    async def list_assets(**kw):
        return [{
            "asset_id": "ca_raw", "review_status": "APPROVED",
            "local_file_path": str(tmp_path / "missing.png"),
        }]

    monkeypatch.setattr(wgps.crud, "list_creative_assets", list_assets)
    asset_id, warnings = await wgps._resolve_hybrid_anchor_916(PID)
    assert asset_id is None
    assert any("HYBRID_ANCHOR_916_NOT_FOUND" in w for w in warnings)
