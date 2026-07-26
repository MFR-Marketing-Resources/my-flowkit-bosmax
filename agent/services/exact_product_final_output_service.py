"""Shared exact final-output orchestration for MWCB and other exact-policy products.

Contract:
  PRODUCT RESOLUTION → EXACT-POLICY CHECK → CANONICAL VALIDATION
  → SCENE-ONLY (caller / Flow) → PLATE RETRIEVAL → DETERMINISTIC COMPOSITE
  → HONEST QA → PERSIST LINEAGE → RETURN FINAL ONLY

Raw Flow plates are internal and never marked product-truth preserved.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from agent.config import OUTPUT_DIR
from agent.db import crud
from agent.services.exact_product_compositor_service import (
    ExactProductCompositeError,
    LANE_SAFE_REGIONS,
    augment_prompt_scene_only,
    compose_final_from_plate,
    ensure_durable_canonical_copy,
    exact_product_policy,
    requires_exact_composite,
    scene_only_prompt_block,
    validate_canonical_or_raise,
)

logger = logging.getLogger(__name__)

# Trusted roots for plate paths (same spirit as poster deliverable).
_ALLOWED_PLATE_ROOTS: tuple[Path, ...] = (OUTPUT_DIR,)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_trusted_path(path_str: str) -> Path:
    path = Path(path_str).resolve()
    if not path.exists() or not path.is_file():
        raise ExactProductCompositeError(
            "SCENE_PLATE_MISSING",
            f"background image file missing: {path_str}",
            status_code=404,
        )
    allowed = False
    for root in _ALLOWED_PLATE_ROOTS:
        try:
            path.relative_to(root.resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ExactProductCompositeError(
            "SCENE_PLATE_PATH_FORBIDDEN",
            "Plate path outside trusted output roots.",
            status_code=403,
        )
    return path


async def resolve_product(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ExactProductCompositeError(
            "PRODUCT_NOT_FOUND", f"product {product_id} not found", status_code=404
        )
    return dict(product)


async def get_policy_for_product(product_id: str) -> dict[str, Any]:
    product = await resolve_product(product_id)
    if not requires_exact_composite(product):
        return {
            "product_id": product_id,
            "exact_product_composite_required": False,
            "scene_only_required": False,
            "send_product_reference_to_flow": True,
            "scene_only_prompt_block": "",
            "lanes": {},
        }
    try:
        meta = validate_canonical_or_raise(product)
        ensure_durable_canonical_copy(product)
        valid = True
        error = None
    except ExactProductCompositeError as exc:
        meta = {
            "exact_product_composite_required": True,
            "scene_only_required": True,
            "send_product_reference_to_flow": False,
        }
        valid = False
        error = {"code": exc.code, "message": exc.message}
    return {
        "product_id": product_id,
        "product_display_name": product.get("product_display_name")
        or product.get("raw_product_title"),
        "exact_product_composite_required": True,
        "scene_only_required": True,
        "send_product_reference_to_flow": False,
        "canonical_valid": valid,
        "canonical": meta if valid else None,
        "error": error,
        "scene_only_prompt_block": scene_only_prompt_block(),
        "lanes": LANE_SAFE_REGIONS,
        "progress_stages": [
            "validating_canonical",
            "generating_scene",
            "inserting_canonical_product",
            "running_qa",
            "final_ready",
        ],
    }


def build_scene_only_prompt(base_prompt: str) -> str:
    return augment_prompt_scene_only(base_prompt)


async def _resolve_plate(
    *,
    background_media_id: str = "",
    background_local_path: str = "",
) -> tuple[str, Path]:
    media_id = _norm(background_media_id)
    local = _norm(background_local_path)
    if media_id:
        artifact = await crud.get_generated_artifact(media_id)
        if not artifact:
            raise ExactProductCompositeError(
                "SCENE_PLATE_MISSING",
                f"generated artifact {media_id} not found",
                status_code=404,
            )
        art_local = _norm(artifact.get("local_path"))
        if not art_local:
            raise ExactProductCompositeError(
                "SCENE_PLATE_MISSING",
                "artifact has no local_path",
                status_code=404,
            )
        return media_id, _validate_trusted_path(art_local)
    if not local:
        raise ExactProductCompositeError(
            "SCENE_PLATE_MISSING",
            "background image file missing: (none)",
            status_code=404,
        )
    return "", _validate_trusted_path(local)


async def compose_final_for_product(
    *,
    product_id: str,
    background_media_id: str = "",
    background_local_path: str = "",
    lane: str = "studio",
    job_id: str | None = None,
) -> dict[str, Any]:
    """Deterministic finalize: plate + canonical cutout → registered final artifact."""
    product = await resolve_product(product_id)
    if not requires_exact_composite(product):
        raise ExactProductCompositeError(
            "EXACT_POLICY_NOT_REQUIRED",
            "Product does not require exact composite; use the standard IMG path.",
            status_code=400,
        )
    validate_canonical_or_raise(product)
    plate_media_id, plate_path = await _resolve_plate(
        background_media_id=background_media_id,
        background_local_path=background_local_path,
    )
    result = compose_final_from_plate(product, plate_path, lane=lane)

    final_media_id = str(uuid.uuid4())  # bare UUID — required by /api/flow/retrieved
    out_path = Path(result["output_path"])
    size_mb = round(out_path.stat().st_size / (1024 * 1024), 4)
    await crud.insert_generated_artifact(
        media_id=final_media_id,
        job_id=job_id or f"exact-compose:{plate_media_id or plate_path.name}",
        mode="IMG_EXACT_COMPOSITE",
        artifact_kind="image",
        local_path=str(out_path),
        size_mb=size_mb,
        model_used="DETERMINISTIC_EXACT_COMPOSITE",
    )

    lineage = {
        "product_id": product_id,
        "schema_key": result.get("schema_key"),
        "canonical_source_sha256": result["canonical_source_sha256"],
        "cutout_sha256": result["cutout_sha256"],
        "raw_plate_media_id": plate_media_id or None,
        "raw_plate_sha256": result["raw_plate_sha256"],
        "raw_plate_path": result["raw_plate_path"],
        "transform": result["transform"],
        "final_media_id": final_media_id,
        "final_output_sha256": result["output_sha256"],
        "final_output_path": result["output_path"],
        "qa": result["qa"],
        "truth_status": result["truth_status"],
        "raw_plate_approvable": False,
        "raw_plate_eligible_for_ready_frame": False,
        "raw_plate_eligible_for_product_reference": False,
        "final_approvable": True,
        "lane": lane,
    }
    lineage_path = out_path.with_suffix(".lineage.json")
    lineage_path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")

    logger.info(
        "exact_final_composed product=%s final=%s plate=%s",
        product_id,
        final_media_id,
        plate_media_id or plate_path.name,
    )
    return {
        "ok": True,
        "product_id": product_id,
        "media_id": final_media_id,
        "url": f"/api/flow/retrieved/{final_media_id}",
        "output_sha256": result["output_sha256"],
        "size_mb": size_mb,
        "lineage": lineage,
        "preview_sha_equals_saved_sha": True,
        "status": "DONE",
        "truth_status": result["truth_status"],
        "stages_completed": [
            "validating_canonical",
            "inserting_canonical_product",
            "running_qa",
            "final_ready",
        ],
    }


def policy_blocks_product_ref(product: dict[str, Any] | None) -> bool:
    """True when Flow must NOT receive a product reference image."""
    return requires_exact_composite(product)


def assert_not_raw_plate_save(lineage: dict[str, Any] | None) -> None:
    """Guardrail helper for save paths."""
    if not lineage:
        return
    if lineage.get("raw_plate_approvable"):
        raise ExactProductCompositeError(
            "RAW_PLATE_NOT_APPROVABLE",
            "Raw scene plates cannot be approved as final product assets.",
            status_code=409,
        )


# Re-export for callers
__all__ = [
    "ExactProductCompositeError",
    "assert_not_raw_plate_save",
    "build_scene_only_prompt",
    "compose_final_for_product",
    "exact_product_policy",
    "get_policy_for_product",
    "policy_blocks_product_ref",
    "requires_exact_composite",
    "resolve_product",
]
