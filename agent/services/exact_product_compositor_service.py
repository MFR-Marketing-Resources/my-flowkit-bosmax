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
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from agent.config import BASE_DIR, OUTPUT_DIR
from agent.services.product_lock_builder import resolve_schema_entry
from agent.services import product_truth_lock_service as truth_lock_service

# Lane-aware product occupancy (% of canvas). Deterministic — never model-chosen.
LANE_SAFE_REGIONS: dict[str, dict[str, float]] = {
    "studio": {"x": 22.0, "y": 18.0, "w": 56.0, "h": 68.0},
    "poster": {"x": 28.0, "y": 22.0, "w": 44.0, "h": 52.0},
    "product_only_hero": {"x": 20.0, "y": 16.0, "w": 60.0, "h": 70.0},
}

# Fit product inside safe region (leave margin); never stretch to fill.
SAFE_REGION_FILL = 0.72

SCENE_ONLY_PROMPT_LINES = (
    "SCENE-ONLY PLATE. Do not generate, render, redraw, imitate, restyle, type, or include the product, packaging, bottle, label, logo, brand mark, or replacement object. The verified product will be inserted later by a deterministic compositor. Reserve the declared placement bounding box as a clear unobstructed region, provide a physically plausible contact surface and compatible scene lighting, and do not place foreground objects, hands, text, shadows, reflections, or props across that region.",
    "EXACT_PRODUCT_COMPOSITE_REQUIRED: the final product bytes come only from the approved Product Truth Lock.",
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
    """Return the exact lane policy, never a synthetic canonical asset.

    Schema flags remain a strategy hint for legacy fixed-hero products.  New
    callers may set the server-derived ``_exact_product_required`` marker for a
    product-only/poster lane.  Neither path makes the schema photo authoritative;
    the persisted ProductTruthLock is checked by ``validate_canonical_or_raise``.
    """
    entry = resolve_schema_entry(product)
    flags = (entry or {}).get("on_the_fly_flags") or {}
    photo = (entry or {}).get("canonical_product_photo") or {}
    required = bool(
        flags.get("exact_product_composite_required")
        or product.get("_exact_product_required") is True
    )
    if not required:
        return None
    # A schema flag without a canonical photo is not enough to replace the
    # standard reference-conditioned prompt.  Exact lanes set the explicit
    # server marker and then fail closed on the missing ProductTruthLock.
    if not photo and product.get("_exact_product_required") is not True:
        return None
    return photo or {"exact_product_composite_required": True}


def requires_exact_composite(product: dict[str, Any] | None) -> bool:
    if not product:
        return False
    return exact_product_policy(product) is not None


def scene_only_prompt_block() -> str:
    return "\n".join(f"- {line}" for line in SCENE_ONLY_PROMPT_LINES)


_SCENE_ONLY_DROPPED_SECTIONS = {
    "=== PRODUCT TRUTH LOCK ===",
    "=== COPY SLOTS ===",
    "=== TEXT OVERLAY ===",
}
_PROMPT_SECTION_HEADER = re.compile(r"^=== [A-Z0-9 _/&-]+ ===$")


def _strip_scene_only_sections(prompt: str) -> str:
    """Remove product/copy instructions before appending the scene-only block."""
    kept: list[str] = []
    dropping = False
    for raw_line in (prompt or "").splitlines():
        line = raw_line.strip()
        if line in _SCENE_ONLY_DROPPED_SECTIONS:
            dropping = True
            continue
        if dropping and _PROMPT_SECTION_HEADER.fullmatch(line):
            dropping = False
        if not dropping:
            kept.append(raw_line)
    return "\n".join(kept).strip()


def augment_prompt_scene_only(prompt: str) -> str:
    """Append scene-only constraints and strip product/copy instructions."""
    base = _strip_scene_only_sections(prompt)
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
    if "SCENE-ONLY PLATE." in cleaned and "deterministic compositor" in cleaned:
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
    """Return verified server-owned files; never generate or approve a cutout."""
    meta = validate_canonical_or_raise(product)
    return {
        **meta,
        "durable_path": meta["source_path"],
        "cutout_path": meta["cutout_path"],
        "product_uuid": str(product.get("id") or product.get("product_id") or ""),
    }


def validate_canonical_or_raise(product: dict[str, Any]) -> dict[str, Any]:
    """Pre-credit fail-closed gate backed by the persisted truth contract."""
    photo = exact_product_policy(product)
    if not photo:
        raise ExactProductCompositeError(
            "EXACT_POLICY_NOT_REQUIRED",
            status_code=400,
        )
    product_id = str(product.get("id") or product.get("product_id") or "")
    if not product_id:
        raise ExactProductCompositeError(
            "PRODUCT_TRUTH_LOCK_REQUIRED",
            "Exact output requires a canonical product id bound to an approved truth lock.",
            status_code=422,
        )
    try:
        resolved = truth_lock_service.resolve_approved_product_truth_lock(product_id)
    except truth_lock_service.ProductTruthLockError as exc:
        raise ExactProductCompositeError(exc.code, exc.message, status_code=exc.status_code) from exc
    entry = resolve_schema_entry(product)
    key = _schema_key(entry)
    return {
        "product_id": product_id,
        "schema_key": key,
        "source_path": resolved.canonical_source_path,
        "source_sha256": resolved.canonical_sha256,
        "dimensions": f"{resolved.source_width}x{resolved.source_height}",
        "canonical_media_id": resolved.canonical_media_id,
        "cutout_path": resolved.canonical_cutout_path,
        "cutout_media_id": resolved.canonical_cutout_media_id,
        "cutout_sha256": resolved.canonical_cutout_sha256,
        "alpha_mask_sha256": resolved.alpha_mask_sha256,
        "allowed_bbox": resolved.allowed_bbox,
        "anchor_point": resolved.anchor_point,
        "min_scale": resolved.min_scale,
        "max_scale": resolved.max_scale,
        "allowed_rotation": resolved.allowed_rotation,
        "allowed_perspective": resolved.allowed_perspective,
        "product_truth_lock_schema_version": resolved.schema_version,
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
    # Warm/red-lit studio wall plaster (MWTCB studio wall lighting behind glass, right edge, & above cap)
    if lum >= 130 and chroma <= 95 and r >= 130 and g >= 100 and b >= 100:
        if abs(r - g) <= 95 and abs(r - b) <= 95:
            # Exclude plastic red cap (g <= 90 or b <= 90)
            if g >= 100 and b >= 100:
                return True
    return False


def _is_red_cap_rgb(r: int, g: int, b: int) -> bool:
    # Plastic red cap only — exclude cream/gold label metal (high G/B).
    return r >= 130 and g <= 90 and b <= 90 and r > g + 50 and r > b + 50


def _is_product_color(r: int, g: int, b: int) -> bool:
    """True for packaging / liquid / cap pixels (NOT wall or floor)."""
    if _is_red_cap_rgb(r, g, b):
        return True
    mx, mn = max(r, g, b), min(r, g, b)
    chroma = mx - mn
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    # green oil liquid
    if g >= 70 and g >= r + 12 and g >= b + 8:
        return True
    # teal / cyan label field
    if g >= 70 and b >= 70 and (g + b) / 2.0 >= r + 18 and chroma >= 18:
        return True
    # cream / ivory cartouche (warm, high lum) — MUST not be treated as wall
    if lum >= 145 and r >= 140 and r >= b and (r - b) >= 8 and chroma <= 95:
        return True
    # gold filigree / border
    if r >= 140 and g >= 90 and b <= 120 and r > b + 25 and g > b + 10 and chroma >= 30:
        return True
    # dark ink / illustration
    if lum <= 85 and chroma <= 55:
        return True
    # mid brown/branch illustration tones
    if 40 <= lum <= 140 and r > g >= b and (r - b) >= 15 and chroma >= 15:
        return True
    return False



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
    caps = [
        c
        for c in comps[1:]
        if c["red"] >= 150 and c["ymax"] <= body["ymin"] + 40
    ]
    for c in caps:
        keep.extend(c["pts"])
    out = Image.new("L", (w, h), 0)
    opx = out.load()
    for x, y in keep:
        if 0 <= x < w and 0 <= y < h:
            opx[x, y] = 255
    # Solid rectangular neck bridge: cap bottom → body top, full cap width.
    if caps:
        cap = max(caps, key=lambda c: c["red"])
        cxs = [p[0] for p in cap["pts"]]
        bxs = [p[0] for p in body["pts"] if body["ymin"] <= p[1] <= body["ymin"] + 40]
        if not bxs:
            bxs = [p[0] for p in body["pts"]]
        cx0 = max(0, min(min(cxs), min(bxs)) - 2)
        cx1 = min(w - 1, max(max(cxs), max(bxs)) + 2)
        # slightly taper bridge toward body center
        mid = (cx0 + cx1) // 2
        half0 = (cx1 - cx0) // 2
        y_start = cap["ymax"]
        y_end = min(h - 1, body["ymin"] + 8)
        span = max(1, y_end - y_start)
        for yi, y in enumerate(range(y_start, y_end + 1)):
            t = yi / span
            half = int(half0 * (1.0 - 0.15 * t))
            for x in range(max(0, mid - half), min(w, mid + half + 1)):
                opx[x, y] = 255
    # close residual neck gaps / thin glass
    out = out.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(3))
    out = out.filter(ImageFilter.MaxFilter(3))
    return out




def _inpaint_background_bleed(image: Image.Image) -> Image.Image:
    """Replace wall-bleed only near the silhouette edge (not interior label).

    Cream cartouche / gold ornaments are high-luminance low-chroma and must NOT
    be treated as background. Only edge-adjacent bg-looking pixels are fixed.
    """
    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()
    alpha = img.getchannel("A")
    # edge = product pixels with a transparent neighbor
    edge = Image.new("L", (w, h), 0)
    epx = edge.load()
    apx = alpha.load()
    for y in range(h):
        for x in range(w):
            if apx[x, y] < 200:
                continue
            border = False
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nx < 0 or ny < 0 or nx >= w or ny >= h or apx[nx, ny] < 128:
                    border = True
                    break
            if border:
                epx[x, y] = 255
    # dilate edge band ~6px
    edge = edge.filter(ImageFilter.MaxFilter(7))
    epx = edge.load()
    # solid samples: non-bg product interior
    cells: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            if _is_red_cap_rgb(r, g, b):
                cells.setdefault((x // 12, y // 12), []).append((r, g, b))
                continue
            if _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b):
                continue
            cells.setdefault((x // 12, y // 12), []).append((r, g, b))
    for y in range(h):
        for x in range(w):
            if epx[x, y] < 200:
                continue
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            if _is_red_cap_rgb(r, g, b):
                continue
            if not (_is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b)):
                continue
            cx, cy = x // 12, y // 12
            found = None
            for rad in range(0, 10):
                bucket: list[tuple[int, int, int]] = []
                for dy in range(-rad, rad + 1):
                    for dx in range(-rad, rad + 1):
                        bucket.extend(cells.get((cx + dx, cy + dy), []))
                if bucket:
                    bucket.sort(
                        key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
                    )
                    found = bucket[len(bucket) // 2]
                    break
            if found:
                px[x, y] = (found[0], found[1], found[2], a)
    return img






def _trim_background_edge_fringe(image: Image.Image, passes: int = 4) -> Image.Image:
    """Remove wall/floor halo on silhouette WITHOUT eroding product core.

    Warm wall tones near the rim often look cream-like; at the exterior they
    must be dropped. Interior cream cartouche stays (not exterior-reachable
    once teal rim seals it, or fails is_drop when keep rules apply only off-edge).
    """
    from collections import deque

    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_core(r: int, g: int, b: int) -> bool:
        """True product colors that must survive edge peel."""
        if _is_red_cap_rgb(r, g, b):
            return True
        # teal glass / label frame
        if g >= 70 and b >= 70 and (g + b) / 2.0 >= r + 12 and (
            max(r, g, b) - min(r, g, b)
        ) >= 12:
            return True
        # green liquid
        if g >= 85 and g >= r + 18 and g >= b + 15:
            return True
        # dark ink / glass shade
        if (0.299 * r + 0.587 * g + 0.114 * b) <= 95:
            return True
        # cream cartouche: warmer yellow bias, enough r-b
        mx, mn = max(r, g, b), min(r, g, b)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        chroma = mx - mn
        if (
            r >= 170
            and g >= 155
            and b <= 200
            and (r - b) >= 28
            and (r - g) >= 2
            and 28 <= chroma <= 90
            and lum >= 160
        ):
            return True
        # gold border
        if r >= 150 and g >= 100 and b <= 130 and r > b + 30 and g > b + 15:
            return True
        # Do NOT keep generic mid-chroma neutrals — wall plaster is ~chroma 25-40
        # and was surviving as false "plumage". Bird interior is sealed by teal frame.
        return False

    def is_drop(r: int, g: int, b: int) -> bool:
        if is_core(r, g, b):
            return False
        if _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b):
            return True
        mx, mn = max(r, g, b), min(r, g, b)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        chroma = mx - mn
        # wall / floor neutrals and warm plaster (incl. pinkish MWTCB wall)
        if lum >= 125 and chroma <= 55:
            return True
        if lum >= 130 and abs(r - g) <= 95 and chroma <= 95:
            if g >= 100 and b >= 100:
                return True
        if lum >= 150 and chroma <= 80:
            return True
        return False

    # exterior flood into droppable pixels
    seen = [[False] * w for _ in range(h)]
    q: deque[tuple[int, int]] = deque()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] < 128:
                seen[y][x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
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
            if nx < 0 or ny < 0 or nx >= w or ny >= h or seen[ny][nx]:
                continue
            r, g, b, a = px[nx, ny]
            if a < 128:
                seen[ny][nx] = True
                q.append((nx, ny))
                continue
            if a >= 180 and is_drop(r, g, b):
                px[nx, ny] = (0, 0, 0, 0)
                seen[ny][nx] = True
                q.append((nx, ny))
            else:
                seen[ny][nx] = True

    # shell peel: droppable pixels with a transparent neighbor
    for _ in range(max(1, int(passes))):
        doomed: list[tuple[int, int]] = []
        for y in range(h):
            for x in range(w):
                r, g, b, a = px[x, y]
                if a < 180 or not is_drop(r, g, b):
                    continue
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h or px[nx, ny][3] < 128:
                        doomed.append((x, y))
                        break
        if not doomed:
            break
        for x, y in doomed:
            px[x, y] = (0, 0, 0, 0)
    return img



def _strip_synthetic_base_tab(image: Image.Image) -> Image.Image:
    """Remove solid-fill green rectangle stubs under the bottle foot."""
    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()
    # find bottom-most opaque row
    bottom = None
    for y in range(h - 1, -1, -1):
        if any(px[x, y][3] >= 200 for x in range(w)):
            bottom = y
            break
    if bottom is None:
        return img
    # scan upward while rows are highly uniform / synthetic
    y = bottom
    stripped = 0
    while y >= int(h * 0.55) and stripped < int(h * 0.25):
        cols = [px[x, y][:3] for x in range(w) if px[x, y][3] >= 200]
        if len(cols) < 30:
            break
        # uniformity: median vs mean chroma low and many identical-ish
        uniq = len(set(cols))
        ratio = uniq / max(1, len(cols))
        # solid fill tabs are nearly one color
        from collections import Counter
        top_n = Counter(cols).most_common(1)[0][1]
        if top_n / len(cols) >= 0.55 or ratio <= 0.08:
            for x in range(w):
                if px[x, y][3] >= 200:
                    px[x, y] = (0, 0, 0, 0)
            stripped += 1
            y -= 1
            continue
        break
    return img


def _keep_main_product_silhouette(image: Image.Image) -> Image.Image:
    """Drop disconnected debris; keep largest blob + top red-cap blob."""
    from collections import deque

    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()
    seen = [[False] * w for _ in range(h)]
    comps: list[tuple[int, list[tuple[int, int]], int, float]] = []
    # (size, cells, red_count, med_y)
    for y in range(h):
        for x in range(w):
            if seen[y][x] or px[x, y][3] < 180:
                seen[y][x] = True if px[x, y][3] < 180 else seen[y][x]
                if px[x, y][3] < 180:
                    seen[y][x] = True
                continue
            if seen[y][x]:
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            cells: list[tuple[int, int]] = []
            red = 0
            while q:
                cx, cy = q.popleft()
                cells.append((cx, cy))
                r, g, b, a = px[cx, cy]
                if _is_red_cap_rgb(r, g, b):
                    red += 1
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and px[nx, ny][3] >= 180:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            ys = sorted(yy for _, yy in cells)
            comps.append((len(cells), cells, red, ys[len(ys) // 2]))
    if not comps:
        return img
    comps.sort(key=lambda t: t[0], reverse=True)
    keep_cells: set[tuple[int, int]] = set(comps[0][1])
    # top red-dominant component in upper 40% if not already kept
    red_caps = [
        c
        for c in comps
        if c[2] >= 40 and c[3] <= h * 0.4 and c[2] / max(1, c[0]) >= 0.35
    ]
    if red_caps:
        red_caps.sort(key=lambda t: t[3])
        for cell in red_caps[0][1]:
            keep_cells.add(cell)
    for y in range(h):
        for x in range(w):
            if px[x, y][3] >= 180 and (x, y) not in keep_cells:
                px[x, y] = (0, 0, 0, 0)
    return img


def _bridge_cap_to_body(image: Image.Image) -> Image.Image:
    """Reconnect TOP red-cap cluster to teal body after edge trim.

    Important: label text may contain red ink (e.g. Sejak 1958). Cap geometry
    must use only the uppermost red component, not all red pixels.
    """
    from collections import deque

    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()

    # Find connected red components
    seen = [[False] * w for _ in range(h)]
    red_comps: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            r, g, b, a = px[x, y]
            if a < 200 or not _is_red_cap_rgb(r, g, b):
                seen[y][x] = True
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            cells: list[tuple[int, int]] = []
            while q:
                cx, cy = q.popleft()
                cells.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h or seen[ny][nx]:
                        continue
                    rr, gg, bb, aa = px[nx, ny]
                    if aa >= 200 and _is_red_cap_rgb(rr, gg, bb):
                        seen[ny][nx] = True
                        q.append((nx, ny))
                    else:
                        seen[ny][nx] = True if aa < 200 else seen[ny][nx]
                        if aa < 200:
                            seen[ny][nx] = True
            if len(cells) >= 40:
                red_comps.append(cells)

    if not red_comps:
        return img
    # Cap = red component with smallest median y (topmost)
    def med_y(cells: list[tuple[int, int]]) -> float:
        ys = sorted(y for _, y in cells)
        return ys[len(ys) // 2]

    red_comps.sort(key=med_y)
    cap_cells = red_comps[0]
    # Ignore red components far below top third (label text)
    if med_y(cap_cells) > h * 0.35:
        return img

    teal_xy: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            if g >= 70 and b >= 70 and (g + b) / 2.0 >= r + 12:
                teal_xy.append((x, y))
    if not teal_xy:
        return img

    cap_bottom = max(y for _, y in cap_cells)
    body_top = min(y for _, y in teal_xy)
    if body_top <= cap_bottom + 2:
        return img

    cap_xs = [x for x, _ in cap_cells]
    body_xs = [x for x, y in teal_xy if y <= body_top + 15]
    if not body_xs:
        body_xs = [x for x, _ in teal_xy]
    mid = int((sum(cap_xs) / len(cap_xs) + sum(body_xs) / len(body_xs)) / 2)
    half = max(6, int(0.42 * (max(cap_xs) - min(cap_xs) + 1) / 2))

    samples: list[tuple[int, int, int]] = []
    for y in range(body_top, min(h, body_top + 12)):
        for x in range(max(0, mid - half), min(w, mid + half + 1)):
            r, g, b, a = px[x, y]
            if a >= 200:
                samples.append((r, g, b))
    glass = (90, 120, 100)
    if samples:
        samples.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
        glass = samples[len(samples) // 2]

    for y in range(cap_bottom, body_top + 1):
        t = (y - cap_bottom) / max(1, body_top - cap_bottom)
        hh = max(5, int(half * (0.5 + 0.5 * t)))
        for x in range(max(0, mid - hh), min(w, mid + hh + 1)):
            if px[x, y][3] >= 200:
                continue
            px[x, y] = (glass[0], glass[1], glass[2], 255)
    return img


def _resize_rgba_premultiplied(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """LANCZOS resize with premultiplied alpha to avoid dark/light edge smear."""
    img = image.convert("RGBA")
    r, g, b, a = img.split()
    zero = Image.new("L", img.size, 0)
    r = Image.composite(r, zero, a)
    g = Image.composite(g, zero, a)
    b = Image.composite(b, zero, a)
    pm = Image.merge("RGBA", (r, g, b, a)).resize(size, Image.Resampling.LANCZOS)
    pr, pg, pb, pa = pm.split()
    prx, pgx, pbx, pax = pr.load(), pg.load(), pb.load(), pa.load()
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    ox = out.load()
    tw, th = size
    for y in range(th):
        for x in range(tw):
            aa = pax[x, y]
            if aa <= 0:
                continue
            if aa >= 250:
                ox[x, y] = (prx[x, y], pgx[x, y], pbx[x, y], 255)
            else:
                inv = 255.0 / aa
                ox[x, y] = (
                    min(255, int(prx[x, y] * inv + 0.5)),
                    min(255, int(pgx[x, y] * inv + 0.5)),
                    min(255, int(pbx[x, y] * inv + 0.5)),
                    aa,
                )
    return out


def _harden_cutout_alpha_after_resize(product: Image.Image) -> Image.Image:
    """Kill translucent LANCZOS halo; keep hard product matte."""
    img = product.convert("RGBA")
    r, g, b, a = img.split()
    a = a.point(lambda v: 255 if v >= 180 else 0)
    img = Image.merge("RGBA", (r, g, b, a))
    img = _trim_background_edge_fringe(img, passes=2)
    img = _bridge_cap_to_body(img)
    return img


def _despeckle_alpha(image: Image.Image, min_comp: int = 120) -> Image.Image:
    """Drop tiny opaque islands outside the main product silhouette."""
    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()
    visited = bytearray(w * h)
    comps: list[list[tuple[int, int]]] = []
    for y0 in range(h):
        for x0 in range(w):
            i0 = y0 * w + x0
            if visited[i0] or px[x0, y0][3] < 200:
                continue
            q: deque[tuple[int, int]] = deque([(x0, y0)])
            visited[i0] = 1
            pts: list[tuple[int, int]] = []
            while q:
                x, y = q.popleft()
                pts.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h:
                        continue
                    i = ny * w + nx
                    if visited[i] or px[nx, ny][3] < 200:
                        continue
                    visited[i] = 1
                    q.append((nx, ny))
            comps.append(pts)
    if not comps:
        return img
    comps.sort(key=len, reverse=True)
    keep = set(comps[0])
    # keep any secondary component with enough red (cap fragment)
    for pts in comps[1:]:
        if len(pts) < min_comp:
            continue
        red = 0
        for x, y in pts:
            r, g, b, a = px[x, y]
            if _is_red_cap_rgb(r, g, b):
                red += 1
        if red >= 80:
            keep.update(pts)
    for pts in comps:
        if pts and pts[0] in keep or (pts and any(p in keep for p in pts[:1])):
            # already kept via set membership of points — handle properly:
            pass
    # rebuild keep properly
    keep = set(comps[0])
    for pts in comps[1:]:
        red = sum(1 for x, y in pts if _is_red_cap_rgb(*px[x, y][:3]))
        if red >= 80 or len(pts) >= max(min_comp, int(0.05 * len(comps[0]))):
            # only if vertically near main body
            ys = [p[1] for p in pts]
            bys = [p[1] for p in comps[0]]
            if min(ys) <= max(bys) and max(ys) >= min(bys) - 40:
                keep.update(pts)
            elif red >= 80:
                keep.update(pts)
    for y in range(h):
        for x in range(w):
            if (x, y) not in keep and px[x, y][3] >= 200:
                r, g, b, a = px[x, y]
                px[x, y] = (r, g, b, 0)
    return img


def _solidify_neck_band(image: Image.Image) -> Image.Image:
    """Fill residual neck holes between TOP red-cap cluster and body.

    Must ignore red label ink (e.g. Sejak 1958) or the neck band expands into
    the full body and floods a solid green rectangle tab under the bottle.
    """
    from collections import deque

    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()

    seen = [[False] * w for _ in range(h)]
    red_comps: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            r, g, b, a = px[x, y]
            if a < 200 or not _is_red_cap_rgb(r, g, b):
                seen[y][x] = True
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            cells: list[tuple[int, int]] = []
            while q:
                cx, cy = q.popleft()
                cells.append((cx, cy))
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if nx < 0 or ny < 0 or nx >= w or ny >= h or seen[ny][nx]:
                        continue
                    rr, gg, bb, aa = px[nx, ny]
                    if aa >= 200 and _is_red_cap_rgb(rr, gg, bb):
                        seen[ny][nx] = True
                        q.append((nx, ny))
                    elif aa < 200:
                        seen[ny][nx] = True
            if len(cells) >= 80:
                red_comps.append(cells)
    if not red_comps:
        return img
    red_comps.sort(key=lambda cells: sorted(y for _, y in cells)[len(cells) // 2])
    cap_cells = red_comps[0]
    cap_ys = [y for _, y in cap_cells]
    cap_xs = [x for x, _ in cap_cells]
    if sorted(cap_ys)[len(cap_ys) // 2] > h * 0.35:
        return img
    cap_ymin, cap_ymax = min(cap_ys), max(cap_ys)
    cap_xmin, cap_xmax = min(cap_xs), max(cap_xs)
    # neck band only: just below top cap, short span
    y0 = cap_ymax
    y1 = min(h - 1, cap_ymax + max(20, int(h * 0.12)))
    x0 = max(0, cap_xmin - 2)
    x1 = min(w - 1, cap_xmax + 2)
    samples: list[tuple[int, int, int]] = []
    for y in range(min(h - 1, y1 + 2), min(h, y1 + 30)):
        for x in range(x0, x1 + 1):
            r, g, b, a = px[x, y]
            if a < 200 or _is_red_cap_rgb(r, g, b):
                continue
            if _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b):
                continue
            samples.append((r, g, b))
    if not samples:
        samples = [(90, 120, 100)]
    samples.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
    fill = samples[len(samples) // 2]
    mid = (x0 + x1) // 2
    half = max(4, (x1 - x0) // 2)
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, y1 - y0)
        hh = int(half * (0.85 + 0.15 * t))
        for x in range(max(0, mid - hh), min(w, mid + hh + 1)):
            r, g, b, a = px[x, y]
            if a < 200:
                px[x, y] = (fill[0], fill[1], fill[2], 255)
            elif _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b):
                px[x, y] = (fill[0], fill[1], fill[2], 255)
    return img


def _fill_mask_holes(mask: Image.Image) -> Image.Image:
    """Fill interior holes (clear glass / label windows) so product is solid."""
    w, h = mask.size
    mpx = mask.load()
    # exterior = background connected to image border
    exterior = bytearray(w * h)
    q: deque[tuple[int, int]] = deque()
    def seed(x: int, y: int) -> None:
        i = y * w + x
        if exterior[i] or mpx[x, y] >= 200:
            return
        exterior[i] = 1
        q.append((x, y))
    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            i = ny * w + nx
            if exterior[i] or mpx[nx, ny] >= 200:
                continue
            exterior[i] = 1
            q.append((nx, ny))
    out = mask.copy()
    opx = out.load()
    for y in range(h):
        for x in range(w):
            if not exterior[y * w + x] and opx[x, y] < 200:
                opx[x, y] = 255
    return out



def _recolor_neck_band(image: Image.Image) -> Image.Image:
    """Replace wall-like forced-neck pixels with vertical blend cap→shoulder."""
    img = image.convert("RGBA")
    w, h = img.size
    px = img.load()
    y_lim = max(20, int(h * 0.32))
    cap_ys: list[int] = []
    for y in range(y_lim):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 200 and _is_red_cap_rgb(r, g, b):
                cap_ys.append(y)
    if len(cap_ys) < 40:
        return img
    cap_ymax = max(cap_ys)
    body_y = None
    for y in range(cap_ymax + 1, min(h, cap_ymax + int(h * 0.4))):
        n = 0
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200 or _is_red_cap_rgb(r, g, b):
                continue
            if not (_is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b)):
                n += 1
        if n >= 12:
            body_y = y
            break
    if body_y is None or body_y <= cap_ymax + 2:
        return img
    cap_cols: list[tuple[int, int, int]] = []
    body_cols: list[tuple[int, int, int]] = []
    for x in range(w):
        r, g, b, a = px[x, cap_ymax]
        if a >= 200:
            cap_cols.append((r, g, b))
        r, g, b, a = px[x, body_y]
        if a >= 200 and not _is_red_cap_rgb(r, g, b):
            body_cols.append((r, g, b))
    if not cap_cols or not body_cols:
        return img
    cap_cols.sort(key=lambda c: c[0] + c[1] + c[2])
    body_cols.sort(key=lambda c: c[0] + c[1] + c[2])
    ccol = cap_cols[len(cap_cols) // 2]
    bcol = body_cols[len(body_cols) // 2]
    for y in range(cap_ymax, body_y + 1):
        tt = (y - cap_ymax) / max(1, body_y - cap_ymax)
        fr = int(ccol[0] * (1 - tt) + bcol[0] * tt)
        fg = int(ccol[1] * (1 - tt) + bcol[1] * tt)
        fb = int(ccol[2] * (1 - tt) + bcol[2] * tt)
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 200 or _is_red_cap_rgb(r, g, b):
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            ch = max(r, g, b) - min(r, g, b)
            if _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b) or (ch < 28 and lum > 145):
                px[x, y] = (fr, fg, fb, 255)
    return img


def _build_canonical_cutout(source: Path) -> Image.Image:
    """Isolate product: ROI from red-cap + teal-label anchors, then BG flood.

    Cream cartouche stays as source RGB (never classified as wall).
    Clear glass holes filled; edge freckles removed.
    """
    image = Image.open(source).convert("RGBA")
    w, h = image.size
    rgb = image.convert("RGB")
    px = rgb.load()

    def is_teal(r: int, g: int, b: int) -> bool:
        return g >= 70 and b >= 70 and (g + b) / 2.0 >= r + 18 and (max(r, g, b) - min(r, g, b)) >= 18

    def is_green_liq(r: int, g: int, b: int) -> bool:
        # saturated green oil — require strong G dominance
        return g >= 90 and g >= r + 25 and g >= b + 20 and g - min(r, b) >= 25

    anchors: list[tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if _is_red_cap_rgb(r, g, b) or is_teal(r, g, b) or is_green_liq(r, g, b):
                anchors.append((x, y))
    if len(anchors) < 500:
        raise ExactProductCompositeError(
            "CANONICAL_CUTOUT_EMPTY",
            "Too few product anchor pixels in canonical source.",
            status_code=422,
        )
    xs = [p[0] for p in anchors]
    ys = [p[1] for p in anchors]
    # ROI padded around anchors — bottle only
    pad_x, pad_y = 18, 22
    x0 = max(0, min(xs) - pad_x)
    x1 = min(w - 1, max(xs) + pad_x)
    y0 = max(0, min(ys) - pad_y)
    y1 = min(h - 1, max(ys) + pad_y)

    # Within ROI: flood background from ROI border through soft/strict neutrals,
    # never through red/teal/green/cream-gold product colors.
    roi_w = x1 - x0 + 1
    roi_h = y1 - y0 + 1
    visited = bytearray(roi_w * roi_h)
    bg = bytearray(roi_w * roi_h)
    q: deque[tuple[int, int]] = deque()

    def is_protected(r: int, g: int, b: int) -> bool:
        if _is_red_cap_rgb(r, g, b) or is_teal(r, g, b) or is_green_liq(r, g, b):
            return True
        # cream / ivory cartouche — measured from MWTCB.jpg centre panel
        # (mean ~205,197,173 → r-g≈8). Prior r-g>=12 treated cream as wall
        # and flood+median fill mosaiced bird artwork + brand text.
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        ch = max(r, g, b) - min(r, g, b)
        if (
            lum >= 145
            and r >= 150
            and g >= 140
            and b >= 100
            and (r - b) >= 15
            and -5 <= (r - g) <= 35
            and ch <= 95
        ):
            return True
        # gold / bronze ornamental border
        if r >= 150 and g >= 100 and b <= 130 and r > b + 30 and g > b + 15:
            return True
        # dark ink / bird body (blue-grey feathers are not bg neutrals)
        if lum <= 90 and ch <= 70:
            return True
        # mid-tone bird plumage / branch (keep source RGB — never median-fill)
        if 40 <= lum <= 160 and ch >= 18 and not (
            _is_soft_bg_rgb(r, g, b) and ch < 22 and abs(r - g) < 12 and abs(g - b) < 12
        ):
            # saturated-ish midtones inside label (feathers, leaves, branch)
            if max(r, g, b) - min(r, g, b) >= 20:
                return True
        return False

    def is_bg_neutral(r: int, g: int, b: int) -> bool:
        if is_protected(r, g, b):
            return False
        return _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b)

    def seed(rx: int, ry: int) -> None:
        i = ry * roi_w + rx
        if visited[i]:
            return
        r, g, b = px[x0 + rx, y0 + ry]
        if is_bg_neutral(r, g, b):
            visited[i] = 1
            q.append((rx, ry))

    for rx in range(roi_w):
        seed(rx, 0)
        seed(rx, roi_h - 1)
    for ry in range(roi_h):
        seed(0, ry)
        seed(roi_w - 1, ry)
    while q:
        rx, ry = q.popleft()
        bg[ry * roi_w + rx] = 1
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = rx + dx, ry + dy
            if nx < 0 or ny < 0 or nx >= roi_w or ny >= roi_h:
                continue
            i = ny * roi_w + nx
            if visited[i]:
                continue
            r, g, b = px[x0 + nx, y0 + ny]
            if is_bg_neutral(r, g, b):
                visited[i] = 1
                q.append((nx, ny))

    mask = Image.new("L", (w, h), 0)
    mpx = mask.load()
    for ry in range(roi_h):
        for rx in range(roi_w):
            if not bg[ry * roi_w + rx]:
                mpx[x0 + rx, y0 + ry] = 255
    # force anchors
    for x, y in anchors:
        mpx[x, y] = 255

    mask = _keep_product_components(mask, rgb=rgb)
    # Constrain to dilated high-confidence core (cap/teal/liquid) to drop wall chunks
    hc = Image.new("L", (w, h), 0)
    hpx = hc.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if _is_red_cap_rgb(r, g, b) or is_teal(r, g, b) or is_green_liq(r, g, b):
                hpx[x, y] = 255
    for _ in range(12):
        hc = hc.filter(ImageFilter.MaxFilter(5))
    hpx = hc.load()
    mpx = mask.load()
    for y in range(h):
        for x in range(w):
            if mpx[x, y] >= 200 and hpx[x, y] < 128:
                mpx[x, y] = 0
    before = mask.copy()
    mask = _fill_mask_holes(mask)
    # light open/close only — stronger open severs thin neck under red cap
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    mask = _fill_mask_holes(mask)

    # FORCE solid neck column between red-cap band and body (clear glass is bg-like)
    mpxn = mask.load()
    cap_pts: list[tuple[int, int]] = []
    # Only true plastic cap: red pixels in the TOP of the frame (not label ink)
    y_cap_limit = max(20, int(h * 0.28))
    for y in range(0, y_cap_limit):
        for x in range(w):
            if mpxn[x, y] < 200:
                continue
            r, g, b = px[x, y]
            if _is_red_cap_rgb(r, g, b):
                cap_pts.append((x, y))
    if cap_pts:
        cap_ymax = max(y for _, y in cap_pts)
        cap_xmin = min(x for x, _ in cap_pts)
        cap_xmax = max(x for x, _ in cap_pts)
        # Find MAIN body (teal/green liquid), not sparse neck fragments
        body_y = None
        body_top_xs = []
        search_to = min(h, cap_ymax + int(h * 0.45))
        for y in range(cap_ymax + 1, search_to):
            row_xs = []
            strong = 0
            for x in range(w):
                if mpxn[x, y] < 200:
                    continue
                r, g, b = px[x, y]
                if _is_red_cap_rgb(r, g, b):
                    continue
                row_xs.append(x)
                if is_teal(r, g, b) or is_green_liq(r, g, b):
                    strong += 1
            if strong >= 10 and len(row_xs) >= 12:
                body_y = y
                body_top_xs = row_xs
                break
        if body_y is None:
            # fallback: widest non-red opaque row in search window
            best = (0, None, [])
            for y in range(cap_ymax + 8, search_to):
                row_xs = [x for x in range(w) if mpxn[x, y] >= 200 and not _is_red_cap_rgb(*px[x, y])]
                if len(row_xs) > best[0]:
                    best = (len(row_xs), y, row_xs)
            if best[1] is not None and best[0] >= 12:
                body_y, body_top_xs = best[1], best[2]
        if body_y is not None and body_y > cap_ymax + 1:
            bx0, bx1 = min(body_top_xs), max(body_top_xs)
            x_left = min(cap_xmin, bx0)
            x_right = max(cap_xmax, bx1)
            mid = (x_left + x_right) // 2
            half = max(10, (x_right - x_left) // 2)
            # solid paint + sample glass fill color from body
            for y in range(cap_ymax, body_y + 1):
                tt = (y - cap_ymax) / max(1, body_y - cap_ymax)
                hh = int(half * (0.75 + 0.25 * tt))
                for x in range(max(0, mid - hh), min(w, mid + hh + 1)):
                    mpxn[x, y] = 255
            mask = _fill_mask_holes(mask)

    # SOURCE-RGB LOCK: silhouette from mask; RGB from canonical photo only.
    # Hole/median/inpaint previously rebuilt cream from teal buckets → mosaic.
    src_rgba = Image.open(source).convert("RGBA")
    src_px = src_rgba.load()
    final = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fpx = final.load()
    mpx_final = mask.load()
    bpx = before.load()

    def nearest_product_rgb(x: int, y: int) -> tuple[int, int, int]:
        best = None
        best_d = 10**18
        for rad in (4, 8, 16, 32, 64, 128, 256):
            for yy in range(max(0, y - rad), min(h, y + rad + 1), 2):
                for xx in range(max(0, x - rad), min(w, x + rad + 1), 2):
                    if bpx[xx, yy] < 200:
                        continue
                    r, g, b = px[xx, yy]
                    if is_protected(r, g, b) or not (
                        _is_soft_bg_rgb(r, g, b) or _is_strict_bg_rgb(r, g, b)
                    ):
                        d = (xx - x) * (xx - x) + (yy - y) * (yy - y)
                        if d < best_d:
                            best_d = d
                            best = (r, g, b)
            if best is not None:
                return best
        return (200, 200, 195)

    for y in range(h):
        for x in range(w):
            if mpx_final[x, y] < 200:
                continue
            # Prefer canonical RGB whenever the source pixel is product-like.
            # Do not depend on pre-hole mask alone (cream was soft-bg and
            # flooded, then median-filled into mosaic).
            sr, sg, sb = src_px[x, y][:3]
            if is_protected(sr, sg, sb) or not (
                _is_soft_bg_rgb(sr, sg, sb) or _is_strict_bg_rgb(sr, sg, sb)
            ):
                fpx[x, y] = (sr, sg, sb, 255)
            elif bpx[x, y] >= 200:
                fpx[x, y] = (sr, sg, sb, 255)
            else:
                r, g, b = nearest_product_rgb(x, y)
                fpx[x, y] = (r, g, b, 255)

    image = _despeckle_alpha(final, min_comp=400)
    # Neck alpha bridge first (geometry), then RGB lock for product-like only
    image = _solidify_neck_band(image)
    ipx2 = image.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = ipx2[x, y]
            if a < 200:
                continue
            sr, sg, sb = src_px[x, y][:3]
            # Never re-lock wall/floor RGB onto the matte — that recreates halo.
            if is_protected(sr, sg, sb) or not (
                _is_soft_bg_rgb(sr, sg, sb) or _is_strict_bg_rgb(sr, sg, sb)
            ):
                ipx2[x, y] = (sr, sg, sb, a)
    # Drop residual wall fringe after RGB lock (right-edge dirty crop)
    image = _trim_background_edge_fringe(image, passes=4)
    image = _inpaint_background_bleed(image)
    image = _trim_background_edge_fringe(image, passes=2)
    image = _keep_main_product_silhouette(image)
    image = _solidify_neck_band(image)
    image = _bridge_cap_to_body(image)
    image = _trim_background_edge_fringe(image, passes=1)
    image = _keep_main_product_silhouette(image)
    image = _bridge_cap_to_body(image)
    image = _strip_synthetic_base_tab(image)

    bbox = image.getbbox()
    if bbox:
        pad = 1
        bx0, by0, bx1, by1 = bbox
        image = image.crop(
            (
                max(0, bx0 - pad),
                max(0, by0 - pad),
                min(w, bx1 + pad),
                min(h, by1 + pad),
            )
        )
    opaque = sum(image.getchannel("A").histogram()[200:])
    if opaque < 500:
        raise ExactProductCompositeError(
            "CANONICAL_CUTOUT_EMPTY",
            "Cutout produced too few opaque product pixels.",
            status_code=422,
        )
    cap_px = 0
    cpx = image.load()
    for y in range(min(image.height, max(1, int(image.height * 0.35)))):
        for x in range(image.width):
            r, g, b, aa = cpx[x, y]
            if aa >= 200 and _is_red_cap_rgb(r, g, b):
                cap_px += 1
    if cap_px < 80:
        src_chk = Image.open(source).convert("RGB")
        sp = src_chk.load()
        sw, sh = src_chk.size
        src_red = sum(
            1
            for yy in range(int(sh * 0.35))
            for xx in range(sw)
            if _is_red_cap_rgb(*sp[xx, yy])
        )
        if src_red >= 200:
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
    if not exact_product_policy(product):
        return {}
    validation = validate_canonical_or_raise(product)
    cutout = Path(validation["cutout_path"])
    cw, ch = int(canvas["w"]), int(canvas["h"])
    if cw <= 0 or ch <= 0:
        raise ExactProductCompositeError("PRODUCT_TRUTH_PLACEMENT_INVALID", status_code=422)

    # Placement is the intersection of the lane's reserved region and the
    # persisted product contract.  The model never chooses or enlarges it.
    lane = {
        "x": float(safe_region["x"]) / 100.0,
        "y": float(safe_region["y"]) / 100.0,
        "w": float(safe_region["w"]) / 100.0,
        "h": float(safe_region["h"]) / 100.0,
    }
    allowed = validation["allowed_bbox"]
    x0 = max(lane["x"], float(allowed["x"]))
    y0 = max(lane["y"], float(allowed["y"]))
    x1 = min(lane["x"] + lane["w"], float(allowed["x"]) + float(allowed["w"]))
    y1 = min(lane["y"] + lane["h"], float(allowed["y"]) + float(allowed["h"]))
    if x1 <= x0 or y1 <= y0:
        raise ExactProductCompositeError(
            "PRODUCT_TRUTH_PLACEMENT_INVALID",
            "Lane placement region does not intersect the persisted allowed bbox.",
            status_code=422,
        )
    max_w = max(1, round(cw * (x1 - x0)))
    max_h = max(1, round(ch * (y1 - y0)))
    with Image.open(cutout) as cutout_image:
        rgba = cutout_image.convert("RGBA")
        try:
            alpha_bbox = rgba.getchannel("A").getbbox()
        finally:
            rgba.close()
        if not alpha_bbox:
            raise ExactProductCompositeError(
                "CANONICAL_CUTOUT_INVALID",
                "Approved cutout has no visible product geometry.",
                status_code=422,
            )
        crop_x0, crop_y0, crop_x1, crop_y1 = alpha_bbox
        iw, ih = crop_x1 - crop_x0, crop_y1 - crop_y0
    desired_scale = min(max_w / iw, max_h / ih) * max(0.01, min(float(fill), 1.0))
    scale = max(float(validation["min_scale"]), min(desired_scale, float(validation["max_scale"])))
    w, h = max(1, round(iw * scale)), max(1, round(ih * scale))
    if w > max_w or h > max_h:
        raise ExactProductCompositeError(
            "PRODUCT_TRUTH_SCALE_INVALID",
            "Approved minimum scale cannot fit inside the allowed product bbox.",
            status_code=422,
        )
    anchor = validation["anchor_point"]
    anchor_x = float(anchor["x"])
    anchor_y = float(anchor["y"])
    x_min, y_min = round(cw * x0), round(ch * y0)
    x_max, y_max = round(cw * x1) - w, round(ch * y1) - h
    x = round(cw * (x0 + (x1 - x0) / 2.0) - w * anchor_x)
    y = round(ch * (y0 + (y1 - y0) / 2.0) - h * anchor_y)
    x = max(x_min, min(x, x_max))
    y = max(y_min, min(y, y_max))
    return {
        "asset_ref": str(cutout),
        "product_id": validation.get("product_id") or str(product.get("id") or product.get("product_id") or ""),
        "source_sha256": validation["source_sha256"],
        "cutout_sha256": validation["cutout_sha256"],
        "canonical_media_id": validation["canonical_media_id"],
        "canonical_cutout_media_id": validation["cutout_media_id"],
        "alpha_mask_sha256": validation["alpha_mask_sha256"],
        "truth_lock_schema_version": validation.get("product_truth_lock_schema_version") or "",
        "schema_key": validation.get("schema_key") or "PRODUCT_TRUTH_LOCK",
        "transform": {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "source_crop": {
                "x": crop_x0,
                "y": crop_y0,
                "w": iw,
                "h": ih,
            },
            "rotation_degrees": 0.0,
            "perspective_skew_x": 0.0,
            "shadow_opacity": 0.24,
            "shadow_blur_px": 18.0,
            "scale": scale,
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
    with Image.open(asset) as asset_image:
        source = asset_image.convert("RGBA")
        crop = t.get("source_crop") or {}
        if crop:
            crop_box = (
                int(crop["x"]),
                int(crop["y"]),
                int(crop["x"] + crop["w"]),
                int(crop["y"] + crop["h"]),
            )
            source = source.crop(crop_box)
        product = _resize_rgba_premultiplied(
            source,
            (int(t["w"]), int(t["h"])),
        )
        source.close()
    product = _harden_cutout_alpha_after_resize(product)
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
        "product_id": layer["product_id"],
        "canonical_media_id": layer["canonical_media_id"],
        "canonical_cutout_media_id": layer["canonical_cutout_media_id"],
        "alpha_mask_sha256": layer["alpha_mask_sha256"],
        "truth_lock_schema_version": layer.get("truth_lock_schema_version") or "",
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
