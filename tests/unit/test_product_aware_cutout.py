"""Product-AWARE cutout tests: background-removal success must NOT be conflated
with product isolation. Covers the CHEEZY GARLIC "jar + bread both retained"
failure — ambiguity detection, operator ROI targeting, ROI safety, and the split
file-quality vs product-isolation contract. All numpy-free (inference is mocked),
so they run in the backend pytest gate.
"""

from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from agent.services import local_cutout_engine as engine


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    engine._sha_verified.clear()
    engine.reset_session_for_tests()
    yield
    engine._sha_verified.clear()
    engine.reset_session_for_tests()


def _source_png(w=800, h=1000):
    img = Image.new("RGB", (w, h), (235, 238, 242))
    ImageDraw.Draw(img).rectangle([300, 300, 500, 800], fill=(180, 40, 40))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _one_blob_mask(w=800, h=1000):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).ellipse([320, 320, 480, 780], fill=255)
    return m


def _two_blob_mask(w=800, h=1000):
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([120, 400, 340, 640], fill=255)   # e.g. bread
    d.ellipse([500, 300, 700, 760], fill=255)   # e.g. jar
    return m


# ── ambiguity / suitability ──────────────────────────────────
def test_single_object_source_needs_review_not_target_selection():
    status, n = engine.classify_source_isolation(_one_blob_mask())
    assert status == engine.ISO_REVIEW_REQUIRED and n == 1


def test_multi_object_source_requires_target_selection():
    status, n = engine.classify_source_isolation(_two_blob_mask())
    assert status == engine.ISO_TARGET_SELECTION_REQUIRED and n >= 2


def test_mechanical_file_quality_is_not_product_isolation(monkeypatch):
    # A clean, mechanically-valid cutout of an AMBIGUOUS source: file quality OK,
    # but product isolation must NOT be asserted (target selection required).
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    monkeypatch.setattr(engine, "_infer_mask", lambda rgb: _two_blob_mask(*rgb.size))
    res = engine.prepare(_source_png())
    assert res.ok() is True  # background removal / file quality succeeded
    assert res.product_isolation_status == engine.ISO_TARGET_SELECTION_REQUIRED
    assert res.needs_target_selection() is True
    assert res.isolation_review_ready() is False  # cannot be treated as a correct cutout


# ── ROI validation / safety ──────────────────────────────────
@pytest.mark.parametrize("roi,size,expected", [
    ((100, 100, 200, 300), (800, 1000), None),
    ((0, 0, 0, 100), (800, 1000), engine.ROI_INVALID),      # zero width
    ((-10, 0, 100, 100), (800, 1000), engine.ROI_INVALID),  # negative origin
    ((700, 0, 200, 100), (800, 1000), engine.ROI_INVALID),  # x+w outside
    ((0, 0, 5, 5), (800, 1000), engine.ROI_TOO_SMALL),      # tiny
])
def test_validate_roi(roi, size, expected):
    assert engine.validate_roi(roi, size) == expected


# ── ROI cutout: product-only, same-canvas ────────────────────
def test_roi_infer_keeps_only_roi_and_preserves_full_canvas(monkeypatch):
    # inference returns an all-foreground mask for whatever crop it is given
    monkeypatch.setattr(engine, "_infer_mask", lambda crop: Image.new("L", crop.size, 255))
    src = Image.new("RGB", (800, 1000), (10, 20, 30))
    roi = (500, 300, 200, 460)  # the "jar" region
    mask = engine._infer_mask_roi(src, roi)
    assert mask.size == (800, 1000)                 # full canvas preserved
    assert mask.getpixel((600, 500)) == 255         # inside ROI opaque
    assert mask.getpixel((200, 500)) == 0           # outside ROI (bread) transparent
    assert mask.getbbox() == (500, 300, 700, 760)   # foreground confined to ROI


def test_prepare_with_roi_isolates_product_same_canvas(monkeypatch):
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    monkeypatch.setattr(engine, "_infer_mask", lambda crop: Image.new("L", crop.size, 255))
    raw = _source_png(800, 1000)
    roi = (500, 300, 200, 460)
    res = engine.prepare(raw, roi=roi)
    assert res.ok() and res.roi == roi
    assert res.product_isolation_status == engine.ISO_REVIEW_REQUIRED  # operator-targeted -> human review
    assert (res.output_width, res.output_height) == (800, 1000)        # same canvas
    with Image.open(BytesIO(res.output_bytes)) as out:
        assert out.mode == "RGBA" and out.size == (800, 1000)
        bbox = out.getchannel("A").getbbox()
        # opaque region confined to the ROI (bread outside stays transparent)
        assert bbox is not None and bbox[0] >= 500 and bbox[2] <= 700


def test_prepare_roi_source_changed_fails_closed(monkeypatch):
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    raw = _source_png()
    res = engine.prepare(raw, roi=(100, 100, 200, 300), roi_source_sha256="deadbeef")
    assert res.failure_code == engine.ROI_SOURCE_CHANGED and res.output_bytes is None


def test_prepare_roi_invalid_geometry_fails_closed(monkeypatch):
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    res = engine.prepare(_source_png(800, 1000), roi=(0, 0, 5, 5))
    assert res.failure_code == engine.ROI_TOO_SMALL


def test_prepare_full_frame_single_object_is_review_required(monkeypatch):
    monkeypatch.setattr(engine, "readiness", lambda **_k: {"state": engine.EngineReadiness.READY.value})
    monkeypatch.setattr(engine, "_infer_mask", lambda rgb: _one_blob_mask(*rgb.size))
    res = engine.prepare(_source_png())
    assert res.ok() and res.product_isolation_status == engine.ISO_REVIEW_REQUIRED
    assert res.roi is None
