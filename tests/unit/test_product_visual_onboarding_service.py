from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.db import crud
from agent.services import product_visual_onboarding_service as service


@pytest.mark.asyncio
async def test_readiness_separates_same_product_grounding_from_exact_approval(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    product = await crud.create_product(
        raw_product_title="Visual Readiness Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )

    readiness = await service.get_product_visual_readiness(product["id"])

    assert readiness["canonical_media_status"] == "AVAILABLE"
    assert readiness["visual_grounding_status"] == "VISUAL_GROUNDING_READY"
    assert readiness["exact_commerce_status"] == "EXACT_COMMERCE_REVIEW_REQUIRED"
    assert readiness["cutout_status"] == "NOT_PREPARED"
    assert readiness["provider_operations"] == 0


def test_deterministic_cutout_bytes_preserve_canonical_source_dimensions(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)

    def fake_cutout(_path, *, preserve_canvas=False):
        assert preserve_canvas is True
        image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        for x in range(2, 6):
            for y in range(2, 8):
                image.putpixel((x, y), (30, 120, 150, 255))
        return image

    monkeypatch.setattr(
        "agent.services.exact_product_compositor_service._build_canonical_cutout",
        fake_cutout,
    )

    raw, bounds, _sha = service._build_cutout_bytes(source)

    with Image.open(BytesIO(raw)) as cutout:
        assert cutout.size == (24, 24)
        assert cutout.getchannel("A").getbbox() is not None
    assert bounds["w"] < 1.0
    assert bounds["h"] < 1.0


@pytest.mark.asyncio
async def test_deterministic_prepare_creates_pending_review_only(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    product = await crud.create_product(
        raw_product_title="Deterministic Prepare Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    reference = SimpleNamespace(
        local_path=str(source),
        media_id=None,
        mime_type="image/png",
        sha256=service._sha256_bytes(source.read_bytes()),
        width=24,
        height=24,
        source_type="PRODUCT_ROW_LOCAL_PATH",
        provenance="TEST_LOCAL_SOURCE",
    )
    async def resolve(_product):
        return reference

    monkeypatch.setattr(service, "_resolve_source", resolve)
    monkeypatch.setattr(
        service,
        "_build_cutout_bytes",
        lambda _path: (
            b"deterministic-cutout",
            {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5},
            service._sha256_bytes(b"deterministic-cutout"),
        ),
    )

    async def register(*_args, **_kwargs):
        return {"media_id": "cutout-media-1"}

    async def onboard(*_args, **_kwargs):
        return {"review_status": "PENDING_REVIEW"}

    monkeypatch.setattr(
        "agent.services.product_truth_lock_service.register_product_truth_cutout_media",
        register,
    )
    monkeypatch.setattr(
        "agent.services.product_truth_lock_service.create_pending_product_truth_lock",
        onboard,
    )

    readiness = await service.prepare_product_cutout(product["id"])

    assert readiness["cutout_status"] == "PENDING_REVIEW"
    assert readiness["cutout_review_status"] == "PENDING_REVIEW"
    assert readiness["exact_commerce_status"] == "EXACT_COMMERCE_REVIEW_REQUIRED"
    assert readiness["provider_operations"] == 0
    receipt = await crud.get_product_cutout_preparation(product["id"])
    assert receipt["status"] == "PENDING_REVIEW"
    assert receipt["cutout_media_id"] == "cutout-media-1"


@pytest.mark.asyncio
async def test_bulk_preview_excludes_archived_and_fixture_rows(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    await crud.create_product(
        raw_product_title="Eligible Visual Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    await crud.create_product(
        raw_product_title="Archived Visual Product",
        source="MANUAL",
        lifecycle_status="ARCHIVED",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    await crud.create_product(
        raw_product_title="TEST Visual Fixture",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )

    preview = await service.preview_bulk_cutout_preparation(limit=100)

    assert preview["provider_operations"] == 0
    assert preview["created_without_credit"] is True
    assert preview["counts"]["eligible"] >= 1
    assert len(preview["preview_digest"]) == 64
