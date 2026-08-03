"""Copywriting Readiness — ONE shared contract for every generation surface.

Composes existing read models (product-intelligence snapshot + copy grounding +
copy sets + formula registry) into a single readiness payload so generation
surfaces (video / IMG / poster) stop re-deriving or ignoring copywriting
readiness. Read-only; no token spend; no new tables; no migration.
"""
from __future__ import annotations

from typing import Any

from agent.authority.copy_formula_registry import recommend_formula
from agent.db import crud
from agent.models.copy_set import STATUS_COPY_APPROVED, serialize_copy_set
from agent.services.copy_grounding_service import resolve_copy_grounding
from agent.services.copy_set_service import CopySetError
from agent.services.product_intelligence_snapshot_service import (
    get_latest_snapshot_response,
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


async def get_copywriting_readiness(product_id: str) -> dict[str, Any]:
    """The shared readiness payload consumed by useCopywritingReadiness + every
    generation-surface gate. `copy_applicable` defaults True; inherently copy-free
    surfaces (clean-frame IMG / Fastlane) treat it as False on their side."""
    product = await crud.get_product(product_id)
    if not product:
        raise CopySetError(
            "PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": product_id}
        )

    snapshot = await get_latest_snapshot_response(product_id)
    grounding = await resolve_copy_grounding(product)
    rows = await crud.list_copy_sets_for_product(product_id)
    sets = [serialize_copy_set(row) for row in rows]
    approved = [
        s
        for s in sets
        if s.get("status") == STATUS_COPY_APPROVED and not s.get("archived")
    ]

    has_approved_snapshot = snapshot.status == "APPROVED_SNAPSHOT_AVAILABLE"
    pk = grounding.product_knowledge
    persona = grounding.buyer_persona
    product_knowledge_ready = has_approved_snapshot and bool(
        pk.benefits or pk.usps or _clean(pk.description)
    )
    customer_avatar_ready = has_approved_snapshot and bool(
        _clean(persona.audience) and (persona.pains or persona.desires)
    )

    # COPY-FINAL-B01: only VALID current approved sets count for readiness.
    from agent.services.copy_eligibility_service import copy_eligibility
    from agent.services.copy_set_validity_service import product_copy_classification

    eligibility = await copy_eligibility(product_id)
    classification = await product_copy_classification(product_id)
    valid_id = classification.get("valid_copy_set_id")
    latest_approved = next((s for s in approved if s.get("copy_set_id") == valid_id), None)
    selected_copy_set_id = (
        latest_approved.get("copy_set_id") if latest_approved else None
    )
    claim_review = (latest_approved or {}).get("claim_review") or {}
    fv = claim_review.get("formula_validation") or {}
    sc = claim_review.get("sales_clarity") or {}
    if not latest_approved:
        formula_validation_status = "NONE"
        sales_clarity_status = "NONE"
    else:
        formula_validation_status = (
            "PASS"
            if fv.get("valid") and not fv.get("review_required")
            else ("REVIEW_REQUIRED" if fv else "UNKNOWN")
        )
        sales_clarity_status = (
            "CLEAR" if sc.get("clear") else ("GAPS" if sc else "UNKNOWN")
        )

    recommended_formula = recommend_formula(
        is_stealth=grounding.is_stealth, family=grounding.family
    )

    blocking_reasons: list[str] = []
    if not has_approved_snapshot:
        blocking_reasons.append("NO_APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT")
    else:
        if not product_knowledge_ready:
            blocking_reasons.append("PRODUCT_KNOWLEDGE_INCOMPLETE")
        if not customer_avatar_ready:
            blocking_reasons.append("CUSTOMER_AVATAR_INCOMPLETE")
    if classification.get("classification") != "APPROVED_COPY_VALID":
        blocking_reasons.append("NO_VALID_APPROVED_COPY_SET")
        cls = classification.get("classification")
        if cls:
            blocking_reasons.append(str(cls))

    if not eligibility["eligible"]:
        blocking_reasons.extend(
            f"COPY_INELIGIBLE:{reason}" for reason in eligibility["reasons"]
        )

    ready_for_generation = (
        has_approved_snapshot
        and eligibility["eligible"]
        and classification.get("classification") == "APPROVED_COPY_VALID"
        and bool(selected_copy_set_id)
    )

    action_map = {
        "APPROVED_COPY_VALID": "READY",
        "APPROVED_COPY_STALE": "REVALIDATE_COPY_SET",
        "COPY_REVIEW_REQUIRED_ONLY": "REVIEW_COPY_SET",
        "DRAFT_COPY_ONLY": "REVIEW_COPY_SET",
        "REJECTED_COPY_ONLY": "GENERATE_AND_APPROVE_COPY_SET",
        "MISSING_COPY": "GENERATE_AND_APPROVE_COPY_SET",
        "BLOCKED_WITH_REASON": "BLOCKED",
    }
    if not has_approved_snapshot:
        recommended_next_action = "PREPARE_PRODUCT_FOR_COPYWRITING"
    else:
        recommended_next_action = action_map.get(
            classification.get("classification") or "",
            "GENERATE_AND_APPROVE_COPY_SET",
        )

    return {
        "product_id": product_id,
        "product_intelligence_status": snapshot.status,
        "has_approved_snapshot": has_approved_snapshot,
        "product_knowledge_ready": product_knowledge_ready,
        "customer_avatar_ready": customer_avatar_ready,
        "recommended_formula": recommended_formula,
        "selected_copy_set_id": selected_copy_set_id,
        "approved_copy_set_count": len(approved),
        "valid_approved_copy_set_count": (
            1 if classification.get("classification") == "APPROVED_COPY_VALID" else 0
        ),
        "copy_classification": classification.get("classification"),
        "formula_validation_status": formula_validation_status,
        "sales_clarity_status": sales_clarity_status,
        "copy_applicable": True,
        "copy_eligible": eligibility["eligible"],
        "copy_eligibility_reasons": eligibility["reasons"],
        "ready_for_generation": ready_for_generation,
        "blocking_reasons": blocking_reasons,
        "recommended_next_action": recommended_next_action,
    }
