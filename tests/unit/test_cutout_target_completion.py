"""Completion-layer backend tests: operator ROI target persistence + source-SHA
binding + readiness isolation surfacing + current-system-visual authority +
provider_operations=0. Uses the pytest temp DB (never the canonical DB).
"""

from io import BytesIO

import pytest
from PIL import Image

from agent.db import crud
from agent.services import product_visual_onboarding_service as service


async def _make_product(tmp_path, w=400, h=600):
    source = tmp_path / "source.png"
    Image.new("RGB", (w, h), (200, 60, 60)).save(source)
    product = await crud.create_product(
        raw_product_title="Target Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    return product["id"], source


@pytest.mark.asyncio
async def test_target_crud_roundtrip_and_delete():
    await crud.create_product(raw_product_title="P", source="MANUAL")  # ensure table usable
    pid = (await crud.create_product(raw_product_title="Roundtrip", source="MANUAL"))["id"]
    await crud.upsert_product_cutout_target(
        pid, source_sha256="abc", source_width=400, source_height=600,
        target_x=10, target_y=20, target_width=100, target_height=150, selected_by="op",
    )
    row = await crud.get_product_cutout_target(pid)
    assert row["target_x"] == 10 and row["target_width"] == 100 and row["source_sha256"] == "abc"
    await crud.delete_product_cutout_target(pid)
    assert await crud.get_product_cutout_target(pid) is None


@pytest.mark.asyncio
async def test_set_target_persists_and_surfaces_in_readiness(tmp_path):
    pid, _ = await _make_product(tmp_path, 400, 600)
    readiness = await service.set_product_cutout_target(pid, x=50, y=60, width=120, height=180, selected_by="operator")
    assert readiness["target_selection_available"] is True
    tr = readiness["target_region"]
    assert (tr["x"], tr["y"], tr["width"], tr["height"]) == (50, 60, 120, 180)
    assert readiness["provider_operations"] == 0
    # persisted + bound to the source SHA
    row = await crud.get_product_cutout_target(pid)
    assert row["source_sha256"] and row["source_width"] == 400 and row["source_height"] == 600


@pytest.mark.asyncio
async def test_set_target_rejects_out_of_bounds(tmp_path):
    pid, _ = await _make_product(tmp_path, 400, 600)
    with pytest.raises(service.ProductVisualOnboardingError) as exc:
        await service.set_product_cutout_target(pid, x=350, y=0, width=100, height=100)  # x+w > 400
    assert exc.value.code == "TARGET_REGION_INVALID"


@pytest.mark.asyncio
async def test_set_target_rejects_tiny_roi(tmp_path):
    pid, _ = await _make_product(tmp_path, 400, 600)
    with pytest.raises(service.ProductVisualOnboardingError) as exc:
        await service.set_product_cutout_target(pid, x=0, y=0, width=2, height=2)
    assert exc.value.code == "TARGET_REGION_TOO_SMALL"


@pytest.mark.asyncio
async def test_readiness_current_system_visual_and_isolation_fields(tmp_path):
    pid, _ = await _make_product(tmp_path, 400, 600)
    readiness = await service.get_product_visual_readiness(pid)
    # no cutout yet -> the trusted original source is the current system reference
    csv = readiness["current_system_visual"]
    assert csv["card"] == "ORIGINAL_SOURCE" and csv["status"] == "ORIGINAL_FALLBACK"
    # isolation fields exist (None until a candidate is prepared)
    assert "file_quality_status" in readiness and "product_isolation_status" in readiness
    assert readiness["target_selection_required"] is False
    assert readiness["provider_operations"] == 0


def test_current_system_visual_mapping_authority():
    assert service._current_system_visual("APPROVED_AUTO_CANONICAL_CUTOUT", source_available=True) == {
        "card": "AUTO_CUTOUT", "label": "Auto Cutout", "status": "OFFICIAL"}
    assert service._current_system_visual("APPROVED_MANUAL_CANONICAL_CUTOUT", source_available=True)["status"] == "OFFICIAL"
    assert service._current_system_visual("SAME_PRODUCT_TRUSTED_SOURCE", source_available=True)["status"] == "ORIGINAL_FALLBACK"
    assert service._current_system_visual("BLOCKED", source_available=False)["status"] == "BLOCKED"
