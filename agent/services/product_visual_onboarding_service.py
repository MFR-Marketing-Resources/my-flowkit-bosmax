"""Provider-free product visual onboarding and readiness authority.

This module deliberately separates three states that were previously easy to
conflate:

* ``VISUAL_GROUNDING_READY`` means the resolver found a same-product source;
* ``CUTOUT_PENDING_REVIEW`` means deterministic preparation produced a review
  candidate; and
* ``EXACT_COMMERCE_CUTOUT_READY`` means the persisted Product Truth lock is
  approved and byte-valid.

No function in this module calls a provider or approves a truth lock.  The
existing resolver, reference-pack builder, and truth-lock service remain the
source authorities for their respective evidence.
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
from typing import Any, Iterable

from PIL import Image

from agent.config import BASE_DIR
from agent.db import crud
from agent.models.product_truth_lock import ProductTruthLockOnboardingRequest
from agent.services.product_intelligence import is_test_product
from agent.services.product_lifecycle_service import is_archived
from agent.services.product_lock_builder import resolve_schema_entry
from agent.services.product_visual_grounding_resolver import (
    ProductVisualReferenceRequiredError,
    resolve_product_reference_image,
)

logger = logging.getLogger(__name__)

NOT_PREPARED = "NOT_PREPARED"
PREPARING = "PREPARING"
PENDING_REVIEW = "PENDING_REVIEW"
APPROVED = "APPROVED"
PREPARATION_FAILED = "PREPARATION_FAILED"
BLOCKED = "BLOCKED"

PREPARATION_STATES = {
    NOT_PREPARED,
    PREPARING,
    PENDING_REVIEW,
    APPROVED,
    PREPARATION_FAILED,
    BLOCKED,
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

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


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


def _truth_row_approved(lock: dict[str, Any] | None) -> bool:
    return bool(lock and str(lock.get("review_status") or "").upper() == APPROVED)


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


def _reference_file(product: dict[str, Any]) -> Path | None:
    """Cheap local source check used by list/preview; it never downloads URLs."""
    local = _path(product.get("local_image_path"))
    if local:
        return local
    entry = resolve_schema_entry(product) or {}
    schema_path = entry.get("canonical_source_path") or (
        entry.get("canonical_product_photo") or {}
    ).get("source_path")
    return _path(schema_path)


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
        return "SAME_PRODUCT_CANONICAL_REFERENCE"
    source_type = str(getattr(reference, "source_type", "") or "")
    if source_type:
        return source_type
    return "SAME_PRODUCT_CANONICAL_REFERENCE"


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
        return PREPARATION_FAILED
    state = str((prep or {}).get("status") or NOT_PREPARED).upper()
    return state if state in PREPARATION_STATES else NOT_PREPARED


def _candidate_actions(
    product: dict[str, Any],
    *,
    source_available: bool,
    state: str,
    lock: dict[str, Any] | None,
    blocked_reason: str | None,
) -> dict[str, bool]:
    active = not blocked_reason
    pending = str((lock or {}).get("review_status") or "").upper() == PENDING_REVIEW
    approved = _truth_row_approved(lock)
    return {
        "can_prepare_cutout": bool(active and source_available and not approved and not pending),
        "can_review_cutout": bool(active and pending),
        "can_approve_cutout": bool(active and pending),
        "can_rebuild_cutout": bool(active and source_available and not approved),
        "can_open_source": bool(source_available or product.get("image_url")),
        "can_view": True,
    }


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
) -> dict[str, Any]:
    state = _prep_state(lock, prep)
    approved = _truth_row_approved(lock)
    if approved:
        grounding_status = "VISUAL_GROUNDING_READY"
        exact_status = "EXACT_COMMERCE_CUTOUT_READY"
    elif source_available:
        grounding_status = "VISUAL_GROUNDING_READY"
        exact_status = "EXACT_COMMERCE_REVIEW_REQUIRED"
    else:
        grounding_status = "VISUAL_GROUNDING_BLOCKED"
        exact_status = "EXACT_COMMERCE_BLOCKED"

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

    actions = _candidate_actions(
        product,
        source_available=source_available,
        state=state,
        lock=lock,
        blocked_reason=blocked_reason,
    )
    return {
        "product_id": str(product.get("id") or ""),
        "canonical_media_status": "AVAILABLE" if source_available else "MISSING",
        "reference_pack_status": str((pack or {}).get("pack_status") or "NOT_PREPARED"),
        "visual_grounding_status": grounding_status,
        "visual_grounding_source": _source_label(reference, approved=approved),
        "cutout_status": state,
        "cutout_review_status": str((lock or {}).get("review_status") or "NOT_CREATED"),
        "exact_commerce_status": exact_status,
        "cutout_media_id": (lock or {}).get("canonical_cutout_media_id")
        or (prep or {}).get("cutout_media_id"),
        "cutout_preview_available": bool(
            (lock or {}).get("canonical_cutout_path")
            or (prep or {}).get("cutout_media_id")
        ),
        "attempt_count": int((prep or {}).get("attempt_count") or 0),
        "failure_code": (prep or {}).get("failure_code"),
        "failure_message": (prep or {}).get("failure_message"),
        "blockers": blockers,
        "warnings": warnings,
        "provider_operations": 0,
        "created_without_credit": True,
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
            raw_cutout, bounds, cutout_sha, compositor_seconds = await _run_cutout_compositor(
                source_path
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

        media_started = time.perf_counter()
        media = await register_product_truth_cutout_media(
            product_id,
            filename=f"deterministic-cutout-{cutout_sha[:16]}.png",
            content_type="image/png",
            raw_bytes=raw_cutout,
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
                created_by="system:deterministic-product-cutout",
                onboarding_note="Deterministic local candidate; explicit human review and approval required.",
            ),
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


async def ensure_product_visual_onboarding(
    product_id: str,
    *,
    reference_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registration seam: pack evidence plus cutout preparation receipt."""
    result = await prepare_product_cutout(product_id)
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
    pack = await crud.get_product_reference_pack(product_id)
    prep = await crud.get_product_cutout_preparation(product_id)
    reference = None
    source_error = None
    source_available = bool(_reference_file(product)) or _truth_row_approved(lock)
    # Detail reads stay read-only: the resolver is consulted only when a
    # server-local source/approved lock already exists.  URL-only rows remain
    # visibly unresolved until an explicit Prepare action is pressed; a GET must
    # not download or materialize a remote image as a hidden side effect.
    if not source_available:
        for media in await crud.list_product_source_media(product_id=product_id):
            if _path(media.get("local_path")):
                source_available = True
                break
    if source_available:
        try:
            reference = await _resolve_source(product)
            source_available = bool(_path(getattr(reference, "local_path", None))) or _truth_row_approved(lock)
        except ProductVisualOnboardingError as exc:
            source_error = exc.code
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
    )


async def annotate_products_visual_readiness(products: list[dict[str, Any]]) -> None:
    """Annotate one catalog page using three batched DB reads, not N+1 calls."""
    ids = [str(product.get("id") or "") for product in products if product.get("id")]
    if not ids:
        return
    locks = await crud.list_product_truth_locks(ids)
    packs = await crud.list_product_reference_packs_by_products(ids)
    preps = await crud.list_product_cutout_preparations(ids)
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
            source_available=bool(source),
            source_error=None,
            blocked_reason=blocked,
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
