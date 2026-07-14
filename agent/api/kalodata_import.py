"""Kalodata/External catalog import API.
Mount prefix: /api/kalodata

Additive staged import (2026-07-13): parses the Owner's Kalodata/Fastmoss
merged workbook into the staged reference catalog + HUB enrichment files.
Zero AI calls, zero direct `product` writes — promotion stays behind the
existing reviewed /fastmoss-bulk gates.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from agent.models.kalodata_import import (
    KalodataApplyHubRequest,
    KalodataCacheImagesRequest,
    KalodataImportReport,
    KalodataImportRequest,
)
from agent.services import kalodata_import_service as _svc

router = APIRouter(prefix="/kalodata", tags=["kalodata"])

# Default source workbook on the Owner's machine; the request may override.
DEFAULT_SOURCE_PATH = (
    r"C:\Users\USER\Desktop\Fastmoss\Kalodata-BONUS 300 DATA PRODUK.xlsx"
)

_CACHE_IMAGES_MAX = 25
_CACHE_IMAGE_ATTEMPTS = 3


@router.post("/import", response_model=KalodataImportReport)
async def import_external_catalog(body: KalodataImportRequest):
    source_path = (body.source_path or "").strip() or DEFAULT_SOURCE_PATH
    try:
        # Duplicate law: the TikTok Product ID is the product identity — rows
        # whose tid already exists in the system are never staged.
        existing_tids = await _svc.collect_system_tids()
        return await asyncio.to_thread(
            _svc.import_workbook, source_path, existing_tids
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, f"WORKBOOK_NOT_FOUND:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim, never partial-staged
        raise HTTPException(422, f"IMPORT_FAILED:{exc}") from exc


@router.post("/copy-intelligence/dry-run")
async def dry_run_copy_intelligence_seed(body: KalodataImportRequest):
    """Read COPYWRITING HUB and return a review-only seed audit."""
    source_path = (body.source_path or "").strip()
    if not source_path:
        raise HTTPException(422, "SOURCE_PATH_REQUIRED")
    try:
        return await _svc.build_copy_intelligence_dry_run_for_system(source_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"WORKBOOK_NOT_FOUND:{exc}") from exc
    except Exception as exc:  # noqa: BLE001 — fail closed before any seed action
        raise HTTPException(422, f"COPY_INTELLIGENCE_DRY_RUN_FAILED:{exc}") from exc


@router.post("/purge-duplicates")
async def purge_duplicates(dry_run: bool = False):
    """Purge never-drafted queue rows whose TikTok product id duplicates
    another queue row or an already-committed product."""
    return await _svc.purge_redundant_queue_rows(dry_run=dry_run)


@router.post("/apply-hub-enrichment")
async def apply_hub_enrichment(body: KalodataApplyHubRequest):
    return await _svc.apply_hub_enrichment(body.reference_ids)


@router.get("/hub-gaps")
async def get_hub_gaps():
    return await _svc.hub_gaps()


@router.post("/cache-images")
async def cache_images(body: KalodataCacheImagesRequest) -> dict[str, Any]:
    """Bounded batch wrapper over the existing per-product cache-image door
    (committed products only). Sequential with per-item retry — never parallel
    hammering of the CDN."""
    product_ids = [p.strip() for p in body.product_ids if p and p.strip()]
    if not product_ids:
        raise HTTPException(422, "PRODUCT_IDS_REQUIRED")
    if len(product_ids) > _CACHE_IMAGES_MAX:
        raise HTTPException(422, f"MAX_{_CACHE_IMAGES_MAX}_PRODUCTS_PER_CALL")

    from agent.api.products import cache_product_image

    results: list[dict[str, Any]] = []
    cached = failed = 0
    for product_id in product_ids:
        outcome: dict[str, Any] = {"product_id": product_id}
        for attempt in range(1, _CACHE_IMAGE_ATTEMPTS + 1):
            try:
                result = await cache_product_image(product_id)
            except HTTPException as exc:
                outcome.update(status="failed", detail=str(exc.detail))
                break
            except Exception as exc:  # noqa: BLE001
                outcome.update(status="failed", detail=str(exc)[:200])
                break
            outcome.update(result)
            if result.get("status") == "success":
                break
            if attempt < _CACHE_IMAGE_ATTEMPTS:
                await asyncio.sleep(1.5 * attempt)
        if outcome.get("status") == "success":
            cached += 1
        else:
            failed += 1
        results.append(outcome)
    return {"results": results, "cached": cached, "failed": failed}
