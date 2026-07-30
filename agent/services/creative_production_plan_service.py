"""P6 production planning, capacity, creative DNA and approval authority."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from agent.db import creative_production_crud as p6db
from agent.db import crud
from agent.models.creative_production import (
    CapacityPreflightResponse,
    PoolAuthorityRequest,
    P58_COHORT_COUNT,
    P58_COHORT_SHA256,
    P58CohortAuthorityResponse,
    PlanStatus,
    ProductionPlanCreateRequest,
    ProductionPlanDetailResponse,
    ProductionPlanUpdateRequest,
    WaveAssignmentRequest,
)
from agent.services import avatar_registry
from agent.services import copy_rotation_service
from agent.services import poster_recipe_service
from agent.services.catalog_coverage_service import build_catalog_authority_matrix
from agent.services.scene_strategy_library import (
    build_scene_strategy_context,
    resolve_scene_strategy,
    select_scene_strategy_variant,
)


MAX_ENUMERATED_COMBINATIONS = 250_000


class CreativeProductionError(ValueError):
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, type(fallback)):
        return value
    try:
        decoded = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return decoded if isinstance(decoded, type(fallback)) else fallback


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key, fallback in (
        ("product_scope_json", []),
        ("model_keys_json", []),
        ("duration_seconds_json", []),
        ("pool_snapshot_json", {}),
        ("execution_policy_json", {}),
        ("capacity_snapshot_json", {}),
        ("compile_snapshot_json", {}),
        ("blockers_json", []),
        ("creative_dimensions_json", {}),
        ("prompt_package_json", {}),
        ("payload_snapshot_json", {}),
        ("provider_snapshot_json", {}),
        ("eligible_media_types_json", []),
        ("runtime_metadata_json", {}),
        ("checklist_json", {}),
        ("evidence_json", {}),
    ):
        if key in decoded:
            decoded[key.removesuffix("_json")] = _loads(decoded.pop(key), fallback)
    if "enabled" in decoded:
        decoded["enabled"] = bool(decoded["enabled"])
    if "credit_spend_intended" in decoded:
        decoded["credit_spend_intended"] = bool(
            decoded["credit_spend_intended"]
        )
    return decoded


def _unique(values: list[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


async def load_p58_cohort_authority() -> P58CohortAuthorityResponse:
    report = await build_catalog_authority_matrix()
    product_ids = sorted(report.p6_launch_cohort_product_ids)
    cohort_sha = _sha(product_ids)
    ready_rows = sorted(
        (row for row in report.products if row.product_id in set(product_ids)),
        key=lambda row: (row.product_name.casefold(), row.product_id),
    )
    return P58CohortAuthorityResponse(
        cohort_count=len(product_ids),
        cohort_sha256=cohort_sha,
        product_ids=product_ids,
        products=[
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "product_type_group": row.product_type_group,
                "scene_strategy_id": row.scene_strategy_id,
            }
            for row in ready_rows
        ],
        matches_frozen_authority=(
            len(product_ids) == P58_COHORT_COUNT
            and cohort_sha == P58_COHORT_SHA256
        ),
        p6_not_started=False,
    )


async def _assert_frozen_cohort(product_ids: list[str]) -> P58CohortAuthorityResponse:
    authority = await load_p58_cohort_authority()
    if not authority.matches_frozen_authority:
        raise CreativeProductionError(
            "P58_COHORT_AUTHORITY_DRIFT",
            "Current catalog authority does not match the frozen P5.8 cohort.",
            status_code=409,
            details={
                "expected_count": P58_COHORT_COUNT,
                "actual_count": authority.cohort_count,
                "expected_sha256": P58_COHORT_SHA256,
                "actual_sha256": authority.cohort_sha256,
            },
        )
    outside = sorted(set(product_ids) - set(authority.product_ids))
    if outside:
        raise CreativeProductionError(
            "PRODUCT_OUTSIDE_P58_COHORT",
            "Every P6 product must belong to the immutable P5.8 launch cohort.",
            status_code=409,
            details={"product_ids": outside},
        )
    return authority


def _request_snapshot(body: ProductionPlanCreateRequest) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude_none=False)


async def create_plan(body: ProductionPlanCreateRequest) -> dict[str, Any]:
    existing = await p6db.get_plan_by_request_id(body.request_id)
    request_snapshot = _request_snapshot(body)
    request_sha = _sha(request_snapshot)
    if existing is not None:
        policy = _loads(existing.get("execution_policy_json"), {})
        if policy.get("create_request_sha256") != request_sha:
            raise CreativeProductionError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                "request_id already identifies a different production plan.",
                status_code=409,
            )
        return _decode_row(existing)

    authority = await _assert_frozen_cohort(body.product_ids)
    policy = body.execution_policy.model_dump(mode="json")
    policy.update(
        {
            "create_request_sha256": request_sha,
            "live_execution_certified": False,
            "live_media_authorization_granted": False,
            "live_authorized_by": None,
            "live_authorized_at": None,
        }
    )
    plan_id = f"p6plan_{uuid.uuid4().hex[:20]}"
    row = await p6db.create_plan(
        {
            "plan_id": plan_id,
            "request_id": body.request_id,
            "created_by": body.operator_id.strip(),
            "name": body.name.strip(),
            "campaign_key": body.campaign_key.strip(),
            "product_scope_json": _stable_json(sorted(body.product_ids)),
            "p58_cohort_sha256": authority.cohort_sha256,
            "p58_cohort_count": authority.cohort_count,
            "target_video_count": body.target_video_count,
            "target_image_count": body.target_image_count,
            "target_poster_count": body.target_poster_count,
            "operating_window_hours": body.operating_window_hours,
            "allocation_strategy": body.allocation_strategy,
            "variation_strategy": body.variation_strategy,
            "logical_mode": body.logical_mode,
            "model_keys_json": _stable_json(body.model_keys),
            "duration_seconds_json": _stable_json(body.duration_seconds),
            "pool_snapshot_json": _stable_json(
                {
                    **body.pools.model_dump(mode="json"),
                    "controlled_reuse_reason": body.controlled_reuse_reason,
                    "controlled_reuse_max_per_dna": (
                        body.controlled_reuse_max_per_dna
                    ),
                }
            ),
            "execution_policy_json": _stable_json(policy),
            "status": PlanStatus.DRAFT.value,
        }
    )
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="CREATE_PLAN",
        source_state=None,
        target_state=PlanStatus.DRAFT.value,
        evidence={"create_request_sha256": request_sha},
    )
    return _decode_row(row)


async def list_plans(limit: int = 50) -> list[dict[str, Any]]:
    return [_decode_row(row) for row in await p6db.list_plans(limit)]


async def _require_plan(plan_id: str) -> dict[str, Any]:
    row = await p6db.get_plan(plan_id)
    if row is None:
        raise CreativeProductionError(
            "PLAN_NOT_FOUND",
            f"Production plan {plan_id} was not found.",
            status_code=404,
        )
    return row


async def record_audit_event(
    *,
    plan_id: str,
    request_id: str,
    actor_id: str,
    action: str,
    source_state: str | None,
    target_state: str | None,
    item_id: str | None = None,
    attempt_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await p6db.record_audit_event(
        {
            "event_id": f"p6audit_{uuid.uuid4().hex[:20]}",
            "plan_id": plan_id,
            "item_id": item_id,
            "attempt_id": attempt_id,
            "request_id": request_id,
            "actor_id": actor_id.strip(),
            "action": action,
            "source_state": source_state,
            "target_state": target_state,
            "evidence_json": _stable_json(evidence or {}),
            "created_at": _now(),
        }
    )


async def update_plan(
    plan_id: str,
    body: ProductionPlanUpdateRequest,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    if plan["status"] not in {
        PlanStatus.DRAFT.value,
        PlanStatus.PREFLIGHT_BLOCKED.value,
        PlanStatus.PREFLIGHT_READY.value,
    }:
        raise CreativeProductionError(
            "PLAN_CONFIGURATION_LOCKED",
            "Plan configuration is immutable after content materialization or approval.",
            status_code=409,
        )
    if await p6db.list_items(plan_id):
        raise CreativeProductionError(
            "PLAN_CONFIGURATION_LOCKED",
            "A materialized content matrix makes plan configuration immutable.",
            status_code=409,
        )

    patch = body.model_dump(mode="json", exclude_none=True)
    request_id = str(patch.pop("request_id"))
    operator_id = str(patch.pop("operator_id"))
    request_sha = _sha(patch)
    policy = _loads(plan.get("execution_policy_json"), {})
    prior_request_id = policy.get("last_update_request_id")
    if prior_request_id == request_id:
        if policy.get("last_update_request_sha256") != request_sha:
            raise CreativeProductionError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                "Update request already identifies a different plan mutation.",
                status_code=409,
            )
        return _decode_row(plan)

    current_targets = {
        "target_video_count": int(plan["target_video_count"]),
        "target_image_count": int(plan["target_image_count"]),
        "target_poster_count": int(plan["target_poster_count"]),
    }
    for field in current_targets:
        if field in patch:
            current_targets[field] = int(patch[field])
    if sum(current_targets.values()) <= 0:
        raise CreativeProductionError(
            "MEDIA_TARGET_REQUIRED",
            "At least one video, image or poster target is required.",
        )

    values: dict[str, Any] = {
        **current_targets,
        "capacity_snapshot_json": "{}",
        "compile_snapshot_json": "{}",
        "blockers_json": "[]",
        "status": PlanStatus.DRAFT.value,
        "updated_at": _now(),
    }
    scalar_fields = {
        "name",
        "campaign_key",
        "operating_window_hours",
        "allocation_strategy",
        "variation_strategy",
        "logical_mode",
    }
    for field in scalar_fields:
        if field in patch:
            values[field] = patch[field]
    if "model_keys" in patch:
        models = _unique(patch["model_keys"])
        if not models:
            raise CreativeProductionError(
                "MODEL_POOL_REQUIRED",
                "At least one non-empty model key is required.",
            )
        values["model_keys_json"] = _stable_json(models)
    if "duration_seconds" in patch:
        durations = sorted({int(value) for value in patch["duration_seconds"]})
        if not durations or any(value < 1 or value > 240 for value in durations):
            raise CreativeProductionError(
                "DURATION_POOL_INVALID",
                "Durations must be unique values between 1 and 240 seconds.",
            )
        values["duration_seconds_json"] = _stable_json(durations)
    if "pools" in patch:
        prior_pool = _loads(plan.get("pool_snapshot_json"), {})
        next_pool = {
            **patch["pools"],
            "controlled_reuse_reason": patch.get(
                "controlled_reuse_reason",
                prior_pool.get("controlled_reuse_reason"),
            ),
            "controlled_reuse_max_per_dna": patch.get(
                "controlled_reuse_max_per_dna",
                prior_pool.get("controlled_reuse_max_per_dna", 1),
            ),
        }
        values["pool_snapshot_json"] = _stable_json(next_pool)
    elif {
        "controlled_reuse_reason",
        "controlled_reuse_max_per_dna",
    } & set(patch):
        next_pool = _loads(plan.get("pool_snapshot_json"), {})
        if "controlled_reuse_reason" in patch:
            next_pool["controlled_reuse_reason"] = patch[
                "controlled_reuse_reason"
            ]
        if "controlled_reuse_max_per_dna" in patch:
            next_pool["controlled_reuse_max_per_dna"] = patch[
                "controlled_reuse_max_per_dna"
            ]
        values["pool_snapshot_json"] = _stable_json(next_pool)

    next_pool = _loads(
        values.get("pool_snapshot_json", plan.get("pool_snapshot_json")),
        {},
    )
    if (
        int(next_pool.get("controlled_reuse_max_per_dna") or 1) > 1
        and not str(next_pool.get("controlled_reuse_reason") or "").strip()
    ):
        raise CreativeProductionError(
            "CONTROLLED_REUSE_REASON_REQUIRED",
            "Exact DNA reuse requires an explicit reason and bounded reuse limit.",
        )
    policy.update(
        {
            "last_update_request_id": request_id,
            "last_update_request_sha256": request_sha,
            "last_updated_by": operator_id,
            "last_updated_at": _now(),
        }
    )
    values["execution_policy_json"] = _stable_json(policy)
    updated = await p6db.update_plan(plan_id, **values)
    await record_audit_event(
        plan_id=plan_id,
        request_id=request_id,
        actor_id=operator_id,
        action="UPDATE_PLAN",
        source_state=str(plan["status"]),
        target_state=PlanStatus.DRAFT.value,
        evidence={"update_request_sha256": request_sha},
    )
    return _decode_row(updated)


async def get_governed_pool_authority(
    body: PoolAuthorityRequest,
) -> dict[str, Any]:
    await _assert_frozen_cohort(body.product_ids)
    products = {
        product_id: await crud.get_product(product_id)
        for product_id in body.product_ids
    }
    copy_sets: list[dict[str, Any]] = []
    poster_copy_sets: list[dict[str, Any]] = []
    avatar_profiles: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    avatar_index = {
        str(row["avatar_code"]): row for row in avatar_registry.list_pool()
    }
    for product_id in body.product_ids:
        copy_sets.extend(
            await copy_rotation_service.list_eligible_copy_sets(product_id)
        )
        poster_copy_sets.extend(
            row
            for row in await crud.list_poster_copy_sets_for_product(product_id)
            if row.get("status") == "POSTER_COPY_APPROVED"
        )
        selection = await crud.get_creative_product_selection(product_id)
        avatar_code = str(
            (selection or {}).get("selected_avatar_code") or ""
        ).strip()
        profile = avatar_index.get(avatar_code)
        avatar_required = body.logical_mode in {"T2V", "HYBRID", "I2V"}
        selection_valid = (
            selection is not None
            and selection.get("status") == "APPROVED"
            and bool(avatar_code)
            and profile is not None
        )
        if avatar_required and not selection_valid:
            blockers.append(
                {
                    "code": "APPROVED_PRODUCT_AVATAR_SELECTION_REQUIRED",
                    "product_id": product_id,
                }
            )
            continue
        if not selection_valid:
            continue
        avatar_profiles.append(
            {
                **profile,
                "product_id": product_id,
                "selection_id": str(selection.get("selection_id") or ""),
                "selection_status": "APPROVED",
            }
        )

    assets = [
        row
        for row in await crud.list_creative_assets(status="ACTIVE", limit=1000)
        if row.get("review_status") == "APPROVED"
        and str(row.get("product_id") or "") in ("", *body.product_ids)
    ]
    recipes = [
        recipe.model_dump(mode="json")
        for recipe in poster_recipe_service.list_recipes()
    ]
    return {
        "product_ids": sorted(body.product_ids),
        "logical_mode": body.logical_mode,
        "products": [products[pid] for pid in body.product_ids if products[pid]],
        "copy_sets": copy_sets,
        "poster_copy_sets": poster_copy_sets,
        "avatar_profiles": avatar_profiles,
        "product_reference_assets": [
            row for row in assets if row.get("semantic_role") == "PRODUCT_REFERENCE"
        ],
        "finished_frame_assets": [
            row
            for row in assets
            if row.get("semantic_role") == "COMPOSITE_FRAME_REFERENCE"
        ],
        "character_assets": [
            row for row in assets if row.get("semantic_role") == "CHARACTER_REFERENCE"
        ],
        "scene_assets": [
            row
            for row in assets
            if row.get("semantic_role") == "SCENE_CONTEXT_REFERENCE"
        ],
        "style_assets": [
            row
            for row in assets
            if row.get("semantic_role") == "STYLE_REFERENCE"
        ],
        "poster_recipes": recipes,
        "blockers": blockers,
        "copy_reuse_cap": copy_rotation_service.REUSE_CAP,
        "near_duplicate_threshold": 0.80,
        "credit_spend": 0,
    }


async def get_plan_detail(plan_id: str) -> ProductionPlanDetailResponse:
    plan = await _require_plan(plan_id)
    waves = await p6db.list_waves(plan_id)
    batches = await p6db.list_batches(plan_id)
    items = await p6db.list_items(plan_id)
    attempts = await p6db.list_attempts(plan_id)
    qa = await p6db.list_qa(plan_id)
    audit_events = await p6db.list_audit_events(plan_id)
    counts = Counter(str(item["status"]) for item in items)
    terminal = sum(
        counts[state]
        for state in (
            "QA_APPROVED",
            "QA_REJECTED",
            "FAILED",
            "CANCELLED",
            "SUPERSEDED",
        )
    )
    return ProductionPlanDetailResponse(
        plan=_decode_row(plan),
        waves=[_decode_row(row) for row in waves],
        batches=[_decode_row(row) for row in batches],
        items=[_decode_row(row) for row in items],
        attempts=[_decode_row(row) for row in attempts],
        qa=[_decode_row(row) for row in qa],
        audit_events=[_decode_row(row) for row in audit_events],
        progress={
            "total": len(items),
            "terminal": terminal,
            "percent": round((terminal / len(items)) * 100, 2) if items else 0.0,
            "by_status": dict(sorted(counts.items())),
        },
    )


async def _load_approved_pools(plan: dict[str, Any]) -> dict[str, Any]:
    pool = _loads(plan.get("pool_snapshot_json"), {})
    product_ids = _loads(plan.get("product_scope_json"), [])
    blockers: list[dict[str, Any]] = []
    logical_mode = str(plan["logical_mode"])
    target_video_count = int(plan["target_video_count"])

    products: dict[str, dict[str, Any]] = {}
    for product_id in product_ids:
        row = await crud.get_product(product_id)
        if row is None:
            blockers.append(
                {"code": "PRODUCT_NOT_FOUND", "product_id": product_id}
            )
        else:
            products[product_id] = row

    catalog = await build_catalog_authority_matrix()
    catalog_rows = {
        row.product_id: row
        for row in catalog.products
        if row.product_id in set(product_ids)
    }
    scene_strategies: dict[str, dict[str, Any]] = {}
    creative_selections: dict[str, dict[str, Any]] = {}
    for product_id, product in products.items():
        authority = catalog_rows.get(product_id)
        if authority is None or authority.terminal_state != "P6_READY":
            blockers.append(
                {
                    "code": "PRODUCT_NO_LONGER_P6_READY",
                    "product_id": product_id,
                }
            )
            continue
        strategy = resolve_scene_strategy(product)
        if (
            strategy["fallback_used"]
            or strategy["strategy_id"] != authority.scene_strategy_id
        ):
            blockers.append(
                {
                    "code": "P58_SCENE_STRATEGY_MISMATCH",
                    "product_id": product_id,
                    "expected": authority.scene_strategy_id,
                    "actual": strategy["strategy_id"],
                    "fallback_used": strategy["fallback_used"],
                }
            )
            continue
        scene_strategies[product_id] = strategy
        selection = await crud.get_creative_product_selection(product_id)
        if selection is not None:
            creative_selections[product_id] = selection

    copy_sets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for copy_set_id in _unique(pool.get("copy_set_ids") or []):
        row = await crud.get_copy_set(copy_set_id)
        if (
            row is None
            or row.get("status") != "COPY_APPROVED"
            or int(row.get("archived") or 0)
            or int(row.get("usage_count") or 0)
            >= copy_rotation_service.REUSE_CAP
        ):
            blockers.append(
                {
                    "code": "COPY_SET_NOT_ROTATION_ELIGIBLE",
                    "copy_set_id": copy_set_id,
                }
            )
            continue
        product_id = str(row.get("product_id") or "")
        if product_id not in products:
            blockers.append(
                {
                    "code": "COPY_SET_PRODUCT_OUT_OF_SCOPE",
                    "copy_set_id": copy_set_id,
                    "product_id": product_id,
                }
            )
            continue
        copy_sets[product_id].append(row)

    poster_copy_sets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for copy_set_id in _unique(pool.get("poster_copy_set_ids") or []):
        row = await crud.get_poster_copy_set(copy_set_id)
        if row is None or row.get("status") != "POSTER_COPY_APPROVED":
            blockers.append(
                {
                    "code": "POSTER_COPY_SET_NOT_APPROVED",
                    "poster_copy_set_id": copy_set_id,
                }
            )
            continue
        product_id = str(row.get("product_id") or "")
        if product_id not in products:
            blockers.append(
                {
                    "code": "POSTER_COPY_SET_PRODUCT_OUT_OF_SCOPE",
                    "poster_copy_set_id": copy_set_id,
                    "product_id": product_id,
                }
            )
            continue
        poster_copy_sets[product_id].append(row)

    avatar_index = {
        str(row["avatar_code"]): row for row in avatar_registry.list_pool()
    }
    requested_avatar_codes = _unique(pool.get("avatar_codes") or [])
    avatar_profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    approved_codes: set[str] = set()
    for product_id in products:
        selection = creative_selections.get(product_id)
        selected_code = str(
            (selection or {}).get("selected_avatar_code") or ""
        ).strip()
        profile = avatar_index.get(selected_code)
        avatar_required = (
            target_video_count > 0 and logical_mode in {"T2V", "HYBRID", "I2V"}
        )
        if (
            avatar_required
            and (
                selection is None
                or selection.get("status") != "APPROVED"
                or not selected_code
                or profile is None
            )
        ):
            blockers.append(
                {
                    "code": "APPROVED_PRODUCT_AVATAR_SELECTION_REQUIRED",
                    "product_id": product_id,
                }
            )
            continue
        if not selected_code or profile is None:
            continue
        if selected_code not in requested_avatar_codes:
            if avatar_required:
                blockers.append(
                    {
                        "code": "APPROVED_PRODUCT_AVATAR_NOT_IN_PLAN_POOL",
                        "product_id": product_id,
                        "avatar_code": selected_code,
                    }
                )
            continue
        age_band = str(profile.get("age_band") or "").lower()
        if "child" in age_band or "teen" in age_band:
            blockers.append(
                {
                    "code": "MINOR_AVATAR_NOT_PERMITTED_IN_P6_AUTOMATION",
                    "product_id": product_id,
                    "avatar_code": selected_code,
                    "age_band": profile.get("age_band"),
                }
            )
            continue
        approved_codes.add(selected_code)
        avatar_profiles[product_id].append(
            {
                **profile,
                "selection_id": str(selection.get("selection_id") or ""),
                "selection_status": "APPROVED",
            }
        )
    for avatar_code in requested_avatar_codes:
        if avatar_code not in approved_codes:
            blockers.append(
                {
                    "code": "AVATAR_CODE_HAS_NO_APPROVED_PRODUCT_LINK",
                    "avatar_code": avatar_code,
                }
            )

    assets: dict[str, dict[str, Any]] = {}
    role_expectations = {
        "product_reference_asset_ids": "PRODUCT_REFERENCE",
        "finished_frame_asset_ids": "COMPOSITE_FRAME_REFERENCE",
        "character_asset_ids": "CHARACTER_REFERENCE",
        "scene_asset_ids": "SCENE_CONTEXT_REFERENCE",
        "style_asset_ids": "STYLE_REFERENCE",
    }
    for pool_key, expected_role in role_expectations.items():
        for asset_id in _unique(pool.get(pool_key) or []):
            row = await crud.get_creative_asset(asset_id)
            if (
                row is None
                or row.get("status") != "ACTIVE"
                or row.get("review_status") != "APPROVED"
                or row.get("semantic_role") != expected_role
            ):
                blockers.append(
                    {
                        "code": "ASSET_NOT_APPROVED_FOR_POOL",
                        "asset_id": asset_id,
                        "expected_role": expected_role,
                    }
                )
                continue
            asset_product_id = str(row.get("product_id") or "")
            if asset_product_id and asset_product_id not in products:
                blockers.append(
                    {
                        "code": "ASSET_PRODUCT_OUT_OF_SCOPE",
                        "asset_id": asset_id,
                        "product_id": asset_product_id,
                    }
                )
                continue
            if not any(
                str(row.get(field) or "").strip()
                for field in (
                    "media_id",
                    "local_file_path",
                    "remote_source_url",
                    "preview_url",
                    "download_url",
                )
            ):
                blockers.append(
                    {
                        "code": "ASSET_SOURCE_NOT_READY",
                        "asset_id": asset_id,
                    }
                )
                continue
            failed_governance = [
                field
                for field in (
                    "product_truth_status",
                    "identity_lock_status",
                    "scale_truth_status",
                    "claim_safety_status",
                )
                if str(row.get(field) or "").upper()
                in {"FAIL", "FAILED", "REJECTED", "BLOCKED"}
            ]
            if failed_governance:
                blockers.append(
                    {
                        "code": "ASSET_GOVERNANCE_BLOCKED",
                        "asset_id": asset_id,
                        "fields": failed_governance,
                    }
                )
                continue
            assets[asset_id] = row

    layout_ids = _unique(pool.get("layout_ids") or [])
    approved_layouts = {
        layout_id: poster_recipe_service.get_recipe(layout_id)
        for layout_id in layout_ids
    }
    for layout_id, recipe in approved_layouts.items():
        if recipe is None:
            blockers.append(
                {
                    "code": "POSTER_RECIPE_NOT_FOUND",
                    "layout_id": layout_id,
                }
            )

    return {
        "raw": pool,
        "products": products,
        "copy_sets": copy_sets,
        "poster_copy_sets": poster_copy_sets,
        "avatar_profiles": avatar_profiles,
        "assets": assets,
        "approved_layouts": {
            key: value
            for key, value in approved_layouts.items()
            if value is not None
        },
        "scene_strategies": scene_strategies,
        "creative_selections": creative_selections,
        "blockers": blockers,
    }


def _asset_rows_for_product(
    approved: dict[str, Any],
    pool_key: str,
    product_id: str,
) -> list[dict[str, Any]]:
    raw_ids = _unique(approved["raw"].get(pool_key) or [])
    return [
        approved["assets"][asset_id]
        for asset_id in raw_ids
        if asset_id in approved["assets"]
        and str(approved["assets"][asset_id].get("product_id") or "")
        in ("", product_id)
    ]


def _avatar_code_from_asset(asset: dict[str, Any]) -> str:
    description = str(asset.get("description") or "")
    marker = "AVATAR_CODE:"
    if marker not in description:
        return ""
    return (
        description.split(marker, 1)[1]
        .split()[0]
        .strip()
        .upper()
    )


def _copy_dimensions(copy: dict[str, Any], threshold: float) -> dict[str, str]:
    try:
        usp_set = json.loads(copy.get("usp_set_json") or "[]")
    except (TypeError, ValueError):
        usp_set = []
    bundle = {
        "angle": str(copy.get("angle") or ""),
        "hook": str(copy.get("hook") or ""),
        "subhook": str(copy.get("subhook") or ""),
        "usp_set": usp_set if isinstance(usp_set, list) else [],
        "cta": str(copy.get("cta") or ""),
        "formula_family": str(copy.get("formula_family") or ""),
    }
    score = float(copy.get("similarity_score") or 0.0)
    return {
        "copy_set_id": str(
            copy.get("poster_copy_set_id")
            or copy.get("copy_set_id")
            or ""
        ),
        "copy_identity_sha256": _sha(bundle),
        "marketing_angle": str(
            copy.get("angle")
            or copy.get("archetype")
            or copy.get("primary_message")
            or ""
        ),
        "hook": str(copy.get("hook") or copy.get("headline") or ""),
        "cta": str(copy.get("cta") or ""),
        "formula_family": str(copy.get("formula_family") or ""),
        "claim_safety_status": "APPROVED",
        "copy_usage_count": str(int(copy.get("usage_count") or 0)),
        "near_duplicate_status": (
            "WARNING" if score >= threshold else "CLEAR"
        ),
        "near_duplicate_score": str(score),
        "similar_to_copy_set_id": str(
            copy.get("similar_to_copy_set_id") or ""
        ),
    }


def _scene_variants(
    approved: dict[str, Any],
    product_id: str,
) -> list[dict[str, str]]:
    strategy = approved["scene_strategies"].get(product_id)
    if strategy is None:
        return []
    count = max(
        len(strategy["allowed_scene_strategy"]),
        len(strategy["allowed_actions"]),
        len(strategy["scene_contexts"]),
        len(strategy["camera_routes"]),
        1,
    )
    variants: list[dict[str, str]] = []
    for index in range(count):
        selected = select_scene_strategy_variant(strategy, index)
        variants.append(
            {
                "scene_strategy_id": selected["scene_strategy_id"],
                "scene_family": selected["scene_strategy_id"],
                "scene_strategy": selected["allowed_scene_strategy"],
                "scene_context": selected["scene_context"],
                "product_interaction": selected["allowed_action"],
                "camera_composition": selected["camera_route"],
                "strategy_avatar_hint": selected["avatar_hint"],
                "strategy_wardrobe_hint": selected["wardrobe_hint"],
                "scene_strategy_context": build_scene_strategy_context(
                    strategy,
                    variation_index=index,
                ),
            }
        )
    return variants


def _creative_dna_payload(dimensions: dict[str, str]) -> dict[str, str]:
    governed_fields = (
        "product_id",
        "media_type",
        "logical_mode",
        "copy_set_id",
        "copy_identity_sha256",
        "marketing_angle",
        "hook",
        "cta",
        "avatar_code",
        "age_band",
        "wardrobe",
        "avatar_variant",
        "product_reference_asset_id",
        "finished_frame_asset_id",
        "character_asset_id",
        "scene_asset_id",
        "scene_strategy_id",
        "scene_family",
        "scene_strategy",
        "scene_context",
        "style_asset_id",
        "layout_id",
        "camera_composition",
        "product_interaction",
        "model_key",
        "duration_seconds",
    )
    return {field: str(dimensions.get(field) or "") for field in governed_fields}


def _product_dimension_rows(
    *,
    plan: dict[str, Any],
    approved: dict[str, Any],
    product_id: str,
    media_type: str,
) -> tuple[int, list[dict[str, str]], list[dict[str, Any]]]:
    raw = approved["raw"]
    layouts = [
        layout_id
        for layout_id in _unique(raw.get("layout_ids") or [])
        if layout_id in approved["approved_layouts"]
    ]
    avatar_profiles = approved["avatar_profiles"].get(product_id) or []
    product_refs = _asset_rows_for_product(
        approved,
        "product_reference_asset_ids",
        product_id,
    )
    finished_frames = _asset_rows_for_product(
        approved,
        "finished_frame_asset_ids",
        product_id,
    )
    characters = _asset_rows_for_product(
        approved,
        "character_asset_ids",
        product_id,
    )
    scenes = _asset_rows_for_product(
        approved,
        "scene_asset_ids",
        product_id,
    )
    styles = _asset_rows_for_product(
        approved,
        "style_asset_ids",
        product_id,
    )
    strategy_variants = _scene_variants(approved, product_id)
    logical_mode = str(plan["logical_mode"])
    model_keys = _loads(plan.get("model_keys_json"), [])
    durations = _loads(plan.get("duration_seconds_json"), [])
    policy = _loads(plan.get("execution_policy_json"), {})
    near_threshold = float(policy.get("near_duplicate_threshold") or 0.80)
    blockers: list[dict[str, Any]] = []

    if media_type == "POSTER":
        copies = approved["poster_copy_sets"].get(product_id) or []
        if not copies:
            blockers.append(
                {"code": "NO_APPROVED_POSTER_COPY", "product_id": product_id}
            )
        if not layouts:
            blockers.append(
                {"code": "NO_APPROVED_LAYOUT_POOL", "product_id": product_id}
            )
        visual_rows = [
            {
                "product_reference_asset_id": "",
                "finished_frame_asset_id": "",
                "character_asset_id": "",
                "avatar_code": "",
                "age_band": "",
                "wardrobe": "",
                "avatar_variant": "",
                "scene_asset_id": str(scene.get("asset_id") or ""),
                "style_asset_id": str(style.get("asset_id") or ""),
            }
            for scene, style in itertools.product(scenes or [{}], styles or [{}])
        ]
    else:
        copies = approved["copy_sets"].get(product_id) or []
        if not copies:
            blockers.append(
                {"code": "NO_APPROVED_COPY", "product_id": product_id}
            )
        layouts = layouts or [""]
        if media_type == "VIDEO" and logical_mode == "T2V":
            if not avatar_profiles:
                blockers.append(
                    {"code": "NO_APPROVED_AVATAR_POOL", "product_id": product_id}
                )
            visual_rows = [
                {
                    "product_reference_asset_id": "",
                    "finished_frame_asset_id": "",
                    "character_asset_id": "",
                    "avatar_code": str(avatar.get("avatar_code") or ""),
                    "age_band": str(avatar.get("age_band") or ""),
                    "wardrobe": str(avatar.get("wardrobe") or ""),
                    "avatar_variant": str(avatar.get("variant") or ""),
                    "scene_asset_id": str(scene.get("asset_id") or ""),
                    "style_asset_id": str(style.get("asset_id") or ""),
                }
                for avatar, scene, style in itertools.product(
                    avatar_profiles,
                    scenes or [{}],
                    styles or [{}],
                )
            ]
        elif media_type == "VIDEO" and logical_mode == "HYBRID":
            if not avatar_profiles:
                blockers.append(
                    {"code": "NO_APPROVED_AVATAR_POOL", "product_id": product_id}
                )
            if not product_refs:
                blockers.append(
                    {
                        "code": "NO_APPROVED_PRODUCT_REFERENCE_POOL",
                        "product_id": product_id,
                    }
                )
            visual_rows = [
                {
                    "product_reference_asset_id": str(ref.get("asset_id") or ""),
                    "finished_frame_asset_id": "",
                    "character_asset_id": "",
                    "avatar_code": str(avatar.get("avatar_code") or ""),
                    "age_band": str(avatar.get("age_band") or ""),
                    "wardrobe": str(avatar.get("wardrobe") or ""),
                    "avatar_variant": str(avatar.get("variant") or ""),
                    "scene_asset_id": str(scene.get("asset_id") or ""),
                    "style_asset_id": str(style.get("asset_id") or ""),
                }
                for avatar, ref, scene, style in itertools.product(
                    avatar_profiles,
                    product_refs,
                    scenes or [{}],
                    styles or [{}],
                )
            ]
        elif media_type == "VIDEO" and logical_mode == "F2V":
            if not finished_frames:
                blockers.append(
                    {
                        "code": "NO_APPROVED_FINISHED_FRAME_POOL",
                        "product_id": product_id,
                    }
                )
            visual_rows = [
                {
                    "product_reference_asset_id": "",
                    "finished_frame_asset_id": str(frame.get("asset_id") or ""),
                    "character_asset_id": "",
                    "avatar_code": "",
                    "age_band": "",
                    "wardrobe": "",
                    "avatar_variant": "",
                    "scene_asset_id": "",
                    "style_asset_id": "",
                }
                for frame in finished_frames
            ]
        elif media_type == "VIDEO" and logical_mode == "I2V":
            if not characters:
                blockers.append(
                    {
                        "code": "NO_APPROVED_CHARACTER_REFERENCE_POOL",
                        "product_id": product_id,
                    }
                )
            visual_rows = []
            for ref, character, scene, style in itertools.product(
                product_refs or [{}],
                characters,
                scenes or [{}],
                styles or [{}],
            ):
                avatar_code = _avatar_code_from_asset(character)
                selection = approved["creative_selections"].get(product_id) or {}
                if (
                    not avatar_code
                    or selection.get("status") != "APPROVED"
                    or avatar_code
                    != str(selection.get("selected_avatar_code") or "").upper()
                ):
                    blockers.append(
                        {
                            "code": "CHARACTER_ASSET_AVATAR_LINK_NOT_APPROVED",
                            "product_id": product_id,
                            "asset_id": character.get("asset_id"),
                        }
                    )
                    continue
                profile = next(
                    (
                        value
                        for value in avatar_profiles
                        if str(value.get("avatar_code") or "").upper()
                        == avatar_code
                    ),
                    {},
                )
                visual_rows.append(
                    {
                        "product_reference_asset_id": str(
                            ref.get("asset_id") or ""
                        ),
                        "finished_frame_asset_id": "",
                        "character_asset_id": str(
                            character.get("asset_id") or ""
                        ),
                        "avatar_code": avatar_code,
                        "age_band": str(profile.get("age_band") or ""),
                        "wardrobe": str(profile.get("wardrobe") or ""),
                        "avatar_variant": str(profile.get("variant") or ""),
                        "scene_asset_id": str(scene.get("asset_id") or ""),
                        "style_asset_id": str(style.get("asset_id") or ""),
                    }
                )
        else:
            product = approved["products"].get(product_id) or {}
            if not any(
                str(product.get(field) or "").strip()
                for field in ("media_id", "local_image_path", "image_url")
            ):
                blockers.append(
                    {
                        "code": "PRODUCT_REFERENCE_IMAGE_REQUIRED",
                        "product_id": product_id,
                    }
                )
            visual_rows = [
                {
                    "product_reference_asset_id": str(ref.get("asset_id") or ""),
                    "finished_frame_asset_id": "",
                    "character_asset_id": str(character.get("asset_id") or ""),
                    "avatar_code": _avatar_code_from_asset(character),
                    "age_band": "",
                    "wardrobe": "",
                    "avatar_variant": "",
                    "scene_asset_id": str(scene.get("asset_id") or ""),
                    "style_asset_id": str(style.get("asset_id") or ""),
                }
                for ref, character, scene, style in itertools.product(
                    product_refs or [{}],
                    characters or [{}],
                    scenes or [{}],
                    styles or [{}],
                )
            ]

    if not strategy_variants:
        blockers.append(
            {
                "code": "P58_SPECIFIC_SCENE_STRATEGY_REQUIRED",
                "product_id": product_id,
            }
        )
    if not model_keys:
        blockers.append(
            {"code": "MODEL_POOL_REQUIRED", "product_id": product_id}
        )
    if not durations:
        blockers.append(
            {"code": "DURATION_POOL_REQUIRED", "product_id": product_id}
        )
    if not visual_rows:
        blockers.append(
            {
                "code": "VISUAL_POOL_EMPTY",
                "product_id": product_id,
                "media_type": media_type,
            }
        )

    factors = (
        len(copies),
        len(visual_rows),
        len(strategy_variants),
        len(layouts),
        len(model_keys),
        len(durations),
    )
    capacity = math.prod(factors)
    if capacity > MAX_ENUMERATED_COMBINATIONS:
        blockers.append(
            {
                "code": "CAPACITY_ENUMERATION_LIMIT",
                "product_id": product_id,
                "media_type": media_type,
                "combination_count": capacity,
                "limit": MAX_ENUMERATED_COMBINATIONS,
            }
        )
        return capacity, [], blockers

    rows: list[dict[str, str]] = []
    for copy, visual, scene_variant, layout, model_key, duration in itertools.product(
        copies,
        visual_rows,
        strategy_variants,
        layouts,
        model_keys,
        durations,
    ):
        copy_fields = _copy_dimensions(copy, near_threshold)
        scene_asset = approved["assets"].get(visual["scene_asset_id"]) or {}
        base_scene = str(
            scene_asset.get("scene_context_dna")
            or scene_asset.get("visual_dna_summary")
            or scene_asset.get("description")
            or ""
        ).strip()
        strategy = approved["scene_strategies"][product_id]
        strategy_index = strategy_variants.index(scene_variant)
        scene_context = build_scene_strategy_context(
            strategy,
            variation_index=strategy_index,
            base_scene_context=base_scene or None,
        )
        rows.append(
            {
                "product_id": product_id,
                "media_type": media_type,
                "logical_mode": logical_mode if media_type == "VIDEO" else "IMG",
                **copy_fields,
                **visual,
                **scene_variant,
                "scene_context": scene_context,
                "layout_id": layout,
                "model_key": str(model_key),
                "duration_seconds": str(duration),
                "exact_duplicate_status": "UNIQUE",
                "quota_status": "WITHIN_POLICY",
                "readiness": "PREFLIGHT_ELIGIBLE",
                "blockers": "",
            }
        )
    return capacity, rows, blockers


async def _capacity_candidates(
    plan: dict[str, Any],
) -> tuple[
    dict[str, int],
    dict[str, list[tuple[str, dict[str, str]]]],
    dict[str, Any],
    list[dict[str, Any]],
    int,
]:
    approved = await _load_approved_pools(plan)
    blockers = list(approved["blockers"])
    product_ids = _loads(plan.get("product_scope_json"), [])
    candidates: dict[str, list[tuple[str, dict[str, str]]]] = {
        "VIDEO": [],
        "IMAGE": [],
        "POSTER": [],
    }
    raw_capacity = {"VIDEO": 0, "IMAGE": 0, "POSTER": 0}
    target_by_media = {
        "VIDEO": int(plan["target_video_count"]),
        "IMAGE": int(plan["target_image_count"]),
        "POSTER": int(plan["target_poster_count"]),
    }

    for media_type in candidates:
        if target_by_media[media_type] == 0:
            continue
        for product_id in product_ids:
            capacity, dimensions, product_blockers = _product_dimension_rows(
                plan=plan,
                approved=approved,
                product_id=product_id,
                media_type=media_type,
            )
            raw_capacity[media_type] += capacity
            blockers.extend(product_blockers)
            for dimension in dimensions:
                dna = _sha(_creative_dna_payload(dimension))
                candidates[media_type].append((dna, dimension))

    all_hashes = [
        dna for media_rows in candidates.values() for dna, _ in media_rows
    ]
    historical = await p6db.list_historical_dna(product_ids, all_hashes)
    if historical:
        candidates = {
            media_type: [
                (dna, dimension)
                for dna, dimension in rows
                if dna not in historical
            ]
            for media_type, rows in candidates.items()
        }

    copy_capacity_slots = 0
    capped_candidates: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for media_type, rows in candidates.items():
        if media_type == "POSTER":
            capped_candidates[media_type] = rows
            continue
        used_per_copy: Counter[str] = Counter()
        eligible_rows: list[tuple[str, dict[str, str]]] = []
        for dna, dimension in rows:
            copy_set_id = dimension["copy_set_id"]
            historical_usage = int(dimension.get("copy_usage_count") or 0)
            remaining = max(
                copy_rotation_service.REUSE_CAP - historical_usage,
                0,
            )
            if used_per_copy[copy_set_id] >= remaining:
                continue
            used_per_copy[copy_set_id] += 1
            eligible_rows.append((dna, dimension))
        copy_capacity_slots += len(eligible_rows)
        capped_candidates[media_type] = eligible_rows
    candidates = capped_candidates

    approved_counts = {
        "products": len(approved["products"]),
        "copy_sets": sum(len(rows) for rows in approved["copy_sets"].values()),
        "poster_copy_sets": sum(
            len(rows) for rows in approved["poster_copy_sets"].values()
        ),
        "avatars": len(
            _unique(approved["raw"].get("avatar_codes") or [])
        ),
        "product_references": len(
            _unique(
                approved["raw"].get("product_reference_asset_ids") or []
            )
        ),
        "finished_frames": len(
            _unique(approved["raw"].get("finished_frame_asset_ids") or [])
        ),
        "character_references": len(
            _unique(approved["raw"].get("character_asset_ids") or [])
        ),
        "scenes": len(_unique(approved["raw"].get("scene_asset_ids") or [])),
        "styles": len(_unique(approved["raw"].get("style_asset_ids") or [])),
        "layouts": len(_unique(approved["raw"].get("layout_ids") or [])),
        "models": len(_loads(plan.get("model_keys_json"), [])),
        "durations": len(_loads(plan.get("duration_seconds_json"), [])),
        "copy_capacity_slots": copy_capacity_slots,
    }
    return raw_capacity, candidates, approved_counts, blockers, len(historical)


async def _lane_window_capacity(
    requested: dict[str, int],
    operating_window_hours: int,
) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, Any]]:
    lanes = await p6db.list_lanes()
    capacity = {"VIDEO": 0, "IMAGE": 0, "POSTER": 0}
    blockers: list[dict[str, Any]] = []
    lane_evidence: dict[str, Any] = {}
    for media_type, target in requested.items():
        if target <= 0:
            continue
        eligible = [
            lane
            for lane in lanes
            if bool(lane.get("enabled"))
            and lane.get("runtime_proof_status") == "VERIFIED"
            and media_type
            in _loads(lane.get("eligible_media_types_json"), [])
        ]
        if not eligible:
            blockers.append(
                {
                    "code": "NO_VERIFIED_EXECUTION_LANE",
                    "media_type": media_type,
                    "requested": target,
                }
            )
            lane_evidence[media_type] = {
                "verified_lanes": 0,
                "planning_capacity": 0,
                "evidence_class": "NO_RUNTIME_PROOF",
            }
            continue
        media_capacity = 0
        details: list[dict[str, Any]] = []
        for lane in eligible:
            interval = max(int(lane.get("interval_seconds") or 0), 1)
            cycle = max(int(lane.get("cooldown_after_n_jobs") or 0), 1)
            cooldown = int(lane.get("cooldown_seconds") or 0)
            # Authority: batch-production research report section 09. Generation
            # plus polling remains assumption-bound at the nominal 300 seconds.
            effective_seconds = interval + 300 + (cooldown / cycle)
            lane_capacity = math.floor(
                (
                    operating_window_hours
                    * 3600
                    * int(lane.get("verified_max_inflight") or 1)
                )
                / effective_seconds
                * 0.90
            )
            media_capacity += lane_capacity
            details.append(
                {
                    "lane_id": lane["lane_id"],
                    "verified_max_inflight": lane["verified_max_inflight"],
                    "health_status": lane["health_status"],
                    "planning_capacity": lane_capacity,
                }
            )
        capacity[media_type] = media_capacity
        lane_evidence[media_type] = {
            "verified_lanes": len(eligible),
            "planning_capacity": media_capacity,
            "evidence_class": "THEORETICAL_NOMINAL_NOT_RUNTIME_SLA",
            "nominal_generation_plus_retrieval_seconds": 300,
            "failure_allowance_multiplier": 0.90,
            "lanes": details,
        }
        if target > media_capacity:
            blockers.append(
                {
                    "code": "OPERATING_WINDOW_CAPACITY_SHORTFALL",
                    "media_type": media_type,
                    "requested": target,
                    "available": media_capacity,
                    "shortfall": target - media_capacity,
                    "evidence_class": "THEORETICAL_NOMINAL_NOT_RUNTIME_SLA",
                }
            )
    return capacity, blockers, lane_evidence


def _capacity_remediation(
    blockers: list[dict[str, Any]],
    pool_counts: dict[str, int],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        if "COPY" in code:
            action = "Add or approve product-bound Copy Sets under the reuse cap."
        elif "AVATAR" in code or "CHARACTER" in code:
            action = (
                "Approve a product-first Avatar Registry selection and linked "
                "CHARACTER_REFERENCE where the selected mode requires one."
            )
        elif "SCENE" in code:
            action = "Restore the exact P5.8 scene strategy or add approved scene assets."
        elif "LAYOUT" in code or "RECIPE" in code:
            action = "Select an existing authoritative poster recipe."
        elif "LANE" in code or "OPERATING_WINDOW" in code:
            action = (
                "Reduce the target/window pressure or separately prove and enable "
                "additional execution-lane capacity."
            )
        elif "CAPACITY" in code:
            smallest = min(
                (
                    (key, value)
                    for key, value in pool_counts.items()
                    if key
                    in {
                        "copy_sets",
                        "avatars",
                        "scenes",
                        "styles",
                        "layouts",
                        "models",
                        "durations",
                    }
                ),
                key=lambda item: (item[1], item[0]),
                default=("governed_pool", 0),
            )
            action = f"Expand governed dimension {smallest[0]} (current {smallest[1]})."
        else:
            action = "Resolve the named fail-closed authority blocker."
        actions.append({"code": code, "action": action})
    return actions


async def run_capacity_preflight(
    plan_id: str,
    action: PlanActionRequest | None = None,
) -> CapacityPreflightResponse:
    plan = await _require_plan(plan_id)
    if plan["status"] not in {
        PlanStatus.DRAFT.value,
        PlanStatus.PREFLIGHT_BLOCKED.value,
        PlanStatus.PREFLIGHT_READY.value,
    }:
        raise CreativeProductionError(
            "ILLEGAL_PLAN_TRANSITION",
            f"Cannot preflight a plan in {plan['status']} state.",
            status_code=409,
        )
    await _assert_frozen_cohort(_loads(plan.get("product_scope_json"), []))
    raw_capacity, candidates, pool_counts, blockers, historical_count = (
        await _capacity_candidates(plan)
    )
    requested = {
        "VIDEO": int(plan["target_video_count"]),
        "IMAGE": int(plan["target_image_count"]),
        "POSTER": int(plan["target_poster_count"]),
    }
    unique_capacity = {
        media_type: len({dna for dna, _ in rows})
        for media_type, rows in candidates.items()
    }
    pool = _loads(plan.get("pool_snapshot_json"), {})
    controlled_reuse_reason = str(
        pool.get("controlled_reuse_reason") or ""
    ).strip()
    controlled_reuse_max = max(
        1,
        min(3, int(pool.get("controlled_reuse_max_per_dna") or 1)),
    )
    safe_capacity: dict[str, int] = {}
    for media_type, rows in candidates.items():
        if media_type == "POSTER":
            safe_capacity[media_type] = unique_capacity[media_type] * (
                controlled_reuse_max if controlled_reuse_reason else 1
            )
            continue
        remaining_by_copy: Counter[str] = Counter()
        unique_by_copy: Counter[str] = Counter()
        for _, dimension in rows:
            copy_set_id = dimension["copy_set_id"]
            historical_usage = int(dimension.get("copy_usage_count") or 0)
            remaining_by_copy[copy_set_id] = max(
                copy_rotation_service.REUSE_CAP - historical_usage,
                0,
            )
            unique_by_copy[copy_set_id] += 1
        safe_capacity[media_type] = sum(
            min(
                unique_count
                * (controlled_reuse_max if controlled_reuse_reason else 1),
                remaining_by_copy[copy_set_id],
            )
            for copy_set_id, unique_count in unique_by_copy.items()
        )
    for media_type, target in requested.items():
        if target <= safe_capacity[media_type]:
            continue
        blockers.append(
            {
                "code": "UNIQUE_CAPACITY_SHORTFALL",
                "media_type": media_type,
                "requested": target,
                "available": safe_capacity[media_type],
                "shortfall": target - safe_capacity[media_type],
                "unique_without_controlled_reuse": unique_capacity[media_type],
            }
        )

    lane_capacity, lane_blockers, lane_evidence = await _lane_window_capacity(
        requested,
        int(plan["operating_window_hours"]),
    )
    blockers.extend(lane_blockers)
    quota_pressure = {
        "copy_slot_pressure": round(
            (requested["VIDEO"] + requested["IMAGE"])
            / max(pool_counts["copy_capacity_slots"], 1),
            4,
        ),
        "avatar_max_reuse": round(
            (requested["VIDEO"] + requested["IMAGE"])
            / max(pool_counts["avatars"], 1),
            4,
        ),
        "scene_max_reuse": round(
            sum(requested.values()) / max(pool_counts["scenes"], 1),
            4,
        ),
    }
    remediation = _capacity_remediation(blockers, pool_counts)
    assumptions = {
        "capacity_is_unique_cartesian_product": True,
        "historical_exact_dna_excluded": True,
        "near_duplicate_is_warning_only": True,
        "controlled_reuse_reason": controlled_reuse_reason or None,
        "controlled_reuse_max_per_dna": controlled_reuse_max,
        "copy_reuse_cap": copy_rotation_service.REUSE_CAP,
        "video_verified_inflight_per_lane": 1,
        "image_provider_capacity_verified": False,
        "capacity_objective_not_sla": True,
        "operating_window_hours": int(plan["operating_window_hours"]),
        "raw_capacity_before_history": raw_capacity,
        "unique_capacity_before_controlled_reuse": unique_capacity,
        "lane_window_capacity": lane_capacity,
        "lane_evidence": lane_evidence,
    }
    snapshot = {
        "requested": requested,
        "safe_capacity": safe_capacity,
        "pool_counts": pool_counts,
        "quota_pressure": quota_pressure,
        "historical_exclusions": historical_count,
        "blockers": blockers,
        "remediation": remediation,
        "assumptions": assumptions,
        "candidate_dna_sha256": {
            media_type: [dna for dna, _ in rows]
            for media_type, rows in candidates.items()
        },
    }
    snapshot_sha = _sha(snapshot)
    status = (
        PlanStatus.PREFLIGHT_BLOCKED.value
        if blockers
        else PlanStatus.PREFLIGHT_READY.value
    )
    await p6db.update_plan(
        plan_id,
        capacity_snapshot_json=_stable_json(
            {**snapshot, "snapshot_sha256": snapshot_sha}
        ),
        blockers_json=_stable_json(blockers),
        status=status,
        updated_at=_now(),
    )
    if action is not None:
        await record_audit_event(
            plan_id=plan_id,
            request_id=action.request_id,
            actor_id=action.operator_id,
            action="RUN_CAPACITY_PREFLIGHT",
            source_state=str(plan["status"]),
            target_state=status,
            evidence={
                "snapshot_sha256": snapshot_sha,
                "blocker_count": len(blockers),
                "credit_spend": 0,
            },
        )
    return CapacityPreflightResponse(
        plan_id=plan_id,
        status=status,
        requested=requested,
        safe_capacity=safe_capacity,
        pool_counts=pool_counts,
        quota_pressure=quota_pressure,
        historical_exclusions=historical_count,
        blockers=blockers,
        remediation=remediation,
        assumptions=assumptions,
        snapshot_sha256=snapshot_sha,
    )


async def materialize_content_matrix(
    plan_id: str,
    action: PlanActionRequest | None = None,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    existing = await p6db.list_items(plan_id)
    if existing:
        return {
            "plan_id": plan_id,
            "created": 0,
            "items": [_decode_row(row) for row in existing],
            "idempotent_replay": True,
        }
    if plan["status"] != PlanStatus.PREFLIGHT_READY.value:
        raise CreativeProductionError(
            "PREFLIGHT_NOT_READY",
            "Content matrix can be materialized only after a green preflight.",
            status_code=409,
        )

    preflight = await run_capacity_preflight(plan_id)
    if preflight.status != PlanStatus.PREFLIGHT_READY.value:
        raise CreativeProductionError(
            "PREFLIGHT_DRIFTED",
            "Capacity or authority changed after the prior preflight.",
            status_code=409,
            details={"blockers": preflight.blockers},
        )
    plan = await _require_plan(plan_id)
    _, candidates, _, _, _ = await _capacity_candidates(plan)
    pool = _loads(plan.get("pool_snapshot_json"), {})
    controlled_reuse_reason = str(
        pool.get("controlled_reuse_reason") or ""
    ).strip()
    controlled_reuse_max = max(
        1,
        min(3, int(pool.get("controlled_reuse_max_per_dna") or 1)),
    )
    requested = {
        "VIDEO": int(plan["target_video_count"]),
        "IMAGE": int(plan["target_image_count"]),
        "POSTER": int(plan["target_poster_count"]),
    }
    selected: list[tuple[str, dict[str, str], int]] = []
    ordinal = 0
    for media_type in ("VIDEO", "IMAGE", "POSTER"):
        rows = candidates[media_type]
        target = requested[media_type]
        if not rows and target:
            raise CreativeProductionError(
                "CAPACITY_CANDIDATE_MISSING",
                f"No safe {media_type} candidates remain.",
                status_code=409,
            )
        dna_uses: Counter[str] = Counter()
        copy_uses: Counter[str] = Counter()
        cursor = 0
        while sum(dna_uses.values()) < target:
            if cursor >= len(rows) * controlled_reuse_max:
                raise CreativeProductionError(
                    "CONTROLLED_CAPACITY_SELECTION_FAILED",
                    f"Bounded selection could not fill {media_type} target.",
                    status_code=409,
                )
            dna, dimensions = rows[cursor % len(rows)]
            cursor += 1
            if dna_uses[dna] >= (
                controlled_reuse_max if controlled_reuse_reason else 1
            ):
                continue
            copy_set_id = dimensions["copy_set_id"]
            if media_type != "POSTER":
                historical_usage = int(
                    dimensions.get("copy_usage_count") or 0
                )
                if (
                    copy_uses[copy_set_id] + historical_usage
                    >= copy_rotation_service.REUSE_CAP
                ):
                    continue
            rendered_dimensions = dict(dimensions)
            if dna_uses[dna]:
                rendered_dimensions["exact_duplicate_status"] = (
                    "CONTROLLED_REUSE"
                )
                rendered_dimensions["readiness"] = (
                    "CONTROLLED_REUSE_APPROVED_BY_PLAN_POLICY"
                )
            selected.append((dna, rendered_dimensions, ordinal))
            dna_uses[dna] += 1
            copy_uses[copy_set_id] += 1
            ordinal += 1

    avatar_counts = Counter(
        dimensions.get("avatar_code") or ""
        for _, dimensions, _ in selected
        if dimensions.get("avatar_code")
    )
    scene_counts = Counter(
        dimensions.get("scene_family") or ""
        for _, dimensions, _ in selected
        if dimensions.get("scene_family")
    )
    avatar_fair_cap = math.ceil(
        len(selected) / max(len(avatar_counts), 1)
    ) + 1
    scene_fair_cap = math.ceil(
        len(selected) / max(len(scene_counts), 1)
    ) + 1

    now = _now()
    items: list[dict[str, Any]] = []
    for dna, dimensions, item_ordinal in selected:
        reuse_cycle = sum(
            1
            for prior_dna, _, _ in selected[:item_ordinal]
            if prior_dna == dna
        )
        reuse_reason = controlled_reuse_reason if reuse_cycle else None
        if (
            avatar_counts.get(dimensions.get("avatar_code") or "", 0)
            > avatar_fair_cap
            or scene_counts.get(dimensions.get("scene_family") or "", 0)
            > scene_fair_cap
        ):
            dimensions["quota_status"] = "WARNING"
        dedupe_guard = (
            f"reuse:{plan_id}:{item_ordinal}:{dna}"
            if reuse_reason
            else f"dna:{dna}"
        )
        items.append(
            {
                "item_id": (
                    f"p6item_{_sha([plan_id, item_ordinal, dna])[:24]}"
                ),
                "plan_id": plan_id,
                "item_ordinal": item_ordinal,
                "product_id": dimensions["product_id"],
                "media_type": dimensions["media_type"],
                "logical_mode": dimensions["logical_mode"],
                "creative_dimensions_json": _stable_json(dimensions),
                "creative_dna_sha256": dna,
                "dedupe_guard_key": dedupe_guard,
                "controlled_reuse_reason": reuse_reason,
                "execution_policy_json": plan["execution_policy_json"],
                "status": "PLANNED",
                "created_at": now,
                "updated_at": now,
            }
        )
    await p6db.insert_items(items)
    if action is not None:
        await record_audit_event(
            plan_id=plan_id,
            request_id=action.request_id,
            actor_id=action.operator_id,
            action="MATERIALIZE_CONTENT_MATRIX",
            source_state=PlanStatus.PREFLIGHT_READY.value,
            target_state=PlanStatus.PREFLIGHT_READY.value,
            evidence={"item_count": len(items), "credit_spend": 0},
        )
    rows = await p6db.list_items(plan_id)
    return {
        "plan_id": plan_id,
        "created": len(rows),
        "items": [_decode_row(row) for row in rows],
        "idempotent_replay": False,
    }


async def mark_compilation_ready(plan_id: str) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    items = await p6db.list_items(plan_id)
    if not items:
        raise CreativeProductionError(
            "CONTENT_MATRIX_EMPTY",
            "Materialize the content matrix before compilation.",
            status_code=409,
        )
    blocked = [
        item["item_id"]
        for item in items
        if item["status"] not in {"COMPILED", "PENDING_APPROVAL"}
    ]
    if blocked:
        raise CreativeProductionError(
            "COMPILATION_INCOMPLETE",
            "Every item must have an immutable compiled package.",
            status_code=409,
            details={"item_ids": blocked},
        )
    await p6db.bulk_update_item_status(
        plan_id,
        from_statuses=["COMPILED"],
        to_status="PENDING_APPROVAL",
        updated_at=_now(),
    )
    row = await p6db.update_plan(
        plan_id,
        status=PlanStatus.PENDING_APPROVAL.value,
        updated_at=_now(),
    )
    return _decode_row(row)


async def approve_plan(
    plan_id: str,
    *,
    request_id: str,
    operator_id: str,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    if (
        plan["status"] == PlanStatus.APPROVED.value
        and plan.get("approved_by") == operator_id
    ):
        return _decode_row(plan)
    if plan["status"] != PlanStatus.PENDING_APPROVAL.value:
        raise CreativeProductionError(
            "ILLEGAL_PLAN_TRANSITION",
            f"Cannot approve a plan in {plan['status']} state.",
            status_code=409,
        )
    items = await p6db.list_items(plan_id)
    if not items or any(item["status"] != "PENDING_APPROVAL" for item in items):
        raise CreativeProductionError(
            "ITEM_APPROVAL_GATE_FAILED",
            "All items must be compiled and pending approval.",
            status_code=409,
        )
    now = _now()
    await p6db.bulk_update_item_status(
        plan_id,
        from_statuses=["PENDING_APPROVAL"],
        to_status="APPROVED",
        updated_at=now,
    )
    row = await p6db.update_plan(
        plan_id,
        status=PlanStatus.APPROVED.value,
        approved_by=operator_id,
        approved_at=now,
        compile_snapshot_json=_stable_json(
            {
                **_loads(plan.get("compile_snapshot_json"), {}),
                "approval_request_id": request_id,
            }
        ),
        updated_at=now,
    )
    await record_audit_event(
        plan_id=plan_id,
        request_id=request_id,
        actor_id=operator_id,
        action="APPROVE_PLAN",
        source_state=str(plan["status"]),
        target_state=PlanStatus.APPROVED.value,
        evidence={"approved_item_count": len(items)},
    )
    return _decode_row(row)


async def assign_waves(
    plan_id: str,
    body: WaveAssignmentRequest,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    existing = await p6db.list_waves(plan_id)
    if existing:
        return {
            "plan_id": plan_id,
            "waves": [_decode_row(row) for row in existing],
            "batches": [
                _decode_row(row) for row in await p6db.list_batches(plan_id)
            ],
            "idempotent_replay": True,
        }
    if plan["status"] != PlanStatus.APPROVED.value:
        raise CreativeProductionError(
            "PLAN_NOT_APPROVED",
            "Only an approved plan can be assigned to waves.",
            status_code=409,
        )
    items = await p6db.list_items(plan_id, statuses=["APPROVED"])
    if not items:
        raise CreativeProductionError(
            "NO_APPROVED_ITEMS",
            "The plan has no approved items.",
            status_code=409,
        )
    wave_count = min(body.wave_count, len(items))
    now = _now()
    waves = [
        {
            "wave_id": f"p6wave_{_sha([plan_id, index])[:20]}",
            "plan_id": plan_id,
            "wave_ordinal": index,
            "name": f"Wave {index + 1}",
            "scheduled_at": body.scheduled_at,
        }
        for index in range(wave_count)
    ]
    batch_count = (len(items) + body.batch_size - 1) // body.batch_size
    batches: list[dict[str, Any]] = []
    for batch_index in range(batch_count):
        wave = waves[batch_index % wave_count]
        batches.append(
            {
                "production_batch_id": (
                    f"p6batch_{_sha([plan_id, batch_index])[:20]}"
                ),
                "plan_id": plan_id,
                "wave_id": wave["wave_id"],
                "batch_ordinal": batch_index,
                "label": f"Review batch {batch_index + 1}",
            }
        )
    assignments: list[tuple[str, str, str, str]] = []
    for index, item in enumerate(items):
        batch = batches[index // body.batch_size]
        assignments.append(
            (
                batch["wave_id"],
                batch["production_batch_id"],
                now,
                item["item_id"],
            )
        )
    await p6db.replace_plan_allocations(
        plan_id,
        waves,
        batches,
        assignments,
    )
    await p6db.update_plan(
        plan_id,
        status=PlanStatus.SCHEDULED.value,
        updated_at=now,
    )
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="ASSIGN_WAVES",
        source_state=str(plan["status"]),
        target_state=PlanStatus.SCHEDULED.value,
        evidence={
            "wave_count": wave_count,
            "batch_count": batch_count,
            "item_count": len(items),
        },
    )
    return {
        "plan_id": plan_id,
        "waves": [_decode_row(row) for row in await p6db.list_waves(plan_id)],
        "batches": [
            _decode_row(row) for row in await p6db.list_batches(plan_id)
        ],
        "idempotent_replay": False,
    }
