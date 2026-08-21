"""Cross-product human review and batch approval for Copy Register V2 drafts.

This module is deliberately a thin orchestration layer over the existing V2
approval authority.  It only reads DRAFT blueprints, applies the claim-safety
and current Product Truth gates, and then calls ``approve_blueprint`` once per
selected blueprint.  It never binds or activates a blueprint and never calls a
provider.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.db.schema import get_db
from agent.models.copy_blueprint_v2 import ProductionReadinessProof, SemanticReviewProof
from agent.services import copy_register_v2_service as v2


BATCH_APPROVAL_CONFIRMATION_PHRASE = "APPROVE_COPY_DRAFTS_BATCH"
# Public alias keeps the phrase easy to share with API/UI callers and tests.
APPROVAL_PHRASE = BATCH_APPROVAL_CONFIRMATION_PHRASE

_REVIEW_REQUIRED_STATUSES = {
    "CLAIM_REVIEW_REQUIRED",
    "CLAIM_SAFE_COPY_REVIEW_REQUIRED",
    "CLAIM_BLOCKED",
    "BLOCKED",
}
_SAFE_COPY_STATUSES = {
    "CLAIM_SAFE",
    "CLAIM_SAFE_COPY_APPROVED",
    "CLAIM_SAFE_COPY_REVIEW_READY",
    "APPROVED",
    "SAFE",
}
_SAFE_RISK_LEVELS = {"", "LOW", "SAFE"}


class CopyRegisterReviewQueueError(ValueError):
    """Stable fail-closed error for the review queue API/service."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: Any = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _claim_blockers(
    claim_safe_copy_status: Any,
    claim_risk_level: Any,
    *,
    truth: dict[str, Any] | None = None,
) -> list[str]:
    """Return claim-safety blockers without ever treating unknown as safe."""

    status = _clean(claim_safe_copy_status).upper()
    risk = _clean(claim_risk_level).upper()
    blockers: list[str] = []
    if status in _REVIEW_REQUIRED_STATUSES:
        blockers.append("CLAIM_SAFETY_REVIEW_REQUIRED")
    elif status and status not in _SAFE_COPY_STATUSES:
        blockers.append("CLAIM_SAFETY_STATUS_NOT_BATCH_SAFE")

    if risk == "HIGH":
        blockers.append("CLAIM_RISK_HIGH")
    elif risk and risk not in _SAFE_RISK_LEVELS:
        blockers.append("CLAIM_RISK_NOT_LOW")

    # Some historical products do not carry the older product-level safe-copy
    # status.  The current V2 Product Truth claim gate is authoritative for that
    # case; only an otherwise-ready truth proof can fill the missing projection.
    if not status and truth and not truth.get("blockers") and risk in _SAFE_RISK_LEVELS:
        return blockers
    if not status:
        blockers.append("CLAIM_SAFETY_STATUS_MISSING")
    return list(dict.fromkeys(blockers))


def _reason_codes(validation: dict[str, Any], claim_blockers: list[str]) -> list[str]:
    reasons: list[str] = []
    raw_reason = _clean(validation.get("reason"))
    if raw_reason:
        reasons.extend(
            code.strip()
            for code in raw_reason.split(",")
            if code.strip() and code.strip() != "EXPLICIT_HUMAN_APPROVAL_REQUIRED"
        )
    reasons.extend(claim_blockers)
    if not validation.get("valid") and not reasons:
        reasons.append("CURRENT_PRODUCT_TRUTH_NOT_READY")
    return list(dict.fromkeys(reasons))


def _row_preview(blueprint: v2.CopyBlueprintV2) -> dict[str, Any]:
    return {
        "angle": blueprint.angle.model_dump(mode="json"),
        "stages": [
            {
                "stage_key": stage.stage_key,
                "formula_stage_key": stage.formula_stage_key,
                "text": stage.authored_text,
                "claim_bearing": stage.claim_bearing,
            }
            for stage in blueprint.stages
        ],
    }


async def _annotate_row(raw: dict[str, Any], blueprint: v2.CopyBlueprintV2) -> dict[str, Any]:
    product_id = str(raw["product_id"])
    try:
        truth = await v2.get_product_truth_proof(product_id)
        validation = v2.get_blueprint_current_authority_validation(blueprint, truth)
    except v2.CopyRegisterV2Error as exc:
        truth = {"blockers": [exc.code], "ready_for_copy": False}
        validation = {
            "status": "CURRENT_PRODUCT_TRUTH_UNAVAILABLE",
            "valid": False,
            "reason": exc.code,
            "mismatches": [],
            "current_fingerprint": None,
            "blueprint_fingerprint": blueprint.product_truth_lineage.taxonomy_authority_fingerprint,
        }

    claim_blockers = _claim_blockers(
        raw.get("claim_safe_copy_status"),
        raw.get("claim_risk_level"),
        truth=truth,
    )
    reasons = _reason_codes(validation, claim_blockers)
    return {
        "blueprint_id": blueprint.blueprint_id,
        "revision": blueprint.revision,
        "product_id": product_id,
        "product_name": _clean(raw.get("product_display_name") or raw.get("raw_product_title")),
        "formula_id": blueprint.formula_id,
        "claim_safe_copy_status": raw.get("claim_safe_copy_status"),
        "claim_risk_level": raw.get("claim_risk_level"),
        "truth_status": validation.get("status"),
        "truth_current": bool(validation.get("valid")),
        "batch_approvable": blueprint.status == "DRAFT" and not reasons,
        "draft_blocked_reason": " · ".join(reasons) if reasons else None,
        "current_authority_reason": validation.get("reason"),
        "current_authority_mismatches": validation.get("mismatches") or [],
        "draft_preview": _row_preview(blueprint),
        "individual_review_path": (
            "/creative/copy-authority?product_id="
            f"{product_id}&blueprint_id={blueprint.blueprint_id}"
        ),
    }


async def list_review_queue(
    *,
    only_claim_safe: bool = False,
    product_id: str | None = None,
) -> dict[str, Any]:
    """List the latest DRAFT revision for every product across the catalog."""

    db = await get_db()
    conditions = ["b.status = 'DRAFT'"]
    params: list[Any] = []
    if product_id:
        conditions.append("b.product_id = ?")
        params.append(product_id)
    where = " AND ".join(conditions)
    cursor = await db.execute(
        f"""
        SELECT b.*, p.product_display_name, p.raw_product_title,
               p.claim_safe_copy_status, p.claim_risk_level
        FROM copy_blueprint_v2 b
        JOIN product p ON p.id = b.product_id
        JOIN (
            SELECT blueprint_id, MAX(revision) AS latest_revision
            FROM copy_blueprint_v2
            GROUP BY blueprint_id
        ) latest
          ON latest.blueprint_id = b.blueprint_id
         AND latest.latest_revision = b.revision
        WHERE {where}
        ORDER BY LOWER(COALESCE(p.product_display_name, p.raw_product_title)),
                 b.created_at, b.blueprint_id
        """,
        params,
    )
    raw_rows = [dict(row) for row in await cursor.fetchall()]
    await cursor.close()

    items: list[dict[str, Any]] = []
    for raw in raw_rows:
        try:
            blueprint = v2._row_to_blueprint(raw)
        except Exception as exc:  # noqa: BLE001 - invalid persistence is fail-closed
            items.append(
                {
                    "blueprint_id": raw.get("blueprint_id"),
                    "revision": raw.get("revision"),
                    "product_id": raw.get("product_id"),
                    "product_name": _clean(raw.get("product_display_name") or raw.get("raw_product_title")),
                    "formula_id": raw.get("formula_id"),
                    "claim_safe_copy_status": raw.get("claim_safe_copy_status"),
                    "claim_risk_level": raw.get("claim_risk_level"),
                    "truth_status": "INVALID_PERSISTED_BLUEPRINT",
                    "truth_current": False,
                    "batch_approvable": False,
                    "draft_blocked_reason": "COPY_V2_BLUEPRINT_INVALID",
                    "current_authority_reason": "COPY_V2_BLUEPRINT_INVALID",
                    "current_authority_mismatches": [],
                    "draft_preview": None,
                    "individual_review_path": None,
                    "error_detail": str(exc),
                }
            )
            continue
        items.append(await _annotate_row(raw, blueprint))

    if only_claim_safe:
        items = [item for item in items if item["batch_approvable"]]
    return {
        "items": items,
        "total": len(items),
        "filters": {
            "only_claim_safe": only_claim_safe,
            "product_id": product_id,
        },
        "provider_calls": 0,
        "credit_spend": 0,
        "activation_mutations": 0,
    }


def _batch_error_code(row: dict[str, Any]) -> str:
    reason = _clean(row.get("draft_blocked_reason")).upper()
    if "CLAIM" in reason:
        return "COPY_V2_CLAIM_SAFETY_BATCH_BLOCKED"
    if "STALE" in reason or "TRUTH" in reason or "AUTHORITY" in reason:
        return "COPY_V2_PRODUCT_TRUTH_STALE"
    return "COPY_V2_BATCH_NOT_APPROVABLE"


async def batch_approve_drafts(
    blueprint_ids: list[str],
    *,
    reviewer: str,
    rationale: str,
    readiness_proof_dict: dict[str, Any] | ProductionReadinessProof,
    confirmation_phrase: str,
) -> dict[str, Any]:
    """Approve an explicit batch of safe, current DRAFT blueprints.

    The preflight is all-or-none: a claim-risk, stale, missing, or non-DRAFT id
    rejects the request before any approval mutation.  Once preflight passes,
    each call remains isolated so a race or per-blueprint validation failure is
    returned as that item's ``FAILED`` result.  No activation is attempted.
    """

    if confirmation_phrase != BATCH_APPROVAL_CONFIRMATION_PHRASE:
        raise CopyRegisterReviewQueueError(
            "INVALID_CONFIRMATION_PHRASE",
            "The exact batch approval confirmation phrase is required.",
            details={"expected": BATCH_APPROVAL_CONFIRMATION_PHRASE},
        )
    reviewer_value = _clean(reviewer)
    rationale_value = _clean(rationale)
    if not reviewer_value:
        raise CopyRegisterReviewQueueError(
            "COPY_V2_REVIEWER_REQUIRED", "A human reviewer identity is required."
        )
    if not rationale_value:
        raise CopyRegisterReviewQueueError(
            "COPY_V2_RATIONALE_REQUIRED", "A human review rationale is required."
        )
    if isinstance(readiness_proof_dict, dict) and any(
        type(value) is not bool for value in readiness_proof_dict.values()
    ):
        raise CopyRegisterReviewQueueError(
            "COPY_V2_READINESS_REQUIRED",
            "The five production readiness gates must be explicit booleans.",
        )
    try:
        readiness = (
            readiness_proof_dict
            if isinstance(readiness_proof_dict, ProductionReadinessProof)
            else ProductionReadinessProof.model_validate(readiness_proof_dict)
        )
    except Exception as exc:  # noqa: BLE001 - normalize the typed proof boundary
        raise CopyRegisterReviewQueueError(
            "COPY_V2_READINESS_REQUIRED",
            "The five production readiness gates must be supplied explicitly.",
            details=str(exc),
        ) from exc
    if not all(readiness.model_dump(mode="python").values()):
        raise CopyRegisterReviewQueueError(
            "COPY_V2_READINESS_REQUIRED",
            "All five production readiness gates must be explicitly proven.",
        )

    ids: list[str] = []
    for blueprint_id in blueprint_ids:
        value = _clean(blueprint_id)
        if value and value not in ids:
            ids.append(value)
    if not ids:
        raise CopyRegisterReviewQueueError(
            "COPY_V2_BATCH_EMPTY", "Select at least one DRAFT blueprint."
        )

    queue = await list_review_queue()
    rows_by_id = {str(item["blueprint_id"]): item for item in queue["items"]}
    invalid: list[dict[str, Any]] = []
    for blueprint_id in ids:
        try:
            blueprint = await v2.get_blueprint(blueprint_id)
        except v2.CopyRegisterV2Error as exc:
            invalid.append(
                {"blueprint_id": blueprint_id, "error_code": exc.code, "detail": str(exc)}
            )
            continue
        if blueprint.status != "DRAFT":
            invalid.append(
                {
                    "blueprint_id": blueprint_id,
                    "error_code": "COPY_V2_BLUEPRINT_NOT_DRAFT",
                    "detail": "Only DRAFT blueprints may enter the batch approval lane.",
                }
            )
            continue
        row = rows_by_id.get(blueprint_id)
        if not row or not row.get("batch_approvable"):
            invalid.append(
                {
                    "blueprint_id": blueprint_id,
                    "error_code": _batch_error_code(row or {}),
                    "detail": (row or {}).get("draft_blocked_reason") or "Blueprint is not batch-approvable.",
                }
            )
            continue
    if invalid:
        raise CopyRegisterReviewQueueError(
            "COPY_V2_BATCH_PREFLIGHT_FAILED",
            "Every selected blueprint must be a current, claim-safe DRAFT.",
            details={"items": invalid},
        )

    semantic_review = SemanticReviewProof(
        decision="APPROVED",
        reviewer=reviewer_value,
        rationale=rationale_value,
        reviewed_at=_now(),
    )
    results: list[dict[str, Any]] = []
    for blueprint_id in ids:
        try:
            approved = await v2.approve_blueprint(
                blueprint_id,
                approved_by=reviewer_value,
                semantic_review=semantic_review,
                readiness_proof=readiness,
            )
            results.append(
                {
                    "blueprint_id": blueprint_id,
                    "status": "APPROVED",
                    "production_status": approved.status,
                    "error_code": None,
                }
            )
        except v2.CopyRegisterV2Error as exc:
            results.append(
                {
                    "blueprint_id": blueprint_id,
                    "status": "FAILED",
                    "production_status": None,
                    "error_code": exc.code,
                    "error_detail": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001 - isolate one approval item
            results.append(
                {
                    "blueprint_id": blueprint_id,
                    "status": "FAILED",
                    "production_status": None,
                    "error_code": "COPY_V2_BATCH_ITEM_FAILED",
                    "error_detail": str(exc),
                }
            )

    approved_count = sum(item["status"] == "APPROVED" for item in results)
    return {
        "results": results,
        "approved_count": approved_count,
        "failed_count": len(results) - approved_count,
        "automatic_approval": False,
        "activation_mutations": 0,
        "provider_calls": 0,
        "credit_spend": 0,
    }


__all__ = [
    "APPROVAL_PHRASE",
    "BATCH_APPROVAL_CONFIRMATION_PHRASE",
    "CopyRegisterReviewQueueError",
    "batch_approve_drafts",
    "list_review_queue",
]
