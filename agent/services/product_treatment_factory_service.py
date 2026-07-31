"""Durable, deterministic Product-to-Treatment Factory orchestration.

The factory coordinates existing authorities. It never approves copy or treatments,
never calls a provider, and never invokes P6/compiler/scheduler execution.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agent.db import crud
from agent.db import product_treatment_factory_crud as factory_crud
from agent.models.creative_treatment import AssetBindingRequest, CreateTreatmentRequest
from agent.models.product_readiness import (
    ProductReadinessEvaluateRequest,
    ProductReadinessProjection,
    ResolvedProductReadinessInput,
)
from agent.models.product_treatment_factory import (
    CreateFactoryPlanRequest,
    FactoryPlanControlRequest,
    FactoryPlanProjection,
    FactoryProductContext,
    FactoryTaskProjection,
    FactoryTaskStatus,
    FactoryTaskType,
    PrepareFactoryPlanRequest,
    TreatmentTemplateProjection,
)
from agent.services import (
    copy_composer_service,
    creative_treatment_service,
    product_readiness_applicability_service,
)
from agent.services.product_treatment_template_service import (
    ProductTreatmentTemplateError,
    resolve_treatment_template,
)


FACTORY_VERSION = "product-treatment-factory-v1"
TASK_TYPES: tuple[FactoryTaskType, ...] = (
    "PRODUCT_TRUTH_REVIEW",
    "EVIDENCE_REVIEW",
    "COPY_GROUNDING",
    "COPY_COMPOSITION",
    "COPY_REVIEW",
    "CREATIVE_SELECTION",
    "ASSET_SUPPLY",
    "TREATMENT_CANDIDATE",
    "TREATMENT_REVIEW",
    "P6_CAPACITY",
)
TERMINAL_TASK_STATES = {"REVIEW_REQUIRED", "SATISFIED", "FAILED", "SUPERSEDED"}


class ProductTreatmentFactoryError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int = 422,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class ProductScan:
    context: FactoryProductContext
    resolved: ResolvedProductReadinessInput | None
    readiness: ProductReadinessProjection | None
    template: TreatmentTemplateProjection | None
    copy_preview: dict[str, object]
    treatments: list[dict[str, object]]
    error_code: str | None


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _sequence_of_mappings(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _first_string(value: object) -> str | None:
    items = sorted(_string_list(value))
    return items[0] if items else None


def _task_projection(row: dict[str, object]) -> FactoryTaskProjection:
    return FactoryTaskProjection(
        task_id=str(row["task_id"]),
        plan_id=str(row["plan_id"]),
        product_id=str(row["product_id"]),
        task_type=cast(FactoryTaskType, str(row["task_type"])),
        status=cast(FactoryTaskStatus, str(row["status"])),
        task_identity_sha256=str(row["task_identity_sha256"]),
        required_authority_sha256=str(row["required_authority_sha256"]),
        blocker_code=cast(str | None, row.get("blocker_code")),
        next_action=cast(str | None, row.get("next_action")),
        template_id=cast(str | None, row.get("template_id")),
        template_sha256=cast(str | None, row.get("template_sha256")),
        treatment_id=cast(str | None, row.get("treatment_id")),
        treatment_sha256=cast(str | None, row.get("treatment_sha256")),
        snapshot=_mapping(row.get("snapshot")),
        result=_mapping(row.get("result")),
        error_code=cast(str | None, row.get("error_code")),
        attempt_count=int(row.get("attempt_count") or 0),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


async def _plan_projection(row: dict[str, object]) -> FactoryPlanProjection:
    task_rows = await factory_crud.list_tasks(str(row["plan_id"]))
    return FactoryPlanProjection(
        plan_id=str(row["plan_id"]),
        plan_identity_sha256=str(row["plan_identity_sha256"]),
        cohort_sha256=str(row["cohort_sha256"]),
        context_sha256=str(row["context_sha256"]),
        status=cast(str, row["status"]),
        product_count=int(row["product_count"]),
        request=_mapping(row.get("request")),
        authority_versions=_mapping(row.get("authority_versions")),
        readiness_summary={
            str(key): int(value)
            for key, value in _mapping(row.get("readiness_summary")).items()
        },
        capacity_summary=_mapping(row.get("capacity_summary")),
        failure_count=int(row.get("failure_count") or 0),
        provider_calls_enabled=False,
        media_generation_enabled=False,
        created_by=str(row["created_by"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        tasks=[_task_projection(task) for task in task_rows],
    )


def _layer_map(readiness: ProductReadinessProjection) -> dict[str, object]:
    return {layer.layer: layer for layer in readiness.readiness_layers}


def _layer_decision(
    readiness: ProductReadinessProjection,
    layer: str,
    *,
    ready_status: FactoryTaskStatus = "SATISFIED",
    blocked_status: FactoryTaskStatus = "REVIEW_REQUIRED",
) -> tuple[FactoryTaskStatus, str | None, str | None]:
    result = _layer_map(readiness).get(layer)
    if result is None:
        return blocked_status, f"{layer.upper()}_AUTHORITY_MISSING", f"REVIEW_{layer.upper()}"
    state = str(getattr(result, "state", "BLOCKED"))
    blocker_codes = list(getattr(result, "blocker_codes", []))
    if state == "READY" or state == "NOT_APPLICABLE":
        return ready_status, None, None
    blocker = str(blocker_codes[0]) if blocker_codes else f"{layer.upper()}_{state}"
    return blocked_status, blocker, f"RESOLVE_{layer.upper()}"


def _error_code(error: Exception) -> str:
    for attribute in ("code",):
        value = getattr(error, attribute, None)
        if isinstance(value, str) and value:
            return value
    message = str(error).strip()
    return message or error.__class__.__name__.upper()


async def _resolve_contexts(
    request: CreateFactoryPlanRequest,
) -> list[FactoryProductContext]:
    if request.scan_all_active:
        products = await crud.list_products(include_archived=False)
        product_ids = sorted(
            str(product["id"])
            for product in products
            if product.get("id")
        )
        if not product_ids:
            raise ProductTreatmentFactoryError(
                "FACTORY_COHORT_EMPTY",
                status_code=422,
            )
        return [
            FactoryProductContext(
                product_id=product_id,
                **request.defaults.model_dump(),
            )
            for product_id in product_ids
        ]
    return sorted(request.products, key=lambda item: item.product_id)


async def _scan_product(context: FactoryProductContext) -> ProductScan:
    readiness_request = ProductReadinessEvaluateRequest(
        product_id=context.product_id,
        allowed_action_index=context.selected_action_index,
        creative_format=context.format,
        logical_mode=context.logical_mode,
        generation_mode=context.generation_mode,
        model_key=context.model_key,
        duration_seconds=context.duration_seconds,
    )
    try:
        resolved = await product_readiness_applicability_service.resolve_readiness_input(
            readiness_request
        )
        readiness = (
            product_readiness_applicability_service.evaluate_resolved_readiness(
                resolved
            )
        )
        template = resolve_treatment_template(
            context=readiness_request,
            profile=readiness.applicability_profile,
            requirements=readiness.evidence_requirements,
        )
        raw_preview = await copy_composer_service.compose_and_persist(
            context.product_id,
            1,
            dry_run=True,
        )
        raw_treatments = await creative_treatment_service.list_treatments(
            product_id=context.product_id,
            status=None,
            variation_group_id=None,
            limit=1000,
        )
        return ProductScan(
            context=context,
            resolved=resolved,
            readiness=readiness,
            template=template,
            copy_preview=_mapping(raw_preview),
            treatments=[_mapping(item) for item in raw_treatments],
            error_code=None,
        )
    except Exception as error:
        return ProductScan(
            context=context,
            resolved=None,
            readiness=None,
            template=None,
            copy_preview={},
            treatments=[],
            error_code=_error_code(error),
        )


def _task_snapshot(scan: ProductScan) -> dict[str, object]:
    readiness = scan.readiness
    template = scan.template
    resolved = scan.resolved
    return {
        "factory_version": FACTORY_VERSION,
        "context": scan.context.model_dump(mode="json"),
        "readiness": readiness.model_dump(mode="json") if readiness else {},
        "resolved_authority": (
            resolved.model_dump(mode="json", by_alias=True) if resolved else {}
        ),
        "treatment_template": (
            template.model_dump(mode="json") if template else {}
        ),
        "copy_preview": scan.copy_preview,
        "existing_treatments": scan.treatments,
        "scan_error_code": scan.error_code,
        "provider_calls": 0,
        "media_generation_calls": 0,
        "credit_spend": 0,
    }


def _evidence_decision(
    readiness: ProductReadinessProjection,
) -> tuple[FactoryTaskStatus, str | None, str | None]:
    outstanding = [
        item
        for item in readiness.evidence_requirements
        if item.applicable and item.state != "VERIFIED_VALUE"
    ]
    if not outstanding:
        return "SATISFIED", None, None
    return (
        "REVIEW_REQUIRED",
        f"EVIDENCE_{outstanding[0].state}",
        "REVIEW_PRODUCT_EVIDENCE",
    )


def _candidate_ready(scan: ProductScan) -> bool:
    readiness = scan.readiness
    resolved = scan.resolved
    template = scan.template
    if readiness is None or resolved is None or template is None:
        return False
    layers = _layer_map(readiness)
    required = (
        "product_truth",
        "copy_set",
        "creative_selection",
        "visual_assets",
        "treatment_template",
    )
    return (
        all(str(getattr(layers.get(name), "state", "")) == "READY" for name in required)
        and bool(resolved.product_truth.snapshot_id)
        and bool(resolved.copy.approved_copy_set_ids)
        and bool(resolved.selection.selection_id)
        and not resolved.assets.missing_roles
        and bool(resolved.assets.required_roles)
    )


def _task_decision(
    scan: ProductScan,
    task_type: FactoryTaskType,
) -> tuple[FactoryTaskStatus, str | None, str | None]:
    if scan.error_code or scan.readiness is None or scan.resolved is None:
        return "REVIEW_REQUIRED", scan.error_code or "FACTORY_SCAN_FAILED", "REVIEW_PRODUCT"

    readiness = scan.readiness
    resolved = scan.resolved
    if task_type == "PRODUCT_TRUTH_REVIEW":
        return _layer_decision(readiness, "product_truth")
    if task_type == "EVIDENCE_REVIEW":
        return _evidence_decision(readiness)
    if task_type == "COPY_GROUNDING":
        return _layer_decision(readiness, "copy_grounding")
    if task_type == "COPY_COMPOSITION":
        if resolved.copy.approved_copy_set_ids:
            return "SATISFIED", None, None
        if int(scan.copy_preview.get("produced") or 0) > 0:
            return "READY", None, "MATERIALIZE_REVIEW_REQUIRED_COPY"
        return (
            "REVIEW_REQUIRED",
            "COPY_COMPONENT_SUPPLY_REQUIRED",
            "REVIEW_COPY_COMPONENT_SUPPLY",
        )
    if task_type == "COPY_REVIEW":
        if resolved.copy.approved_copy_set_ids:
            return "SATISFIED", None, None
        return "REVIEW_REQUIRED", "APPROVED_COPY_SET_REQUIRED", "REVIEW_COPY_SET"
    if task_type == "CREATIVE_SELECTION":
        return _layer_decision(readiness, "creative_selection")
    if task_type == "ASSET_SUPPLY":
        return _layer_decision(readiness, "visual_assets")
    if task_type == "TREATMENT_CANDIDATE":
        if resolved.treatment.approved_treatment_ids:
            return "SATISFIED", None, None
        if _candidate_ready(scan):
            return "READY", None, "MATERIALIZE_REVIEW_REQUIRED_TREATMENT"
        return (
            "PENDING",
            "TREATMENT_PREREQUISITES_REQUIRED",
            "RESOLVE_TREATMENT_PREREQUISITES",
        )
    if task_type == "TREATMENT_REVIEW":
        if resolved.treatment.approved_treatment_ids:
            return "SATISFIED", None, None
        if any(
            str(item.get("status")) in {"DRAFT", "IN_REVIEW"}
            for item in scan.treatments
        ):
            return "REVIEW_REQUIRED", "TREATMENT_REVIEW_REQUIRED", "REVIEW_TREATMENT"
        return "PENDING", "TREATMENT_CANDIDATE_REQUIRED", "CREATE_TREATMENT_CANDIDATE"
    if task_type == "P6_CAPACITY":
        if resolved.treatment.p6_ready:
            return "SATISFIED", None, None
        return "REVIEW_REQUIRED", "P6_CAPACITY_NOT_READY", "RESOLVE_P6_CAPACITY"
    raise ProductTreatmentFactoryError("UNKNOWN_FACTORY_TASK_TYPE")


def _readiness_summary(tasks: list[dict[str, object]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for task in tasks:
        status = str(task["status"])
        summary[status] = summary.get(status, 0) + 1
    return summary


def _capacity_summary(
    scans: list[ProductScan],
    tasks: list[dict[str, object]],
) -> dict[str, object]:
    p6_ready_products = sorted(
        scan.context.product_id
        for scan in scans
        if scan.resolved is not None and scan.resolved.treatment.p6_ready
    )
    approved_master_treatments = sorted(
        {
            treatment_id
            for scan in scans
            if scan.resolved is not None
            for treatment_id in scan.resolved.treatment.approved_treatment_ids
        }
    )
    return {
        "product_count": len(scans),
        "task_count": len(tasks),
        "p6_ready_product_count": len(p6_ready_products),
        "p6_ready_product_ids": p6_ready_products,
        "approved_master_treatment_count": len(approved_master_treatments),
        "approved_master_treatment_ids": approved_master_treatments,
        "extend_segments_counted": 0,
    }


async def create_plan(request: CreateFactoryPlanRequest) -> FactoryPlanProjection:
    contexts = await _resolve_contexts(request)
    scans = [await _scan_product(context) for context in contexts]
    request_snapshot: dict[str, object] = {
        "factory_version": FACTORY_VERSION,
        "products": [context.model_dump(mode="json") for context in contexts],
        "scan_all_active": request.scan_all_active,
        "provider_calls_enabled": False,
        "media_generation_enabled": False,
    }
    cohort_sha256 = canonical_sha256(
        [context.product_id for context in contexts]
    )
    context_sha256 = canonical_sha256(
        [context.model_dump(mode="json") for context in contexts]
    )
    authority_versions: dict[str, object] = {
        "factory_version": FACTORY_VERSION,
        "products": [
            {
                "product_id": scan.context.product_id,
                "product_authority_sha256": (
                    scan.readiness.product_authority_sha256
                    if scan.readiness
                    else None
                ),
                "readiness_sha256": (
                    scan.readiness.readiness_sha256 if scan.readiness else None
                ),
                "template_sha256": (
                    scan.template.template_sha256 if scan.template else None
                ),
                "scan_error_code": scan.error_code,
            }
            for scan in scans
        ],
    }
    plan_identity_sha256 = canonical_sha256(
        {
            "cohort_sha256": cohort_sha256,
            "context_sha256": context_sha256,
            "authority_versions": authority_versions,
        }
    )
    plan, created = await factory_crud.create_or_get_plan(
        plan_identity_sha256=plan_identity_sha256,
        cohort_sha256=cohort_sha256,
        context_sha256=context_sha256,
        product_count=len(contexts),
        request=request_snapshot,
        authority_versions=authority_versions,
        created_by=request.created_by,
    )
    plan_id = str(plan["plan_id"])
    existing_status = str(plan["status"])
    if created:
        await factory_crud.append_event(
            plan_id=plan_id,
            task_id=None,
            event_identity_sha256=canonical_sha256(
                {"plan": plan_id, "action": "PLAN_CREATED"}
            ),
            actor_id=request.created_by,
            action="PLAN_CREATED",
            source_state=None,
            target_state="DRAFT",
            evidence={
                "plan_identity_sha256": plan_identity_sha256,
                "provider_calls": 0,
                "media_generation_calls": 0,
                "credit_spend": 0,
            },
        )

    for scan in scans:
        snapshot = _task_snapshot(scan)
        for task_type in TASK_TYPES:
            status, blocker_code, next_action = _task_decision(scan, task_type)
            required_authority_sha256 = canonical_sha256(
                {
                    "readiness_sha256": (
                        scan.readiness.readiness_sha256 if scan.readiness else None
                    ),
                    "template_sha256": (
                        scan.template.template_sha256 if scan.template else None
                    ),
                    "scan_error_code": scan.error_code,
                }
            )
            task_identity_sha256 = canonical_sha256(
                {
                    "plan_identity_sha256": plan_identity_sha256,
                    "product_id": scan.context.product_id,
                    "task_type": task_type,
                    "required_authority_sha256": required_authority_sha256,
                }
            )
            await factory_crud.create_or_get_task(
                plan_id=plan_id,
                product_id=scan.context.product_id,
                task_type=task_type,
                status=status,
                task_identity_sha256=task_identity_sha256,
                required_authority_sha256=required_authority_sha256,
                blocker_code=blocker_code,
                next_action=next_action,
                template_id=scan.template.template_id if scan.template else None,
                template_sha256=(
                    scan.template.template_sha256 if scan.template else None
                ),
                snapshot=snapshot,
            )

    if not created and existing_status != "DRAFT":
        return await get_plan(plan_id)

    task_rows = await factory_crud.list_tasks(plan_id)
    readiness_summary = _readiness_summary(task_rows)
    failure_count = sum(1 for scan in scans if scan.error_code)
    capacity_summary = _capacity_summary(scans, task_rows)
    await factory_crud.update_plan(
        plan_id,
        status="SCANNED",
        readiness_summary_json=factory_crud.encode(readiness_summary),
        capacity_summary_json=factory_crud.encode(capacity_summary),
        failure_count=failure_count,
        scanned_at=factory_crud.utc_now(),
    )
    await factory_crud.append_event(
        plan_id=plan_id,
        task_id=None,
        event_identity_sha256=canonical_sha256(
            {
                "plan": plan_id,
                "action": "PLAN_SCANNED",
                "readiness_summary": readiness_summary,
            }
        ),
        actor_id=request.created_by,
        action="PLAN_SCANNED",
        source_state="DRAFT",
        target_state="SCANNED",
        evidence={
            "readiness_summary": readiness_summary,
            "capacity_summary": capacity_summary,
            "failure_count": failure_count,
        },
    )
    return await get_plan(plan_id)


def _candidate_signature(value: Mapping[str, object]) -> str:
    return canonical_sha256(
        {
            "product_id": value.get("product_id"),
            "product_truth_snapshot_id": value.get("product_truth_snapshot_id"),
            "copy_set_id": value.get("copy_set_id"),
            "creative_selection_id": value.get("creative_selection_id"),
            "scene_strategy_id": value.get("scene_strategy_id"),
            "format": value.get("format"),
            "generation_mode": value.get("generation_mode"),
            "duration_seconds": value.get("duration_seconds"),
            "action_sequence": value.get("action_sequence"),
            "shot_grammar": value.get("shot_grammar"),
            "compatibility_profile": value.get("compatibility_profile"),
            "asset_bindings": sorted(
                _sequence_of_mappings(value.get("asset_bindings")),
                key=lambda item: (str(item.get("role")), str(item.get("asset_id"))),
            ),
        }
    )


def _treatment_request_from_snapshot(
    task: dict[str, object],
    *,
    created_by: str,
) -> CreateTreatmentRequest:
    snapshot = _mapping(task.get("snapshot"))
    resolved = _mapping(snapshot.get("resolved_authority"))
    context = _mapping(snapshot.get("context"))
    template = _mapping(snapshot.get("treatment_template"))
    product_truth = _mapping(resolved.get("product_truth"))
    copy_authority = _mapping(resolved.get("copy"))
    selection = _mapping(resolved.get("selection"))
    assets = _mapping(resolved.get("assets"))
    product_truth_snapshot_id = str(product_truth.get("snapshot_id") or "")
    copy_set_id = _first_string(copy_authority.get("approved_copy_set_ids"))
    creative_selection_id = str(selection.get("selection_id") or "")
    asset_bindings: list[AssetBindingRequest] = []
    eligible_by_role = _mapping(assets.get("eligible_asset_ids_by_role"))
    for role in _string_list(assets.get("required_roles")):
        asset_id = _first_string(eligible_by_role.get(role))
        if asset_id:
            asset_bindings.append(AssetBindingRequest(role=role, asset_id=asset_id))
    if (
        not product_truth_snapshot_id
        or not copy_set_id
        or not creative_selection_id
        or not asset_bindings
    ):
        raise ProductTreatmentFactoryError(
            "TREATMENT_PREREQUISITES_REQUIRED",
            details={"task_id": str(task["task_id"])},
        )
    return CreateTreatmentRequest(
        product_id=str(task["product_id"]),
        product_truth_snapshot_id=product_truth_snapshot_id,
        copy_set_id=copy_set_id,
        creative_selection_id=creative_selection_id,
        scene_strategy_id=str(template["scene_strategy_id"]),
        format=cast(str, template["format"]),
        generation_mode=cast(str, context["generation_mode"]),
        duration_seconds=float(template["duration_seconds"]),
        action_sequence=cast(list[dict[str, object]], template["action_sequence"]),
        shot_grammar=cast(list[dict[str, object]], template["shot_grammar"]),
        compatibility_profile=cast(
            dict[str, object],
            template["compatibility_profile"],
        ),
        asset_bindings=asset_bindings,
        created_by=created_by,
    )


async def _prepare_copy_task(
    task: dict[str, object],
) -> tuple[str, dict[str, object]]:
    result = await copy_composer_service.compose_and_persist(
        str(task["product_id"]),
        1,
        dry_run=False,
    )
    normalized = _mapping(result)
    if int(normalized.get("created") or 0) < 1:
        raise ProductTreatmentFactoryError(
            "COPY_COMPOSITION_NOT_MATERIALIZED",
            details={"task_id": str(task["task_id"])},
        )
    return "REVIEW_REQUIRED", normalized


async def _prepare_treatment_task(
    task: dict[str, object],
    *,
    actor_id: str,
) -> tuple[str, dict[str, object]]:
    request = _treatment_request_from_snapshot(task, created_by=actor_id)
    request_projection = request.model_dump(mode="json")
    signature = _candidate_signature(request_projection)
    existing = await creative_treatment_service.list_treatments(
        product_id=request.product_id,
        status=None,
        variation_group_id=None,
        limit=1000,
    )
    treatment = next(
        (
            _mapping(item)
            for item in existing
            if _candidate_signature(_mapping(item)) == signature
        ),
        None,
    )
    created = False
    if treatment is None:
        treatment = _mapping(
            await creative_treatment_service.create_treatment(request)
        )
        created = True
    treatment_id = str(treatment["treatment_id"])
    treatment_sha256 = str(treatment["treatment_sha256"])
    template_id = cast(str | None, task.get("template_id"))
    template_sha256 = cast(str | None, task.get("template_sha256"))
    return (
        "REVIEW_REQUIRED",
        {
            "candidate_signature_sha256": signature,
            "created": created,
            "template_id": template_id,
            "template_sha256": template_sha256,
            "treatment_id": treatment_id,
            "treatment_sha256": treatment_sha256,
            "status": str(treatment["status"]),
            "lineage": {
                "template_id": template_id,
                "template_sha256": template_sha256,
                "treatment_id": treatment_id,
                "treatment_sha256": treatment_sha256,
            },
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        },
    )


async def _synchronize_treatment_review_task(
    candidate_task: dict[str, object],
    *,
    actor_id: str,
    result: dict[str, object],
) -> None:
    peers = await factory_crud.list_tasks(str(candidate_task["plan_id"]))
    review_task = next(
        (
            peer
            for peer in peers
            if str(peer["product_id"]) == str(candidate_task["product_id"])
            and str(peer["task_type"]) == "TREATMENT_REVIEW"
            and str(peer["status"]) not in {"SATISFIED", "SUPERSEDED"}
        ),
        None,
    )
    if review_task is None:
        return
    await factory_crud.update_task(
        str(review_task["task_id"]),
        status="REVIEW_REQUIRED",
        blocker_code="TREATMENT_REVIEW_REQUIRED",
        next_action="REVIEW_TREATMENT",
        treatment_id=result["treatment_id"],
        treatment_sha256=result["treatment_sha256"],
        result_json=factory_crud.encode({"lineage": result["lineage"]}),
    )
    await factory_crud.append_event(
        plan_id=str(candidate_task["plan_id"]),
        task_id=str(review_task["task_id"]),
        event_identity_sha256=canonical_sha256(
            {
                "task": review_task["task_id"],
                "action": "TREATMENT_REVIEW_REQUESTED",
                "treatment_sha256": result["treatment_sha256"],
            }
        ),
        actor_id=actor_id,
        action="TREATMENT_REVIEW_REQUESTED",
        source_state=str(review_task["status"]),
        target_state="REVIEW_REQUIRED",
        evidence={"lineage": result["lineage"]},
    )


async def _process_task(
    task: dict[str, object],
    *,
    actor_id: str,
) -> None:
    claimed = await factory_crud.claim_ready_task(str(task["task_id"]))
    if claimed is None:
        return
    source_status = "READY"
    try:
        task_type = str(claimed["task_type"])
        if task_type == "COPY_COMPOSITION":
            target_status, result = await _prepare_copy_task(claimed)
        elif task_type == "TREATMENT_CANDIDATE":
            target_status, result = await _prepare_treatment_task(
                claimed,
                actor_id=actor_id,
            )
        else:
            raise ProductTreatmentFactoryError(
                "FACTORY_TASK_NOT_MATERIALIZABLE",
                details={"task_type": task_type},
            )
        update_fields: dict[str, object] = {
            "status": target_status,
            "blocker_code": (
                "COPY_REVIEW_REQUIRED"
                if task_type == "COPY_COMPOSITION"
                else "TREATMENT_REVIEW_REQUIRED"
            ),
            "next_action": (
                "REVIEW_COPY_SET"
                if task_type == "COPY_COMPOSITION"
                else "REVIEW_TREATMENT"
            ),
            "result_json": factory_crud.encode(result),
        }
        if task_type == "TREATMENT_CANDIDATE":
            update_fields["treatment_id"] = result["treatment_id"]
            update_fields["treatment_sha256"] = result["treatment_sha256"]
        await factory_crud.update_task(str(claimed["task_id"]), **update_fields)
        if task_type == "TREATMENT_CANDIDATE":
            await _synchronize_treatment_review_task(
                claimed,
                actor_id=actor_id,
                result=result,
            )
        await factory_crud.append_event(
            plan_id=str(claimed["plan_id"]),
            task_id=str(claimed["task_id"]),
            event_identity_sha256=canonical_sha256(
                {
                    "task": claimed["task_id"],
                    "attempt": claimed["attempt_count"],
                    "target": target_status,
                }
            ),
            actor_id=actor_id,
            action="TASK_MATERIALIZED",
            source_state=source_status,
            target_state=target_status,
            evidence=result,
        )
    except Exception as error:
        code = _error_code(error)
        await factory_crud.update_task(
            str(claimed["task_id"]),
            status="FAILED",
            blocker_code=code,
            next_action="REVIEW_FAILED_FACTORY_TASK",
            error_code=code,
            result_json=factory_crud.encode(
                {
                    "error_code": code,
                    "provider_calls": 0,
                    "media_generation_calls": 0,
                    "credit_spend": 0,
                }
            ),
        )
        await factory_crud.append_event(
            plan_id=str(claimed["plan_id"]),
            task_id=str(claimed["task_id"]),
            event_identity_sha256=canonical_sha256(
                {
                    "task": claimed["task_id"],
                    "attempt": claimed["attempt_count"],
                    "target": "FAILED",
                    "error": code,
                }
            ),
            actor_id=actor_id,
            action="TASK_FAILED",
            source_state=source_status,
            target_state="FAILED",
            evidence={
                "error_code": code,
                "provider_calls": 0,
                "media_generation_calls": 0,
                "credit_spend": 0,
            },
        )


async def prepare_plan(
    plan_id: str,
    request: PrepareFactoryPlanRequest,
) -> FactoryPlanProjection:
    plan = await factory_crud.get_plan(plan_id)
    if plan is None:
        raise ProductTreatmentFactoryError("FACTORY_PLAN_NOT_FOUND", status_code=404)
    source_state = str(plan["status"])
    if source_state == "PAUSED":
        raise ProductTreatmentFactoryError("FACTORY_PLAN_PAUSED", status_code=409)
    if source_state in {"FAILED"}:
        raise ProductTreatmentFactoryError(
            "FACTORY_PLAN_NOT_PREPARABLE",
            status_code=409,
            details={"status": source_state},
        )
    await factory_crud.update_plan(
        plan_id,
        status="PREPARING",
        preparation_started_at=factory_crud.utc_now(),
    )
    await factory_crud.append_event(
        plan_id=plan_id,
        task_id=None,
        event_identity_sha256=canonical_sha256(
            {
                "plan": plan_id,
                "action": "PLAN_PREPARING",
                "source": source_state,
            }
        ),
        actor_id=request.actor_id,
        action="PLAN_PREPARING",
        source_state=source_state,
        target_state="PREPARING",
        evidence={
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        },
    )
    tasks = await factory_crud.list_tasks(plan_id)
    eligible_types: set[str] = set()
    if request.materialize_copy_composition:
        eligible_types.add("COPY_COMPOSITION")
    if request.materialize_treatment_candidates:
        eligible_types.add("TREATMENT_CANDIDATE")
    processed = 0
    for task in tasks:
        if (
            processed >= request.max_tasks
            or str(task["status"]) != "READY"
            or str(task["task_type"]) not in eligible_types
        ):
            continue
        await _process_task(task, actor_id=request.actor_id)
        processed += 1

    refreshed = await factory_crud.list_tasks(plan_id)
    summary = _readiness_summary(refreshed)
    if refreshed and all(
        str(task["status"]) == "SATISFIED" for task in refreshed
    ):
        final_status = "COMPLETED"
    elif any(str(task["status"]) in {"READY", "RUNNING"} for task in refreshed):
        final_status = "SCANNED"
    elif any(str(task["status"]) in {"PENDING"} for task in refreshed):
        final_status = "COMPLETED_WITH_BLOCKERS"
    elif all(str(task["status"]) in TERMINAL_TASK_STATES for task in refreshed):
        final_status = "COMPLETED_WITH_BLOCKERS"
    else:
        final_status = "FAILED"
    failure_count = sum(1 for task in refreshed if str(task["status"]) == "FAILED")
    await factory_crud.update_plan(
        plan_id,
        status=final_status,
        readiness_summary_json=factory_crud.encode(summary),
        failure_count=failure_count,
        completed_at=(
            factory_crud.utc_now()
            if final_status in {"COMPLETED", "COMPLETED_WITH_BLOCKERS", "FAILED"}
            else None
        ),
    )
    await factory_crud.append_event(
        plan_id=plan_id,
        task_id=None,
        event_identity_sha256=canonical_sha256(
            {
                "plan": plan_id,
                "action": "PLAN_PREPARATION_FINISHED",
                "processed": processed,
                "target": final_status,
                "summary": summary,
            }
        ),
        actor_id=request.actor_id,
        action="PLAN_PREPARATION_FINISHED",
        source_state="PREPARING",
        target_state=final_status,
        evidence={
            "processed_tasks": processed,
            "readiness_summary": summary,
            "failure_count": failure_count,
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        },
    )
    return await get_plan(plan_id)


async def pause_plan(
    plan_id: str,
    request: FactoryPlanControlRequest,
) -> FactoryPlanProjection:
    plan = await factory_crud.get_plan(plan_id)
    if plan is None:
        raise ProductTreatmentFactoryError("FACTORY_PLAN_NOT_FOUND", status_code=404)
    source_state = str(plan["status"])
    if source_state in {"COMPLETED", "COMPLETED_WITH_BLOCKERS", "FAILED"}:
        raise ProductTreatmentFactoryError(
            "FACTORY_PLAN_TERMINAL",
            status_code=409,
            details={"status": source_state},
        )
    await factory_crud.update_plan(
        plan_id,
        status="PAUSED",
        pause_reason=request.reason,
    )
    await factory_crud.append_event(
        plan_id=plan_id,
        task_id=None,
        event_identity_sha256=canonical_sha256(
            {
                "plan": plan_id,
                "action": "PLAN_PAUSED",
                "source": source_state,
                "reason": request.reason,
            }
        ),
        actor_id=request.actor_id,
        action="PLAN_PAUSED",
        source_state=source_state,
        target_state="PAUSED",
        evidence={"reason": request.reason},
    )
    return await get_plan(plan_id)


async def resume_plan(
    plan_id: str,
    request: FactoryPlanControlRequest,
) -> FactoryPlanProjection:
    plan = await factory_crud.get_plan(plan_id)
    if plan is None:
        raise ProductTreatmentFactoryError("FACTORY_PLAN_NOT_FOUND", status_code=404)
    if str(plan["status"]) != "PAUSED":
        raise ProductTreatmentFactoryError(
            "FACTORY_PLAN_NOT_PAUSED",
            status_code=409,
        )
    await factory_crud.update_plan(
        plan_id,
        status="SCANNED",
        pause_reason=None,
    )
    await factory_crud.append_event(
        plan_id=plan_id,
        task_id=None,
        event_identity_sha256=canonical_sha256(
            {
                "plan": plan_id,
                "action": "PLAN_RESUMED",
                "reason": request.reason,
            }
        ),
        actor_id=request.actor_id,
        action="PLAN_RESUMED",
        source_state="PAUSED",
        target_state="SCANNED",
        evidence={"reason": request.reason},
    )
    return await get_plan(plan_id)


async def get_plan(plan_id: str) -> FactoryPlanProjection:
    row = await factory_crud.get_plan(plan_id)
    if row is None:
        raise ProductTreatmentFactoryError("FACTORY_PLAN_NOT_FOUND", status_code=404)
    return await _plan_projection(row)


async def list_plans(
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[FactoryPlanProjection]:
    rows = await factory_crud.list_plans(status=status, limit=limit)
    return [await _plan_projection(row) for row in rows]
