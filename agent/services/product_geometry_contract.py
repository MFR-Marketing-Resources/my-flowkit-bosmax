"""Shared OFFICIAL_PRODUCT_VISUAL_CONTRACT.

The single machine-readable geometry-lock payload that every product-reference
generation path must carry so the official Smart-Registration visual's apparent
geometry/scale (silhouette, label position & relative dimensions, cap/body/base
proportions, apparent package capacity) is preserved end to end. Consumers MUST
NOT rescale/stretch/reinterpret the product; if more room is needed they expand
the canvas, never the product.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class OfficialProductVisualContract:
    official_media_id: str
    official_sha256: str
    intrinsic_width: int
    intrinsic_height: int
    is_transparent: bool
    # Visible product bounding box in the canonical-frame pixels.
    product_bbox_px: dict[str, int]
    # Same box normalized to 0..1 of the canonical frame.
    normalized_bbox: dict[str, float]
    product_aspect_ratio: float
    geometry_lock_enabled: bool = True
    preserve_silhouette: bool = True
    preserve_label_position: bool = True
    preserve_label_dimensions: bool = True
    preserve_cap_body_base_proportions: bool = True
    preserve_apparent_capacity: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_dimensions(dimensions: str) -> tuple[int, int]:
    try:
        w, h = str(dimensions).lower().split("x", 1)
        return int(float(w)), int(float(h))
    except (ValueError, AttributeError):
        return 0, 0


def build_official_product_visual_contract(
    validation: Mapping[str, Any],
    *,
    product_bbox_px: Mapping[str, int] | None = None,
    is_transparent: bool = True,
) -> OfficialProductVisualContract:
    """Build the geometry-lock contract from a ``validate_canonical_or_raise`` dict.

    ``product_bbox_px`` is the product's alpha bounding box within the canonical
    frame (px). If omitted it is derived from the persisted ``allowed_bbox`` and
    intrinsic frame dimensions so the contract is always populated.
    """
    fw, fh = _parse_dimensions(validation.get("dimensions", ""))
    allowed = dict(validation.get("allowed_bbox") or {})
    if product_bbox_px is None:
        product_bbox_px = {
            "x": int(round(float(allowed.get("x", 0.0)) * fw)),
            "y": int(round(float(allowed.get("y", 0.0)) * fh)),
            "w": max(1, int(round(float(allowed.get("w", 0.0)) * fw))),
            "h": max(1, int(round(float(allowed.get("h", 0.0)) * fh))),
        }
    bw = max(1, int(product_bbox_px.get("w", 1)))
    bh = max(1, int(product_bbox_px.get("h", 1)))
    normalized = {
        "x": (product_bbox_px.get("x", 0) / fw) if fw else float(allowed.get("x", 0.0)),
        "y": (product_bbox_px.get("y", 0) / fh) if fh else float(allowed.get("y", 0.0)),
        "w": (bw / fw) if fw else float(allowed.get("w", 0.0)),
        "h": (bh / fh) if fh else float(allowed.get("h", 0.0)),
    }
    return OfficialProductVisualContract(
        official_media_id=str(validation.get("canonical_media_id") or ""),
        official_sha256=str(validation.get("source_sha256") or ""),
        intrinsic_width=fw,
        intrinsic_height=fh,
        is_transparent=bool(is_transparent),
        product_bbox_px=dict(product_bbox_px),
        normalized_bbox=normalized,
        product_aspect_ratio=(bw / bh),
    )
