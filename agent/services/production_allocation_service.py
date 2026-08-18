"""Macro Round 3 P5 — P6 per-item production copy allocation + usage ledger.

Allocates specific FROZEN-manifest items to a P6 production plan as EXPLICIT
per-item copy selections — each carrying an exact (v2_blueprint_id, revision,
v2_approval_snapshot_id).  It resolves the exact execution copy by reading the
selected blueprint DIRECTLY (never the product-global activation pointer
``copy_execution_authority_v2``), so P6 multi-copy selection can never churn the
interactive creator lanes' active blueprint.  Every allocation / consumption /
block is recorded in the append-only ``landbank_usage_v3`` ledger.

Compile / queue / provider-start each revalidate the exact selected blueprint and
FAIL CLOSED on any drift — a stale item is blocked, never silently substituted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.authority.copy_blueprint_v2_authority import formula_version as v2_formula_version
from agent.db import creative_production_crud as p6db
from agent.models.storyboard_landbank_v3 import deterministic_digest, deterministic_id
from agent.models.storyboard_landbank_v3_round3 import LandbankUsageV3, usage_event_digest
from agent.services import copy_register_v2_service as v2svc
from agent.services import production_copy_supply_service as supply_status
from agent.services import production_supply_repository as supply_repo
from agent.services.round3_authority_validator import revalidate_round3_v2_authority


class AllocationError(Exception):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.details = details or {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _resolve_blueprint(blueprint_id: str, revision: int):
    try:
        return await v2svc.get_blueprint(blueprint_id, revision)
    except v2svc.CopyRegisterV2Error:
        return None


async def _revalidate_selection(
    *,
    v2_blueprint_id: str,
    v2_blueprint_revision: int,
    product_truth_snapshot_digest: str,
    formula_id: str,
    current_truth: dict[str, Any] | None,
    expected_approval_snapshot_id: str | None = None,
) -> tuple[bool, str | None, Any]:
    """Full current-production-authority revalidation for one selected blueprint.

    Delegates to the ONE shared Round 3 validator, which reuses the complete V2
    authority (current-authority projection + validate_copy_blueprint_v2), so a
    historically PRODUCTION_VALID blueprint whose current authority drifted
    (stale/missing/mutated evidence, taxonomy drift, approval mutation, snapshot
    mismatch, formula drift, duration) FAILS CLOSED — not just a status/digest
    check.  ``current_truth`` is accepted for call-site compatibility; the shared
    validator loads CURRENT truth + evidence itself.
    """

    result = await revalidate_round3_v2_authority(
        blueprint_id=v2_blueprint_id,
        revision=v2_blueprint_revision,
        expected_approval_snapshot_id=expected_approval_snapshot_id,
        expected_truth_digest=product_truth_snapshot_digest or None,
        expected_formula=formula_id or None,
    )
    reason = result.reason_codes[0] if result.reason_codes else None
    return result.valid, reason, result.blueprint


def _authority_digest(item) -> str:
    return deterministic_digest(
        {
            "v2_blueprint": [item.v2_blueprint_id, item.v2_blueprint_revision],
            "approval_snapshot": item.v2_approval_snapshot_id,
            "projection_digest": item.projection_exact_digest,
            "truth_digest": item.product_truth_snapshot_digest,
            "formula": [item.formula_id, item.formula_version],
        }
    )


async def _record_usage(
    *,
    item,
    p6_plan_id: str,
    p6_item_id: str,
    usage_type: str,
    outcome_status: str = "OK",
    reason_code: str = "",
    campaign_key: str = "",
    actor_id: str,
) -> LandbankUsageV3:
    created_at = _now()
    authority_digest = _authority_digest(item)
    event_payload = {
        "manifest_item_id": item.item_id,
        "manifest": [item.manifest_id, item.manifest_revision],
        "v2_blueprint": [item.v2_blueprint_id, item.v2_blueprint_revision],
        "p6_plan_id": p6_plan_id,
        "p6_item_id": p6_item_id,
        "usage_type": usage_type,
        "outcome_status": outcome_status,
        "reason_code": reason_code,
        "created_at": created_at,
    }
    event = LandbankUsageV3(
        usage_id=deterministic_id("usev3", event_payload),
        product_id=item.product_id,
        master_id=item.master_id,
        master_revision=item.master_revision,
        projection_id=item.projection_id,
        projection_revision=item.projection_revision,
        v2_blueprint_id=item.v2_blueprint_id,
        v2_blueprint_revision=item.v2_blueprint_revision,
        v2_approval_snapshot_id=item.v2_approval_snapshot_id,
        materialization_link_id=item.materialization_link_id,
        materialization_link_revision=item.materialization_link_revision,
        manifest_id=item.manifest_id,
        manifest_revision=item.manifest_revision,
        manifest_item_id=item.item_id,
        p6_plan_id=p6_plan_id,
        p6_item_id=p6_item_id,
        duration_seconds=item.duration_seconds,
        campaign_key=campaign_key,
        usage_type=usage_type,
        outcome_status=outcome_status,
        reason_code=reason_code,
        authority_digest=authority_digest,
        event_digest=usage_event_digest(event_payload),
        created_at=created_at,
        created_by=actor_id,
    )
    await supply_repo.insert_usage_event(event)
    return event


async def allocate_from_manifest(
    manifest_id: str,
    revision: int,
    *,
    p6_plan_id: str,
    requested_items: int,
    actor_id: str,
    campaign_key: str = "",
    allow_exact_reuse: bool = False,
    p6_item_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Allocate up to ``requested_items`` FROZEN-manifest items to a P6 plan.

    Only a FROZEN manifest can be allocated.  Each item is revalidated against
    CURRENT authority; stale items are reported (never allocated).  A per-item
    selection is returned + an ALLOCATED usage event recorded.  The product-global
    activation pointer is NEVER touched.
    """

    if requested_items < 1:
        raise AllocationError(
            "ALLOCATION_COUNT_INVALID", "requested_items must be >= 1.", status_code=422
        )
    manifest = await supply_repo.get_manifest(manifest_id, revision)
    if manifest is None:
        raise AllocationError(
            "ALLOCATION_MANIFEST_NOT_FOUND",
            f"Manifest {manifest_id}:{revision} not found.",
            status_code=404,
        )
    if manifest.status != "FROZEN":
        raise AllocationError(
            "ALLOCATION_MANIFEST_NOT_FROZEN",
            "Only a FROZEN manifest can be allocated to production.",
            status_code=422,
            details={"status": manifest.status},
        )

    items = await supply_repo.list_manifest_items(manifest_id, revision)
    current_truth = await supply_status._current_truth(manifest.product_id)

    allocations: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    used_digests: set[str] = set()
    for item in items:
        if len(allocations) >= int(requested_items):
            break
        valid, reason, _blueprint = await _revalidate_selection(
            v2_blueprint_id=item.v2_blueprint_id,
            v2_blueprint_revision=item.v2_blueprint_revision,
            product_truth_snapshot_digest=item.product_truth_snapshot_digest,
            formula_id=item.formula_id,
            current_truth=current_truth,
            expected_approval_snapshot_id=item.v2_approval_snapshot_id,
        )
        if not valid:
            blocked.append({"manifest_item_id": item.item_id, "reason": reason})
            await _record_usage(
                item=item,
                p6_plan_id=p6_plan_id,
                p6_item_id=f"{p6_plan_id}:blocked:{item.item_index}",
                usage_type="BLOCKED",
                outcome_status="REVALIDATION_BLOCKED",
                reason_code=reason or "",
                campaign_key=campaign_key,
                actor_id=actor_id,
            )
            continue
        if not allow_exact_reuse and item.projection_exact_digest in used_digests:
            blocked.append(
                {"manifest_item_id": item.item_id, "reason": "EXACT_REUSE_BLOCKED_BY_POLICY"}
            )
            continue
        used_digests.add(item.projection_exact_digest)
        # Bind to a REAL P6 item row id when provided (Blocker 1); the synthetic
        # id path remains only for pure-allocation callers/tests without a plan.
        if p6_item_ids is not None and len(allocations) < len(p6_item_ids):
            p6_item_id = p6_item_ids[len(allocations)]
        else:
            p6_item_id = f"{p6_plan_id}:item:{len(allocations)}"
        await _record_usage(
            item=item,
            p6_plan_id=p6_plan_id,
            p6_item_id=p6_item_id,
            usage_type="ALLOCATED",
            campaign_key=campaign_key,
            actor_id=actor_id,
        )
        allocations.append(
            {
                "p6_item_id": p6_item_id,
                # Index matches the p6_item_id suffix (both are the pre-append
                # position); computed before append so the first item is 0, not -1.
                "p6_item_index": len(allocations),
                # This is the EXACT per-item production copy selection a P6 item
                # carries; it resolves copy directly, bypassing global activation.
                "round3_manifest_item": {
                    "manifest_id": item.manifest_id,
                    "manifest_revision": item.manifest_revision,
                    "manifest_item_id": item.item_id,
                    "v2_blueprint_id": item.v2_blueprint_id,
                    "v2_blueprint_revision": item.v2_blueprint_revision,
                    "v2_approval_snapshot_id": item.v2_approval_snapshot_id,
                    "product_truth_snapshot_digest": item.product_truth_snapshot_digest,
                    "formula_id": item.formula_id,
                    "duration_seconds": item.duration_seconds,
                },
            }
        )

    return {
        "manifest_id": manifest_id,
        "manifest_revision": revision,
        "p6_plan_id": p6_plan_id,
        "requested_items": int(requested_items),
        "allocated_count": len(allocations),
        "allocations": allocations,
        "blocked_count": len(blocked),
        "blocked": blocked,
        "shortfall": max(0, int(requested_items) - len(allocations)),
    }


async def revalidate_item_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Compile / queue / provider-start gate for ONE explicitly-selected P6 item.

    Reads and revalidates the exact selected blueprint (never the global pointer)
    and resolves the exact approved execution copy.  FAILS CLOSED on drift.
    """

    v2_blueprint_id = str(selection.get("v2_blueprint_id") or "")
    v2_blueprint_revision = int(selection.get("v2_blueprint_revision") or 0)
    if not v2_blueprint_id or v2_blueprint_revision < 1:
        return {"valid": False, "reason": "SELECTION_INVALID"}
    product_id = None
    blueprint = await _resolve_blueprint(v2_blueprint_id, v2_blueprint_revision)
    if blueprint is not None:
        product_id = blueprint.product_id
    current_truth = await supply_status._current_truth(product_id) if product_id else None
    valid, reason, blueprint = await _revalidate_selection(
        v2_blueprint_id=v2_blueprint_id,
        v2_blueprint_revision=v2_blueprint_revision,
        product_truth_snapshot_digest=str(selection.get("product_truth_snapshot_digest") or ""),
        formula_id=str(selection.get("formula_id") or (blueprint.formula_id if blueprint else "")),
        current_truth=current_truth,
    )
    if not valid or blueprint is None:
        return {
            "valid": False,
            "reason": reason or "SELECTION_INVALID",
            "v2_blueprint_id": v2_blueprint_id,
            "v2_blueprint_revision": v2_blueprint_revision,
        }
    current_snapshot_id = (
        blueprint.approval_snapshot.approval_snapshot_id
        if blueprint.approval_snapshot is not None
        else ""
    )
    # Defense-in-depth: the exact selected blueprint revision is immutable, but if
    # the caller's recorded approval snapshot no longer matches, fail closed rather
    # than execute copy the selection was not approved against.
    expected_snapshot_id = str(selection.get("v2_approval_snapshot_id") or "")
    if expected_snapshot_id and expected_snapshot_id != current_snapshot_id:
        return {
            "valid": False,
            "reason": "APPROVAL_SNAPSHOT_MISMATCH",
            "v2_blueprint_id": v2_blueprint_id,
            "v2_blueprint_revision": v2_blueprint_revision,
        }
    return {
        "valid": True,
        "v2_blueprint_id": v2_blueprint_id,
        "v2_blueprint_revision": v2_blueprint_revision,
        "v2_approval_snapshot_id": current_snapshot_id,
        "approved_execution_text": [
            {"stage_key": entry.stage_key, "text": entry.text}
            for entry in blueprint.approved_execution_text
        ],
    }


async def allocate_manifest_to_production_plan(
    *,
    production_plan_id: str,
    manifest_id: str,
    manifest_revision: int,
    requested_items: int,
    actor_id: str,
    campaign_key: str = "",
    allow_exact_reuse: bool = False,
) -> dict[str, Any]:
    """Persist a FROZEN manifest's validated selections onto REAL P6 item rows.

    Deterministically maps ``allocate_from_manifest`` selections onto the plan's
    actual ``creative_production_item`` rows and durably writes each item's exact
    ``round3_manifest_item`` (v2 blueprint revision + approval snapshot + copy
    digest).  Idempotent: the same (plan, manifest, revision) rebinds the same
    real items to the same selection JSON (no-op on re-run); a DIFFERENT selection
    already bound to a real item is a deterministic conflict, never a silent
    overwrite.  NEVER mutates ``copy_execution_authority_v2`` (the product-global
    interactive-lane pointer).
    """

    plan = await p6db.get_plan(production_plan_id)
    if plan is None:
        raise AllocationError(
            "ALLOCATION_PLAN_NOT_FOUND",
            f"Production plan {production_plan_id} not found.",
            status_code=404,
        )
    manifest = await supply_repo.get_manifest(manifest_id, manifest_revision)
    if manifest is None:
        raise AllocationError(
            "ALLOCATION_MANIFEST_NOT_FOUND",
            f"Manifest {manifest_id}:{manifest_revision} not found.",
            status_code=404,
        )

    # Real, eligible P6 item rows for this plan+product, in a stable order.
    eligible_items = [
        it
        for it in await p6db.list_items(production_plan_id)
        if str(it.get("product_id")) == str(manifest.product_id)
        and str(it.get("status")) in {"PLANNED", "COMPILED", "PENDING_APPROVAL"}
    ]
    def _summary(selection: dict[str, Any], item_id: str) -> dict[str, Any]:
        return {
            "p6_item_id": item_id,
            "manifest_item_id": selection.get("manifest_item_id"),
            "v2_blueprint_id": selection.get("v2_blueprint_id"),
            "v2_blueprint_revision": selection.get("v2_blueprint_revision"),
            "v2_approval_snapshot_id": selection.get("v2_approval_snapshot_id"),
        }

    # Idempotency: real items already carrying a selection are returned as-is and
    # are NEVER re-allocated (no duplicate usage events / no churn). Only unbound
    # eligible items consume fresh manifest allocation on this call.
    already_bound: list[dict[str, Any]] = []
    unbound_ids: list[str] = []
    for it in eligible_items:
        raw = str(it.get("round3_manifest_item_json") or "{}")
        if raw not in ("", "{}"):
            already_bound.append(_summary(json.loads(raw), str(it["item_id"])))
        else:
            unbound_ids.append(str(it["item_id"]))

    if not already_bound and not unbound_ids:
        raise AllocationError(
            "ALLOCATION_NO_ELIGIBLE_ITEMS",
            "No eligible production items to bind for this plan/product.",
            status_code=409,
            details={"eligible": 0},
        )

    target = min(int(requested_items), len(eligible_items))
    need = max(0, target - len(already_bound))
    newly_bound: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    if need > 0 and unbound_ids:
        assign_ids = unbound_ids[:need]
        result = await allocate_from_manifest(
            manifest_id,
            manifest_revision,
            p6_plan_id=production_plan_id,
            requested_items=len(assign_ids),
            actor_id=actor_id,
            campaign_key=campaign_key,
            allow_exact_reuse=allow_exact_reuse,
            p6_item_ids=assign_ids,
        )
        for alloc in result.get("allocations", []):
            item_id = str(alloc["p6_item_id"])
            selection = alloc["round3_manifest_item"]
            payload = json.dumps(selection, sort_keys=True, separators=(",", ":"))
            await p6db.update_item(
                item_id,
                round3_manifest_item_json=payload,
                updated_at=_now(),
            )
            newly_bound.append(_summary(selection, item_id))
        blocked = result.get("blocked", [])

    bound = already_bound + newly_bound
    return {
        "production_plan_id": production_plan_id,
        "manifest_id": manifest_id,
        "manifest_revision": manifest_revision,
        "bound_count": len(bound),
        "bound": bound,
        "blocked_count": len(blocked),
        "blocked": blocked,
        "shortfall": max(0, int(requested_items) - len(bound)),
    }
