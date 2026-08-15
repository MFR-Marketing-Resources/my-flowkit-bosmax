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
from agent.db import creative_treatment_crud as treatment_db
from agent.db import crud
from agent.models.creative_production import (
    CapacityPreflightResponse,
    PoolAuthorityRequest,
    P58_COHORT_COUNT,
    P58_COHORT_SHA256,
    P58CohortAuthorityResponse,
    PlanStatus,
    ProductionPlanCanonicalSnapshot,
    ProductionPlanCreateRequest,
    ProductionPlanDetailResponse,
    ProductionPlanUpdateRequest,
    WaveAssignmentRequest,
)
from agent.services import avatar_registry
from agent.services import copy_rotation_service
from agent.services import creative_recipe_service
from agent.services import creative_scene_prompt_service
from agent.services import creative_treatment_service as treatment_service
from agent.services import poster_recipe_service
from agent.services import video_models
from agent.services.catalog_coverage_service import build_catalog_authority_matrix
from agent.services.product_intelligence import resolve_image_readiness
from agent.services.scene_strategy_library import (
    build_scene_strategy_context,
    resolve_scene_strategy,
    select_scene_strategy_variant,
)
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)
from agent.services import copy_register_v2_service


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


async def _v2_copy_authority_record(product_id: str, lane: str) -> dict[str, Any]:
    """Project the canonical persisted V2 authority into P6's DNA dimensions."""

    try:
        resolution = await resolve_persisted_copy_execution_binding(product_id, lane)
    except CopyExecutionResolutionError as exc:
        raise CreativeProductionError(
            exc.code,
            str(exc),
            status_code=exc.status_code,
            details={"product_id": product_id, "lane": lane, "upstream": exc.details},
        ) from exc

    derived = getattr(resolution.projection, "derived_copy", None)
    if resolution.copy_policy == "NOT_REQUIRED":
        return {
            "copy_set_id": f"copy-not-required:{product_id}:{lane}",
            "copy_binding_id": None,
            "blueprint_id": None,
            "product_id": product_id,
            "angle": "COPY_NOT_REQUIRED",
            "hook": "",
            "subhook": "",
            "usp_set_json": "[]",
            "cta": "",
            "formula_family": "COPY_NOT_REQUIRED",
            "usage_count": 0,
            "copy_architecture_v2": resolution.to_metadata(),
        }
    if resolution.binding is None or derived is None:
        raise CreativeProductionError(
            "V2 BINDING REQUIRED",
            "P6 requires a persisted formula-native V2 binding.",
            status_code=409,
            details={"product_id": product_id, "lane": lane},
        )
    blueprint = await copy_register_v2_service.get_blueprint(
        resolution.binding.blueprint_id,
        resolution.binding.revision,
    )
    return {
        # Kept as a JSON dimension key for historical P6 row compatibility; the
        # value is a V2 binding identity and is never looked up in copy_set.
        "copy_set_id": resolution.binding.binding_id,
        "copy_binding_id": resolution.binding.binding_id,
        "blueprint_id": resolution.binding.blueprint_id,
        "revision": resolution.binding.revision,
        "product_id": product_id,
        "angle": blueprint.angle.definition,
        "hook": derived.hook,
        "subhook": "",
        "usp_set_json": _stable_json([derived.body] if derived.body else []),
        "cta": derived.cta,
        "formula_family": resolution.binding.formula_id,
        "formula_version": resolution.binding.formula_version,
        "usage_count": 0,
        "copy_architecture_v2": resolution.to_metadata(),
    }


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
        ("plan_snapshot_json", {}),
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


def _video_configuration_snapshot(
    model_keys: list[str],
    duration_seconds: list[int],
    missing_fields: list[str],
) -> list[dict[str, Any]]:
    configurations: list[dict[str, Any]] = []
    for model_key in model_keys:
        for duration in duration_seconds:
            try:
                spec = video_models.resolve(model_key)
                orchestration = video_models.resolve_orchestration(
                    model_key,
                    int(duration),
                )
            except (TypeError, ValueError):
                if "video_configurations" not in missing_fields:
                    missing_fields.append("video_configurations")
                continue
            configurations.append(
                {
                    "model_key": str(spec["key"]),
                    "model_label": str(spec["ui_label"]),
                    **orchestration,
                }
            )
    if not configurations and "video_configurations" not in missing_fields:
        missing_fields.append("video_configurations")
    return configurations


def _validated_allocation_rows(
    product_ids: list[str],
    target_video_count: int,
    allocations: Any,
) -> list[dict[str, Any]] | None:
    if target_video_count == 0:
        if allocations:
            return None
        return [
            {"product_id": product_id, "video_count": 0}
            for product_id in product_ids
        ]
    if not isinstance(allocations, list) or not allocations:
        return None
    by_product: dict[str, int] = {}
    for allocation in allocations:
        if not isinstance(allocation, dict):
            return None
        product_id = str(allocation.get("product_id") or "")
        try:
            video_count = int(allocation.get("video_count"))
        except (TypeError, ValueError):
            return None
        if (
            not product_id
            or product_id in by_product
            or video_count < 1
            or video_count > 200
        ):
            return None
        by_product[product_id] = video_count
    if set(by_product) != set(product_ids):
        return None
    if sum(by_product.values()) != target_video_count:
        return None
    return [
        {"product_id": product_id, "video_count": by_product[product_id]}
        for product_id in product_ids
    ]


def _snapshot_from_plan_values(
    plan: dict[str, Any],
    *,
    allocations: Any,
    product_names: dict[str, str],
    source: str,
    evidence: dict[str, Any],
    matrix_count: int = 0,
    attempts_count: int = 0,
    qa_count: int = 0,
    extra_missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    missing_fields = list(extra_missing_fields or [])
    product_ids = [
        str(value)
        for value in _loads(plan.get("product_scope_json"), [])
        if str(value)
    ]
    target_video_count = int(plan.get("target_video_count") or 0)
    valid_allocations = _validated_allocation_rows(
        product_ids,
        target_video_count,
        allocations,
    )
    product_allocations: list[dict[str, Any]] = []
    if valid_allocations is None:
        missing_fields.append("product_allocations")
    else:
        for allocation in valid_allocations:
            product_id = str(allocation["product_id"])
            product_name = str(product_names.get(product_id) or "").strip()
            if not product_name:
                if "product_names" not in missing_fields:
                    missing_fields.append("product_names")
                product_name = product_id
            product_allocations.append(
                {
                    **allocation,
                    "product_name": product_name,
                }
            )

    model_keys = [
        str(value)
        for value in _loads(plan.get("model_keys_json"), [])
        if str(value).strip()
    ]
    durations = [
        int(value)
        for value in _loads(plan.get("duration_seconds_json"), [])
        if isinstance(value, int) or str(value).isdigit()
    ]
    video_configurations = (
        _video_configuration_snapshot(
            model_keys,
            durations,
            missing_fields,
        )
        if target_video_count > 0
        else []
    )
    pool_snapshot = _loads(plan.get("pool_snapshot_json"), {})
    execution_policy = _loads(plan.get("execution_policy_json"), {})
    aspect = str(execution_policy.get("aspect") or "")
    if aspect not in {"9:16", "16:9"}:
        missing_fields.append("aspect_ratio")
        aspect = "9:16"

    unique_missing = sorted(set(missing_fields))
    return {
        "schema_version": 1,
        "completeness": (
            "LEGACY_INCOMPLETE" if unique_missing else "COMPLETE"
        ),
        "missing_fields": unique_missing,
        "source": source,
        "evidence": evidence,
        "plan_id": str(plan["plan_id"]),
        "plan_name": str(plan["name"]),
        "purpose": str(plan.get("campaign_key") or "").strip() or None,
        "status": str(plan["status"]),
        "operator_id": str(plan["created_by"]),
        "request_id": str(plan["request_id"]),
        "product_allocations": product_allocations,
        "target_video_count": target_video_count,
        "target_image_count": int(plan.get("target_image_count") or 0),
        "target_poster_count": int(plan.get("target_poster_count") or 0),
        "logical_mode": str(plan["logical_mode"]),
        "video_configurations": video_configurations,
        "aspect_ratio": aspect,
        "operating_window_hours": int(plan["operating_window_hours"]),
        "allocation_strategy": str(plan["allocation_strategy"]),
        "variation_strategy": str(plan["variation_strategy"]),
        "approved_pool_snapshot": (
            pool_snapshot if plan.get("approved_by") else None
        ),
        "pool_snapshot": pool_snapshot,
        "cohort_snapshot": {
            "cohort_sha256": str(plan["p58_cohort_sha256"]),
            "cohort_count": int(plan["p58_cohort_count"]),
            "product_ids": product_ids,
        },
        "matrix_count": matrix_count,
        "attempts_count": attempts_count,
        "qa_count": qa_count,
        "created_at": str(plan["created_at"]),
        "updated_at": str(plan["updated_at"]),
    }


def _unique(values: list[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


async def load_p58_cohort_authority() -> P58CohortAuthorityResponse:
    report = await build_catalog_authority_matrix()
    product_ids = sorted(report.p6_launch_cohort_product_ids)
    cohort_sha = _sha(product_ids)
    catalog_product_rows = await crud.list_products(include_archived=False)
    catalog_products = {
        str(product.get("id") or ""): product
        for product in catalog_product_rows
    }
    image_readiness_by_id = {
        str(product.get("id") or ""): resolve_image_readiness(product)
        for product in catalog_product_rows
    }
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
                "image_url": str(
                    (catalog_products.get(row.product_id) or {}).get("image_url")
                    or ""
                ),
                "image_readiness_status": str(
                    (image_readiness_by_id.get(row.product_id) or {}).get(
                        "image_readiness_status"
                    )
                    or ""
                ),
                "readiness_status": "PRODUCTION_READY",
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


async def _catalog_product_names() -> dict[str, str]:
    return {
        str(product.get("id") or ""): str(
            product.get("product_display_name")
            or product.get("product_name")
            or product.get("raw_product_title")
            or product.get("name")
            or ""
        )
        for product in await crud.list_products(include_archived=True)
        if str(product.get("id") or "")
    }


def _reconstruct_product_allocations(
    plan: dict[str, Any],
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    product_ids = [
        str(value)
        for value in _loads(plan.get("product_scope_json"), [])
        if str(value)
    ]
    target_video_count = int(plan.get("target_video_count") or 0)
    pool_snapshot = _loads(plan.get("pool_snapshot_json"), {})
    persisted = _validated_allocation_rows(
        product_ids,
        target_video_count,
        pool_snapshot.get("product_video_allocations"),
    )
    if persisted is not None:
        return persisted, {
            "allocation_source": "PERSISTED_POOL_SNAPSHOT",
            "allocation_item_ids": [],
        }

    primary_video_items = [
        item
        for item in items
        if str(item.get("media_type") or "") == "VIDEO"
        and not str(item.get("replacement_for_item_id") or "")
    ]
    counts = Counter(
        str(item.get("product_id") or "")
        for item in primary_video_items
        if str(item.get("product_id") or "")
    )
    item_allocations = [
        {"product_id": product_id, "video_count": int(counts[product_id])}
        for product_id in product_ids
        if counts[product_id] > 0
    ]
    validated = _validated_allocation_rows(
        product_ids,
        target_video_count,
        item_allocations,
    )
    return validated, {
        "allocation_source": (
            "PRIMARY_VIDEO_ITEMS" if validated is not None else "NOT_PROVABLE"
        ),
        "allocation_item_ids": sorted(
            str(item.get("item_id") or "")
            for item in primary_video_items
            if str(item.get("item_id") or "")
        ),
    }


async def _render_plan_snapshot(
    plan: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    qa: list[dict[str, Any]],
) -> ProductionPlanCanonicalSnapshot:
    persisted = _loads(plan.get("plan_snapshot_json"), {})
    if persisted:
        snapshot = dict(persisted)
        snapshot.update(
            {
                "status": str(plan["status"]),
                "approved_pool_snapshot": (
                    snapshot.get("pool_snapshot")
                    if plan.get("approved_by")
                    else None
                ),
                "matrix_count": len(items),
                "attempts_count": len(attempts),
                "qa_count": len(qa),
                "updated_at": str(plan["updated_at"]),
            }
        )
        return ProductionPlanCanonicalSnapshot.model_validate(snapshot)

    allocations, allocation_evidence = _reconstruct_product_allocations(
        plan,
        items,
    )
    snapshot = _snapshot_from_plan_values(
        plan,
        allocations=allocations,
        product_names=await _catalog_product_names(),
        source="LEGACY_PREVIEW",
        evidence={
            **allocation_evidence,
            "product_name_source": "CURRENT_CANONICAL_CATALOG_PREVIEW",
            "persisted": False,
        },
        matrix_count=len(items),
        attempts_count=len(attempts),
        qa_count=len(qa),
        extra_missing_fields=(
            [] if allocations is not None else ["product_allocations"]
        ),
    )
    snapshot["completeness"] = "LEGACY_INCOMPLETE"
    if "persisted_plan_snapshot" not in snapshot["missing_fields"]:
        snapshot["missing_fields"].append("persisted_plan_snapshot")
        snapshot["missing_fields"].sort()
    return ProductionPlanCanonicalSnapshot.model_validate(snapshot)


async def reconcile_legacy_plan_snapshots(
    *,
    request_id: str,
    operator_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    product_names = await _catalog_product_names()
    results: list[dict[str, Any]] = []
    for plan in await p6db.list_plans(100_000):
        persisted = _loads(plan.get("plan_snapshot_json"), {})
        if persisted:
            results.append(
                {
                    "plan_id": str(plan["plan_id"]),
                    "result": "ALREADY_RECONCILED",
                    "completeness": str(persisted.get("completeness") or ""),
                }
            )
            continue
        items = await p6db.list_items(str(plan["plan_id"]))
        allocations, allocation_evidence = _reconstruct_product_allocations(
            plan,
            items,
        )
        reconciled_at = _now()
        snapshot = _snapshot_from_plan_values(
            plan,
            allocations=allocations,
            product_names=product_names,
            source="LEGACY_RECONCILIATION",
            evidence={
                **allocation_evidence,
                "product_name_source": (
                    "CURRENT_CANONICAL_CATALOG_AT_RECONCILIATION"
                ),
                "reconciled_at": reconciled_at,
                "reconciliation_request_id": request_id,
            },
            matrix_count=len(items),
            attempts_count=len(
                await p6db.list_attempts(str(plan["plan_id"]))
            ),
            qa_count=len(await p6db.list_qa(str(plan["plan_id"]))),
            extra_missing_fields=(
                [] if allocations is not None else ["product_allocations"]
            ),
        )
        if not dry_run:
            await p6db.update_plan(
                str(plan["plan_id"]),
                plan_snapshot_json=_stable_json(snapshot),
            )
            await record_audit_event(
                plan_id=str(plan["plan_id"]),
                request_id=f"{request_id}:{plan['plan_id']}",
                actor_id=operator_id,
                action="RECONCILE_PLAN_SNAPSHOT",
                source_state=str(plan["status"]),
                target_state=str(plan["status"]),
                evidence={
                    "completeness": snapshot["completeness"],
                    "missing_fields": snapshot["missing_fields"],
                    **allocation_evidence,
                },
            )
        results.append(
            {
                "plan_id": str(plan["plan_id"]),
                "result": "DRY_RUN" if dry_run else "RECONCILED",
                "completeness": snapshot["completeness"],
                "missing_fields": snapshot["missing_fields"],
                **allocation_evidence,
            }
        )
    return {
        "dry_run": dry_run,
        "plans": results,
        "complete_count": sum(
            result.get("completeness") == "COMPLETE" for result in results
        ),
        "incomplete_count": sum(
            result.get("completeness") == "LEGACY_INCOMPLETE"
            for result in results
        ),
    }


async def require_complete_plan_snapshot(plan_id: str) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    snapshot = _loads(plan.get("plan_snapshot_json"), {})
    if (
        snapshot.get("completeness") != "COMPLETE"
        or snapshot.get("plan_id") != plan_id
    ):
        raise CreativeProductionError(
            "PLAN_SNAPSHOT_INCOMPLETE",
            "Live production requires a complete persisted plan snapshot.",
            status_code=409,
            details={
                "plan_id": plan_id,
                "missing_fields": snapshot.get(
                    "missing_fields",
                    ["persisted_plan_snapshot"],
                ),
            },
        )
    return snapshot


def _request_snapshot(body: ProductionPlanCreateRequest) -> dict[str, Any]:
    snapshot = body.model_dump(mode="json", exclude_none=False)
    if snapshot.get("copy_v2_context") is None:
        snapshot.pop("copy_v2_context", None)
    return snapshot


def _video_allocations(plan: dict[str, Any]) -> dict[str, int]:
    pool = _loads(plan.get("pool_snapshot_json"), {})
    rows = pool.get("product_video_allocations") or []
    return {
        str(row.get("product_id") or ""): int(row.get("video_count") or 0)
        for row in rows
        if isinstance(row, dict)
        and str(row.get("product_id") or "").strip()
        and int(row.get("video_count") or 0) > 0
    }


_TREATMENT_DEPENDENCY_HASH_FIELDS = (
    "product_truth_sha256",
    "copy_set_sha256",
    "creative_selection_sha256",
    "scene_strategy_sha256",
    "avatar_sha256",
    "wardrobe_sha256",
    "scene_template_sha256",
    "camera_preset_sha256",
    "dialogue_sha256",
)


def _treatment_error(
    code: str,
    message: str,
    *,
    status_code: int = 422,
    details: dict[str, Any] | None = None,
) -> CreativeProductionError:
    return CreativeProductionError(
        code,
        message,
        status_code=status_code,
        details=details,
    )


def _v2_visual_treatment_projection(projection: dict[str, Any]) -> dict[str, Any]:
    """Remove retired copy authority from an active P6 treatment projection."""

    result = json.loads(_stable_json(projection))
    for field in (
        "copy_set_id",
        "copy_set_sha256",
        "content_angle",
        "dialogue_text",
        "dialogue_sha256",
    ):
        result.pop(field, None)
    dependencies = dict(result.get("dependency_hashes") or {})
    dependencies.pop("copy_set_sha256", None)
    dependencies.pop("dialogue_sha256", None)
    result["dependency_hashes"] = dependencies
    segment_plan = result.get("segment_plan")
    if isinstance(segment_plan, dict):
        for segment in segment_plan.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            segment["exact_dialogue_slice"] = ""
            allocation = segment.get("planner_allocation")
            if isinstance(allocation, dict):
                allocation["exact_dialogue_slice"] = ""
                allocation.pop("full_dialogue_text", None)
    result["copy_authority"] = "COPY_REGISTER_V2_ONLY"
    result["historical_copy_excluded"] = True
    return result


async def resolve_treatment_authority(
    treatment_id: str,
    *,
    plan: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one immutable P7.5 treatment projection for a P6 video item."""

    row = await treatment_db.get_treatment(treatment_id)
    if row is None:
        raise _treatment_error(
            "TREATMENT_NOT_FOUND",
            f"Creative Treatment {treatment_id} was not found.",
            status_code=404,
        )
    if str(row.get("status") or "") != "APPROVED":
        raise _treatment_error(
            "TREATMENT_NOT_APPROVED",
            f"Creative Treatment {treatment_id} is not approved.",
            status_code=409,
        )
    generation_mode = str(row.get("generation_mode") or "").upper()
    if generation_mode not in {"SINGLE", "EXTEND"}:
        raise _treatment_error(
            "TREATMENT_GENERATION_MODE_UNSUPPORTED",
            f"Unsupported treatment generation mode {generation_mode or '<empty>'}.",
        )
    format_name = str(row.get("format") or "").upper()
    if format_name not in {"UGC", "PGC", "CINEMATIC"}:
        raise _treatment_error(
            "TREATMENT_FORMAT_UNSUPPORTED",
            f"Unsupported treatment format {format_name or '<empty>'}.",
        )
    decoded = treatment_service._decode_treatment(row)
    compatibility = decoded.get("compatibility_profile") or {}
    if not isinstance(compatibility, dict):
        raise _treatment_error(
            "TREATMENT_INCOMPATIBLE",
            "Treatment compatibility authority is malformed.",
        )
    if "FALLBACK" in str(row.get("scene_strategy_id") or "").upper():
        raise _treatment_error(
            "TREATMENT_GENERIC_FALLBACK_FORBIDDEN",
            "Generic fallback scene authority is forbidden for P6 video.",
        )
    from agent.services.scene_choreography_lineage import (
        assert_production_treatment_payload,
    )

    try:
        assert_production_treatment_payload(
            strategy_id=str(row.get("scene_strategy_id") or ""),
            decoded=decoded,
        )
    except Exception as exc:
        raise _treatment_error(
            str(getattr(exc, "code", None) or "LEGACY_ATOMIC_TREATMENT_REJECTED"),
            str(exc),
        ) from exc
    expected_source_mode = {
        "T2V": "T2V",
        "HYBRID": "HYBRID",
        "F2V": "FRAMES",
        "I2V": "INGREDIENTS",
    }.get(str(compatibility.get("logical_mode") or ""))
    if (
        expected_source_mode is None
        or str(compatibility.get("source_mode") or "")
        != expected_source_mode
    ):
        raise _treatment_error(
            "TREATMENT_INCOMPATIBLE",
            "Treatment source mode does not match its governed logical mode.",
            details={"treatment_id": treatment_id},
        )
    try:
        current = (
            await treatment_service._revalidate(row)
            if legacy_copy_maintenance_enabled()
            else treatment_service.revalidate_stored_treatment_receipt(row)
        )
    except treatment_service.CreativeTreatmentError as exc:
        code = (
            "TREATMENT_HASH_STALE"
            if exc.code == "TREATMENT_AUTHORITY_STALE"
            else "TREATMENT_DEPENDENCY_STALE"
        )
        raise _treatment_error(
            code,
            "Creative Treatment dependency authority has drifted.",
            status_code=409,
            details={"treatment_id": treatment_id, "authority_code": exc.code},
        ) from exc

    if plan is not None:
        product_scope = set(_loads(plan.get("product_scope_json"), []))
        if str(row["product_id"]) not in product_scope:
            raise _treatment_error(
                "TREATMENT_INCOMPATIBLE",
                "Treatment product is outside the P6 plan scope.",
                details={"treatment_id": treatment_id},
            )
        logical_mode = str(plan.get("logical_mode") or "")
        if str(compatibility.get("logical_mode") or "") != logical_mode:
            raise _treatment_error(
                "TREATMENT_INCOMPATIBLE",
                "Treatment logical mode does not match the P6 plan.",
                details={
                    "treatment_id": treatment_id,
                    "treatment_logical_mode": compatibility.get("logical_mode"),
                    "plan_logical_mode": logical_mode,
                },
            )
        durations = {
            float(value)
            for value in _loads(plan.get("duration_seconds_json"), [])
        }
        if float(row["duration_seconds"]) not in durations:
            raise _treatment_error(
                "TREATMENT_INCOMPATIBLE",
                "Treatment duration is outside the P6 duration pool.",
                details={"treatment_id": treatment_id},
            )
        plan_models = _loads(plan.get("model_keys_json"), [])
        compatible_models: list[str] = []
        for value in compatibility.get("model_keys") or plan_models:
            model_key = str(value)
            if model_key not in plan_models:
                continue
            try:
                orchestration = video_models.resolve_orchestration(
                    model_key,
                    int(float(row["duration_seconds"])),
                )
            except ValueError:
                continue
            if orchestration["generation_mode"] == generation_mode:
                compatible_models.append(model_key)
        if not compatible_models:
            raise _treatment_error(
                "TREATMENT_INCOMPATIBLE",
                "Treatment has no compatible model in the P6 model pool.",
                details={"treatment_id": treatment_id},
            )
    else:
        compatible_models = [
            str(value) for value in compatibility.get("model_keys") or []
        ]

    group_projection: dict[str, Any] | None = None
    group_id = str(row.get("variation_group_id") or "").strip()
    if group_id:
        group = await treatment_db.get_variation_group(group_id)
        if group is None or str(group.get("status") or "") != "APPROVED":
            raise _treatment_error(
                "VARIATION_GROUP_NOT_APPROVED",
                f"Variation Group {group_id} is not approved.",
                status_code=409,
            )
        members = await treatment_db.list_group_members(group_id)
        try:
            group_sha256, member_projection = treatment_service._group_snapshot(
                group,
                members,
            )
        except treatment_service.CreativeTreatmentError as exc:
            mapped = (
                "VARIATION_GROUP_DIALOGUE_MISMATCH"
                if "DIALOGUE" in exc.code
                else "VARIATION_GROUP_NOT_APPROVED"
            )
            raise _treatment_error(
                mapped,
                "Variation Group authority failed revalidation.",
                status_code=409,
                details={"group_id": group_id, "authority_code": exc.code},
            ) from exc
        if group_sha256 != str(group.get("group_sha256") or ""):
            raise _treatment_error(
                "VARIATION_GROUP_HASH_STALE",
                "Variation Group membership hash has drifted.",
                status_code=409,
                details={"group_id": group_id},
            )
        group_projection = {
            "group_id": group_id,
            "group_sha256": group_sha256,
            "dialogue_sha256": group["dialogue_sha256"],
            "member_count": len(member_projection),
            "members": member_projection,
        }

    projection = {
        "treatment_id": treatment_id,
        "treatment_sha256": str(current["treatment_sha256"]),
        "product_id": str(row["product_id"]),
        "format": format_name,
        "generation_mode": generation_mode,
        "duration_seconds": float(row["duration_seconds"]),
        "copy_set_id": str(row.get("copy_set_id") or ""),
        "copy_execution_binding_id_v2": str(
            row.get("copy_execution_binding_id_v2") or ""
        ),
        "content_angle": str(row.get("content_angle") or ""),
        "dialogue_text": str(row.get("dialogue_text") or ""),
        "avatar_code": str(row.get("avatar_code") or ""),
        "wardrobe_text": str(row.get("wardrobe_text") or ""),
        "scene_strategy_id": str(row["scene_strategy_id"]),
        "choreography_schema_version": decoded.get("choreography_schema_version"),
        "choreography_id": decoded.get("choreography_id"),
        "choreography_sha256": decoded.get("choreography_sha256"),
        "scene_template_id": str(row.get("scene_template_id") or ""),
        "camera_preset_code": str(row.get("camera_preset_code") or ""),
        "asset_bindings": decoded.get("asset_bindings") or [],
        "action_sequence": decoded.get("action_sequence") or [],
        "shot_grammar": decoded.get("shot_grammar") or [],
        "compatibility_profile": compatibility,
        "segment_plan": current.get("segment_plan") or [],
        "compatible_model_keys": compatible_models,
        "selected_model_key": compatible_models[0] if compatible_models else "",
        "visual_fingerprint_sha256": str(
            row["visual_fingerprint_sha256"]
        ),
        "variation_group": group_projection,
        "variation_group_id": group_id or None,
        "variation_ordinal": row.get("variation_ordinal"),
        "dependency_hashes": {
            field: row.get(field)
            for field in _TREATMENT_DEPENDENCY_HASH_FIELDS
        },
    }
    if expected is not None:
        expected_dependencies = dict(expected.get("dependency_hashes") or {})
        current_dependencies = dict(projection["dependency_hashes"])
        if not legacy_copy_maintenance_enabled():
            for field in ("copy_set_sha256", "dialogue_sha256"):
                expected_dependencies.pop(field, None)
                current_dependencies.pop(field, None)
        if expected_dependencies != current_dependencies:
            raise _treatment_error(
                "TREATMENT_DEPENDENCY_STALE",
                "Stored P6 treatment dependencies no longer match authority.",
                status_code=409,
                details={"treatment_id": treatment_id},
            )
        if expected.get("variation_group") != projection["variation_group"]:
            raise _treatment_error(
                "VARIATION_GROUP_HASH_STALE",
                "Stored P6 Variation Group lineage no longer matches authority.",
                status_code=409,
                details={"treatment_id": treatment_id},
            )
        if (
            expected.get("treatment_sha256")
            != projection["treatment_sha256"]
            or expected.get("visual_fingerprint_sha256")
            != projection["visual_fingerprint_sha256"]
        ):
            raise _treatment_error(
                "TREATMENT_HASH_STALE",
                "Stored P6 treatment lineage no longer matches authority.",
                status_code=409,
                details={"treatment_id": treatment_id},
            )
    return (
        projection
        if legacy_copy_maintenance_enabled()
        else _v2_visual_treatment_projection(projection)
    )


async def resolve_treatment_availability(
    *,
    product_video_allocations: list[dict[str, Any]],
    logical_mode: str,
    model_key: str,
    duration_seconds: int,
    creative_format: str = "AUTO",
    treatment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve deterministic approved-treatment capacity for Studio and create."""

    try:
        requested_orchestration = video_models.resolve_orchestration(
            model_key,
            duration_seconds,
        )
    except ValueError as exc:
        raise CreativeProductionError(
            "INVALID_MODEL_DURATION_COMBINATION",
            str(exc),
            status_code=422,
        ) from exc
    requested_format = str(creative_format or "AUTO").upper()
    explicit_ids = {
        str(value).strip()
        for value in treatment_ids or []
        if str(value).strip()
    }
    requested_total = sum(
        int(item["video_count"])
        for item in product_video_allocations
    )
    selection_mode = "EXPLICIT" if explicit_ids else "AUTO"
    product_results: list[dict[str, Any]] = []
    selected_treatments: list[dict[str, Any]] = []
    supported_by_key: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []

    for allocation in product_video_allocations:
        product_id = str(allocation["product_id"])
        requested = int(allocation["video_count"])
        rows = await treatment_db.list_treatments(
            product_id=product_id,
            status="APPROVED",
            limit=200,
        )
        eligible: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for row in sorted(rows, key=lambda item: str(item["treatment_id"])):
            treatment_id = str(row["treatment_id"])
            try:
                projection = await resolve_treatment_authority(treatment_id)
            except CreativeProductionError as exc:
                excluded.append({"treatment_id": treatment_id, "code": exc.code})
                continue
            compatibility = projection["compatibility_profile"]
            configured_models = [
                str(value)
                for value in compatibility.get("model_keys") or [model_key]
            ]
            supported = {
                "format": projection["format"],
                "logical_mode": compatibility.get("logical_mode"),
                "generation_mode": projection["generation_mode"],
                "duration_seconds": int(projection["duration_seconds"]),
                "model_keys": sorted(configured_models),
            }
            supported_by_key[_stable_json(supported)] = supported
            exact_match = (
                str(compatibility.get("logical_mode") or "") == logical_mode
                and model_key in configured_models
                and math.isclose(
                    float(projection["duration_seconds"]),
                    float(duration_seconds),
                    abs_tol=0.001,
                )
                and projection["generation_mode"]
                == requested_orchestration["generation_mode"]
                and (
                    requested_format == "AUTO"
                    or projection["format"] == requested_format
                )
            )
            if exact_match and (not explicit_ids or treatment_id in explicit_ids):
                eligible.append(projection)
        eligible.sort(key=lambda item: str(item["treatment_id"]))
        selected = eligible if explicit_ids else eligible[:requested]
        selected_treatments.extend(selected)
        available = len(eligible)
        ready = len(selected) == requested
        shortage = max(0, requested - len(selected))
        product_result = {
            "product_id": product_id,
            "requested": requested,
            "eligible_capacity": available,
            "selected_count": len(selected),
            "selected_treatment_ids": [
                item["treatment_id"] for item in selected
            ],
            "ready": ready,
            "shortage": shortage,
            "excluded_authority": excluded,
        }
        product_results.append(product_result)
        if not ready:
            blockers.append(
                {
                    "code": "TREATMENT_CAPACITY_INSUFFICIENT",
                    "product_id": product_id,
                    "requested": requested,
                    "available": len(selected),
                    "shortage": shortage,
                    "remediation": (
                        "Approve additional Creative Treatments matching the "
                        "selected format, mode, model, and duration."
                    ),
                }
            )

    selected_ids = {
        str(item["treatment_id"]) for item in selected_treatments
    }
    unused_explicit_ids = sorted(explicit_ids - selected_ids)
    if explicit_ids and len(explicit_ids) != requested_total:
        blockers.append(
            {
                "code": "TREATMENT_SELECTION_COUNT_MISMATCH",
                "requested": requested_total,
                "selected": len(explicit_ids),
                "remediation": "Select exactly one unique treatment per video.",
            }
        )
    if unused_explicit_ids:
        blockers.append(
            {
                "code": "TREATMENT_SELECTION_INELIGIBLE",
                "treatment_ids": unused_explicit_ids,
                "remediation": (
                    "Remove treatments outside the product or selected governed "
                    "configuration."
                ),
            }
        )
    selected_treatments.sort(
        key=lambda item: (str(item["product_id"]), str(item["treatment_id"])),
    )
    supported_configurations = [
        supported_by_key[key] for key in sorted(supported_by_key)
    ]
    result = {
        "ready": not blockers and len(selected_treatments) == requested_total,
        "selection_mode": selection_mode,
        "requested": {
            "logical_mode": logical_mode,
            "model_key": model_key,
            "duration_seconds": duration_seconds,
            "creative_format": requested_format,
            "video_count": requested_total,
        },
        "selected_treatment_ids": [
            item["treatment_id"] for item in selected_treatments
        ],
        "selected_treatments": selected_treatments,
        "product_results": product_results,
        "supported_formats": sorted(
            {item["format"] for item in supported_configurations}
        ),
        "supported_configurations": supported_configurations,
        "blockers": blockers,
    }
    return {
        **result,
        "availability_sha256": _sha(result),
    }


async def _resolve_plan_treatments(
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    if int(plan.get("target_video_count") or 0) <= 0:
        return []
    pool = _loads(plan.get("pool_snapshot_json"), {})
    treatment_ids = [
        str(value).strip()
        for value in pool.get("treatment_ids") or []
        if str(value).strip()
    ]
    if not treatment_ids:
        raise _treatment_error(
            "TREATMENT_IDS_REQUIRED_FOR_VIDEO",
            "P6 video plans require explicit approved Creative Treatment IDs.",
        )
    if len(treatment_ids) != len(set(treatment_ids)):
        raise _treatment_error(
            "TREATMENT_INCOMPATIBLE",
            "Treatment IDs must be unique.",
        )
    expected_by_id = {
        str(item.get("treatment_id") or ""): item
        for item in pool.get("treatments") or []
        if isinstance(item, dict) and item.get("treatment_id")
    }
    projections = [
        await resolve_treatment_authority(
            treatment_id,
            plan=plan,
            expected=expected_by_id.get(treatment_id),
        )
        for treatment_id in treatment_ids
    ]
    if int(plan["target_video_count"]) > len(projections):
        raise _treatment_error(
            "TREATMENT_INCOMPATIBLE",
            "Video target exceeds eligible unique treatment authority.",
            details={
                "requested": int(plan["target_video_count"]),
                "available": len(projections),
            },
        )
    allocations = _video_allocations(plan)
    counts = Counter(item["product_id"] for item in projections)
    for product_id, requested in allocations.items():
        if requested > counts[product_id]:
            raise _treatment_error(
                "TREATMENT_INCOMPATIBLE",
                "Product video allocation exceeds eligible treatments.",
                details={
                    "product_id": product_id,
                    "requested": requested,
                    "available": counts[product_id],
                },
            )
    return projections


async def resolve_item_treatment(
    dimensions: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    expected = dimensions.get("creative_treatment")
    if not isinstance(expected, dict) or not expected.get("treatment_id"):
        raise _treatment_error(
            "TREATMENT_LINEAGE_REQUIRED",
            "Nonterminal P6 video items require immutable treatment lineage.",
            status_code=409,
        )
    return await resolve_treatment_authority(
        str(expected["treatment_id"]),
        plan=plan,
        expected=expected,
    )


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
    allocation_snapshot = [
        allocation.model_dump(mode="json")
        for allocation in body.product_video_allocations
    ]
    availability: dict[str, Any] | None = None
    if body.target_video_count > 0:
        if len(body.model_keys) != 1 or len(body.duration_seconds) != 1:
            raise CreativeProductionError(
                "TREATMENT_SELECTION_CONFIGURATION_AMBIGUOUS",
                "Treatment-backed video plans require one model and one duration.",
                status_code=422,
            )
        availability = await resolve_treatment_availability(
            product_video_allocations=allocation_snapshot,
            logical_mode=body.logical_mode,
            model_key=body.model_keys[0],
            duration_seconds=body.duration_seconds[0],
            creative_format=body.creative_format,
            treatment_ids=body.pools.treatment_ids,
        )
        if not availability["ready"]:
            raise CreativeProductionError(
                "TREATMENT_CAPACITY_INSUFFICIENT",
                "Approved Creative Treatment capacity is insufficient.",
                status_code=409,
                details=availability,
            )

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
    created_at = _now()
    pool_snapshot = {
        **body.pools.model_dump(mode="json"),
        # Product Registration owns the sole product visual for every P6 lane.
        # Keep this legacy request field for wire compatibility, but never
        # persist client-selected Creative Library product references into the
        # executable plan snapshot.
        "product_reference_asset_ids": [],
        "creative_format": body.creative_format,
        "controlled_reuse_reason": body.controlled_reuse_reason,
        "controlled_reuse_max_per_dna": body.controlled_reuse_max_per_dna,
        "product_video_allocations": allocation_snapshot,
    }
    if not legacy_copy_maintenance_enabled():
        pool_snapshot.update(
            {
                "copy_set_ids": [],
                "poster_copy_set_ids": [],
                "copy_authority": "COPY_REGISTER_V2_ONLY",
            }
        )
    if body.copy_v2_context is not None:
        pool_snapshot["copy_v2_context"] = body.copy_v2_context
    if availability is not None:
        pool_snapshot["treatment_ids"] = availability[
            "selected_treatment_ids"
        ]
        pool_snapshot["treatments"] = availability["selected_treatments"]
        pool_snapshot["treatment_selection_mode"] = availability[
            "selection_mode"
        ]
        pool_snapshot["treatment_availability_sha256"] = availability[
            "availability_sha256"
        ]
        pool_snapshot["treatment_availability"] = {
            key: value
            for key, value in availability.items()
            if key != "selected_treatments"
        }

    values: dict[str, Any] = {
        "plan_id": plan_id,
        "request_id": body.request_id,
        "created_by": body.operator_id.strip(),
        "name": body.name.strip(),
        "campaign_key": body.campaign_key.strip(),
        "product_scope_json": _stable_json(body.product_ids),
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
        "pool_snapshot_json": _stable_json(pool_snapshot),
        "execution_policy_json": _stable_json(policy),
        "status": PlanStatus.DRAFT.value,
        "created_at": created_at,
        "updated_at": created_at,
    }
    if body.target_video_count > 0:
        pool_snapshot["treatments"] = await _resolve_plan_treatments(values)
        values["pool_snapshot_json"] = _stable_json(pool_snapshot)
    product_names = {
        str(product.get("product_id") or ""): str(
            product.get("product_name")
            or product.get("product_display_name")
            or product.get("name")
            or ""
        )
        for product in authority.products
    }
    snapshot = _snapshot_from_plan_values(
        values,
        allocations=pool_snapshot["product_video_allocations"],
        product_names=product_names,
        source="CREATE_REQUEST",
        evidence={
            "create_request_sha256": request_sha,
            "allocation_source": "CREATE_REQUEST",
            "product_name_source": "P58_COHORT_AUTHORITY_AT_CREATE",
            "treatment_availability_sha256": pool_snapshot.get(
                "treatment_availability_sha256"
            ),
        },
    )
    if snapshot["completeness"] != "COMPLETE":
        raise CreativeProductionError(
            "PLAN_SNAPSHOT_INCOMPLETE",
            "A new production plan requires a complete canonical snapshot.",
            status_code=409,
            details={"missing_fields": snapshot["missing_fields"]},
        )
    values["plan_snapshot_json"] = _stable_json(snapshot)
    row = await p6db.create_plan(values)
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="CREATE_PLAN",
        source_state=None,
        target_state=PlanStatus.DRAFT.value,
        evidence={
            "create_request_sha256": request_sha,
            "treatment_availability_sha256": pool_snapshot.get(
                "treatment_availability_sha256"
            ),
        },
    )
    return _decode_row(row)


async def list_plans(limit: int = 50) -> list[dict[str, Any]]:
    plans: list[dict[str, Any]] = []
    for row in await p6db.list_plans(limit):
        decoded = _decode_row(row)
        snapshot = decoded.get("plan_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            decoded["snapshot_summary"] = {
                "completeness": snapshot.get("completeness"),
                "missing_fields": snapshot.get("missing_fields", []),
                "product_allocations": snapshot.get(
                    "product_allocations",
                    [],
                ),
                "video_configurations": snapshot.get(
                    "video_configurations",
                    [],
                ),
                "aspect_ratio": snapshot.get("aspect_ratio"),
            }
        else:
            decoded["snapshot_summary"] = {
                "completeness": "LEGACY_INCOMPLETE",
                "missing_fields": ["persisted_plan_snapshot"],
                "product_allocations": [],
                "video_configurations": [],
                "aspect_ratio": None,
            }
        plans.append(decoded)
    return plans


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
    prior_snapshot = _loads(plan.get("plan_snapshot_json"), {})
    if prior_snapshot.get("completeness") != "COMPLETE":
        raise CreativeProductionError(
            "PLAN_SNAPSHOT_INCOMPLETE",
            "Reconcile the legacy plan snapshot before changing its configuration.",
            status_code=409,
            details={
                "plan_id": plan_id,
                "missing_fields": prior_snapshot.get(
                    "missing_fields",
                    ["persisted_plan_snapshot"],
                ),
            },
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
    product_scope = [
        str(value)
        for value in _loads(plan.get("product_scope_json"), [])
        if str(value)
    ]
    prior_pool = _loads(plan.get("pool_snapshot_json"), {})
    if (
        "target_video_count" in patch
        and "product_video_allocations" not in patch
    ):
        raise CreativeProductionError(
            "PRODUCT_VIDEO_ALLOCATIONS_REQUIRED",
            "Changing target_video_count requires exact product allocations.",
        )
    allocation_rows = patch.get(
        "product_video_allocations",
        prior_pool.get("product_video_allocations"),
    )
    valid_allocations = _validated_allocation_rows(
        product_scope,
        current_targets["target_video_count"],
        allocation_rows,
    )
    if valid_allocations is None:
        raise CreativeProductionError(
            "PRODUCT_VIDEO_ALLOCATIONS_INVALID",
            "Product allocations must cover the plan products exactly and sum "
            "to target_video_count.",
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
            "product_video_allocations": valid_allocations,
        }
        values["pool_snapshot_json"] = _stable_json(next_pool)
    elif {
        "controlled_reuse_reason",
        "controlled_reuse_max_per_dna",
        "product_video_allocations",
    } & set(patch):
        next_pool = dict(prior_pool)
        if "controlled_reuse_reason" in patch:
            next_pool["controlled_reuse_reason"] = patch[
                "controlled_reuse_reason"
            ]
        if "controlled_reuse_max_per_dna" in patch:
            next_pool["controlled_reuse_max_per_dna"] = patch[
                "controlled_reuse_max_per_dna"
            ]
        next_pool["product_video_allocations"] = valid_allocations
        values["pool_snapshot_json"] = _stable_json(next_pool)

    next_pool = _loads(
        values.get("pool_snapshot_json", plan.get("pool_snapshot_json")),
        {},
    )
    # Preserve the legacy field for schema compatibility, but never carry a
    # Creative Library product visual into an updated executable P6 snapshot.
    next_pool["product_reference_asset_ids"] = []
    if (
        int(next_pool.get("controlled_reuse_max_per_dna") or 1) > 1
        and not str(next_pool.get("controlled_reuse_reason") or "").strip()
    ):
        raise CreativeProductionError(
            "CONTROLLED_REUSE_REASON_REQUIRED",
            "Exact DNA reuse requires an explicit reason and bounded reuse limit.",
        )
    authority_plan = {**plan, **values}
    next_pool["treatments"] = await _resolve_plan_treatments(
        {
            **authority_plan,
            "pool_snapshot_json": _stable_json(next_pool),
        }
    )
    values["pool_snapshot_json"] = _stable_json(next_pool)
    policy.update(
        {
            "last_update_request_id": request_id,
            "last_update_request_sha256": request_sha,
            "last_updated_by": operator_id,
            "last_updated_at": _now(),
        }
    )
    values["execution_policy_json"] = _stable_json(policy)
    next_plan = {**plan, **values}
    product_names = {
        str(allocation.get("product_id") or ""): str(
            allocation.get("product_name") or ""
        )
        for allocation in prior_snapshot.get("product_allocations", [])
        if isinstance(allocation, dict)
    }
    snapshot = _snapshot_from_plan_values(
        next_plan,
        allocations=valid_allocations,
        product_names=product_names,
        source=str(prior_snapshot["source"]),
        evidence={
            **dict(prior_snapshot.get("evidence") or {}),
            "last_update_request_sha256": request_sha,
            "last_updated_by": operator_id,
        },
    )
    if snapshot["completeness"] != "COMPLETE":
        raise CreativeProductionError(
            "PLAN_SNAPSHOT_INCOMPLETE",
            "The plan update would produce an incomplete canonical snapshot.",
            details={"missing_fields": snapshot["missing_fields"]},
        )
    values["plan_snapshot_json"] = _stable_json(snapshot)
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
    copy_bindings: list[dict[str, Any]] = []
    avatar_profiles: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    avatar_index = {
        str(row["avatar_code"]): row for row in avatar_registry.list_pool()
    }
    for product_id in body.product_ids:
        if legacy_copy_maintenance_enabled():
            copy_sets.extend(
                await copy_rotation_service.list_eligible_copy_sets(product_id)
            )
            poster_copy_sets.extend(
                row
                for row in await crud.list_poster_copy_sets_for_product(product_id)
                if row.get("status") == "POSTER_COPY_APPROVED"
            )
        else:
            for lane in ("PRODUCTION_STUDIO_P6", "POSTER_BUILDER"):
                try:
                    authority = await _v2_copy_authority_record(product_id, lane)
                    copy_bindings.append(
                        {
                            "product_id": product_id,
                            "lane": lane,
                            "binding_id": authority.get("copy_binding_id"),
                            "blueprint_id": authority.get("blueprint_id"),
                            "revision": authority.get("revision"),
                            "formula_id": authority.get("formula_family"),
                        }
                    )
                except CreativeProductionError as exc:
                    blockers.append(
                        {
                            "code": exc.code,
                            "product_id": product_id,
                            "lane": lane,
                            "details": exc.details,
                        }
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
        "copy_bindings": copy_bindings,
        "copy_authority": (
            "LEGACY_MAINTENANCE"
            if legacy_copy_maintenance_enabled()
            else "COPY_REGISTER_V2_ONLY"
        ),
        "avatar_profiles": avatar_profiles,
        # Deliberately empty: product visuals are resolved per product from
        # Product Registration's approved Official Product Visual at compile /
        # dispatch time, not selected from the Creative Library pool.
        "product_reference_assets": [],
        "official_product_visual_authority": {
            "source": "PRODUCT_REGISTRATION",
            "selection": "ONE_APPROVED_OFFICIAL_VISUAL_PER_PRODUCT",
            "used_by": ["IMG", "HYBRID", "I2V", "F2V", "POSTER"],
        },
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
    decoded_items = [_decode_row(row) for row in items]
    decoded_attempts = [_decode_row(row) for row in attempts]
    decoded_qa = [_decode_row(row) for row in qa]
    return ProductionPlanDetailResponse(
        plan=_decode_row(plan),
        snapshot=await _render_plan_snapshot(
            plan,
            items=decoded_items,
            attempts=decoded_attempts,
            qa=decoded_qa,
        ),
        waves=[_decode_row(row) for row in waves],
        batches=[_decode_row(row) for row in batches],
        items=decoded_items,
        attempts=decoded_attempts,
        qa=decoded_qa,
        audit_events=[_decode_row(row) for row in audit_events],
        progress={
            "total": len(items),
            "terminal": terminal,
            "percent": round((terminal / len(items)) * 100, 2) if items else 0.0,
            "by_status": dict(sorted(counts.items())),
        },
    )


def _selection_avatar_codes(selection: dict[str, Any] | None) -> list[str]:
    """The product's diverse avatar picks (multi-select list) with a single-pick
    fallback, so the production plan can rotate presenters instead of repeating one.
    """
    if not selection:
        return []
    codes = [
        str(c).strip()
        for c in (_loads(selection.get("selected_avatar_codes_json"), []) or [])
        if str(c or "").strip()
    ]
    if not codes:
        single = str(selection.get("selected_avatar_code") or "").strip()
        codes = [single] if single else []
    return _unique(codes)


def _selection_scene_template_ids(selection: dict[str, Any] | None) -> list[str]:
    """The product's diverse scene picks with a single-pick fallback."""
    if not selection:
        return []
    scene_ids = [
        str(value).strip()
        for value in (
            _loads(selection.get("selected_scene_template_ids_json"), []) or []
        )
        if str(value or "").strip()
    ]
    if not scene_ids:
        single = str(selection.get("selected_scene_template_id") or "").strip()
        scene_ids = [single] if single else []
    return _unique(scene_ids)


async def _load_approved_pools(plan: dict[str, Any]) -> dict[str, Any]:
    pool = _loads(plan.get("pool_snapshot_json"), {})
    product_ids = _loads(plan.get("product_scope_json"), [])
    blockers: list[dict[str, Any]] = []
    logical_mode = str(plan["logical_mode"])
    target_video_count = int(plan["target_video_count"])
    treatment_projections = await _resolve_plan_treatments(plan)
    treatment_authority_active = bool(treatment_projections)

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
    poster_copy_sets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    image_copy_authorities: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if legacy_copy_maintenance_enabled():
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
    else:
        for product_id in products:
            try:
                if int(plan.get("target_video_count") or 0) > 0:
                    copy_sets[product_id].append(
                        await _v2_copy_authority_record(
                            product_id,
                            "PRODUCTION_STUDIO_P6",
                        )
                    )
                if int(plan.get("target_image_count") or 0) > 0:
                    image_copy_authorities[product_id].append(
                        await _v2_copy_authority_record(product_id, "IMAGE_GEN")
                    )
                if int(plan.get("target_poster_count") or 0) > 0:
                    poster_copy_sets[product_id].append(
                        await _v2_copy_authority_record(product_id, "POSTER_BUILDER")
                    )
            except CreativeProductionError as exc:
                blockers.append(
                    {
                        "code": exc.code,
                        "product_id": product_id,
                        "details": exc.details,
                    }
                )

    avatar_index = {
        str(row["avatar_code"]): row for row in avatar_registry.list_pool()
    }
    requested_avatar_codes = _unique(pool.get("avatar_codes") or [])
    avatar_profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    approved_codes: set[str] = set()
    for product_id in products:
        selection = creative_selections.get(product_id)
        selection_approved = (
            selection is not None and selection.get("status") == "APPROVED"
        )
        # Rotate presenters: admit the product's WHOLE diverse avatar selection
        # (multi-select list, single-pick fallback) that is in this plan's pool, so
        # the plan varies the avatar instead of repeating one. Each code stays gated
        # on adult + resolvable profile + APPROVED selection.
        selected_codes = _selection_avatar_codes(selection)
        avatar_required = (
            target_video_count > 0 and logical_mode in {"T2V", "HYBRID", "I2V"}
            and not treatment_authority_active
        )
        if avatar_required and (not selection_approved or not selected_codes):
            blockers.append(
                {
                    "code": "APPROVED_PRODUCT_AVATAR_SELECTION_REQUIRED",
                    "product_id": product_id,
                }
            )
            continue
        if not selection_approved or not selected_codes:
            continue
        admitted_here = 0
        for selected_code in selected_codes:
            profile = avatar_index.get(selected_code)
            if not selected_code or profile is None:
                continue
            if selected_code not in requested_avatar_codes:
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
            admitted_here += 1
        if avatar_required and admitted_here == 0:
            blockers.append(
                {
                    "code": "APPROVED_PRODUCT_AVATAR_NOT_IN_PLAN_POOL",
                    "product_id": product_id,
                    "avatar_code": selected_codes[0] if selected_codes else None,
                }
            )
            continue
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
        "image_copy_authorities": image_copy_authorities,
        "avatar_profiles": avatar_profiles,
        "assets": assets,
        "approved_layouts": {
            key: value
            for key, value in approved_layouts.items()
            if value is not None
        },
        "scene_strategies": scene_strategies,
        "creative_selections": creative_selections,
        "treatments": treatment_projections,
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
    from agent.services.scene_choreography_catalog import all_choreography_variants

    count = max(
        len(all_choreography_variants().get(strategy["strategy_id"], ())),
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
    selection = approved["creative_selections"].get(product_id)
    selected_scene_ids = _selection_scene_template_ids(selection)
    if not selected_scene_ids:
        return variants
    templates_by_id = {
        str(template.get("template_id")): template
        for template in creative_scene_prompt_service.library_templates()
        if template.get("template_id")
    }
    selected_templates = [
        templates_by_id[scene_id]
        for scene_id in selected_scene_ids
        if scene_id in templates_by_id
    ]
    if not selected_templates:
        # Keep the existing strategy authority if an approved selection's scene
        # ids have drifted out of the current library; the recipe service applies
        # the same fail-soft policy for a drifted saved plan.
        return variants
    rotated: list[dict[str, str]] = []
    for index, template in enumerate(selected_templates):
        base = dict(variants[index % len(variants)])
        rotated.append(
            {
                **base,
                "scene_template_id": str(template["template_id"]),
                "camera_preset_code": creative_recipe_service.camera_for_variant(
                    template.get("variant")
                ),
            }
        )
    return rotated
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
        "scene_template_id",
        "camera_preset_code",
        "style_asset_id",
        "layout_id",
        "camera_composition",
        "product_interaction",
        "model_key",
        "duration_seconds",
        "generation_mode",
        "engine_block_duration_seconds",
        "segment_count",
        "execution_route",
        "treatment_id",
        "treatment_sha256",
        "treatment_visual_fingerprint_sha256",
        "treatment_format",
        "variation_group_id",
        "variation_group_sha256",
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
    # Product references are not a P6 variation dimension.  P6 must compile
    # every image/video item against the one Official Product Visual selected
    # in Product Registration; carrying a creative-library product asset here
    # would allow cosmetic props or a stale combo image to re-enter the lane.
    product_refs = [{}]
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

    if media_type == "VIDEO" and approved.get("treatments"):
        treatment_rows = [
            treatment
            for treatment in approved["treatments"]
            if treatment["product_id"] == product_id
        ]
        v2_copy_dimensions: dict[str, str] | None = None
        if not legacy_copy_maintenance_enabled():
            copy_authorities = approved["copy_sets"].get(product_id) or []
            if not copy_authorities:
                blockers.append(
                    {"code": "V2 BINDING REQUIRED", "product_id": product_id}
                )
                return len(treatment_rows), [], blockers
            v2_copy_dimensions = _copy_dimensions(copy_authorities[0], near_threshold)
        rows: list[dict[str, Any]] = []
        for treatment in treatment_rows:
            asset_by_role = {
                str(binding.get("role") or ""): str(
                    binding.get("asset_id") or ""
                )
                for binding in treatment["asset_bindings"]
                if isinstance(binding, dict)
            }
            duration = int(float(treatment["duration_seconds"]))
            model_key = str(treatment["selected_model_key"])
            try:
                orchestration = video_models.resolve_orchestration(
                    model_key,
                    duration,
                )
            except ValueError as exc:
                blockers.append(
                    {
                        "code": "TREATMENT_INCOMPATIBLE",
                        "treatment_id": treatment["treatment_id"],
                        "detail": str(exc),
                    }
                )
                continue
            if orchestration["generation_mode"] != treatment["generation_mode"]:
                blockers.append(
                    {
                        "code": "TREATMENT_INCOMPATIBLE",
                        "treatment_id": treatment["treatment_id"],
                        "detail": "Treatment mode does not match model orchestration.",
                    }
                )
                continue
            segment_plan = treatment.get("segment_plan") or []
            if orchestration["generation_mode"] == "EXTEND" and (
                not isinstance(segment_plan, dict)
                or int(segment_plan.get("segment_count") or 0)
                != int(orchestration["segment_count"])
            ):
                blockers.append(
                    {
                        "code": "TREATMENT_SEGMENT_PLAN_INVALID",
                        "treatment_id": treatment["treatment_id"],
                    }
                )
                continue
            group = treatment.get("variation_group") or {}
            copy_dimensions = v2_copy_dimensions or {
                "copy_set_id": treatment["copy_set_id"],
                "copy_identity_sha256": treatment["dependency_hashes"][
                    "copy_set_sha256"
                ],
                "marketing_angle": treatment["content_angle"],
                "hook": treatment["dialogue_text"],
                "cta": "",
                "formula_family": "CREATIVE_TREATMENT",
                "claim_safety_status": "APPROVED",
                "copy_usage_count": "0",
                "near_duplicate_status": "CLEAR",
                "near_duplicate_score": "0.0",
                "similar_to_copy_set_id": "",
            }
            rows.append(
                {
                    "product_id": product_id,
                    "media_type": "VIDEO",
                    "logical_mode": logical_mode,
                    **copy_dimensions,
                    "avatar_code": treatment["avatar_code"],
                    "age_band": "",
                    "wardrobe": treatment["wardrobe_text"],
                    "avatar_variant": "",
                    # Treatment evidence may retain its original binding for
                    # audit, but it is never a provider reference.  The WGP
                    # compiler resolves Product Registration's official visual.
                    "product_reference_asset_id": "",
                    "finished_frame_asset_id": asset_by_role.get(
                        "COMPOSITE_FRAME_REFERENCE",
                        "",
                    ),
                    "character_asset_id": asset_by_role.get(
                        "CHARACTER_REFERENCE",
                        "",
                    ),
                    "scene_asset_id": asset_by_role.get(
                        "SCENE_CONTEXT_REFERENCE",
                        "",
                    ),
                    "style_asset_id": asset_by_role.get(
                        "STYLE_REFERENCE",
                        "",
                    ),
                    "scene_strategy_id": treatment["scene_strategy_id"],
                    "scene_family": treatment["scene_strategy_id"],
                    "scene_strategy": treatment["scene_strategy_id"],
                    "scene_context": treatment["scene_template_id"],
                    "scene_template_id": treatment["scene_template_id"],
                    "camera_preset_code": treatment["camera_preset_code"],
                    "product_interaction": _stable_json(
                        treatment["action_sequence"]
                    ),
                    "camera_composition": treatment["camera_preset_code"],
                    "strategy_avatar_hint": treatment["avatar_code"],
                    "strategy_wardrobe_hint": treatment["wardrobe_text"],
                    "scene_strategy_context": treatment[
                        "scene_template_id"
                    ],
                    "layout_id": "",
                    "model_key": model_key,
                    "duration_seconds": str(duration),
                    "generation_mode": orchestration["generation_mode"],
                    "engine_block_duration_seconds": str(
                        orchestration["engine_block_duration_seconds"]
                    ),
                    "segment_count": str(orchestration["segment_count"]),
                    "execution_route": orchestration["execution_route"],
                    "treatment_id": treatment["treatment_id"],
                    "treatment_sha256": treatment["treatment_sha256"],
                    "treatment_visual_fingerprint_sha256": treatment[
                        "visual_fingerprint_sha256"
                    ],
                    "treatment_format": treatment["format"],
                    "variation_group_id": treatment.get(
                        "variation_group_id"
                    )
                    or "",
                    "variation_group_sha256": group.get("group_sha256") or "",
                    "creative_treatment": treatment,
                    "exact_duplicate_status": "UNIQUE",
                    "quota_status": "WITHIN_POLICY",
                    "readiness": "PREFLIGHT_ELIGIBLE",
                    "blockers": "",
                }
            )
        return len(treatment_rows), rows, blockers

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
    elif media_type == "IMAGE" and not legacy_copy_maintenance_enabled():
        copies = approved["image_copy_authorities"].get(product_id) or []
        if not copies:
            blockers.append(
                {"code": "COPY_NOT_REQUIRED_PROOF_MISSING", "product_id": product_id}
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
                product_refs,
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
        try:
            orchestration = video_models.resolve_orchestration(
                model_key,
                int(duration),
            )
        except ValueError as exc:
            blockers.append(
                {
                    "code": "INVALID_MODEL_DURATION_COMBINATION",
                    "product_id": product_id,
                    "model_key": str(model_key),
                    "duration_seconds": int(duration),
                    "detail": str(exc),
                }
            )
            continue
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
                "generation_mode": orchestration["generation_mode"],
                "engine_block_duration_seconds": str(
                    orchestration["engine_block_duration_seconds"]
                ),
                "segment_count": str(orchestration["segment_count"]),
                "execution_route": orchestration["execution_route"],
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
        if media_type in {"VIDEO", "POSTER"}:
            capped_candidates[media_type] = rows
            if media_type == "VIDEO":
                copy_capacity_slots += len(rows)
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
        "product_references": 0,
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
        "treatments": len(approved.get("treatments") or []),
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
        if media_type == "VIDEO":
            safe_capacity[media_type] = unique_capacity[media_type]
            continue
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
    video_allocations = _video_allocations(plan)
    for product_id, requested_count in video_allocations.items():
        product_rows = [
            (dna, dimension)
            for dna, dimension in candidates["VIDEO"]
            if dimension.get("product_id") == product_id
        ]
        product_safe_capacity = len({dna for dna, _ in product_rows})
        if requested_count > product_safe_capacity:
            blockers.append(
                {
                    "code": "PRODUCT_VIDEO_CAPACITY_SHORTFALL",
                    "product_id": product_id,
                    "requested": requested_count,
                    "available": product_safe_capacity,
                    "shortfall": requested_count - product_safe_capacity,
                }
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
        "capacity_is_unique_cartesian_product": (
            int(plan["target_video_count"]) == 0
        ),
        "video_capacity_is_cartesian_product": False,
        "video_capacity_authority": "APPROVED_CREATIVE_TREATMENTS",
        "video_controlled_reuse_enabled": False,
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
        "product_video_allocations": video_allocations,
        "explicit_product_allocation": bool(video_allocations),
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
    video_allocations = _video_allocations(plan)
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
        selection_groups: list[
            tuple[str | None, int, list[tuple[str, dict[str, str]]]]
        ]
        if media_type == "VIDEO" and video_allocations:
            selection_groups = [
                (
                    product_id,
                    product_target,
                    [
                        (dna, dimension)
                        for dna, dimension in rows
                        if dimension.get("product_id") == product_id
                    ],
                )
                for product_id, product_target in video_allocations.items()
            ]
        else:
            selection_groups = [(None, target, rows)]
        for product_id, group_target, group_rows in selection_groups:
            if not group_rows and group_target:
                raise CreativeProductionError(
                    "PRODUCT_CAPACITY_CANDIDATE_MISSING",
                    (
                        f"No safe {media_type} candidates remain for "
                        f"{product_id or 'the governed scope'}."
                    ),
                    status_code=409,
                )
            cursor = 0
            selected_in_group = 0
            media_reuse_max = 1 if media_type == "VIDEO" else controlled_reuse_max
            while selected_in_group < group_target:
                if cursor >= len(group_rows) * media_reuse_max:
                    raise CreativeProductionError(
                        "CONTROLLED_CAPACITY_SELECTION_FAILED",
                        (
                            f"Bounded selection could not fill {media_type} "
                            f"target for {product_id or 'the governed scope'}."
                        ),
                        status_code=409,
                    )
                dna, dimensions = group_rows[cursor % len(group_rows)]
                cursor += 1
                if dna_uses[dna] >= (
                    media_reuse_max
                    if controlled_reuse_reason and media_type != "VIDEO"
                    else 1
                ):
                    continue
                copy_set_id = dimensions["copy_set_id"]
                if media_type == "IMAGE":
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
                selected_in_group += 1

    if video_allocations:
        materialized_video_counts = Counter(
            dimensions["product_id"]
            for _, dimensions, _ in selected
            if dimensions["media_type"] == "VIDEO"
        )
        if dict(materialized_video_counts) != video_allocations:
            raise CreativeProductionError(
                "PRODUCT_VIDEO_ALLOCATION_INVARIANT_FAILED",
                "Materialized video items do not match the durable product allocation.",
                status_code=409,
                details={
                    "requested": video_allocations,
                    "materialized": dict(materialized_video_counts),
                },
            )

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
