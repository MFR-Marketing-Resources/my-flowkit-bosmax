"""Copywriting readiness API — the shared contract for generation-surface gates.

Read-only; no token spend. Composes product-intelligence snapshot + copy
grounding + copy sets + formula into one payload.
"""
from fastapi import APIRouter, HTTPException, Query

from agent.models.copywriting_taxonomy import (
    CopywritingTaxonomyEntry,
    CopywritingTaxonomyListResponse,
    CopywritingTaxonomyProductResolution,
    CopywritingTaxonomyRollupResponse,
)

from agent.models.lip_color_copy_strategy import (
    LipColorCopyStrategyResponse,
    LipColorDurationSeconds,
)
from agent.models.rempah_copy_strategy import (
    RempahCopyStrategyResponse,
    RempahDurationSeconds,
)
from agent.models.product_type_copy_strategy import (
    CatalogAuthorityMatrixReport,
    CatalogCoverageMatrixReport,
    ProductTypeCopyEligibleReport,
    ProductTypeCopyStrategyResponse,
)
from agent.services.catalog_coverage_service import (
    build_catalog_authority_matrix,
    build_catalog_coverage_matrix,
)
from agent.services.copy_set_service import CopySetError
from agent.services.copywriting_readiness_service import get_copywriting_readiness
from agent.services.fastmoss_product_reference_service import (
    is_fastmoss_reference_product_id,
)
from agent.services.lip_color_copy_strategy_service import (
    LipColorCopyStrategyError,
    build_lip_color_copy_strategy,
)
from agent.services.rempah_copy_strategy_service import (
    RempahCopyStrategyError,
    build_rempah_copy_strategy,
)
from agent.services.product_type_copy_strategy_service import (
    ProductTypeCopyStrategyError,
    build_product_type_copy_eligible_report,
    build_product_type_copy_strategy,
)
from agent.services.copywriting_taxonomy_service import (
    get_copywriting_taxonomy_entry,
    get_copywriting_taxonomy_rollup,
    list_copywriting_taxonomy_entries,
    resolve_product_taxonomy,
)

router = APIRouter(prefix="/copywriting", tags=["copywriting"])


@router.get(
    "/p3a/lip-color/{product_id}",
    response_model=LipColorCopyStrategyResponse,
)
async def p3a_lip_color_copy_strategy(
    product_id: str,
    duration_seconds: LipColorDurationSeconds = LipColorDurationSeconds.SECONDS_8,
):
    """Preview direct-BM P3A copy without provider calls or persistence."""
    try:
        return await build_lip_color_copy_strategy(product_id, duration_seconds)
    except LipColorCopyStrategyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.code,
                "product_id": exc.product_id,
                "blocked_reasons": exc.blocked_reasons,
            },
        ) from exc


@router.get(
    "/p3b/rempah/{product_id}",
    response_model=RempahCopyStrategyResponse,
)
async def p3b_rempah_copy_strategy(
    product_id: str,
    duration_seconds: RempahDurationSeconds = RempahDurationSeconds.SECONDS_8,
):
    """Preview Direct BM P3B rempah copy without provider calls or persistence."""
    try:
        return await build_rempah_copy_strategy(product_id, duration_seconds)
    except RempahCopyStrategyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.code,
                "product_id": exc.product_id,
                "blocked_reasons": exc.blocked_reasons,
            },
        ) from exc


@router.get(
    "/p4/product-type/{product_id}",
    response_model=ProductTypeCopyStrategyResponse,
)
async def p4_product_type_copy_strategy(
    product_id: str,
    duration_seconds: int = 8,
):
    """Preview generalized Direct BM copy without persistence or providers."""
    try:
        return await build_product_type_copy_strategy(
            product_id,
            duration_seconds,
        )
    except ProductTypeCopyStrategyError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.code,
                "product_id": exc.product_id,
                "blocked_reasons": exc.blocked_reasons,
            },
        ) from exc


@router.get(
    "/p4/eligible-report",
    response_model=ProductTypeCopyEligibleReport,
)
async def p4_product_type_eligible_report():
    """Return the read-only full-catalog P4 eligibility summary."""
    return await build_product_type_copy_eligible_report()


@router.get(
    "/p5-7/catalog-coverage",
    response_model=CatalogCoverageMatrixReport,
)
async def p5_7_catalog_coverage_matrix():
    """Return the authoritative full-catalog coverage and P6 launch cohort."""
    return await build_catalog_coverage_matrix()


@router.get(
    "/p5-8/catalog-authority",
    response_model=CatalogAuthorityMatrixReport,
)
async def p5_8_catalog_authority_matrix():
    """Return all 659 products with one deterministic terminal state each."""

    return await build_catalog_authority_matrix()


@router.get(
    "/taxonomy",
    response_model=CopywritingTaxonomyListResponse,
)
async def copywriting_taxonomy_registry(
    cluster_name: str | None = Query(default=None),
    category: str | None = Query(default=None),
    subcategory: str | None = Query(default=None),
    type_name: str | None = Query(default=None, alias="type"),
    product_type_code: str | None = Query(default=None),
    registry_status: str | None = Query(default=None),
    query: str | None = Query(default=None, alias="q"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """List the registered workbook dependency map without mutating products."""

    try:
        return await list_copywriting_taxonomy_entries(
            cluster_name=cluster_name,
            category=category,
            subcategory=subcategory,
            type_name=type_name,
            product_type_code=product_type_code,
            registry_status=registry_status,
            query=query,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/taxonomy/rollup",
    response_model=CopywritingTaxonomyRollupResponse,
)
async def copywriting_taxonomy_rollup():
    """Return the cluster/category/subcategory/type/angle dependency counts."""

    return await get_copywriting_taxonomy_rollup()


@router.get(
    "/taxonomy/entry/{product_type_code}",
    response_model=CopywritingTaxonomyEntry,
)
async def copywriting_taxonomy_entry(
    product_type_code: str,
    cluster_name: str | None = Query(default=None),
):
    entry = await get_copywriting_taxonomy_entry(
        product_type_code,
        cluster_name=cluster_name,
    )
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "COPYWRITING_TAXONOMY_ENTRY_NOT_FOUND",
                "product_type_code": product_type_code,
            },
        )
    return entry


@router.get(
    "/taxonomy/product/{product_id}",
    response_model=CopywritingTaxonomyProductResolution,
)
async def resolve_product_copywriting_taxonomy(product_id: str):
    """Resolve an existing product against the new authority, read-only."""

    resolution = await resolve_product_taxonomy(product_id)
    if resolution is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "PRODUCT_NOT_FOUND", "product_id": product_id},
        )
    return resolution


@router.get("/readiness/{product_id}")
async def copywriting_readiness(product_id: str):
    """Shared copywriting readiness for a product. Drives the generation-surface
    readiness card + 'Prepare Product for Copywriting' CTA + copy-bind gate."""
    if is_fastmoss_reference_product_id(product_id):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "REFERENCE_ONLY_PRODUCT",
                "detail": {
                    "product_id": product_id,
                    "conversion_instruction": (
                        "Convert/Register this FastMoss reference before requesting "
                        "copywriting readiness."
                    ),
                },
            },
        )
    try:
        return await get_copywriting_readiness(product_id)
    except CopySetError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.code, "detail": exc.detail},
        ) from exc
