"""ONE shared OFFICIAL provider-reference preparation boundary.

Every product-conditioned provider VIDEO operation (Hybrid, reference-conditioned
Faceless, Montage product-anchor scenes, P6 provider stages) must obtain its
product reference from the OFFICIAL visual selected in Smart Product Registration
— never a listing thumbnail, a regenerated/inferred bottle, or a stale asset —
and must NEVER resize/stretch/reinterpret the product. When a provider needs a
different canvas/aspect the CANVAS is padded; the official product pixels are
preserved byte-for-byte.

This module is the single seam that turns the official visual into a
provider-ready reference and emits the full custody tuple + geometry contract so
the provider payload can be traced back to the current official chosen visual and
fails closed when it cannot.

It is deliberately provider-free (no upload here) and self-contained on hashing so
it can be imported by the custody seam without an import cycle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from agent.services.product_geometry_contract import OfficialProductVisualContract

# The ONLY source types that represent the official visual selected in Smart
# Product Registration (an approved Manual/Canva/Auto cutout, or an explicitly
# registered same-product Original Source). Every other resolver branch
# (schema canonical, product-row local path, product-row media id, reference-pack
# canonical, generic creative asset, materialized listing image_url) is NOT the
# registration-selected official visual and must fail closed for provider video.
OFFICIAL_REGISTRATION_SOURCE_TYPES = frozenset(
    {"PRODUCT_TRUTH_LOCK_CUTOUT", "PRODUCT_TRUTH_LOCK_SOURCE"}
)

ERR_OFFICIAL_PROVIDER_REFERENCE_NOT_REGISTERED = (
    "ERR_OFFICIAL_PROVIDER_REFERENCE_NOT_REGISTERED"
)
ERR_OFFICIAL_PROVIDER_REFERENCE_BYTES_UNREADABLE = (
    "ERR_OFFICIAL_PROVIDER_REFERENCE_BYTES_UNREADABLE"
)
ERR_OFFICIAL_PROVIDER_REFERENCE_HASH_MISMATCH = (
    "ERR_OFFICIAL_PROVIDER_REFERENCE_HASH_MISMATCH"
)
ERR_OFFICIAL_PROVIDER_REFERENCE_CANVAS_TOO_SMALL = (
    "ERR_OFFICIAL_PROVIDER_REFERENCE_CANVAS_TOO_SMALL"
)
ERR_OFFICIAL_PROVIDER_REFERENCE_PIXEL_FIDELITY = (
    "ERR_OFFICIAL_PROVIDER_REFERENCE_PIXEL_FIDELITY"
)


class OfficialProviderReferenceError(ValueError):
    """Stable fail-closed error for the official provider-reference boundary."""

    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details or {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(asset: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if isinstance(asset, dict) and asset.get(key) not in (None, ""):
            return asset.get(key)
    return None


def _asset_source_type(official_asset: dict[str, Any]) -> str:
    return str(
        _value(
            official_asset,
            "official_visual_source_type",
            "officialVisualSourceType",
            "source_type",
        )
        or ""
    ).strip().upper()


def _official_media_id(official_asset: dict[str, Any]) -> str | None:
    value = _value(official_asset, "media_id", "mediaId", "asset_id", "assetId")
    return str(value) if value not in (None, "") else None


def _official_sha256(official_asset: dict[str, Any]) -> str:
    return str(
        _value(official_asset, "official_visual_sha256", "officialVisualSha256", "sha256")
        or ""
    ).strip().lower()


def _local_path(official_asset: dict[str, Any]) -> Path | None:
    raw = _value(official_asset, "local_file_path", "localFilePath")
    if not raw:
        return None
    return Path(str(raw)).expanduser().resolve()


def _resolve_official_asset(product: dict[str, Any], slot_key: str) -> dict[str, Any]:
    # Late import keeps this module free of an import cycle through the resolver.
    from agent.services.product_visual_grounding_resolver import (
        build_official_product_visual_asset,
    )

    return build_official_product_visual_asset(
        product, slot_key=slot_key, label="Official product visual"
    )


def _product_bbox_px(image: Image.Image, *, is_cutout: bool) -> dict[str, int]:
    """Product bounding box within the official frame.

    A cutout carries a real alpha silhouette, so the product box is its alpha
    bbox. A flat official source photo has no segmentation; the whole frame is
    the reference and the box is the full frame (never a guessed crop).
    """
    w, h = image.size
    if is_cutout and image.mode in {"RGBA", "LA"}:
        alpha = image.convert("RGBA").getchannel("A")
        box = alpha.getbbox()
        if box:
            x0, y0, x1, y1 = box
            return {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)}
    return {"x": 0, "y": 0, "w": int(w), "h": int(h)}


def _build_geometry_contract(
    *,
    official_media_id: str | None,
    official_sha256: str,
    image: Image.Image,
    is_cutout: bool,
) -> dict[str, Any]:
    fw, fh = int(image.width), int(image.height)
    bbox = _product_bbox_px(image, is_cutout=is_cutout)
    bw = max(1, int(bbox["w"]))
    bh = max(1, int(bbox["h"]))
    normalized = {
        "x": (bbox["x"] / fw) if fw else 0.0,
        "y": (bbox["y"] / fh) if fh else 0.0,
        "w": (bw / fw) if fw else 0.0,
        "h": (bh / fh) if fh else 0.0,
    }
    is_transparent = image.mode in {"RGBA", "LA"}
    contract = OfficialProductVisualContract(
        official_media_id=str(official_media_id or ""),
        official_sha256=official_sha256,
        intrinsic_width=fw,
        intrinsic_height=fh,
        is_transparent=bool(is_transparent),
        product_bbox_px=bbox,
        normalized_bbox=normalized,
        product_aspect_ratio=(bw / bh),
    )
    return contract.to_dict()


def _pad_to_canvas(
    image: Image.Image, target_canvas: dict[str, int], destination: Path
) -> tuple[str, dict[str, int], bool]:
    """Pad (never resize) the official product onto a target canvas.

    The product keeps its native pixels; only transparent canvas is added. Fails
    closed if the product does not fit — the canvas must be expanded, the product
    is never shrunk.  Returns (prepared_sha256, canvas_padding, pixel_fidelity_verified).
    """
    tw, th = int(target_canvas["w"]), int(target_canvas["h"])
    product = image.convert("RGBA")
    pw, ph = product.size
    if pw > tw or ph > th:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_CANVAS_TOO_SMALL,
            "Target canvas is smaller than the official product; expand the canvas rather than shrink the product.",
            details={"product": [pw, ph], "canvas": [tw, th]},
        )
    x = (tw - pw) // 2
    y = (th - ph) // 2
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    canvas.paste(product, (x, y))  # native product pixels, unchanged
    # Byte-identity proof: the product region cropped back out must equal the
    # native product exactly (no resample, no reinterpretation).
    region = canvas.crop((x, y, x + pw, y + ph))
    pixel_fidelity_verified = ImageChops.difference(region, product).getbbox() is None
    if not pixel_fidelity_verified:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_PIXEL_FIDELITY,
            "Padding altered the official product pixels; refusing to dispatch a reinterpreted reference.",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG")
    padding = {"left": x, "top": y, "right": tw - pw - x, "bottom": th - ph - y}
    return _sha_bytes(destination), padding, pixel_fidelity_verified


def prepare_official_provider_reference(
    product: dict[str, Any],
    official_asset: dict[str, Any] | None = None,
    *,
    target_canvas: dict[str, int] | None = None,
    slot_key: str = "start_frame",
    require_registered: bool = True,
) -> dict[str, Any]:
    """Prepare the governed official provider reference for a product-conditioned
    provider video op.

    ``official_asset`` may be supplied by the caller (the flow gate already
    resolved it); otherwise it is resolved here. The official bytes are re-hashed
    fail-closed, the source is required to be the registration-selected official
    visual, a geometry contract is attached, and — when ``target_canvas`` is given
    and its aspect differs — the CANVAS is padded (product pixels preserved).
    """
    product_id = str(product.get("id") or product.get("product_id") or "").strip()
    if not product_id:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_NOT_REGISTERED,
            "Product id is required to resolve the official provider reference.",
        )
    if not isinstance(official_asset, dict):
        official_asset = _resolve_official_asset(product, slot_key)

    source_type = _asset_source_type(official_asset)
    if require_registered and source_type not in OFFICIAL_REGISTRATION_SOURCE_TYPES:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_NOT_REGISTERED,
            "The provider reference must be the official visual selected in Smart Product "
            "Registration (an approved cutout or a registered Original Source). "
            "A catalog/listing image, a stale generated asset, or an unregistered source "
            "is not eligible for product-conditioned provider video.",
            details={"product_id": product_id, "resolved_source_type": source_type},
        )

    official_sha256 = _official_sha256(official_asset)
    path = _local_path(official_asset)
    if not official_sha256 or path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_BYTES_UNREADABLE,
            "The official product visual has no readable server-owned bytes.",
            details={"product_id": product_id},
        )
    actual_sha = _sha_bytes(path)
    if actual_sha != official_sha256:
        raise OfficialProviderReferenceError(
            ERR_OFFICIAL_PROVIDER_REFERENCE_HASH_MISMATCH,
            "The official product visual bytes do not match the persisted SHA-256 authority.",
            details={"declared_sha256": official_sha256, "actual_sha256": actual_sha},
        )

    is_cutout = source_type == "PRODUCT_TRUTH_LOCK_CUTOUT" or str(
        _value(official_asset, "asset_source", "assetSource", "source") or ""
    ).upper().endswith("CUTOUT")

    with Image.open(path) as opened:
        opened.load()
        native_w, native_h = int(opened.width), int(opened.height)
        geometry_contract = _build_geometry_contract(
            official_media_id=_official_media_id(official_asset),
            official_sha256=official_sha256,
            image=opened,
            is_cutout=is_cutout,
        )
        product_pixel_dimensions = {
            "w": geometry_contract["product_bbox_px"]["w"],
            "h": geometry_contract["product_bbox_px"]["h"],
        }
        # Prepared reference: native official bytes unless a target aspect forces
        # a padded canvas.  Native aspect => no padding, prepared == official bytes.
        canvas_padding: dict[str, int] | None = None
        prepared_reference_sha256 = official_sha256
        reference_path = str(path)
        reference_width, reference_height = native_w, native_h
        pixel_fidelity_verified = True
        if target_canvas:
            tw, th = int(target_canvas.get("w") or 0), int(target_canvas.get("h") or 0)
            native_ar = native_w / native_h if native_h else 0.0
            target_ar = tw / th if th else 0.0
            if tw > 0 and th > 0 and abs(native_ar - target_ar) > 1e-3:
                destination = path.parent / f"provider-ref-{official_sha256[:16]}-{tw}x{th}.png"
                prepared_reference_sha256, canvas_padding, pixel_fidelity_verified = _pad_to_canvas(
                    opened, {"w": tw, "h": th}, destination
                )
                reference_path = str(destination)
                reference_width, reference_height = tw, th

    geometry_contract_digest = hashlib.sha256(
        _stable_json(geometry_contract).encode("utf-8")
    ).hexdigest()

    return {
        "product_id": product_id,
        "official_media_id": _official_media_id(official_asset),
        "official_sha256": official_sha256,
        "official_source_type": source_type,
        "geometry_contract": geometry_contract,
        "geometry_contract_digest": geometry_contract_digest,
        "reference_path": reference_path,
        "reference_width": reference_width,
        "reference_height": reference_height,
        "product_bbox": geometry_contract["product_bbox_px"],
        "product_pixel_dimensions": product_pixel_dimensions,
        "canvas_padding": canvas_padding,
        "product_rescaled": False,
        "pixel_fidelity_verified": bool(pixel_fidelity_verified),
        "prepared_reference_sha256": prepared_reference_sha256,
        "official_asset": official_asset,
    }
