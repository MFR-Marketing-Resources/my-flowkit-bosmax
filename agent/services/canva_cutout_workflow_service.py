"""Durable Canva-assisted product cutout workflow authority.

Canva is an assisted operator lane in the current runtime.  This module owns
the parts BOSMAX can prove locally: canonical-source identity, dimensions,
workflow state, resumable queue state, PNG/alpha verification, provenance,
and handoff to the existing Product Visual manual-cutout authority.  It does
not store Canva cookies or pretend that MCP/browser control exists.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from PIL import Image

from agent.db import crud
from agent.services.product_intelligence import is_test_product
from agent.services.product_lifecycle_service import is_archived
from agent.services.product_visual_grounding_resolver import (
    ProductVisualReferenceRequiredError,
    resolve_product_reference_image,
)
from agent.services.product_visual_canvas_service import (
    STANDARD_VISUAL_CANVAS_HEIGHT,
    STANDARD_VISUAL_CANVAS_SIZE,
    STANDARD_VISUAL_CANVAS_WIDTH,
)


CANVA_STAGES = (
    "NOT_STARTED",
    "PREFLIGHT",
    "CANVA_PRO_REQUIRED",
    "OPENING_CANVA",
    "MAGIC_GRAB",
    "BACKGROUND_REMOVER",
    "MAGIC_LAYERS",
    "CLEAN_CANVAS",
    "READY_TO_EXPORT",
    "EXPORTING",
    "VERIFYING_ALPHA",
    "CUTOUT_READY",
    "PENDING_HUMAN_REVIEW",
    "APPROVED",
    "FAILED",
    "PAUSED",
    "CANCELLED",
)
CANVA_STAGE_SET = frozenset(CANVA_STAGES)
CANVA_METHODS = frozenset({"MAGIC_GRAB", "BACKGROUND_REMOVER", "MAGIC_LAYERS"})
CANVA_PROVENANCE = {
    "MAGIC_GRAB": "CANVA_MAGIC_GRAB",
    "BACKGROUND_REMOVER": "CANVA_BG_REMOVER",
    "MAGIC_LAYERS": "CANVA_MAGIC_LAYERS",
}
CANVA_PROVENANCE_VALUES = frozenset(CANVA_PROVENANCE.values())
CANVA_CAPABILITY_KEYS = (
    "login_status",
    "magic_grab_status",
    "background_remover_status",
    "magic_layers_status",
    "transparent_export_status",
)
CANVA_CAPABILITY_VALUES = frozenset({"READY", "UNAVAILABLE", "UNKNOWN", "PRO_REQUIRED", "USER_ACTION_REQUIRED"})
CANVA_TERMINAL_STAGES = frozenset({"APPROVED", "CANCELLED"})
CANVA_PENDING_STAGES = frozenset({"CUTOUT_READY", "PENDING_HUMAN_REVIEW"})
BULK_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
BULK_PENDING_ITEM_STAGES = frozenset({"NOT_STARTED", "PREFLIGHT", "PAUSED"})


class CanvaCutoutWorkflowError(ValueError):
    """Stable fail-closed Canva workflow error."""

    def __init__(self, code: str, message: str = "", *, status_code: int = 409) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _safe_design_url(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in {"canva.com", "www.canva.com", "app.canva.com", "design.canva.com"}:
        raise CanvaCutoutWorkflowError(
            "CANVA_DESIGN_URL_INVALID",
            "Canva design URL must be an HTTPS Canva URL; credentials and session data are not accepted.",
        )
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if any(token in key.lower() for token in ("token", "cookie", "session", "secret", "password", "api_key")):
            raise CanvaCutoutWorkflowError(
                "CANVA_DESIGN_URL_SECRET_FORBIDDEN",
                "Canva design URLs containing credentials or session tokens are not persisted.",
            )
    return raw[:2000]


def _safe_design_id(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) > 256 or any(token in raw.lower() for token in ("cookie", "session", "secret", "password")):
        raise CanvaCutoutWorkflowError(
            "CANVA_DESIGN_ID_INVALID",
            "Canva design ID is limited to a non-secret operator reference.",
        )
    return raw


def _default_preflight() -> dict[str, str]:
    return {key: "UNKNOWN" for key in CANVA_CAPABILITY_KEYS}


def _normalize_preflight(values: dict[str, Any] | None) -> dict[str, str]:
    result = _default_preflight()
    for key in CANVA_CAPABILITY_KEYS:
        value = str((values or {}).get(key) or result[key]).upper()
        if value not in CANVA_CAPABILITY_VALUES:
            raise CanvaCutoutWorkflowError(
                "CANVA_PREFLIGHT_STATUS_INVALID",
                f"Unsupported Canva preflight status for {key}.",
            )
        result[key] = value
    return result


def _method_status(preflight: dict[str, str], method: str) -> str:
    return preflight.get(
        {
            "MAGIC_GRAB": "magic_grab_status",
            "BACKGROUND_REMOVER": "background_remover_status",
            "MAGIC_LAYERS": "magic_layers_status",
        }.get(method, ""),
        "UNKNOWN",
    )


def _preflight_ready(preflight: dict[str, str], method: str | None = None) -> bool:
    if preflight.get("login_status") != "READY" or preflight.get("transparent_export_status") != "READY":
        return False
    if method:
        return method in CANVA_METHODS and _method_status(preflight, method) == "READY"
    return any(_method_status(preflight, candidate) == "READY" for candidate in CANVA_METHODS)


def _preflight_error(preflight: dict[str, str], method: str | None = None) -> tuple[str, str] | None:
    if preflight.get("transparent_export_status") == "PRO_REQUIRED":
        return "CANVA_PRO_REQUIRED", "Transparent PNG export is locked behind Canva Pro entitlement."
    if preflight.get("login_status") != "READY":
        return "CANVA_LOGIN_REQUIRED", "Confirm a live Canva session before editing or exporting."
    if preflight.get("transparent_export_status") != "READY":
        return "CANVA_TRANSPARENT_EXPORT_PREFLIGHT_REQUIRED", "Confirm transparent PNG export entitlement before editing."
    if method and _method_status(preflight, method) != "READY":
        return "CANVA_METHOD_UNAVAILABLE", f"The selected Canva method {method} is not proven available."
    if not method and not _preflight_ready(preflight):
        return "CANVA_METHOD_PREFLIGHT_REQUIRED", "Confirm at least one Canva cutout method is available."
    return None


def _provenance_for_method(method: str) -> str:
    normalized = str(method or "").upper()
    if normalized not in CANVA_METHODS:
        raise CanvaCutoutWorkflowError("CANVA_METHOD_REQUIRED", "Select Magic Grab, Background Remover, or Magic Layers.")
    return CANVA_PROVENANCE[normalized]


def _is_current_canva_candidate(lock: dict[str, Any] | None) -> bool:
    if not lock:
        return False
    provenance = _json(lock.get("provenance_json"), {})
    declared = str(
        provenance.get("canva_provenance_source")
        or provenance.get("cutout_provenance")
        or provenance.get("source")
        or ""
    ).upper()
    return declared in CANVA_PROVENANCE_VALUES


def _next_action(stage: str) -> str:
    return {
        "NOT_STARTED": "START_CANVA_PREFLIGHT",
        "PREFLIGHT": "COMPLETE_CANVA_PREFLIGHT",
        "CANVA_PRO_REQUIRED": "CANVA_PRO_REQUIRED",
        "OPENING_CANVA": "PERFORM_CANVA_UI_ACTION",
        "MAGIC_GRAB": "ISOLATE_PRODUCT_IN_CANVA",
        "BACKGROUND_REMOVER": "VERIFY_PRODUCT_PIXELS_IN_CANVA",
        "MAGIC_LAYERS": "REMOVE_NON_PRODUCT_LAYERS_IN_CANVA",
        "CLEAN_CANVAS": "COPY_TO_1000X1000_CANVAS",
        "READY_TO_EXPORT": "EXPORT_TRANSPARENT_PNG",
        "EXPORTING": "WAIT_FOR_OPERATOR_EXPORT",
        "VERIFYING_ALPHA": "VERIFY_PNG_ALPHA_LOCALLY",
        "CUTOUT_READY": "HANDOFF_TO_EXISTING_MANUAL_LANE",
        "PENDING_HUMAN_REVIEW": "REVIEW_ACTIVE_CANDIDATE",
        "APPROVED": "EXACT_CUTOUT_AUTHORIZED",
        "FAILED": "RETRY_OR_USE_SAME_PRODUCT_FALLBACK",
        "PAUSED": "RESUME_OPERATOR_WORKFLOW",
        "CANCELLED": "TERMINAL_CANCELLED",
    }.get(stage, "INSPECT_WORKFLOW")


def _workflow_payload(row: dict[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    stage = str(row.get("current_stage") or "NOT_STARTED").upper()
    if stage not in CANVA_STAGE_SET:
        stage = "FAILED"
    preflight = _normalize_preflight(_json(row.get("preflight_json"), {}))
    return {
        "workflow_id": row.get("workflow_id"),
        "product_id": row.get("product_id"),
        "source_sha256": row.get("source_sha256"),
        "source_dimensions": {
            "width": STANDARD_VISUAL_CANVAS_WIDTH,
            "height": STANDARD_VISUAL_CANVAS_HEIGHT,
        },
        "output_dimensions": {
            "width": int(row.get("output_width") or 0) or None,
            "height": int(row.get("output_height") or 0) or None,
        },
        "canva_method": row.get("canva_method") or "UNSELECTED",
        "design_id": row.get("design_id"),
        "design_url": row.get("design_url"),
        "current_stage": stage,
        "attempt_count": int(row.get("attempt_count") or 0),
        "last_error_code": row.get("last_error_code"),
        "last_error": row.get("last_error"),
        "preflight": preflight,
        "output_sha256": row.get("output_sha256"),
        "output_available": bool(row.get("output_path")),
        "alpha_verified": bool(row.get("alpha_verified")),
        "human_review_status": row.get("human_review_status") or "NOT_STARTED",
        "provenance_source": row.get("provenance_source"),
        "started_at": row.get("started_at"),
        "updated_at": row.get("updated_at"),
        "next_action": _next_action(stage),
        "automation_boundary": {
            "AUTOMATABLE_IN_BOSMAX": [
                "canonical_source_resolution",
                "sha256_and_dimension_capture",
                "durable_state_and_resume_ledger",
                "pillow_png_alpha_verification",
                "existing_manual_lane_handoff",
                "human_review_gate",
            ],
            "AUTOMATABLE_VIA_LOCAL_BROWSER_CONTROLLER": [
                "open_canva_design",
                "observe_canva_ui_capabilities",
                "operator_assisted_export_download",
            ],
            "USER_ACTION_REQUIRED": [
                "canva_login_and_session",
                "canva_pro_entitlement_confirmation",
                "magic_grab_or_background_remover_or_magic_layers",
                "visual_identity_review_and_approval",
            ],
        },
    }


async def _load_product_source(product_id: str) -> tuple[dict[str, Any], Any, Path, str, int, int]:
    product = await crud.get_product(product_id)
    if not product:
        raise CanvaCutoutWorkflowError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    if await crud.is_product_catalog_alias_tombstoned(product_id):
        raise CanvaCutoutWorkflowError("PURGED_ALIAS", "Purged catalog aliases cannot enter the Canva workflow.")
    if is_archived(product):
        raise CanvaCutoutWorkflowError("ARCHIVED_PRODUCT", "Archived products cannot enter a new Canva workflow.")
    if is_test_product(product):
        raise CanvaCutoutWorkflowError("TEST_FIXTURE", "Test fixtures cannot enter the Canva workflow.")
    try:
        reference = resolve_product_reference_image(dict(product), prefer_approved_cutout=False)
    except ProductVisualReferenceRequiredError as exc:
        raise CanvaCutoutWorkflowError("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - stable workflow boundary
        raise CanvaCutoutWorkflowError("CANONICAL_PRODUCT_SOURCE_INVALID", str(exc)) from exc
    source_path = Path(str(getattr(reference, "local_path", "") or "")).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise CanvaCutoutWorkflowError("TRUSTED_SAME_PRODUCT_SOURCE_REQUIRED", "A local canonical product image is required before Canva.")
    try:
        with Image.open(source_path) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001 - source evidence boundary
        raise CanvaCutoutWorkflowError("CANONICAL_PRODUCT_SOURCE_INVALID", f"Canonical product image cannot be decoded: {exc}") from exc
    if width <= 0 or height <= 0:
        raise CanvaCutoutWorkflowError("CANONICAL_PRODUCT_SOURCE_INVALID", "Canonical product dimensions are unavailable.")
    actual_sha = _sha256_path(source_path)
    declared_sha = str(getattr(reference, "sha256", "") or "").lower()
    if declared_sha and declared_sha != actual_sha:
        raise CanvaCutoutWorkflowError("CANONICAL_PRODUCT_SOURCE_INVALID", "Canonical source SHA-256 changed before Canva preflight.")
    return product, reference, source_path, actual_sha, width, height


async def _readiness(product_id: str) -> dict[str, Any]:
    from agent.services.product_visual_onboarding_service import get_product_visual_readiness

    return await get_product_visual_readiness(product_id)


async def _response(product_id: str) -> dict[str, Any]:
    row = await crud.get_canva_cutout_workflow(product_id)
    return {"workflow": _workflow_payload(row), "readiness": await _readiness(product_id)}


async def get_canva_cutout_workflow(product_id: str) -> dict[str, Any]:
    """Read the current state without downloading or opening Canva."""
    product = await crud.get_product(product_id)
    if not product:
        raise CanvaCutoutWorkflowError("PRODUCT_NOT_FOUND", f"Product {product_id} was not found.", status_code=404)
    row = await crud.get_canva_cutout_workflow(product_id)
    payload = _workflow_payload(row)
    if row is None:
        try:
            _product, _reference, _path, source_sha, width, height = await _load_product_source(product_id)
            payload["source_sha256"] = source_sha
            payload["source_dimensions"] = {
                "width": STANDARD_VISUAL_CANVAS_WIDTH,
                "height": STANDARD_VISUAL_CANVAS_HEIGHT,
            }
        except CanvaCutoutWorkflowError as exc:
            payload["last_error_code"] = exc.code
            payload["last_error"] = exc.message
    return payload


async def start_canva_cutout(product_id: str) -> dict[str, Any]:
    """Create or resume one product workflow at the preflight boundary."""
    _product, _reference, _path, source_sha, width, height = await _load_product_source(product_id)
    existing = await crud.get_canva_cutout_workflow(product_id)
    current = str((existing or {}).get("current_stage") or "NOT_STARTED").upper()
    existing_has_standard_canvas = (
        int((existing or {}).get("source_width") or 0),
        int((existing or {}).get("source_height") or 0),
    ) == STANDARD_VISUAL_CANVAS_SIZE
    if existing and existing_has_standard_canvas and current == "PENDING_HUMAN_REVIEW" and str(existing.get("source_sha256") or "") == source_sha:
        return await _response(product_id)
    if existing and existing_has_standard_canvas and current in {"PREFLIGHT", "CANVA_PRO_REQUIRED", "OPENING_CANVA", "MAGIC_GRAB", "BACKGROUND_REMOVER", "MAGIC_LAYERS", "CLEAN_CANVAS", "READY_TO_EXPORT", "EXPORTING", "VERIFYING_ALPHA", "PAUSED"} and str(existing.get("source_sha256") or "") == source_sha:
        return await _response(product_id)
    attempt_count = int((existing or {}).get("attempt_count") or 0) + 1
    row = await crud.upsert_canva_cutout_workflow(
        product_id,
        workflow_id=f"canva_{uuid.uuid4().hex}",
        source_sha256=source_sha,
        source_width=STANDARD_VISUAL_CANVAS_WIDTH,
        source_height=STANDARD_VISUAL_CANVAS_HEIGHT,
        canva_method="UNSELECTED",
        design_id=None,
        design_url=None,
        current_stage="PREFLIGHT",
        attempt_count=attempt_count,
        last_error_code=None,
        last_error=None,
        preflight_json=json.dumps(_default_preflight(), sort_keys=True),
        output_path=None,
        output_sha256=None,
        output_width=None,
        output_height=None,
        alpha_verified=0,
        human_review_status="NOT_STARTED",
        provenance_source=None,
        started_at=_now(),
    )
    await _sync_bulk_items(product_id, workflow_id=str((row or {}).get("workflow_id") or ""), stage="PREFLIGHT")
    return await _response(product_id)


async def record_canva_preflight(
    product_id: str,
    *,
    canva_method: str | None,
    design_id: str | None,
    design_url: str | None,
    preflight: dict[str, Any],
) -> dict[str, Any]:
    """Persist operator-observed Canva capability facts before editing."""
    _product, _reference, _path, source_sha, _width, _height = await _load_product_source(product_id)
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        await start_canva_cutout(product_id)
        row = await crud.get_canva_cutout_workflow(product_id)
    if not row or str(row.get("source_sha256") or "") != source_sha:
        raise CanvaCutoutWorkflowError("CANVA_SOURCE_CHANGED", "Restart Canva preflight because the canonical source changed.")
    method = str(canva_method or row.get("canva_method") or "UNSELECTED").upper()
    if method != "UNSELECTED" and method not in CANVA_METHODS:
        raise CanvaCutoutWorkflowError("CANVA_METHOD_INVALID", "Unsupported Canva cutout method.")
    normalized = _normalize_preflight(preflight)
    design = _safe_design_url(design_url)
    design_ref = _safe_design_id(design_id)
    failure = _preflight_error(normalized, None if method == "UNSELECTED" else method)
    if failure and failure[0] == "CANVA_PRO_REQUIRED":
        stage = "CANVA_PRO_REQUIRED"
    elif failure:
        stage = "PREFLIGHT"
    else:
        if method == "UNSELECTED":
            raise CanvaCutoutWorkflowError("CANVA_METHOD_REQUIRED", "Select the Canva method you will use after preflight.")
        stage = "OPENING_CANVA"
    await crud.upsert_canva_cutout_workflow(
        product_id,
        canva_method=method,
        design_id=design_ref,
        design_url=design,
        current_stage=stage,
        preflight_json=json.dumps(normalized, sort_keys=True),
        last_error_code=failure[0] if failure else None,
        last_error=failure[1] if failure else None,
        provenance_source=CANVA_PROVENANCE.get(method) if method in CANVA_METHODS else None,
        alpha_verified=0 if stage != "PENDING_HUMAN_REVIEW" else int(row.get("alpha_verified") or 0),
    )
    return await _response(product_id)


async def advance_canva_stage(
    product_id: str,
    *,
    stage: str,
    canva_method: str | None = None,
    design_id: str | None = None,
    design_url: str | None = None,
) -> dict[str, Any]:
    """Record an operator/browser-controller stage; never drives Canva UI."""
    normalized_stage = str(stage or "").upper()
    if normalized_stage not in CANVA_STAGE_SET:
        raise CanvaCutoutWorkflowError("CANVA_STAGE_INVALID", "Unsupported Canva workflow stage.")
    if normalized_stage in {"NOT_STARTED", "APPROVED", "PENDING_HUMAN_REVIEW", "CUTOUT_READY", "VERIFYING_ALPHA", "FAILED", "CANCELLED"}:
        raise CanvaCutoutWorkflowError("CANVA_STAGE_CONTROLLED_BY_WORKFLOW", "This stage is written by a dedicated workflow action.")
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_WORKFLOW_NOT_FOUND", "Start the per-product Canva workflow first.", status_code=404)
    if str(row.get("current_stage") or "") in CANVA_TERMINAL_STAGES:
        raise CanvaCutoutWorkflowError("CANVA_WORKFLOW_TERMINAL", "A terminal Canva workflow cannot be advanced.")
    method = str(canva_method or row.get("canva_method") or "UNSELECTED").upper()
    if method not in CANVA_METHODS:
        raise CanvaCutoutWorkflowError("CANVA_METHOD_REQUIRED", "Select a Canva method before recording UI progress.")
    preflight = _normalize_preflight(_json(row.get("preflight_json"), {}))
    failure = _preflight_error(preflight, method)
    if failure:
        raise CanvaCutoutWorkflowError(failure[0], failure[1])
    await crud.upsert_canva_cutout_workflow(
        product_id,
        canva_method=method,
        design_id=_safe_design_id(design_id) if design_id is not None else row.get("design_id"),
        design_url=_safe_design_url(design_url) if design_url is not None else row.get("design_url"),
        current_stage=normalized_stage,
        last_error_code=None,
        last_error=None,
        provenance_source=CANVA_PROVENANCE[method],
    )
    return await _response(product_id)


def _verify_canva_png(raw_bytes: bytes, expected_dimensions: tuple[int, int]) -> tuple[int, int, str]:
    if not raw_bytes:
        raise CanvaCutoutWorkflowError("CANVA_PNG_INVALID", "Canva output is empty.")
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            if (image.format or "").upper() != "PNG":
                raise CanvaCutoutWorkflowError("CANVA_PNG_REQUIRED", "Canva handoff requires a PNG export.")
            width, height = image.size
            if (width, height) != expected_dimensions:
                raise CanvaCutoutWorkflowError(
                    "CANVA_CANVAS_DIMENSIONS_MISMATCH",
                    "Canva output must be a transparent PNG on the standard 1000x1000 px canvas.",
                )
            if "A" not in image.getbands() and "transparency" not in image.info:
                raise CanvaCutoutWorkflowError(
                    "CANVA_ALPHA_REQUIRED",
                    "A white RGB PNG is not a transparent cutout; export an alpha-bearing PNG.",
                )
            rgba = image.convert("RGBA")
            try:
                alpha = rgba.getchannel("A")
                extrema = alpha.getextrema()
                if extrema[1] <= 0 or extrema[0] >= 255 or alpha.getbbox() is None:
                    raise CanvaCutoutWorkflowError(
                        "CANVA_ALPHA_REQUIRED",
                        "Canva output must contain transparent pixels and visible product pixels.",
                    )
            finally:
                rgba.close()
            return width, height, _sha256_bytes(raw_bytes)
    except CanvaCutoutWorkflowError:
        raise
    except Exception as exc:  # noqa: BLE001 - decode boundary
        raise CanvaCutoutWorkflowError("CANVA_PNG_INVALID", f"Canva PNG cannot be decoded: {exc}") from exc


async def complete_canva_cutout(
    product_id: str,
    *,
    filename: str,
    content_type: str | None,
    raw_bytes: bytes,
    uploaded_by: str,
    canva_method: str,
    design_id: str | None = None,
    design_url: str | None = None,
) -> dict[str, Any]:
    """Verify a Canva PNG and hand it to PR #683's existing manual lane."""
    method = str(canva_method or "").upper()
    provenance_source = _provenance_for_method(method)
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_WORKFLOW_NOT_FOUND", "Start Canva preflight before uploading a result.", status_code=404)
    if str(row.get("current_stage") or "") in CANVA_TERMINAL_STAGES:
        raise CanvaCutoutWorkflowError("CANVA_WORKFLOW_TERMINAL", "A terminal Canva workflow cannot accept a new export.")
    preflight = _normalize_preflight(_json(row.get("preflight_json"), {}))
    failure = _preflight_error(preflight, method)
    if failure:
        raise CanvaCutoutWorkflowError(failure[0], failure[1])
    source_width = STANDARD_VISUAL_CANVAS_WIDTH
    source_height = STANDARD_VISUAL_CANVAS_HEIGHT
    await crud.upsert_canva_cutout_workflow(
        product_id,
        canva_method=method,
        design_id=_safe_design_id(design_id) if design_id is not None else row.get("design_id"),
        design_url=_safe_design_url(design_url) if design_url is not None else row.get("design_url"),
        current_stage="VERIFYING_ALPHA",
        last_error_code=None,
        last_error=None,
        provenance_source=provenance_source,
    )
    try:
        output_width, output_height, output_sha = _verify_canva_png(raw_bytes, (source_width, source_height))
        from agent.services.product_visual_onboarding_service import upload_manual_product_cutout

        readiness = await upload_manual_product_cutout(
            product_id,
            filename=filename,
            content_type=content_type,
            raw_bytes=raw_bytes,
            uploaded_by=uploaded_by,
            provenance_source=provenance_source,
        )
        lock = await crud.get_product_truth_lock(product_id)
        media_id = str((readiness or {}).get("cutout_media_id") or "")
        media = await crud.get_product_source_media(media_id) if media_id else None
        await crud.upsert_canva_cutout_workflow(
            product_id,
            current_stage="PENDING_HUMAN_REVIEW",
            output_path=(lock or {}).get("canonical_cutout_path") or (media or {}).get("local_path"),
            output_sha256=(lock or {}).get("canonical_cutout_sha256") or output_sha,
            output_width=output_width,
            output_height=output_height,
            alpha_verified=1,
            human_review_status="PENDING_REVIEW",
            last_error_code=None,
            last_error=None,
        )
        await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="PENDING_HUMAN_REVIEW")
        return await _response(product_id)
    except Exception as exc:  # noqa: BLE001 - durable failure receipt
        code = getattr(exc, "code", None) or "CANVA_HANDOFF_FAILED"
        message = getattr(exc, "message", None) or str(exc)
        await crud.upsert_canva_cutout_workflow(
            product_id,
            current_stage="FAILED",
            last_error_code=code,
            last_error=message,
            human_review_status="NOT_STARTED",
            alpha_verified=0,
        )
        await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="FAILED", error=message)
        if isinstance(exc, CanvaCutoutWorkflowError):
            raise
        raise CanvaCutoutWorkflowError("CANVA_HANDOFF_FAILED", message) from exc


async def mark_canva_workflow_approved(product_id: str) -> dict[str, Any] | None:
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        return None
    lock = await crud.get_product_truth_lock(product_id)
    if not _is_current_canva_candidate(lock):
        return _workflow_payload(row)
    if str(row.get("current_stage") or "") not in CANVA_PENDING_STAGES:
        return _workflow_payload(row)
    await crud.upsert_canva_cutout_workflow(
        product_id,
        current_stage="APPROVED",
        human_review_status="APPROVED",
        alpha_verified=1,
        last_error_code=None,
        last_error=None,
    )
    await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="APPROVED")
    return _workflow_payload(await crud.get_canva_cutout_workflow(product_id))


async def mark_canva_workflow_rejected(product_id: str, reason: str) -> dict[str, Any] | None:
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        return None
    lock = await crud.get_product_truth_lock(product_id)
    if not _is_current_canva_candidate(lock):
        return _workflow_payload(row)
    await crud.upsert_canva_cutout_workflow(
        product_id,
        current_stage="FAILED",
        human_review_status="REJECTED",
        last_error_code="HUMAN_REVIEW_REJECTED",
        last_error=str(reason or "Rejected by reviewer"),
    )
    await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="FAILED", error=str(reason or "Rejected by reviewer"))
    return _workflow_payload(await crud.get_canva_cutout_workflow(product_id))


async def mark_canva_workflow_fallback(product_id: str, reason: str) -> dict[str, Any] | None:
    """Close a Canva candidate when the existing same-product fallback wins."""
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        return None
    lock = await crud.get_product_truth_lock(product_id)
    if not _is_current_canva_candidate(lock):
        return _workflow_payload(row)
    message = str(reason or "Same-product fallback selected by operator.")
    await crud.upsert_canva_cutout_workflow(
        product_id,
        current_stage="FAILED",
        human_review_status="REJECTED",
        last_error_code="SAME_PRODUCT_FALLBACK_SELECTED",
        last_error=message,
        alpha_verified=0,
    )
    await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="FAILED", error=message)
    return _workflow_payload(await crud.get_canva_cutout_workflow(product_id))


async def mark_canva_workflow_superseded_by_manual(product_id: str) -> dict[str, Any] | None:
    """Close a stale Canva attempt when a normal manual candidate replaces it."""
    row = await crud.get_canva_cutout_workflow(product_id)
    if not row:
        return None
    message = "A normal manual cutout candidate superseded this Canva attempt."
    await crud.upsert_canva_cutout_workflow(
        product_id,
        current_stage="FAILED",
        human_review_status="REJECTED",
        last_error_code="SUPERSEDED_BY_MANUAL_CUTOUT",
        last_error=message,
        alpha_verified=0,
    )
    await _sync_bulk_items(product_id, workflow_id=str(row.get("workflow_id") or ""), stage="FAILED", error=message)
    return _workflow_payload(await crud.get_canva_cutout_workflow(product_id))


async def preview_canva_cutout_bulk(*, limit: int = 1000) -> dict[str, Any]:
    from agent.services.product_visual_onboarding_service import preview_bulk_cutout_preparation

    base = await preview_bulk_cutout_preparation(limit=limit)
    candidate_ids = [str(value) for value in base.get("eligible_product_ids") or []]
    workflows = await crud.list_canva_cutout_workflows(candidate_ids)
    eligible: list[str] = []
    counts = {
        "eligible": 0,
        "already_approved": int((base.get("counts") or {}).get("already_approved") or 0),
        "pending_review": int((base.get("counts") or {}).get("pending_review") or 0),
        "canva_pro_required": 0,
        "missing_source": 0,
        "blocked": int((base.get("counts") or {}).get("blocked") or 0),
        "skipped": int((base.get("counts") or {}).get("skipped") or 0),
    }
    for product_id in candidate_ids:
        row = workflows.get(product_id)
        stage = str((row or {}).get("current_stage") or "NOT_STARTED")
        if stage == "APPROVED":
            counts["already_approved"] += 1
        elif stage == "PENDING_HUMAN_REVIEW":
            counts["pending_review"] += 1
        elif stage == "CANVA_PRO_REQUIRED":
            counts["canva_pro_required"] += 1
        elif stage not in {"NOT_STARTED", "FAILED", "CANCELLED", "PAUSED"}:
            counts["skipped"] += 1
        else:
            eligible.append(product_id)
    counts["eligible"] = len(eligible)
    digest = hashlib.sha256(json.dumps(eligible, separators=(",", ":")).encode()).hexdigest()
    return {
        "eligible_product_ids": eligible,
        "preview_digest": digest,
        "counts": counts,
        "remaining": len(eligible),
        "total_scanned": int(base.get("total_scanned") or 0),
        "execution_policy": "BOUNDED_OPERATOR_CONFIRMATION_REQUIRED",
        "automation_boundary": "USER_ACTION_REQUIRED_FOR_CANVA_UI",
        "bounded_batch": {
            "default_size": 3,
            "max_size": 25,
            "estimated_throughput": "Operator-paced; Canva UI actions are not run by the BOSMAX worker.",
        },
        "provider_operations": 0,
        "created_without_credit": True,
    }


def _bulk_preflight_status(preflight: dict[str, str]) -> tuple[str, str | None, str | None]:
    normalized = _normalize_preflight(preflight)
    if normalized.get("transparent_export_status") == "PRO_REQUIRED":
        return "BLOCKED_CANVA_PRO_REQUIRED", "CANVA_PRO_REQUIRED", "Transparent PNG export is locked behind Canva Pro entitlement."
    if not _preflight_ready(normalized):
        return "PAUSED", "CANVA_PREFLIGHT_REQUIRED", "Complete Canva login, capability, and transparent export preflight before resuming."
    return "QUEUED", None, None


async def prepare_canva_cutout_bulk(
    *,
    confirm: bool,
    preview_digest: str,
    max_products: int,
    priority_product_ids: list[str] | None,
    preflight: dict[str, Any] | None,
) -> dict[str, Any]:
    if not confirm:
        raise CanvaCutoutWorkflowError("EXPLICIT_CONFIRMATION_REQUIRED", "Preview and confirm the bounded Canva cohort before queueing.", status_code=400)
    preview = await preview_canva_cutout_bulk(limit=1000)
    if preview_digest != preview["preview_digest"]:
        raise CanvaCutoutWorkflowError("PREVIEW_STALE", "Catalog changed after Canva preview; refresh before queueing.")
    max_products = max(1, min(int(max_products), 25))
    available = list(preview.get("eligible_product_ids") or [])
    requested_priority = [str(value).strip() for value in (priority_product_ids or []) if str(value).strip()]
    ordered = [value for value in requested_priority if value in available]
    ordered.extend(value for value in available if value not in ordered)
    product_ids = ordered[:max_products]
    normalized = _normalize_preflight(preflight)
    status, error_code, error_message = _bulk_preflight_status(normalized)
    run_id = f"canva_bulk_{uuid.uuid4().hex}"
    await crud.create_canva_cutout_bulk_run(
        run_id,
        status=status,
        preview_digest=preview_digest,
        total_expected=len(product_ids),
        product_ids_json=json.dumps(product_ids, separators=(",", ":")),
        priority_product_ids_json=json.dumps(requested_priority, separators=(",", ":")),
        preflight_json=json.dumps(normalized, sort_keys=True),
        last_error_code=error_code,
        last_error=error_message,
    )
    for ordinal, product_id in enumerate(product_ids):
        await crud.create_canva_cutout_bulk_item(
            f"{run_id}_{ordinal}_{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            product_id=product_id,
            ordinal=ordinal,
            priority=0 if product_id in requested_priority else 1,
            current_stage="CANVA_PRO_REQUIRED" if status == "BLOCKED_CANVA_PRO_REQUIRED" else "NOT_STARTED",
            last_error=error_message,
        )
    return await get_canva_cutout_bulk_run(run_id)


async def _sync_bulk_items(product_id: str, *, workflow_id: str, stage: str, error: str | None = None) -> None:
    for item in await crud.list_canva_cutout_bulk_items_for_product(product_id):
        run = await crud.get_canva_cutout_bulk_run(str(item.get("run_id") or ""))
        run_status = str((run or {}).get("status") or "")
        if not run or (run_status in {"CANCELLED", "FAILED"} and stage != "APPROVED"):
            continue
        await crud.update_canva_cutout_bulk_item(
            str(item["item_id"]),
            workflow_id=workflow_id or item.get("workflow_id"),
            current_stage=stage,
            last_error=error,
        )
        await _refresh_canva_bulk_counts(str(item["run_id"]))


async def _refresh_canva_bulk_counts(run_id: str) -> dict[str, Any] | None:
    run = await crud.get_canva_cutout_bulk_run(run_id)
    if not run:
        return None
    items = await crud.list_canva_cutout_bulk_items(run_id)
    stages = [str(item.get("current_stage") or "NOT_STARTED") for item in items]
    ready = sum(stage in {"CUTOUT_READY", "APPROVED"} for stage in stages)
    pending = sum(stage == "PENDING_HUMAN_REVIEW" for stage in stages)
    failed = sum(stage == "FAILED" for stage in stages)
    blocked = sum(stage == "CANVA_PRO_REQUIRED" for stage in stages)
    bypassed = sum(stage == "BYPASSED" for stage in stages)
    processed = sum(stage not in {"NOT_STARTED", "PAUSED"} for stage in stages)
    next_index = next((index for index, stage in enumerate(stages) if stage in BULK_PENDING_ITEM_STAGES), len(stages))
    updates: dict[str, Any] = {
        "total_processed": processed,
        "total_ready": ready,
        "total_pending_review": pending,
        "total_failed": failed,
        "total_blocked": blocked,
        "total_bypassed": bypassed,
        "next_index": next_index,
    }
    if str(run.get("status") or "") == "RUNNING" and stages and all(stage not in BULK_PENDING_ITEM_STAGES for stage in stages):
        updates["status"] = "COMPLETED"
    return await crud.update_canva_cutout_bulk_run(run_id, **updates)


async def get_canva_cutout_bulk_run(run_id: str) -> dict[str, Any]:
    row = await crud.get_canva_cutout_bulk_run(run_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_BULK_RUN_NOT_FOUND", f"Canva bulk run {run_id} was not found.", status_code=404)
    row = await _refresh_canva_bulk_counts(run_id) or row
    return {
        "run_id": row.get("run_id"),
        "status": row.get("status"),
        "preview_digest": row.get("preview_digest"),
        "total_expected": int(row.get("total_expected") or 0),
        "total_processed": int(row.get("total_processed") or 0),
        "total_ready": int(row.get("total_ready") or 0),
        "total_pending_review": int(row.get("total_pending_review") or 0),
        "total_failed": int(row.get("total_failed") or 0),
        "total_blocked": int(row.get("total_blocked") or 0),
        "total_bypassed": int(row.get("total_bypassed") or 0),
        "next_index": int(row.get("next_index") or 0),
        "product_ids": _json(row.get("product_ids_json"), []),
        "priority_product_ids": _json(row.get("priority_product_ids_json"), []),
        "preflight": _normalize_preflight(_json(row.get("preflight_json"), {})),
        "last_error_code": row.get("last_error_code"),
        "last_error": row.get("last_error"),
        "items": await crud.list_canva_cutout_bulk_items(run_id),
        "provider_operations": 0,
        "created_without_credit": True,
        "automation_boundary": "USER_ACTION_REQUIRED_FOR_CANVA_UI",
    }


async def pause_canva_cutout_bulk(run_id: str) -> dict[str, Any]:
    row = await crud.get_canva_cutout_bulk_run(run_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_BULK_RUN_NOT_FOUND", f"Canva bulk run {run_id} was not found.", status_code=404)
    if str(row.get("status") or "") in BULK_TERMINAL_STATUSES:
        return await get_canva_cutout_bulk_run(run_id)
    await crud.update_canva_cutout_bulk_run(run_id, status="PAUSED", last_error_code=None, last_error=None)
    return await get_canva_cutout_bulk_run(run_id)


async def resume_canva_cutout_bulk(run_id: str, *, preflight: dict[str, Any] | None) -> dict[str, Any]:
    row = await crud.get_canva_cutout_bulk_run(run_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_BULK_RUN_NOT_FOUND", f"Canva bulk run {run_id} was not found.", status_code=404)
    if str(row.get("status") or "") in BULK_TERMINAL_STATUSES:
        return await get_canva_cutout_bulk_run(run_id)
    normalized = _normalize_preflight(preflight or _json(row.get("preflight_json"), {}))
    status, error_code, error_message = _bulk_preflight_status(normalized)
    if status == "BLOCKED_CANVA_PRO_REQUIRED":
        await crud.update_canva_cutout_bulk_run(run_id, status=status, preflight_json=json.dumps(normalized, sort_keys=True), last_error_code=error_code, last_error=error_message)
        for item in await crud.list_canva_cutout_bulk_items(run_id):
            if str(item.get("current_stage") or "") in BULK_PENDING_ITEM_STAGES:
                await crud.update_canva_cutout_bulk_item(str(item["item_id"]), current_stage="CANVA_PRO_REQUIRED", last_error=error_message)
        return await get_canva_cutout_bulk_run(run_id)
    if status != "QUEUED":
        await crud.update_canva_cutout_bulk_run(run_id, status="PAUSED", preflight_json=json.dumps(normalized, sort_keys=True), last_error_code=error_code, last_error=error_message)
        return await get_canva_cutout_bulk_run(run_id)
    await crud.update_canva_cutout_bulk_run(run_id, status="RUNNING", preflight_json=json.dumps(normalized, sort_keys=True), last_error_code=None, last_error=None)
    for item in await crud.list_canva_cutout_bulk_items(run_id):
        if str(item.get("current_stage") or "") in {"CANVA_PRO_REQUIRED", "PAUSED"}:
            await crud.update_canva_cutout_bulk_item(str(item["item_id"]), current_stage="NOT_STARTED", last_error=None)
    return await get_canva_cutout_bulk_run(run_id)


async def cancel_canva_cutout_bulk(run_id: str) -> dict[str, Any]:
    row = await crud.get_canva_cutout_bulk_run(run_id)
    if not row:
        raise CanvaCutoutWorkflowError("CANVA_BULK_RUN_NOT_FOUND", f"Canva bulk run {run_id} was not found.", status_code=404)
    if str(row.get("status") or "") not in BULK_TERMINAL_STATUSES:
        await crud.update_canva_cutout_bulk_run(run_id, status="CANCELLED", last_error_code="BULK_RUN_CANCELLED", last_error="Operator cancelled the remaining Canva queue.")
        for item in await crud.list_canva_cutout_bulk_items(run_id):
            stage = str(item.get("current_stage") or "")
            if stage in BULK_PENDING_ITEM_STAGES or stage == "CANVA_PRO_REQUIRED":
                await crud.update_canva_cutout_bulk_item(str(item["item_id"]), current_stage="CANCELLED", last_error="Operator cancelled the remaining Canva queue.")
    return await get_canva_cutout_bulk_run(run_id)


async def bypass_canva_cutout_bulk_item(run_id: str, product_id: str, *, reason: str) -> dict[str, Any]:
    item = await crud.get_canva_cutout_bulk_item_for_product(run_id, product_id)
    if not item:
        raise CanvaCutoutWorkflowError("CANVA_BULK_ITEM_NOT_FOUND", "Product is not in this Canva bulk run.", status_code=404)
    if str(item.get("current_stage") or "") in {"APPROVED", "PENDING_HUMAN_REVIEW"}:
        raise CanvaCutoutWorkflowError("CANVA_BULK_ITEM_TERMINAL", "A reviewed Canva item cannot be bypassed.")
    await crud.update_canva_cutout_bulk_item(
        str(item["item_id"]),
        current_stage="BYPASSED",
        last_error=str(reason or "Operator bypassed this product."),
    )
    await _refresh_canva_bulk_counts(run_id)
    return await get_canva_cutout_bulk_run(run_id)
