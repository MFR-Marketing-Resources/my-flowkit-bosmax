"""Copy Component API — the per-product authoring surface (Phase B1/B2).

    POST /api/copy-components/author              author N components (the button)
    GET  /api/copy-components/product/{id}        the pool
    GET  /api/copy-components/capacity/{id}       how many copies it can compose
    POST /api/copy-components/{id}/approve        operator gate (never automatic)
    POST /api/copy-components/{id}/reject

`author` spends AI tokens ONLY when dry_run is false, and only on an explicit
call — exactly like the Copy Set generate button. Nothing here fires Google
Flow or spends video credits.
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent.db import crud
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_angle_derivation
from agent.services import copy_component_author_service as author_svc
from agent.services import copy_component_service as pool_svc

router = APIRouter(prefix="/copy-components", tags=["copy-components"])


class AuthorRequest(BaseModel):
    product_id: str
    angle_key: str
    component_type: str
    count: int = Field(default=6, ge=author_svc.MIN_PER_CALL, le=author_svc.MAX_PER_CALL)
    dry_run: bool = False


class ApproveRequest(BaseModel):
    approved_by: str = "operator"


class RejectRequest(BaseModel):
    reviewer_note: str


@router.post("/author")
async def author(request: AuthorRequest):
    """Author components for ONE angle + ONE type. Spends AI tokens unless
    dry_run. Candidates land COMPONENT_REVIEW_REQUIRED — never approved."""
    try:
        return await author_svc.author_components(
            request.product_id,
            request.angle_key,
            request.component_type,
            request.count,
            dry_run=request.dry_run,
        )
    except ai_provider.AICopyProviderNotConfigured as error:
        raise HTTPException(status_code=409, detail={"error": error.code}) from error
    except ai_provider.AICopyProviderError as error:
        raise HTTPException(
            status_code=502, detail={"error": error.code, "detail": error.detail}
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"error": str(error)}) from error


@router.get("/product/{product_id}")
async def list_components(product_id: str):
    items = await crud.list_copy_components_for_product(product_id)
    return {"product_id": product_id, "items": items, "count": len(items)}


@router.get("/capacity/{product_id}")
async def capacity(product_id: str, formula_count: int = 1):
    """How many distinct copies this product's pool can compose right now, plus
    `next_best` — the component type whose next addition unlocks the most.
    Read-only, no tokens."""
    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail={"error": "PRODUCT_NOT_FOUND"})

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    persona = (snap or {}).get("buyer_persona_snapshot_json")
    if isinstance(persona, str):
        try:
            persona = json.loads(persona or "{}")
        except Exception:  # noqa: BLE001
            persona = {}
    derivation = copy_angle_derivation.derive_angles(persona)
    angles = derivation.get("angles") or []

    components = await crud.list_copy_components_for_product(product_id)
    cap = pool_svc.pool_capacity(
        components,
        [a["angle_key"] for a in angles],
        formula_count=max(1, int(formula_count or 1)),
    )
    # Label the angles so the operator sees pains, not hashes.
    labels = {a["angle_key"]: a["label"] for a in angles}
    for entry in cap.get("per_angle", []):
        entry["angle_label"] = labels.get(entry["angle_key"], "")
    if cap.get("next_best"):
        cap["next_best"]["angle_label"] = labels.get(cap["next_best"]["angle_key"], "")

    return {
        "product_id": product_id,
        "angles_derived": bool(derivation.get("derived")),
        "angle_warnings": derivation.get("warnings") or [],
        "component_count": len(components),
        **cap,
    }


@router.get("/coverage/{product_id}")
async def coverage(product_id: str):
    """Phase C2 — angle spread of this product's APPROVED component pool.

    Every other gate in the lane measures sameness (dedupe, near-dup, the
    combination ledger). This is the only one that measures spread, which is why
    a 57-of-58 single-theme batch passed everything. Read-only, no tokens."""
    from agent.services import copy_coverage_service as cov

    product = await crud.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail={"error": "PRODUCT_NOT_FOUND"})

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    persona = (snap or {}).get("buyer_persona_snapshot_json")
    if isinstance(persona, str):
        try:
            persona = json.loads(persona or "{}")
        except Exception:  # noqa: BLE001
            persona = {}
    angles = copy_angle_derivation.derive_angles(persona).get("angles") or []

    components = await crud.list_copy_components_for_product(product_id)
    approved = [c for c in components if c.get("status") == pool_svc.STATUS_APPROVED]
    report = cov.evaluate_coverage(
        approved,
        [a["angle_key"] for a in angles],
        labels={a["angle_key"]: a["label"] for a in angles},
    )
    return {
        "product_id": product_id,
        "pool_total": len(components),
        "pool_approved": len(approved),
        **report,
    }


@router.post("/{component_id}/approve")
async def approve(component_id: str, request: ApproveRequest):
    """Operator approval. Only APPROVED components can ever be composed, so this
    gate is what keeps unreviewed claim-bearing text out of production."""
    row = await crud.get_copy_component(component_id)
    if not row:
        raise HTTPException(status_code=404, detail={"error": "COMPONENT_NOT_FOUND"})
    if str(row.get("status")) == pool_svc.STATUS_APPROVED:
        return row
    from datetime import datetime, timezone

    return await crud.update_copy_component(
        component_id,
        status=pool_svc.STATUS_APPROVED,
        approved_by=request.approved_by,
        approved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


@router.post("/{component_id}/reject")
async def reject(component_id: str, request: RejectRequest):
    row = await crud.get_copy_component(component_id)
    if not row:
        raise HTTPException(status_code=404, detail={"error": "COMPONENT_NOT_FOUND"})
    if not request.reviewer_note.strip():
        raise HTTPException(status_code=422, detail={"error": "REVIEWER_NOTE_REQUIRED"})
    return await crud.update_copy_component(
        component_id,
        status="COMPONENT_REJECTED",
        reviewer_note=request.reviewer_note.strip(),
    )
