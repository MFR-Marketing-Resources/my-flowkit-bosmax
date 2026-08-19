"""Server-side product truth lock resolution and byte-level validation.

This service is intentionally read-only during generation.  A product truth
lock is created and approved by a controlled onboarding/review lane; IMG
generation may only consume an already persisted, APPROVED contract.  Prompt
text, browser state, client hashes, OCR, CLIP, and a checkbox are not authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from agent.config import BASE_DIR, DB_PATH
from agent.db import crud
from agent.models.product_truth_lock import (
    ProductTruthLock,
    ProductTruthLockApprovalRequest,
    ProductTruthLockOnboardingRequest,
)
from agent.services.product_visual_canvas_service import (
    STANDARD_VISUAL_CANVAS_HEIGHT,
    STANDARD_VISUAL_CANVAS_LABEL,
    STANDARD_VISUAL_CANVAS_SIZE,
    STANDARD_VISUAL_CANVAS_WIDTH,
    standardize_image_file_to_canvas,
)


class ProductTruthLockError(ValueError):
    """Stable fail-closed product truth error."""

    def __init__(self, code: str, message: str = "", *, status_code: int = 422):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code


AUTO_GENERATED = "AUTO_GENERATED"
USER_UPLOAD = "USER_UPLOAD"
CANONICAL_REFERENCE = "CANONICAL_REFERENCE"
ACTIVE_CANONICAL_CUTOUT = "APPROVED_CANONICAL_CUTOUT"
ACTIVE_SAME_PRODUCT_FALLBACK = "SAME_PRODUCT_TRUSTED_SOURCE"


@dataclass(frozen=True)
class ResolvedProductTruthLock:
    product_id: str
    canonical_media_id: str
    canonical_sha256: str
    source_width: int
    source_height: int
    canonical_source_path: str
    canonical_cutout_media_id: str
    canonical_cutout_sha256: str
    canonical_cutout_path: str
    alpha_mask_sha256: str
    anchor_point: dict[str, float]
    min_scale: float
    max_scale: float
    allowed_bbox: dict[str, float]
    allowed_rotation: float
    allowed_perspective: float
    review_status: str
    provenance: dict[str, Any]
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _path_from_server_record(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def _row_for_product(product_id: str) -> dict[str, Any] | None:
    if not product_id:
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM product_visual_truth_lock WHERE product_id = ?",
                (product_id,),
            ).fetchone()
            return dict(row) if row else None
    except sqlite3.OperationalError as exc:
        # A legacy database without the additive table is equivalent to no
        # contract.  It must never fall back to the product row or schema prompt.
        if "no such table" in str(exc).lower():
            return None
        raise


def _json_field(row: dict[str, Any], name: str, default: Any) -> Any:
    raw = row.get(name)
    if raw in (None, ""):
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_INVALID",
            f"{name} is not valid JSON",
        ) from exc


def _cutout_source_kind(row: dict[str, Any]) -> str:
    provenance = _json_field(row, "provenance_json", {})
    declared = str(
        provenance.get("source_kind")
        or provenance.get("cutout_source")
        or ""
    ).upper()
    if declared in {AUTO_GENERATED, USER_UPLOAD, CANONICAL_REFERENCE}:
        return declared
    created_by = str(provenance.get("created_by") or "").lower()
    return AUTO_GENERATED if created_by.startswith("system:") else USER_UPLOAD


def _safe_upload_filename(filename: str | None) -> str:
    """Keep the operator label while preventing path components in metadata."""
    raw = str(filename or "").replace("\\", "/")
    safe = Path(raw).name.strip()
    if not safe or safe in {".", ".."}:
        return "manual-cutout.png"
    return safe[:255]


def _uploaded_cutout_details(
    raw_bytes: bytes,
    *,
    expected_dimensions: tuple[int, int] | None = None,
) -> tuple[int, int, str, tuple[int, int, int, int]]:
    """Decode and validate a transparent PNG without resizing or mutating it."""
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            if (image.format or "").upper() != "PNG":
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_MIME_INVALID",
                    "Manual product cutouts must be PNG files; JPEG and other formats are rejected.",
                )
            width, height = image.size
            if width <= 0 or height <= 0 or width > 8192 or height > 8192:
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_DIMENSIONS_INVALID",
                    "Manual cutout dimensions must be positive and no larger than 8192px per side.",
                )
            if expected_dimensions and (width, height) != expected_dimensions:
                expected_width, expected_height = expected_dimensions
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_DIMENSIONS_MISMATCH",
                    f"Manual cutout must use the standard {expected_width}x{expected_height} px canvas; "
                    f"received {width}x{height}.",
                )
            rgba = image.convert("RGBA")
            try:
                alpha = rgba.getchannel("A")
                extrema = alpha.getextrema()
                bbox = alpha.getbbox()
                if extrema[1] <= 0 or extrema[0] >= 255 or bbox is None:
                    raise ProductTruthLockError(
                        "CANONICAL_CUTOUT_ALPHA_REQUIRED",
                        "Manual cutout must contain transparent background and visible product geometry.",
                    )
                return width, height, _sha256_bytes(alpha.tobytes()), bbox
            finally:
                rgba.close()
    except ProductTruthLockError:
        raise
    except Exception as exc:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            f"Manual cutout cannot be decoded as a valid PNG: {exc}",
        ) from exc


def _model_from_row(row: dict[str, Any]) -> ProductTruthLock:
    payload = dict(row)
    payload["alpha_mask"] = _json_field(row, "alpha_mask_json", {})
    payload["anchor_point"] = _json_field(row, "anchor_point_json", {})
    payload["allowed_bbox"] = _json_field(row, "allowed_bbox_json", {})
    payload["provenance"] = _json_field(row, "provenance_json", {})
    for key in (
        "alpha_mask_json",
        "anchor_point_json",
        "allowed_bbox_json",
        "provenance_json",
        "created_at",
        "updated_at",
    ):
        payload.pop(key, None)
    try:
        return ProductTruthLock.model_validate(payload)
    except Exception as exc:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_INVALID",
            f"Persisted product truth contract failed schema validation: {exc}",
        ) from exc


def load_product_truth_lock(product_id: str) -> ProductTruthLock | None:
    """Load only the persisted contract; never synthesize one from product data."""

    row = _row_for_product(product_id)
    if row is None:
        return None
    lock = _model_from_row(row)
    if lock.product_id != product_id:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_PRODUCT_MISMATCH",
            "Persisted truth lock does not belong to the requested product.",
        )
    return lock


def _number_map(
    value: dict[str, float],
    *,
    name: str,
    keys: tuple[str, ...],
    lower: float,
    upper: float,
) -> dict[str, float]:
    if any(key not in value for key in keys):
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_INVALID",
            f"{name} must contain {', '.join(keys)}",
        )
    result: dict[str, float] = {}
    for key in keys:
        item = value[key]
        if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ProductTruthLockError(
                "PRODUCT_TRUTH_LOCK_INVALID",
                f"{name}.{key} must be finite",
            )
        number = float(item)
        if number < lower or number > upper:
            raise ProductTruthLockError(
                "PRODUCT_TRUTH_LOCK_INVALID",
                f"{name}.{key} is outside [{lower}, {upper}]",
            )
        result[key] = number
    return result


def _validate_alpha_mask(lock: ProductTruthLock, cutout: Path) -> str:
    try:
        with Image.open(cutout) as image:
            if image.width <= 0 or image.height <= 0:
                raise ProductTruthLockError("CANONICAL_CUTOUT_INVALID", "Cutout dimensions are invalid.")
            rgba = image.convert("RGBA")
            alpha = rgba.getchannel("A")
            alpha_extrema = alpha.getextrema()
            if alpha_extrema[1] <= 0 or alpha_extrema[0] >= 255:
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_INVALID",
                    "Approved cutout must contain both transparent and opaque geometry.",
                )
            if alpha.getbbox() is None:
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_INVALID",
                    "Approved cutout alpha mask is empty.",
                )
            alpha_sha = _sha256_bytes(alpha.tobytes())
            alpha_width, alpha_height = alpha.size
    except ProductTruthLockError:
        raise
    except Exception as exc:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            f"Approved cutout cannot be decoded: {exc}",
        ) from exc

    mask = lock.alpha_mask
    source = str(mask.get("source") or "").strip().lower()
    declared_sha = str(mask.get("sha256") or "").strip().lower()
    if source != "cutout_alpha":
        raise ProductTruthLockError(
            "CANONICAL_ALPHA_MASK_REQUIRED",
            "The persisted alpha mask must be the approved cutout alpha channel or a reviewed mask file.",
        )
    if declared_sha != alpha_sha:
        raise ProductTruthLockError(
            "CANONICAL_ALPHA_MASK_INVALID",
            "Cutout alpha mask hash does not match the persisted contract.",
        )
    try:
        declared_width = int(mask.get("width") or 0)
        declared_height = int(mask.get("height") or 0)
    except (TypeError, ValueError) as exc:
        raise ProductTruthLockError(
            "CANONICAL_ALPHA_MASK_INVALID",
            "Cutout alpha mask dimensions must be integers.",
        ) from exc
    if declared_width != alpha_width or declared_height != alpha_height:
        raise ProductTruthLockError(
            "CANONICAL_ALPHA_MASK_INVALID",
            "Cutout alpha mask dimensions do not match the approved cutout.",
        )
    return alpha_sha


def resolve_product_truth_cutout_preview(product_id: str) -> Path:
    """Return the server-owned cutout used by the pending/approved review lock."""

    lock = load_product_truth_lock(product_id)
    if lock is None:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_REQUIRED",
            "No onboarding lock exists for this product.",
            status_code=404,
        )
    cutout = _path_from_server_record(lock.canonical_cutout_path)
    try:
        cutout.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Persisted cutout path is outside the server media root.",
            status_code=403,
        ) from exc
    if not cutout.exists() or not cutout.is_file() or cutout.stat().st_size == 0:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Persisted canonical cutout is missing.",
            status_code=404,
        )
    return cutout


def _validate_lock_bytes(lock: ProductTruthLock) -> ResolvedProductTruthLock:
    source = _path_from_server_record(lock.canonical_source_path)
    cutout = _path_from_server_record(lock.canonical_cutout_path)
    for code, path in (
        ("CANONICAL_PRODUCT_SOURCE_INVALID", source),
        ("CANONICAL_CUTOUT_INVALID", cutout),
    ):
        if not path.exists() or not path.is_file() or path.stat().st_size == 0:
            raise ProductTruthLockError(code, f"Persisted canonical file is missing: {path}")

    if _sha256_path(source) != lock.canonical_sha256:
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Canonical source SHA-256 does not match the persisted product truth lock.",
        )
    try:
        with Image.open(source) as source_image:
            source_dimensions = source_image.size
            source_rgba = source_image.convert("RGBA")
            try:
                if source_rgba.getchannel("A").getextrema()[1] <= 0:
                    raise ProductTruthLockError(
                        "CANONICAL_PRODUCT_SOURCE_INVALID",
                        "Canonical source is fully transparent and cannot prove product identity.",
                    )
            finally:
                source_rgba.close()
    except Exception as exc:
        if isinstance(exc, ProductTruthLockError):
            raise
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            f"Canonical source cannot be decoded: {exc}",
        ) from exc
    if source_dimensions != (lock.source_width, lock.source_height):
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Canonical source dimensions do not match the persisted product truth lock.",
        )

    if _sha256_path(cutout) != lock.canonical_cutout_sha256:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Canonical cutout SHA-256 does not match the persisted product truth lock.",
        )
    try:
        with Image.open(cutout) as cutout_image:
            cutout_dimensions = cutout_image.size
    except Exception as exc:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            f"Canonical cutout cannot be decoded: {exc}",
        ) from exc
    alpha_sha = _validate_alpha_mask(lock, cutout)

    _number_map(
        lock.anchor_point,
        name="anchor_point",
        keys=("x", "y"),
        lower=0.0,
        upper=1.0,
    )
    bbox = _number_map(
        lock.allowed_bbox,
        name="allowed_bbox",
        keys=("x", "y", "w", "h"),
        lower=0.0,
        upper=1.0,
    )
    if bbox["w"] <= 0 or bbox["h"] <= 0 or bbox["x"] + bbox["w"] > 1 or bbox["y"] + bbox["h"] > 1:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_PLACEMENT_INVALID",
            "Allowed product bounding box must be positive and stay inside the canvas.",
        )
    if lock.min_scale > lock.max_scale:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_SCALE_INVALID",
            "min_scale cannot exceed max_scale.",
        )
    if lock.review_status != "APPROVED":
        raise ProductTruthLockError(
            "HUMAN_REVIEW_REQUIRED",
            "Product truth lock is not approved for exact output.",
        )
    if str(lock.provenance.get("active_selection") or "").upper() == ACTIVE_SAME_PRODUCT_FALLBACK:
        raise ProductTruthLockError(
            "SAME_PRODUCT_FALLBACK_SELECTED",
            "The operator selected same-product fallback; the cutout is not active for exact commerce.",
        )
    if not all(
        (
            lock.identity_lock,
            lock.geometry_lock,
            lock.label_lock,
            lock.logo_lock,
            lock.colour_lock,
            lock.scale_lock,
        )
    ):
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_INCOMPLETE",
            "All identity, geometry, label, logo, colour, and scale locks must be true.",
        )
    if lock.failure_state:
        raise ProductTruthLockError(
            "HUMAN_REVIEW_REQUIRED",
            f"Product truth lock carries failure state: {lock.failure_state}",
        )

    return ResolvedProductTruthLock(
        product_id=lock.product_id,
        canonical_media_id=lock.canonical_media_id,
        canonical_sha256=lock.canonical_sha256,
        source_width=lock.source_width,
        source_height=lock.source_height,
        canonical_source_path=str(source),
        canonical_cutout_media_id=lock.canonical_cutout_media_id,
        canonical_cutout_sha256=lock.canonical_cutout_sha256,
        canonical_cutout_path=str(cutout),
        alpha_mask_sha256=alpha_sha,
        anchor_point={key: float(lock.anchor_point[key]) for key in ("x", "y")},
        min_scale=float(lock.min_scale),
        max_scale=float(lock.max_scale),
        allowed_bbox={key: float(bbox[key]) for key in ("x", "y", "w", "h")},
        allowed_rotation=float(lock.allowed_rotation),
        allowed_perspective=float(lock.allowed_perspective),
        review_status=lock.review_status,
        provenance=dict(lock.provenance),
        schema_version=lock.schema_version,
    )


def resolve_approved_product_truth_lock(product_id: str) -> ResolvedProductTruthLock:
    """Resolve and validate the exact contract, failing before any provider call."""

    lock = load_product_truth_lock(product_id)
    if lock is None:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_REQUIRED",
            "No persisted approved product truth lock exists for this product.",
        )
    return _validate_lock_bytes(lock)


def inspect_product_truth_lock(product_id: str) -> dict[str, Any]:
    """Return a safe status payload for UI/preflight gates without auto-approving."""

    row = _row_for_product(product_id)
    if row is None:
        return {
            "product_id": product_id,
            "lock_present": False,
            "lock_valid": False,
            "exact_allowed": False,
            "review_status": None,
            "product_truth_status": "PRODUCT_TRUTH_LOCK_REQUIRED",
            "failure_state": "PRODUCT_TRUTH_LOCK_REQUIRED",
        }
    review_status = str(row.get("review_status") or "")
    try:
        lock = _model_from_row(row)
        resolved = _validate_lock_bytes(lock)
        return {
            "product_id": product_id,
            "lock_present": True,
            "lock_valid": True,
            "exact_allowed": True,
            "review_status": resolved.review_status,
            "product_truth_status": "PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
            "failure_state": "",
            "canonical_media_id": resolved.canonical_media_id,
            "canonical_sha256": resolved.canonical_sha256,
            "canonical_cutout_media_id": resolved.canonical_cutout_media_id,
            "canonical_cutout_sha256": resolved.canonical_cutout_sha256,
            "source_width": resolved.source_width,
            "source_height": resolved.source_height,
            "provenance": resolved.provenance,
            "schema_version": resolved.schema_version,
        }
    except ProductTruthLockError as exc:
        status = "HUMAN_REVIEW_REQUIRED" if review_status != "APPROVED" else exc.code
        return {
            "product_id": product_id,
            "lock_present": True,
            "lock_valid": False,
            "exact_allowed": False,
            "review_status": review_status or None,
            "product_truth_status": status,
            "failure_state": exc.code,
            "error": exc.message,
            "canonical_media_id": lock.canonical_media_id,
            "canonical_sha256": lock.canonical_sha256,
            "canonical_cutout_media_id": lock.canonical_cutout_media_id,
            "canonical_cutout_sha256": lock.canonical_cutout_sha256,
            "source_width": lock.source_width,
            "source_height": lock.source_height,
            "provenance": dict(lock.provenance),
            "schema_version": lock.schema_version,
        }


def standard_product_truth_status(product_id: str | None) -> str:
    """Honest status for reference-conditioned output; it is never an exact pass."""

    if not product_id:
        return "NOT_APPLICABLE"
    return "NON_DETERMINISTIC_REFERENCE_CONDITIONED"


def validate_product_truth_lock_for_approval(lock: ProductTruthLock) -> ResolvedProductTruthLock:
    """Validate a candidate whose status has already been set to APPROVED.

    This is deliberately separate from persistence: callers must validate the
    candidate bytes and all locks before writing the approved state.
    """

    return _validate_lock_bytes(lock)


def _truth_lock_directory(product_id: str) -> Path:
    product_digest = hashlib.sha256(product_id.encode("utf-8")).hexdigest()[:24]
    return BASE_DIR / "data" / "exact-product" / f"product-{product_digest}"


def _truth_lock_bytes_match(
    source: Path,
    cutout: Path,
    *,
    expected_source_sha256: str,
    expected_cutout_sha256: str,
) -> bool:
    try:
        return (
            source.is_file()
            and cutout.is_file()
            and _sha256_path(source) == expected_source_sha256
            and _sha256_path(cutout) == expected_cutout_sha256
        )
    except (OSError, RuntimeError, ValueError):
        return False


def _find_exact_truth_lock_store_path(
    product_id: str,
    expected_sha256: str,
) -> Path | None:
    """Find an exact persisted byte copy inside this product's store only."""
    if len(expected_sha256) != 64:
        return None
    try:
        base_directory = BASE_DIR.resolve()
        product_directory = _truth_lock_directory(product_id).resolve()
        product_directory.relative_to(base_directory)
        if not product_directory.is_dir():
            return None
        candidates = product_directory.rglob("*")
    except (OSError, RuntimeError, ValueError):
        return None

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(product_directory)
            resolved.relative_to(base_directory)
            if (
                not resolved.is_file()
                or resolved.stat().st_size <= 0
                or _sha256_path(resolved) != expected_sha256
            ):
                continue
            return resolved
        except (OSError, RuntimeError, ValueError):
            continue
    return None


def _copy_exact_truth_lock_store_path(
    source: Path,
    target: Path,
    *,
    expected_sha256: str,
) -> bool:
    """Materialize one already-verified store byte copy at its lock path."""
    temporary: Path | None = None
    try:
        target.resolve().relative_to(BASE_DIR.resolve())
        if target.is_symlink():
            return False
        if target.is_file() and _sha256_path(target) == expected_sha256:
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        shutil.copyfile(source, temporary)
        if _sha256_path(temporary) != expected_sha256:
            return False
        temporary.replace(target)
        return target.is_file() and _sha256_path(target) == expected_sha256
    except (OSError, RuntimeError, ValueError):
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _recover_exact_truth_lock_store_bytes(
    product_id: str,
    *,
    expected_source_sha256: str,
    expected_cutout_sha256: str,
    canonical_source: Path,
    canonical_cutout: Path,
) -> bool:
    """Recover both lock bytes only from exact hashes in the product store."""
    source_candidate = _find_exact_truth_lock_store_path(product_id, expected_source_sha256)
    cutout_candidate = _find_exact_truth_lock_store_path(product_id, expected_cutout_sha256)
    if source_candidate is None or cutout_candidate is None:
        return False
    if not _copy_exact_truth_lock_store_path(
        source_candidate,
        canonical_source,
        expected_sha256=expected_source_sha256,
    ):
        return False
    if not _copy_exact_truth_lock_store_path(
        cutout_candidate,
        canonical_cutout,
        expected_sha256=expected_cutout_sha256,
    ):
        return False
    return _truth_lock_bytes_match(
        canonical_source,
        canonical_cutout,
        expected_source_sha256=expected_source_sha256,
        expected_cutout_sha256=expected_cutout_sha256,
    )


def _server_path_string(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(BASE_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return str(resolved)


def _safe_media_path(raw_path: Any) -> Path:
    value = str(raw_path or "").strip()
    if not value:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Reviewed cutout media has no local file path.",
        )
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    resolved = path.resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Reviewed cutout media path is outside the server media root.",
        ) from exc
    if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size == 0:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Reviewed cutout media file is missing or empty.",
        )
    return resolved


def _resolve_canonical_reference(product: dict[str, Any]) -> Any:
    from agent.services import product_visual_grounding_resolver as resolver

    try:
        return resolver.resolve_product_reference_image(dict(product), prefer_approved_cutout=False)
    except TypeError as exc:
        # Compatibility seam for narrow test doubles and legacy callers that
        # predate the explicit resolver preference keyword.
        if "prefer_approved_cutout" not in str(exc):
            raise
        return resolver.resolve_product_reference_image(dict(product))


async def register_product_truth_cutout_media(
    product_id: str,
    *,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
    expected_dimensions: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Persist a transparent review cutout as server-owned ``STORED`` media.

    This is an onboarding input lane only. It does not create a truth lock or
    change review status. The media ID returned by ``crud`` is the real
    persisted registry ID consumed by the separate onboarding endpoint.
    """

    if not raw_bytes:
        raise ProductTruthLockError("CANONICAL_CUTOUT_INVALID", "Uploaded cutout is empty.")
    if len(raw_bytes) > 10 * 1024 * 1024:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            "Uploaded cutout exceeds the 10 MB review-media limit.",
            status_code=413,
        )
    normalized_mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime and normalized_mime != "image/png":
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_MIME_INVALID",
            "Manual product cutouts must declare image/png MIME type.",
        )

    product = await crud.get_product(product_id)
    if not product:
        raise ProductTruthLockError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)

    try:
        reference = _resolve_canonical_reference(dict(product))
    except Exception as exc:
        if isinstance(exc, ProductTruthLockError):
            raise
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            f"Server could not resolve the canonical product source: {exc}",
        ) from exc

    width, height, _alpha_sha, _bbox = _uploaded_cutout_details(
        raw_bytes,
        expected_dimensions=expected_dimensions or STANDARD_VISUAL_CANVAS_SIZE,
    )

    cutout_sha = _sha256_bytes(raw_bytes)
    existing_media = await crud.list_product_source_media(product_id=product_id)
    for row in existing_media:
        if str(row.get("kind") or "") != "image":
            continue
        try:
            path = _safe_media_path(row.get("local_path"))
        except ProductTruthLockError:
            continue
        if _sha256_path(path) == cutout_sha:
            return {
                "product_id": product_id,
                "media_id": row.get("media_id"),
                "kind": "image",
                "filename": row.get("filename") or _safe_upload_filename(filename),
                "mime": row.get("mime") or content_type or "image/png",
                "bytes": len(raw_bytes),
                "width": width,
                "height": height,
                "status": str(row.get("status") or "STORED"),
                "review_status": "PENDING_REVIEW",
                "sha256": cutout_sha,
                "reused": True,
            }

    directory = _truth_lock_directory(product_id)
    directory.mkdir(parents=True, exist_ok=True)
    durable_path = directory / f"review_cutout_{cutout_sha[:16]}.png"
    durable_path.write_bytes(raw_bytes)
    safe_filename = _safe_upload_filename(filename)
    try:
        row = await crud.create_product_source_media(
            f"visual-lock:{product_id}",
            "image",
            product_id=product_id,
            local_path=_server_path_string(durable_path),
            filename=safe_filename,
            mime="image/png",
            bytes=len(raw_bytes),
            width=width,
            height=height,
            status="STORED",
        )
    except Exception:
        durable_path.unlink(missing_ok=True)
        raise
    if not row or not str(row.get("media_id") or "").strip():
        durable_path.unlink(missing_ok=True)
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_MEDIA_REQUIRED",
            "Server could not persist a media ID for the reviewed cutout.",
        )
    return {
        "product_id": product_id,
        "media_id": row.get("media_id") if row else None,
        "kind": "image",
        "filename": safe_filename or durable_path.name,
        "mime": "image/png",
        "bytes": len(raw_bytes),
        "width": width,
        "height": height,
        "status": "STORED",
        "review_status": "PENDING_REVIEW",
        "sha256": cutout_sha,
        "reused": False,
    }


def _validate_placement(request: ProductTruthLockOnboardingRequest) -> None:
    _number_map(
        request.anchor_point,
        name="anchor_point",
        keys=("x", "y"),
        lower=0.0,
        upper=1.0,
    )
    bbox = _number_map(
        request.allowed_bbox,
        name="allowed_bbox",
        keys=("x", "y", "w", "h"),
        lower=0.0,
        upper=1.0,
    )
    if bbox["w"] <= 0 or bbox["h"] <= 0 or bbox["x"] + bbox["w"] > 1 or bbox["y"] + bbox["h"] > 1:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_PLACEMENT_INVALID",
            "Allowed product bounding box must be positive and stay inside the canvas.",
        )
    if request.min_scale > request.max_scale:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_SCALE_INVALID",
            "min_scale cannot exceed max_scale.",
        )


def _inspect_source(path: Path) -> tuple[int, int, str, str]:
    try:
        raw = path.read_bytes()
        with Image.open(path) as image:
            width, height = image.size
            fmt = (image.format or "png").lower()
            if fmt == "jpg":
                fmt = "jpeg"
            rgba = image.convert("RGBA")
            try:
                if rgba.getchannel("A").getextrema()[1] <= 0:
                    raise ProductTruthLockError(
                        "CANONICAL_PRODUCT_SOURCE_INVALID",
                        "Canonical source is fully transparent and cannot prove product identity.",
                    )
            finally:
                rgba.close()
        return width, height, f"image/{fmt}", _sha256_bytes(raw)
    except ProductTruthLockError:
        raise
    except Exception as exc:
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            f"Canonical source cannot be decoded: {exc}",
        ) from exc


def _prepare_durable_assets(
    product_id: str,
    source_path: Path,
    cutout_path: Path,
    *,
    source_width: int,
    source_height: int,
    version_id: str | None = None,
) -> tuple[Path, Path, str, str, dict[str, Any]]:
    directory = _truth_lock_directory(product_id)
    if version_id:
        directory = directory / "versions" / version_id
    directory.mkdir(parents=True, exist_ok=True)

    source_suffix = source_path.suffix.lower()
    if source_suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        source_suffix = ".png"
    durable_source = directory / f"canonical_source{source_suffix}"
    durable_cutout = directory / "canonical_cutout.png"
    shutil.copyfile(source_path, durable_source)

    try:
        with Image.open(cutout_path) as cutout_image:
            if cutout_image.size != (source_width, source_height):
                raise ProductTruthLockError(
                    "CANONICAL_CUTOUT_DIMENSIONS_MISMATCH",
                    (
                        f"Reviewed cutout must use the standard {STANDARD_VISUAL_CANVAS_WIDTH}x{STANDARD_VISUAL_CANVAS_HEIGHT} px canvas."
                        if (source_width, source_height) == STANDARD_VISUAL_CANVAS_SIZE
                        else "Reviewed cutout dimensions must match the canonical product source dimensions."
                    ),
                )
            rgba = cutout_image.convert("RGBA")
            try:
                alpha = rgba.getchannel("A")
                extrema = alpha.getextrema()
                if extrema[1] <= 0 or extrema[0] >= 255:
                    raise ProductTruthLockError(
                        "CANONICAL_CUTOUT_INVALID",
                        "Reviewed cutout must contain both transparent and opaque geometry.",
                    )
                if alpha.getbbox() is None:
                    raise ProductTruthLockError(
                        "CANONICAL_CUTOUT_INVALID",
                        "Reviewed cutout alpha mask is empty.",
                    )
                alpha_sha = _sha256_bytes(alpha.tobytes())
                alpha_mask = {
                    "source": "cutout_alpha",
                    "sha256": alpha_sha,
                    "width": alpha.width,
                    "height": alpha.height,
                }
                rgba.save(durable_cutout, format="PNG")
            finally:
                rgba.close()
    except ProductTruthLockError:
        durable_source.unlink(missing_ok=True)
        durable_cutout.unlink(missing_ok=True)
        raise
    except Exception as exc:
        durable_source.unlink(missing_ok=True)
        durable_cutout.unlink(missing_ok=True)
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_INVALID",
            f"Reviewed cutout cannot be decoded: {exc}",
        ) from exc

    return (
        durable_source,
        durable_cutout,
        _sha256_path(durable_source),
        _sha256_path(durable_cutout),
        alpha_mask,
    )


def _bound_recovery_media_path(
    media: dict[str, Any] | None,
    *,
    product_id: str,
) -> Path | None:
    """Resolve one immutable product-bound media file for byte recovery."""
    if (
        not media
        or str(media.get("product_id") or "") != str(product_id)
        or str(media.get("kind") or "").lower() != "image"
        or str(media.get("status") or "").upper() not in {"STORED", "APPROVED"}
    ):
        return None
    raw_path = str(media.get("local_path") or "").strip()
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    resolved = path.resolve()
    try:
        resolved.relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        return None
    return resolved


async def _recover_bound_truth_lock_bytes(
    product_id: str,
    existing: dict[str, Any],
    *,
    canonical_source: Path,
    canonical_cutout: Path,
    source_media_path: Path,
    cutout_media_path: Path,
) -> str | None:
    """Rebuild durable bytes from bound media only when persisted SHA matches."""
    expected_source_sha = str(existing.get("canonical_sha256") or "").strip().lower()
    expected_cutout_sha = str(existing.get("canonical_cutout_sha256") or "").strip().lower()
    if len(expected_source_sha) != 64 or len(expected_cutout_sha) != 64:
        return None

    recovery_id = f"recovery-{uuid.uuid4().hex}"
    recovery_directory = _truth_lock_directory(product_id) / "versions" / recovery_id
    try:
        source_kind = _cutout_source_kind(existing)
        if source_kind == AUTO_GENERATED:
            standardized_source_path = source_media_path
        else:
            standardized_source = standardize_image_file_to_canvas(
                source_media_path,
                recovery_directory / "standardized-source.png",
            )
            standardized_source_path = standardized_source.path

        (
            recovered_source,
            recovered_cutout,
            recovered_source_sha,
            recovered_cutout_sha,
            recovered_alpha_mask,
        ) = _prepare_durable_assets(
            product_id,
            standardized_source_path,
            cutout_media_path,
            source_width=int(existing.get("source_width") or 0),
            source_height=int(existing.get("source_height") or 0),
            version_id=recovery_id,
        )
        expected_alpha_sha = str(
            _json_field(existing, "alpha_mask_json", {}).get("sha256") or ""
        ).strip().lower()
        if (
            recovered_source_sha != expected_source_sha
            or recovered_cutout_sha != expected_cutout_sha
            or (
                expected_alpha_sha
                and str(recovered_alpha_mask.get("sha256") or "").lower()
                != expected_alpha_sha
            )
        ):
            return None

        canonical_source.parent.mkdir(parents=True, exist_ok=True)
        canonical_cutout.parent.mkdir(parents=True, exist_ok=True)
        if not _copy_exact_truth_lock_store_path(
            recovered_source,
            canonical_source,
            expected_sha256=expected_source_sha,
        ):
            return None
        if not _copy_exact_truth_lock_store_path(
            recovered_cutout,
            canonical_cutout,
            expected_sha256=expected_cutout_sha,
        ):
            return None
        if _truth_lock_bytes_match(
            canonical_source,
            canonical_cutout,
            expected_source_sha256=expected_source_sha,
            expected_cutout_sha256=expected_cutout_sha,
        ):
            return "DETERMINISTIC_BOUND_MEDIA_SHA256_VERIFIED"
        return None
    except (OSError, ValueError, ProductTruthLockError):
        return None
    finally:
        shutil.rmtree(recovery_directory, ignore_errors=True)


async def _recover_missing_truth_lock_bytes(
    product_id: str,
    existing: dict[str, Any],
    *,
    canonical_source: Path,
    canonical_cutout: Path,
) -> str | None:
    """Recover missing bytes from bound media or exact product-local history."""
    source_media_id = str(existing.get("canonical_media_id") or "").strip()
    cutout_media_id = str(existing.get("canonical_cutout_media_id") or "").strip()
    if source_media_id and cutout_media_id:
        source_media = await crud.get_product_source_media(source_media_id)
        cutout_media = await crud.get_product_source_media(cutout_media_id)
        source_media_path = _bound_recovery_media_path(source_media, product_id=product_id)
        cutout_media_path = _bound_recovery_media_path(cutout_media, product_id=product_id)
        if source_media_path is not None and cutout_media_path is not None:
            recovered = await _recover_bound_truth_lock_bytes(
                product_id,
                existing,
                canonical_source=canonical_source,
                canonical_cutout=canonical_cutout,
                source_media_path=source_media_path,
                cutout_media_path=cutout_media_path,
            )
            if recovered:
                return recovered

    expected_source_sha = str(existing.get("canonical_sha256") or "").strip().lower()
    expected_cutout_sha = str(existing.get("canonical_cutout_sha256") or "").strip().lower()
    if _recover_exact_truth_lock_store_bytes(
        product_id,
        expected_source_sha256=expected_source_sha,
        expected_cutout_sha256=expected_cutout_sha,
        canonical_source=canonical_source,
        canonical_cutout=canonical_cutout,
    ):
        return "TRUTH_LOCK_STORE_SHA256_VERIFIED"
    return None


async def _archive_existing_truth_lock(
    product_id: str,
    existing: dict[str, Any],
    *,
    superseded_by_media_id: str,
    reason: str,
) -> str:
    """Archive the former active candidate before replacing the one-row SSOT.

    Copies the prior locked bytes into history when they are present (or can be
    recovered from bound media / the local store). When they are genuinely
    unrecoverable, records a metadata-only tombstone instead of blocking — so a
    lost byte store can never permanently trap a legitimate replacement, while the
    audit trail (SHAs, ids, dims, provenance) is preserved in the DB. Returns the
    history_id.
    """
    history_id = uuid.uuid4().hex
    history_directory = _truth_lock_directory(product_id) / "history" / history_id
    history_directory.mkdir(parents=True, exist_ok=False)
    try:
        source = _path_from_server_record(str(existing.get("canonical_source_path") or ""))
        cutout = _path_from_server_record(str(existing.get("canonical_cutout_path") or ""))
        history_byte_recovery = None
        expected_source_sha = str(existing.get("canonical_sha256") or "").strip().lower()
        expected_cutout_sha = str(existing.get("canonical_cutout_sha256") or "").strip().lower()
        if not _truth_lock_bytes_match(
            source,
            cutout,
            expected_source_sha256=expected_source_sha,
            expected_cutout_sha256=expected_cutout_sha,
        ):
            history_byte_recovery = await _recover_missing_truth_lock_bytes(
                product_id,
                existing,
                canonical_source=source,
                canonical_cutout=cutout,
            )
        if not _truth_lock_bytes_match(
            source,
            cutout,
            expected_source_sha256=expected_source_sha,
            expected_cutout_sha256=expected_cutout_sha,
        ):
            # The prior locked bytes are genuinely unrecoverable — the runtime byte
            # store was separated from the promoted DB (e.g. the cutout was generated
            # in a since-pruned worktree). Hard-blocking the replace does NOT bring
            # those bytes back; it only traps the operator permanently. Archive a
            # metadata-only TOMBSTONE instead: the DB already holds the true SHAs,
            # media ids, dimensions and provenance, so the audit trail's integrity
            # (what was locked, when, and what superseded it) is fully preserved even
            # though the raw bytes are gone. See
            # docs/incident-truth-lock-byte-store-desync.md.
            shutil.rmtree(history_directory, ignore_errors=True)
            tombstone_provenance = _json_field(existing, "provenance_json", {})
            tombstone_provenance.update(
                {
                    "history_id": history_id,
                    "superseded_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "superseded_by_media_id": superseded_by_media_id,
                    "superseded_reason": reason,
                    "history_byte_status": "UNAVAILABLE",
                    "history_byte_unavailable_reason": (
                        "Prior truth-lock bytes were absent from the runtime store at "
                        "supersession and could not be recovered; archived as a metadata "
                        "tombstone to preserve the audit record without blocking replacement."
                    ),
                    "expected_source_sha256": expected_source_sha or None,
                    "expected_cutout_sha256": expected_cutout_sha or None,
                }
            )
            if history_byte_recovery:
                tombstone_provenance["history_byte_recovery"] = history_byte_recovery
            await crud.create_product_truth_lock_history(
                product_id,
                history_id=history_id,
                source_kind=_cutout_source_kind(existing),
                review_status=str(existing.get("review_status") or "UNKNOWN"),
                canonical_media_id=existing.get("canonical_media_id"),
                canonical_sha256=existing.get("canonical_sha256"),
                source_width=existing.get("source_width"),
                source_height=existing.get("source_height"),
                canonical_source_path=None,
                canonical_cutout_media_id=existing.get("canonical_cutout_media_id"),
                canonical_cutout_sha256=existing.get("canonical_cutout_sha256"),
                canonical_cutout_path=None,
                alpha_mask_json=str(existing.get("alpha_mask_json") or "{}"),
                anchor_point_json=str(existing.get("anchor_point_json") or "{}"),
                allowed_bbox_json=str(existing.get("allowed_bbox_json") or "{}"),
                provenance_json=json.dumps(tombstone_provenance, sort_keys=True),
                superseded_by_media_id=superseded_by_media_id,
                superseded_reason=reason,
            )
            return history_id
        archived_source = history_directory / f"canonical_source{source.suffix.lower() or '.bin'}"
        archived_cutout = history_directory / "canonical_cutout.png"
        shutil.copyfile(source, archived_source)
        shutil.copyfile(cutout, archived_cutout)
        provenance = _json_field(existing, "provenance_json", {})
        provenance.update(
            {
                "history_id": history_id,
                "superseded_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "superseded_by_media_id": superseded_by_media_id,
                "superseded_reason": reason,
            }
        )
        if history_byte_recovery:
            provenance["history_byte_recovery"] = history_byte_recovery
        await crud.create_product_truth_lock_history(
            product_id,
            history_id=history_id,
            source_kind=_cutout_source_kind(existing),
            review_status=str(existing.get("review_status") or "UNKNOWN"),
            canonical_media_id=existing.get("canonical_media_id"),
            canonical_sha256=existing.get("canonical_sha256"),
            source_width=existing.get("source_width"),
            source_height=existing.get("source_height"),
            canonical_source_path=_server_path_string(archived_source),
            canonical_cutout_media_id=existing.get("canonical_cutout_media_id"),
            canonical_cutout_sha256=existing.get("canonical_cutout_sha256"),
            canonical_cutout_path=_server_path_string(archived_cutout),
            alpha_mask_json=str(existing.get("alpha_mask_json") or "{}"),
            anchor_point_json=str(existing.get("anchor_point_json") or "{}"),
            allowed_bbox_json=str(existing.get("allowed_bbox_json") or "{}"),
            provenance_json=json.dumps(provenance, sort_keys=True),
            superseded_by_media_id=superseded_by_media_id,
            superseded_reason=reason,
        )
        return history_id
    except ProductTruthLockError:
        shutil.rmtree(history_directory, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(history_directory, ignore_errors=True)
        raise ProductTruthLockError(
            "TRUTH_LOCK_HISTORY_REQUIRED",
            f"Previous truth-lock candidate could not be archived: {exc}",
            status_code=409,
        ) from exc


def _safe_result(
    *,
    product_id: str,
    review_status: str,
    exact_allowed: bool,
    product_truth_status: str,
    failure_state: str,
    canonical_media_id: str | None = None,
    canonical_sha256: str | None = None,
    canonical_cutout_media_id: str | None = None,
    canonical_cutout_sha256: str | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
    provenance: dict[str, Any] | None = None,
    schema_version: str = "1.0",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "product_id": product_id,
        "lock_present": True,
        "lock_valid": exact_allowed,
        "exact_allowed": exact_allowed,
        "review_status": review_status,
        "product_truth_status": product_truth_status,
        "failure_state": failure_state,
        "schema_version": schema_version,
    }
    for key, value in {
        "canonical_media_id": canonical_media_id,
        "canonical_sha256": canonical_sha256,
        "canonical_cutout_media_id": canonical_cutout_media_id,
        "canonical_cutout_sha256": canonical_cutout_sha256,
        "source_width": source_width,
        "source_height": source_height,
        "provenance": provenance,
    }.items():
        if value is not None:
            result[key] = value
    return result


async def create_pending_product_truth_lock(
    product_id: str,
    request: ProductTruthLockOnboardingRequest,
    *,
    allow_approved_replacement: bool = False,
    source_kind: str = USER_UPLOAD,
    original_filename: str | None = None,
    uploaded_by: str | None = None,
    uploaded_at: str | None = None,
    supersede_reason: str | None = None,
    provenance_source: str | None = None,
) -> dict[str, Any]:
    """Create a server-owned, human-review-only lock from a cutout candidate."""

    product = await crud.get_product(product_id)
    if not product:
        raise ProductTruthLockError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    existing = await crud.get_product_truth_lock(product_id)
    if source_kind not in {AUTO_GENERATED, USER_UPLOAD, CANONICAL_REFERENCE}:
        raise ProductTruthLockError("PRODUCT_TRUTH_SOURCE_INVALID", "Unsupported cutout provenance source.")
    if provenance_source is not None and provenance_source not in {
        "CANVA_MAGIC_GRAB",
        "CANVA_BG_REMOVER",
        "CANVA_MAGIC_LAYERS",
    }:
        raise ProductTruthLockError("PRODUCT_TRUTH_SOURCE_INVALID", "Unsupported Canva cutout provenance source.")
    if existing and str(existing.get("review_status") or "") == "APPROVED" and not allow_approved_replacement:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_IMMUTABLE",
            "An approved product truth lock can only be replaced by an explicit manual cutout upload.",
            status_code=409,
        )

    _validate_placement(request)
    media = await crud.get_product_source_media(request.canonical_cutout_media_id)
    if not media or str(media.get("kind") or "") != "image":
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_MEDIA_REQUIRED",
            "Onboarding requires an existing reviewed image media item.",
        )
    if str(media.get("status") or "").upper() not in {"STORED", "APPROVED"}:
        raise ProductTruthLockError(
            "CANONICAL_CUTOUT_MEDIA_REQUIRED",
            "The selected cutout media is not in a reviewable stored state.",
        )
    cutout_path = _safe_media_path(media.get("local_path"))

    try:
        reference = _resolve_canonical_reference(dict(product))
    except Exception as exc:
        if isinstance(exc, ProductTruthLockError):
            raise
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            f"Server could not resolve the canonical product source: {exc}",
        ) from exc
    canonical_media_id = str(reference.media_id or "").strip()
    if not canonical_media_id:
        raise ProductTruthLockError(
            "CANONICAL_MEDIA_ID_REQUIRED",
            "The server-resolved canonical product source has no stable media ID.",
        )
    source_path = Path(str(reference.local_path or "")).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "The server-resolved canonical product source is missing.",
        )
    source_width, source_height, _mime, source_sha = _inspect_source(source_path)
    if (source_width, source_height) != (int(reference.width), int(reference.height)):
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Canonical source dimensions changed during onboarding.",
        )
    reference_sha = str(reference.sha256 or "").strip().lower()
    if reference_sha and source_sha != reference_sha:
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Canonical source SHA-256 changed during onboarding.",
        )

    if source_kind == AUTO_GENERATED:
        # The historical Auto Cutout lane is paused and remains byte/dimension
        # compatible with its existing native-source contract.  The fixed
        # 1000x1000 canvas applies to the active Manual / Canva lane only.
        standardized_source_path = source_path
        standardized_source_sha = source_sha
        original_source_width = source_width
        original_source_height = source_height
        source_was_resized = False
    else:
        standardized_source = standardize_image_file_to_canvas(
            source_path,
            _truth_lock_directory(product_id)
            / "standardized-source"
            / f"source-1000x1000-{source_sha[:16]}.png",
        )
        standardized_source_path = standardized_source.path
        standardized_source_sha = standardized_source.standardized_sha256
        original_source_width = standardized_source.original_width
        original_source_height = standardized_source.original_height
        source_was_resized = standardized_source.was_resized
        source_width = STANDARD_VISUAL_CANVAS_WIDTH
        source_height = STANDARD_VISUAL_CANVAS_HEIGHT

    if existing:
        await _archive_existing_truth_lock(
            product_id,
            existing,
            superseded_by_media_id=request.canonical_cutout_media_id,
            reason=supersede_reason or "REPLACED_BY_NEW_CUTOUT_CANDIDATE",
        )

    version_id = uuid.uuid4().hex
    durable_source, durable_cutout, durable_source_sha, durable_cutout_sha, alpha_mask = _prepare_durable_assets(
        product_id,
        standardized_source_path,
        cutout_path,
        source_width=source_width,
        source_height=source_height,
        version_id=version_id,
    )
    if durable_source_sha != standardized_source_sha:
        durable_source.unlink(missing_ok=True)
        durable_cutout.unlink(missing_ok=True)
        raise ProductTruthLockError(
            "CANONICAL_PRODUCT_SOURCE_INVALID",
            "Durable standardized canonical source copy changed bytes during onboarding.",
        )

    provenance = {
        "source_kind": source_kind,
        "source": provenance_source or source_kind,
        "cutout_provenance": provenance_source or source_kind,
        "onboarding_method": (
            "CANVA_ASSISTED_MANUAL_HANDOFF"
            if provenance_source
            else "DETERMINISTIC_AUTO_CUTOUT" if source_kind == AUTO_GENERATED else "USER_SUPPLIED_MANUAL_CUTOUT"
        ),
        "created_by": uploaded_by or request.created_by,
        "uploaded_by": uploaded_by or request.created_by,
        "uploaded_at": uploaded_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "original_filename": _safe_upload_filename(original_filename or media.get("filename")),
        "mime": "image/png",
        "width": source_width,
        "height": source_height,
        "sha256": durable_cutout_sha,
        "review_status": "PENDING_REVIEW",
        "approval_status": "PENDING_REVIEW",
        "active_selection": "CANDIDATE",
        "onboarding_note": request.onboarding_note,
        "canonical_source_type": str(reference.source_type or ""),
        "canonical_source_provenance": str(reference.provenance or ""),
        "canonical_media_id": canonical_media_id,
        "source_media_id": request.canonical_cutout_media_id,
        "source_media_sha256": _sha256_path(cutout_path),
        "version_id": version_id,
        "human_review_required": True,
    }
    if source_kind != AUTO_GENERATED:
        provenance.update(
            {
                "canonical_canvas_width": STANDARD_VISUAL_CANVAS_WIDTH,
                "canonical_canvas_height": STANDARD_VISUAL_CANVAS_HEIGHT,
                "canonical_canvas_label": STANDARD_VISUAL_CANVAS_LABEL,
                "canonical_canvas_requirement": (
                    "Manual / Canva cutouts must be transparent PNG files on an exact "
                    "1000x1000 px canvas."
                ),
                "source_normalization": (
                    "FIT_CONTAIN_CENTER_PRESERVE_ASPECT"
                    if source_was_resized
                    else "SOURCE_ALREADY_1000X1000"
                ),
                "original_source_width": original_source_width,
                "original_source_height": original_source_height,
                "original_source_sha256": source_sha,
            }
        )
    if provenance_source:
        provenance["canva_provenance_source"] = provenance_source
    if existing:
        provenance["supersedes_previous_media_id"] = existing.get("canonical_cutout_media_id")
        provenance["supersedes_previous_sha256"] = existing.get("canonical_cutout_sha256")
        provenance["supersede_reason"] = supersede_reason or "REPLACED_BY_NEW_CUTOUT_CANDIDATE"
    await crud.upsert_product_truth_lock(
        product_id,
        canonical_media_id=canonical_media_id,
        canonical_sha256=durable_source_sha,
        source_width=source_width,
        source_height=source_height,
        canonical_source_path=_server_path_string(durable_source),
        canonical_cutout_media_id=request.canonical_cutout_media_id,
        canonical_cutout_sha256=durable_cutout_sha,
        canonical_cutout_path=_server_path_string(durable_cutout),
        alpha_mask_json=json.dumps(alpha_mask, sort_keys=True),
        anchor_point_json=json.dumps(request.anchor_point, sort_keys=True),
        min_scale=request.min_scale,
        max_scale=request.max_scale,
        allowed_bbox_json=json.dumps(request.allowed_bbox, sort_keys=True),
        allowed_rotation=0.0,
        allowed_perspective=0.0,
        identity_lock=0,
        geometry_lock=0,
        label_lock=0,
        logo_lock=0,
        colour_lock=0,
        scale_lock=0,
        review_status="PENDING_REVIEW",
        failure_state="HUMAN_REVIEW_REQUIRED",
        provenance_json=json.dumps(provenance, sort_keys=True),
        schema_version="1.0",
    )
    return _safe_result(
        product_id=product_id,
        review_status="PENDING_REVIEW",
        exact_allowed=False,
        product_truth_status="HUMAN_REVIEW_REQUIRED",
        failure_state="HUMAN_REVIEW_REQUIRED",
        canonical_media_id=canonical_media_id,
        canonical_sha256=durable_source_sha,
        canonical_cutout_media_id=request.canonical_cutout_media_id,
        canonical_cutout_sha256=durable_cutout_sha,
        source_width=source_width,
        source_height=source_height,
        provenance=provenance,
    )


async def approve_product_truth_lock(
    product_id: str,
    request: ProductTruthLockApprovalRequest,
) -> dict[str, Any]:
    """Approve only an existing pending lock after explicit human confirmation."""

    if not (
        request.confirm_identity
        and request.confirm_label_logo
        and request.confirm_geometry_scale
        and request.confirm_product_isolation
    ):
        raise ProductTruthLockError(
            "HUMAN_REVIEW_CONFIRMATION_REQUIRED",
            "Identity, label/logo, geometry/scale, and product-isolation "
            "confirmations are all required.",
            status_code=409,
        )
    lock = load_product_truth_lock(product_id)
    if lock is None:
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_REQUIRED",
            "No onboarding lock exists for this product.",
        )
    if lock.review_status == "APPROVED":
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_IMMUTABLE",
            "An approved product truth lock is immutable.",
            status_code=409,
        )
    if lock.review_status != "PENDING_REVIEW":
        raise ProductTruthLockError(
            "PRODUCT_TRUTH_LOCK_NOT_PENDING_REVIEW",
            "Only a PENDING_REVIEW lock can be approved.",
            status_code=409,
        )

    reviewed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    provenance = dict(lock.provenance)
    provenance.update(
        {
            "reviewed_by": request.reviewed_by,
            "review_note": request.review_note,
            "reviewed_at": reviewed_at,
            "review_status": "APPROVED",
            "approval_status": "APPROVED",
            "approved_by": request.reviewed_by,
            "approved_at": reviewed_at,
            "active_selection": ACTIVE_CANONICAL_CUTOUT,
            "human_review_required": False,
            "confirm_product_isolation": request.confirm_product_isolation,
        }
    )
    candidate = lock.model_copy(
        update={
            "identity_lock": True,
            "geometry_lock": True,
            "label_lock": True,
            "logo_lock": True,
            "colour_lock": True,
            "scale_lock": True,
            "review_status": "APPROVED",
            "failure_state": "",
            "provenance": provenance,
        }
    )
    resolved = validate_product_truth_lock_for_approval(candidate)
    await crud.upsert_product_truth_lock(
        product_id,
        canonical_media_id=candidate.canonical_media_id,
        canonical_sha256=candidate.canonical_sha256,
        source_width=candidate.source_width,
        source_height=candidate.source_height,
        canonical_source_path=candidate.canonical_source_path,
        canonical_cutout_media_id=candidate.canonical_cutout_media_id,
        canonical_cutout_sha256=candidate.canonical_cutout_sha256,
        canonical_cutout_path=candidate.canonical_cutout_path,
        alpha_mask_json=json.dumps(candidate.alpha_mask, sort_keys=True),
        anchor_point_json=json.dumps(candidate.anchor_point, sort_keys=True),
        min_scale=candidate.min_scale,
        max_scale=candidate.max_scale,
        allowed_bbox_json=json.dumps(candidate.allowed_bbox, sort_keys=True),
        allowed_rotation=candidate.allowed_rotation,
        allowed_perspective=candidate.allowed_perspective,
        identity_lock=1,
        geometry_lock=1,
        label_lock=1,
        logo_lock=1,
        colour_lock=1,
        scale_lock=1,
        review_status="APPROVED",
        failure_state="",
        provenance_json=json.dumps(provenance, sort_keys=True),
        schema_version=candidate.schema_version,
    )
    return _safe_result(
        product_id=product_id,
        review_status="APPROVED",
        exact_allowed=True,
        product_truth_status="PRODUCT_TRUTH_PRESERVED_EXACT_COMPOSITE",
        failure_state="",
        canonical_media_id=resolved.canonical_media_id,
        canonical_sha256=resolved.canonical_sha256,
        canonical_cutout_media_id=resolved.canonical_cutout_media_id,
        canonical_cutout_sha256=resolved.canonical_cutout_sha256,
        source_width=resolved.source_width,
        source_height=resolved.source_height,
        provenance=resolved.provenance,
        schema_version=resolved.schema_version,
    )


async def reject_product_truth_lock(
    product_id: str,
    *,
    rejected_by: str,
    reason: str,
) -> dict[str, Any]:
    """Record an explicit human rejection while retaining candidate bytes."""
    operator = str(rejected_by or "").strip()
    note = str(reason or "").strip()
    if not operator or not note:
        raise ProductTruthLockError(
            "HUMAN_REVIEW_NOTE_REQUIRED",
            "A reviewer identity and rejection reason are required.",
            status_code=409,
        )
    lock = load_product_truth_lock(product_id)
    if lock is None:
        raise ProductTruthLockError("PRODUCT_TRUTH_LOCK_REQUIRED", "No cutout candidate exists for this product.", status_code=404)
    rejected_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    provenance = dict(lock.provenance)
    provenance.update(
        {
            "review_status": "REJECTED_BY_USER",
            "approval_status": "REJECTED_BY_USER",
            "rejected_by": operator,
            "rejection_reason": note,
            "rejected_at": rejected_at,
            "active_selection": ACTIVE_SAME_PRODUCT_FALLBACK,
            "human_review_required": False,
        }
    )
    await crud.upsert_product_truth_lock(
        product_id,
        review_status="REJECTED",
        failure_state="REJECTED_BY_USER",
        identity_lock=0,
        geometry_lock=0,
        label_lock=0,
        logo_lock=0,
        colour_lock=0,
        scale_lock=0,
        provenance_json=json.dumps(provenance, sort_keys=True),
    )
    return {
        "product_id": product_id,
        "review_status": "REJECTED_BY_USER",
        "exact_allowed": False,
        "active_selection": ACTIVE_SAME_PRODUCT_FALLBACK,
        "provenance": provenance,
    }


async def select_product_truth_fallback(
    product_id: str,
    *,
    selected_by: str,
    reason: str,
) -> dict[str, Any]:
    """Select the trusted same-product source without deleting any candidate."""
    operator = str(selected_by or "").strip()
    note = str(reason or "").strip()
    if not operator or not note:
        raise ProductTruthLockError(
            "HUMAN_REVIEW_NOTE_REQUIRED",
            "A reviewer identity and fallback reason are required.",
            status_code=409,
        )
    lock = load_product_truth_lock(product_id)
    if lock is None:
        return {
            "product_id": product_id,
            "review_status": "NOT_CREATED",
            "exact_allowed": False,
            "active_selection": ACTIVE_SAME_PRODUCT_FALLBACK,
        }
    selected_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    provenance = dict(lock.provenance)
    provenance.update(
        {
            "active_selection": ACTIVE_SAME_PRODUCT_FALLBACK,
            "fallback_selected_by": operator,
            "fallback_reason": note,
            "fallback_selected_at": selected_at,
            "review_status": "FALLBACK_SELECTED",
            "approval_status": "FALLBACK_SELECTED",
        }
    )
    await crud.upsert_product_truth_lock(
        product_id,
        review_status="REJECTED",
        failure_state="FALLBACK_SELECTED",
        identity_lock=0,
        geometry_lock=0,
        label_lock=0,
        logo_lock=0,
        colour_lock=0,
        scale_lock=0,
        provenance_json=json.dumps(provenance, sort_keys=True),
    )
    return {
        "product_id": product_id,
        "review_status": "FALLBACK_SELECTED",
        "exact_allowed": False,
        "active_selection": ACTIVE_SAME_PRODUCT_FALLBACK,
        "provenance": provenance,
    }
