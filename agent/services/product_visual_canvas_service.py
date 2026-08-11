"""Shared 1000x1000 product-visual canvas contract.

The Visual / Canva lane uses one working canvas for every product.  Raw
product sources may still arrive at different native dimensions, but every
cutout candidate and every durable truth-lock source is normalized to this
canvas before it enters the review/official-selection flow.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


STANDARD_VISUAL_CANVAS_WIDTH = 1000
STANDARD_VISUAL_CANVAS_HEIGHT = 1000
STANDARD_VISUAL_CANVAS_SIZE = (
    STANDARD_VISUAL_CANVAS_WIDTH,
    STANDARD_VISUAL_CANVAS_HEIGHT,
)
STANDARD_VISUAL_CANVAS_LABEL = "1000×1000 px"
STANDARD_VISUAL_CANVAS_REQUIREMENT = (
    "Manual / Canva cutouts must be transparent PNG files on an exact "
    "1000x1000 px canvas."
)


@dataclass(frozen=True)
class StandardizedImageFile:
    path: Path
    original_width: int
    original_height: int
    original_sha256: str
    standardized_sha256: str
    was_resized: bool


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def normalize_image_to_standard_canvas(raw_bytes: bytes) -> bytes:
    """Fit an image onto a centered, transparent 1000x1000 canvas.

    Aspect ratio is preserved.  A source that is already 1000x1000 is still
    encoded as PNG so the helper has one deterministic output format for
    generated candidates.
    """

    if not raw_bytes:
        raise ValueError("Image bytes are empty")
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            source = image.convert("RGBA")
            try:
                if image.size == STANDARD_VISUAL_CANVAS_SIZE and (image.format or "").upper() == "PNG":
                    return raw_bytes
                canvas = Image.new("RGBA", STANDARD_VISUAL_CANVAS_SIZE, (0, 0, 0, 0))
                fitted = ImageOps.contain(
                    source,
                    STANDARD_VISUAL_CANVAS_SIZE,
                    method=Image.Resampling.LANCZOS,
                )
                try:
                    left = (STANDARD_VISUAL_CANVAS_WIDTH - fitted.width) // 2
                    top = (STANDARD_VISUAL_CANVAS_HEIGHT - fitted.height) // 2
                    canvas.alpha_composite(fitted, (left, top))
                finally:
                    fitted.close()
                stream = io.BytesIO()
                try:
                    canvas.save(stream, format="PNG")
                    return stream.getvalue()
                finally:
                    canvas.close()
            finally:
                source.close()
    except Exception as exc:  # noqa: BLE001 - stable image boundary
        raise ValueError(f"Image cannot be normalized to the standard canvas: {exc}") from exc


def standardize_image_file_to_canvas(
    source_path: Path,
    destination_path: Path,
) -> StandardizedImageFile:
    """Return source evidence with a durable 1000x1000 representation.

    Existing 1000x1000 files are returned unchanged so their source SHA remains
    the source identity.  Non-standard files are written to the caller-owned
    destination as a centered PNG and retain the original dimensions/SHA in
    the returned receipt for provenance.
    """

    source_path = source_path.resolve()
    raw_bytes = source_path.read_bytes()
    with Image.open(io.BytesIO(raw_bytes)) as image:
        original_width, original_height = image.size
    original_sha256 = _sha256(raw_bytes)
    if (original_width, original_height) == STANDARD_VISUAL_CANVAS_SIZE:
        return StandardizedImageFile(
            path=source_path,
            original_width=original_width,
            original_height=original_height,
            original_sha256=original_sha256,
            standardized_sha256=original_sha256,
            was_resized=False,
        )

    normalized = normalize_image_to_standard_canvas(raw_bytes)
    destination_path = destination_path.resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_bytes(normalized)
    return StandardizedImageFile(
        path=destination_path,
        original_width=original_width,
        original_height=original_height,
        original_sha256=original_sha256,
        standardized_sha256=_sha256(normalized),
        was_resized=True,
    )
