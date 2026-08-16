"""Provider-free product visual onboarding and readiness authority.

This module deliberately separates three states that were previously easy to
conflate:

* ``VISUAL_GROUNDING_READY`` means the resolver found a same-product source;
* ``CUTOUT_PENDING_REVIEW`` means deterministic preparation produced a review
  candidate; and
* ``EXACT_COMMERCE_CUTOUT_READY`` means the persisted Product Truth lock is
  approved and byte-valid.

Generation and upload functions in this module never call a provider or approve
a truth lock.  The page-level save orchestration delegates any explicit
approval to the existing Product Truth authority; the resolver, reference-pack
builder, and truth-lock service remain the source authorities for their
respective evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
import uuid

from PIL import Image

from agent import config
from agent.config import BASE_DIR
from agent.db import crud
from agent.db.schema import atomic
from agent.models.product_truth_lock import (
    ProductTruthLockApprovalRequest,
    ProductTruthLockOnboardingRequest,
)
from agent.services.product_intelligence import is_test_product
from agent.services.product_lifecycle_service import is_archived
from agent.services.product_lock_builder import resolve_schema_entry
from agent.services.product_visual_grounding_resolver import (
    ProductVisualReferenceRequiredError,
    durable_schema_canonical_source_path,
    resolve_governed_original_product_source,
    resolve_product_reference_image,
)
from agent.services.product_visual_canvas_service import (
    STANDARD_VISUAL_CANVAS_HEIGHT,
    STANDARD_VISUAL_CANVAS_LABEL,
    STANDARD_VISUAL_CANVAS_REQUIREMENT,
    STANDARD_VISUAL_CANVAS_WIDTH,
)
from agent.services.product_truth_lock_service import (
    AUTO_GENERATED,
    USER_UPLOAD,
    ProductTruthLockError,
    create_pending_product_truth_lock,
    approve_product_truth_lock,
    register_product_truth_cutout_media,
    resolve_approved_product_truth_lock,
    reject_product_truth_lock,
    select_product_truth_fallback,
)

logger = logging.getLogger(__name__)

NOT_PREPARED = "NOT_PREPARED"
PREPARING = "PREPARING"
PENDING_REVIEW = "PENDING_REVIEW"
APPROVED = "APPROVED"
PREPARATION_FAILED = "PREPARATION_FAILED"
BLOCKED = "BLOCKED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"

PREPARATION_STATES = {
    NOT_PREPARED,
    PREPARING,
    PENDING_REVIEW,
    APPROVED,
    PREPARATION_FAILED,
    BLOCKED,
    REJECTED,
}

_SOURCE_REAUTH_MAX_BYTES = 10 * 1024 * 1024
_SOURCE_REAUTH_MEDIA_PREFIX = "visual-source-reauthorization:"
_SOURCE_REAUTH_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}

_COMPOSITOR_POOL: ProcessPoolExecutor | None = None
_BULK_CANCEL_REQUESTS: set[str] = set()


def _compositor_worker_count() -> int:
    """Bound CPU parallelism; SQLite writes remain serialized by the DB lock."""
    try:
        requested = int(os.getenv("BOSMAX_CUTOUT_COMPOSITOR_WORKERS", "2"))
    except ValueError:
        requested = 2
    return max(1, min(requested, 4))


def _get_compositor_pool() -> ProcessPoolExecutor:
    global _COMPOSITOR_POOL
    if _COMPOSITOR_POOL is None:
        _COMPOSITOR_POOL = ProcessPoolExecutor(max_workers=_compositor_worker_count())
    return _COMPOSITOR_POOL


def _build_cutout_bytes_timed(
    source_path: Path,
) -> tuple[bytes, dict[str, float], str, float]:
    started = time.perf_counter()
    raw, bounds, cutout_sha = _build_cutout_bytes(source_path)
    return raw, bounds, cutout_sha, time.perf_counter() - started


async def _run_cutout_compositor(
    source_path: Path,
) -> tuple[bytes, dict[str, float], str, float]:
    """Run the CPU-bound compositor off the event loop with bounded processes.

    Unit tests replace ``_build_cutout_bytes`` with local doubles. Those doubles
    stay on a thread so the test seam remains patchable; production uses the
    process pool because the compositor contains Python-level pixel loops and
    therefore does not scale through GIL-bound worker threads.
    """
    started = time.perf_counter()
    import __main__

    main_file = getattr(__main__, "__file__", None)
    spawned_from_stdin = not main_file or str(main_file).startswith("<")
    if (
        getattr(_build_cutout_bytes, "__module__", None) != __name__
        or spawned_from_stdin
    ):
        raw, bounds, cutout_sha = await asyncio.to_thread(
            _build_cutout_bytes, source_path
        )
        return raw, bounds, cutout_sha, time.perf_counter() - started

    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _get_compositor_pool(), _build_cutout_bytes_timed, source_path
        )
    except BrokenProcessPool:
        # A worker crash must not poison future pilot/full-run work. Recreate the
        # bounded pool once and retry this product in a thread as a fail-safe.
        global _COMPOSITOR_POOL
        if _COMPOSITOR_POOL is not None:
            _COMPOSITOR_POOL.shutdown(wait=False, cancel_futures=True)
            _COMPOSITOR_POOL = None
        raw, bounds, cutout_sha = await asyncio.to_thread(
            _build_cutout_bytes, source_path
        )
        return raw, bounds, cutout_sha, time.perf_counter() - started


def _with_performance(
    payload: dict[str, Any],
    *,
    started: float,
    compositor_seconds: float = 0.0,
    db_write_seconds: float = 0.0,
) -> dict[str, Any]:
    payload["performance"] = {
        "wall_seconds": round(time.perf_counter() - started, 4),
        "compositor_seconds": round(compositor_seconds, 4),
        "db_write_seconds": round(db_write_seconds, 4),
    }
    return payload


class ProductVisualOnboardingError(ValueError):
    """Stable, provider-free onboarding failure."""

    def __init__(self, code: str, message: str = "", *, status_code: int = 409) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(value: Any) -> Path | None:
    if not value:
        return None
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None


def _preview_servable_path(value: Any) -> Path | None:
    """Return a readable local path that the preview endpoint is allowed to serve.

    Readiness and preview must share this gate. A file that exists but sits
    outside BASE_DIR media storage is NOT "available" for internal preview URLs.
    """
    candidate = _path(value)
    if candidate is None:
        return None
    try:
        candidate.resolve().relative_to(BASE_DIR.resolve())
    except ValueError:
        return None
    return candidate.resolve()


def _safe_source_filename(filename: str | None) -> str:
    raw = str(filename or "").replace("\\", "/")
    safe = Path(raw).name.strip()
    return (safe if safe and safe not in {".", ".."} else "product-source-image")[:255]


def _safe_path_segment(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return safe[:120] or "product"


def _source_media_reference(
    *,
    product_id: str,
    media_id: str,
    path: Path,
    filename: str,
    mime_type: str | None,
) -> Any:
    """Build the server-owned reference used by explicit source reauthorization."""
    try:
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.load()
        metadata = _SOURCE_REAUTH_FORMATS.get(image_format)
        if metadata is None:
            raise ValueError(f"unsupported image format: {image_format or 'unknown'}")
        detected_mime = metadata[1]
        sha256 = _sha256_bytes(path.read_bytes())
    except Exception as exc:  # noqa: BLE001 - replacement validation is fail-closed
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            f"Uploaded replacement source is not a valid image: {exc}",
            status_code=422,
        ) from exc
    return SimpleNamespace(
        source_type="PRODUCT_SOURCE_MEDIA_REAUTHORIZATION",
        media_id=media_id,
        local_path=str(path),
        image_url=None,
        mime_type=str(mime_type or detected_mime),
        sha256=sha256,
        width=int(width),
        height=int(height),
        provenance="SMART_REGISTRATION_SOURCE_REAUTHORIZATION_UPLOAD",
        validation_status="VALIDATED",
        product_id=product_id,
        filename=filename,
    )


async def upload_original_source_candidate(
    product_id: str,
    *,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
    uploaded_by: str,
) -> dict[str, Any]:
    """Persist an immutable, product-bound source candidate for explicit reauthorization.

    This is deliberately separate from Product Truth lock mutation. Uploading a
    candidate never changes the active source or attempts to archive/supersede a
    lock; the existing ``ORIGINAL_SOURCE_REAUTHORIZE`` save path performs that
    explicit, SHA-CAS-protected decision later.
    """
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError(
            "PRODUCT_NOT_FOUND",
            f"Product {product_id} was not found.",
            status_code=404,
        )
    blocked = await _blocked_reason(product)
    if blocked:
        raise ProductVisualOnboardingError(
            blocked,
            "Original Source replacement is blocked for this product cohort.",
            status_code=409,
        )
    if not raw_bytes:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Uploaded replacement source is empty.",
            status_code=422,
        )
    if len(raw_bytes) > _SOURCE_REAUTH_MAX_BYTES:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Uploaded replacement source exceeds the 10 MB limit.",
            status_code=422,
        )

    safe_filename = _safe_source_filename(filename)
    media_id = uuid.uuid4().hex
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.load()
        format_meta = _SOURCE_REAUTH_FORMATS.get(image_format)
        if format_meta is None:
            raise ValueError(f"unsupported image format: {image_format or 'unknown'}")
    except Exception as exc:  # noqa: BLE001 - upload validation is fail-closed
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            f"Uploaded replacement source is not a valid image: {exc}",
            status_code=422,
        ) from exc

    target = (
        BASE_DIR
        / "data"
        / "product_registration"
        / "source_reauthorization"
        / _safe_path_segment(str(product_id))
        / f"{media_id}.{format_meta[0]}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw_bytes)
    relative_path = str(target.resolve().relative_to(BASE_DIR.resolve())).replace("\\", "/")
    try:
        rows = await crud.list_product_source_media(product_id=product_id)
        ordinal = max((int(row.get("ordinal") or 0) for row in rows), default=-1) + 1
        row = await crud.create_product_source_media(
            f"{_SOURCE_REAUTH_MEDIA_PREFIX}{product_id}",
            "image",
            media_id=media_id,
            product_id=product_id,
            local_path=relative_path,
            filename=safe_filename,
            mime=format_meta[1],
            bytes=len(raw_bytes),
            width=int(width),
            height=int(height),
            ordinal=ordinal,
            status="PENDING_REAUTHORIZATION",
        )
    except Exception as exc:  # noqa: BLE001 - do not leave an unregistered candidate
        target.unlink(missing_ok=True)
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_UPLOAD_FAILED",
            f"Replacement source could not be registered: {exc}",
            status_code=500,
        ) from exc

    sha256 = _sha256_bytes(raw_bytes)
    return {
        "product_id": str(product_id),
        "media_id": media_id,
        "sha256": sha256,
        "filename": safe_filename,
        "mime": format_meta[1],
        "bytes": len(raw_bytes),
        "width": int(width),
        "height": int(height),
        "status": str((row or {}).get("status") or "PENDING_REAUTHORIZATION"),
        "uploaded_by": str(uploaded_by or "operator").strip() or "operator",
        "created_without_credit": True,
    }


async def _resolve_uploaded_source_candidate(
    product_id: str,
    media_id: str,
) -> Any:
    row = await crud.get_product_source_media(media_id)
    if not row or str(row.get("product_id") or "") != str(product_id):
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_PRODUCT_MISMATCH",
            "Governed replacement media belongs to a different product or is unavailable.",
            status_code=409,
        )
    if str(row.get("kind") or "").lower() != "image":
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Governed replacement media must be an image.",
            status_code=422,
        )
    status = str(row.get("status") or "").upper()
    if status not in {"PENDING_REAUTHORIZATION", "STORED"}:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Governed replacement media is not available for reauthorization.",
            status_code=422,
        )
    path = _preview_servable_path(row.get("local_path"))
    if path is None:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Governed replacement media bytes are unavailable under BASE_DIR.",
            status_code=422,
        )
    return _source_media_reference(
        product_id=product_id,
        media_id=str(media_id),
        path=path,
        filename=str(row.get("filename") or path.name),
        mime_type=str(row.get("mime") or "") or None,
    )


def _candidate_cutout_path(
    lock: dict[str, Any] | None,
    history: list[dict[str, Any]] | None,
    source_kind: str,
) -> Path | None:
    """Resolve the newest byte-backed cutout path for AUTO/MANUAL without status inference."""
    history = history or []
    if lock and _candidate_source_kind(lock) == source_kind:
        path = _preview_servable_path(lock.get("canonical_cutout_path"))
        if path is not None:
            return path
    for item in history:
        if str(item.get("source_kind") or "").upper() != source_kind:
            continue
        path = _preview_servable_path(item.get("canonical_cutout_path"))
        if path is not None:
            return path
    return None


async def _enrich_product_with_source_media(product: dict[str, Any]) -> dict[str, Any]:
    """Attach the first readable same-product source-media image when the row lacks one.

    Read-only: never writes DB rows or downloads remote URLs.
    """
    product_id = str(product.get("id") or product.get("product_id") or "").strip()
    if not product_id:
        return product
    if _preview_servable_path(product.get("local_image_path")) is not None:
        return product
    try:
        media_rows = await crud.list_product_source_media(product_id=product_id)
    except Exception:  # noqa: BLE001 - readiness must stay fail-closed and read-only
        return product
    for media in media_rows:
        if str(media.get("kind") or "").lower() != "image":
            continue
        media_id = str(media.get("media_id") or "").strip()
        draft_id = str(media.get("draft_id") or "")
        # A source reauthorization upload is an explicit candidate, not an
        # implicit replacement. It becomes readable by the normal resolver only
        # after the reauthorization CAS makes its media id current on the product.
        if draft_id.startswith(_SOURCE_REAUTH_MEDIA_PREFIX) and media_id != str(product.get("media_id") or "").strip():
            continue
        path = _preview_servable_path(media.get("local_path"))
        if path is None:
            continue
        enriched = dict(product)
        if media_id:
            enriched["media_id"] = media_id
        if not str(enriched.get("local_image_path") or "").strip():
            enriched["local_image_path"] = str(path)
        return enriched
    return product



def _governed_original_path_candidates(
    product: dict[str, Any],
    *,
    pack: dict[str, Any] | None = None,
) -> list[Any]:
    """Candidate original-source paths that may be preview-servable under BASE_DIR."""
    values: list[Any] = []
    values.append(product.get("local_image_path"))
    try:
        entry = resolve_schema_entry(product) or {}
        key = str(entry.get("product_id") or entry.get("schema_key") or "").strip()
        if key:
            values.append(durable_schema_canonical_source_path(key))
        photo = entry.get("canonical_product_photo") if isinstance(entry.get("canonical_product_photo"), dict) else {}
        values.append(entry.get("canonical_source_path"))
        values.append((photo or {}).get("source_path"))
    except Exception:  # noqa: BLE001
        pass
    pack_path = _reference_pack_file(pack)
    if pack_path is not None:
        values.append(str(pack_path))
    return values


def _truth_lock_source_reference(lock: dict[str, Any] | None, product: dict[str, Any]) -> Any | None:
    """Resolve the active same-product source directly from its persisted lock."""
    if not lock:
        return None
    active_selection = str(_provenance(lock).get("active_selection") or "").upper()
    if active_selection != "SAME_PRODUCT_TRUSTED_SOURCE":
        return None
    path = _preview_servable_path(lock.get("canonical_source_path"))
    if path is None:
        return None
    expected_sha = str(lock.get("canonical_sha256") or "").strip().lower()
    try:
        with Image.open(path) as image:
            image_format = str(image.format or "").upper()
            width, height = image.size
            image.load()
        actual_sha = _sha256_bytes(path.read_bytes())
    except Exception:  # noqa: BLE001 - readiness remains fail-closed
        return None
    if not expected_sha or actual_sha != expected_sha:
        return None
    mime_type = _SOURCE_REAUTH_FORMATS.get(image_format, ("", "image/octet-stream"))[1]
    return SimpleNamespace(
        source_type="PRODUCT_TRUTH_LOCK_SOURCE",
        media_id=lock.get("canonical_media_id"),
        local_path=str(path),
        image_url=product.get("image_url"),
        mime_type=mime_type,
        sha256=actual_sha,
        width=int(width),
        height=int(height),
        provenance="PRODUCT_VISUAL_TRUTH_LOCK_SOURCE",
        validation_status="VALIDATED",
    )


async def _resolve_trusted_original_reference(
    product: dict[str, Any],
    *,
    pack: dict[str, Any] | None = None,
    lock: dict[str, Any] | None = None,
) -> tuple[Any | None, bool, str | None]:
    """Single authority for byte-backed original source used by readiness AND preview.

    Returns (reference, source_available, source_error_code).
    source_available is True only when the resolved local path is preview-servable.
    GET/read remains side-effect free regarding DB writes; remote URL materialization
    is avoided by only invoking the resolver when a local/cheap source signal exists
    or product_source_media already holds a servable image.
    """
    product_id = str(product.get("id") or product.get("product_id") or "").strip()
    if pack is None and product_id:
        try:
            pack = await crud.get_product_reference_pack(product_id)
        except Exception:  # noqa: BLE001
            pack = None
    if lock is None and product_id:
        try:
            lock = await crud.get_product_truth_lock(product_id)
        except Exception:  # noqa: BLE001
            lock = None

    locked_reference = _truth_lock_source_reference(lock, product)
    if locked_reference is not None:
        return locked_reference, True, None

    resolver_product = await _enrich_product_with_source_media(product)
    # Match prior readiness gates: local file / schema / pack / approved lock / PSM bytes.
    # Bare remote image_url is never a resolve trigger (prevents GET-time download).
    has_local_signal = bool(
        _preview_servable_path(resolver_product.get("local_image_path"))
        or _reference_file(resolver_product)
        or _reference_pack_file(pack)
        or _truth_row_approved(lock)
    )
    if not has_local_signal:
        return None, False, None

    try:
        reference = await _resolve_source(resolver_product)
    except ProductVisualOnboardingError as exc:
        return None, False, exc.code
    servable = _preview_servable_path(getattr(reference, "local_path", None))
    if servable is None:
        # Resolver may return an external authoring path (schema Priority-0) while
        # a governed BASE_DIR twin already exists (durable exact-product copy,
        # product row local cache, or PSM). Remap by SHA when possible; never
        # expand the serve allowlist to arbitrary filesystem paths.
        expected_sha = str(getattr(reference, "sha256", "") or "").strip().lower()
        for candidate in _governed_original_path_candidates(resolver_product, pack=pack):
            path = _preview_servable_path(candidate)
            if path is None:
                continue
            if expected_sha:
                try:
                    if _sha256_bytes(path.read_bytes()) != expected_sha:
                        continue
                except OSError:
                    continue
            servable = path
            break
    if servable is None:
        return None, False, None
    try:
        object.__setattr__(reference, "local_path", str(servable))
    except Exception:  # noqa: BLE001
        if hasattr(reference, "__dict__"):
            reference.__dict__["local_path"] = str(servable)
    return reference, True, None


def _truth_row_approved(lock: dict[str, Any] | None) -> bool:
    if not lock or str(lock.get("review_status") or "").upper() != APPROVED:
        return False
    provenance = _parse_json(lock.get("provenance_json"), {})
    return str(provenance.get("active_selection") or "").upper() not in {
        "SAME_PRODUCT_TRUSTED_SOURCE",
        "FALLBACK",
    }


def _purge_reason(product: dict[str, Any]) -> str | None:
    reason = str(product.get("archived_reason") or "").upper()
    if reason.startswith("DUPLICATE_MERGED_TO_CANONICAL"):
        return "MERGED_ALIAS"
    return None


async def _blocked_reason(product: dict[str, Any]) -> str | None:
    product_id = str(product.get("id") or "")
    if not product_id:
        return "PRODUCT_ID_MISSING"
    if await crud.is_product_catalog_alias_tombstoned(product_id):
        return "PURGED_ALIAS"
    if is_archived(product):
        return "ARCHIVED_PRODUCT"
    if _purge_reason(product):
        return _purge_reason(product)
    if is_test_product(product):
        return "TEST_FIXTURE"
    return None


async def _get_canva_workflow_row(product_id: str) -> dict[str, Any] | None:
    """Read the additive Canva ledger without breaking legacy DB readers."""
    try:
        return await crud.get_canva_cutout_workflow(product_id)
    except Exception as exc:  # noqa: BLE001 - legacy runtime compatibility
        if "no such table" in str(exc).lower():
            return None
        raise


def _canva_table_missing(exc: Exception) -> bool:
    return "no such table" in str(exc).lower()


async def _list_canva_workflow_rows(product_ids: list[str]) -> dict[str, dict[str, Any]]:
    try:
        return await crud.list_canva_cutout_workflows(product_ids)
    except Exception as exc:  # noqa: BLE001 - legacy runtime compatibility
        if "no such table" in str(exc).lower():
            return {}
        raise


def _reference_file(product: dict[str, Any]) -> Path | None:
    """Cheap local source check used by list/preview; it never downloads URLs."""
    local = _path(product.get("local_image_path"))
    if local and _preview_servable_path(str(local)) is not None:
        return local
    if local:
        # exists outside governed root — keep as signal only when no governed twin
        pass
    try:
        entry = resolve_schema_entry(product) or {}
        key = str(entry.get("product_id") or entry.get("schema_key") or "").strip()
        if key:
            durable = _preview_servable_path(str(durable_schema_canonical_source_path(key)))
            if durable is not None:
                return durable
        schema_path = entry.get("canonical_source_path") or (
            (entry.get("canonical_product_photo") or {}) if isinstance(entry.get("canonical_product_photo"), dict) else {}
        ).get("source_path")
        governed_schema = _preview_servable_path(schema_path)
        if governed_schema is not None:
            return governed_schema
        # External schema authoring path may still be a local signal for has_local_signal.
        external = _path(schema_path)
        if external is not None:
            return external
    except Exception:  # noqa: BLE001
        pass
    if local:
        return local
    return None



def _reference_pack_file(pack: dict[str, Any] | None) -> Path | None:
    """Return only a byte-backed PRODUCT_CANONICAL pack source."""
    references = _parse_json((pack or {}).get("references_json"), [])
    for reference in references if isinstance(references, list) else []:
        if isinstance(reference, dict) and str(reference.get("role") or "").upper() == "PRODUCT_CANONICAL":
            return _path(reference.get("local_file_path"))
    return None


def _http_source_url(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if candidate.lower().startswith(("http://", "https://")):
        return candidate
    return None


def _display_image_url(product: dict[str, Any]) -> tuple[str, str] | None:
    """Return the same browser-visible image precedence used by Product Detail.

    ``get_product_visual_readiness`` is intentionally read-only and must not
    materialize a URL-only source.  It still needs to expose the image that the
    product header already displays, otherwise the Visual/Canva page presents
    a false ``Not available`` state and disables the manual lane.  Only remote
    URLs are considered here; byte-backed/local sources continue through the
    trusted preview endpoint above.
    """
    candidates: list[tuple[Any, str]] = [
        (product.get("image_url"), "PRODUCT_ROW_IMAGE_URL"),
        (product.get("rendered_img_src"), "PRODUCT_RENDERED_IMAGE_URL"),
        (product.get("image_analysis_image_url"), "PRODUCT_IMAGE_ANALYSIS_URL"),
    ]
    analysis = product.get("image_analysis")
    if isinstance(analysis, dict):
        candidates.append((analysis.get("image_url"), "PRODUCT_IMAGE_ANALYSIS_URL"))
    candidates.append((product.get("source_url"), "PRODUCT_ROW_SOURCE_URL"))
    for value, source in candidates:
        url = _http_source_url(value)
        if url:
            return url, source
    return None


def _original_display_source(
    product: dict[str, Any],
    *,
    source_available: bool,
) -> dict[str, str | None]:
    """Resolve the image the operator should see without changing trust state.

    A byte-backed source is served through the governed preview endpoint.  If
    trust has not been established yet, the product row URL remains a display
    source only; it never upgrades ``canonical_media_status``.
    """
    product_id = str(product.get("id") or product.get("product_id") or "")
    if source_available and product_id:
        return {
            "url": f"/api/product-visual-onboarding/{product_id}/cutout/preview/original",
            "source": "TRUSTED_SAME_PRODUCT_SOURCE",
            "trust_status": "TRUSTED",
        }
    display = _display_image_url(product)
    if display:
        url, source = display
        return {"url": url, "source": source, "trust_status": "DISPLAY_ONLY"}
    return {"url": None, "source": "UNAVAILABLE", "trust_status": "UNAVAILABLE"}


def _parse_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _source_label(reference: Any | None, *, approved: bool) -> str:
    if approved:
        return "APPROVED_PRODUCT_TRUTH_CUTOUT"
    if reference is None:
        return "SOURCE_NOT_RESOLVED"
    source_type = str(getattr(reference, "source_type", "") or "")
    if source_type:
        return source_type
    return "SAME_PRODUCT_CANONICAL_REFERENCE"


def _provenance(row: dict[str, Any] | None) -> dict[str, Any]:
    return _parse_json((row or {}).get("provenance_json"), {})


def _candidate_source_kind(row: dict[str, Any] | None) -> str:
    provenance = _provenance(row)
    declared = str(provenance.get("source_kind") or "").upper()
    if declared in {AUTO_GENERATED, USER_UPLOAD}:
        return declared
    created_by = str(provenance.get("created_by") or "").lower()
    return AUTO_GENERATED if created_by.startswith("system:") else USER_UPLOAD


def _review_label(row: dict[str, Any] | None) -> str:
    if not row:
        return "NOT_CREATED"
    provenance = _provenance(row)
    if str(row.get("review_status") or "").upper() == "REJECTED":
        return str(provenance.get("review_status") or "REJECTED_BY_USER")
    return str(row.get("review_status") or "NOT_CREATED")


def _candidate_status(
    row: dict[str, Any] | None,
    history: list[dict[str, Any]],
    source_kind: str,
) -> str:
    if row and _candidate_source_kind(row) == source_kind:
        review = str(row.get("review_status") or "").upper()
        if review == "APPROVED" and _truth_row_approved(row):
            return APPROVED
        if review == "PENDING_REVIEW":
            return PENDING_REVIEW
        if review == "REJECTED":
            return REJECTED
    for item in history:
        if str(item.get("source_kind") or "").upper() != source_kind:
            continue
        review = str(item.get("review_status") or "").upper()
        if review == "APPROVED":
            return SUPERSEDED
        if review == "PENDING_REVIEW":
            return SUPERSEDED
        if review == "REJECTED":
            return REJECTED
    return "NOT_UPLOADED" if source_kind == USER_UPLOAD else NOT_PREPARED


def _prep_state(
    lock: dict[str, Any] | None,
    prep: dict[str, Any] | None,
) -> str:
    if _truth_row_approved(lock):
        return APPROVED
    review_status = str((lock or {}).get("review_status") or "").upper()
    if review_status == "PENDING_REVIEW":
        return PENDING_REVIEW
    if review_status == "REJECTED":
        return REJECTED
    state = str((prep or {}).get("status") or NOT_PREPARED).upper()
    return state if state in PREPARATION_STATES else NOT_PREPARED


def _candidate_actions(
    product: dict[str, Any],
    *,
    source_available: bool,
    display_source_available: bool,
    state: str,
    lock: dict[str, Any] | None,
    blocked_reason: str | None,
    canva_workflow: dict[str, Any] | None = None,
) -> dict[str, bool]:
    active = not blocked_reason
    pending = str((lock or {}).get("review_status") or "").upper() == PENDING_REVIEW
    approved = _truth_row_approved(lock)
    canva_stage = str((canva_workflow or {}).get("current_stage") or "NOT_STARTED").upper()
    return {
        # A display-only URL is a valid operator-visible input.  The write lane
        # resolves/materializes it lazily; the readiness GET remains read-only.
        "can_prepare_cutout": bool(active and (source_available or display_source_available) and not approved and not pending),
        "can_review_cutout": bool(active and pending),
        "can_approve_cutout": bool(active and pending),
        "can_rebuild_cutout": bool(active and (source_available or display_source_available) and not approved),
        "can_upload_manual_cutout": bool(active and (source_available or display_source_available)),
        "can_reject_cutout": bool(active and lock and str(lock.get("review_status") or "").upper() in {PENDING_REVIEW, APPROVED}),
        "can_use_original_fallback": bool(active and source_available),
        "can_start_canva_cutout": bool(active and source_available and canva_stage not in {"PENDING_HUMAN_REVIEW", "APPROVED"}),
        "can_open_source": bool(source_available or display_source_available),
        "can_view": True,
    }


def _current_system_visual(active_source: str, *, source_available: bool) -> dict[str, Any]:
    """The single visual BOSMAX is using RIGHT NOW, derived from backend authority.

    Exactly one card is 'current'. OFFICIAL = an approved canonical cutout;
    FALLBACK = the trusted original source is the reference while a cutout is
    still pending; BLOCKED/NOT_SELECTED otherwise.
    """
    mapping = {
        "APPROVED_AUTO_CANONICAL_CUTOUT": ("AUTO_CUTOUT", "Auto Cutout", "OFFICIAL"),
        "APPROVED_MANUAL_CANONICAL_CUTOUT": ("MANUAL_CUTOUT", "Manual / Canva Cutout", "OFFICIAL"),
        "SAME_PRODUCT_TRUSTED_SOURCE": ("ORIGINAL_SOURCE", "Original Source", "ORIGINAL_FALLBACK"),
    }
    if active_source in mapping:
        card, label, status = mapping[active_source]
    elif active_source == "BLOCKED" or not source_available:
        card, label, status = None, None, "BLOCKED"
    else:
        card, label, status = None, None, "NOT_SELECTED"
    return {"card": card, "label": label, "status": status}


def _readiness_payload(
    product: dict[str, Any],
    *,
    lock: dict[str, Any] | None,
    pack: dict[str, Any] | None,
    prep: dict[str, Any] | None,
    reference: Any | None,
    source_available: bool,
    source_error: str | None = None,
    blocked_reason: str | None = None,
    history: list[dict[str, Any]] | None = None,
    canva_workflow: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history = history or []
    state = _prep_state(lock, prep)
    approved = _truth_row_approved(lock)
    source_kind = _candidate_source_kind(lock) if lock else ""
    auto_status = _candidate_status(lock, history, AUTO_GENERATED)
    manual_status = _candidate_status(lock, history, USER_UPLOAD)
    if blocked_reason:
        grounding_status = "VISUAL_GROUNDING_BLOCKED"
        exact_status = "EXACT_COMMERCE_BLOCKED"
    elif approved:
        grounding_status = "VISUAL_GROUNDING_READY"
        exact_status = "EXACT_COMMERCE_CUTOUT_READY"
    elif source_available:
        grounding_status = "VISUAL_GROUNDING_READY_FALLBACK"
        exact_status = "CUTOUT_REQUIRED"
    else:
        grounding_status = "VISUAL_GROUNDING_BLOCKED"
        exact_status = "EXACT_COMMERCE_BLOCKED"

    active_source = "BLOCKED"
    if blocked_reason:
        active_source = "BLOCKED"
    elif approved and source_kind == USER_UPLOAD:
        active_source = "APPROVED_MANUAL_CANONICAL_CUTOUT"
    elif approved and source_kind == AUTO_GENERATED:
        active_source = "APPROVED_AUTO_CANONICAL_CUTOUT"
    elif source_available:
        active_source = "SAME_PRODUCT_TRUSTED_SOURCE"

    blockers: list[str] = []
    warnings: list[str] = []
    if blocked_reason:
        blockers.append(blocked_reason)
    if not source_available:
        blockers.append("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED")
    if source_error:
        warnings.append(source_error)
    if not approved:
        warnings.append("EXACT_COMMERCE_REQUIRES_EXPLICIT_HUMAN_APPROVAL")
    if state == PREPARATION_FAILED:
        warnings.append(str((prep or {}).get("failure_code") or "CUTOUT_PREPARATION_FAILED"))
    if state == REJECTED:
        warnings.append("REJECTED_BY_USER")

    display_source = _original_display_source(product, source_available=source_available)

    actions = _candidate_actions(
        product,
        source_available=source_available,
        display_source_available=bool(display_source["url"]),
        state=state,
        lock=lock,
        blocked_reason=blocked_reason,
        canva_workflow=canva_workflow,
    )
    canva_preflight = _parse_json((canva_workflow or {}).get("preflight_json"), {})
    canva_payload = {
        "workflow_id": (canva_workflow or {}).get("workflow_id"),
        "current_stage": str((canva_workflow or {}).get("current_stage") or "NOT_STARTED"),
        "canva_method": (canva_workflow or {}).get("canva_method") or "UNSELECTED",
        "design_id": (canva_workflow or {}).get("design_id"),
        "design_url": (canva_workflow or {}).get("design_url"),
        "attempt_count": int((canva_workflow or {}).get("attempt_count") or 0),
        "last_error_code": (canva_workflow or {}).get("last_error_code"),
        "last_error": (canva_workflow or {}).get("last_error"),
        "preflight": canva_preflight,
        "source_dimensions": {
            "width": STANDARD_VISUAL_CANVAS_WIDTH,
            "height": STANDARD_VISUAL_CANVAS_HEIGHT,
        },
        "output_dimensions": {
            "width": int((canva_workflow or {}).get("output_width") or 0) or None,
            "height": int((canva_workflow or {}).get("output_height") or 0) or None,
        },
        "output_sha256": (canva_workflow or {}).get("output_sha256"),
        "alpha_verified": bool((canva_workflow or {}).get("alpha_verified")),
        "human_review_status": (canva_workflow or {}).get("human_review_status") or "NOT_STARTED",
        "provenance_source": (canva_workflow or {}).get("provenance_source"),
    }
    return {
        "product_id": str(product.get("id") or ""),
        "visual_canvas_width": STANDARD_VISUAL_CANVAS_WIDTH,
        "visual_canvas_height": STANDARD_VISUAL_CANVAS_HEIGHT,
        "visual_canvas_label": STANDARD_VISUAL_CANVAS_LABEL,
        "visual_canvas_requirement": STANDARD_VISUAL_CANVAS_REQUIREMENT,
        "canonical_media_status": "AVAILABLE" if source_available else "MISSING",
        "canonical_source_media_id": (lock or {}).get("canonical_media_id"),
        "canonical_source_sha256": (lock or {}).get("canonical_sha256"),
        "original_source_reauthorization_required": _original_authority_requires_reauthorization(lock),
        "reference_pack_status": str((pack or {}).get("pack_status") or "NOT_PREPARED"),
        "visual_grounding_status": grounding_status,
        "visual_grounding_source": "BLOCKED" if blocked_reason else (active_source if approved else _source_label(reference, approved=False)),
        "cutout_status": state,
        "cutout_review_status": _review_label(lock),
        "exact_commerce_status": exact_status,
        "auto_cutout_status": auto_status,
        "manual_cutout_status": manual_status,
        "active_visual_source": active_source,
        "cutout_media_id": (lock or {}).get("canonical_cutout_media_id")
        or (prep or {}).get("cutout_media_id"),
        "cutout_preview_available": bool(
            _preview_servable_path((lock or {}).get("canonical_cutout_path"))
            or _candidate_cutout_path(lock, history, AUTO_GENERATED)
            or _candidate_cutout_path(lock, history, USER_UPLOAD)
        ),
        "attempt_count": int((prep or {}).get("attempt_count") or 0),
        "failure_code": (prep or {}).get("failure_code"),
        "failure_message": (prep or {}).get("failure_message"),
        "original_preview_url": (
            f"/api/product-visual-onboarding/{product.get('id')}/cutout/preview/original"
            if source_available else None
        ),
        "original_display_url": display_source["url"],
        "original_display_source": display_source["source"],
        "original_display_trust_status": display_source["trust_status"],
        "auto_input_preview_url": (
            display_source["url"]
            if auto_status in {NOT_PREPARED, "NOT_UPLOADED"} and display_source["url"]
            else None
        ),
        "auto_input_source": (
            "ORIGINAL_SOURCE_INPUT"
            if auto_status in {NOT_PREPARED, "NOT_UPLOADED"} and display_source["url"]
            else None
        ),
        "auto_input_trust_status": (
            display_source["trust_status"]
            if auto_status in {NOT_PREPARED, "NOT_UPLOADED"} and display_source["url"]
            else None
        ),
        # Preview URLs require resolvable bytes — candidate status alone is insufficient.
        "auto_cutout_preview_url": (
            f"/api/product-visual-onboarding/{product.get('id')}/cutout/preview/auto"
            if auto_status not in {NOT_PREPARED, "NOT_UPLOADED"}
            and _candidate_cutout_path(lock, history, AUTO_GENERATED) is not None
            else None
        ),
        "manual_cutout_preview_url": (
            f"/api/product-visual-onboarding/{product.get('id')}/cutout/preview/manual"
            if manual_status not in {NOT_PREPARED, "NOT_UPLOADED"}
            and _candidate_cutout_path(lock, history, USER_UPLOAD) is not None
            else None
        ),
        "active_cutout_preview_url": (
            f"/api/product-visual-onboarding/{product.get('id')}/cutout/preview/active"
            if lock and _preview_servable_path(lock.get("canonical_cutout_path")) is not None
            else None
        ),
        "cutout_history_count": len(history),
        # ── Product-aware isolation + operator target (preparation metadata) ──
        "file_quality_status": (prep or {}).get("file_quality_status"),
        "product_isolation_status": (prep or {}).get("product_isolation_status"),
        "target_selection_required": (prep or {}).get("product_isolation_status") == "TARGET_SELECTION_REQUIRED",
        "target_selection_available": bool(target),
        "target_region": (
            {
                "x": int(target["target_x"]), "y": int(target["target_y"]),
                "width": int(target["target_width"]), "height": int(target["target_height"]),
                "source_sha256": target.get("source_sha256"),
            }
            if target else None
        ),
        # ── Which visual BOSMAX uses RIGHT NOW (backend authority; no FE guess) ──
        "current_system_visual": _current_system_visual(active_source, source_available=source_available),
        "blockers": blockers,
        "warnings": warnings,
        "provider_operations": 0,
        "created_without_credit": True,
        "canva_cutout_workflow": canva_payload,
        "canva_cutout_stage": canva_payload["current_stage"],
        **actions,
    }


async def _resolve_source(product: dict[str, Any]) -> Any:
    try:
        return resolve_product_reference_image(product, prefer_approved_cutout=False)
    except ProductVisualReferenceRequiredError as exc:
        raise ProductVisualOnboardingError("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - resolver has stable fail-closed boundary
        raise ProductVisualOnboardingError("CANONICAL_PRODUCT_SOURCE_INVALID", str(exc)) from exc


async def _ensure_canonical_media(product: dict[str, Any], reference: Any) -> str:
    existing_media_id = str(getattr(reference, "media_id", None) or "").strip()
    if existing_media_id:
        return existing_media_id
    source_path = _path(getattr(reference, "local_path", None))
    if source_path is None:
        raise ProductVisualOnboardingError("CANONICAL_MEDIA_ID_REQUIRED", "Canonical source is not a local readable image.")
    product_id = str(product["id"])
    source_sha = str(getattr(reference, "sha256", "") or "")
    for row in await crud.list_product_source_media(product_id=product_id):
        if str(row.get("kind") or "") != "image":
            continue
        candidate = _path(row.get("local_path"))
        if candidate and _sha256_bytes(candidate.read_bytes()) == source_sha:
            media_id = str(row.get("media_id") or "").strip()
            if media_id:
                await crud.update_product(product_id, media_id=media_id)
                return media_id
    row = await crud.create_product_source_media(
        f"visual-source:{product_id}",
        "image",
        product_id=product_id,
        local_path=str(source_path),
        filename=source_path.name,
        mime=str(getattr(reference, "mime_type", None) or "image/jpeg"),
        bytes=source_path.stat().st_size,
        width=int(getattr(reference, "width", 0) or 0),
        height=int(getattr(reference, "height", 0) or 0),
        status="STORED",
    )
    media_id = str((row or {}).get("media_id") or "").strip()
    if not media_id:
        raise ProductVisualOnboardingError("CANONICAL_MEDIA_ID_REQUIRED", "Source media registry did not return a media ID.")
    await crud.update_product(product_id, media_id=media_id)
    return media_id


def _build_cutout_bytes(source_path: Path) -> tuple[bytes, dict[str, float], str]:
    from agent.services.exact_product_compositor_service import _build_canonical_cutout

    image = _build_canonical_cutout(source_path, preserve_canvas=True)
    try:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        bbox = alpha.getbbox()
        extrema = alpha.getextrema()
        if bbox is None or extrema[0] >= 255 or extrema[1] <= 0:
            raise ProductVisualOnboardingError("CANONICAL_CUTOUT_INVALID", "Deterministic cutout has no transparent background and visible geometry.")
        stream = io.BytesIO()
        rgba.save(stream, format="PNG")
        width, height = rgba.size
        allowed_bbox = {
            "x": max(0.0, min(1.0, bbox[0] / width)),
            "y": max(0.0, min(1.0, bbox[1] / height)),
            "w": max(0.0001, min(1.0, (bbox[2] - bbox[0]) / width)),
            "h": max(0.0001, min(1.0, (bbox[3] - bbox[1]) / height)),
        }
        anchor = {
            "x": max(0.0, min(1.0, (bbox[0] + bbox[2]) / (2 * width))),
            "y": max(0.0, min(1.0, (bbox[1] + bbox[3]) / (2 * height))),
        }
        return stream.getvalue(), {**allowed_bbox, **{f"anchor_{key}": value for key, value in anchor.items()}}, _sha256_bytes(stream.getvalue())
    finally:
        image.close()


def _build_local_cutout_bytes(
    source_path: Path, roi=None, roi_source_sha256: str | None = None,
) -> tuple[bytes, dict[str, float], str, str, str]:
    """Prepare AUTO cutout bytes via the local ONNX engine.

    Returns ``(bytes, bounds, sha, product_isolation_status, file_quality_status)``.
    When ``roi`` is given, inference is confined to the operator target region.
    Raises ``ProductVisualOnboardingError`` on failure; an invalid/stale ROI
    surfaces its own code so the caller does NOT fall back to a full-frame
    compositor (which would re-include the excluded objects). Local engine =
    no provider credit, no provider operation.
    """
    from agent.services import local_cutout_engine as engine

    result = engine.prepare(source_path, roi=roi, roi_source_sha256=roi_source_sha256)
    if not result.ok() or not result.output_bytes:
        code = result.failure_code or result.quality_status
        if code in {engine.ROI_INVALID, engine.ROI_TOO_SMALL, engine.ROI_SOURCE_CHANGED}:
            raise ProductVisualOnboardingError(code, f"Product target region rejected: {code}.")
        raise ProductVisualOnboardingError(
            "LOCAL_CUTOUT_ENGINE_UNAVAILABLE",
            f"Local cutout engine did not produce a valid cutout: {code}.",
        )
    rgba = Image.open(io.BytesIO(result.output_bytes)).convert("RGBA")
    try:
        alpha = rgba.getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            raise ProductVisualOnboardingError(
                "LOCAL_CUTOUT_ENGINE_UNAVAILABLE", "Local cutout has empty alpha bounding box."
            )
        width, height = rgba.size
        allowed_bbox = {
            "x": max(0.0, min(1.0, bbox[0] / width)),
            "y": max(0.0, min(1.0, bbox[1] / height)),
            "w": max(0.0001, min(1.0, (bbox[2] - bbox[0]) / width)),
            "h": max(0.0001, min(1.0, (bbox[3] - bbox[1]) / height)),
        }
        anchor = {
            "x": max(0.0, min(1.0, (bbox[0] + bbox[2]) / (2 * width))),
            "y": max(0.0, min(1.0, (bbox[1] + bbox[3]) / (2 * height))),
        }
        bounds = {**allowed_bbox, **{f"anchor_{key}": value for key, value in anchor.items()}}
        cutout_sha = result.output_sha256 or _sha256_bytes(result.output_bytes)
        return (
            result.output_bytes, bounds, cutout_sha,
            result.product_isolation_status, result.file_quality_status,
        )
    finally:
        rgba.close()


async def _run_auto_cutout(
    source_path: Path, roi=None, roi_source_sha256: str | None = None,
) -> tuple[bytes, dict[str, float], str, float, str, str, str]:
    """Dispatch AUTO cutout byte production and report which engine produced it.

    Policy (the ``LOCAL_CUTOUT_ENGINE_ENABLED`` flag IS the policy — two engines
    never run for one candidate):

    * Flag OFF  -> deterministic compositor only (byte-identical to prior behavior).
    * Flag ON   -> try the local BiRefNet engine in-thread (reusing its ONNX
      session); on ANY failure or not-ready, fall back to the deterministic
      compositor. Exactly one set of bytes is ever persisted.
    """
    from agent.services import local_cutout_engine as engine

    if config.LOCAL_CUTOUT_ENGINE_ENABLED:
        started = time.perf_counter()
        try:
            raw, bounds, cutout_sha, iso_status, file_quality = await asyncio.to_thread(
                _build_local_cutout_bytes, source_path, roi, roi_source_sha256
            )
            return (
                raw, bounds, cutout_sha, time.perf_counter() - started,
                "local-birefnet-onnx", iso_status, file_quality,
            )
        except ProductVisualOnboardingError as exc:
            # An invalid/stale operator target must NOT silently fall back to a
            # full-frame cutout that re-includes the excluded objects.
            if getattr(exc, "code", "") in {engine.ROI_INVALID, engine.ROI_TOO_SMALL, engine.ROI_SOURCE_CHANGED}:
                raise
            logger.warning("local cutout engine unavailable; falling back to compositor: %s", exc)
        except Exception as exc:  # not ready / inference error
            logger.warning("local cutout engine error; falling back to compositor: %s", exc)
    raw, bounds, cutout_sha, seconds = await _run_cutout_compositor(source_path)
    return raw, bounds, cutout_sha, seconds, "deterministic-compositor", "PRODUCT_ISOLATION_REVIEW_REQUIRED", "OK"


async def prepare_product_cutout(product_id: str, *, force: bool = False) -> dict[str, Any]:
    """Prepare one deterministic cutout candidate; never approve it."""
    started = time.perf_counter()
    compositor_seconds = 0.0
    db_write_seconds = 0.0

    async def timed_write(awaitable):
        nonlocal db_write_seconds
        write_started = time.perf_counter()
        result = await awaitable
        db_write_seconds += time.perf_counter() - write_started
        return result

    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.")

    lock = await crud.get_product_truth_lock(product_id)
    pack = await crud.get_product_reference_pack(product_id)
    prep = await crud.get_product_cutout_preparation(product_id)
    if _truth_row_approved(lock):
        row = await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=APPROVED,
            source_sha256=lock.get("canonical_sha256"),
            cutout_media_id=lock.get("canonical_cutout_media_id"),
            cutout_sha256=lock.get("canonical_cutout_sha256"),
            failure_code=None,
            failure_message=None,
        ))
        return _with_performance(_readiness_payload(
            product,
            lock=lock,
            pack=pack,
            prep=row or prep,
            reference=None,
            source_available=True,
        ), started=started, db_write_seconds=db_write_seconds)

    blocked_reason = await _blocked_reason(product)
    if blocked_reason:
        row = await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=BLOCKED,
            failure_code=blocked_reason,
            failure_message="Product is outside the canonical production preparation cohort.",
        ))
        return _with_performance(_readiness_payload(
            product,
            lock=lock,
            pack=pack,
            prep=row or prep,
            reference=None,
            source_available=False,
            source_error=blocked_reason,
            blocked_reason=blocked_reason,
        ), started=started, db_write_seconds=db_write_seconds)

    if str((lock or {}).get("review_status") or "").upper() == PENDING_REVIEW and not force:
        return _with_performance(_readiness_payload(
            product,
            lock=lock,
            pack=pack,
            prep=prep,
            reference=None,
            source_available=True,
        ), started=started, db_write_seconds=db_write_seconds)

    try:
        reference = await _resolve_source(product)
        source_path = _path(getattr(reference, "local_path", None))
        if source_path is None:
            raise ProductVisualOnboardingError("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", "Canonical source is not a readable local image.")
        source_sha = str(getattr(reference, "sha256", "") or "")
        # Operator-selected product target (ROI). Bound to the source SHA — a
        # changed source invalidates a stale target (fail-closed).
        target = await crud.get_product_cutout_target(product_id)
        roi = None
        roi_source_sha = None
        if target and str(target.get("source_sha256") or "") == source_sha:
            roi = (
                int(target["target_x"]), int(target["target_y"]),
                int(target["target_width"]), int(target["target_height"]),
            )
            roi_source_sha = source_sha
        elif target:
            await crud.delete_product_cutout_target(product_id)
            target = None
        attempt_count = int((prep or {}).get("attempt_count") or 0) + 1
        await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=PREPARING,
            source_sha256=source_sha,
            attempt_count=attempt_count,
            last_started_at=_now(),
            failure_code=None,
            failure_message=None,
        ))
        media_sync_started = time.perf_counter()
        canonical_media_id = await _ensure_canonical_media(product, reference)
        db_write_seconds += time.perf_counter() - media_sync_started
        compositor_started = time.perf_counter()
        try:
            raw_cutout, bounds, cutout_sha, compositor_seconds, cutout_engine, isolation_status, file_quality_status = await _run_auto_cutout(
                source_path, roi=roi, roi_source_sha256=roi_source_sha
            )
        except Exception:
            # Failed compositor calls still contribute to the pilot/full-run
            # timing receipt; otherwise deterministic failures look free.
            compositor_seconds = time.perf_counter() - compositor_started
            raise
        from agent.services.product_truth_lock_service import (
            create_pending_product_truth_lock,
            register_product_truth_cutout_media,
        )

        # Provenance reflects HOW the bytes were prepared; WHO approves is
        # unchanged (still a PENDING_REVIEW candidate needing human approval).
        if cutout_engine == "local-birefnet-onnx":
            cutout_label = "local-cutout"
            cutout_created_by = "system:local-cutout-engine"
            cutout_note = (
                "Local BiRefNet cutout candidate; explicit human review and approval required."
            )
        else:
            cutout_label = "deterministic-cutout"
            cutout_created_by = "system:deterministic-product-cutout"
            cutout_note = (
                "Deterministic local candidate; explicit human review and approval required."
            )
        cutout_filename = f"{cutout_label}-{cutout_sha[:16]}.png"

        media_started = time.perf_counter()
        media = await register_product_truth_cutout_media(
            product_id,
            filename=cutout_filename,
            content_type="image/png",
            raw_bytes=raw_cutout,
            expected_dimensions=(
                int(getattr(reference, "width", 0) or 0),
                int(getattr(reference, "height", 0) or 0),
            ),
        )
        db_write_seconds += time.perf_counter() - media_started
        media_id = str(media.get("media_id") or "").strip()
        if not media_id:
            raise ProductVisualOnboardingError("CANONICAL_CUTOUT_MEDIA_REQUIRED", "Cutout registry did not return a media ID.")
        lock_started = time.perf_counter()
        await create_pending_product_truth_lock(
            product_id,
            ProductTruthLockOnboardingRequest(
                canonical_cutout_media_id=media_id,
                anchor_point={"x": float(bounds["anchor_x"]), "y": float(bounds["anchor_y"])},
                min_scale=0.5,
                max_scale=2.0,
                allowed_bbox={key: float(bounds[key]) for key in ("x", "y", "w", "h")},
                created_by=cutout_created_by,
                onboarding_note=cutout_note,
            ),
            source_kind=AUTO_GENERATED,
            original_filename=cutout_filename,
            uploaded_by=cutout_created_by,
            supersede_reason="REBUILT_AUTO_CANDIDATE",
        )
        db_write_seconds += time.perf_counter() - lock_started
        persisted_lock = await crud.get_product_truth_lock(product_id)
        row = await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=PENDING_REVIEW,
            source_sha256=source_sha,
            cutout_media_id=media_id,
            cutout_sha256=cutout_sha,
            attempt_count=attempt_count,
            last_finished_at=_now(),
            failure_code=None,
            failure_message=None,
            file_quality_status=file_quality_status,
            product_isolation_status=isolation_status,
        ))
        return _with_performance(_readiness_payload(
            product,
            lock=persisted_lock
            or {
                "review_status": PENDING_REVIEW,
                "canonical_cutout_media_id": media_id,
            },
            pack=pack,
            prep=row,
            reference=reference,
            source_available=True,
            target=target,
        ), started=started, compositor_seconds=compositor_seconds,
        db_write_seconds=db_write_seconds)
    except ProductVisualOnboardingError as exc:
        row = await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=BLOCKED if exc.code in {"TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", "CANONICAL_MEDIA_ID_REQUIRED"} else PREPARATION_FAILED,
            failure_code=exc.code,
            failure_message=exc.message,
            last_finished_at=_now(),
        ))
        return _with_performance(_readiness_payload(
            product,
            lock=await crud.get_product_truth_lock(product_id),
            pack=pack,
            prep=row,
            reference=None,
            source_available=exc.code not in {"TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", "CANONICAL_MEDIA_ID_REQUIRED"},
            source_error=exc.code,
        ), started=started, compositor_seconds=compositor_seconds,
        db_write_seconds=db_write_seconds)
    except Exception as exc:  # noqa: BLE001 - failure is receipt, never rollback product
        logger.exception("Product cutout preparation failed for %s", product_id)
        row = await timed_write(crud.upsert_product_cutout_preparation(
            product_id,
            status=PREPARATION_FAILED,
            failure_code="CUTOUT_PREPARATION_FAILED",
            failure_message=str(exc),
            last_finished_at=_now(),
        ))
        return _with_performance(_readiness_payload(
            product,
            lock=await crud.get_product_truth_lock(product_id),
            pack=pack,
            prep=row,
            reference=None,
            source_available=True,
            source_error="CUTOUT_PREPARATION_FAILED",
        ), started=started, compositor_seconds=compositor_seconds,
        db_write_seconds=db_write_seconds)


def _manual_cutout_bounds(raw_bytes: bytes, width: int, height: int) -> dict[str, float]:
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            rgba = image.convert("RGBA")
            try:
                bbox = rgba.getchannel("A").getbbox()
            finally:
                rgba.close()
    except Exception as exc:
        raise ProductVisualOnboardingError("CANONICAL_CUTOUT_INVALID", str(exc)) from exc
    if bbox is None:
        raise ProductVisualOnboardingError("CANONICAL_CUTOUT_ALPHA_REQUIRED", "Manual cutout has no visible product geometry.")
    left, top, right, bottom = bbox
    return {
        "x": left / width,
        "y": top / height,
        "w": (right - left) / width,
        "h": (bottom - top) / height,
        "anchor_x": (left + right) / (2 * width),
        "anchor_y": (top + bottom) / (2 * height),
    }


def _truth_error(exc: ProductTruthLockError) -> ProductVisualOnboardingError:
    return ProductVisualOnboardingError(exc.code, exc.message, status_code=exc.status_code)


async def upload_manual_product_cutout(
    product_id: str,
    *,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
    uploaded_by: str,
    provenance_source: str | None = None,
) -> dict[str, Any]:
    """Persist a user PNG as a pending first-class cutout candidate."""
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    blocked = await _blocked_reason(product)
    if blocked:
        raise ProductVisualOnboardingError(
            blocked,
            "Manual cutout upload is blocked for this product cohort.",
            status_code=409,
        )
    reference = await _resolve_source(product)
    source_width = int(getattr(reference, "width", 0) or 0)
    source_height = int(getattr(reference, "height", 0) or 0)
    if source_width <= 0 or source_height <= 0:
        raise ProductVisualOnboardingError("CANONICAL_PRODUCT_SOURCE_INVALID", "Canonical product source dimensions are unavailable.")
    # URL-only product images become governed same-product source media as
    # part of the manual lane. This is source preparation, not auto cutout.
    await _ensure_canonical_media(product, reference)
    try:
        media = await register_product_truth_cutout_media(
            product_id,
            filename=filename,
            content_type=content_type,
            raw_bytes=raw_bytes,
        )
        media_id = str(media.get("media_id") or "").strip()
        if not media_id:
            raise ProductVisualOnboardingError("CANONICAL_CUTOUT_MEDIA_REQUIRED", "Manual cutout media was not persisted.")
        bounds = _manual_cutout_bounds(
            raw_bytes,
            STANDARD_VISUAL_CANVAS_WIDTH,
            STANDARD_VISUAL_CANVAS_HEIGHT,
        )
        onboarding_kwargs: dict[str, Any] = {}
        if provenance_source:
            onboarding_kwargs["provenance_source"] = provenance_source
        await create_pending_product_truth_lock(
            product_id,
            ProductTruthLockOnboardingRequest(
                canonical_cutout_media_id=media_id,
                anchor_point={"x": bounds["anchor_x"], "y": bounds["anchor_y"]},
                min_scale=0.5,
                max_scale=2.0,
                allowed_bbox={key: bounds[key] for key in ("x", "y", "w", "h")},
                created_by=uploaded_by,
                onboarding_note="Operator-supplied manual cutout; explicit identity, label/logo, and geometry/scale approval required.",
            ),
            allow_approved_replacement=True,
            source_kind=USER_UPLOAD,
            original_filename=filename,
            uploaded_by=uploaded_by,
            uploaded_at=_now(),
            supersede_reason="MANUAL_CUTOUT_OVERRIDE",
            **onboarding_kwargs,
        )
    except ProductTruthLockError as exc:
        raise _truth_error(exc) from exc
    await crud.upsert_product_cutout_preparation(
        product_id,
        status=PENDING_REVIEW,
        source_sha256=str(getattr(reference, "sha256", "") or ""),
        cutout_media_id=media_id,
        cutout_sha256=_sha256_bytes(raw_bytes),
        failure_code=None,
        failure_message=None,
        last_finished_at=_now(),
    )
    if not provenance_source:
        from agent.services.canva_cutout_workflow_service import mark_canva_workflow_superseded_by_manual

        try:
            await mark_canva_workflow_superseded_by_manual(product_id)
        except Exception as exc:  # noqa: BLE001 - additive table may await runtime restart
            if not _canva_table_missing(exc):
                raise
    return await get_product_visual_readiness(product_id)


async def reject_product_cutout(
    product_id: str,
    *,
    rejected_by: str,
    reason: str,
) -> dict[str, Any]:
    try:
        await reject_product_truth_lock(product_id, rejected_by=rejected_by, reason=reason)
    except ProductTruthLockError as exc:
        raise _truth_error(exc) from exc
    await crud.upsert_product_cutout_preparation(
        product_id,
        status=PREPARATION_FAILED,
        failure_code="REJECTED_BY_USER",
        failure_message=str(reason).strip(),
        last_finished_at=_now(),
    )
    from agent.services.canva_cutout_workflow_service import mark_canva_workflow_rejected

    try:
        await mark_canva_workflow_rejected(product_id, str(reason).strip())
    except Exception as exc:  # noqa: BLE001 - additive table may await runtime restart
        if not _canva_table_missing(exc):
            raise
    return await get_product_visual_readiness(product_id)


async def use_original_product_fallback(
    product_id: str,
    *,
    selected_by: str,
    reason: str,
) -> dict[str, Any]:
    try:
        await select_product_truth_fallback(product_id, selected_by=selected_by, reason=reason)
    except ProductTruthLockError as exc:
        raise _truth_error(exc) from exc
    await crud.upsert_product_cutout_preparation(
        product_id,
        status=PREPARATION_FAILED,
        failure_code="FALLBACK_SELECTED",
        failure_message=str(reason).strip(),
        last_finished_at=_now(),
    )
    from agent.services.canva_cutout_workflow_service import mark_canva_workflow_fallback

    try:
        await mark_canva_workflow_fallback(product_id, str(reason).strip())
    except Exception as exc:  # noqa: BLE001 - additive table may await runtime restart
        if not _canva_table_missing(exc):
            raise
    return await get_product_visual_readiness(product_id)


def _original_authority_requires_reauthorization(lock: dict[str, Any] | None) -> bool:
    """Return True when an explicit Original Source lock no longer validates."""
    if not lock:
        return False
    active_selection = str(
        _parse_json(lock.get("provenance_json"), {}).get("active_selection") or ""
    ).upper()
    if active_selection != "SAME_PRODUCT_TRUSTED_SOURCE":
        return False
    source_path = _preview_servable_path(lock.get("canonical_source_path"))
    if source_path is None:
        return True
    try:
        return _sha256_bytes(source_path.read_bytes()) != str(lock.get("canonical_sha256") or "").lower()
    except OSError:
        return True


async def reauthorize_product_original_source(
    product_id: str,
    *,
    reviewed_by: str | None,
    review_note: str | None,
    confirm_identity: bool,
    confirm_label_logo: bool,
    confirm_geometry_scale: bool,
    confirm_product_isolation: bool,
    expected_previous_canonical_sha256: str | None,
    expected_replacement_sha256: str | None,
    replacement_media_id: str | None = None,
) -> dict[str, Any]:
    """Explicitly replace one product's stale Original Source authority.

    The replacement is resolved server-side and persisted through a narrow
    compare-and-swap writer. Existing cutout bytes and their audit metadata are
    retained; the operation only makes the governed Original Source active.
    """
    operator = str(reviewed_by or "").strip()
    note = str(review_note or "").strip()
    if not operator or not note:
        raise ProductVisualOnboardingError(
            "HUMAN_REVIEW_NOTE_REQUIRED",
            "Reviewer identity and reauthorization note are required.",
            status_code=409,
        )
    if not (
        confirm_identity
        and confirm_label_logo
        and confirm_geometry_scale
        and confirm_product_isolation
    ):
        raise ProductVisualOnboardingError(
            "HUMAN_REVIEW_CONFIRMATION_REQUIRED",
            "Identity, label/logo, geometry/scale, and product-isolation confirmations are all required.",
            status_code=409,
        )

    previous_sha = str(expected_previous_canonical_sha256 or "").strip().lower()
    replacement_sha = str(expected_replacement_sha256 or "").strip().lower()
    if len(previous_sha) != 64 or len(replacement_sha) != 64:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INPUT_REQUIRED",
            "Expected previous and replacement canonical SHA-256 values are required.",
            status_code=400,
        )

    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError(
            "PRODUCT_NOT_FOUND",
            f"Product {product_id} was not found.",
            status_code=404,
        )
    blocked = await _blocked_reason(product)
    if blocked:
        raise ProductVisualOnboardingError(
            blocked,
            "Visual source reauthorization is blocked for this product cohort.",
            status_code=409,
        )

    lock = await crud.get_product_truth_lock(product_id)
    if not lock:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_REQUIRED",
            "A persisted Original Source authority is required before reauthorization.",
            status_code=409,
        )
    current_sha = str(lock.get("canonical_sha256") or "").strip().lower()
    if current_sha != previous_sha:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_STALE",
            "The persisted Original Source SHA changed before reauthorization.",
            status_code=409,
        )

    selected_media_id = str(replacement_media_id or "").strip()
    if selected_media_id:
        # An uploaded candidate is selected by an exact product-bound media id;
        # the active approved cutout authority is still validated before this
        # source switch can proceed.
        if str(lock.get("review_status") or "").upper() == APPROVED and str(
            _provenance(lock).get("active_selection") or ""
        ).upper() != "SAME_PRODUCT_TRUSTED_SOURCE":
            try:
                resolve_approved_product_truth_lock(product_id)
            except ProductTruthLockError as exc:
                raise ProductVisualOnboardingError(
                    "OFFICIAL_PRODUCT_VISUAL_INVALID",
                    str(exc),
                    status_code=422,
                ) from exc
        reference = await _resolve_uploaded_source_candidate(product_id, selected_media_id)
    else:
        try:
            reference = resolve_governed_original_product_source(dict(product))
        except ProductVisualReferenceRequiredError as exc:
            message = str(exc)
            code = "OFFICIAL_PRODUCT_VISUAL_INVALID" if message.startswith("OFFICIAL_PRODUCT_VISUAL_INVALID") else "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID"
            raise ProductVisualOnboardingError(code, message, status_code=422) from exc

    source_path = _preview_servable_path(getattr(reference, "local_path", None))
    if source_path is None:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Governed replacement source is not a readable file under BASE_DIR.",
            status_code=422,
        )
    try:
        with Image.open(source_path) as image:
            source_width, source_height = image.size
        resolved_sha = _sha256_bytes(source_path.read_bytes())
    except Exception as exc:  # noqa: BLE001 - fail closed before persistence
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            f"Governed replacement source is not a valid image: {exc}",
            status_code=422,
        ) from exc
    if resolved_sha != str(getattr(reference, "sha256", "") or "").lower():
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_INVALID",
            "Server-resolved replacement source changed during validation.",
            status_code=422,
        )
    if resolved_sha != replacement_sha:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_STALE",
            "The governed replacement source SHA does not match the expected SHA.",
            status_code=409,
        )

    # A registered source-media id is accepted only when its product binding is
    # exact. Schema/creative-asset ids are already resolved by the server-side
    # product resolver and remain valid canonical media authorities.
    replacement_media_id = str(getattr(reference, "media_id", "") or "").strip()
    media_row = None
    if replacement_media_id:
        media_row = await crud.get_product_source_media(replacement_media_id)
        if media_row and str(media_row.get("product_id") or "") != str(product_id):
            raise ProductVisualOnboardingError(
                "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_PRODUCT_MISMATCH",
                "Governed replacement media belongs to a different product.",
                status_code=409,
            )
    pack = await crud.get_product_reference_pack(product_id)
    governed_paths = {
        candidate.resolve()
        for raw_candidate in _governed_original_path_candidates(product, pack=pack)
        if (candidate := _preview_servable_path(raw_candidate)) is not None
    }
    if source_path not in governed_paths and media_row is None:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_PRODUCT_MISMATCH",
            "Governed replacement source is not bound to the exact product.",
            status_code=409,
        )
    if not replacement_media_id:
        replacement_media_id = await _ensure_canonical_media(product, reference)
    if not replacement_media_id:
        raise ProductVisualOnboardingError(
            "CANONICAL_MEDIA_ID_REQUIRED",
            "Governed replacement source has no canonical media registry id.",
            status_code=422,
        )

    provenance = _parse_json(lock.get("provenance_json"), {})
    reauthorized_at = _now()
    provenance.update(
        {
            "previous_canonical_media_id": lock.get("canonical_media_id"),
            "previous_canonical_sha256": lock.get("canonical_sha256"),
            "previous_canonical_source_path": lock.get("canonical_source_path"),
            "previous_review_status": lock.get("review_status"),
            "previous_failure_state": lock.get("failure_state"),
            "replacement_canonical_media_id": replacement_media_id,
            "replacement_canonical_sha256": resolved_sha,
            "replacement_canonical_source_path": str(source_path),
            "reauthorized_by": operator,
            "reauthorization_note": note,
            "reauthorized_at": reauthorized_at,
            "reason": "LEGACY_CANONICAL_SOURCE_MISSING_OWNER_REAUTHORIZED",
            "active_selection": "SAME_PRODUCT_TRUSTED_SOURCE",
            "review_status": "FALLBACK_SELECTED",
            "approval_status": "FALLBACK_SELECTED",
            "human_review_required": False,
        }
    )

    async with atomic():
        persisted = await crud.cas_reauthorize_product_truth_lock_original_source(
            product_id,
            expected_previous_canonical_sha256=previous_sha,
            canonical_media_id=replacement_media_id,
            canonical_sha256=resolved_sha,
            source_width=source_width,
            source_height=source_height,
            canonical_source_path=str(source_path),
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
        if persisted is not None and selected_media_id:
            # These writes deliberately remain inside the same atomic boundary
            # as the SHA-CAS lock mutation. A failure in either promotion step
            # rolls the lock, product pointer, and candidate lifecycle back.
            updated_product = await crud.update_product(
                product_id,
                media_id=replacement_media_id,
                local_image_path=str(source_path),
                image_asset_status="READY",
                asset_status="DOWNLOADED",
            )
            if (
                not updated_product
                or str(updated_product.get("media_id") or "") != replacement_media_id
                or str(updated_product.get("local_image_path") or "") != str(source_path)
            ):
                raise ProductVisualOnboardingError(
                    "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_FAILED",
                    "The product source pointer could not be promoted atomically.",
                    status_code=500,
                )
            promoted_media = await crud.promote_product_source_media(
                product_id,
                replacement_media_id,
            )
            if not promoted_media or str(promoted_media.get("status") or "").upper() != "STORED":
                raise ProductVisualOnboardingError(
                    "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_FAILED",
                    "The replacement media lifecycle could not be promoted atomically.",
                    status_code=500,
                )
    if persisted is None:
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_STALE",
            "The persisted Original Source SHA changed before the CAS write.",
            status_code=409,
        )

    # Keep the existing preparation ledger honest without touching cutout
    # bytes, history, Copy V2, or any provider-facing state.
    await crud.upsert_product_cutout_preparation(
        product_id,
        status=PREPARATION_FAILED,
        source_sha256=resolved_sha,
        failure_code="FALLBACK_SELECTED",
        failure_message=note,
        last_finished_at=reauthorized_at,
    )
    readiness = await get_product_visual_readiness(product_id)
    readiness["original_source_reauthorization"] = {
        "product_id": product_id,
        "previous_canonical_media_id": lock.get("canonical_media_id"),
        "previous_canonical_sha256": lock.get("canonical_sha256"),
        "previous_canonical_source_path": lock.get("canonical_source_path"),
        "replacement_canonical_media_id": replacement_media_id,
        "replacement_canonical_sha256": resolved_sha,
        "replacement_canonical_source_path": str(source_path),
        "reauthorized_by": operator,
        "reauthorized_at": reauthorized_at,
        "reason": "LEGACY_CANONICAL_SOURCE_MISSING_OWNER_REAUTHORIZED",
    }
    return readiness


async def save_product_visual_setup(
    product_id: str,
    *,
    selected_visual: str,
    reviewed_by: str | None = None,
    review_note: str | None = None,
    confirm_identity: bool = False,
    confirm_label_logo: bool = False,
    confirm_geometry_scale: bool = False,
    confirm_product_isolation: bool = False,
    expected_previous_canonical_sha256: str | None = None,
    expected_replacement_sha256: str | None = None,
    replacement_media_id: str | None = None,
) -> dict[str, Any]:
    """Commit one page-level visual selection through existing authorities.

    This is intentionally an orchestration seam, not a second truth system:
    Original delegates to the existing trusted-source fallback authority and a
    pending Auto/Manual candidate delegates to the existing Product Truth
    approval authority.  Candidate generation/upload remains review-only.
    """
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    blocked = await _blocked_reason(product)
    if blocked:
        raise ProductVisualOnboardingError(
            blocked,
            "Visual selection is blocked for this product cohort.",
            status_code=409,
        )

    selection = str(selected_visual or "").strip().upper()
    if selection not in {"ORIGINAL", "ORIGINAL_SOURCE_REAUTHORIZE", "AUTO", "MANUAL"}:
        raise ProductVisualOnboardingError(
            "VISUAL_SELECTION_INVALID",
            "Choose Original, Original Source Reauthorization, Auto Cutout, or Manual / Canva.",
            status_code=400,
        )
    operator = str(reviewed_by or "").strip()
    note = str(review_note or "").strip()

    if selection == "ORIGINAL_SOURCE_REAUTHORIZE":
        return await reauthorize_product_original_source(
            product_id,
            reviewed_by=reviewed_by,
            review_note=review_note,
            confirm_identity=confirm_identity,
            confirm_label_logo=confirm_label_logo,
            confirm_geometry_scale=confirm_geometry_scale,
            confirm_product_isolation=confirm_product_isolation,
            expected_previous_canonical_sha256=expected_previous_canonical_sha256,
            expected_replacement_sha256=expected_replacement_sha256,
            replacement_media_id=replacement_media_id,
        )

    lock = await crud.get_product_truth_lock(product_id)
    if selection == "ORIGINAL" and _original_authority_requires_reauthorization(lock):
        raise ProductVisualOnboardingError(
            "PRODUCT_VISUAL_SOURCE_REAUTHORIZATION_REQUIRED",
            "The selected Original Source authority is missing or changed; explicit source reauthorization is required.",
            status_code=409,
        )
    readiness = await get_product_visual_readiness(product_id)
    current_card = str(((readiness.get("current_system_visual") or {}).get("card") or "")).upper()

    if selection == "ORIGINAL":
        if current_card == "ORIGINAL_SOURCE":
            return readiness
        if not operator or not note:
            raise ProductVisualOnboardingError(
                "HUMAN_REVIEW_NOTE_REQUIRED",
                "Operator identity and a reason are required to save Original Source.",
                status_code=409,
            )
        # The existing fallback authority expects a governed source.  Resolve
        # and register a display-only URL only on this explicit write action;
        # the page GET never performs this materialization.
        if not readiness.get("can_use_original_fallback"):
            reference = await _resolve_source(product)
            source_path = _path(getattr(reference, "local_path", None))
            if source_path is None:
                raise ProductVisualOnboardingError(
                    "TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED",
                    "The Original Source image could not be prepared as a trusted same-product source.",
                )
            await _ensure_canonical_media(product, reference)
        return await use_original_product_fallback(
            product_id,
            selected_by=operator,
            reason=note,
        )

    selected_status = (
        readiness.get("auto_cutout_status")
        if selection == "AUTO"
        else readiness.get("manual_cutout_status")
    )
    selected_card = "AUTO_CUTOUT" if selection == "AUTO" else "MANUAL_CUTOUT"
    if current_card == selected_card and str(selected_status or "").upper() == APPROVED:
        return readiness
    if str(selected_status or "").upper() != PENDING_REVIEW:
        raise ProductVisualOnboardingError(
            "VISUAL_CANDIDATE_NOT_AVAILABLE",
            "Generate or upload a candidate before saving this visual.",
            status_code=409,
        )
    if not operator or not note:
        raise ProductVisualOnboardingError(
            "HUMAN_REVIEW_NOTE_REQUIRED",
            "Reviewer identity and review note are required before approving a pending candidate.",
            status_code=409,
        )
    if not (
        confirm_identity
        and confirm_label_logo
        and confirm_geometry_scale
        and confirm_product_isolation
    ):
        raise ProductVisualOnboardingError(
            "HUMAN_REVIEW_CONFIRMATION_REQUIRED",
            "Identity, label/logo, geometry/scale, and product-isolation confirmations are all required.",
            status_code=409,
        )

    lock = await crud.get_product_truth_lock(product_id)
    expected_source_kind = AUTO_GENERATED if selection == "AUTO" else USER_UPLOAD
    if not lock or _candidate_source_kind(lock) != expected_source_kind:
        raise ProductVisualOnboardingError(
            "VISUAL_CANDIDATE_NOT_AVAILABLE",
            "The selected candidate is no longer the active review candidate. Refresh the page and try again.",
            status_code=409,
        )
    try:
        await approve_product_truth_lock(
            product_id,
            ProductTruthLockApprovalRequest(
                reviewed_by=operator,
                review_note=note,
                confirm_identity=confirm_identity,
                confirm_label_logo=confirm_label_logo,
                confirm_geometry_scale=confirm_geometry_scale,
                confirm_product_isolation=confirm_product_isolation,
            ),
        )
    except ProductTruthLockError as exc:
        raise _truth_error(exc) from exc
    # Keep the existing additive Canva workflow ledger in sync when the
    # approved candidate came through that assisted lane. Product Truth above
    # remains the sole approval authority; this is only the established mirror.
    from agent.services.canva_cutout_workflow_service import mark_canva_workflow_approved

    try:
        await mark_canva_workflow_approved(product_id)
    except Exception as exc:  # noqa: BLE001 - additive ledger may await runtime restart
        if not _canva_table_missing(exc):
            raise
        logger.warning("Canva workflow mirror deferred until schema initialization: %s", exc)
    return await get_product_visual_readiness(product_id)


async def get_product_cutout_history(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    current = await crud.get_product_truth_lock(product_id)
    history = await crud.list_product_truth_lock_history(product_id)
    current_candidate: dict[str, Any] | None = None
    if current:
        current_candidate = {
            "history_id": None,
            "source_kind": _candidate_source_kind(current),
            "review_status": _review_label(current),
            "active": _truth_row_approved(current),
            "preview_url": f"/api/product-visual-onboarding/{product_id}/cutout/preview/active",
            "provenance": _provenance(current),
        }
    history_candidates: list[dict[str, Any]] = []
    for item in history:
        history_candidates.append(
            {
                "history_id": item.get("history_id"),
                "source_kind": str(item.get("source_kind") or "UNKNOWN"),
                "review_status": str(item.get("review_status") or "UNKNOWN"),
                "active": False,
                "preview_url": f"/api/product-visual-onboarding/{product_id}/cutout/preview/history?history_id={item.get('history_id')}",
                "provenance": _parse_json(item.get("provenance_json"), {}),
            }
        )
    return {
        "product_id": product_id,
        "current": [current_candidate] if current_candidate else [],
        "history": history_candidates,
        "count": len(history),
    }


def _safe_preview_path(value: Any) -> Path:
    candidate = _path(value)
    if candidate is None:
        raise ProductVisualOnboardingError("CUTOUT_PREVIEW_NOT_FOUND", "Requested cutout preview is not available.", status_code=404)
    try:
        candidate.resolve().relative_to(BASE_DIR.resolve())
    except ValueError as exc:
        raise ProductVisualOnboardingError("CUTOUT_PREVIEW_FORBIDDEN", "Requested preview is outside server media storage.", status_code=403) from exc
    return candidate.resolve()


async def resolve_product_visual_preview(
    product_id: str,
    variant: str,
    *,
    history_id: str | None = None,
) -> Path:
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    normalized = str(variant or "").lower()
    lock = await crud.get_product_truth_lock(product_id)
    history = await crud.list_product_truth_lock_history(product_id)
    if normalized == "original":
        reference, available, _err = await _resolve_trusted_original_reference(product, lock=lock)
        if not available or reference is None:
            raise ProductVisualOnboardingError(
                "CUTOUT_PREVIEW_NOT_FOUND",
                "Requested cutout preview is not available.",
                status_code=404,
            )
        return _safe_preview_path(getattr(reference, "local_path", None))
    if normalized in {"active", "current"}:
        return _safe_preview_path((lock or {}).get("canonical_cutout_path"))
    if normalized == "history":
        item = next((row for row in history if str(row.get("history_id")) == str(history_id or "")), None)
        return _safe_preview_path((item or {}).get("canonical_cutout_path"))
    if normalized not in {"auto", "manual"}:
        raise ProductVisualOnboardingError("CUTOUT_PREVIEW_VARIANT_INVALID", "Preview variant is not supported.", status_code=400)
    source_kind = AUTO_GENERATED if normalized == "auto" else USER_UPLOAD
    candidate = _candidate_cutout_path(lock, history, source_kind)
    if candidate is None:
        raise ProductVisualOnboardingError("CUTOUT_PREVIEW_NOT_FOUND", "Requested cutout candidate is not available.", status_code=404)
    return candidate


async def ensure_product_visual_onboarding(
    product_id: str,
    *,
    reference_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registration seam: materialize readiness without auto-generating cutouts."""
    result = await get_product_visual_readiness(product_id)
    if reference_pack is not None:
        result["reference_pack"] = reference_pack
    result["provider_operations"] = 0
    result["created_without_credit"] = True
    return result


async def get_product_visual_readiness(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.")
    lock = await crud.get_product_truth_lock(product_id)
    history = await crud.list_product_truth_lock_history(product_id)
    pack = await crud.get_product_reference_pack(product_id)
    prep = await crud.get_product_cutout_preparation(product_id)
    target = await crud.get_product_cutout_target(product_id)
    canva_workflow = await _get_canva_workflow_row(product_id)
    # One canonical byte-backed resolution path for readiness + original preview.
    # Detail reads stay read-only: no DB writes and no silent DISPLAY_ONLY→TRUSTED upgrade.
    reference, source_available, source_error = await _resolve_trusted_original_reference(
        product,
        pack=pack,
        lock=lock,
    )
    blocked_reason = await _blocked_reason(product)
    return _readiness_payload(
        product,
        lock=lock,
        pack=pack,
        prep=prep,
        reference=reference,
        source_available=source_available,
        source_error=source_error,
        blocked_reason=blocked_reason,
        history=history,
        canva_workflow=canva_workflow,
        target=target,
    )


async def set_product_cutout_target(
    product_id: str, *, x: int, y: int, width: int, height: int, selected_by: str = "operator",
) -> dict[str, Any]:
    """Persist an operator-selected product ROI (validated against the CURRENT
    source geometry + SHA). Preparation provenance only — never approves truth."""
    from agent.services import local_cutout_engine as engine

    product = await crud.get_product(product_id)
    if not product:
        raise ProductVisualOnboardingError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.")
    reference = await _resolve_source(product)
    source_path = _path(getattr(reference, "local_path", None))
    if source_path is None:
        raise ProductVisualOnboardingError("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", "Canonical source is not a readable local image.")
    with Image.open(source_path) as img:
        sw, sh = img.size
    source_sha = str(getattr(reference, "sha256", "") or "") or _sha256_bytes(Path(source_path).read_bytes())
    roi_err = engine.validate_roi((x, y, width, height), (sw, sh))
    if roi_err:
        raise ProductVisualOnboardingError(roi_err, f"Product target region rejected: {roi_err}.")
    await crud.upsert_product_cutout_target(
        product_id, source_sha256=source_sha, source_width=sw, source_height=sh,
        target_x=int(x), target_y=int(y), target_width=int(width), target_height=int(height),
        selected_by=selected_by, selected_at=_now(),
    )
    return await get_product_visual_readiness(product_id)


async def clear_product_cutout_target(product_id: str) -> dict[str, Any]:
    """Clear the operator ROI target (reset)."""
    await crud.delete_product_cutout_target(product_id)
    return await get_product_visual_readiness(product_id)


async def annotate_products_visual_readiness(products: list[dict[str, Any]]) -> None:
    """Annotate one catalog page using three batched DB reads, not N+1 calls."""
    ids = [str(product.get("id") or "") for product in products if product.get("id")]
    if not ids:
        return
    locks = await crud.list_product_truth_locks(ids)
    packs = await crud.list_product_reference_packs_by_products(ids)
    preps = await crud.list_product_cutout_preparations(ids)
    histories = await crud.list_product_truth_lock_histories(ids)
    canva_workflows = await _list_canva_workflow_rows(ids)
    tombstoned: set[str] = set()
    # Tombstones are a small, indexed purge authority; load the page ids in one
    # query where possible, while legacy DBs without the table stay compatible.
    from agent.db.schema import get_db

    db = await get_db()
    placeholders = ",".join("?" for _ in ids)
    try:
        cur = await db.execute(
            f"SELECT alias_product_id FROM product_catalog_alias_tombstone WHERE alias_product_id IN ({placeholders})",
            ids,
        )
        tombstoned = {str(row[0]) for row in await cur.fetchall()}
    except Exception as exc:
        if "no such table" not in str(exc).lower():
            raise
    for product in products:
        pid = str(product.get("id") or "")
        lock = locks.get(pid)
        pack = packs.get(pid)
        prep = preps.get(pid)
        source = _reference_file(product)
        source_available = bool(source) or bool(_reference_pack_file(pack)) or _truth_row_approved(lock)
        blocked = "PURGED_ALIAS" if pid in tombstoned else _purge_reason(product)
        if not blocked and is_archived(product):
            blocked = "ARCHIVED_PRODUCT"
        if not blocked and is_test_product(product):
            blocked = "TEST_FIXTURE"
        product["visual_readiness"] = _readiness_payload(
            product,
            lock=lock,
            pack=pack,
            prep=prep,
            reference=None,
            source_available=source_available,
            source_error=None,
            blocked_reason=blocked,
            history=histories.get(pid, []),
            canva_workflow=canva_workflows.get(pid),
        )


def eligible_bulk_product(product: dict[str, Any], readiness: dict[str, Any]) -> bool:
    """Strict preview predicate for Prepare Missing Cutouts."""
    if str(product.get("lifecycle_status") or "ACTIVE").upper() != "ACTIVE":
        return False
    if product.get("reference_only") or is_test_product(product) or _purge_reason(product):
        return False
    if readiness.get("cutout_status") == APPROVED:
        return False
    if readiness.get("cutout_review_status") == PENDING_REVIEW:
        return False
    if readiness.get("auto_cutout_status") in {PENDING_REVIEW, REJECTED, APPROVED}:
        return False
    if readiness.get("manual_cutout_status") in {PENDING_REVIEW, APPROVED}:
        return False
    if not readiness.get("canonical_media_status") == "AVAILABLE":
        return False
    return bool(readiness.get("can_prepare_cutout") or readiness.get("can_rebuild_cutout"))


async def preview_bulk_cutout_preparation(*, limit: int = 454) -> dict[str, Any]:
    products = await crud.list_products(limit=max(1, min(int(limit), 1000)), include_archived=True)
    await annotate_products_visual_readiness(products)
    eligible: list[str] = []
    counts = {"eligible": 0, "already_approved": 0, "pending_review": 0, "blocked": 0, "skipped": 0}
    for product in products:
        readiness = product.get("visual_readiness") or {}
        pid = str(product.get("id") or "")
        if readiness.get("cutout_status") == APPROVED:
            counts["already_approved"] += 1
        elif readiness.get("cutout_review_status") == PENDING_REVIEW:
            counts["pending_review"] += 1
        elif eligible_bulk_product(product, readiness):
            counts["eligible"] += 1
            eligible.append(pid)
        else:
            reason = (readiness.get("blockers") or ["NOT_ELIGIBLE"])[0]
            if reason in {"ARCHIVED_PRODUCT", "MERGED_ALIAS", "PURGED_ALIAS", "TEST_FIXTURE", "TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED"}:
                counts["blocked"] += 1
            else:
                counts["skipped"] += 1
    digest = hashlib.sha256(json.dumps(eligible, separators=(",", ":")).encode()).hexdigest()
    return {
        "eligible_product_ids": eligible,
        "preview_digest": digest,
        "counts": counts,
        "total_scanned": len(products),
        "execution_policy": "BOUNDED_OPERATOR_CONFIRMATION_REQUIRED",
        "bounded_batch": {
            "default_size": 5,
            "max_size": 25,
            "estimated_throughput": "Measured from completed local runs; no provider work is scheduled.",
        },
        "provider_operations": 0,
        "created_without_credit": True,
    }


async def request_bulk_cutout_cancellation(run_id: str) -> dict[str, Any]:
    """Request a durable stop; the worker honours it after the active batch."""
    row = await crud.get_product_visual_onboarding_run(run_id)
    if not row:
        raise ProductVisualOnboardingError("BULK_RUN_NOT_FOUND", f"Run {run_id} was not found.")
    status = str(row.get("status") or "").upper()
    if status not in {"QUEUED", "RUNNING"}:
        return {"run_id": run_id, "status": status, "cancel_requested": False}
    _BULK_CANCEL_REQUESTS.add(run_id)
    return {"run_id": run_id, "status": "CANCEL_REQUESTED", "cancel_requested": True}


async def run_bulk_cutout_preparation(
    run_id: str,
    product_ids: Iterable[str],
    batch_size: int,
    concurrency: int = 2,
) -> None:
    ids = [str(value) for value in product_ids if str(value).strip()]
    batch_size = max(1, min(int(batch_size), 25))
    concurrency = max(1, min(int(concurrency), _compositor_worker_count()))
    await crud.update_product_visual_onboarding_run(run_id, status="RUNNING")
    processed = pending_review = failed = blocked = skipped = 0
    errors: list[dict[str, str]] = []
    try:
        for start in range(0, len(ids), batch_size):
            batch = ids[start : start + batch_size]
            semaphore = asyncio.Semaphore(concurrency)

            async def prepare_one(product_id: str):
                async with semaphore:
                    return product_id, await prepare_product_cutout(product_id)

            results = await asyncio.gather(
                *(prepare_one(product_id) for product_id in batch),
            )
            for product_id, result in results:
                state = str(result.get("cutout_status") or "")
                processed += 1
                if state == PENDING_REVIEW:
                    pending_review += 1
                elif state == PREPARATION_FAILED:
                    failed += 1
                    errors.append({"product_id": product_id, "code": str(result.get("failure_code") or "CUTOUT_PREPARATION_FAILED")})
                elif state == BLOCKED:
                    blocked += 1
                elif state == NOT_PREPARED:
                    skipped += 1
            await crud.update_product_visual_onboarding_run(
                run_id,
                total_processed=processed,
                total_pending_review=pending_review,
                total_failed=failed,
                total_blocked=blocked,
                total_skipped=skipped,
                error_log_json=json.dumps(errors, sort_keys=True),
            )
            if run_id in _BULK_CANCEL_REQUESTS:
                errors.append({
                    "code": "BULK_RUN_CANCELLED_AT_BATCH_BOUNDARY",
                    "message": "Operator cancellation was applied after the active batch completed.",
                })
                await crud.update_product_visual_onboarding_run(
                    run_id,
                    status="PARTIAL_FAILED",
                    total_processed=processed,
                    total_pending_review=pending_review,
                    total_failed=failed,
                    total_blocked=blocked,
                    total_skipped=skipped,
                    error_log_json=json.dumps(errors, sort_keys=True),
                )
                _BULK_CANCEL_REQUESTS.discard(run_id)
                return
        final_status = "PARTIAL_FAILED" if failed else "COMPLETED"
        await crud.update_product_visual_onboarding_run(
            run_id,
            status=final_status,
            total_processed=processed,
            total_pending_review=pending_review,
            total_failed=failed,
            total_blocked=blocked,
            total_skipped=skipped,
            error_log_json=json.dumps(errors, sort_keys=True),
        )
        _BULK_CANCEL_REQUESTS.discard(run_id)
    except Exception as exc:  # noqa: BLE001 - durable run receipt
        logger.exception("Bulk product visual onboarding failed for %s", run_id)
        await crud.update_product_visual_onboarding_run(
            run_id,
            status="FAILED",
            total_processed=processed,
            total_pending_review=pending_review,
            total_failed=failed + 1,
            total_blocked=blocked,
            total_skipped=skipped,
            error_log_json=json.dumps([*errors, {"code": "BULK_RUN_FAILED", "message": str(exc)}], sort_keys=True),
        )
        _BULK_CANCEL_REQUESTS.discard(run_id)
