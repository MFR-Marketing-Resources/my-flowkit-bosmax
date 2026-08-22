"""Owner-only Product Release Control API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from agent.db import crud
from agent.security.access_control import get_current_auth_context
from agent.services import product_release_service as release


router = APIRouter(prefix="/product-release", tags=["product-release"])


class ProductReleaseActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ProductReleaseBulkRequest(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=200)
    action: str
    note: str | None = Field(default=None, max_length=500)


def _http(exc: release.ProductReleaseError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message, "details": exc.details},
    )


def _require_owner() -> Any:
    actor = get_current_auth_context()
    if actor is None:
        raise _http(
            release.ProductReleaseError(
                "AUTHENTICATION_REQUIRED",
                "An authenticated OWNER session is required.",
                status_code=401,
            )
        )
    if "OWNER" not in {str(role).upper() for role in actor.role_codes}:
        raise _http(
            release.ProductReleaseError(
                "OWNER_REQUIRED",
                "Only OWNER may view or mutate Product Release Control.",
                status_code=403,
            )
        )
    if "products.release" not in actor.permission_codes:
        raise _http(
            release.ProductReleaseError(
                "PERMISSION_DENIED",
                "The authenticated session lacks products.release.",
                status_code=403,
            )
        )
    return actor


def _matches_query(row: dict[str, Any], query: str | None) -> bool:
    needle = str(query or "").strip().casefold()
    if not needle:
        return True
    return any(
        needle in str(row.get(field) or "").casefold()
        for field in (
            "id",
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "brand",
            "source",
        )
    )


async def _release_control_rows() -> list[dict[str, Any]]:
    """Build the owner grid with bounded set-based readiness reads."""

    from agent.api.products import _build_catalog_projection
    from agent.services.product_truth_catalog_projection import (
        attach_product_truth_projections,
    )

    raw_products = await crud.list_products(include_archived=True, limit=5000)
    rows = [
        _build_catalog_projection(
            product,
            include_reconciliation=True,
            include_sales_metrics=False,
        )
        for product in raw_products
    ]
    ids = [str(row.get("id") or "") for row in rows if row.get("id")]
    approved = await crud.latest_approved_product_intelligence_snapshots_by_products(ids)
    drafts = await crud.latest_actionable_review_drafts_by_products(ids)
    attach_product_truth_projections(
        rows,
        approved_by_product=approved,
        drafts_by_product=drafts,
    )
    await release.annotate_product_release_state(
        rows,
        attach_truth=False,
    )
    return rows


@router.get("")
async def list_product_release_control(
    q: str | None = Query(default=None, max_length=200),
    release_status: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    eligibility: str | None = Query(default=None),
    blocker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    _require_owner()
    rows = [row for row in await _release_control_rows() if _matches_query(row, q)]
    status_filter = str(release_status or "").strip().upper()
    visibility_filter = str(visibility or "").strip().upper()
    eligibility_filter = str(eligibility or "").strip().upper()
    blocker_filter = str(blocker or "").strip().upper()
    if status_filter in {release.HIDDEN, release.RELEASED}:
        rows = [row for row in rows if row.get("staff_release_status") == status_filter]
    if visibility_filter:
        rows = [row for row in rows if str(row.get("visibility_reason") or "").upper() == visibility_filter]
    if eligibility_filter in {"ELIGIBLE", "BLOCKED"}:
        rows = [row for row in rows if row.get("minimum_eligibility_status") == eligibility_filter]
    if blocker_filter:
        rows = [row for row in rows if blocker_filter in set(row.get("blocker_codes") or [])]
    rows.sort(
        key=lambda row: str(
            row.get("product_short_name")
            or row.get("product_display_name")
            or row.get("raw_product_title")
            or row.get("id")
        ).casefold()
    )
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "total_count": total,
        "returned_count": len(page),
        "has_pagination": offset + len(page) < total,
        "limit": limit,
        "offset": offset,
        "items": page,
        "summary": {
            "hidden": sum(row.get("staff_release_status") == release.HIDDEN for row in rows),
            "released": sum(row.get("staff_release_status") == release.RELEASED for row in rows),
            "visible_to_staff": sum(bool(row.get("operationally_visible")) for row in rows),
            "released_but_blocked": sum(row.get("visibility_reason") == "RELEASED_BUT_BLOCKED" for row in rows),
            "eligible_to_release": sum(
                row.get("minimum_eligibility_status") == "ELIGIBLE" for row in rows
            ),
        },
    }


@router.get("/{product_id}")
async def get_product_release_control(product_id: str) -> dict[str, Any]:
    _require_owner()
    try:
        return await release.load_product_release_state(product_id)
    except release.ProductReleaseError as exc:
        raise _http(exc) from exc


@router.post("/{product_id}/release")
async def release_one(product_id: str, body: ProductReleaseActionRequest):
    actor = _require_owner()
    try:
        return await release.release_product(product_id, actor=actor, note=body.note)
    except release.ProductReleaseError as exc:
        raise _http(exc) from exc


@router.post("/{product_id}/hide")
async def hide_one(product_id: str, body: ProductReleaseActionRequest):
    actor = _require_owner()
    try:
        return await release.hide_product(product_id, actor=actor, note=body.note)
    except release.ProductReleaseError as exc:
        raise _http(exc) from exc


@router.post("/bulk")
async def bulk_release_control(body: ProductReleaseBulkRequest):
    actor = _require_owner()
    try:
        return await release.bulk_update_products(
            body.product_ids,
            action=body.action,
            actor=actor,
            note=body.note,
        )
    except release.ProductReleaseError as exc:
        raise _http(exc) from exc
