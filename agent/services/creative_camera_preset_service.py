"""Creative Intelligence — Round 3: product/category -> recommended camera /
video presets.

READ-FIRST, non-generative, reference/preview only. This service:
  * loads a committed, ingested Camera / Video Preset library
    (``creative_camera_preset_library.json``) from the workbook ``CameraSettings``
    sheet (shot distances, camera angles, movements, e-commerce shot types, named
    HOOK/BODY/CTA/TRANS presets, and the block-content -> preset mapping);
  * REUSES the Round 1 reconciliation engine
    (``creative_avatar_recommendation_service.resolve_cluster``) only to echo the
    product's canonical cluster for card context — the camera vocabulary itself is
    universal (structured by video block, not product cluster);
  * returns recommended camera/video presets for a product/category/cluster,
    optionally narrowed by block purpose or content type;
  * optionally persists the named presets into the ``creative_camera_preset`` config
    table (idempotent, dry-run default) purely for auditability.

Safety: it NEVER writes Product Truth, product rows or product camera columns,
Product Intelligence snapshots/drafts, Copy Sets, Copy Registry, Copy Intelligence,
DeepSeek, the canonical compiler, or any generation/asset table. Presets are
reference-only and are never sent to generation in Round 3.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import creative_avatar_recommendation_service as _avatar

_AUTHORITY = Path(__file__).resolve().parents[1] / "authority"
_LIBRARY_FILE = _AUTHORITY / "creative_camera_preset_library.json"

LIBRARY_SOURCE = "CREATIVE_CAMERA_PRESET_v1"

# Columns persisted to the creative_camera_preset config table by the seed.
_SEED_FIELDS = ("preset_name", "shot_type", "distance_angle", "movement", "block_group")


@lru_cache(maxsize=1)
def _library() -> dict[str, Any]:
    return json.loads(_LIBRARY_FILE.read_text(encoding="utf-8"))


def named_presets() -> list[dict[str, Any]]:
    return list(_library().get("named_presets", []))


def block_content_mapping() -> list[dict[str, Any]]:
    return list(_library().get("block_content_mapping", []))


def block_groups() -> list[str]:
    return list(_library().get("block_groups", []))


def quarantine() -> list[dict[str, Any]]:
    return list(_library().get("quarantine", []))


def _vocabulary() -> dict[str, Any]:
    lib = _library()
    return {
        "shot_distances": list(lib.get("shot_distances", [])),
        "camera_angles": list(lib.get("camera_angles", [])),
        "camera_movements": list(lib.get("camera_movements", [])),
        "ecomm_shot_types": list(lib.get("ecomm_shot_types", [])),
        "named_presets": named_presets(),
    }


@lru_cache(maxsize=1)
def _preset_index() -> dict[str, dict[str, Any]]:
    return {p["preset_code"]: p for p in named_presets()}


def _resolve_preset(code: str | None) -> dict[str, Any] | None:
    if not code:
        return None
    return _preset_index().get(code)


def _build_block_recommendations(
    block: str | None, content_type: str | None
) -> list[dict[str, Any]]:
    """Block-content -> preset mapping, each preset resolved to full detail.

    Placeholders/product data are never involved; this is static reference data.
    """
    out: list[dict[str, Any]] = []
    for m in block_content_mapping():
        if block and m.get("block_purpose", "").lower() != block.lower():
            continue
        if content_type and m.get("content_type", "").lower() != content_type.lower():
            continue
        out.append({
            "block_purpose": m.get("block_purpose"),
            "content_type": m.get("content_type"),
            "recommended_preset": _resolve_preset(m.get("recommended_preset")),
            "alt_presets": [
                p for p in (_resolve_preset(m.get("alt_preset_1")), _resolve_preset(m.get("alt_preset_2")))
                if p is not None
            ],
            "source_row": m.get("source_row"),
        })
    return out


def _build_recommendation(
    *, cluster: str, cluster_source: str, block: str | None, content_type: str | None
) -> dict[str, Any]:
    recs = _build_block_recommendations(block, content_type)
    return {
        "cluster": cluster,
        "cluster_source": cluster_source,
        "block_groups": block_groups(),
        "block_recommendation_count": len(recs),
        "block_recommendations": recs,
        "library": _vocabulary(),
        "filtered_by": {"block": block, "content_type": content_type},
        "has_recommendations": bool(recs),
    }


async def seed_camera_presets(*, dry_run: bool = True) -> dict[str, Any]:
    """Persist the named presets into the ``creative_camera_preset`` config table.

    Idempotent (upsert keyed on ``preset_code``). ``dry_run`` (default true) writes
    nothing. Only touches the config table — no Product Truth / product-row / Copy /
    generation effect.
    """
    from agent.db import crud

    presets = named_presets()
    written = 0
    for p in presets:
        if dry_run:
            continue
        payload = {k: p.get(k) for k in _SEED_FIELDS}
        payload["preset_code"] = p.get("preset_code")
        payload["provenance"] = f"{p.get('block_group')} row={p.get('source_row')} [src:{LIBRARY_SOURCE}]"
        await crud.upsert_creative_camera_preset(**payload)
        written += 1

    return {
        "dry_run": dry_run,
        "source": LIBRARY_SOURCE,
        "library_version": _library().get("library_version"),
        "presets_available": len(presets),
        "written": 0 if dry_run else written,
        "quarantine": quarantine(),
    }


async def recommend_camera_presets_for_category(
    category: str | None, block: str | None = None, content_type: str | None = None
) -> dict[str, Any]:
    """Read-only camera/video preset recommendation for a raw category.

    Resolves category -> canonical cluster via the Round 1 resolver (for card
    context), then returns the universal block-content preset guidance. Never
    mutates; never writes product camera columns; never calls generation.
    """
    resolved = _avatar.resolve_cluster(category)
    result = _build_recommendation(
        cluster=resolved["cluster"], cluster_source=resolved["cluster_source"],
        block=block, content_type=content_type,
    )
    result["category"] = category
    return result


async def recommend_camera_presets_for_cluster(
    cluster: str, block: str | None = None, content_type: str | None = None
) -> dict[str, Any]:
    """Read-only camera/video preset recommendation for an explicit cluster."""
    result = _build_recommendation(
        cluster=cluster, cluster_source="EXPLICIT_CLUSTER", block=block, content_type=content_type,
    )
    return result


async def recommend_camera_presets_for_product(
    product_id: str, block: str | None = None, content_type: str | None = None
) -> dict[str, Any]:
    """Read-only camera/video preset recommendation for a product (manual or
    imported). Raises ``ValueError('PRODUCT_NOT_FOUND')`` if unknown."""
    from agent.db import crud

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    result = await recommend_camera_presets_for_category(
        product.get("category"), block=block, content_type=content_type
    )
    result["product_id"] = product_id
    result["product_name"] = (
        product.get("product_display_name") or product.get("raw_product_title")
    )
    return result
