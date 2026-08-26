"""Product-geometry-custody regression tests.

The official product visual's apparent scale must be GOVERNED (a function of the
product's own canonical frame), never a per-lane occupancy, and canvas expansion
must never rescale the product. See owner directive 2026-08-26.
"""
from PIL import Image, ImageChops

import agent.services.exact_product_compositor_service as svc


def _mk_validation(tmp_path):
    # Canonical 1000x1000 cutout with an off-centre opaque product region so the
    # alpha bbox is a real sub-rectangle of the frame.
    cut = Image.new("RGBA", (1000, 1000), (0, 0, 0, 0))
    product = Image.new("RGBA", (400, 600), (200, 180, 160, 255))
    cut.paste(product, (300, 250))
    cutout_path = tmp_path / "cutout.png"
    cut.save(cutout_path)
    return {
        "product_id": "p-geom",
        "schema_key": "PRODUCT_TRUTH_LOCK",
        "source_path": str(cutout_path),
        "source_sha256": "srcsha",
        "dimensions": "1000x1000",
        "canonical_media_id": "cmid",
        "cutout_path": str(cutout_path),
        "cutout_media_id": "cutmid",
        "cutout_sha256": "cutsha",
        "alpha_mask_sha256": "masksha",
        "allowed_bbox": {"x": 0.30, "y": 0.25, "w": 0.40, "h": 0.60},
        "anchor_point": {"x": 0.5, "y": 0.5},
        "min_scale": 0.05,
        "max_scale": 4.0,
        "allowed_rotation": 0.0,
        "allowed_perspective": 0.0,
        "product_truth_lock_schema_version": "v1",
    }


def _patch(monkeypatch, validation):
    monkeypatch.setattr(svc, "validate_canonical_or_raise", lambda product: validation)
    monkeypatch.setattr(svc, "exact_product_policy", lambda product: {"required": True})


def test_J_scale_is_lane_independent(monkeypatch, tmp_path):
    """REGRESSION (was broken): same product + same canvas, different lane ->
    IDENTICAL product pixel scale. Previously LANE_SAFE_REGIONS x SAFE_REGION_FILL
    made studio and poster differ."""
    _patch(monkeypatch, _mk_validation(tmp_path))
    canvas = {"w": 720, "h": 1280}
    studio = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], canvas)
    poster = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["poster"], canvas)
    assert studio["transform"]["scale"] == poster["transform"]["scale"]
    assert (studio["transform"]["w"], studio["transform"]["h"]) == (
        poster["transform"]["w"],
        poster["transform"]["h"],
    )


def test_C_canvas_expansion_does_not_rescale_product(monkeypatch, tmp_path):
    """Expanding the canvas (taller, same width) must NOT change the product's
    rendered pixel dimensions -- only padding grows."""
    _patch(monkeypatch, _mk_validation(tmp_path))
    base = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1280})
    taller = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1920})
    assert base["transform"]["scale"] == taller["transform"]["scale"]
    assert (base["transform"]["w"], base["transform"]["h"]) == (
        taller["transform"]["w"],
        taller["transform"]["h"],
    )


def test_governed_scale_maps_canonical_frame_to_canvas(monkeypatch, tmp_path):
    """The governed scale is min(cw,ch)/frame_dim -- derived from the product's own
    canonical frame, not any lane region."""
    _patch(monkeypatch, _mk_validation(tmp_path))
    layer = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1280})
    # frame is 1000x1000, canvas 720x1280 -> governed scale = 720/1000 = 0.72
    assert abs(layer["transform"]["scale"] - 0.72) < 1e-6
    # product alpha bbox is 400x600 -> rendered 288x432 at 0.72
    assert layer["transform"]["w"] == round(400 * 0.72)
    assert layer["transform"]["h"] == round(600 * 0.72)


def test_B_plate_carries_geometry_contract(monkeypatch, tmp_path):
    """The geometry-lock contract must be preserved through preparation and pin the
    OFFICIAL visual identity + governed bbox/aspect."""
    _patch(monkeypatch, _mk_validation(tmp_path))
    layer = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1280})
    gc = layer["geometry_contract"]
    assert gc["geometry_lock_enabled"] is True
    assert gc["official_media_id"] == "cmid"
    assert gc["official_sha256"] == "srcsha"
    assert gc["intrinsic_width"] == 1000 and gc["intrinsic_height"] == 1000
    # product alpha bbox 400x600 -> aspect 0.6667, all preserve-flags on
    assert abs(gc["product_aspect_ratio"] - (400 / 600)) < 1e-6
    assert gc["product_bbox_px"]["w"] == 400 and gc["product_bbox_px"]["h"] == 600
    for k in (
        "preserve_silhouette",
        "preserve_label_position",
        "preserve_label_dimensions",
        "preserve_cap_body_base_proportions",
        "preserve_apparent_capacity",
    ):
        assert gc[k] is True


def test_I_changing_official_visual_updates_identity_same_contract(monkeypatch, tmp_path):
    """Changing the official visual updates media_id/sha while the contract shape +
    geometry-preserving behavior are unchanged."""
    v1 = _mk_validation(tmp_path)
    _patch(monkeypatch, v1)
    a = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1280})
    v2 = dict(v1)
    v2["canonical_media_id"] = "cmid-v2"
    v2["source_sha256"] = "srcsha-v2"
    monkeypatch.setattr(svc, "validate_canonical_or_raise", lambda product: v2)
    b = svc.prepare_layer({"id": "p-geom"}, svc.LANE_SAFE_REGIONS["studio"], {"w": 720, "h": 1280})
    assert b["geometry_contract"]["official_media_id"] == "cmid-v2"
    assert b["geometry_contract"]["official_sha256"] == "srcsha-v2"
    # identity changed, but governed scale/geometry behavior identical
    assert a["transform"]["scale"] == b["transform"]["scale"]
    assert a["geometry_contract"]["geometry_lock_enabled"] == b["geometry_contract"]["geometry_lock_enabled"]
