"""Durable, deterministic Product-to-Treatment Factory orchestration.

The factory coordinates existing authorities. It never approves copy or treatments,
never invokes P6/compiler/scheduler execution, and never calls a provider unless
the caller explicitly enables the review-only AI copy-assist batch path. Media
generation and credit spend remain permanently disabled.
"""

from __future__ import annotations

import hashlib
import math
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from agent.authority import product_readiness_applicability_registry as applicability_registry
from agent.db import crud
from agent.db import product_treatment_factory_crud as factory_crud
from agent.models.copy_set import AICopyAssistBatchRequest
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
    ai_copy_assist_service,
    copy_composer_service,
    copy_register_v2_service,
    copy_rotation_service,
    creative_recipe_service,
    creative_scene_prompt_service,
    creative_treatment_service,
    product_readiness_applicability_service,
)
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled
from agent.authority.copy_lane_matrix import get_lane_descriptor
from agent.services.product_treatment_template_service import (
    ProductTreatmentTemplateError,
    resolve_treatment_template,
)


FACTORY_VERSION = "product-treatment-factory-v2"
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



def _lane_for_logical_mode(logical_mode: str) -> str:
    mode = str(logical_mode or "").strip().upper()
    if mode in {"HYBRID", "F2V", "PGC", "UGC", "CINEMATIC"}:
        return "PRODUCTION_STUDIO_P6"
    if mode == "T2V":
        return "T2V"
    if mode == "I2V":
        return "I2V"
    return "PRODUCTION_STUDIO_P6"


async def _list_eligible_v2_bindings(product_id: str, logical_mode: str) -> list[dict]:
    """Return active V2 bindings usable as treatment copy authority."""
    lane = _lane_for_logical_mode(logical_mode)
    try:
        descriptor = get_lane_descriptor(lane)
        lane_id = descriptor.lane_id
    except ValueError:
        lane_id = lane
    try:
        binding = await copy_register_v2_service.get_binding(product_id, lane_id)
    except copy_register_v2_service.CopyRegisterV2Error:
        return []
    return [
        {
            "binding_id": binding.binding_id,
            "lane": binding.lane,
            "blueprint_id": binding.blueprint_id,
            "revision": binding.revision,
            "formula_id": binding.formula_id,
            "approval_snapshot_id": binding.approval_snapshot_id,
        }
    ]


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


def _selection_recipe_grid(selection: Mapping[str, object]) -> list[creative_recipe_service.CreativeRecipe]:
    """Build the approved selection's coherent avatar x scene rotation grid."""

    def values(list_key: str, primary_key: str) -> list[str]:
        raw = selection.get(list_key)
        source = raw if isinstance(raw, list) else []
        if not source:
            source = [selection.get(primary_key)]
        return list(
            dict.fromkeys(
                str(value).strip()
                for value in source
                if str(value or "").strip()
            )
        )

    avatars = values("selected_avatar_codes", "selected_avatar_code")
    scene_ids = values(
        "selected_scene_template_ids",
        "selected_scene_template_id",
    )
    if not avatars or not scene_ids:
        return []
    scene_index = {
        str(template.get("template_id")): template
        for template in creative_scene_prompt_service.library_templates()
        if template.get("template_id")
    }
    scenes = [scene_index[scene_id] for scene_id in scene_ids if scene_id in scene_index]
    if not scenes:
        return []
    return creative_recipe_service.build_recipes(
        avatars,
        scenes,
        creative_recipe_service.load_bridge(),
        creative_recipe_service.load_camera_mapping(),
    )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _first_string(value: object) -> str | None:
    items = sorted(_string_list(value))
    return items[0] if items else None


_NON_MATERIAL_EXECUTION_FIELDS = frozenset(
    {
        "workspace_generation_package_id",
        "item_id",
        "attempt_id",
        "request_id",
        "trace_id",
        "retry_token",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    }
)


def normalize_material_execution_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): normalize_material_execution_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _NON_MATERIAL_EXECUTION_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_material_execution_payload(item) for item in value]
    return value

def material_execution_fingerprint(payload: Mapping[str, object]) -> str:
    return canonical_sha256(normalize_material_execution_payload(payload))



def canonical_same_dialogue_reuse_cap() -> int:
    ordinal_schema = CreateTreatmentRequest.model_json_schema()["properties"][
        "variation_ordinal"
    ]
    candidates: list[int] = []
    if isinstance(ordinal_schema, Mapping):
        maximum = ordinal_schema.get("maximum")
        if isinstance(maximum, int):
            candidates.append(maximum)
        for branch in ordinal_schema.get("anyOf", []):
            if isinstance(branch, Mapping):
                branch_maximum = branch.get("maximum")
                if isinstance(branch_maximum, int):
                    candidates.append(branch_maximum)
    if not candidates or min(candidates) < 1:
        raise ProductTreatmentFactoryError("VARIATION_GROUP_REUSE_CAP_UNAVAILABLE")
    return min(candidates)

def required_dialogue_count(
    target_video_count: int,
    reuse_cap: int | None = None,
) -> int:
    if target_video_count < 0:
        raise ProductTreatmentFactoryError("INVALID_TARGET_VIDEO_COUNT")
    if target_video_count == 0:
        return 0
    cap = reuse_cap if reuse_cap is not None else canonical_same_dialogue_reuse_cap()
    if cap < 1:
        raise ProductTreatmentFactoryError("VARIATION_GROUP_REUSE_CAP_UNAVAILABLE")
    return math.ceil(target_video_count / cap)

def _allocated_product_targets(
    target_video_count: int,
    contexts: list[FactoryProductContext],
) -> dict[str, int]:
    if not contexts:
        return {}
    ordered = sorted(contexts, key=lambda context: context.product_id)
    quotient, remainder = divmod(target_video_count, len(ordered))
    return {
        context.product_id: quotient + (index < remainder)
        for index, context in enumerate(ordered)
    }

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


async def _plan_projection(
    row: dict[str, object],
    *,
    include_tasks: bool = True,
) -> FactoryPlanProjection:
    task_rows = (
        await factory_crud.list_tasks(str(row["plan_id"])) if include_tasks else []
    )
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
        contexts = [
            FactoryProductContext(
                product_id=product_id,
                **request.defaults.model_dump(),
            )
            for product_id in product_ids
        ]
    else:
        contexts = sorted(request.products, key=lambda item: item.product_id)
    allocations = _allocated_product_targets(request.target_video_count, contexts)
    return [
        context.model_copy(
            update={"target_video_count": allocations[context.product_id]}
        )
        for context in contexts
    ]


async def _eligible_approved_copy_sets(
    product_id: str,
) -> list[dict[str, object]]:
    rows = await copy_rotation_service.list_eligible_copy_sets(product_id)
    return sorted(
        [_mapping(row) for row in rows],
        key=lambda row: str(row.get("copy_set_id") or ""),
    )

def _approved_copy_set_ids(scan: ProductScan) -> list[str]:
    preview = scan.copy_preview
    if "eligible_approved_copy_set_ids" in preview:
        return _string_list(preview.get("eligible_approved_copy_set_ids"))
    resolved = scan.resolved
    return sorted(_string_list(resolved.copy.approved_copy_set_ids) if resolved else [])


def _eligible_binding_ids(scan: ProductScan) -> list[str]:
    """PRODUCTION_VALID Copy Register V2 bindings eligible for factory authority."""
    return sorted(_string_list(scan.copy_preview.get("eligible_approved_binding_ids")))


def _copy_authority_ready(scan: ProductScan, required_dialogues: int) -> bool:
    """Copy authority is ready via V2 binding or enough legacy approved copy sets.

    One PRODUCTION_VALID V2 binding authorizes the full dialogue/recipe grid for the
    product. Legacy path still requires one approved copy_set per required dialogue.
    """
    if required_dialogues <= 0:
        return True
    if _eligible_binding_ids(scan):
        return True
    return len(_approved_copy_set_ids(scan)) >= required_dialogues


def _canonical_required_asset_roles(scan: ProductScan) -> tuple[str, ...]:
    if scan.resolved is None:
        return ()
    logical_mode = str(scan.context.logical_mode or "").strip().upper()
    profile = applicability_registry.resolve_applicability_profile(
        scan.resolved.taxonomy.matched_scene_strategy_id
    )
    return tuple(
        str(role)
        for role in profile.required_asset_roles_by_mode.get(logical_mode, [])
    )


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
    try:
        template = resolve_treatment_template(
            context=readiness_request,
            profile=readiness.applicability_profile,
            requirements=readiness.evidence_requirements,
        )
    except Exception as error:
        return ProductScan(
            context=context,
            resolved=resolved,
            readiness=readiness,
            template=None,
            copy_preview={},
            treatments=[],
            error_code=(
                "UNSUPPORTED_PRODUCT_TAXONOMY"
                if readiness.primary_status == "UNSUPPORTED_PRODUCT_TAXONOMY"
                else _error_code(error)
            ),
        )
    try:
        reuse_cap = canonical_same_dialogue_reuse_cap()
        required_dialogues = required_dialogue_count(
            context.target_video_count,
            reuse_cap,
        )
        approved_bindings = await _list_eligible_v2_bindings(
            context.product_id,
            context.logical_mode,
        )
        approved_copy_sets: list[dict[str, object]] = []
        if approved_bindings:
            composition_shortfall = 0
            raw_preview = {
                "copy_authority": "COPY_REGISTER_V2",
                "produced": 0,
                "provider_calls_enabled": False,
            }
        else:
            if legacy_copy_maintenance_enabled():
                approved_copy_sets = await _eligible_approved_copy_sets(
                    context.product_id
                )
            composition_shortfall = max(
                0,
                required_dialogues - len(approved_copy_sets),
            )
            raw_preview = await copy_composer_service.compose_and_persist(
                context.product_id,
                composition_shortfall,
                dry_run=True,
            )
        raw_treatments = await creative_treatment_service.list_treatments(
            product_id=context.product_id,
            status=None,
            variation_group_id=None,
            limit=1000,
        )
        copy_preview = _mapping(raw_preview)
        copy_preview.update(
            {
                "variation_group_reuse_cap": reuse_cap,
                "target_video_count": context.target_video_count,
                "required_dialogues": required_dialogues,
                "eligible_approved_copy_set_ids": [
                    str(row["copy_set_id"])
                    for row in approved_copy_sets
                    if row.get("copy_set_id")
                ],
                "eligible_approved_binding_ids": [
                    str(row["binding_id"])
                    for row in approved_bindings
                    if row.get("binding_id")
                ],
                "eligible_approved_copy_count": (
                    len(approved_bindings) if approved_bindings else len(approved_copy_sets)
                ),
                "composition_shortfall": composition_shortfall,
                "copy_authority": (
                    "COPY_REGISTER_V2" if approved_bindings else "LEGACY_COPY_SET"
                ),
                "provider_calls": 0,
                "media_generation_calls": 0,
                "credit_spend": 0,
            }
        )
        return ProductScan(
            context=context,
            resolved=resolved,
            readiness=readiness,
            template=template,
            copy_preview=copy_preview,
            treatments=[_mapping(item) for item in raw_treatments],
            error_code=None,
        )
    except Exception as error:
        return ProductScan(
            context=context,
            resolved=resolved,
            readiness=readiness,
            template=template,
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
        "target_video_count": scan.context.target_video_count,
        "required_dialogues": required_dialogue_count(scan.context.target_video_count),
        "variation_group_reuse_cap": canonical_same_dialogue_reuse_cap(),
        "provider_calls_enabled": bool(scan.copy_preview.get("provider_calls_enabled")),
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
    binding_ids = _eligible_binding_ids(scan)
    # V2 binding is the production copy authority after Copy Register cutover.
    # Do not require the legacy copy_set readiness layer when a binding is present.
    required = (
        (
            "product_truth",
            "creative_selection",
            "treatment_template",
        )
        if binding_ids
        else (
            "product_truth",
            "copy_set",
            "creative_selection",
            "treatment_template",
        )
    )
    logical_mode = str(scan.context.logical_mode or "").strip().upper()
    canonical_required_roles = _canonical_required_asset_roles(scan)
    t2v_zero_role_mode = logical_mode == "T2V" and not canonical_required_roles
    visual_layer = layers.get("visual_assets")
    visual_ready = str(getattr(visual_layer, "state", "")) == "READY" or (
        t2v_zero_role_mode
        and str(getattr(visual_layer, "state", "")) == "NOT_APPLICABLE"
    )
    required_dialogues = required_dialogue_count(scan.context.target_video_count)
    copy_ready = _copy_authority_ready(scan, required_dialogues)
    return (
        all(str(getattr(layers.get(name), "state", "")) == "READY" for name in required)
        and visual_ready
        and bool(resolved.product_truth.snapshot_id)
        and copy_ready
        and bool(resolved.selection.selection_id)
        and not resolved.assets.missing_roles
        and (
            required_dialogues == 0
            or t2v_zero_role_mode
            or bool(resolved.assets.required_roles)
        )
    )


def _task_decision(
    scan: ProductScan,
    task_type: FactoryTaskType,
) -> tuple[FactoryTaskStatus, str | None, str | None]:
    if (
        scan.readiness is not None
        and scan.readiness.primary_status == "UNSUPPORTED_PRODUCT_TAXONOMY"
    ):
        return (
            "REVIEW_REQUIRED",
            "UNSUPPORTED_PRODUCT_TAXONOMY",
            (
                scan.readiness.next_actions[0]
                if scan.readiness.next_actions
                else "VERIFY_SUPPORTED_PRODUCT_TAXONOMY"
            ),
        )
    if scan.error_code or scan.readiness is None or scan.resolved is None:
        return "REVIEW_REQUIRED", scan.error_code or "FACTORY_SCAN_FAILED", "REVIEW_PRODUCT"

    readiness = scan.readiness
    resolved = scan.resolved
    required_dialogues = required_dialogue_count(scan.context.target_video_count)
    copy_ready = _copy_authority_ready(scan, required_dialogues)
    approved_treatment_count = len(resolved.treatment.approved_treatment_ids)
    treatment_ready = approved_treatment_count >= required_dialogues
    if task_type == "PRODUCT_TRUTH_REVIEW":
        return _layer_decision(readiness, "product_truth")
    if task_type == "EVIDENCE_REVIEW":
        return _evidence_decision(readiness)
    if task_type == "COPY_GROUNDING":
        return _layer_decision(readiness, "copy_grounding")
    if task_type == "COPY_COMPOSITION":
        if copy_ready:
            return "SATISFIED", None, None
        if (
            int(scan.copy_preview.get("produced") or 0) > 0
            or bool(scan.copy_preview.get("provider_calls_enabled"))
        ):
            return "READY", None, "MATERIALIZE_REVIEW_REQUIRED_COPY"
        return (
            "REVIEW_REQUIRED",
            "COPY_COMPONENT_SUPPLY_REQUIRED",
            "REVIEW_COPY_COMPONENT_SUPPLY",
        )
    if task_type == "COPY_REVIEW":
        if copy_ready:
            return "SATISFIED", None, None
        if (
            int(scan.copy_preview.get("produced") or 0) > 0
            or bool(scan.copy_preview.get("provider_calls_enabled"))
        ):
            return (
                "REVIEW_REQUIRED",
                "COPY_REVIEW_REQUIRED",
                "REVIEW_COPY_SET",
            )
        return "REVIEW_REQUIRED", "APPROVED_COPY_SET_REQUIRED", "REVIEW_COPY_SET"
    if task_type == "CREATIVE_SELECTION":
        return _layer_decision(readiness, "creative_selection")
    if task_type == "ASSET_SUPPLY":
        return _layer_decision(readiness, "visual_assets")
    if task_type == "TREATMENT_CANDIDATE":
        if treatment_ready:
            return "SATISFIED", None, None
        if _candidate_ready(scan):
            return "READY", None, "MATERIALIZE_REVIEW_REQUIRED_TREATMENT"
        if not copy_ready:
            return (
                "PENDING",
                "APPROVED_COPY_CAPACITY_SHORTFALL",
                "APPROVE_REQUIRED_COPY_SETS",
            )
        return (
            "PENDING",
            "TREATMENT_PREREQUISITES_REQUIRED",
            "RESOLVE_TREATMENT_PREREQUISITES",
        )
    if task_type == "TREATMENT_REVIEW":
        if treatment_ready:
            return "SATISFIED", None, None
        if any(
            str(item.get("status")) in {"DRAFT", "IN_REVIEW", "REVIEW_REQUIRED"}
            for item in scan.treatments
        ):
            return "REVIEW_REQUIRED", "TREATMENT_REVIEW_REQUIRED", "REVIEW_TREATMENT"
        if not copy_ready:
            return (
                "PENDING",
                "APPROVED_COPY_CAPACITY_SHORTFALL",
                "APPROVE_REQUIRED_COPY_SETS",
            )
        return "PENDING", "TREATMENT_CANDIDATE_REQUIRED", "CREATE_TREATMENT_CANDIDATE"
    if task_type == "P6_CAPACITY":
        if resolved.treatment.p6_ready and treatment_ready:
            return "SATISFIED", None, None
        if not resolved.treatment.p6_ready:
            return "REVIEW_REQUIRED", "P6_CAPACITY_NOT_READY", "RESOLVE_P6_CAPACITY"
        return "REVIEW_REQUIRED", "P6_CAPACITY_SHORTFALL", "RESOLVE_TREATMENT_CAPACITY"
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
    target_by_product = {
        scan.context.product_id: scan.context.target_video_count
        for scan in scans
    }
    required_by_product = {
        scan.context.product_id: required_dialogue_count(
            scan.context.target_video_count
        )
        for scan in scans
    }
    approved_copy_by_product = {
        scan.context.product_id: _approved_copy_set_ids(scan)
        for scan in scans
    }
    approved_binding_by_product = {
        scan.context.product_id: _eligible_binding_ids(scan)
        for scan in scans
    }
    approved_treatment_by_product = {
        scan.context.product_id: sorted(
            scan.resolved.treatment.approved_treatment_ids
            if scan.resolved is not None
            else []
        )
        for scan in scans
    }
    approved_copy_ids = sorted(
        {
            copy_set_id
            for copy_set_ids in approved_copy_by_product.values()
            for copy_set_id in copy_set_ids
        }
    )
    approved_binding_ids = sorted(
        {
            binding_id
            for binding_ids in approved_binding_by_product.values()
            for binding_id in binding_ids
        }
    )
    approved_master_treatments = sorted(
        {
            treatment_id
            for treatment_ids in approved_treatment_by_product.values()
            for treatment_id in treatment_ids
        }
    )
    p6_ready_products = sorted(
        scan.context.product_id
        for scan in scans
        if scan.resolved is not None and scan.resolved.treatment.p6_ready
    )
    target_video_count = sum(target_by_product.values())
    required_dialogues = sum(required_by_product.values())
    copy_shortfall = sum(
        max(
            0,
            0
            if approved_binding_by_product.get(product_id)
            else (
                required_by_product[product_id]
                - len(approved_copy_by_product[product_id])
            ),
        )
        for product_id in required_by_product
    )
    treatment_shortfall = sum(
        max(
            0,
            required_by_product[product_id]
            - len(approved_treatment_by_product[product_id]),
        )
        for product_id in required_by_product
    )
    return {
        "product_count": len(scans),
        "task_count": len(tasks),
        "target_video_count": target_video_count,
        "target_video_count_by_product": target_by_product,
        "variation_group_reuse_cap": canonical_same_dialogue_reuse_cap(),
        "required_dialogues": required_dialogues,
        "required_dialogues_by_product": required_by_product,
        "approved_copy_set_count": len(approved_copy_ids),
        "approved_copy_set_ids": approved_copy_ids,
        "approved_binding_count": len(approved_binding_ids),
        "approved_binding_ids": approved_binding_ids,
        "required_copy_set_count": required_dialogues,
        "copy_shortfall": copy_shortfall,
        "p6_ready_product_count": len(p6_ready_products),
        "p6_ready_product_ids": p6_ready_products,
        "approved_master_treatment_count": len(approved_master_treatments),
        "approved_master_treatment_ids": approved_master_treatments,
        "required_treatment_count": required_dialogues,
        "treatment_shortfall": treatment_shortfall,
        "extend_segments_counted": 0,
    }


async def create_plan(request: CreateFactoryPlanRequest) -> FactoryPlanProjection:
    contexts = await _resolve_contexts(request)
    scans = [await _scan_product(context) for context in contexts]
    for scan in scans:
        scan.copy_preview["provider_calls_enabled"] = request.provider_calls_enabled
    request_snapshot: dict[str, object] = {
        "factory_version": FACTORY_VERSION,
        "products": [context.model_dump(mode="json") for context in contexts],
        "target_video_count": request.target_video_count,
        "scan_all_active": request.scan_all_active,
        "provider_calls_enabled": request.provider_calls_enabled,
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
                "target_video_count": scan.context.target_video_count,
                "required_dialogues": required_dialogue_count(scan.context.target_video_count),
                "approved_copy_set_ids": _approved_copy_set_ids(scan),
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
                    "target_video_count": scan.context.target_video_count,
                    "required_dialogues": required_dialogue_count(scan.context.target_video_count),
                    "approved_copy_set_ids": _approved_copy_set_ids(scan),
                    "variation_group_reuse_cap": canonical_same_dialogue_reuse_cap(),
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
            "avatar_code": value.get("avatar_code"),
            "scene_template_id": value.get("scene_template_id"),
        }
    )


def _treatment_request_from_snapshot(
    task: dict[str, object],
    *,
    created_by: str,
    copy_set_id: str | None = None,
    copy_execution_binding_id_v2: str | None = None,
    recipe: creative_recipe_service.CreativeRecipe | None = None,
) -> CreateTreatmentRequest:
    snapshot = _mapping(task.get("snapshot"))
    resolved = _mapping(snapshot.get("resolved_authority"))
    context = _mapping(snapshot.get("context"))
    template = _mapping(snapshot.get("treatment_template"))
    product_truth = _mapping(resolved.get("product_truth"))
    copy_authority = _mapping(resolved.get("copy"))
    selection = _mapping(resolved.get("selection"))
    assets = _mapping(resolved.get("assets"))
    preview = _mapping(snapshot.get("copy_preview"))
    product_truth_snapshot_id = str(product_truth.get("snapshot_id") or "")
    binding_id = (
        str(copy_execution_binding_id_v2 or "").strip()
        or _first_string(preview.get("eligible_approved_binding_ids"))
        or _first_string(copy_authority.get("approved_binding_ids"))
    )
    legacy_copy_set_id = (
        None
        if binding_id
        else (
            str(copy_set_id or "").strip()
            or _first_string(copy_authority.get("approved_copy_set_ids"))
            or None
        )
    )
    creative_selection_id = str(selection.get("selection_id") or "")
    asset_bindings: list[AssetBindingRequest] = []
    eligible_by_role = _mapping(assets.get("eligible_asset_ids_by_role"))
    for role in _string_list(assets.get("required_roles")):
        asset_id = _first_string(eligible_by_role.get(role))
        if asset_id:
            asset_bindings.append(AssetBindingRequest(role=role, asset_id=asset_id))
    compatibility = _mapping(template.get("compatibility_profile"))
    required_asset_roles = _string_list(
        compatibility.get("required_asset_roles")
    )
    if (
        not product_truth_snapshot_id
        or not (binding_id or legacy_copy_set_id)
        or not creative_selection_id
        or (required_asset_roles and not asset_bindings)
    ):
        raise ProductTreatmentFactoryError(
            "TREATMENT_PREREQUISITES_REQUIRED",
            details={"task_id": str(task["task_id"])},
        )
    format_name = str(template.get("format") or "")
    return CreateTreatmentRequest(
        product_id=str(task["product_id"]),
        product_truth_snapshot_id=product_truth_snapshot_id,
        copy_set_id=legacy_copy_set_id,
        copy_execution_binding_id_v2=binding_id or None,
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
        avatar_code=(
            recipe.avatar_code
            if recipe is not None and format_name != "PGC"
            else None
        ),
        scene_template_id=(recipe.scene_template_id if recipe is not None else None),
        choreography_schema_version=str(template.get("choreography_schema_version") or "") or None,
        choreography_id=str(template.get("choreography_id") or "") or None,
        choreography_sha256=str(template.get("choreography_sha256") or "") or None,
        created_by=created_by,
    )


async def _prepare_copy_task(
    task: dict[str, object],
) -> tuple[str, dict[str, object]]:
    snapshot = _mapping(task.get("snapshot"))
    preview = _mapping(snapshot.get("copy_preview"))
    required_dialogues = int(
        preview.get("required_dialogues")
        or snapshot.get("required_dialogues")
        or 1
    )
    binding_count = len(_string_list(preview.get("eligible_approved_binding_ids")))
    approved_copy_count = len(
        _string_list(preview.get("eligible_approved_copy_set_ids"))
    )
    if binding_count > 0:
        return "SATISFIED", {
            "created": 0,
            "created_count": 0,
            "requested_count": 0,
            "remaining_shortfall": 0,
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
            "copy_authority": "COPY_REGISTER_V2",
        }
    shortfall = max(0, required_dialogues - approved_copy_count)
    provider_enabled = bool(
        snapshot.get("provider_calls_enabled")
        or preview.get("provider_calls_enabled")
    )
    if shortfall == 0:
        return "SATISFIED", {
            "created": 0,
            "created_count": 0,
            "requested_count": 0,
            "remaining_shortfall": 0,
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        }
    result = await copy_composer_service.compose_and_persist(
        str(task["product_id"]),
        shortfall,
        dry_run=False,
    )
    normalized = _mapping(result)
    composer_created_count = int(
        normalized.get("created") or normalized.get("created_count") or 0
    )
    created_count = composer_created_count
    remaining = max(0, shortfall - created_count)
    ai_batches: list[dict[str, object]] = []
    provider_calls = 0
    while provider_enabled and remaining >= 3:
        batch_count = min(10, remaining)
        ai_result = _mapping(
            await ai_copy_assist_service.generate_ai_copy_candidates_batch(
                AICopyAssistBatchRequest(
                    product_id=str(task["product_id"]),
                    requested_count=batch_count,
                    dry_run=False,
                )
            )
        )
        ai_batches.append(ai_result)
        provider_calls += 1
        ai_created_count = int(
            ai_result.get("created_count") or ai_result.get("created") or 0
        )
        created_count += ai_created_count
        remaining = max(0, shortfall - created_count)
        if ai_created_count <= 0:
            break
    if composer_created_count < 1 and not provider_enabled:
        raise ProductTreatmentFactoryError(
            "COPY_COMPOSITION_NOT_MATERIALIZED",
            details={"task_id": str(task["task_id"])},
        )
    normalized.update(
        {
            "created_count": created_count,
            "composer_created_count": composer_created_count,
            "requested_count": shortfall,
            "remaining_shortfall": remaining,
            "ai_batches": ai_batches,
            "provider_calls": provider_calls,
            "media_generation_calls": 0,
            "credit_spend": 0,
            "review_required": True,
        }
    )
    if remaining:
        normalized["blocker_code"] = (
            "AI_BATCH_MINIMUM_SHORTFALL" if provider_enabled else "COPY_CAPACITY_SHORTFALL"
        )
    return "REVIEW_REQUIRED", normalized


async def _prepare_treatment_task(
    task: dict[str, object],
    *,
    actor_id: str,
) -> tuple[str, dict[str, object]]:
    snapshot = _mapping(task.get("snapshot"))
    preview = _mapping(snapshot.get("copy_preview"))
    required_dialogues = int(
        preview.get("required_dialogues")
        or snapshot.get("required_dialogues")
        or 1
    )
    resolved = _mapping(snapshot.get("resolved_authority"))
    copy_authority = _mapping(resolved.get("copy"))
    binding_ids = sorted(
        _string_list(preview.get("eligible_approved_binding_ids"))
        or _string_list(copy_authority.get("approved_binding_ids"))
    )
    copy_set_ids = sorted(
        _string_list(preview.get("eligible_approved_copy_set_ids"))
        or _string_list(copy_authority.get("approved_copy_set_ids"))
    )
    if required_dialogues <= 0:
        return "SATISFIED", {
            "created": False,
            "created_count": 0,
            "reused_count": 0,
            "treatment_ids": [],
            "treatment_sha256s": [],
            "provider_calls": 0,
            "media_generation_calls": 0,
            "credit_spend": 0,
        }
    if binding_ids:
        # Repeat the active V2 binding across recipe slots.
        primary = binding_ids[0]
        authority_slots: list[tuple[str, str | None]] = [
            ("v2", primary) for _ in range(required_dialogues)
        ]
    else:
        if len(copy_set_ids) < required_dialogues:
            raise ProductTreatmentFactoryError(
                "APPROVED_COPY_CAPACITY_SHORTFALL",
                details={
                    "task_id": str(task["task_id"]),
                    "required_dialogues": required_dialogues,
                    "approved_copy_set_count": len(copy_set_ids),
                },
            )
        authority_slots = [
            ("legacy", item) for item in copy_set_ids[:required_dialogues]
        ]
    selection = _mapping(resolved.get("selection"))
    recipes = _selection_recipe_grid(selection)
    product_id = str(task["product_id"])
    existing = await creative_treatment_service.list_treatments(
        product_id=product_id,
        status=None,
        variation_group_id=None,
        limit=1000,
    )
    template_id = cast(str | None, task.get("template_id"))
    template_sha256 = cast(str | None, task.get("template_sha256"))
    candidates: list[dict[str, object]] = []
    for index, (authority_mode, authority_id) in enumerate(authority_slots):
        recipe = recipes[index % len(recipes)] if recipes else None
        request = _treatment_request_from_snapshot(
            task,
            created_by=actor_id,
            copy_set_id=None if authority_mode == "v2" else authority_id,
            copy_execution_binding_id_v2=(
                authority_id if authority_mode == "v2" else None
            ),
            recipe=recipe,
        )
        request_projection = request.model_dump(mode="json")
        signature = _candidate_signature(request_projection)
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
            existing.append(treatment)
        treatment_id = str(treatment["treatment_id"])
        treatment_sha256 = str(treatment["treatment_sha256"])
        candidates.append(
            {
                "candidate_signature_sha256": signature,
                "copy_set_id": None if authority_mode == "v2" else authority_id,
                "copy_execution_binding_id_v2": (
                    authority_id if authority_mode == "v2" else None
                ),
                "avatar_code": request.avatar_code,
                "scene_template_id": request.scene_template_id,
                "camera_preset_code": (
                    recipe.camera_preset_code if recipe is not None else None
                ),
                "created": created,
                "treatment_id": treatment_id,
                "treatment_sha256": treatment_sha256,
                "status": str(treatment["status"]),
                "lineage": {
                    "template_id": template_id,
                    "template_sha256": template_sha256,
                    "copy_set_id": None if authority_mode == "v2" else authority_id,
                    "copy_execution_binding_id_v2": (
                        authority_id if authority_mode == "v2" else None
                    ),
                    "treatment_id": treatment_id,
                    "treatment_sha256": treatment_sha256,
                },
            }
        )
    first = candidates[0]
    created_count = sum(1 for candidate in candidates if candidate["created"])
    first_lineage = {
        key: value
        for key, value in _mapping(first["lineage"]).items()
        if value not in (None, "")
    }
    return (
        "REVIEW_REQUIRED",
        {
            "candidate_signature_sha256": first["candidate_signature_sha256"],
            "created": created_count == 1 and bool(first["created"]),
            "created_count": created_count,
            "reused_count": len(candidates) - created_count,
            "candidates": candidates,
            "treatment_ids": [str(item["treatment_id"]) for item in candidates],
            "treatment_sha256s": [
                str(item["treatment_sha256"]) for item in candidates
            ],
            "template_id": template_id,
            "template_sha256": template_sha256,
            "treatment_id": first["treatment_id"],
            "treatment_sha256": first["treatment_sha256"],
            "status": first["status"],
            "lineage": first_lineage,
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
        result_json=factory_crud.encode(
            {
                "lineage": result["lineage"],
                "candidates": result.get("candidates", []),
            }
        ),
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
        evidence={
            "lineage": result["lineage"],
            "candidates": result.get("candidates", []),
        },
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
        default_blocker = (
            (
                "COPY_REVIEW_REQUIRED"
                if task_type == "COPY_COMPOSITION"
                else "TREATMENT_REVIEW_REQUIRED"
            )
            if target_status == "REVIEW_REQUIRED"
            else None
        )
        default_next_action = (
            (
                "REVIEW_COPY_SET"
                if task_type == "COPY_COMPOSITION"
                else "REVIEW_TREATMENT"
            )
            if target_status == "REVIEW_REQUIRED"
            else None
        )
        update_fields: dict[str, object] = {
            "status": target_status,
            "blocker_code": result.get("blocker_code") or default_blocker,
            "next_action": default_next_action,
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
    if request.provider_calls_enabled:
        for task in tasks:
            if str(task["task_type"]) != "COPY_COMPOSITION":
                continue
            snapshot = _mapping(task.get("snapshot"))
            copy_preview = _mapping(snapshot.get("copy_preview"))
            snapshot["provider_calls_enabled"] = True
            copy_preview["provider_calls_enabled"] = True
            snapshot["copy_preview"] = copy_preview
            ready_for_provider_assist = (
                str(task["status"]) == "REVIEW_REQUIRED"
                and str(task.get("blocker_code"))
                == "COPY_COMPONENT_SUPPLY_REQUIRED"
            )
            await factory_crud.update_task(
                str(task["task_id"]),
                status="READY" if ready_for_provider_assist else str(task["status"]),
                blocker_code=None if ready_for_provider_assist else task.get("blocker_code"),
                next_action=(
                    "MATERIALIZE_REVIEW_REQUIRED_COPY"
                    if ready_for_provider_assist
                    else task.get("next_action")
                ),
                snapshot_json=snapshot,
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


async def _refresh_plan_authority(plan: dict[str, object]) -> None:
    request = _mapping(plan.get("request"))
    contexts = [
        FactoryProductContext.model_validate(item)
        for item in _sequence_of_mappings(request.get("products"))
    ]
    if not contexts:
        return
    provider_enabled = bool(request.get("provider_calls_enabled"))
    scans: list[ProductScan] = []
    for context in contexts:
        scan = await _scan_product(context)
        scan.copy_preview["provider_calls_enabled"] = provider_enabled
        scans.append(scan)
    tasks = await factory_crud.list_tasks(str(plan["plan_id"]))
    for scan in scans:
        snapshot = _task_snapshot(scan)
        required_authority_sha256 = canonical_sha256(
            {
                "target_video_count": scan.context.target_video_count,
                "required_dialogues": required_dialogue_count(
                    scan.context.target_video_count
                ),
                "approved_copy_set_ids": _approved_copy_set_ids(scan),
                "variation_group_reuse_cap": canonical_same_dialogue_reuse_cap(),
                "readiness_sha256": (
                    scan.readiness.readiness_sha256 if scan.readiness else None
                ),
                "template_sha256": (
                    scan.template.template_sha256 if scan.template else None
                ),
                "scan_error_code": scan.error_code,
            }
        )
        for task in tasks:
            if str(task["product_id"]) != scan.context.product_id:
                continue
            task_type = cast(FactoryTaskType, str(task["task_type"]))
            status, blocker_code, next_action = _task_decision(scan, task_type)
            await factory_crud.update_task(
                str(task["task_id"]),
                status=status,
                required_authority_sha256=required_authority_sha256,
                blocker_code=blocker_code,
                next_action=next_action,
                template_id=scan.template.template_id if scan.template else None,
                template_sha256=(
                    scan.template.template_sha256 if scan.template else None
                ),
                snapshot_json=snapshot,
                error_code=scan.error_code,
            )
    refreshed_tasks = await factory_crud.list_tasks(str(plan["plan_id"]))
    await factory_crud.update_plan(
        str(plan["plan_id"]),
        status="SCANNED",
        readiness_summary_json=factory_crud.encode(
            _readiness_summary(refreshed_tasks)
        ),
        capacity_summary_json=factory_crud.encode(
            _capacity_summary(scans, refreshed_tasks)
        ),
        failure_count=sum(
            1 for task in refreshed_tasks if str(task["status"]) == "FAILED"
        ),
        scanned_at=factory_crud.utc_now(),
    )

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
    await _refresh_plan_authority(plan)
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
    return [await _plan_projection(row, include_tasks=False) for row in rows]
