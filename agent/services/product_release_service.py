"""Owner-governed product release and operational visibility authority.

Product lifecycle, readiness, and staff release are deliberately separate
state machines.  This module is the single server-side resolver used by the
catalog and by active production entry points:

    operationally_visible = RELEASED and current minimum eligibility is clear

The resolver only reads existing Product Truth, visual onboarding, mapping, and
prompt-pipeline authorities.  It never calls a provider and never spends
credits.  HTTP middleware installs an AuthContext before human API handlers;
the no-context compatibility branch is reserved for isolated worker/router
tests and non-HTTP internal calls.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.security.access_control import get_current_auth_context
from agent.services.access_control_service import AuthContext, write_audit_event


HIDDEN = "HIDDEN"
RELEASED = "RELEASED"
RELEASE_ACTION = "RELEASE"
HIDE_ACTION = "HIDE"

OPERATIONAL_PRODUCTION = "OPERATIONAL_PRODUCTION"
AUTHORING_MAINTENANCE = "AUTHORING_MAINTENANCE"
OWNER_RELEASE_CONTROL = "OWNER_RELEASE_CONTROL"
REPORTING_HISTORY = "REPORTING_HISTORY"

_ELIGIBLE = "ELIGIBLE"
_BLOCKED = "BLOCKED"


class ProductReleaseError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = dict(details or {})


class ProductOperationalVisibilityError(ProductReleaseError):
    pass


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if isinstance(parsed, list):
        return [str(item).strip().upper() for item in parsed if str(item).strip()]
    return []


def _release_status(product: Mapping[str, Any]) -> str:
    status = _upper(product.get("staff_release_status"))
    return status if status in {HIDDEN, RELEASED} else HIDDEN


def _production_approval_present(product: Mapping[str, Any]) -> bool:
    status = _upper(product.get("production_prompt_approval_status"))
    modes = _json_list(product.get("production_prompt_approved_modes"))
    return status == "APPROVED" and bool(modes)


def _readiness_blockers(
    product: Mapping[str, Any],
    readiness_report: Mapping[str, Any] | None,
) -> list[str]:
    """Resolve the minimum gate without creating a second readiness engine."""

    blockers: list[str] = []
    lifecycle = _upper(product.get("lifecycle_status") or product.get("status"))
    if lifecycle and lifecycle != "ACTIVE":
        blockers.append("PRODUCT_NOT_ACTIVE")

    mapping_status = _upper(product.get("mapping_status"))
    if mapping_status not in {"READY", "APPROVED"}:
        blockers.append("PRODUCT_MAPPING_NOT_READY")

    truth_status = _upper(product.get("product_truth_status"))
    if truth_status != "APPROVED":
        blockers.append("PRODUCT_INTELLIGENCE_NOT_APPROVED")
    if product.get("product_truth_update_pending"):
        blockers.append("PRODUCT_TRUTH_UPDATE_PENDING")

    visual = product.get("visual_readiness") or {}
    if _upper(visual.get("exact_commerce_status")) != "EXACT_COMMERCE_CUTOUT_READY":
        if _upper(visual.get("canonical_media_status")) != "AVAILABLE":
            blockers.append("VISUAL_SOURCE_MISSING")
        blockers.append("VISUAL_CUTOUT_NOT_READY")

    if readiness_report is not None:
        if not readiness_report.get("production_generation_allowed"):
            report_blockers = readiness_report.get("blockers") or []
            if report_blockers:
                for reason in report_blockers:
                    code = _upper(reason)
                    if code == "TAXONOMY_MISSING":
                        blockers.append("PRODUCT_MAPPING_NOT_READY")
                    elif code == "IMAGE_REFERENCE_MISSING":
                        blockers.append("VISUAL_SOURCE_MISSING")
                    elif code in {"CLAIM_SAFE_COPY_REQUIRED", "CLAIM_REVIEW_REQUIRED_FOR_PRODUCTION"}:
                        blockers.append("COPY_READINESS_NOT_READY")
                    elif code == "PHYSICS_MISSING":
                        blockers.append("PRODUCT_READINESS_NOT_READY")
                    elif code == "PRODUCT_ARCHIVED":
                        blockers.append("PRODUCT_NOT_ACTIVE")
                    else:
                        blockers.append(f"READINESS_{code}")
            else:
                blockers.append("PRODUCT_READINESS_NOT_READY")
    else:
        prompt_status = _upper(product.get("prompt_readiness_status"))
        if prompt_status != "READY":
            blockers.append("PRODUCT_READINESS_NOT_READY")
        claim_gate = _upper(product.get("claim_gate"))
        claim_safe_copy = _upper(product.get("claim_safe_copy_status"))
        if (
            claim_gate not in {"", "CLAIM_SAFE"}
            and claim_safe_copy != "APPROVED"
            and not _production_approval_present(product)
        ):
            blockers.append("COPY_READINESS_NOT_READY")

    # Keep the public blocker list deterministic and free of repeated causes
    # when the catalog projection and the detailed readiness report agree.
    return sorted(set(blockers))


def resolve_product_release_state(
    product: Mapping[str, Any],
    *,
    readiness_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure, context-neutral release + current eligibility projection."""

    status = _release_status(product)
    blocker_codes = _readiness_blockers(product, readiness_report)
    minimum_eligibility = _BLOCKED if blocker_codes else _ELIGIBLE
    operationally_visible = status == RELEASED and not blocker_codes
    if operationally_visible:
        visibility_reason = "VISIBLE_TO_STAFF"
    elif status == RELEASED:
        visibility_reason = "RELEASED_BUT_BLOCKED"
    elif blocker_codes:
        visibility_reason = "HIDDEN_AND_BLOCKED"
    else:
        visibility_reason = "OWNER_RELEASE_REQUIRED"

    return {
        "staff_release_status": status,
        "owner_released": status == RELEASED,
        "minimum_eligibility_status": minimum_eligibility,
        "current_minimum_eligibility": minimum_eligibility == _ELIGIBLE,
        "operationally_visible": operationally_visible,
        "visibility_reason": visibility_reason,
        "blocker_codes": blocker_codes,
        "blockers": blocker_codes,
        "release_history": {
            "released_by_user_id": product.get("released_by_user_id"),
            "released_by_staff_id": product.get("released_by_staff_id"),
            "released_at": product.get("released_at"),
            "hidden_by_user_id": product.get("hidden_by_user_id"),
            "hidden_by_staff_id": product.get("hidden_by_staff_id"),
            "hidden_at": product.get("hidden_at"),
            "release_note": product.get("release_note"),
            "release_updated_at": product.get("release_updated_at"),
        },
    }


async def annotate_product_release_state(
    products: list[dict[str, Any]],
    *,
    attach_truth: bool = True,
    visual_already_attached: bool = False,
) -> None:
    """Attach release state using set-based Product Truth and visual reads.

    This is intentionally called before operational filtering and pagination so
    a 600-row catalog does not become a page-local or N+1 decision.
    """

    if not products:
        return
    ids = [str(item.get("id") or "").strip() for item in products if item.get("id")]
    if attach_truth:
        from agent.services.product_truth_catalog_projection import (
            attach_product_truth_projections,
        )

        approved = await crud.latest_approved_product_intelligence_snapshots_by_products(ids)
        drafts = await crud.latest_actionable_review_drafts_by_products(ids)
        attach_product_truth_projections(
            products,
            approved_by_product=approved,
            drafts_by_product=drafts,
        )
    if not visual_already_attached:
        from agent.services.product_visual_onboarding_service import (
            annotate_products_visual_readiness,
        )

        await annotate_products_visual_readiness(products)
    for product in products:
        product.update(resolve_product_release_state(product))


async def load_product_release_state(product_id: str) -> dict[str, Any]:
    """Load one product through the detailed existing readiness authority."""

    product = await crud.get_product(str(product_id).strip())
    if not product:
        raise ProductReleaseError(
            "PRODUCT_NOT_FOUND",
            f"Product not found: {product_id}",
            status_code=404,
        )
    from agent.services.product_intelligence import enrich_product
    from agent.services.product_visual_onboarding_service import get_product_visual_readiness
    from agent.services.prompt_pipeline_readiness_service import PromptPipelineReadinessService
    from agent.services.product_truth_catalog_projection import (
        attach_product_truth_projections,
    )

    enriched = await enrich_product(product, persist=False)
    ids = [str(product.get("id") or "")]
    approved = await crud.latest_approved_product_intelligence_snapshots_by_products(ids)
    drafts = await crud.latest_actionable_review_drafts_by_products(ids)
    attach_product_truth_projections(
        [enriched], approved_by_product=approved, drafts_by_product=drafts
    )
    try:
        enriched["visual_readiness"] = await get_product_visual_readiness(str(product_id))
    except Exception as exc:  # noqa: BLE001 - resolver must fail closed
        enriched["visual_readiness"] = {
            "canonical_media_status": "MISSING",
            "exact_commerce_status": "EXACT_COMMERCE_BLOCKED",
            "blockers": ["VISUAL_READINESS_UNAVAILABLE"],
            "warnings": [str(exc)],
        }
    report = await PromptPipelineReadinessService.get_readiness_report(enriched)
    state = resolve_product_release_state(enriched, readiness_report=report)
    return {
        "product": enriched,
        "readiness": report,
        **state,
    }


def _require_owner(actor: AuthContext | None) -> AuthContext:
    if actor is None:
        raise ProductReleaseError(
            "AUTHENTICATION_REQUIRED",
            "An authenticated OWNER session is required.",
            status_code=401,
        )
    if "OWNER" not in {str(role).upper() for role in actor.role_codes}:
        raise ProductReleaseError(
            "OWNER_REQUIRED",
            "Only OWNER may release or hide products.",
            status_code=403,
        )
    if "products.release" not in actor.permission_codes:
        raise ProductReleaseError(
            "PERMISSION_DENIED",
            "The authenticated session lacks products.release.",
            status_code=403,
        )
    return actor


async def release_product(
    product_id: str,
    *,
    actor: AuthContext | None,
    note: str | None = None,
) -> dict[str, Any]:
    actor = _require_owner(actor)
    now = crud._now()
    db = await get_db()
    safe_note = str(note or "").strip()[:500] or None
    state: dict[str, Any]
    previous: str
    async with _db_lock:
        # Resolve the complete current product/readiness state while holding the
        # same mutation lock used for the release write.  This closes the stale
        # green-check race without duplicating a weaker raw-row pre-check.
        state = await load_product_release_state(str(product_id))
        previous = state["staff_release_status"]
        if state["minimum_eligibility_status"] != _ELIGIBLE:
            raise ProductReleaseError(
                "PRODUCT_NOT_READY_FOR_RELEASE",
                "Product is not currently eligible for operational release.",
                details={
                    "product_id": product_id,
                    "staff_release_status": state["staff_release_status"],
                    "minimum_eligibility_status": state["minimum_eligibility_status"],
                    "blocker_codes": state["blocker_codes"],
                    "visibility_reason": state["visibility_reason"],
                },
            )
        if previous == RELEASED:
            return {
                "ok": True,
                "action": RELEASE_ACTION,
                "result": "ALREADY_RELEASED",
                **state,
            }
        await db.execute(
            "UPDATE product SET staff_release_status='RELEASED', "
            "released_by_user_id=?, released_by_staff_id=?, released_at=?, "
            "hidden_by_user_id=NULL, hidden_by_staff_id=NULL, hidden_at=NULL, "
            "release_note=?, release_updated_at=?, updated_at=? WHERE id=?",
            (
                actor.user_id,
                actor.staff_id,
                now,
                safe_note,
                now,
                now,
                str(product_id),
            ),
        )
        await write_audit_event(
            db,
            "PRODUCT_RELEASED",
            actor=actor,
            success=True,
            metadata={
                "product_id": str(product_id),
                "previous_status": previous,
                "note": safe_note,
            },
        )
        await db.commit()
    refreshed_state = await load_product_release_state(str(product_id))
    return {
        "ok": True,
        "action": RELEASE_ACTION,
        "result": "RELEASED",
        **refreshed_state,
    }


async def hide_product(
    product_id: str,
    *,
    actor: AuthContext | None,
    note: str | None = None,
) -> dict[str, Any]:
    actor = _require_owner(actor)
    product = await crud.get_product(str(product_id).strip())
    if not product:
        raise ProductReleaseError(
            "PRODUCT_NOT_FOUND", f"Product not found: {product_id}", status_code=404
        )
    previous = _release_status(product)
    if previous == HIDDEN:
        state = resolve_product_release_state(product)
        return {"ok": True, "action": HIDE_ACTION, "result": "ALREADY_HIDDEN", **state}

    now = crud._now()
    db = await get_db()
    safe_note = str(note or "").strip()[:500] or None
    async with _db_lock:
        await db.execute(
            "UPDATE product SET staff_release_status='HIDDEN', "
            "hidden_by_user_id=?, hidden_by_staff_id=?, hidden_at=?, "
            "release_note=?, release_updated_at=?, updated_at=? WHERE id=?",
            (actor.user_id, actor.staff_id, now, safe_note, now, now, str(product_id)),
        )
        await write_audit_event(
            db,
            "PRODUCT_HIDDEN",
            actor=actor,
            success=True,
            metadata={
                "product_id": str(product_id),
                "previous_status": previous,
                "note": safe_note,
            },
        )
        await db.commit()
    refreshed_state = await load_product_release_state(str(product_id))
    return {"ok": True, "action": HIDE_ACTION, "result": "HIDDEN", **refreshed_state}


async def ensure_product_operationally_visible(
    product_id: str,
    *,
    lane: str,
) -> dict[str, Any]:
    """Fail closed for authenticated production requests.

    The access-control middleware always installs a context for external human
    production calls.  Direct router tests and internal non-HTTP workers have
    no context and intentionally retain their pre-existing provider-free test
    seam; they do not constitute an externally reachable permission bypass.
    """

    if get_current_auth_context() is None:
        return {"product_id": str(product_id), "operationally_visible": True, "internal_call": True}
    state = await load_product_release_state(product_id)
    if not state["operationally_visible"]:
        raise ProductOperationalVisibilityError(
            "PRODUCT_NOT_OPERATIONALLY_VISIBLE",
            "Product is hidden or currently blocked for operational production.",
            details={
                "product_id": str(product_id),
                "lane": lane,
                "staff_release_status": state["staff_release_status"],
                "minimum_eligibility_status": state["minimum_eligibility_status"],
                "visibility_reason": state["visibility_reason"],
                "blocker_codes": state["blocker_codes"],
            },
        )
    return state


async def require_product_operational_visibility(
    product_id: str,
    *,
    lane: str,
) -> dict[str, Any]:
    """Context-independent release/readiness assertion for workers and sinks."""
    normalized_product_id = str(product_id or "").strip()
    if not normalized_product_id:
        raise ProductOperationalVisibilityError(
            "PRODUCT_ID_REQUIRED",
            "A canonical product identity is required before operational dispatch.",
            details={"lane": lane},
        )
    state = await load_product_release_state(normalized_product_id)
    if not state.get("operationally_visible"):
        raise ProductOperationalVisibilityError(
            "PRODUCT_NOT_OPERATIONALLY_VISIBLE",
            "Product is hidden or currently blocked for operational production.",
            details={
                "product_id": normalized_product_id,
                "lane": lane,
                "staff_release_status": state.get("staff_release_status"),
                "minimum_eligibility_status": state.get("minimum_eligibility_status"),
                "visibility_reason": state.get("visibility_reason"),
                "blocker_codes": state.get("blocker_codes") or [],
            },
        )
    return state


async def ensure_products_operationally_visible(
    product_ids: Iterable[str],
    *,
    lane: str,
) -> list[dict[str, Any]]:
    ids = [
        str(product_id).strip()
        for product_id in product_ids
        if product_id is not None and str(product_id).strip()
    ]
    if get_current_auth_context() is None:
        return [{"product_id": product_id, "operationally_visible": True, "internal_call": True} for product_id in ids]
    results: list[dict[str, Any]] = []
    for product_id in ids:
        results.append(await ensure_product_operationally_visible(product_id, lane=lane))
    return results


async def bulk_update_products(
    product_ids: Iterable[str],
    *,
    action: str,
    actor: AuthContext | None,
    note: str | None = None,
) -> dict[str, Any]:
    actor = _require_owner(actor)
    ids = list(
        dict.fromkeys(
            str(product_id).strip()
            for product_id in product_ids
            if product_id is not None and str(product_id).strip()
        )
    )
    if not ids or len(ids) > 200:
        raise ProductReleaseError(
            "PRODUCT_RELEASE_BULK_LIMIT",
            "Provide between 1 and 200 product ids.",
            status_code=422,
        )
    normalized_action = _upper(action)
    if normalized_action not in {RELEASE_ACTION, HIDE_ACTION}:
        raise ProductReleaseError(
            "PRODUCT_RELEASE_ACTION_INVALID",
            "Action must be RELEASE or HIDE.",
            status_code=422,
        )
    results: list[dict[str, Any]] = []
    for product_id in ids:
        try:
            result = (
                await release_product(product_id, actor=actor, note=note)
                if normalized_action == RELEASE_ACTION
                else await hide_product(product_id, actor=actor, note=note)
            )
            results.append({"product_id": product_id, "ok": True, **result})
        except ProductReleaseError as exc:
            results.append(
                {
                    "product_id": product_id,
                    "ok": False,
                    "error": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            )
    return {
        "ok": all(bool(item.get("ok")) for item in results),
        "action": normalized_action,
        "total": len(results),
        "succeeded": sum(1 for item in results if item.get("ok")),
        "failed": sum(1 for item in results if not item.get("ok")),
        "results": results,
    }
