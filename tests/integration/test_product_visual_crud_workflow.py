"""Provider-free end-to-end lock for the per-product Visual / Canva CRUD flow.

The pytest fixture uses a process-local temporary database. This workflow must
never touch the canonical ``flow_agent.db`` or make a provider call.
"""

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from agent.config import DB_PATH
from agent.db import crud
from agent.services import product_truth_lock_service
from agent.services import product_visual_onboarding_service as service


def _cutout_bytes(color: tuple[int, int, int], size: tuple[int, int] = (1000, 1000)) -> bytes:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    for x in range(max(1, width // 5), min(width, width - max(1, width // 5))):
        for y in range(max(1, height // 8), min(height, height - max(1, height // 8))):
            image.putpixel((x, y), (*color, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.asyncio
async def test_product_visual_crud_workflow_is_provider_free(tmp_path, monkeypatch):
    """READ -> Auto -> refetch -> Manual Replace -> Save -> refetch."""

    assert Path(DB_PATH).name.startswith("flowkit-pytest-")
    assert Path(DB_PATH).name != "flow_agent.db"
    isolated_runtime_root = tmp_path / "runtime-storage"
    isolated_runtime_root.mkdir()
    monkeypatch.setattr(service, "BASE_DIR", isolated_runtime_root)
    monkeypatch.setattr(product_truth_lock_service, "BASE_DIR", isolated_runtime_root)

    source = tmp_path / "product-source.png"
    Image.new("RGB", (32, 32), (35, 110, 160)).save(source)
    product = await crud.create_product(
        raw_product_title="Visual CRUD Integration Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    product_id = product["id"]

    read = await service.get_product_visual_readiness(product_id)
    assert read["current_system_visual"] == {
        "card": "ORIGINAL_SOURCE",
        "label": "Original Source",
        "status": "ORIGINAL_FALLBACK",
    }
    assert read["provider_operations"] == 0

    auto_bytes = _cutout_bytes((190, 70, 60), (32, 32))
    auto_calls = 0

    async def fake_auto_cutout(_source_path, roi=None, roi_source_sha256=None):
        nonlocal auto_calls
        auto_calls += 1
        assert roi is None
        assert roi_source_sha256 is None
        return (
            auto_bytes,
            {"x": 0.1875, "y": 0.15625, "w": 0.625, "h": 0.71875, "anchor_x": 0.5, "anchor_y": 0.515625},
            service._sha256_bytes(auto_bytes),
            0.001,
            "deterministic-compositor",
            "PRODUCT_ISOLATION_REVIEW_REQUIRED",
            "OK",
        )

    monkeypatch.setattr(service, "_run_auto_cutout", fake_auto_cutout)

    prepared = await service.prepare_product_cutout(product_id)
    assert auto_calls == 1
    assert prepared["auto_cutout_status"] == "PENDING_REVIEW"
    assert prepared["provider_operations"] == 0

    after_auto = await service.get_product_visual_readiness(product_id)
    assert after_auto["auto_cutout_status"] == "PENDING_REVIEW"
    assert after_auto["current_system_visual"]["card"] == "ORIGINAL_SOURCE"
    assert after_auto["auto_cutout_preview_url"]
    assert after_auto["provider_operations"] == 0
    auto_preview = await service.resolve_product_visual_preview(product_id, "auto")
    assert auto_preview.read_bytes() == auto_bytes
    with Image.open(auto_preview) as auto_image:
        assert auto_image.size == (32, 32)

    first_manual_bytes = _cutout_bytes((60, 170, 90))
    first_manual = await service.upload_manual_product_cutout(
        product_id,
        filename="manual-first.png",
        content_type="image/png",
        raw_bytes=first_manual_bytes,
        uploaded_by="integration-operator",
    )
    assert first_manual["manual_cutout_status"] == "PENDING_REVIEW"
    assert first_manual["current_system_visual"]["card"] == "ORIGINAL_SOURCE"
    first_preview = await service.resolve_product_visual_preview(product_id, "manual")
    assert first_preview.read_bytes() == first_manual_bytes

    second_manual_bytes = _cutout_bytes((70, 90, 210))
    replaced = await service.upload_manual_product_cutout(
        product_id,
        filename="manual-replacement.png",
        content_type="image/png",
        raw_bytes=second_manual_bytes,
        uploaded_by="integration-operator",
    )
    assert replaced["manual_cutout_status"] == "PENDING_REVIEW"
    assert replaced["current_system_visual"]["card"] == "ORIGINAL_SOURCE"
    assert replaced["provider_operations"] == 0
    replacement_preview = await service.resolve_product_visual_preview(product_id, "manual")
    assert replacement_preview.read_bytes() == second_manual_bytes
    assert replacement_preview.read_bytes() != first_preview.read_bytes()

    saved = await service.save_product_visual_setup(
        product_id,
        selected_visual="MANUAL",
        reviewed_by="integration-operator",
        review_note="Identity, label/logo, geometry/scale, and product isolation verified.",
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
        confirm_product_isolation=True,
    )
    assert saved["current_system_visual"] == {
        "card": "MANUAL_CUTOUT",
        "label": "Manual / Canva Cutout",
        "status": "OFFICIAL",
    }
    assert saved["provider_operations"] == 0

    refetched = await service.get_product_visual_readiness(product_id)
    assert refetched["current_system_visual"]["card"] == "MANUAL_CUTOUT"
    assert refetched["current_system_visual"]["status"] == "OFFICIAL"
    assert refetched["manual_cutout_status"] == "APPROVED"
    assert refetched["exact_commerce_status"] == "EXACT_COMMERCE_CUTOUT_READY"
    assert refetched["provider_operations"] == 0
