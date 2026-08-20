"""Shared product-visual custody and fidelity policy seam.

Product references are evidence with custody, not anonymous provider media ids.
This module deliberately stays provider-free: it validates the server-selected
bytes, records the authority that selected them, classifies the fidelity policy,
and fails closed when an exact-product request would enter a generative route.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from agent.services.exact_product_compositor_service import requires_exact_composite
from agent.services.product_lock_builder import build_product_lock
from agent.services import product_truth_lock_service


PRODUCT_VISUAL_CUSTODY_VERSION = "PRODUCT_VISUAL_CUSTODY_V1"
PRODUCT_LOCK_VERSION = "PRODUCT_LOCK_V1"

REFERENCE_CONDITIONED = "REFERENCE_CONDITIONED"
EXACT_PRODUCT_REQUIRED = "EXACT_PRODUCT_REQUIRED"

PRODUCT_FIDELITY_QC_PENDING = "PRODUCT_FIDELITY_QC_PENDING"
PRODUCT_FIDELITY_QC_PASS = "PRODUCT_FIDELITY_QC_PASS"
PRODUCT_FIDELITY_QC_FAIL = "PRODUCT_FIDELITY_QC_FAIL"
PRODUCT_FIDELITY_REVIEW_REQUIRED = "PRODUCT_FIDELITY_REVIEW_REQUIRED"

PRODUCT_FIDELITY_QC_DIMENSIONS = (
    "identity",
    "silhouette_geometry",
    "cap_components",
    "scale",
    "label_field_layout",
    "printed_text",
    "color_material",
    "duplication",
    "frame_morph",
)

ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN = "ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN"
ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED = "ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED"
ERR_OFFICIAL_PRODUCT_VISUAL_BYTES_UNREADABLE = (
    "ERR_OFFICIAL_PRODUCT_VISUAL_BYTES_UNREADABLE"
)
ERR_OFFICIAL_PRODUCT_VISUAL_HASH_MISMATCH = (
    "ERR_OFFICIAL_PRODUCT_VISUAL_HASH_MISMATCH"
)


class ProductVisualCustodyError(ValueError):
    """Stable fail-closed product custody/policy error."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha_text(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(asset: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if asset.get(key) not in (None, ""):
            return asset.get(key)
    return None


def _asset_is_official(asset: dict[str, Any] | None) -> bool:
    if not isinstance(asset, dict):
        return False
    source = str(_value(asset, "asset_source", "assetSource", "source") or "").upper()
    return bool(
        _value(asset, "official_visual", "officialVisual") is True
        or source.startswith("PRODUCT_VISUAL_OFFICIAL")
        or source in {"PRODUCT_TRUTH_LOCK_SOURCE", "PRODUCT_TRUTH_LOCK_CUTOUT"}
    )


def _asset_product_id(asset: dict[str, Any]) -> str | None:
    value = _value(asset, "product_id", "productId")
    return str(value).strip() if value not in (None, "") else None


def _asset_local_path(asset: dict[str, Any]) -> Path | None:
    raw = _value(asset, "local_file_path", "localFilePath")
    if not raw:
        return None
    return Path(str(raw)).expanduser().resolve()


def _receipt_hash(receipt: dict[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return _sha_text(_stable_json(body))


def product_visual_custody_receipt_sha256(receipt: dict[str, Any]) -> str:
    """Return the stable dispatch-lineage hash for complete or blocked receipts."""
    return _receipt_hash(receipt)


def exact_product_required(product: dict[str, Any] | None) -> bool:
    """Use the authored schema flag directly, independent of lane strategy.

    ``resolve_generation_strategy`` intentionally treats HYBRID as a human
    interaction strategy. That is not permission to weaken a product's exact
    visual policy, so this function is the custody seam's single policy check.
    """

    return bool(product and requires_exact_composite(product))


def _truth_lock_snapshot(product_id: str) -> dict[str, Any]:
    status = product_truth_lock_service.inspect_product_truth_lock(product_id)
    return {
        "status": status.get("product_truth_status"),
        "review_status": status.get("review_status"),
        "lock_present": bool(status.get("lock_present")),
        "lock_valid": bool(status.get("lock_valid")),
        "schema_version": status.get("schema_version"),
        "canonical_media_id": status.get("canonical_media_id"),
        "canonical_sha256": status.get("canonical_sha256"),
        "canonical_cutout_media_id": status.get("canonical_cutout_media_id"),
        "canonical_cutout_sha256": status.get("canonical_cutout_sha256"),
        "failure_state": status.get("failure_state"),
    }


def _product_lock_snapshot(product: dict[str, Any]) -> tuple[dict[str, Any], str]:
    lock = build_product_lock(product, is_video=True, has_product_reference=True)
    payload = {
        "version": PRODUCT_LOCK_VERSION,
        "product_id": product.get("id") or product.get("product_id"),
        "lock": lock,
    }
    return lock, _sha_text(_stable_json(payload))


def validate_official_reference_asset(
    product: dict[str, Any],
    official_asset: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate official ownership and the exact bytes before transport.

    A live Flow media id is never accepted as proof of the official bytes. The
    server-owned local path and its declared SHA must be present and must agree.
    """

    product_id = str(product.get("id") or product.get("product_id") or "").strip()
    if not product_id or not isinstance(official_asset, dict) or not _asset_is_official(official_asset):
        raise ProductVisualCustodyError(
            ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED,
            "A server-owned official product visual is required before video dispatch.",
        )
    asset_product_id = _asset_product_id(official_asset)
    if asset_product_id != product_id:
        raise ProductVisualCustodyError(
            ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED,
            "The official product visual belongs to a different product.",
            details={"product_id": product_id, "asset_product_id": asset_product_id},
        )
    declared_sha = str(
        _value(official_asset, "official_visual_sha256", "officialVisualSha256", "sha256")
        or ""
    ).strip().lower()
    path = _asset_local_path(official_asset)
    if not declared_sha or path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise ProductVisualCustodyError(
            ERR_OFFICIAL_PRODUCT_VISUAL_BYTES_UNREADABLE,
            "The official product visual has no readable server-owned bytes and cannot be dispatched.",
        )
    actual_sha = _sha_bytes(path)
    if actual_sha != declared_sha:
        raise ProductVisualCustodyError(
            ERR_OFFICIAL_PRODUCT_VISUAL_HASH_MISMATCH,
            "The official product visual bytes do not match the persisted SHA-256 authority.",
            details={"declared_sha256": declared_sha, "actual_sha256": actual_sha},
        )
    return {
        "asset_id": _value(official_asset, "asset_id", "assetId", "media_id", "mediaId"),
        "asset_source": _value(official_asset, "asset_source", "assetSource", "source"),
        "official_visual_sha256": declared_sha,
        "local_file_path": str(path),
        "size_bytes": path.stat().st_size,
        "width": _value(official_asset, "width"),
        "height": _value(official_asset, "height"),
        "product_id": product_id,
    }


def prompt_lock_status(product: dict[str, Any], prompt: str | None) -> dict[str, Any]:
    """Report prompt lock markers without treating marker presence as visual proof."""

    lock, _ = _product_lock_snapshot(product)
    text = str(prompt or "")
    markers = {
        "identity": "PRODUCT IDENTITY LOCK" in text,
        "geometry": "PRODUCT GEOMETRY LOCK" in text,
        "scale": "PRODUCT SCALE LOCK" in text,
        "reference": "PRODUCT REFERENCE LOCK" in text,
        "frame_persistence": "FRAME PERSISTENCE LOCK" in text,
        "no_modification": "PRODUCT NO-MODIFICATION LOCK" in text,
    }
    return {
        "markers": markers,
        "all_required_markers_present": all(markers.values()),
        "product_lock": lock,
        "prompt_is_not_visual_fidelity_proof": True,
    }


def build_product_visual_custody_receipt(
    product: dict[str, Any],
    official_asset: dict[str, Any] | None,
    *,
    mode: str,
    source_mode: str | None,
    prompt: str | None = None,
    provider_route: str | None = None,
    generation_type: str | None = None,
    execution_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the provider-affecting receipt before any provider operation."""

    product_id = str(product.get("id") or product.get("product_id") or "").strip()
    official = validate_official_reference_asset(product, official_asset)
    truth = _truth_lock_snapshot(product_id)
    product_lock, lock_fingerprint = _product_lock_snapshot(product)
    exact_required = exact_product_required(product)
    receipt: dict[str, Any] = {
        "receipt_version": PRODUCT_VISUAL_CUSTODY_VERSION,
        "product_id": product_id,
        "product_name": product.get("product_display_name") or product.get("raw_product_title") or product.get("name"),
        "official_visual_asset_id": official.get("asset_id"),
        "official_visual_asset_source": official.get("asset_source"),
        "official_visual_sha256": official.get("official_visual_sha256"),
        "canonical_source_sha256": truth.get("canonical_sha256"),
        "product_truth_lock": truth,
        "product_truth_lock_version": truth.get("schema_version"),
        "product_lock_version": PRODUCT_LOCK_VERSION,
        "product_lock_fingerprint": lock_fingerprint,
        "product_lock": product_lock,
        "uploaded_reference_media_id": None,
        "provider_reference_media_ids": [],
        "reference_transport": "NOT_DISPATCHED",
        "reference_bytes_sha256_verified": True,
        "source_mode": str(source_mode or "").strip().upper() or None,
        "mode": str(mode or "").strip().upper() or None,
        "provider_route": provider_route,
        "generation_type": generation_type,
        "fidelity_policy": EXACT_PRODUCT_REQUIRED if exact_required else REFERENCE_CONDITIONED,
        "exact_product_required": exact_required,
        "product_fidelity_qc_required": True,
        "product_fidelity_qc_status": PRODUCT_FIDELITY_QC_PENDING,
        "prompt_lock": prompt_lock_status(product, prompt),
        "execution_identity": copy.deepcopy(execution_identity) if execution_identity else None,
    }
    receipt["receipt_sha256"] = _receipt_hash(receipt)
    return receipt


def bind_provider_reference_transport(
    receipt: dict[str, Any],
    *,
    provider_reference_media_ids: list[str],
    official_provider_media_id: str | None,
    provider_route: str | None = None,
    generation_type: str | None = None,
) -> dict[str, Any]:
    """Attach observed provider ids only after local official bytes were resolved."""

    updated = copy.deepcopy(receipt)
    ids = [str(value) for value in provider_reference_media_ids if value]
    updated["provider_reference_media_ids"] = ids
    updated["uploaded_reference_media_id"] = official_provider_media_id
    updated["reference_transport"] = "LOCAL_OFFICIAL_BYTES_UPLOADED"
    if provider_route is not None:
        updated["provider_route"] = provider_route
    if generation_type is not None:
        updated["generation_type"] = generation_type
    updated["receipt_sha256"] = _receipt_hash(updated)
    return updated


def validate_pre_dispatch_route(
    receipt: dict[str, Any],
    *,
    provider_route: str,
    generation_type: str,
) -> None:
    """Reject exact products before approval, credit, upload, or project setup."""

    if not receipt.get("exact_product_required"):
        return
    if provider_route != "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE":
        raise ProductVisualCustodyError(
            ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN,
            "Exact-product video is blocked: the selected route is generative reference conditioning, not a proven deterministic exact-product route.",
            details={
                "fidelity_policy": receipt.get("fidelity_policy"),
                "provider_route": provider_route,
                "generation_type": generation_type,
                "required_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
            },
        )


def evaluate_product_fidelity_qc(
    receipt: dict[str, Any] | None,
    *,
    evidence: dict[str, Any] | None = None,
    artifact_available: bool = False,
) -> dict[str, Any]:
    """Evaluate structured fidelity evidence; never infer PASS from a prompt/id."""

    if not receipt or not receipt.get("product_fidelity_qc_required"):
        return {
            "status": PRODUCT_FIDELITY_QC_PASS,
            "verified": True,
            "reason": "Product fidelity QC not required.",
        }
    evidence = dict(evidence or {})
    explicit_status = str(evidence.get("status") or "").strip().upper()
    if explicit_status in {PRODUCT_FIDELITY_QC_FAIL, "FAIL"}:
        status = PRODUCT_FIDELITY_QC_FAIL
    elif (
        explicit_status in {PRODUCT_FIDELITY_QC_PASS, "PASS"}
        and evidence.get("verified") is True
        and _all_fidelity_dimensions_pass(evidence.get("dimensions"))
    ):
        status = PRODUCT_FIDELITY_QC_PASS
    elif artifact_available:
        status = PRODUCT_FIDELITY_REVIEW_REQUIRED
    else:
        status = PRODUCT_FIDELITY_QC_PENDING
    return {
        "status": status,
        "verified": status == PRODUCT_FIDELITY_QC_PASS,
        "reason": (
            "Structured product fidelity evidence passed."
            if status == PRODUCT_FIDELITY_QC_PASS
            else "Prompt/reference metadata cannot prove rendered product fidelity; human or deterministic QC evidence is required."
        ),
        "dimensions": evidence.get("dimensions") or {},
    }


def _dimension_pass(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().upper() in {"PASS", "PASSED", "VERIFIED", "OK"}
    if isinstance(value, dict):
        if value.get("verified") is True:
            return True
        return str(value.get("status") or "").strip().upper() in {
            "PASS",
            "PASSED",
            "VERIFIED",
            "OK",
        }
    return False


def _all_fidelity_dimensions_pass(dimensions: Any) -> bool:
    if not isinstance(dimensions, dict):
        return False
    return all(
        _dimension_pass(dimensions.get(key))
        for key in PRODUCT_FIDELITY_QC_DIMENSIONS
    )


def exact_output_ready(receipt: dict[str, Any] | None, qc: dict[str, Any] | None) -> bool:
    """Exact-product output is READY only after an explicit QC PASS."""

    if not receipt or not receipt.get("exact_product_required"):
        return True
    return bool(qc and qc.get("status") == PRODUCT_FIDELITY_QC_PASS and qc.get("verified") is True)
