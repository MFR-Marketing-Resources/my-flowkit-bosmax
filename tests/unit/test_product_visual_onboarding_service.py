from io import BytesIO
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from agent.db import crud
from agent.services import product_visual_onboarding_service as service


def _standard_cutout_bytes(color=(40, 80, 120)) -> bytes:
    image = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    for x in range(200, 800):
        for y in range(120, 880):
            image.putpixel((x, y), (*color, 255))
    stream = BytesIO()
    image.save(stream, format="PNG")
    image.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_readiness_separates_same_product_grounding_from_exact_approval(tmp_path):
    from agent.config import BASE_DIR
    source = BASE_DIR / "data" / "products" / "images" / "visual-readiness-unit-source.png"
    source.parent.mkdir(parents=True, exist_ok=True)
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
    assert readiness["visual_grounding_status"] == "VISUAL_GROUNDING_READY_FALLBACK"
    assert readiness["exact_commerce_status"] == "CUTOUT_REQUIRED"
    assert readiness["cutout_status"] == "NOT_PREPARED"
    assert readiness["can_use_original_fallback"] is True
    assert readiness["provider_operations"] == 0
    assert readiness["visual_canvas_width"] == 1000
    assert readiness["visual_canvas_height"] == 1000
    assert readiness["visual_canvas_label"] == "1000×1000 px"
    assert product["visual_canvas_width"] == 1000
    assert product["visual_canvas_height"] == 1000
    assert "1000x1000 px canvas" in product["visual_canvas_requirement"]


def test_url_only_display_source_stays_untrusted_but_manual_lane_is_available():
    readiness = service._readiness_payload(
        {"id": "missing-source", "image_url": "https://example.test/product.jpg"},
        lock=None,
        pack=None,
        prep=None,
        reference=None,
        source_available=False,
    )

    assert readiness["visual_grounding_source"] == "SOURCE_NOT_RESOLVED"
    assert readiness["original_preview_url"] is None
    assert readiness["original_display_url"] == "https://example.test/product.jpg"
    assert readiness["original_display_source"] == "PRODUCT_ROW_IMAGE_URL"
    assert readiness["original_display_trust_status"] == "DISPLAY_ONLY"
    assert readiness["canonical_media_status"] == "MISSING"
    assert readiness["can_prepare_cutout"] is True
    assert readiness["auto_input_preview_url"] == "https://example.test/product.jpg"
    assert readiness["auto_input_source"] == "ORIGINAL_SOURCE_INPUT"
    assert readiness["can_upload_manual_cutout"] is True
    assert readiness["can_start_canva_cutout"] is False
    assert readiness["can_open_source"] is True


def test_display_source_follows_product_header_fallbacks_without_promoting_trust():
    rendered_only = service._readiness_payload(
        {
            "id": "rendered-only",
            "rendered_img_src": "https://example.test/rendered-product.jpg",
        },
        lock=None,
        pack=None,
        prep=None,
        reference=None,
        source_available=False,
    )
    assert rendered_only["original_display_url"] == "https://example.test/rendered-product.jpg"
    assert rendered_only["original_display_source"] == "PRODUCT_RENDERED_IMAGE_URL"
    assert rendered_only["original_display_trust_status"] == "DISPLAY_ONLY"
    assert rendered_only["can_upload_manual_cutout"] is True

    analysis_only = service._readiness_payload(
        {
            "id": "analysis-only",
            "image_analysis": {"image_url": "https://example.test/analysis-product.jpg"},
        },
        lock=None,
        pack=None,
        prep=None,
        reference=None,
        source_available=False,
    )
    assert analysis_only["original_display_url"] == "https://example.test/analysis-product.jpg"
    assert analysis_only["original_display_source"] == "PRODUCT_IMAGE_ANALYSIS_URL"
    assert analysis_only["original_display_trust_status"] == "DISPLAY_ONLY"


def test_missing_source_has_no_display_or_manual_action():
    readiness = service._readiness_payload(
        {"id": "missing-source"},
        lock=None,
        pack=None,
        prep=None,
        reference=None,
        source_available=False,
    )

    assert readiness["original_display_url"] is None
    assert readiness["original_display_source"] == "UNAVAILABLE"
    assert readiness["original_display_trust_status"] == "UNAVAILABLE"
    assert readiness["can_upload_manual_cutout"] is False
    assert readiness["can_open_source"] is False


@pytest.mark.asyncio
async def test_display_only_generate_uses_the_existing_write_lane_materialization(tmp_path, monkeypatch):
    source = tmp_path / "display-source.png"
    Image.new("RGB", (24, 24), (40, 80, 120)).save(source)
    product = await crud.create_product(
        raw_product_title="Display Only Generate Product",
        source="MANUAL",
        image_url="https://example.test/display-source.png",
        image_asset_status="UNRESOLVED",
        asset_status="UNRESOLVED",
    )
    reference = SimpleNamespace(
        local_path=str(source),
        media_id=None,
        mime_type="image/png",
        sha256=service._sha256_bytes(source.read_bytes()),
        width=24,
        height=24,
        source_type="PRODUCT_ROW_IMAGE_URL",
        provenance="PRODUCT_DATABASE_RECORD",
    )
    ensured: list[str] = []

    async def resolve(_product):
        return reference

    async def ensure(_product, _reference):
        ensured.append(str(_reference.local_path))
        return "source-media-display-only"

    async def local_cutout(*_args, **_kwargs):
        generated = _standard_cutout_bytes()
        return (
            generated,
            {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5},
            service._sha256_bytes(generated),
            0.01,
            "local-u2net-test",
            "OK",
            "OK",
        )

    monkeypatch.setattr(service, "_resolve_source", resolve)
    monkeypatch.setattr(service, "_ensure_canonical_media", ensure)
    monkeypatch.setattr(service, "_run_auto_cutout", local_cutout)
    monkeypatch.setattr("agent.services.product_truth_lock_service.register_product_truth_cutout_media", AsyncMock(return_value={"media_id": "auto-media-display-only"}))
    monkeypatch.setattr("agent.services.product_truth_lock_service.create_pending_product_truth_lock", AsyncMock(return_value={"review_status": "PENDING_REVIEW"}))

    readiness = await service.prepare_product_cutout(product["id"])

    assert ensured == [str(source)]
    assert readiness["cutout_status"] == "PENDING_REVIEW"
    assert readiness["cutout_media_id"] == "auto-media-display-only"
    assert readiness["provider_operations"] == 0


@pytest.mark.asyncio
async def test_save_original_delegates_to_existing_fallback_authority(monkeypatch):
    product = {"id": "save-original-product"}
    readiness = {
        "current_system_visual": {"card": "AUTO_CUTOUT"},
        "can_use_original_fallback": True,
        "auto_cutout_status": "APPROVED",
        "manual_cutout_status": "NOT_UPLOADED",
    }
    monkeypatch.setattr(service.crud, "get_product", AsyncMock(return_value=product))
    monkeypatch.setattr(service, "_blocked_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_product_visual_readiness", AsyncMock(return_value=readiness))
    calls: list[dict[str, str]] = []

    async def use_fallback(product_id, *, selected_by, reason):
        calls.append({"product_id": product_id, "selected_by": selected_by, "reason": reason})
        return {"current_system_visual": {"card": "ORIGINAL_SOURCE"}}

    monkeypatch.setattr(service, "use_original_product_fallback", use_fallback)
    result = await service.save_product_visual_setup(
        "save-original-product",
        selected_visual="ORIGINAL",
        reviewed_by="operator-1",
        review_note="Use the verified original source.",
    )

    assert calls == [{
        "product_id": "save-original-product",
        "selected_by": "operator-1",
        "reason": "Use the verified original source.",
    }]
    assert result["current_system_visual"]["card"] == "ORIGINAL_SOURCE"


@pytest.mark.asyncio
async def test_save_pending_auto_requires_existing_review_confirmations(monkeypatch):
    product = {"id": "save-auto-product"}
    pending = {
        "current_system_visual": {"card": "ORIGINAL_SOURCE"},
        "can_use_original_fallback": True,
        "can_review_cutout": True,
        "auto_cutout_status": "PENDING_REVIEW",
        "manual_cutout_status": "NOT_UPLOADED",
    }
    monkeypatch.setattr(service.crud, "get_product", AsyncMock(return_value=product))
    monkeypatch.setattr(service, "_blocked_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_product_visual_readiness", AsyncMock(return_value=pending))
    monkeypatch.setattr(service.crud, "get_product_truth_lock", AsyncMock(return_value={
        "review_status": "PENDING_REVIEW",
        "provenance_json": '{"source_kind":"AUTO_GENERATED"}',
    }))
    approval_calls: list[object] = []

    async def approve(product_id, request):
        approval_calls.append(request)
        return {"product_id": product_id, "review_status": "APPROVED"}

    monkeypatch.setattr(service, "approve_product_truth_lock", approve)

    with pytest.raises(service.ProductVisualOnboardingError) as raised:
        await service.save_product_visual_setup(
            "save-auto-product",
            selected_visual="AUTO",
            reviewed_by="reviewer-1",
            review_note="Reviewed candidate.",
        )

    assert raised.value.code == "HUMAN_REVIEW_CONFIRMATION_REQUIRED"
    assert approval_calls == []


@pytest.mark.asyncio
async def test_save_pending_auto_uses_existing_approval_authority_and_refetches(monkeypatch):
    product = {"id": "save-auto-product"}
    pending = {
        "current_system_visual": {"card": "ORIGINAL_SOURCE"},
        "can_review_cutout": True,
        "auto_cutout_status": "PENDING_REVIEW",
        "manual_cutout_status": "NOT_UPLOADED",
    }
    approved = {
        "current_system_visual": {"card": "AUTO_CUTOUT"},
        "auto_cutout_status": "APPROVED",
        "manual_cutout_status": "NOT_UPLOADED",
    }
    monkeypatch.setattr(service.crud, "get_product", AsyncMock(return_value=product))
    monkeypatch.setattr(service, "_blocked_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "get_product_visual_readiness", AsyncMock(side_effect=[pending, approved]))
    monkeypatch.setattr(service.crud, "get_product_truth_lock", AsyncMock(return_value={
        "review_status": "PENDING_REVIEW",
        "provenance_json": '{"source_kind":"AUTO_GENERATED"}',
    }))
    approval_calls: list[tuple[str, object]] = []

    async def approve(product_id, request):
        approval_calls.append((product_id, request))
        return {"review_status": "APPROVED"}

    monkeypatch.setattr(service, "approve_product_truth_lock", approve)

    result = await service.save_product_visual_setup(
        "save-auto-product",
        selected_visual="AUTO",
        reviewed_by="reviewer-1",
        review_note="Reviewed candidate.",
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
        confirm_product_isolation=True,
    )

    assert result == approved
    assert len(approval_calls) == 1
    assert approval_calls[0][0] == "save-auto-product"
    assert approval_calls[0][1].reviewed_by == "reviewer-1"


def test_trusted_source_display_uses_governed_preview_endpoint():
    readiness = service._readiness_payload(
        {"id": "trusted-source"},
        lock=None,
        pack=None,
        prep=None,
        reference=SimpleNamespace(source_type="PRODUCT_ROW_LOCAL_PATH"),
        source_available=True,
    )

    assert readiness["original_display_url"] == "/api/product-visual-onboarding/trusted-source/cutout/preview/original"
    assert readiness["original_display_source"] == "TRUSTED_SAME_PRODUCT_SOURCE"
    assert readiness["original_display_trust_status"] == "TRUSTED"
    assert readiness["original_preview_url"] == readiness["original_display_url"]


def test_reference_pack_source_is_trusted_display(tmp_path):
    pack_source = tmp_path / "reference-pack-source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(pack_source)
    pack = {
        "references_json": json.dumps([
            {"role": "PRODUCT_CANONICAL", "local_file_path": str(pack_source)},
        ]),
    }

    readiness = service._readiness_payload(
        {"id": "pack-source"},
        lock=None,
        pack=pack,
        prep=None,
        reference=None,
        source_available=bool(service._reference_pack_file(pack)),
    )

    assert readiness["original_display_source"] == "TRUSTED_SAME_PRODUCT_SOURCE"
    assert readiness["original_display_trust_status"] == "TRUSTED"
    assert readiness["original_display_url"].endswith("/pack-source/cutout/preview/original")


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

    deterministic_cutout = _standard_cutout_bytes()
    monkeypatch.setattr(service, "_resolve_source", resolve)
    monkeypatch.setattr(
        service,
        "_build_cutout_bytes",
        lambda _path: (
            deterministic_cutout,
            {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "anchor_x": 0.5, "anchor_y": 0.5},
            service._sha256_bytes(deterministic_cutout),
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
    assert readiness["exact_commerce_status"] == "CUTOUT_REQUIRED"
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


def test_manual_approved_candidate_outranks_superseded_auto_candidate():
    product = {"id": "product-1"}
    manual_lock = {
        "review_status": "APPROVED",
        "canonical_cutout_path": "data/exact-product/manual.png",
        "provenance_json": '{"source_kind":"USER_UPLOAD","active_selection":"APPROVED_CANONICAL_CUTOUT"}',
    }
    readiness = service._readiness_payload(
        product,
        lock=manual_lock,
        pack=None,
        prep=None,
        reference=None,
        source_available=True,
        history=[
            {
                "source_kind": "AUTO_GENERATED",
                "review_status": "APPROVED",
                "provenance_json": "{}",
            }
        ],
    )

    assert readiness["active_visual_source"] == "APPROVED_MANUAL_CANONICAL_CUTOUT"
    assert readiness["exact_commerce_status"] == "EXACT_COMMERCE_CUTOUT_READY"
    assert readiness["manual_cutout_status"] == "APPROVED"
    assert readiness["auto_cutout_status"] == "SUPERSEDED"


def test_rejected_auto_candidate_routes_to_trusted_fallback():
    readiness = service._readiness_payload(
        {"id": "product-1"},
        lock={
            "review_status": "REJECTED",
            "provenance_json": '{"source_kind":"AUTO_GENERATED","review_status":"REJECTED_BY_USER","active_selection":"SAME_PRODUCT_TRUSTED_SOURCE"}',
        },
        pack=None,
        prep={"status": "PREPARATION_FAILED", "failure_code": "REJECTED_BY_USER"},
        reference=None,
        source_available=True,
        history=[],
    )

    assert readiness["auto_cutout_status"] == "REJECTED"
    assert readiness["active_visual_source"] == "SAME_PRODUCT_TRUSTED_SOURCE"
    assert readiness["visual_grounding_status"] == "VISUAL_GROUNDING_READY_FALLBACK"
    assert readiness["exact_commerce_status"] == "CUTOUT_REQUIRED"


@pytest.mark.asyncio
async def test_manual_upload_is_pending_and_uses_user_provenance(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    Image.new("RGB", (24, 24), (30, 120, 150)).save(source)
    product = await crud.create_product(
        raw_product_title="Manual Override Product",
        source="MANUAL",
        local_image_path=str(source),
        image_asset_status="READY",
        asset_status="DOWNLOADED",
    )
    buffer = BytesIO(_standard_cutout_bytes())
    captured: dict[str, object] = {}
    reference = SimpleNamespace(width=24, height=24, sha256=service._sha256_bytes(source.read_bytes()), local_path=str(source))

    async def resolve(_product):
        return reference

    async def register(*_args, **kwargs):
        captured["register"] = kwargs
        return {"media_id": "manual-media-1"}

    async def onboard(*_args, **kwargs):
        captured["onboard"] = kwargs
        return {"review_status": "PENDING_REVIEW"}

    async def readiness(_product_id):
        return {"cutout_status": "PENDING_REVIEW", "exact_commerce_status": "CUTOUT_REQUIRED"}

    monkeypatch.setattr(service, "_resolve_source", resolve)
    async def ensure_media(_product, _reference):
        captured["canonical_source"] = _reference
        return "source-media-1"

    monkeypatch.setattr(service, "_ensure_canonical_media", ensure_media)
    monkeypatch.setattr(service, "register_product_truth_cutout_media", register)
    monkeypatch.setattr(service, "create_pending_product_truth_lock", onboard)
    monkeypatch.setattr(service, "get_product_visual_readiness", readiness)

    result = await service.upload_manual_product_cutout(
        product["id"],
        filename=r"..\operator\manual.png",
        content_type="image/png",
        raw_bytes=buffer.getvalue(),
        uploaded_by="operator-1",
    )

    assert result["cutout_status"] == "PENDING_REVIEW"
    assert captured["register"]["content_type"] == "image/png"
    assert captured["onboard"]["allow_approved_replacement"] is True
    assert captured["onboard"]["source_kind"] == "USER_UPLOAD"
    assert captured["onboard"]["uploaded_by"] == "operator-1"
    assert captured["onboard"]["original_filename"] == r"..\operator\manual.png"
    assert captured["canonical_source"] is reference



@pytest.mark.asyncio
async def test_product_source_media_only_source_matches_original_preview(tmp_path, monkeypatch):
    """PSM-only byte source: readiness and original preview share one authority."""
    source = tmp_path / "psm-only.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(source)
    from agent.config import BASE_DIR
    hosted = BASE_DIR / "data" / "products" / "images" / f"psm-only-test-{source.name}"
    hosted.parent.mkdir(parents=True, exist_ok=True)
    hosted.write_bytes(source.read_bytes())

    product = await crud.create_product(
        raw_product_title="PSM Only Source Product",
        source="MANUAL",
        image_url="https://example.test/remote-only.jpg",
        image_asset_status="UNRESOLVED",
        asset_status="UNRESOLVED",
    )
    media = await crud.create_product_source_media(
        f"visual-source:{product['id']}",
        "image",
        product_id=product["id"],
        local_path=str(hosted),
        filename=hosted.name,
        mime="image/png",
        bytes=hosted.stat().st_size,
        width=32,
        height=32,
        status="STORED",
    )
    assert media and media.get("media_id")

    readiness = await service.get_product_visual_readiness(product["id"])
    assert readiness["canonical_media_status"] == "AVAILABLE"
    assert readiness["original_preview_url"] == (
        f"/api/product-visual-onboarding/{product['id']}/cutout/preview/original"
    )
    assert readiness["original_display_trust_status"] == "TRUSTED"

    preview_path = await service.resolve_product_visual_preview(product["id"], "original")
    assert preview_path.is_file()
    assert preview_path.resolve() == hosted.resolve()
    fresh = await crud.get_product(product["id"])
    assert not (fresh or {}).get("local_image_path")


@pytest.mark.asyncio
async def test_url_only_readiness_stays_display_only_without_materialize(monkeypatch):
    product = await crud.create_product(
        raw_product_title="URL Only Display Product",
        source="MANUAL",
        image_url="https://cdn.example.com/image.jpg?signature=ABC&expires=123",
        image_asset_status="UNRESOLVED",
        asset_status="UNRESOLVED",
    )

    def boom(*_a, **_k):
        raise AssertionError("resolve must not materialize remote URLs on readiness GET")

    monkeypatch.setattr(
        "agent.services.product_visual_grounding_resolver._materialize_image_url",
        boom,
    )
    readiness = await service.get_product_visual_readiness(product["id"])
    assert readiness["original_preview_url"] is None
    assert readiness["original_display_url"] == "https://cdn.example.com/image.jpg?signature=ABC&expires=123"
    assert readiness["original_display_trust_status"] == "DISPLAY_ONLY"
    assert readiness["canonical_media_status"] == "MISSING"


def test_candidate_missing_bytes_emits_null_preview_urls(tmp_path):
    lock = {
        "review_status": "PENDING_REVIEW",
        "canonical_cutout_path": str(tmp_path / "missing-auto.png"),
        "provenance_json": json.dumps({"source_kind": "AUTO_GENERATED", "created_by": "system:cutout"}),
    }
    readiness = service._readiness_payload(
        {"id": "missing-bytes"},
        lock=lock,
        pack=None,
        prep={"status": "PENDING_REVIEW"},
        reference=None,
        source_available=True,
        history=[],
    )
    assert readiness["auto_cutout_status"] == "PENDING_REVIEW"
    assert readiness["auto_cutout_preview_url"] is None
    assert readiness["active_cutout_preview_url"] is None
    assert readiness["cutout_preview_available"] is False


def test_rejected_candidate_missing_bytes_has_no_preview_url(tmp_path):
    lock = {
        "review_status": "REJECTED",
        "canonical_cutout_path": str(tmp_path / "gone-manual.png"),
        "provenance_json": json.dumps({"source_kind": "USER_UPLOAD", "created_by": "operator"}),
    }
    readiness = service._readiness_payload(
        {"id": "rejected-missing"},
        lock=lock,
        pack=None,
        prep={"status": "REJECTED"},
        reference=None,
        source_available=True,
        history=[],
    )
    assert readiness["manual_cutout_status"] == "REJECTED"
    assert readiness["manual_cutout_preview_url"] is None


def test_rejected_candidate_with_valid_bytes_keeps_preview(tmp_path):
    from agent.config import BASE_DIR
    cutout = BASE_DIR / "data" / "products" / "images" / "rejected-valid-cutout.png"
    cutout.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(cutout)
    lock = {
        "review_status": "REJECTED",
        "canonical_cutout_path": str(cutout),
        "provenance_json": json.dumps({"source_kind": "USER_UPLOAD", "created_by": "operator"}),
    }
    readiness = service._readiness_payload(
        {"id": "rejected-valid"},
        lock=lock,
        pack=None,
        prep={"status": "REJECTED"},
        reference=None,
        source_available=True,
        history=[],
    )
    assert readiness["manual_cutout_status"] == "REJECTED"
    assert readiness["manual_cutout_preview_url"] == (
        "/api/product-visual-onboarding/rejected-valid/cutout/preview/manual"
    )
    assert readiness["active_visual_source"] != "APPROVED_MANUAL_CANONICAL_CUTOUT"


def test_active_approved_emits_preview_only_when_bytes_exist(tmp_path):
    from agent.config import BASE_DIR
    cutout = BASE_DIR / "data" / "products" / "images" / "approved-valid-cutout.png"
    cutout.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (9, 9, 9, 255)).save(cutout)
    lock = {
        "review_status": "APPROVED",
        "canonical_cutout_path": str(cutout),
        "canonical_cutout_media_id": "mid-1",
        "provenance_json": json.dumps({
            "source_kind": "AUTO_GENERATED",
            "created_by": "system:cutout",
            "active_selection": "AUTO",
        }),
    }
    ok = service._readiness_payload(
        {"id": "approved-ok"},
        lock=lock,
        pack=None,
        prep={"status": "APPROVED"},
        reference=None,
        source_available=True,
        history=[],
    )
    assert ok["auto_cutout_status"] == "APPROVED"
    assert ok["auto_cutout_preview_url"]
    assert ok["active_cutout_preview_url"]

    broken = dict(lock)
    broken["canonical_cutout_path"] = str(tmp_path / "missing-approved.png")
    bad = service._readiness_payload(
        {"id": "approved-bad"},
        lock=broken,
        pack=None,
        prep={"status": "APPROVED"},
        reference=None,
        source_available=True,
        history=[],
    )
    assert bad["active_cutout_preview_url"] is None
    assert bad["auto_cutout_preview_url"] is None
