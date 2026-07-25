import hashlib
from pathlib import Path

from PIL import Image

from agent.services.exact_product_compositor_service import composite, prepare_layer


def test_exact_product_cutout_composite_preserves_transformed_pixels(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    original = Image.new("RGBA", (40, 60), (250, 250, 250, 255))
    for y in range(10, 55):
        for x in range(10, 30):
            original.putpixel((x, y), (12, 100, 70, 255))
    original.save(source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    entry = {"on_the_fly_flags": {"exact_product_composite_required": True}, "canonical_product_photo": {"source_path": str(source), "sha256": digest}}
    monkeypatch.setattr("agent.services.exact_product_compositor_service.resolve_schema_entry", lambda _: entry)
    layer = prepare_layer({}, {"x": 10, "y": 10, "w": 60, "h": 70}, {"w": 1080, "h": 1920})
    assert layer["source_sha256"] == digest
    assert layer["transform"]["perspective_skew_x"] == 0.0
    target = tmp_path / "poster.png"
    Image.new("RGBA", (1080, 1920), (255, 240, 220, 255)).save(target)
    integrity = composite(target, layer)
    assert integrity["composition_ok"] is True
    assert integrity["pixel_match"] is True
    assert integrity["attestation"] == "ALPHA_AWARE_TRANSFORMED_CUTOUT_EXACT_MATCH"
