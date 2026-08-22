"""Read-only Production Output management reporting transport."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from agent.security.access_control import get_current_auth_context
from agent.services import production_output_reporting_service as svc

router = APIRouter(prefix="/api/reporting/production", tags=["production-reporting"])


def _filters(
    staff: Optional[str],
    media_type: Optional[str],
    production_recipe: Optional[str],
    origin_surface: Optional[str],
    product_id: Optional[str],
    provider: Optional[str],
    model_key: Optional[str],
    status: Optional[str],
    qa_status: Optional[str],
) -> dict[str, str | None]:
    values = {
        "staff": staff,
        "media_type": media_type,
        "production_recipe": production_recipe,
        "origin_surface": origin_surface,
        "product_id": product_id,
        "provider": provider,
        "model_key": model_key,
        "status": status,
        "qa_status": qa_status,
    }
    for name, value in values.items():
        try:
            svc.validate_filter_value(name, value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return values


async def _report(
    *,
    start_date: Optional[str],
    end_date: Optional[str],
    filters: dict[str, str | None],
    request: Request,
):
    context = get_current_auth_context() or getattr(request.state, "auth_context", None)
    if context is None:
        raise HTTPException(status_code=401, detail={"error": "AUTHENTICATION_REQUIRED"})
    # OWNER and MANAGER may inspect the organization. Other roles receive only
    # their own real StaffProfile lineage; arbitrary staff query parameters are
    # never an impersonation/reporting authority.
    if not ({"OWNER", "MANAGER"} & set(context.role_codes)):
        requested_staff = str(filters.get("staff") or "").strip()
        if requested_staff and requested_staff != context.staff_id:
            raise HTTPException(
                status_code=403,
                detail={"error": "REPORTING_STAFF_SCOPE_DENIED"},
            )
        filters["staff"] = context.staff_id
    try:
        return await svc.get_production_report(
            start_date=start_date,
            end_date=end_date,
            filters=filters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
@router.get("/")
@router.get("/summary")
async def production_output_summary(
    request: Request,
    start_date: Optional[str] = Query(None, description="Inclusive Malaysia calendar date: YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="Inclusive Malaysia calendar date: YYYY-MM-DD"),
    staff: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    production_recipe: Optional[str] = Query(None),
    origin_surface: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    model_key: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    qa_status: Optional[str] = Query(None),
):
    filters = _filters(
        staff,
        media_type,
        production_recipe,
        origin_surface,
        product_id,
        provider,
        model_key,
        status,
        qa_status,
    )
    return await _report(start_date=start_date, end_date=end_date, filters=filters, request=request)


@router.get("/ledger")
async def production_output_ledger(
    request: Request,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    staff: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    production_recipe: Optional[str] = Query(None),
    origin_surface: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    model_key: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    qa_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = _filters(
        staff,
        media_type,
        production_recipe,
        origin_surface,
        product_id,
        provider,
        model_key,
        status,
        qa_status,
    )
    try:
        context = get_current_auth_context() or getattr(request.state, "auth_context", None)
        if context is None:
            raise HTTPException(status_code=401, detail={"error": "AUTHENTICATION_REQUIRED"})
        if not ({"OWNER", "MANAGER"} & set(context.role_codes)):
            requested_staff = str(filters.get("staff") or "").strip()
            if requested_staff and requested_staff != context.staff_id:
                raise HTTPException(status_code=403, detail={"error": "REPORTING_STAFF_SCOPE_DENIED"})
            filters["staff"] = context.staff_id
        return await svc.get_production_ledger(
            start_date=start_date,
            end_date=end_date,
            filters=filters,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
