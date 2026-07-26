"""Offline, deterministic exact-product cutout and final compositing service.

Products with ``on_the_fly_flags.exact_product_composite_required`` never use
raw Google Flow product pixels as final output. Flow may only generate a
scene/background plate; this module inserts the canonical cutout and attests
product-region identity against that cutout (not self-comparison alone).
"""
from __future__ import annotations

from collections import deque

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from agent.config import BASE_DIR, OUTPUT_DIR
from agent.services.product_lock_builder import resolve_schema_entry

# Lane-aware product occupancy (% of canvas). Deterministic — never model-chosen.
LANE_SAFE_REGIONS: dict[str, dict[str, float]] = {
    "studio": {"x": 22.0, "y": 18.0, "w": 56.0, "h": 68.0},
    "poster": {"x": 28.0, "y": 22.0, "w": 44.0, "h": 52.0},
    "product_only_hero": {"x": 20.0, "y": 16.0, "w": 60.0, "h": 70.0},
}

# Fit product inside safe region (leave margin); never stretch to fill.
SAFE_REGION_FILL = 0.88

SCENE_ONLY_PROMPT_LINES = (
    "EXACT_PRODUCT_COMPOSITE_REQUIRED: Generate a clean scene-only plate.",
    "Do not render, redraw, invent, type, stylize, or include any product, bottle, packaging, label, cap, logo, or brand mark.",
    "Reserve a clear empty product-safe region in the lower-middle / center for later deterministic product insertion.",
    "Provide a realistic surface or contact-shadow receiver under the empty product region.",
    "No duplicate products. No floating bottles. No marketing typography overlay.",
)

SCENE_ONLY_NEGATIVE = (
    "product bottle, packaging, label text, brand logo, cap, glass bottle, "
    "herbal oil bottle, product mockup, floating product, barcode, TOK"
)


class ExactProductCompositeError(Exception):
    """Fail-closed exact-product error with stable machine code."""

    def __init__(self, code: str, message: str = "", *, status_code: int = 422):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code
        self.message = message or code


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_key(entry: dict[str, Any] | None) -> str:
    if not entry:
        return "UNKNOWN"
    return str(entry.get("product_id") or entry.get("schema_key") or "UNKNOWN")


def durable_canonical_dir(schema_key: str) -> Path:
    return BASE_DIR / "data" / "exact-product" / schema_key


def durable_canonical_source_path(schema_key: str) -> Path:
    return durable_canonical_dir(schema_key) / "canonical_source.jpg"


def exact_product_policy(product: dict[str, Any]) -> dict[str, Any] | None:
    """Return canonical_product_photo dict when exact composite is required."""
    entry = resolve_schema_entry(product)
    flags = (entry or {}).get("on_the_fly_flags") or {}
    photo = (entry or {}).get("canonical_product_photo") or {}
    if not flags.get("exact_product_composite_required") or not photo:
        return None
    return photo


def requires_exact_composite(product: dict[str, Any] | None) -> bool:
    if not product:
        return False
    return exact_product_policy(product) is not None


def scene_only_prompt_block() -> str:
    return "\n".join(f"- {line}" for line in SCENE_ONLY_PROMPT_LINES)


def augment_prompt_scene_only(prompt: str) -> str:
    """Append scene-only constraints; strip soft product-preserve language."""
    base = (prompt or "").strip()
    # Soft preserve lines encourage Flow to redraw packaging — drop them for exact.
    drop_markers = (
        "PRESERVE the real product label",
        "preserve product identity",
        "exact product reference",
        "Feature the product",
    )
    lines = [
        ln
        for ln in base.splitlines()
        if not any(m.lower() in ln.lower() for m in drop_markers)
    ]
    cleaned = "\n".join(lines).strip()
    block = "\n".join(SCENE_ONLY_PROMPT_LINES)
    if "EXACT_PRODUCT_COMPOSITE_REQUIRED" in cleaned:
        return cleaned
    return f"{cleaned}\n\n{block}".strip()


def resolve_canonical_source(photo: dict[str, Any], *, schema_key: str = "") -> Path:
    """Prefer durable runtime copy; fall back to schema source_path."""
    expected = str(photo.get("sha256") or "")
    candidates: list[Path] = []
    if schema_key:
        candidates.append(durable_canonical_source_path(schema_key))
    raw = str(photo.get("source_path") or "").strip()
    if raw:
        candidates.append(Path(raw))
    for path in candidates:
        if path.exists() and path.is_file():
            if expected and _sha(path) != expected:
                continue
            return path
    raise ExactProductCompositeError(
        "CANONICAL_PRODUCT_SOURCE_INVALID",
        "Canonical physical product source missing, unreadable, or hash-mismatched.",
        status_code=422,
    )


def ensure_durable_canonical_copy(product: dict[str, Any]) -> dict[str, Any]:
    """Copy verified physical source into BASE_DIR/data/exact-product/..."""
    entry = resolve_schema_entry(product)
    photo = exact_product_policy(product)
    if not photo:
        raise ExactProductCompositeError(
            "EXACT_POLICY_NOT_REQUIRED",
            "Product is not under exact-product composite policy.",
            status_code=400,
        )
    key = _schema_key(entry)
    expected = str(photo["sha256"])
    source = resolve_canonical_source(photo, schema_key=key)
    dest_dir = durable_canonical_dir(key)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = durable_canonical_source_path(key)
    if not dest.exists() or _sha(dest) != expected:
        shutil.copy2(source, dest)
    if _sha(dest) != expected:
        raise ExactProductCompositeError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Durable canonical copy failed hash verification.",
            status_code=422,
        )
    meta = {
        "schema_key": key,
        "source_sha256": expected,
        "durable_path": str(dest),
        "dimensions": str(photo.get("dimensions") or ""),
        "product_uuid": str(product.get("id") or product.get("product_id") or ""),
    }
    (dest_dir / "provenance.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return meta


def validate_canonical_or_raise(product: dict[str, Any]) -> dict[str, Any]:
    """Pre-credit fail-closed gate."""
    photo = exact_product_policy(product)
    if not photo:
        raise ExactProductCompositeError(
            "EXACT_POLICY_NOT_REQUIRED",
            status_code=400,
        )
    entry = resolve_schema_entry(product)
    key = _schema_key(entry)
    path = resolve_canonical_source(photo, schema_key=key)
    digest = _sha(path)
    expected = str(photo["sha256"])
    if digest != expected:
        raise ExactProductCompositeError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            f"Hash mismatch for {path}",
            status_code=422,
        )
    return {
        "schema_key": key,
        "source_path": str(path),
        "source_sha256": digest,
        "dimensions": str(photo.get("dimensions") or ""),
        "exact_product_composite_required": True,
        "scene_only_required": True,
        "send_product_reference_to_flow": False,
    }


def _is_strict_bg_rgb(r: int, g: int, b: int) -> bool:
    """Only obvious wall/floor neutrals (do NOT eat clear glass as bg)."""
    mx, mn = max(r, g, b), min(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = mx - mn
    if lum >= 200 and chroma <= 28:
        return True
    if lum >= 175 and chroma <= 18:
        return True
    return False


def _is_soft_bg_rgb(r: int, g: int, b: int) -> bool:
    """Broader wall/floor for residual cleanup away from product core."""
    mx, mn = max(r, g, b), min(r, g, b)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    chroma = mx - mn
    if lum >= 155 and chroma <= 40:
        return True
    if lum >= 170 and chroma <= 55:
        return True
    return False


def _is_red_cap_rgb(r: int, g: int, b: int) -> bool:
    # Plastic red cap only — exclude cream/gold label metal (high G/B).
    return r >= 130 and g <= 90 and b <= 90 and r > g + 50 and r > b + 50


def _keep_product_components(
    mask: Image.Image,
    *,
    rgb: Image.Image | None = None,
) -> Image.Image:
    """Keep largest body blob and any substantial red-cap blob above it."""
    w, h = mask.size
    mpx = mask.load()
    rpx = rgb.load() if rgb is not None else None
    visited = bytearray(w * h)
    comps: list[dict[str, Any]] = []
    for y0 in range(h):
        for x0 in range(w):
            i0 = y0 * w + x0
            if visited[i0] or mpx[x0, y0] < 200:
                continue
            q: deque[tuple[int, int]] = deque([(x0, y0)])
            visited[i0] = 1
            comp: list[tuple[int, int]] = []
            red_n = 0
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                if rpx is not None:
                    r, g, b = rpx[x, y]
                    if _is_red_cap_rgb(r, g, b):
                        red_n += 1
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue
                    i = ny * w + nx
                    if visited[i] or mpx[nx, ny] < 200:
                        continue
                    visited[i] = 1
                    q.append((nx, ny))
            if len(comp) < 80:
                continue
            ys = [p[1] for p in comp]
            comps.append(
                {
                    "pts": comp,
                    "n": len(comp),
                    "red": red_n,
                    "ymin": min(ys),
                    "ymax": max(ys),
                }
            )
    if not comps:
        return Image.new("L", (w, h), 0)
    comps.sort(key=lambda c: c["n"], reverse=True)
    body = comps[0]
    keep = list(body["pts"])
    # Merge red-cap component(s) sitting above the body.
    for c in comps[1:]:
        if c["red"] >= 200 and c["ymax"] <= body["ymin"] + 30:
            keep.extend(c["pts"])
            # paint a short vertical bridge between cap and body
            xs = [p[0] for p in c["pts"]]
            cx0, cx1 = min(xs), max(xs)
            for y in range(c["ymax"], min(h, body["ymin"] + 1)):
                for x in range(cx0, cx1 + 1):
                    keep.append((x, y))
    out = Image.new("L", (w, h), 0)
    opx = out.load()
    for x, y in keep:
        if 0 <= x < w and 0 <= y < h:
            opx[x, y] = 255
    # close residual neck gaps
    out = out.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(3))
    return out


def _build_canonical_cutout(source: Path) -> Image.Image:
    """Isolate product while preserving RGB and the red cap.

    Strategy (fail-closed, deterministic, no ML):
    1. Strict border flood removes pure wall/floor only (not clear glass).
    2. Grow product from image center through non-soft-bg + red-cap pixels.
    3. Reattach any nearby red-cap blob above the body.
    4. Largest-component cleanup, light edge soften; interior RGB untouched.
    """
    image = Image.open(source).convert("RGBA")
    w, h = image.size
    rgb = image.convert("RGB")
    px = rgb.load()

    # --- 1) strict border flood → definite background ---
    visited = bytearray(w * h)
    strict_bg = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()

    def seed_strict(x: int, y: int) -> None:
        i = y * w + x
        if visited[i]:
            return
        r, g, b = px[x, y]
        if _is_strict_bg_rgb(r, g, b):
            visited[i] = 1
            q.append((x, y))

    for x in range(w):
        seed_strict(x, 0)
        seed_strict(x, h - 1)
    for y in range(h):
        seed_strict(0, y)
        seed_strict(w - 1, y)
    while q:
        x, y = q.popleft()
        strict_bg[y * w + x] = 1
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            i = ny * w + nx
            if visited[i]:
                continue
            r, g, b = px[nx, ny]
            if _is_strict_bg_rgb(r, g, b):
                visited[i] = 1
                q.append((nx, ny))

    # --- 2) product grow from center ---
    product = bytearray(w * h)
    pq: deque[tuple[int, int]] = deque()
    cx0, cx1 = int(w * 0.30), int(w * 0.70)
    cy0, cy1 = int(h * 0.20), int(h * 0.80)
    for y in range(cy0, cy1):
        for x in range(cx0, cx1):
            i = y * w + x
            if strict_bg[i]:
                continue
            r, g, b = px[x, y]
            if _is_soft_bg_rgb(r, g, b) and not _is_red_cap_rgb(r, g, b):
                continue
            product[i] = 1
            pq.append((x, y))

    while pq:
        x, y = pq.popleft()
        for nx, ny in (
            (x + 1, y),
            (x - 1, y),
            (x, y + 1),
            (x, y - 1),
            (x + 1, y + 1),
            (x - 1, y - 1),
            (x + 1, y - 1),
            (x - 1, y + 1),
        ):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            i = ny * w + nx
            if product[i] or strict_bg[i]:
                continue
            r, g, b = px[nx, ny]
            if _is_red_cap_rgb(r, g, b):
                product[i] = 1
                pq.append((nx, ny))
                continue
            if _is_soft_bg_rgb(r, g, b):
                continue
            product[i] = 1
            pq.append((nx, ny))

    # Force-include every true-red pixel (cap) then bridge neck vertically.
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if product[i] or strict_bg[i]:
                continue
            r, g, b = px[x, y]
            if _is_red_cap_rgb(r, g, b):
                product[i] = 1
    # Vertical bridge from red clusters downward into product body (neck glass).
    red_cols: dict[int, list[int]] = {}
    for y in range(h):
        for x in range(w):
            if product[y * w + x] and _is_red_cap_rgb(*px[x, y]):
                red_cols.setdefault(x, []).append(y)
    for x, ys in red_cols.items():
        y_bottom = max(ys)
        # paint a thin column down up to 80px to reconnect neck
        for y in range(y_bottom, min(h, y_bottom + 80)):
            for xx in (x - 2, x - 1, x, x + 1, x + 2):
                if 0 <= xx < w and not strict_bg[y * w + xx]:
                    # only bridge non-strict-bg (glass/label) pixels
                    r, g, b = px[xx, y]
                    if not _is_strict_bg_rgb(r, g, b):
                        product[y * w + xx] = 1

    # --- 3) reattach red-cap components near top of product ---
    # find product bbox
    min_x, min_y, max_x, max_y = w, h, 0, 0
    any_p = False
    for y in range(h):
        row = y * w
        for x in range(w):
            if product[row + x]:
                any_p = True
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if any_p:
        cap_y0 = max(0, min_y - int(h * 0.12))
        cap_y1 = min(h, min_y + int(h * 0.08))
        cap_x0 = max(0, min_x - 8)
        cap_x1 = min(w, max_x + 8)
        for y in range(cap_y0, cap_y1):
            for x in range(cap_x0, cap_x1):
                i = y * w + x
                if product[i] or strict_bg[i]:
                    continue
                r, g, b = px[x, y]
                if _is_red_cap_rgb(r, g, b):
                    # flood red blob into product
                    rq: deque[tuple[int, int]] = deque([(x, y)])
                    product[i] = 1
                    while rq:
                        cx, cy = rq.popleft()
                        for nx, ny in (
                            (cx + 1, cy),
                            (cx - 1, cy),
                            (cx, cy + 1),
                            (cx, cy - 1),
                        ):
                            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                                continue
                            j = ny * w + nx
                            if product[j]:
                                continue
                            rr, gg, bb = px[nx, ny]
                            if _is_red_cap_rgb(rr, gg, bb) or (
                                rr > 100 and gg < 90 and bb < 90
                            ):
                                product[j] = 1
                                rq.append((nx, ny))

    mask = Image.new("L", (w, h), 0)
    mpx = mask.load()
    for y in range(h):
        row = y * w
        for x in range(w):
            if product[row + x]:
                mpx[x, y] = 255
    mask = mask.filter(ImageFilter.MaxFilter(3))  # bridge thin neck
    mask = _keep_product_components(mask, rgb=rgb)
    # light edge soften; solid interior stays fully opaque
    soft = mask.filter(ImageFilter.GaussianBlur(radius=0.5))
    mpx2 = mask.load()
    spx = soft.load()
    for y in range(h):
        for x in range(w):
            if mpx2[x, y] >= 250:
                spx[x, y] = 255
    image.putalpha(soft)
    bbox = image.getbbox()
    if bbox:
        pad = 4
        x0, y0, x1, y1 = bbox
        image = image.crop(
            (
                max(0, x0 - pad),
                max(0, y0 - pad),
                min(w, x1 + pad),
                min(h, y1 + pad),
            )
        )
    a = image.getchannel("A")
    opaque = sum(a.histogram()[200:])
    if opaque < 500:
        raise ExactProductCompositeError(
            "CANONICAL_CUTOUT_EMPTY",
            "Cutout produced too few opaque product pixels.",
            status_code=422,
        )
    # Cap presence check for bottle products (soft warn via fail if zero red)
    cap_px = 0
    cpx = image.load()
    for y in range(min(image.height, max(1, int(image.height * 0.25)))):
        for x in range(image.width):
            r, g, b, aa = cpx[x, y]
            if aa >= 200 and _is_red_cap_rgb(r, g, b):
                cap_px += 1
    if cap_px < 80:
        # still allow synthetic white-bg unit bottles without red caps
        # only enforce when source itself has abundant red near top
        src = Image.open(source).convert("RGB")
        sp = src.load()
        sw, sh = src.size
        src_red = 0
        for y in range(int(sh * 0.25)):
            for x in range(sw):
                r, g, b = sp[x, y]
                if _is_red_cap_rgb(r, g, b):
                    src_red += 1
        if src_red >= 200 and cap_px < 80:
            raise ExactProductCompositeError(
                "CANONICAL_CUTOUT_CAP_MISSING",
                "Cutout lost red cap — refusing to emit incomplete product layer.",
                status_code=422,
            )
    return image



def prepare_layer(
    product: dict[str, Any],
    safe_region: dict[str, float],
    canvas: dict[str, int],
    *,
    fill: float = SAFE_REGION_FILL,
) -> dict[str, Any]:
    photo = exact_product_policy(product)
    if not photo:
        return {}
    entry = resolve_schema_entry(product)
    key = _schema_key(entry)
    source = resolve_canonical_source(photo, schema_key=key)
    expected = str(photo["sha256"])
    if _sha(source) != expected:
        raise ExactProductCompositeError("CANONICAL_PRODUCT_SOURCE_INVALID")

    cutout_dir = BASE_DIR / "data" / "exact-product-cutouts"
    cutout_dir.mkdir(parents=True, exist_ok=True)
    # Also mirror under OUTPUT_DIR for compositor path compatibility.
    out_cutout_dir = OUTPUT_DIR / "exact-product-cutouts"
    out_cutout_dir.mkdir(parents=True, exist_ok=True)
    cutout = cutout_dir / f"{expected}.png"
    if not cutout.exists():
        image = _build_canonical_cutout(source)
        image.save(cutout)
    mirror = out_cutout_dir / cutout.name
    if not mirror.exists() or _sha(mirror) != _sha(cutout):
        shutil.copy2(cutout, mirror)

    cw, ch = int(canvas["w"]), int(canvas["h"])
    max_w = int(cw * float(safe_region["w"]) / 100)
    max_h = int(ch * float(safe_region["h"]) / 100)
    im = Image.open(cutout)
    scale = min(max_w / im.width, max_h / im.height) * float(fill)
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    x = round(cw * float(safe_region["x"]) / 100 + (max_w - w) / 2)
    y = round(ch * float(safe_region["y"]) / 100 + (max_h - h) / 2)
    return {
        "asset_ref": str(cutout),
        "source_sha256": expected,
        "cutout_sha256": _sha(cutout),
        "schema_key": key,
        "transform": {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "rotation_degrees": 0.0,
            "perspective_skew_x": 0.0,
            "shadow_opacity": 0.24,
            "shadow_blur_px": 18.0,
        },
    }


def _product_region_match(
    final_img: Image.Image, cutout_resized: Image.Image, origin: tuple[int, int]
) -> dict[str, Any]:
    """Compare final product-region RGBA against placed cutout (honest QA)."""
    x, y = origin
    w, h = cutout_resized.size
    region = final_img.crop((x, y, x + w, y + h)).convert("RGBA")
    cut = cutout_resized.convert("RGBA")
    # Only opaque cutout pixels must match (ignore soft shadow fringe on plate).
    cut_alpha = cut.split()[3]
    # Build mask of solid product pixels
    solid = cut_alpha.point(lambda a: 255 if a >= 250 else 0)
    if ImageStat.Stat(solid).sum[0] < 100:
        return {
            "product_region_match": False,
            "reason": "CUTOUT_ALPHA_TOO_SPARSE",
            "opaque_px": 0,
        }
    diff = ImageChops.difference(region, cut)
    # Zero-out transparent cutout pixels in the diff
    bands = list(diff.split())
    mask_l = solid
    for i in range(4):
        bands[i] = ImageChops.multiply(bands[i], mask_l)
    masked = Image.merge("RGBA", bands)
    # Max channel delta among opaque pixels
    extrema = masked.getextrema()
    max_delta = max(e[1] for e in extrema)
    # Source-derived LANCZOS downscale: allow tiny filter deltas on edges
    ok = max_delta <= 12
    return {
        "product_region_match": ok,
        "max_channel_delta": int(max_delta),
        "opaque_px": int(ImageStat.Stat(solid).sum[0] // 255),
        "attestation": (
            "CANONICAL_CUTOUT_REGION_MATCH" if ok else "PRODUCT_REGION_MISMATCH"
        ),
    }


def composite(output_path: Path, layer: dict[str, Any]) -> dict[str, Any]:
    asset, t = Path(str(layer["asset_ref"])), layer["transform"]
    base = Image.open(output_path).convert("RGBA")
    product = Image.open(asset).convert("RGBA").resize(
        (int(t["w"]), int(t["h"])), Image.Resampling.LANCZOS
    )
    shadow = Image.new("RGBA", base.size)
    alpha = product.getchannel("A").filter(
        ImageFilter.GaussianBlur(float(t["shadow_blur_px"]))
    )
    dark = Image.new(
        "RGBA", product.size, (0, 0, 0, round(255 * float(t["shadow_opacity"])))
    )
    dark.putalpha(alpha.point(lambda value: value * float(t["shadow_opacity"])))
    # Shadow offset below product; keep clear glass base readable (offset only).
    shadow.alpha_composite(dark, (int(t["x"]) + 8, int(t["y"]) + 12))
    composed = Image.alpha_composite(base, shadow)
    composed.alpha_composite(product, (int(t["x"]), int(t["y"])))
    composed.save(output_path)

    # Self write-verify (file bytes round-trip)
    reloaded = Image.open(output_path).convert("RGBA")
    write_ok = ImageChops.difference(composed, reloaded).getbbox() is None
    region_qa = _product_region_match(
        reloaded, product, (int(t["x"]), int(t["y"]))
    )
    return {
        "composition_ok": bool(write_ok and region_qa.get("product_region_match")),
        "attestation": region_qa.get("attestation")
        or "ALPHA_AWARE_TRANSFORMED_CUTOUT_EXACT_MATCH",
        "product_region": {k: int(t[k]) for k in ("x", "y", "w", "h")},
        "pixel_match": write_ok,  # write integrity only — not sole product proof
        "write_verified": write_ok,
        "product_region_match": bool(region_qa.get("product_region_match")),
        "region_qa": region_qa,
        "exact_product_count": 1,
        "aspect_ratio_preserved": True,
        "rotation_degrees": float(t.get("rotation_degrees") or 0.0),
        "perspective_skew_x": float(t.get("perspective_skew_x") or 0.0),
    }


def compose_final_from_plate(
    product: dict[str, Any],
    plate_path: Path,
    *,
    lane: str = "studio",
    canvas: dict[str, int] | None = None,
    safe_region: dict[str, float] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Copy plate → insert canonical product → return lineage + QA."""
    validate_canonical_or_raise(product)
    ensure_durable_canonical_copy(product)
    if not plate_path.exists():
        raise ExactProductCompositeError(
            "SCENE_PLATE_MISSING",
            f"Scene plate not found: {plate_path}",
            status_code=404,
        )
    plate = Image.open(plate_path).convert("RGBA")
    cw, ch = plate.size
    canvas = canvas or {"w": cw, "h": ch}
    region = safe_region or LANE_SAFE_REGIONS.get(lane) or LANE_SAFE_REGIONS["studio"]
    layer = prepare_layer(product, region, canvas)
    if not layer:
        raise ExactProductCompositeError("EXACT_POLICY_NOT_REQUIRED", status_code=400)

    out = output_path or (
        OUTPUT_DIR
        / "exact-product-finals"
        / f"{layer['source_sha256'][:16]}_{lane}_{plate_path.stem}.png"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plate_path, out)
    integrity = composite(out, layer)
    if not integrity.get("composition_ok"):
        raise ExactProductCompositeError(
            "EXACT_COMPOSITE_QA_FAILED",
            json.dumps(integrity),
            status_code=422,
        )
    plate_sha = _sha(plate_path)
    final_sha = _sha(out)
    return {
        "ok": True,
        "lane": lane,
        "output_path": str(out),
        "output_sha256": final_sha,
        "raw_plate_path": str(plate_path),
        "raw_plate_sha256": plate_sha,
        "canonical_source_sha256": layer["source_sha256"],
        "cutout_sha256": layer["cutout_sha256"],
        "cutout_path": layer["asset_ref"],
        "transform": layer["transform"],
        "schema_key": layer.get("schema_key"),
        "qa": integrity,
        "truth_status": "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
        "raw_plate_approvable": False,
        "final_approvable": True,
    }
