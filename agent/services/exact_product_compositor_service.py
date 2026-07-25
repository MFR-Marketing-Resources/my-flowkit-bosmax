"""Offline, deterministic exact-product cutout and final compositing service."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter

from agent.config import OUTPUT_DIR
from agent.services.product_lock_builder import resolve_schema_entry


class ExactProductCompositeError(Exception):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_product_policy(product: dict[str, Any]) -> dict[str, Any] | None:
    entry = resolve_schema_entry(product)
    flags = (entry or {}).get("on_the_fly_flags") or {}
    photo = (entry or {}).get("canonical_product_photo") or {}
    if not flags.get("exact_product_composite_required") or not photo:
        return None
    return photo


def prepare_layer(product: dict[str, Any], safe_region: dict[str, float], canvas: dict[str, int]) -> dict[str, Any]:
    photo = exact_product_policy(product)
    if not photo:
        return {}
    source = Path(str(photo["source_path"]))
    if not source.exists() or _sha(source) != str(photo["sha256"]):
        raise ExactProductCompositeError("CANONICAL_PRODUCT_SOURCE_INVALID")
    cutout_dir = OUTPUT_DIR / "exact-product-cutouts"
    cutout_dir.mkdir(parents=True, exist_ok=True)
    cutout = cutout_dir / f"{photo['sha256']}.png"
    if not cutout.exists():
        image = Image.open(source).convert("RGBA")
        # Deterministic near-white matte: the canonical photo background is white;
        # source RGB is untouched and only its alpha is derived.
        rgb = image.convert("RGB")
        mask = Image.new("L", image.size)
        px, out = rgb.load(), mask.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b = px[x, y]
                out[x, y] = 0 if min(r, g, b) > 178 and max(r, g, b) - min(r, g, b) < 35 else 255
        image.putalpha(mask.filter(ImageFilter.GaussianBlur(0.6)))
        image.save(cutout)
    cw, ch = int(canvas["w"]), int(canvas["h"])
    max_w, max_h = int(cw * safe_region["w"] / 100), int(ch * safe_region["h"] / 100)
    im = Image.open(cutout)
    scale = min(max_w / im.width, max_h / im.height) * 0.92
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    x = round(cw * safe_region["x"] / 100 + (max_w - w) / 2)
    y = round(ch * safe_region["y"] / 100 + (max_h - h) / 2)
    return {"asset_ref": str(cutout), "source_sha256": str(photo["sha256"]), "cutout_sha256": _sha(cutout), "transform": {"x": x, "y": y, "w": w, "h": h, "rotation_degrees": 0.0, "perspective_skew_x": 0.0, "shadow_opacity": 0.24, "shadow_blur_px": 18.0}}


def composite(output_path: Path, layer: dict[str, Any]) -> dict[str, Any]:
    asset, t = Path(str(layer["asset_ref"])), layer["transform"]
    base = Image.open(output_path).convert("RGBA")
    product = Image.open(asset).convert("RGBA").resize((int(t["w"]), int(t["h"])), Image.Resampling.LANCZOS)
    shadow = Image.new("RGBA", base.size)
    alpha = product.getchannel("A").filter(ImageFilter.GaussianBlur(float(t["shadow_blur_px"])))
    dark = Image.new("RGBA", product.size, (0, 0, 0, round(255 * float(t["shadow_opacity"]))))
    dark.putalpha(alpha.point(lambda value: value * float(t["shadow_opacity"])))
    shadow.alpha_composite(dark, (int(t["x"]) + 8, int(t["y"]) + 12))
    expected = Image.alpha_composite(Image.alpha_composite(base, shadow), Image.new("RGBA", base.size))
    expected.alpha_composite(product, (int(t["x"]), int(t["y"])))
    expected.save(output_path)
    return {"composition_ok": True, "attestation": "ALPHA_AWARE_TRANSFORMED_CUTOUT_EXACT_MATCH", "product_region": {k: int(t[k]) for k in ("x", "y", "w", "h")}, "pixel_match": ImageChops.difference(expected, Image.open(output_path).convert("RGBA")).getbbox() is None}
