"""P7 durable creative-supply orchestration and review authority.

The factory fills only measured component deficits. It reuses the canonical
``text_assist`` component author and deterministic composer, but adds the
mission-critical control plane they intentionally do not own: a 120-call hard
ceiling, durable pause/resume, explicit transient-only retry, exact review
lineage, and product/angle/type capacity readback.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from agent.db import creative_supply_crud as supply_db
from agent.db import crud
from agent.models.copy_set import APPROVAL_PHRASE, STATUS_COPY_APPROVED, serialize_copy_set
from agent.models.creative_asset import CreativeAssetCreateRequest, CreativeAssetUpdateRequest
from agent.models.creative_production import P58_COHORT_SHA256
from agent.services import ai_copy_provider_adapter as ai_provider
from agent.services import copy_angle_derivation
from agent.services import copy_component_author_service as author_service
from agent.services import copy_component_service
from agent.services import copy_composer_service
from agent.services import copy_set_service as copy_set_registry_service
from agent.services import creative_asset_service
from agent.services import production_queue_service
from agent.services.copy_grounding_service import resolve_copy_grounding
from agent.services.copy_set_service import scan_copy_safety
from agent.services.flow_client import get_flow_client

COMPONENT_ORDER = ("HOOK", "SUBHOOK", "USP_SET", "CTA")
ACTIVE_TASK_STATES = {"PENDING", "RUNNING", "REVIEW_REQUIRED", "RETRY_ELIGIBLE"}
FINAL_FAILURE_STATES = {"FAILED", "BLOCKED"}
TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
DEFAULT_REVIEWER_ID = "codex-p7-reviewer"
P7_ANCHOR_UPLOAD_CONFIRMATION = "UPLOAD_P7_ANCHOR_TO_FLOW_ZERO_CREDIT"


class CreativeSupplyError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    text = value if isinstance(value, str) else stable_json(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_sha256(component: dict[str, Any]) -> str:
    return sha256(str(component.get("content") or ""))


def _json(value: Any, fallback: Any) -> Any:
    if isinstance(value, type(fallback)):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _slot_fields(component: dict[str, Any]) -> dict[str, Any]:
    ctype = str(component.get("component_type") or "")
    content = str(component.get("content") or "")
    if ctype == "USP_SET":
        return {"usp_set": _json(content, [content] if content else [])}
    field = {"HOOK": "hook", "SUBHOOK": "subhook", "CTA": "cta"}.get(ctype)
    return {field: content} if field else {}


def _task_idempotency_key(
    run_id: str,
    product_id: str,
    angle_key: str,
    component_type: str,
    deficit_round: int,
    target: int,
    task_kind: str = "AUTHOR_DEFICIT",
) -> str:
    return sha256(
        {
            "run_id": run_id,
            "product_id": product_id,
            "angle_key": angle_key,
            "component_type": component_type,
            "deficit_round": deficit_round,
            "target": target,
            "task_kind": task_kind,
        }
    )


def _role_targets(target_policy: dict[str, Any], role: str) -> dict[str, int]:
    raw = target_policy.get(role) or {}
    targets = {
        component_type: int((raw.get("components") or {}).get(component_type) or 0)
        for component_type in COMPONENT_ORDER
    }
    if any(value < 1 or value > 12 for value in targets.values()):
        raise CreativeSupplyError(
            "INVALID_COMPONENT_TARGET",
            f"Every {role} component target must be between 1 and 12.",
            details={"role": role, "targets": targets},
        )
    return targets


def _approved_count(
    components: list[dict[str, Any]], angle_key: str, component_type: str
) -> int:
    return sum(
        1
        for component in components
        if str(component.get("status") or "") == copy_component_service.STATUS_APPROVED
        and not int(component.get("archived") or 0)
        and str(component.get("component_type") or "") == component_type
        and str(component.get("angle_key") or "") in ("", angle_key)
    )


async def _validate_scope(
    roster: list[dict[str, Any]], angle_plan: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    if len(roster) != 10:
        raise CreativeSupplyError(
            "TOP10_ROSTER_REQUIRED",
            "The P7 factory requires exactly ten frozen products.",
            details={"actual_count": len(roster)},
        )
    product_ids = [str(item.get("product_id") or "").strip() for item in roster]
    if len(set(product_ids)) != 10 or any(not product_id for product_id in product_ids):
        raise CreativeSupplyError("INVALID_ROSTER", "Roster product ids must be non-empty and unique.")
    hero_count = sum(1 for item in roster if str(item.get("role") or "") == "HERO")
    if hero_count != 2:
        raise CreativeSupplyError(
            "TWO_HERO_PRODUCTS_REQUIRED",
            "The frozen roster must contain exactly two HERO products.",
        )

    from agent.services.creative_production_plan_service import load_p58_cohort_authority

    authority = await load_p58_cohort_authority()
    if not authority.matches_frozen_authority or authority.cohort_sha256 != P58_COHORT_SHA256:
        raise CreativeSupplyError(
            "P58_COHORT_AUTHORITY_DRIFT",
            "Current catalog authority no longer matches the frozen P5.8 cohort.",
            status_code=409,
            details={
                "expected": P58_COHORT_SHA256,
                "actual": authority.cohort_sha256,
                "count": authority.cohort_count,
            },
        )
    outside = sorted(set(product_ids) - set(authority.product_ids))
    if outside:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_P58_COHORT",
            "Every P7 product must remain inside the frozen P5.8 cohort.",
            status_code=409,
            details={"product_ids": outside},
        )

    angles_by_product: dict[str, list[dict[str, Any]]] = {product_id: [] for product_id in product_ids}
    for planned in angle_plan:
        product_id = str(planned.get("product_id") or "").strip()
        if product_id not in angles_by_product:
            raise CreativeSupplyError(
                "ANGLE_PRODUCT_OUTSIDE_ROSTER",
                "Every planned angle must belong to the frozen roster.",
                details={"product_id": product_id},
            )
        angles_by_product[product_id].append(planned)

    for item in roster:
        product_id = str(item["product_id"])
        product = await crud.get_product(product_id)
        snapshot = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
        if not product or not snapshot:
            raise CreativeSupplyError(
                "PRODUCT_TRUTH_NOT_APPROVED",
                "Every P7 product needs an approved Product Intelligence snapshot.",
                details={"product_id": product_id},
            )
        persona = _json(snapshot.get("buyer_persona_snapshot_json"), {})
        derived = copy_angle_derivation.derive_angles(persona).get("angles") or []
        by_key = {str(angle.get("angle_key") or ""): angle for angle in derived}
        required = 4 if str(item.get("role") or "") == "HERO" else 2
        planned = angles_by_product[product_id]
        if len(planned) < required:
            raise CreativeSupplyError(
                "INSUFFICIENT_EVIDENCE_BACKED_ANGLES",
                f"{item.get('role')} product requires at least {required} approved angles.",
                details={"product_id": product_id, "actual": len(planned)},
            )
        if len({str(angle.get("angle_key") or "") for angle in planned}) != len(planned):
            raise CreativeSupplyError(
                "DUPLICATE_ANGLE_KEY",
                "Planned angles must be unique per product.",
                details={"product_id": product_id},
            )
        unknown = [
            str(angle.get("angle_key") or "")
            for angle in planned
            if str(angle.get("angle_key") or "") not in by_key
        ]
        if unknown:
            raise CreativeSupplyError(
                "ANGLE_NOT_DERIVED_FROM_APPROVED_PERSONA",
                "P7 cannot author against an invented or stale angle.",
                details={"product_id": product_id, "angle_keys": unknown},
            )
        for angle in planned:
            canonical = by_key[str(angle["angle_key"])]
            supplied_label = str(angle.get("angle_label") or angle.get("label") or "")
            if supplied_label and supplied_label != str(canonical.get("label") or ""):
                raise CreativeSupplyError(
                    "ANGLE_LABEL_AUTHORITY_MISMATCH",
                    "Planned angle label does not match approved persona derivation.",
                    details={"product_id": product_id, "angle_key": angle["angle_key"]},
                )
            angle["angle_label"] = str(canonical.get("label") or "")
    return angles_by_product


async def create_run(
    *,
    mission_id: str,
    roster: list[dict[str, Any]],
    angle_plan: list[dict[str, Any]],
    target_policy: dict[str, Any],
    provider_budget_max: int = 120,
    reviewer_id: str = DEFAULT_REVIEWER_ID,
) -> dict[str, Any]:
    if not mission_id.strip():
        raise CreativeSupplyError("MISSION_ID_REQUIRED", "A stable mission id is required.")
    if not reviewer_id.strip():
        raise CreativeSupplyError("REVIEWER_ID_REQUIRED", "A stable reviewer id is required.")
    if provider_budget_max < 1 or provider_budget_max > 120:
        raise CreativeSupplyError(
            "PROVIDER_BUDGET_OUT_OF_RANGE",
            "P7 text-provider budget must be between 1 and 120 calls.",
        )
    angles_by_product = await _validate_scope(roster, angle_plan)
    for role in ("HERO", "TOP10"):
        _role_targets(target_policy, role)

    run = await supply_db.create_run(
        mission_id=mission_id,
        roster_sha256=sha256(roster),
        cohort_sha256=P58_COHORT_SHA256,
        roster=roster,
        angle_plan=angle_plan,
        target_policy=target_policy,
        provider_budget_max=provider_budget_max,
        reviewer_id=reviewer_id.strip(),
    )

    provider_task_count = 0
    for item in roster:
        product_id = str(item["product_id"])
        role = str(item.get("role") or "TOP10")
        targets = _role_targets(target_policy, role)
        components = await crud.list_copy_components_for_product(product_id)
        scheduled_audit_ids: set[str] = set()
        for angle in angles_by_product[product_id]:
            angle_key = str(angle["angle_key"])
            angle_label = str(angle.get("angle_label") or "")
            for component_type in COMPONENT_ORDER:
                target = targets[component_type]
                legacy_candidates = [
                    component
                    for component in components
                    if str(component.get("status") or "")
                    == copy_component_service.STATUS_APPROVED
                    and not int(component.get("archived") or 0)
                    and str(component.get("component_type") or "") == component_type
                    and str(component.get("angle_key") or "") in ("", angle_key)
                    and str(component.get("component_id") or "") not in scheduled_audit_ids
                ]
                if legacy_candidates:
                    component_ids = [
                        str(component["component_id"]) for component in legacy_candidates
                    ]
                    for component in legacy_candidates:
                        scheduled_audit_ids.add(str(component["component_id"]))
                        provenance = _json(component.get("provenance_json"), {})
                        provenance["p7_legacy_revalidation"] = {
                            "run_id": str(run["run_id"]),
                            "previous_status": copy_component_service.STATUS_APPROVED,
                            "previous_approved_by": component.get("approved_by"),
                            "previous_approved_at": component.get("approved_at"),
                        }
                        await crud.update_copy_component(
                            str(component["component_id"]),
                            status=author_service.STATUS_REVIEW_REQUIRED,
                            provenance_json=stable_json(provenance),
                            reviewer_note="P7 legacy approval revalidation required.",
                        )
                    await supply_db.create_task(
                        run_id=str(run["run_id"]),
                        product_id=product_id,
                        angle_key=angle_key,
                        angle_label=angle_label,
                        component_type=component_type,
                        task_kind="LEGACY_AUDIT",
                        deficit_round=0,
                        target_approved_count=target,
                        requested_count=0,
                        idempotency_key=_task_idempotency_key(
                            str(run["run_id"]),
                            product_id,
                            angle_key,
                            component_type,
                            0,
                            target,
                            "LEGACY_AUDIT",
                        ),
                        state="REVIEW_REQUIRED",
                        result={
                            "component_ids": component_ids,
                            "legacy_revalidation": True,
                            "provider_calls": 0,
                        },
                    )
                    continue
                deficit = target - _approved_count(components, angle_key, component_type)
                if deficit <= 0:
                    continue
                await supply_db.create_task(
                    run_id=str(run["run_id"]),
                    product_id=product_id,
                    angle_key=angle_key,
                    angle_label=angle_label,
                    component_type=component_type,
                    deficit_round=1,
                    target_approved_count=target,
                    requested_count=max(2, min(author_service.MAX_PER_CALL, deficit)),
                    idempotency_key=_task_idempotency_key(
                        str(run["run_id"]),
                        product_id,
                        angle_key,
                        component_type,
                        1,
                        target,
                    ),
                )
                provider_task_count += 1
    if provider_task_count > provider_budget_max:
        await supply_db.update_run(
            str(run["run_id"]),
            state="BLOCKED",
            last_error=(
                f"INITIAL_TASKS_EXCEED_PROVIDER_BUDGET:"
                f"{provider_task_count}/{provider_budget_max}"
            ),
        )
        raise CreativeSupplyError(
            "INITIAL_TASKS_EXCEED_PROVIDER_BUDGET",
            "The measured initial deficit cannot fit the authorized call ceiling.",
            status_code=409,
            details={"required_calls": provider_task_count, "budget": provider_budget_max},
        )
    return await status(str(run["run_id"]))


def _proven_transient(error: Exception) -> bool:
    if not isinstance(error, ai_provider.AICopyProviderError):
        return False
    if error.http_status in TRANSIENT_HTTP_STATUSES:
        return True
    diagnostic = str(error.diagnostic_category or "").upper()
    detail = str(error.detail or "").upper()
    return any(token in f"{diagnostic}:{detail}" for token in ("TIMEOUT", "CONNECT", "TEMPORAR"))


async def step(run_id: str) -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    if str(run.get("state")) == "PAUSED":
        raise CreativeSupplyError("RUN_PAUSED", "Resume the run before authoring.", status_code=409)
    if str(run.get("state")) in {"COMPLETED", "CANCELLED", "BLOCKED"}:
        raise CreativeSupplyError(
            "RUN_NOT_EXECUTABLE",
            f"Run state {run.get('state')} cannot author another task.",
            status_code=409,
        )
    task = await supply_db.claim_next_pending_task(run_id)
    if not task:
        return await status(run_id)
    if int(run.get("provider_calls_used") or 0) >= int(run.get("provider_budget_max") or 0):
        await supply_db.update_run(
            run_id, state="BLOCKED", last_error="PROVIDER_BUDGET_EXHAUSTED"
        )
        raise CreativeSupplyError(
            "PROVIDER_BUDGET_EXHAUSTED",
            "No authorized text-provider calls remain.",
            status_code=409,
        )

    components = await crud.list_copy_components_for_product(str(task["product_id"]))
    approved = _approved_count(
        components, str(task["angle_key"]), str(task["component_type"])
    )
    if approved >= int(task["target_approved_count"]):
        await supply_db.update_task(str(task["task_id"]), state="COMPLETED")
        return await status(run_id)

    requested = max(
        2,
        min(
            author_service.MAX_PER_CALL,
            int(task["target_approved_count"]) - approved,
        ),
    )
    await supply_db.update_run(run_id, state="RUNNING", last_error=None)
    before = ai_provider.provider_call_receipt()
    try:
        result = await author_service.author_components(
            str(task["product_id"]),
            str(task["angle_key"]),
            str(task["component_type"]),
            requested,
            dry_run=False,
        )
    except Exception as error:
        after = ai_provider.provider_call_receipt()
        delta = max(
            0,
            int(after.get("request_count_since_process_start") or 0)
            - int(before.get("request_count_since_process_start") or 0),
        )
        if delta:
            await supply_db.increment_provider_calls(run_id, delta)
        transient = _proven_transient(error)
        await supply_db.update_task(
            str(task["task_id"]),
            state=(
                "RETRY_ELIGIBLE"
                if transient and int(task.get("attempt_count") or 0) < 2
                else "FAILED"
            ),
            provider_call_count=int(task.get("provider_call_count") or 0) + delta,
            transient_failure_proven=1 if transient else 0,
            provider_receipt_json=supply_db.encode(after),
            last_error=f"{type(error).__name__}:{error}",
        )
        await supply_db.update_run(
            run_id,
            state="RUNNING",
            last_error=f"TASK_FAILED:{task['task_id']}:{type(error).__name__}:{error}",
        )
        return await status(run_id)

    after = ai_provider.provider_call_receipt()
    delta = max(
        0,
        int(after.get("request_count_since_process_start") or 0)
        - int(before.get("request_count_since_process_start") or 0),
    )
    if delta != 1:
        await supply_db.update_task(
            str(task["task_id"]),
            state="BLOCKED",
            provider_receipt_json=supply_db.encode(after),
            result_json=supply_db.encode(result),
            last_error=f"PROVIDER_RECEIPT_DELTA_INVALID:{delta}",
        )
        await supply_db.update_run(
            run_id, state="BLOCKED", last_error=f"PROVIDER_RECEIPT_DELTA_INVALID:{delta}"
        )
        return await status(run_id)
    await supply_db.increment_provider_calls(run_id, 1)
    item_ids = [str(item.get("component_id") or "") for item in result.get("items") or []]
    result_record = {
        "requested_count": requested,
        "created_count": int(result.get("created_count") or 0),
        "deduped_count": int(result.get("deduped_count") or 0),
        "rejected_count": int(result.get("rejected_count") or 0),
        "component_ids": [component_id for component_id in item_ids if component_id],
        "warnings": result.get("warnings") or [],
    }
    next_state = "REVIEW_REQUIRED" if result_record["component_ids"] else "COMPLETED"
    await supply_db.update_task(
        str(task["task_id"]),
        state=next_state,
        provider_call_count=int(task.get("provider_call_count") or 0) + 1,
        provider_receipt_json=supply_db.encode(after),
        result_json=supply_db.encode(result_record),
    )
    if next_state == "COMPLETED":
        await _create_deficit_round_if_needed(str(task["task_id"]))
    return await status(run_id)


async def retry_transient(task_id: str) -> dict[str, Any]:
    task = await supply_db.get_task(task_id)
    if not task:
        raise CreativeSupplyError("TASK_NOT_FOUND", "Creative-supply task not found.", status_code=404)
    if (
        str(task.get("state")) != "RETRY_ELIGIBLE"
        or not int(task.get("transient_failure_proven") or 0)
        or int(task.get("attempt_count") or 0) >= 2
    ):
        raise CreativeSupplyError(
            "RETRY_NOT_AUTHORIZED",
            "Only one explicit retry is allowed after a proven transient transport failure.",
            status_code=409,
        )
    await supply_db.update_task(task_id, state="PENDING")
    return await status(str(task["run_id"]))


async def requeue_unsubmitted(task_id: str) -> dict[str, Any]:
    """Requeue a task that failed before the provider boundary.

    This is not a retry: no HTTP request was counted and no provider output
    existed. It is limited to the fail-closed configuration error so low-quality,
    unsafe, duplicate, refused, and schema-valid responses can never use it.
    """
    task = await supply_db.get_task(task_id)
    if not task:
        raise CreativeSupplyError("TASK_NOT_FOUND", "Creative-supply task not found.", status_code=404)
    if (
        str(task.get("state")) != "FAILED"
        or int(task.get("provider_call_count") or 0) != 0
        or "AICopyProviderNotConfigured" not in str(task.get("last_error") or "")
    ):
        raise CreativeSupplyError(
            "UNSUBMITTED_REQUEUE_NOT_AUTHORIZED",
            "Only a configuration failure with zero provider calls may be requeued.",
            status_code=409,
        )
    await supply_db.update_task(
        task_id,
        state="PENDING",
        attempt_count=0,
        transient_failure_proven=0,
        last_error=None,
    )
    return await status(str(task["run_id"]))


async def reconcile_interrupted_running_task(
    task_id: str, evidence_reason: str
) -> dict[str, Any]:
    """Conservatively close a process-interrupted task.

    A killed process can lose the in-memory receipt after HTTP submission. The
    call is therefore charged against the mission ceiling even when billing
    cannot be proven, and any remaining slot is represented by a new deficit
    round rather than rewriting or retrying the interrupted task.
    """
    task = await supply_db.get_task(task_id)
    if not task:
        raise CreativeSupplyError("TASK_NOT_FOUND", "Creative-supply task not found.", status_code=404)
    if str(task.get("state")) != "RUNNING":
        raise CreativeSupplyError(
            "TASK_NOT_RUNNING",
            "Only an interrupted RUNNING task can be reconciled.",
            status_code=409,
        )
    if not evidence_reason.strip():
        raise CreativeSupplyError(
            "INTERRUPTION_EVIDENCE_REQUIRED",
            "Interrupted task reconciliation requires an evidence reason.",
        )
    run = await supply_db.get_run(str(task["run_id"]))
    if not run or int(run.get("provider_calls_used") or 0) >= int(
        run.get("provider_budget_max") or 0
    ):
        raise CreativeSupplyError(
            "PROVIDER_BUDGET_EXHAUSTED",
            "The interrupted call cannot be conservatively charged inside the ceiling.",
            status_code=409,
        )
    await supply_db.increment_provider_calls(str(task["run_id"]), 1)
    await supply_db.update_task(
        task_id,
        state="COMPLETED",
        provider_call_count=int(task.get("provider_call_count") or 0) + 1,
        provider_receipt_json=supply_db.encode(
            {
                "receipt_status": "PROCESS_INTERRUPTED_RECEIPT_UNAVAILABLE",
                "conservative_billable_count": 1,
                "evidence_reason": evidence_reason.strip(),
            }
        ),
        result_json=supply_db.encode(
            {
                "component_ids": [],
                "warnings": ["PROCESS_INTERRUPTED_OUTPUT_UNAVAILABLE"],
            }
        ),
        last_error=f"PROCESS_INTERRUPTED:{evidence_reason.strip()}",
    )
    await supply_db.update_run(
        str(task["run_id"]),
        state="RUNNING",
        last_error=f"INTERRUPTED_TASK_RECONCILED:{task_id}",
    )
    await _create_deficit_round_if_needed(task_id)
    return await status(str(task["run_id"]))


async def control(run_id: str, action: str, reason: str = "") -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    normalized = action.strip().upper()
    if normalized == "PAUSE":
        if not reason.strip():
            raise CreativeSupplyError("PAUSE_REASON_REQUIRED", "Pause requires an evidence reason.")
        await supply_db.update_run(run_id, state="PAUSED", pause_reason=reason.strip())
    elif normalized == "RESUME":
        if str(run.get("state")) != "PAUSED":
            raise CreativeSupplyError("RUN_NOT_PAUSED", "Only a paused run can resume.", status_code=409)
        await supply_db.update_run(run_id, state="RUNNING", pause_reason=None)
    else:
        raise CreativeSupplyError("UNKNOWN_CONTROL_ACTION", "Action must be PAUSE or RESUME.")
    return await status(run_id)


async def register_manual_remediation(
    *,
    run_id: str,
    product_id: str,
    angle_key: str,
    component_type: str,
    contents: list[Any],
    authored_by: str,
) -> dict[str, Any]:
    """Register zero-provider, Product-Truth-grounded candidates for review.

    Manual candidates use the existing review-only task class because it has
    identical economics: zero provider calls and mandatory SHA-bound review.
    Provenance distinguishes manual remediation from legacy revalidation.
    """
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    if not authored_by.strip():
        raise CreativeSupplyError("AUTHOR_ID_REQUIRED", "Manual remediation requires an author id.")
    ctype = component_type.strip().upper()
    if ctype not in COMPONENT_ORDER:
        raise CreativeSupplyError("UNKNOWN_COMPONENT_TYPE", "Unknown component type.")
    if not contents or len(contents) > 12:
        raise CreativeSupplyError(
            "MANUAL_CONTENT_COUNT_OUT_OF_RANGE",
            "Manual remediation requires 1..12 reviewed candidate values.",
        )
    roster_by_id = {
        str(item.get("product_id") or ""): item for item in run.get("roster") or []
    }
    if product_id not in roster_by_id:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_RUN_ROSTER",
            "Manual remediation product must belong to the frozen roster.",
            status_code=409,
        )
    planned = next(
        (
            item
            for item in run.get("angle_plan") or []
            if str(item.get("product_id") or "") == product_id
            and str(item.get("angle_key") or "") == angle_key
        ),
        None,
    )
    if not planned:
        raise CreativeSupplyError(
            "ANGLE_OUTSIDE_APPROVED_PLAN",
            "Manual remediation angle must belong to the approved P7 angle plan.",
            status_code=409,
        )
    normalized: list[str] = []
    for value in contents:
        if ctype == "USP_SET":
            if not isinstance(value, list) or not value:
                raise CreativeSupplyError(
                    "USP_SET_ARRAY_REQUIRED",
                    "Manual USP_SET content must be a non-empty string array.",
                )
            content = json.dumps(
                [str(item).strip() for item in value if str(item).strip()],
                ensure_ascii=False,
            )
        else:
            content = str(value or "").strip()
        if not content:
            raise CreativeSupplyError("EMPTY_MANUAL_CONTENT", "Manual content cannot be empty.")
        safety = scan_copy_safety(
            _slot_fields({"component_type": ctype, "content": content}),
            product_id=product_id,
        )
        if not safety.get("safe"):
            raise CreativeSupplyError(
                "UNSAFE_MANUAL_CONTENT",
                "Manual remediation failed the canonical safety scanner.",
                status_code=409,
                details={"violations": safety.get("violations") or []},
            )
        dkey = copy_component_service.make_dedupe_key(content)
        if await crud.find_copy_component_by_dedupe_key(product_id, ctype, dkey):
            raise CreativeSupplyError(
                "DUPLICATE_MANUAL_COMPONENT",
                "Manual remediation cannot re-enter an existing component.",
                status_code=409,
            )
        normalized.append(content)

    role = str(roster_by_id[product_id].get("role") or "TOP10")
    target = _role_targets(run.get("target_policy") or {}, role)[ctype]
    tasks = await supply_db.list_tasks(run_id)
    audit_round = (
        max(
            [
                int(task.get("deficit_round") or 0)
                for task in tasks
                if str(task.get("product_id") or "") == product_id
                and str(task.get("angle_key") or "") == angle_key
                and str(task.get("component_type") or "") == ctype
                and str(task.get("task_kind") or "") == "LEGACY_AUDIT"
            ]
            or [0]
        )
        + 1
    )
    component_ids = []
    for content in normalized:
        safety = scan_copy_safety(
            _slot_fields({"component_type": ctype, "content": content}),
            product_id=product_id,
        )
        component = await crud.create_copy_component(
            product_id,
            angle_key=angle_key,
            angle_label=str(planned.get("angle_label") or ""),
            component_type=ctype,
            content=content,
            status=author_service.STATUS_REVIEW_REQUIRED,
            claim_review_json=stable_json({"safety": safety}),
            dedupe_key=copy_component_service.make_dedupe_key(content),
            source="P7_MANUAL_REMEDIATION",
            provenance_json=stable_json(
                {
                    "lane": "MANUAL_ZERO_PROVIDER",
                    "p7_run_id": run_id,
                    "authored_by": authored_by.strip(),
                    "provider_calls": 0,
                }
            ),
        )
        component_ids.append(str(component["component_id"]))
    task = await supply_db.create_task(
        run_id=run_id,
        product_id=product_id,
        angle_key=angle_key,
        angle_label=str(planned.get("angle_label") or ""),
        component_type=ctype,
        task_kind="LEGACY_AUDIT",
        deficit_round=audit_round,
        target_approved_count=target,
        requested_count=0,
        idempotency_key=sha256(
            {
                "run_id": run_id,
                "manual_remediation": True,
                "product_id": product_id,
                "angle_key": angle_key,
                "component_type": ctype,
                "contents": normalized,
            }
        ),
        state="REVIEW_REQUIRED",
        result={
            "component_ids": component_ids,
            "manual_remediation": True,
            "authored_by": authored_by.strip(),
            "provider_calls": 0,
        },
    )
    return {"task": task, "run": await status(run_id)}


async def review_component(
    *,
    run_id: str,
    task_id: str,
    component_id: str,
    decision: str,
    reviewed_content_sha256: str,
    reasons: list[str],
    reviewer_id: str,
    include_status: bool = True,
) -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    task = await supply_db.get_task(task_id)
    component = await crud.get_copy_component(component_id)
    if not run or not task or not component or str(task.get("run_id")) != run_id:
        raise CreativeSupplyError(
            "REVIEW_LINEAGE_NOT_FOUND",
            "Run, task, and component review lineage must all exist.",
            status_code=404,
        )
    if reviewer_id.strip() != str(run.get("reviewer_id") or ""):
        raise CreativeSupplyError(
            "REVIEWER_ID_MISMATCH",
            "Review must use the stable delegated reviewer identity.",
            status_code=409,
        )
    result_ids = {str(value) for value in (task.get("result") or {}).get("component_ids") or []}
    if component_id not in result_ids:
        raise CreativeSupplyError(
            "COMPONENT_OUTSIDE_TASK_RESULT",
            "The component was not authored by this task.",
            status_code=409,
        )
    for field in ("product_id", "angle_key", "component_type"):
        if str(component.get(field) or "") != str(task.get(field) or ""):
            raise CreativeSupplyError(
                "COMPONENT_TASK_AUTHORITY_MISMATCH",
                "Component product, angle, and type must match its authoring task.",
                status_code=409,
                details={"field": field},
            )
    actual_sha = content_sha256(component)
    if reviewed_content_sha256 != actual_sha:
        raise CreativeSupplyError(
            "REVIEW_CONTENT_SHA_MISMATCH",
            "The decision is not bound to the current component content.",
            status_code=409,
            details={"expected": actual_sha, "actual": reviewed_content_sha256},
        )
    clean_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not clean_reasons:
        raise CreativeSupplyError(
            "REVIEW_REASON_REQUIRED",
            "Every approval or rejection requires at least one explicit review reason.",
        )
    normalized_decision = decision.strip().upper()
    if normalized_decision not in {"APPROVED", "REJECTED"}:
        raise CreativeSupplyError("INVALID_REVIEW_DECISION", "Decision must be APPROVED or REJECTED.")
    safety = scan_copy_safety(_slot_fields(component), product_id=str(component["product_id"]))
    if normalized_decision == "APPROVED" and not safety.get("safe"):
        raise CreativeSupplyError(
            "UNSAFE_COMPONENT_CANNOT_BE_APPROVED",
            "The canonical safety scanner blocks this approval.",
            status_code=409,
            details={"violations": safety.get("violations") or []},
        )

    provenance = _json(component.get("provenance_json"), {})
    provenance.update(
        {
            "p7_run_id": run_id,
            "p7_task_id": task_id,
            "provider_receipt": task.get("provider_receipt") or {},
            "reviewed_content_sha256": actual_sha,
        }
    )
    event = await supply_db.record_review_and_update_component(
        run_id=run_id,
        task_id=task_id,
        component=component,
        decision=normalized_decision,
        reviewed_content_sha256=actual_sha,
        reasons=clean_reasons,
        safety=safety,
        provider_provenance=provenance,
        reviewer_id=reviewer_id.strip(),
    )
    await _finalize_review_task_if_ready(task_id)
    return {
        "event": event,
        "run": await status(run_id) if include_status else None,
    }


async def _finalize_review_task_if_ready(task_id: str) -> None:
    task = await supply_db.get_task(task_id)
    if not task:
        return
    component_ids = [str(value) for value in (task.get("result") or {}).get("component_ids") or []]
    components = [await crud.get_copy_component(component_id) for component_id in component_ids]
    if any(
        component
        and str(component.get("status") or "") == author_service.STATUS_REVIEW_REQUIRED
        for component in components
    ):
        return
    await supply_db.update_task(task_id, state="COMPLETED")
    await _create_deficit_round_if_needed(task_id)


async def _create_deficit_round_if_needed(task_id: str) -> None:
    task = await supply_db.get_task(task_id)
    if not task:
        return
    components = await crud.list_copy_components_for_product(str(task["product_id"]))
    approved = _approved_count(
        components, str(task["angle_key"]), str(task["component_type"])
    )
    deficit = int(task["target_approved_count"]) - approved
    if deficit <= 0:
        return
    run = await supply_db.get_run(str(task["run_id"]))
    if not run:
        return
    tasks = await supply_db.list_tasks(str(task["run_id"]))
    active_same_slot = any(
        str(item.get("product_id") or "") == str(task["product_id"])
        and str(item.get("angle_key") or "") == str(task["angle_key"])
        and str(item.get("component_type") or "") == str(task["component_type"])
        and str(item.get("task_kind") or "AUTHOR_DEFICIT") == "AUTHOR_DEFICIT"
        and str(item.get("state") or "") in ACTIVE_TASK_STATES
        for item in tasks
    )
    if active_same_slot:
        return
    planned_calls = int(run.get("provider_calls_used") or 0) + sum(
        1 for item in tasks if str(item.get("state")) in {"PENDING", "RETRY_ELIGIBLE"}
    )
    if planned_calls >= int(run.get("provider_budget_max") or 0):
        await supply_db.update_run(
            str(task["run_id"]),
            state="BLOCKED",
            last_error="DEFICIT_REMAINS_BUT_PROVIDER_BUDGET_RESERVED",
        )
        return
    slot_rounds = [
        int(item.get("deficit_round") or 0)
        for item in tasks
        if str(item.get("product_id") or "") == str(task["product_id"])
        and str(item.get("angle_key") or "") == str(task["angle_key"])
        and str(item.get("component_type") or "") == str(task["component_type"])
        and str(item.get("task_kind") or "AUTHOR_DEFICIT") == "AUTHOR_DEFICIT"
    ]
    next_round = max(slot_rounds or [0]) + 1
    await supply_db.create_task(
        run_id=str(task["run_id"]),
        product_id=str(task["product_id"]),
        angle_key=str(task["angle_key"]),
        angle_label=str(task["angle_label"]),
        component_type=str(task["component_type"]),
        deficit_round=next_round,
        target_approved_count=int(task["target_approved_count"]),
        requested_count=max(2, min(author_service.MAX_PER_CALL, deficit)),
        idempotency_key=_task_idempotency_key(
            str(task["run_id"]),
            str(task["product_id"]),
            str(task["angle_key"]),
            str(task["component_type"]),
            next_round,
            int(task["target_approved_count"]),
        ),
    )


async def reconcile_missing_deficit_tasks(run_id: str) -> dict[str, Any]:
    """Rebuild only absent deficit tasks after a review/process interruption."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    tasks = await supply_db.list_tasks(run_id)
    seen_slots: set[tuple[str, str, str]] = set()
    for task in reversed(tasks):
        slot = (
            str(task.get("product_id") or ""),
            str(task.get("angle_key") or ""),
            str(task.get("component_type") or ""),
        )
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        await _create_deficit_round_if_needed(str(task["task_id"]))
    return await status(run_id)


async def settle_satisfied_tasks(run_id: str) -> dict[str, Any]:
    """Close pending author tasks whose targets were met without a provider."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    settled = []
    for task in await supply_db.list_tasks(run_id):
        if str(task.get("state") or "") != "PENDING":
            continue
        components = await crud.list_copy_components_for_product(str(task["product_id"]))
        approved = _approved_count(
            components, str(task["angle_key"]), str(task["component_type"])
        )
        if approved < int(task["target_approved_count"]):
            continue
        await supply_db.update_task(
            str(task["task_id"]),
            state="COMPLETED",
            result_json=supply_db.encode(
                {
                    **(task.get("result") or {}),
                    "settled_without_provider_call": True,
                    "approved_count": approved,
                }
            ),
        )
        settled.append(str(task["task_id"]))
    await supply_db.update_run(run_id, state="RUNNING", last_error=None)
    return {"settled_task_ids": settled, "run": await status(run_id)}


async def compose_sample(run_id: str, product_id: str, count: int, dry_run: bool) -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if product_id not in roster_ids:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_RUN_ROSTER",
            "Composition product must belong to the frozen P7 roster.",
            status_code=409,
        )
    if count < 1 or count > 100:
        raise CreativeSupplyError("COMPOSE_COUNT_OUT_OF_RANGE", "Compose count must be 1..100.")
    preview = await copy_composer_service.compose_and_persist(
        product_id, count, dry_run=True
    )
    unsafe = [
        item for item in preview.get("items") or [] if not bool(item.get("safe"))
    ]
    safety_summary = {
        "safe_count": len(preview.get("items") or []) - len(unsafe),
        "unsafe_count": len(unsafe),
        "all_safe": not unsafe,
    }
    if dry_run:
        return {**preview, "safety_summary": safety_summary}
    if unsafe:
        raise CreativeSupplyError(
            "COMPOSITION_BATCH_UNSAFE",
            "P7 refuses to persist a composition batch containing unsafe output.",
            status_code=409,
            details={
                "unsafe_combinations": [
                    {
                        "combination_fingerprint": str(
                            item.get("combination_fingerprint") or ""
                        ),
                        "violations": list(item.get("violations") or []),
                    }
                    for item in unsafe
                ]
            },
        )
    persisted = await copy_composer_service.compose_and_persist(
        product_id, count, dry_run=False
    )
    if any(not bool(item.get("safe")) for item in persisted.get("items") or []):
        raise CreativeSupplyError(
            "PERSISTED_COMPOSITION_SAFETY_DRIFT",
            "Composition changed between preview and persistence; operator review required.",
            status_code=409,
        )
    return {**persisted, "safety_summary": safety_summary}


def copy_set_content_sha256(row: dict[str, Any]) -> str:
    fields = serialize_copy_set(row)
    return sha256(
        {
            key: fields.get(key)
            for key in (
                "product_id",
                "angle",
                "hook",
                "subhook",
                "usp_set",
                "cta",
                "platform",
                "language",
                "route_type",
                "formula_family",
                "source",
                "provenance",
            )
        }
    )


async def review_composed_copy_set(
    *,
    run_id: str,
    copy_set_id: str,
    decision: str,
    reviewed_content_sha256: str,
    reasons: list[str],
    reviewer_id: str = DEFAULT_REVIEWER_ID,
) -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CreativeSupplyError("COPY_SET_NOT_FOUND", "Copy Set not found.", status_code=404)
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if str(row.get("product_id") or "") not in roster_ids:
        raise CreativeSupplyError(
            "COPY_SET_OUTSIDE_RUN_ROSTER",
            "Copy Set must belong to the frozen P7 roster.",
            status_code=409,
        )
    if str(row.get("source") or "") != copy_composer_service.SOURCE_COMPONENT_COMPOSER:
        raise CreativeSupplyError(
            "COPY_SET_SOURCE_NOT_P7_COMPOSER",
            "P7 review only accepts deterministic component-composer Copy Sets.",
            status_code=409,
        )
    current_sha256 = copy_set_content_sha256(row)
    if reviewed_content_sha256 != current_sha256:
        raise CreativeSupplyError(
            "COPY_SET_CONTENT_CHANGED_SINCE_REVIEW",
            "Reviewed hash does not match current Copy Set content.",
            status_code=409,
        )
    normalized_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not normalized_reasons:
        raise CreativeSupplyError(
            "COPY_SET_REVIEW_REASON_REQUIRED",
            "Copy Set review requires at least one exact reason.",
        )
    normalized_decision = decision.strip().upper()
    reviewer_note = " | ".join(normalized_reasons)
    if normalized_decision == "APPROVED":
        reviewed = await copy_set_registry_service.approve_copy_set(
            copy_set_id,
            {
                "approval_phrase": APPROVAL_PHRASE,
                "reviewer_note": reviewer_note,
                "approved_by": reviewer_id.strip() or DEFAULT_REVIEWER_ID,
                "override_formula_review": False,
            },
        )
    elif normalized_decision == "REJECTED":
        reviewed = await copy_set_registry_service.reject_copy_set(
            copy_set_id, {"reviewer_note": reviewer_note}
        )
    else:
        raise CreativeSupplyError(
            "UNKNOWN_COPY_SET_REVIEW_DECISION",
            "Copy Set decision must be APPROVED or REJECTED.",
        )
    return {
        "copy_set": reviewed,
        "reviewed_content_sha256": current_sha256,
        "reviewer_id": reviewer_id.strip() or DEFAULT_REVIEWER_ID,
        "reasons": normalized_reasons,
    }


async def compose_selected_components(
    *,
    run_id: str,
    product_id: str,
    hook_component_id: str,
    subhook_component_id: str,
    usp_set_component_id: str,
    cta_component_id: str,
) -> dict[str, Any]:
    """Persist one exact, operator-selected deterministic composition."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if product_id not in roster_ids:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_RUN_ROSTER",
            "Selected composition product must belong to the frozen P7 roster.",
            status_code=409,
        )
    requested = {
        "HOOK": hook_component_id,
        "SUBHOOK": subhook_component_id,
        "USP_SET": usp_set_component_id,
        "CTA": cta_component_id,
    }
    components: dict[str, dict[str, Any]] = {}
    angle_keys: set[str] = set()
    for expected_type, component_id in requested.items():
        component = await crud.get_copy_component(component_id)
        if not component:
            raise CreativeSupplyError(
                "SELECTED_COMPONENT_NOT_FOUND",
                "Selected copy component not found.",
                status_code=404,
                details={"component_id": component_id},
            )
        if (
            str(component.get("product_id") or "") != product_id
            or str(component.get("component_type") or "") != expected_type
            or str(component.get("status") or "")
            != copy_component_service.STATUS_APPROVED
            or int(component.get("archived") or 0)
        ):
            raise CreativeSupplyError(
                "SELECTED_COMPONENT_NOT_ELIGIBLE",
                "Selected component must be approved, active, product-matched and type-matched.",
                status_code=409,
                details={"component_id": component_id, "expected_type": expected_type},
            )
        components[expected_type] = component
        angle_keys.add(str(component.get("angle_key") or ""))
    if len(angle_keys) != 1 or "" in angle_keys:
        raise CreativeSupplyError(
            "SELECTED_COMPONENT_ANGLE_MISMATCH",
            "All selected components must share one approved angle.",
            status_code=409,
        )
    angle_key = next(iter(angle_keys))
    planned = next(
        (
            item
            for item in run.get("angle_plan") or []
            if str(item.get("product_id") or "") == product_id
            and str(item.get("angle_key") or "") == angle_key
        ),
        None,
    )
    if not planned:
        raise CreativeSupplyError(
            "SELECTED_ANGLE_OUTSIDE_APPROVED_PLAN",
            "Selected composition angle must belong to the approved P7 plan.",
            status_code=409,
        )
    try:
        usp_set = json.loads(str(components["USP_SET"].get("content") or "[]"))
    except json.JSONDecodeError as error:
        raise CreativeSupplyError(
            "SELECTED_USP_SET_INVALID",
            "Selected USP_SET content is not a valid JSON array.",
            status_code=409,
        ) from error
    if not isinstance(usp_set, list) or not usp_set:
        raise CreativeSupplyError(
            "SELECTED_USP_SET_INVALID",
            "Selected USP_SET content must be a non-empty JSON array.",
            status_code=409,
        )
    product = await crud.get_product(product_id)
    if not product:
        raise CreativeSupplyError("PRODUCT_NOT_FOUND", "Product not found.", status_code=404)
    grounding = await resolve_copy_grounding(product)
    fields = copy_set_registry_service._normalize_fields(
        {
            "angle": str(planned.get("angle_label") or ""),
            "hook": str(components["HOOK"].get("content") or ""),
            "subhook": str(components["SUBHOOK"].get("content") or ""),
            "usp_set": [str(value) for value in usp_set],
            "cta": str(components["CTA"].get("content") or ""),
            "platform": "TIKTOK",
            "language": "BM_MS",
            "route_type": str(
                getattr(grounding, "effective_route", "") or "DIRECT"
            ),
            "formula_family": "PAS",
        }
    )
    safety = scan_copy_safety(fields, product_id=product_id)
    if not safety.get("safe"):
        raise CreativeSupplyError(
            "SELECTED_COMPOSITION_UNSAFE",
            "Selected composition failed the canonical safety scanner.",
            status_code=409,
            details={"violations": safety.get("violations") or []},
        )
    dedupe_key = copy_set_registry_service._dedupe_key_for(product_id, fields)
    existing = await crud.find_copy_set_by_dedupe_key(dedupe_key)
    if existing:
        return {
            "copy_set": serialize_copy_set(existing),
            "created": False,
            "dedupe_match": True,
            "safety": safety,
        }
    ordered_component_ids = [requested[name] for name in COMPONENT_ORDER]
    row = await crud.create_copy_set(
        product_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"], ensure_ascii=False),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        status=copy_set_registry_service.STATUS_COPY_REVIEW_REQUIRED,
        dedupe_key=dedupe_key,
        source=copy_composer_service.SOURCE_COMPONENT_COMPOSER,
        provenance_json=stable_json(
            {
                "composed": True,
                "p7_selected_composition": True,
                "p7_run_id": run_id,
                "angle_key": angle_key,
                "component_ids": ordered_component_ids,
                "combination_fingerprint": copy_composer_service.combination_fingerprint(
                    ordered_component_ids
                ),
                "provider_calls": 0,
            }
        ),
        claim_review_json=stable_json(
            {
                "composed": True,
                "safety": safety,
                "route_type": fields["route_type"],
            }
        ),
    )
    return {
        "copy_set": serialize_copy_set(row),
        "created": True,
        "dedupe_match": False,
        "safety": safety,
    }


async def correct_component_review(
    *,
    run_id: str,
    component_id: str,
    reviewed_content_sha256: str,
    reasons: list[str],
    reviewer_id: str = DEFAULT_REVIEWER_ID,
) -> dict[str, Any]:
    """Supersede an approval when composed-output review proves it unusable."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    component = await crud.get_copy_component(component_id)
    if not component:
        raise CreativeSupplyError(
            "COMPONENT_NOT_FOUND", "Copy component not found.", status_code=404
        )
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if str(component.get("product_id") or "") not in roster_ids:
        raise CreativeSupplyError(
            "COMPONENT_OUTSIDE_RUN_ROSTER",
            "Corrected component must belong to the frozen P7 roster.",
            status_code=409,
        )
    if str(component.get("status") or "") != copy_component_service.STATUS_APPROVED:
        raise CreativeSupplyError(
            "CORRECTION_REQUIRES_APPROVED_COMPONENT",
            "Only an approved component can be corrected to rejected.",
            status_code=409,
        )
    current_sha256 = content_sha256(component)
    if reviewed_content_sha256 != current_sha256:
        raise CreativeSupplyError(
            "COMPONENT_CONTENT_CHANGED_SINCE_CORRECTION_REVIEW",
            "Reviewed hash does not match current component content.",
            status_code=409,
        )
    normalized_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not normalized_reasons:
        raise CreativeSupplyError(
            "COMPONENT_CORRECTION_REASON_REQUIRED",
            "Component correction requires an exact reason.",
        )
    tasks = await supply_db.list_tasks(run_id)
    source_task = next(
        (
            task
            for task in reversed(tasks)
            if component_id
            in {
                str(value)
                for value in (task.get("result") or {}).get("component_ids") or []
            }
        ),
        None,
    )
    if not source_task:
        raise CreativeSupplyError(
            "COMPONENT_TASK_LINEAGE_NOT_FOUND",
            "Component correction requires P7 task lineage.",
            status_code=409,
        )
    reviews = await supply_db.list_review_events(run_id)
    prior_review = next(
        (
            event
            for event in reversed(reviews)
            if str(event.get("component_id") or "") == component_id
        ),
        None,
    )
    safety = scan_copy_safety(
        _slot_fields(component), product_id=str(component["product_id"])
    )
    provenance = {
        **_json(component.get("provenance_json"), {}),
        "review_correction": {
            "trigger": "COMPOSED_OUTPUT_ACTUAL_REVIEW",
            "prior_event_id": str((prior_review or {}).get("event_id") or ""),
            "decision": "REJECTED",
        },
    }
    correction_key = sha256(
        {
            "run_id": run_id,
            "component_id": component_id,
            "prior_event_id": str((prior_review or {}).get("event_id") or ""),
            "decision": "REJECTED",
            "reasons": normalized_reasons,
        }
    )
    correction_task = next(
        (
            task
            for task in tasks
            if str(task.get("idempotency_key") or "") == correction_key
        ),
        None,
    )
    if not correction_task:
        correction_task = await supply_db.create_task(
            run_id=run_id,
            product_id=str(component["product_id"]),
            angle_key=str(component["angle_key"]),
            angle_label=str(component.get("angle_label") or ""),
            component_type=str(component["component_type"]),
            task_kind="LEGACY_AUDIT",
            deficit_round=max(
                [
                    int(task.get("deficit_round") or 0)
                    for task in tasks
                    if str(task.get("product_id") or "")
                    == str(component["product_id"])
                    and str(task.get("angle_key") or "")
                    == str(component["angle_key"])
                    and str(task.get("component_type") or "")
                    == str(component["component_type"])
                ]
                or [0]
            )
            + 1,
            target_approved_count=int(source_task.get("target_approved_count") or 0),
            requested_count=0,
            idempotency_key=correction_key,
            state="REVIEW_REQUIRED",
            result={
                "component_ids": [component_id],
                "review_correction": True,
                "source_task_id": str(source_task["task_id"]),
                "prior_event_id": str((prior_review or {}).get("event_id") or ""),
                "provider_calls": 0,
            },
        )
    event = await supply_db.record_review_and_update_component(
        run_id=run_id,
        task_id=str(correction_task["task_id"]),
        component=component,
        decision="REJECTED",
        reviewed_content_sha256=current_sha256,
        reasons=normalized_reasons,
        safety=safety,
        provider_provenance=provenance,
        reviewer_id=reviewer_id.strip() or DEFAULT_REVIEWER_ID,
        expected_statuses=(copy_component_service.STATUS_APPROVED,),
    )
    await supply_db.update_task(
        str(correction_task["task_id"]),
        state="COMPLETED",
        result_json=supply_db.encode(
            {
                **(correction_task.get("result") or {}),
                "review_event_id": str(event["event_id"]),
                "decision": "REJECTED",
            }
        ),
    )
    return {"event": event, "run": await status(run_id)}


async def register_product_only_f2v_frame_alias(
    *,
    run_id: str,
    product_id: str,
    source_asset_id: str,
    reviewer_id: str = DEFAULT_REVIEWER_ID,
) -> dict[str, Any]:
    """Register an approved product photo as a zero-generation F2V start frame."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if product_id not in roster_ids:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_RUN_ROSTER",
            "F2V frame alias product must belong to the frozen P7 roster.",
            status_code=409,
        )
    source = await crud.get_creative_asset(source_asset_id)
    if not source:
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_NOT_FOUND",
            "Source product asset not found.",
            status_code=404,
        )
    if (
        str(source.get("product_id") or "") != product_id
        or str(source.get("semantic_role") or "") != "PRODUCT_REFERENCE"
        or str(source.get("status") or "") != "ACTIVE"
        or str(source.get("review_status") or "") != "APPROVED"
    ):
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_NOT_ELIGIBLE",
            "F2V alias requires an active, approved, product-matched PRODUCT_REFERENCE.",
            status_code=409,
        )
    allowed_modes = _json(source.get("allowed_modes"), [])
    if "F2V" not in allowed_modes:
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_NOT_F2V_ELIGIBLE",
            "Source product asset is not approved for F2V.",
            status_code=409,
        )
    if not (
        str(source.get("local_file_path") or "").strip()
        or str(source.get("media_id") or "").strip()
        or str(source.get("preview_url") or "").strip()
    ):
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_HAS_NO_RESOLVABLE_MEDIA",
            "Source product asset has no resolvable media binding.",
            status_code=409,
        )
    existing_assets = await crud.list_creative_assets(
        product_id=product_id,
        semantic_role="COMPOSITE_FRAME_REFERENCE",
        status="ACTIVE",
        limit=500,
    )
    for existing in existing_assets:
        handoff = _json(existing.get("mode_a_metadata_handoff"), {})
        if (
            str(existing.get("generation_recipe_id") or "")
            == "P7_PRODUCT_ONLY_F2V_ALIAS"
            and str(handoff.get("source_product_reference_asset_id") or "")
            == source_asset_id
        ):
            return {
                "asset": creative_asset_service._normalize_record(existing).model_dump(
                    mode="json"
                ),
                "created": False,
                "provider_media_calls": 0,
            }
    handoff = {
        "p7_run_id": run_id,
        "lane": "PRODUCT_ONLY_F2V_START_FRAME_ALIAS",
        "source_product_reference_asset_id": source_asset_id,
        "provider_media_calls": 0,
        "pixel_mutation": False,
        "reviewed_by": reviewer_id.strip() or DEFAULT_REVIEWER_ID,
        "inject_as": "frame_reference_description",
        "role_hint": "product_only_start_frame",
    }
    created = await creative_asset_service.create_creative_asset(
        CreativeAssetCreateRequest(
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            display_name=f"P7 product-only F2V frame — {source.get('display_name') or product_id}",
            description=(
                "Zero-generation alias of the approved physical PRODUCT_REFERENCE. "
                "No pixels were generated or edited; the source image remains the "
                "identity, geometry, scale and label truth."
            ),
            source_type="PRODUCT_CACHE",
            storage_kind=str(source.get("storage_kind") or "LOCAL_FILE"),
            preview_url=source.get("preview_url"),
            download_url=source.get("download_url"),
            media_id=source.get("media_id"),
            local_file_path=source.get("local_file_path"),
            remote_source_url=source.get("remote_source_url"),
            product_id=product_id,
            category=source.get("category"),
            silo=source.get("silo"),
            product_type=source.get("product_type"),
            allowed_modes=["F2V"],
            engine_slot_eligibility=["start_frame"],
            mode_a_metadata_handoff=handoff,
            asset_subtype="PRODUCT_ONLY_START_FRAME_ALIAS",
            generation_recipe_id="P7_PRODUCT_ONLY_F2V_ALIAS",
            contains_rendered_text=False,
            approved_for_video_support=True,
            approved_for_poster=False,
            product_truth_status=str(
                source.get("product_truth_status") or "P7_VISUAL_REVIEWED"
            ),
            identity_lock_status=str(
                source.get("identity_lock_status") or "P7_VISUAL_REVIEWED"
            ),
            scale_truth_status=str(
                source.get("scale_truth_status") or "P7_VISUAL_REVIEWED"
            ),
            claim_safety_status="NOT_APPLICABLE",
            review_status="APPROVED",
        )
    )
    return {
        "asset": created.model_dump(mode="json"),
        "created": True,
        "provider_media_calls": 0,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_embedded_source_pixels(
    *,
    source_path: Path,
    anchor_path: Path,
    source_region: dict[str, int],
) -> bool:
    with Image.open(source_path) as raw_source, Image.open(anchor_path) as raw_anchor:
        source = raw_source.convert("RGBA")
        anchor = raw_anchor.convert("RGBA")
        x = int(source_region["x"])
        y = int(source_region["y"])
        w = int(source_region["w"])
        h = int(source_region["h"])
        if source.size != (w, h):
            return False
        embedded = anchor.crop((x, y, x + w, y + h))
        return ImageChops.difference(source, embedded).getbbox() is None


async def prepare_product_only_f2v_anchor_916(
    *,
    run_id: str,
    product_id: str,
    source_asset_id: str,
) -> dict[str, Any]:
    """Create a zero-provider 9:16 anchor without changing source pixels.

    The approved physical product image is embedded at its native dimensions
    on a neutral 9:16 canvas. The derivative remains PENDING_REVIEW until a
    reviewer binds approval to its exact output hash.
    """
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError(
            "RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404
        )
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    if product_id not in roster_ids:
        raise CreativeSupplyError(
            "PRODUCT_OUTSIDE_RUN_ROSTER",
            "F2V anchor product must belong to the frozen P7 roster.",
            status_code=409,
        )
    source = await crud.get_creative_asset(source_asset_id)
    if not source:
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_NOT_FOUND",
            "Source product asset not found.",
            status_code=404,
        )
    if (
        str(source.get("product_id") or "") != product_id
        or str(source.get("semantic_role") or "") != "PRODUCT_REFERENCE"
        or str(source.get("status") or "") != "ACTIVE"
        or str(source.get("review_status") or "") != "APPROVED"
    ):
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_NOT_ELIGIBLE",
            "F2V anchor requires an active, approved, product-matched PRODUCT_REFERENCE.",
            status_code=409,
        )
    source_path = Path(str(source.get("local_file_path") or "")).resolve()
    if not source_path.is_file():
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_LOCAL_FILE_REQUIRED",
            "Deterministic 9:16 anchor preparation requires a local source file.",
            status_code=409,
        )
    existing_assets = await crud.list_creative_assets(
        product_id=product_id,
        semantic_role="COMPOSITE_FRAME_REFERENCE",
        status="ACTIVE",
        limit=500,
    )
    for existing in existing_assets:
        handoff = _json(existing.get("mode_a_metadata_handoff"), {})
        if (
            str(existing.get("generation_recipe_id") or "")
            == "P7_PRODUCT_ONLY_F2V_ANCHOR_916"
            and str(handoff.get("source_product_reference_asset_id") or "")
            == source_asset_id
        ):
            return {
                "asset": creative_asset_service._normalize_record(existing).model_dump(
                    mode="json"
                ),
                "created": False,
                "provider_media_calls": 0,
            }

    with Image.open(source_path) as raw_source:
        source_image = raw_source.convert("RGBA")
    if source_image.getchannel("A").getextrema() != (255, 255):
        raise CreativeSupplyError(
            "SOURCE_PRODUCT_ASSET_ALPHA_UNSUPPORTED",
            "Source transparency prevents exact native-pixel embedding.",
            status_code=409,
        )
    unit = max(
        160,
        math.ceil(source_image.width / 9),
        math.ceil(source_image.height / 16),
    )
    canvas_size = (unit * 9, unit * 16)
    x = (canvas_size[0] - source_image.width) // 2
    y = (canvas_size[1] - source_image.height) // 2
    canvas = Image.new("RGBA", canvas_size, (245, 244, 240, 255))
    canvas.paste(source_image, (x, y))
    embedded = canvas.crop(
        (x, y, x + source_image.width, y + source_image.height)
    )
    if ImageChops.difference(source_image, embedded).getbbox() is not None:
        raise CreativeSupplyError(
            "SOURCE_PIXEL_INTEGRITY_FAILED",
            "Native product pixels changed during deterministic padding.",
            status_code=500,
        )
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=False)
    output_bytes = output.getvalue()
    source_sha256 = _sha256_file(source_path)
    output_sha256 = hashlib.sha256(output_bytes).hexdigest()
    source_region = {
        "x": x,
        "y": y,
        "w": source_image.width,
        "h": source_image.height,
    }
    handoff = {
        "p7_run_id": run_id,
        "lane": "PRODUCT_ONLY_F2V_ANCHOR_916",
        "source_product_reference_asset_id": source_asset_id,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "canvas": {"w": canvas_size[0], "h": canvas_size[1], "aspect": "9:16"},
        "source_region": source_region,
        "provider_media_calls": 0,
        "source_pixel_mutation": False,
        "canvas_padding_added": True,
        "source_pixel_region_match": True,
        "review_state": "PENDING_REVIEW",
        "inject_as": "frame_reference_description",
        "role_hint": "product_only_start_frame",
    }
    created = await creative_asset_service.create_creative_asset(
        CreativeAssetCreateRequest(
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            display_name=f"P7 reviewed 9:16 product anchor — {source.get('display_name') or product_id}",
            description=(
                "Zero-provider deterministic 9:16 input anchor. The approved "
                "physical PRODUCT_REFERENCE is embedded at native dimensions; "
                "only neutral canvas padding is added."
            ),
            source_type="PRODUCT_CACHE",
            storage_kind="LOCAL_FILE",
            product_id=product_id,
            category=source.get("category"),
            silo=source.get("silo"),
            product_type=source.get("product_type"),
            allowed_modes=["F2V"],
            engine_slot_eligibility=["start_frame"],
            mode_a_metadata_handoff=handoff,
            asset_subtype="PRODUCT_ONLY_START_FRAME_ANCHOR_916",
            generation_recipe_id="P7_PRODUCT_ONLY_F2V_ANCHOR_916",
            contains_rendered_text=False,
            approved_for_video_support=False,
            approved_for_poster=False,
            product_truth_status="UNVERIFIED",
            identity_lock_status="UNVERIFIED",
            scale_truth_status="UNVERIFIED",
            claim_safety_status="UNVERIFIED",
            review_status="PENDING_REVIEW",
            image_base64=base64.b64encode(output_bytes).decode("ascii"),
            file_name="p7-product-only-anchor-916.png",
        )
    )
    return {
        "asset": created.model_dump(mode="json"),
        "created": True,
        "provider_media_calls": 0,
        "source_sha256": source_sha256,
        "output_sha256": output_sha256,
        "source_region": source_region,
    }


async def review_product_only_f2v_anchor_916(
    *,
    run_id: str,
    asset_id: str,
    reviewed_output_sha256: str,
    reasons: list[str],
    reviewer_id: str = DEFAULT_REVIEWER_ID,
) -> dict[str, Any]:
    """Approve a prepared anchor only after exact hash-bound visual review."""
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError(
            "RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404
        )
    asset = await crud.get_creative_asset(asset_id)
    if not asset:
        raise CreativeSupplyError(
            "ANCHOR_ASSET_NOT_FOUND", "Prepared anchor not found.", status_code=404
        )
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    handoff = _json(asset.get("mode_a_metadata_handoff"), {})
    if (
        str(asset.get("product_id") or "") not in roster_ids
        or str(asset.get("generation_recipe_id") or "")
        != "P7_PRODUCT_ONLY_F2V_ANCHOR_916"
        or str(handoff.get("p7_run_id") or "") != run_id
    ):
        raise CreativeSupplyError(
            "ANCHOR_ASSET_OUTSIDE_RUN",
            "Prepared anchor is not governed by this P7 run.",
            status_code=409,
        )
    if not reasons or not all(str(reason).strip() for reason in reasons):
        raise CreativeSupplyError(
            "ANCHOR_REVIEW_REASONS_REQUIRED",
            "Anchor approval requires explicit review reasons.",
            status_code=422,
        )
    anchor_path = Path(str(asset.get("local_file_path") or "")).resolve()
    source = await crud.get_creative_asset(
        str(handoff.get("source_product_reference_asset_id") or "")
    )
    source_path = Path(str((source or {}).get("local_file_path") or "")).resolve()
    if not anchor_path.is_file() or not source_path.is_file():
        raise CreativeSupplyError(
            "ANCHOR_REVIEW_FILE_MISSING",
            "Anchor or source file is missing at review time.",
            status_code=409,
        )
    actual_sha256 = _sha256_file(anchor_path)
    expected_sha256 = str(handoff.get("output_sha256") or "")
    if (
        reviewed_output_sha256 != actual_sha256
        or expected_sha256 != actual_sha256
    ):
        raise CreativeSupplyError(
            "ANCHOR_REVIEW_HASH_MISMATCH",
            "Reviewed anchor hash does not match the persisted file.",
            status_code=409,
        )
    if not _verify_embedded_source_pixels(
        source_path=source_path,
        anchor_path=anchor_path,
        source_region=handoff.get("source_region") or {},
    ):
        raise CreativeSupplyError(
            "ANCHOR_SOURCE_PIXEL_INTEGRITY_FAILED",
            "Embedded source pixels no longer match the approved product reference.",
            status_code=409,
        )
    handoff.update(
        {
            "review_state": "APPROVED",
            "reviewed_output_sha256": actual_sha256,
            "reviewed_by": reviewer_id.strip() or DEFAULT_REVIEWER_ID,
            "review_reasons": [str(reason).strip() for reason in reasons],
            "source_pixel_region_match": True,
        }
    )
    updated = await creative_asset_service.update_creative_asset(
        asset_id,
        CreativeAssetUpdateRequest(
            mode_a_metadata_handoff=handoff,
            approved_for_video_support=True,
            product_truth_status="PASS",
            identity_lock_status="PASS",
            scale_truth_status="PASS",
            claim_safety_status="PASS",
            review_status="APPROVED",
        ),
    )
    return {
        "asset": updated.model_dump(mode="json"),
        "reviewed_output_sha256": actual_sha256,
        "provider_media_calls": 0,
    }


async def upload_product_only_f2v_anchor_916(
    *,
    run_id: str,
    asset_id: str,
    confirmation: str,
) -> dict[str, Any]:
    """Reuse the proven Flow upload helper; never submit a generation job."""
    if confirmation != P7_ANCHOR_UPLOAD_CONFIRMATION:
        raise CreativeSupplyError(
            "ANCHOR_UPLOAD_CONFIRMATION_REQUIRED",
            f"Exact confirmation required: {P7_ANCHOR_UPLOAD_CONFIRMATION}",
            status_code=403,
        )
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError(
            "RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404
        )
    asset = await crud.get_creative_asset(asset_id)
    if not asset:
        raise CreativeSupplyError(
            "ANCHOR_ASSET_NOT_FOUND", "Prepared anchor not found.", status_code=404
        )
    roster_ids = {str(item.get("product_id") or "") for item in run.get("roster") or []}
    handoff = _json(asset.get("mode_a_metadata_handoff"), {})
    if (
        str(asset.get("product_id") or "") not in roster_ids
        or str(asset.get("generation_recipe_id") or "")
        != "P7_PRODUCT_ONLY_F2V_ANCHOR_916"
        or str(asset.get("review_status") or "") != "APPROVED"
        or str(handoff.get("review_state") or "") != "APPROVED"
    ):
        raise CreativeSupplyError(
            "ANCHOR_UPLOAD_NOT_ELIGIBLE",
            "Only an approved, hash-bound P7 9:16 anchor may be uploaded.",
            status_code=409,
        )
    client = get_flow_client()
    if not getattr(client, "connected", False):
        raise CreativeSupplyError(
            "EXTENSION_OFFLINE_FOR_UPLOAD",
            "The canonical Flow transport is not connected.",
            status_code=409,
        )
    prior_media_id = str(asset.get("media_id") or "")
    media_id, blocker = await production_queue_service._upload_slot_to_flow_media(
        asset_id,
        {"product_id": str(asset.get("product_id") or "")},
        client,
        aspect="9:16",
    )
    if blocker or not media_id:
        raise CreativeSupplyError(
            "ANCHOR_UPLOAD_BLOCKED",
            blocker or "Flow returned no durable media identity.",
            status_code=409,
        )
    handoff.update(
        {
            "flow_media_id": media_id,
            "flow_upload_confirmation": P7_ANCHOR_UPLOAD_CONFIRMATION,
            "generation_submission_attempts": 0,
            "generation_credit_spend": 0,
        }
    )
    updated = await crud.update_creative_asset(
        asset_id,
        mode_a_metadata_handoff=supply_db.encode(handoff),
    )
    return {
        "asset_id": asset_id,
        "media_id": media_id,
        "reused_existing_live_media": prior_media_id == media_id,
        "provider_generation_calls": 0,
        "credit_spend": 0,
        "asset": creative_asset_service._normalize_record(updated).model_dump(
            mode="json"
        ),
    }


async def _product_status(
    run: dict[str, Any], roster_item: dict[str, Any], planned_angles: list[dict[str, Any]]
) -> dict[str, Any]:
    product_id = str(roster_item["product_id"])
    product = await crud.get_product(product_id)
    snapshot = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    components = await crud.list_copy_components_for_product(product_id)
    copy_sets = await crud.list_copy_sets_for_product(product_id)
    selection = await crud.get_creative_product_selection(product_id)
    assets = await crud.list_creative_assets(product_id=product_id, limit=200)
    poster_sets = await crud.list_poster_copy_sets_for_product(product_id)
    role = str(roster_item.get("role") or "TOP10")
    targets = _role_targets(run.get("target_policy") or {}, role)
    angle_keys = [str(angle.get("angle_key") or "") for angle in planned_angles]
    component_counts: list[dict[str, Any]] = []
    deficits: list[dict[str, Any]] = []
    for angle in planned_angles:
        angle_key = str(angle.get("angle_key") or "")
        counts = {
            component_type: _approved_count(components, angle_key, component_type)
            for component_type in COMPONENT_ORDER
        }
        component_counts.append(
            {
                "angle_key": angle_key,
                "angle_label": str(angle.get("angle_label") or ""),
                "approved": counts,
            }
        )
        for component_type in COMPONENT_ORDER:
            if counts[component_type] < targets[component_type]:
                deficits.append(
                    {
                        "angle_key": angle_key,
                        "component_type": component_type,
                        "missing": targets[component_type] - counts[component_type],
                    }
                )
    capacity = copy_component_service.pool_capacity(
        components,
        angle_keys,
        formula_count=1,
    )
    total_capacity = int(
        capacity.get("total_combinations")
        or capacity.get("total_capacity")
        or 0
    )
    capacity_target = int(
        ((run.get("target_policy") or {}).get(role) or {}).get("minimum_capacity") or 0
    )
    blockers: list[str] = []
    if not snapshot:
        blockers.append("NO_APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT")
    if deficits:
        blockers.append(f"COMPONENT_DEFICITS:{len(deficits)}")
    if total_capacity < capacity_target:
        blockers.append(
            f"COMPOSABLE_CAPACITY_SHORTFALL:{total_capacity}/{capacity_target}"
        )
    if not selection or str(selection.get("status") or "") != "APPROVED":
        blockers.append("PRODUCT_FIRST_AVATAR_SELECTION_NOT_APPROVED")
    active_assets = [
        asset
        for asset in assets
        if str(asset.get("status") or "") == "ACTIVE"
        and str(asset.get("review_status") or "") == "APPROVED"
    ]
    has_product_reference = any(
        str(asset.get("semantic_role") or "") == "PRODUCT_REFERENCE" for asset in active_assets
    )
    has_finished_frame = any(
        str(asset.get("semantic_role") or "") == "COMPOSITE_FRAME_REFERENCE"
        for asset in active_assets
    )
    poster_ready = any(
        str(item.get("status") or "") == "POSTER_COPY_APPROVED" for item in poster_sets
    ) and any(int(asset.get("approved_for_poster") or 0) for asset in active_assets)
    if not has_product_reference and not has_finished_frame:
        blockers.append("NO_APPROVED_VIDEO_PRODUCT_ASSET")
    if not poster_ready:
        blockers.append("POSTER_IMAGE_POOL_NOT_READY")

    statuses = Counter(str(component.get("status") or "") for component in components)
    next_action = "READY"
    if deficits:
        first = deficits[0]
        next_action = (
            f"AUTHOR:{first['angle_key']}:{first['component_type']}:missing={first['missing']}"
        )
    elif total_capacity < capacity_target:
        next_best = capacity.get("next_best") or {}
        next_action = (
            f"CAPACITY_UPLIFT:{next_best.get('angle_key')}:{next_best.get('component_type')}"
        )
    return {
        "product_id": product_id,
        "product_name": (product or {}).get("product_display_name")
        or (product or {}).get("raw_product_title")
        or product_id,
        "rank": roster_item.get("rank"),
        "role": role,
        "product_truth_readiness": (snapshot or {}).get("readiness_status") or "MISSING",
        "approved_snapshot_status": (snapshot or {}).get("status") or "MISSING",
        "claim_gate": (snapshot or {}).get("claim_gate") or "MISSING",
        "angle_count": len(planned_angles),
        "component_counts": component_counts,
        "component_total": len(components),
        "review_required_count": statuses[author_service.STATUS_REVIEW_REQUIRED],
        "approved_count": statuses[copy_component_service.STATUS_APPROVED],
        "rejected_count": statuses["COMPONENT_REJECTED"],
        "deficits": deficits,
        "composable_capacity": total_capacity,
        "capacity_target": capacity_target,
        "approved_copy_set_count": sum(
            1 for item in copy_sets if str(item.get("status") or "") == STATUS_COPY_APPROVED
        ),
        "avatar_readiness": "APPROVED" if selection and str(selection.get("status")) == "APPROVED" else "BLOCKED",
        "scene_readiness": (
            "APPROVED"
            if selection
            and str(selection.get("status")) == "APPROVED"
            and str(selection.get("selected_scene_template_id") or "")
            else "BLOCKED"
        ),
        "video_asset_readiness": {
            "product_reference": has_product_reference,
            "composite_frame_reference": has_finished_frame,
        },
        "poster_image_readiness": "READY" if poster_ready else "BLOCKED",
        "p6_preflight_status": "REQUIRES_EXACT_ZERO_CREDIT_PREFLIGHT",
        "blockers": blockers,
        "next_best_supply_action": next_action,
    }


async def status(run_id: str) -> dict[str, Any]:
    run = await supply_db.get_run(run_id)
    if not run:
        raise CreativeSupplyError("RUN_NOT_FOUND", "Creative-supply run not found.", status_code=404)
    tasks = await supply_db.list_tasks(run_id)
    reviews = await supply_db.list_review_events(run_id)
    review_queue: list[dict[str, Any]] = []
    for task in tasks:
        if str(task.get("state") or "") != "REVIEW_REQUIRED":
            continue
        candidates = []
        for component_id in (task.get("result") or {}).get("component_ids") or []:
            component = await crud.get_copy_component(str(component_id))
            if not component:
                continue
            candidates.append(
                {
                    "component_id": str(component["component_id"]),
                    "product_id": str(component["product_id"]),
                    "angle_key": str(component["angle_key"]),
                    "angle_label": str(component.get("angle_label") or ""),
                    "component_type": str(component["component_type"]),
                    "content": str(component.get("content") or ""),
                    "status": str(component.get("status") or ""),
                    "content_sha256": content_sha256(component),
                    "provider_provenance": _json(component.get("provenance_json"), {}),
                }
            )
        review_queue.append({**task, "candidates": candidates})
    angles_by_product: dict[str, list[dict[str, Any]]] = {}
    for angle in run.get("angle_plan") or []:
        angles_by_product.setdefault(str(angle.get("product_id") or ""), []).append(angle)
    products = [
        await _product_status(run, roster_item, angles_by_product.get(str(roster_item["product_id"]), []))
        for roster_item in run.get("roster") or []
    ]
    task_counts = Counter(str(task.get("state") or "") for task in tasks)
    provider_used = int(run.get("provider_calls_used") or 0)
    provider_max = int(run.get("provider_budget_max") or 0)
    remaining = max(0, provider_max - provider_used)
    pending_calls = task_counts["PENDING"] + task_counts["RETRY_ELIGIBLE"]
    state = str(run.get("state") or "")
    if state not in {"PAUSED", "CANCELLED", "BLOCKED"}:
        if not any(task_counts[name] for name in ACTIVE_TASK_STATES) and all(
            not product["deficits"]
            and product["composable_capacity"] >= product["capacity_target"]
            for product in products
        ):
            state = "COMPLETED"
        elif any(task_counts[name] for name in FINAL_FAILURE_STATES) and not any(
            task_counts[name] for name in ACTIVE_TASK_STATES
        ):
            state = "BLOCKED"
        elif state in {"READY", "DRAFT"} and tasks:
            state = "READY"
        else:
            state = "RUNNING"
        if state != str(run.get("state")):
            run = await supply_db.update_run(run_id, state=state) or run
    return {
        "run": run,
        "products": products,
        "tasks": tasks,
        "task_counts": dict(sorted(task_counts.items())),
        "review_events": reviews,
        "review_queue": review_queue,
        "provider_budget": {
            "maximum": provider_max,
            "used": provider_used,
            "remaining": remaining,
            "pending_or_retry_calls": pending_calls,
            "within_ceiling": provider_used + pending_calls <= provider_max,
        },
        "exact_blockers": sorted(
            {
                blocker
                for product in products
                for blocker in product.get("blockers") or []
            }
        ),
    }


async def list_runs() -> dict[str, Any]:
    return {"runs": await supply_db.list_runs()}
