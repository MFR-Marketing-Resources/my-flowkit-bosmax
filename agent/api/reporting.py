"""Read-only reporting router — BOSMAX Command Centre (Tier A).

Thin transport wrapper. ALL aggregation / filtering / KPI / drill-down logic lives in
`agent/services/reporting_service.py` (the service layer) so the logic is unit-testable
and the chart library stays a swappable pure-view layer.

Serves ONLY the coverage/exception gaps that existing endpoints do not already answer
(authored-copy presence, snapshot coverage, prompt-readiness histogram, filterable
drill-down). Cluster counts, mapping-summary, image counts and the failed-job SUMMARY
are served elsewhere and consumed by the frontend directly — not duplicated here.

Every endpoint is GET, read-only, and accepts the cross-filter + pagination seam params.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from agent.services import reporting_service as svc

router = APIRouter(prefix="/api/reporting", tags=["reporting"])


@router.get("/coverage/copywriting")
async def coverage_copywriting(
    lifecycle_status: str = Query("ACTIVE"),
    cluster: Optional[str] = Query(None),
    product_type_group: Optional[str] = Query(None),
):
    return await svc.copywriting_coverage(lifecycle_status, cluster, product_type_group)


@router.get("/coverage/product-intelligence")
async def coverage_product_intelligence(
    lifecycle_status: str = Query("ACTIVE"),
    cluster: Optional[str] = Query(None),
    product_type_group: Optional[str] = Query(None),
):
    return await svc.product_intelligence_coverage(lifecycle_status, cluster, product_type_group)


@router.get("/coverage/registration-queue")
async def coverage_registration_queue():
    """Pre-commit registration-queue backlog (cluster / product-type) — the drafts
    the committed-product KPIs cannot see. Makes '0 missing cluster' unambiguous."""
    return await svc.registration_queue_coverage()


@router.get("/pi-quality")
async def pi_quality(
    lifecycle_status: str = Query("ALL", description="ALL keeps archived debt visible"),
    cluster: Optional[str] = Query(None),
    product_type_group: Optional[str] = Query(None),
):
    """INTEL QUALITY DEBT authority (Mission-08D): the four mutually-exclusive PI
    classes (FULLY_COMPLETE / APPROVED_WITH_GOVERNED_ABSENCE /
    LEGACY_APPROVED_INCOMPLETE / MISSING_APPROVED_INTELLIGENCE), fixture-quarantined,
    each split ACTIVE vs ARCHIVED. Drill-down = /exceptions with the returned kinds."""
    return await svc.product_intelligence_quality_summary(
        lifecycle_status, cluster, product_type_group)


@router.get("/coverage/prompt-readiness")
async def coverage_prompt_readiness(
    lifecycle_status: str = Query("ACTIVE"),
    cluster: Optional[str] = Query(None),
    product_type_group: Optional[str] = Query(None),
):
    return await svc.prompt_readiness_histogram(lifecycle_status, cluster, product_type_group)


@router.get("/failed-generations")
async def failed_generations():
    """Honest failed-generation reporting: 24h/7d/30d/all-time windows + error/mode
    grouping + ADR-007 dead-DOM-lane classification. Read-only; deletes no history."""
    return await svc.failed_generation_report()


@router.get("/exceptions")
async def exceptions(
    kind: str = Query(..., description=f"one of: {', '.join(svc.EXCEPTION_KINDS)}"),
    lifecycle_status: str = Query("ACTIVE"),
    cluster: Optional[str] = Query(None),
    product_type_group: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, description="free-text search over the WHOLE cohort"),
    sort_by: Optional[str] = Query(None, description="allowlisted column; anything else falls back"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    include_test_fixtures: bool = Query(
        False,
        description="quarantined harness rows are excluded by default; true = fixture view",
    ),
    intelligence_stage: Optional[str] = Query(
        None, description=f"one of: {', '.join(svc.INTELLIGENCE_STAGES)}"),
    claim_risk_level: Optional[str] = Query(None, description="e.g. LOW / MEDIUM / HIGH"),
    copy_blocked: Optional[bool] = Query(
        None, description="true = no approved snapshot, so the copy lane fails closed"),
):
    if kind not in svc.EXCEPTION_KINDS:
        raise HTTPException(status_code=422, detail=f"UNKNOWN_EXCEPTION_KIND: {kind}")
    try:
        return await svc.list_exceptions(
            kind, lifecycle_status, cluster, product_type_group, limit, offset,
            q=q, sort_by=sort_by, sort_dir=sort_dir,
            include_test_fixtures=include_test_fixtures,
            intelligence_stage=intelligence_stage,
            claim_risk_level=claim_risk_level,
            copy_blocked=copy_blocked,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
