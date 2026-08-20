"""V3 Copy Factory + Macro Round 2 Copy Register API.

Round 2 adds only explicit assistant planning/execution, bounded review reads,
and immutable human approval receipts.  V2 materialization, P6, media, and
activation endpoints remain deliberately absent.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from agent.services import production_allocation_service as allocation_service
from agent.services import production_copy_supply_service as supply_service
from agent.services import production_supply_manifest_service as manifest_service
from agent.services.production_supply_manifest_service import ManifestError
from agent.services.storyboard_landbank_v3_factory import (
    ROUND1_SOURCE,
    V3CopyFactoryService,
    V3FactoryError,
)
from agent.services.storyboard_landbank_v3_materializer import MaterializationError
from agent.services.storyboard_landbank_v3_round2 import round2_service
from agent.services.storyboard_landbank_v3_maintenance import (
    V3CopywritingLandbankMaintenanceService,
)


router = APIRouter(prefix="/storyboard-landbank/v3", tags=["storyboard-landbank-v3"])
service = V3CopyFactoryService()
maintenance_service = V3CopywritingLandbankMaintenanceService(factory=service)


def _error(exc: V3FactoryError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
    if exc.details is not None:
        detail["details"] = exc.details
    return HTTPException(status_code=exc.status_code, detail=detail)


def _materialization_error(exc: MaterializationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.detail, "details": exc.details},
    )


def _manifest_error(exc: ManifestError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.detail, "details": exc.details},
    )


def _meta(request: Request, payload: dict[str, Any]) -> tuple[str, str, str]:
    actor_id = str(request.headers.get("X-Actor-Id") or payload.get("actor_id") or "").strip()
    request_id = str(
        request.headers.get("X-Request-Id")
        or request.headers.get("Idempotency-Key")
        or payload.get("request_id")
        or ""
    ).strip()
    source = str(request.headers.get("X-Source") or payload.get("source") or ROUND1_SOURCE).strip()
    if not actor_id or not request_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "MUTATION_RECEIPT_REQUIRED", "message": "actor_id and request_id are required for V3 mutations."},
        )
    return actor_id, request_id, source


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, (tuple, list)):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


@router.get("/authority/formulas")
async def get_formula_authority(production_only: bool = Query(default=False)):
    return {"formulas": [_dump(item) for item in await service.formulas(production_only=production_only)], "provider_calls": 0}


@router.get("/products/{product_id}/truth")
async def get_product_truth(product_id: str):
    try:
        return await service.product_supply(product_id)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/products/{product_id}/supply")
async def get_product_supply(product_id: str):
    return await get_product_truth(product_id)


@router.get("/products/{product_id}/evidence/rank")
async def rank_product_evidence(
    product_id: str,
    formula_id: str | None = None,
    fact_id: list[str] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        result = await service.rank_evidence(product_id, formula_id=formula_id, requested_fact_ids=tuple(fact_id or ()), limit=limit)
        return _dump(result)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/angles")
async def list_angles(
    product_id: str | None = None,
    status: str | None = None,
    formula_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        rows = await service.repository.list("ANGLE", product_id=product_id, status=status, formula_id=formula_id, limit=limit, offset=offset)
        return {"items": [_dump(row) for row in rows[:limit]], "limit": limit, "offset": offset, "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/angles/{angle_id}")
async def get_angle(angle_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("ANGLE", angle_id, revision)
        if row is None:
            raise V3FactoryError("ANGLE_NOT_FOUND", "Angle was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/angles", status_code=201)
async def create_angle(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.create_angle(str(payload.get("product_id") or ""), payload, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/angles/{angle_id}/revisions", status_code=201)
async def revise_angle(angle_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        revision = int(payload.get("revision") or 1)
        updates = dict(payload.get("updates") or {})
        return _dump(await service.create_revision("ANGLE", angle_id, revision, updates, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/storyline-families")
async def list_storyline_families(
    product_id: str | None = None,
    status: str | None = None,
    formula_id: str | None = None,
    angle_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        rows = await service.repository.list("STORYLINE_FAMILY", product_id=product_id, status=status, formula_id=formula_id, angle_id=angle_id, limit=limit, offset=offset)
        return {"items": [_dump(row) for row in rows[:limit]], "limit": limit, "offset": offset, "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/storyline-families/{family_id}")
async def get_storyline_family(family_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("STORYLINE_FAMILY", family_id, revision)
        if row is None:
            raise V3FactoryError("STORYLINE_FAMILY_NOT_FOUND", "Storyline Family was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/storyline-families", status_code=201)
async def create_storyline_family(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.create_storyline_family(str(payload.get("product_id") or ""), payload, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/storyline-families/{family_id}/revisions", status_code=201)
async def revise_storyline_family(family_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(
            await service.create_revision(
                "STORYLINE_FAMILY",
                family_id,
                int(payload.get("revision") or 1),
                dict(payload.get("updates") or {}),
                actor_id=actor_id,
                request_id=request_id,
                source=source,
            )
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/components")
async def list_components(
    product_id: str | None = None,
    status: str | None = None,
    formula_id: str | None = None,
    storyline_family_id: str | None = None,
    semantic_class: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        rows = await service.repository.list("STORYBOARD_COMPONENT", product_id=product_id, status=status, formula_id=formula_id, storyline_family_id=storyline_family_id, limit=limit, offset=offset)
        if semantic_class:
            rows = [row for row in rows if row.semantic_class == semantic_class.upper()]
        return {"items": [_dump(row) for row in rows[:limit]], "limit": limit, "offset": offset, "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/components/{component_id}")
async def get_component(component_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("STORYBOARD_COMPONENT", component_id, revision)
        if row is None:
            raise V3FactoryError("COMPONENT_NOT_FOUND", "Component was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/components", status_code=201)
async def create_component(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.create_component(str(payload.get("product_id") or ""), payload, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/components/{component_id}/revisions", status_code=201)
async def revise_component(component_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(
            await service.create_revision(
                "STORYBOARD_COMPONENT",
                component_id,
                int(payload.get("revision") or 1),
                dict(payload.get("updates") or {}),
                actor_id=actor_id,
                request_id=request_id,
                source=source,
            )
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/recipes")
async def list_recipes(product_id: str | None = None, status: str | None = None, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    try:
        rows = await service.repository.list("COPY_RECIPE", product_id=product_id, status=status, limit=limit, offset=offset)
        return {"items": [_dump(row) for row in rows[:limit]], "limit": limit, "offset": offset, "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/recipes", status_code=201)
async def create_recipe(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.create_recipe(str(payload.get("product_id") or ""), payload, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("COPY_RECIPE", recipe_id, revision)
        if row is None:
            raise V3FactoryError("RECIPE_NOT_FOUND", "Copy Recipe was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/recipes/{recipe_id}/revisions", status_code=201)
async def revise_recipe(recipe_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(
            await service.create_revision(
                "COPY_RECIPE",
                recipe_id,
                int(payload.get("revision") or 1),
                dict(payload.get("updates") or {}),
                actor_id=actor_id,
                request_id=request_id,
                source=source,
            )
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/recipes/preview")
async def preview_recipe(payload: dict[str, Any]):
    try:
        formula_id = str(payload.get("formula_id") or "")
        formula = next(item for item in await service.formulas(production_only=True) if item.formula_id == formula_id or item.formula_id.casefold() == formula_id.casefold())
        preset = str(payload.get("preset") or "CUSTOM").upper()
        targets = payload.get("component_count_targets") or ({"HOOK": 6, "BODY_CORE": 3, "CTA": 3} if preset == "FAST54" else {})
        theoretical = int(targets.get("HOOK", 0)) * int(targets.get("BODY_CORE", 0)) * int(targets.get("CTA", 0))
        return {"preset": preset, "formula": _dump(formula), "component_count_targets": targets, "requested_capacity": payload.get("requested_capacity", theoretical), "theoretical_capacity": theoretical, "approved_capacity": 0, "executable_capacity": 0, "provider_calls": 0, "mutations": 0}
    except (StopIteration, V3FactoryError) as exc:
        if isinstance(exc, V3FactoryError):
            raise _error(exc) from exc
        raise HTTPException(status_code=422, detail={"code": "FORMULA_UNKNOWN", "message": "Formula is not canonical."}) from exc


@router.post("/candidates/preview")
async def preview_candidates(payload: dict[str, Any]):
    try:
        return _dump(await service.enumerate_candidates(str(payload.get("recipe_id") or ""), revision=payload.get("revision"), limit=int(payload.get("limit") or 50), cursor=payload.get("cursor"), durations=payload.get("durations"), compile=True, existing_fingerprints=payload.get("existing_fingerprints") or ()))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/candidates/compile")
async def compile_candidates(payload: dict[str, Any]):
    return await preview_candidates(payload)


@router.post("/masters/compile")
async def compile_master(request: Request, payload: dict[str, Any]):
    try:
        persist = bool(payload.get("persist", False))
        actor_id = request.headers.get("X-Actor-Id") or payload.get("actor_id")
        request_id = request.headers.get("X-Request-Id") or request.headers.get("Idempotency-Key") or payload.get("request_id")
        source = request.headers.get("X-Source") or payload.get("source") or ROUND1_SOURCE
        result = await service.compile_master(
            str(payload.get("recipe_id") or ""), angle_id=str(payload.get("angle_id") or ""), angle_revision=int(payload.get("angle_revision") or 1),
            storyline_family_id=str(payload.get("storyline_family_id") or ""), storyline_family_revision=int(payload.get("storyline_family_revision") or 1),
            hook_id=str(payload.get("hook_id") or ""), hook_revision=int(payload.get("hook_revision") or 1),
            body_core_id=str(payload.get("body_core_id") or ""), body_core_revision=int(payload.get("body_core_revision") or 1),
            cta_id=str(payload.get("cta_id") or ""), cta_revision=int(payload.get("cta_revision") or 1),
            persist=persist, actor_id=str(actor_id or "") if persist else None, request_id=str(request_id or "") if persist else None, source=str(source),
        )
        return _dump(result)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/masters/{master_id}")
async def get_master(master_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("MASTER_STORYBOARD", master_id, revision)
        if row is None:
            raise V3FactoryError("MASTER_NOT_FOUND", "Master Storyboard was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/masters/{master_id}/projections")
async def get_master_projections(master_id: str, revision: int = Query(default=1, ge=1), limit: int = Query(default=100, ge=1, le=500)):
    try:
        master = await service.get_entity("MASTER_STORYBOARD", master_id, revision)
        if master is None:
            raise V3FactoryError("MASTER_NOT_FOUND", "Master Storyboard was not found.", status_code=404)
        rows = await service.repository.list("DURATION_PROJECTION", product_id=master.product_id, limit=limit, latest_only=True)
        return {"master": _dump(master), "projections": [_dump(row) for row in rows if row.master.entity_id == master_id and row.master.revision == revision][:limit], "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/projections/{projection_id}")
async def get_projection(projection_id: str, revision: int | None = Query(default=None, ge=1)):
    try:
        row = await service.get_entity("DURATION_PROJECTION", projection_id, revision)
        if row is None:
            raise V3FactoryError("PROJECTION_NOT_FOUND", "Duration Projection was not found.", status_code=404)
        return _dump(row)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/projections/compile")
async def compile_projection(request: Request, payload: dict[str, Any]):
    try:
        persist = bool(payload.get("persist", False))
        actor_id = request.headers.get("X-Actor-Id") or payload.get("actor_id")
        request_id = request.headers.get("X-Request-Id") or request.headers.get("Idempotency-Key") or payload.get("request_id")
        projection, issues, details = await service.project_duration(
            str(payload.get("master_id") or ""), master_revision=int(payload.get("master_revision") or 1), duration_seconds=int(payload.get("duration_seconds") or payload.get("target_duration_seconds") or 0),
            language_profile=str(payload.get("language_profile") or "Malay"), wps_mode=str(payload.get("wps_mode") or "SAFE"), preferred_lane=payload.get("preferred_lane"),
            persist=persist, actor_id=str(actor_id or "") if persist else None, request_id=str(request_id or "") if persist else None, source=str(payload.get("source") or ROUND1_SOURCE),
        )
        return {"projection": _dump(projection), "valid": projection is not None and not issues, "issue_codes": issues, "details": details, "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/capacity/{recipe_id}")
async def get_capacity(recipe_id: str, evaluation_limit: int = Query(default=250, ge=1, le=250)):
    try:
        return _dump(await service.capacity(recipe_id, evaluation_limit=evaluation_limit))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/capacity/preview")
async def preview_capacity(payload: dict[str, Any]):
    try:
        return _dump(await service.capacity(str(payload.get("recipe_id") or ""), revision=payload.get("revision"), evaluation_limit=int(payload.get("evaluation_limit") or 250)))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/provider-status")
async def get_v3_copy_register_provider_status():
    """Secret-free status for the reused text_assist lane; never calls it."""

    return {**_dump(round2_service.provider_status()), "provider_calls": 0, "credit_spend": 0}


@router.post("/copy-register/setup-campaign")
async def setup_v3_campaign(request: Request, payload: dict[str, Any]):
    """Normal Setup Campaign: build/reuse a V3 CopyRecipe from a human preset."""
    try:
        actor_id, request_id, _source = _meta(request, payload)
        return await round2_service.create_campaign_recipe(
            str(payload.get("product_id") or ""),
            objective_id=str(payload.get("objective_id") or ""),
            objective_definition=str(payload.get("objective_definition") or payload.get("objective_id") or ""),
            formula_id=str(payload.get("formula_id") or ""),
            preset=str(payload.get("preset") or "CUSTOM"),
            supported_durations_seconds=payload.get("supported_durations_seconds"),
            target_capacity=payload.get("target_capacity"),
            language_profile=str(payload.get("language_profile") or "Malay"),
            wps_mode=str(payload.get("wps_mode") or "SAFE"),
            component_count_targets=payload.get("component_count_targets"),
            actor_id=actor_id,
            request_id=request_id,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/assistant/plan")
async def plan_v3_copy_assistant(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, _source = _meta(request, payload)
        plan = await round2_service.plan_assistant(
            str(payload.get("product_id") or ""),
            str(payload.get("recipe_id") or ""),
            mode=str(payload.get("mode") or "CREATE").upper(),
            actor_id=actor_id,
            request_id=request_id,
            revision=payload.get("revision"),
            additional_count=int(payload.get("additional_count") or 1),
            semantic_class=payload.get("semantic_class"),
            target_counts=payload.get("target_counts"),
            target_capacity=payload.get("target_capacity"),
            evidence_fact_ids=payload.get("evidence_fact_ids"),
            max_provider_calls=int(payload.get("max_provider_calls") if payload.get("max_provider_calls") is not None else 1),
            max_output_tokens=int(payload.get("max_output_tokens") if payload.get("max_output_tokens") is not None else 20000),
            max_cost=int(payload.get("max_cost") if payload.get("max_cost") is not None else 0),
        )
        return {"plan": _dump(plan), "provider_calls": 0, "credit_spend": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/assistant/plans/{plan_id}")
async def get_v3_copy_assistant_plan(plan_id: str):
    try:
        return {"plan": _dump(await round2_service._load_plan(plan_id)), "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/assistant/plans/{plan_id}/prompt-preview")
async def preview_v3_copy_assistant_prompt(plan_id: str):
    try:
        return {"preview": _dump(await round2_service.prompt_preview(plan_id)), "provider_calls": 0, "credit_spend": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/assistant/plans/{plan_id}/execute")
async def execute_v3_copy_assistant(request: Request, plan_id: str, payload: dict[str, Any]):
    try:
        actor_id, request_id, _source = _meta(request, payload)
        mode = str(payload.get("provider_mode") or "LIVE_TEXT_ASSIST").upper()
        if mode not in {"LIVE_TEXT_ASSIST", "FAKE_TEST"}:
            raise V3FactoryError("PROVIDER_MODE_INVALID", "provider_mode must be LIVE_TEXT_ASSIST or FAKE_TEST.", status_code=422)
        return await round2_service.execute_assistant(
            plan_id,
            actor_id=actor_id,
            request_id=request_id,
            provider_mode=mode,  # type: ignore[arg-type]
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/assistant/projection/ai-assisted")
async def derive_v3_ai_assisted_projection(request: Request, payload: dict[str, Any]):
    """Governed AI-assisted natural compression of a Master's overlong stages."""
    try:
        actor_id, request_id, _source = _meta(request, payload)
        mode = str(payload.get("provider_mode") or "LIVE_TEXT_ASSIST").upper()
        if mode not in {"LIVE_TEXT_ASSIST", "FAKE_TEST"}:
            raise V3FactoryError("PROVIDER_MODE_INVALID", "provider_mode must be LIVE_TEXT_ASSIST or FAKE_TEST.", status_code=422)
        return await round2_service.derive_ai_assisted_projection(
            str(payload.get("master_id") or ""),
            master_revision=int(payload.get("master_revision") or 1),
            duration_seconds=int(payload.get("duration_seconds") or 8),
            provider_mode=mode,  # type: ignore[arg-type]
            language_profile=str(payload.get("language_profile") or "Malay"),
            wps_mode=str(payload.get("wps_mode") or "SAFE"),
            actor_id=actor_id,
            request_id=request_id,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/components/{component_id}/regenerate")
async def regenerate_v3_component(request: Request, component_id: str, payload: dict[str, Any]):
    """Provider-backed regeneration of a DRAFT component into a NEW revision."""
    try:
        actor_id, request_id, _source = _meta(request, payload)
        mode = str(payload.get("provider_mode") or "LIVE_TEXT_ASSIST").upper()
        if mode not in {"LIVE_TEXT_ASSIST", "FAKE_TEST"}:
            raise V3FactoryError("PROVIDER_MODE_INVALID", "provider_mode must be LIVE_TEXT_ASSIST or FAKE_TEST.", status_code=422)
        return await round2_service.regenerate_component(
            component_id,
            revision=int(payload.get("revision") or 1),
            provider_mode=mode,  # type: ignore[arg-type]
            actor_id=actor_id,
            request_id=request_id,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/runs/{product_id}")
async def list_v3_copy_assistant_runs(product_id: str, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)):
    try:
        return await round2_service.list_runs(product_id, limit=limit, offset=offset)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/landbank")
async def get_v3_copy_register_landbank(
    product_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    formula_id: str | None = None,
    angle_id: str | None = None,
    storyline_family_id: str | None = None,
    duration_seconds: int | None = Query(default=None, ge=1),
    source: str | None = None,
    quality: str | None = None,
    blocker: str | None = None,
    recipe_id: str | None = None,
    search: str | None = None,
):
    try:
        payload = await round2_service.copy_register_landbank(
            product_id, limit=limit, offset=offset, status=status, formula_id=formula_id,
            angle_id=angle_id, storyline_family_id=storyline_family_id, duration_seconds=duration_seconds,
            source=source, quality=quality, blocker=blocker, recipe_id=recipe_id, search=search,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc
    # Read-only enrichment: report truthful V2 materialization status per
    # projection.  Opening the landbank NEVER materializes and NEVER approves.
    return await supply_service.enrich_landbank_payload(payload)


@router.get("/copy-register/maintenance")
async def get_v3_copy_register_maintenance(
    product_id: str | None = None,
    status: str | None = None,
    formula_id: str | None = None,
    angle_id: str | None = None,
    search: str | None = None,
    production_ready: bool | None = None,
    stale: bool | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Authoritative all-product Reporting view over exact V3 Master revisions."""

    try:
        return await maintenance_service.list_records(
            product_id=product_id,
            status=status,
            formula_id=formula_id,
            angle_id=angle_id,
            search=search,
            production_ready=production_ready,
            stale=stale,
            limit=limit,
            offset=offset,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/maintenance/{master_id}")
async def get_v3_copy_register_maintenance_detail(
    master_id: str,
    revision: int = Query(..., ge=1),
):
    """Return one exact Master Storyboard revision; never silently resolve latest."""

    try:
        return await maintenance_service.get_detail(master_id, revision)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/maintenance/{master_id}/revisions", status_code=201)
async def create_v3_copy_register_maintenance_revision(
    master_id: str,
    request: Request,
    payload: dict[str, Any],
):
    """Save stage text as a new DRAFT revision with optimistic concurrency."""

    try:
        actor_id, request_id, _source = _meta(request, payload)
        raw_source_revision = payload.get("source_revision")
        if raw_source_revision is None:
            raw_source_revision = payload.get("expected_revision")
        if raw_source_revision is None:
            raise V3FactoryError(
                "SOURCE_REVISION_REQUIRED",
                "source_revision is required for a safe maintenance save.",
                status_code=422,
            )
        return await maintenance_service.create_manual_revision(
            master_id,
            source_revision=int(raw_source_revision),
            stages=payload.get("stages") or [],
            actor_id=actor_id,
            request_id=request_id,
            reason=str(payload.get("reason") or "").strip() or None,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.delete("/copy-register/maintenance/{master_id}/{revision}")
async def delete_v3_copy_register_maintenance_draft(
    master_id: str,
    revision: int,
    request: Request,
):
    """Delete only an unreferenced exact DRAFT Master revision."""

    try:
        actor_id, request_id, _source = _meta(request, {})
        return {
            "deleted": await maintenance_service.delete_draft(
                master_id,
                revision,
                actor_id=actor_id,
                request_id=request_id,
            ),
            "provider_calls": 0,
            "mutations": 1,
        }
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/materialize")
async def materialize_v3_projection(request: Request, payload: dict[str, Any]):
    """Explicitly materialize ONE approved projection into a V2 PRODUCTION_VALID blueprint."""

    actor_id, _request_id, _source = _meta(request, payload)
    projection_id = str(payload.get("projection_id") or "").strip()
    receipt_id = str(payload.get("receipt_id") or "").strip()
    if not projection_id or not receipt_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MATERIALIZE_REQUEST_INVALID",
                "message": "projection_id and receipt_id are required.",
            },
        )
    try:
        return await supply_service.materialize(
            projection_id=projection_id,
            receipt_id=receipt_id,
            projection_revision=payload.get("projection_revision"),
            actor_id=actor_id,
        )
    except MaterializationError as exc:
        raise _materialization_error(exc) from exc


@router.post("/copy-register/materialize-bulk")
async def materialize_v3_projections_bulk(request: Request, payload: dict[str, Any]):
    """Bounded bulk materialization of clean approved projections (partial success)."""

    actor_id, _request_id, _source = _meta(request, payload)
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MATERIALIZE_BULK_REQUEST_INVALID",
                "message": "items must be a non-empty list of {projection_id, receipt_id}.",
            },
        )
    try:
        return await supply_service.materialize_bulk(items, actor_id=actor_id)
    except MaterializationError as exc:
        raise _materialization_error(exc) from exc


@router.get("/copy-register/capacity")
async def get_v3_production_capacity(product_id: str):
    """4-tier capacity: semantic / projection / executable-copy / production."""

    return await supply_service.production_capacity(product_id)


@router.post("/copy-register/manifest")
async def build_v3_production_manifest(request: Request, payload: dict[str, Any]):
    """Build a DRAFT production copy supply manifest from MATERIALIZED supply."""

    actor_id, _request_id, _source = _meta(request, payload)
    product_id = str(payload.get("product_id") or "").strip()
    if not product_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "MANIFEST_REQUEST_INVALID", "message": "product_id is required."},
        )
    try:
        outcome = await manifest_service.build_manifest(
            product_id,
            requested_capacity=int(payload.get("requested_capacity") or 1),
            actor_id=actor_id,
            duration_seconds=payload.get("duration_seconds"),
            reuse_policy=payload.get("reuse_policy"),
            campaign_key=str(payload.get("campaign_key") or ""),
            production_plan_id=payload.get("production_plan_id"),
        )
    except ManifestError as exc:
        raise _manifest_error(exc) from exc
    return _dump(outcome)


@router.post("/copy-register/manifest/{manifest_id}/freeze")
async def freeze_v3_production_manifest(
    request: Request, manifest_id: str, payload: dict[str, Any]
):
    actor_id, _request_id, _source = _meta(request, payload)
    revision = int(payload.get("revision") or 0)
    if revision < 1:
        raise HTTPException(
            status_code=422,
            detail={"code": "MANIFEST_REQUEST_INVALID", "message": "revision is required."},
        )
    try:
        return _dump(
            await manifest_service.freeze_manifest(manifest_id, revision, actor_id=actor_id)
        )
    except ManifestError as exc:
        raise _manifest_error(exc) from exc


@router.post("/copy-register/manifest/{manifest_id}/allocate-to-plan")
async def allocate_v3_manifest_to_production_plan(
    request: Request, manifest_id: str, payload: dict[str, Any]
):
    """Persist a FROZEN manifest's exact per-item selections onto REAL P6 items.

    Operator-governed: binds each production item to an exact V2 blueprint
    revision + approval snapshot (idempotent) so compile resolves per-item copy.
    Never mutates the product-global V2 activation pointer.
    """

    actor_id, _request_id, _source = _meta(request, payload)
    revision = int(payload.get("revision") or 0)
    production_plan_id = str(payload.get("production_plan_id") or "").strip()
    requested_items = int(payload.get("requested_items") or 0)
    if revision < 1 or not production_plan_id or requested_items < 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ALLOCATION_REQUEST_INVALID",
                "message": "revision, production_plan_id and requested_items are required.",
            },
        )
    try:
        return await allocation_service.allocate_manifest_to_production_plan(
            production_plan_id=production_plan_id,
            manifest_id=manifest_id,
            manifest_revision=revision,
            requested_items=requested_items,
            actor_id=actor_id,
            campaign_key=str(payload.get("campaign_key") or ""),
            allow_exact_reuse=bool(payload.get("allow_exact_reuse") or False),
        )
    except allocation_service.AllocationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail, "details": exc.details},
        ) from exc


@router.get("/copy-register/manifest/{manifest_id}")
async def get_v3_production_manifest(manifest_id: str, revision: int | None = None):
    try:
        return _dump(await manifest_service.get_manifest_view(manifest_id, revision))
    except ManifestError as exc:
        raise _manifest_error(exc) from exc


@router.get("/copy-register/review-queue")
async def get_v3_copy_register_review_queue(
    product_id: str,
    status: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    formula_id: str | None = None,
    angle_id: str | None = None,
    storyline_family_id: str | None = None,
    duration_seconds: int | None = Query(default=None, ge=1),
    source: str | None = None,
    quality: str | None = None,
    blocker: str | None = None,
    recipe_id: str | None = None,
    search: str | None = None,
):
    try:
        return await round2_service.review_queue(
            product_id, statuses=tuple(status or ("DRAFT", "REVIEW_REQUIRED", "VALIDATED", "BLOCKED")),
            limit=limit, offset=offset, formula_id=formula_id, angle_id=angle_id,
            storyline_family_id=storyline_family_id, duration_seconds=duration_seconds,
            source=source, quality=quality, blocker=blocker, recipe_id=recipe_id, search=search,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/approval/master/{master_id}")
async def approve_v3_master_storyboard(request: Request, master_id: str, payload: dict[str, Any]):
    try:
        actor_id, request_id, _source = _meta(request, payload)
        return await round2_service.human_approve(
            master_id,
            projection_ids=payload.get("projection_ids") or [],
            checklist=payload.get("checklist") or {},
            approved_by=str(payload.get("approved_by") or actor_id),
            rationale=str(payload.get("rationale") or ""),
            actor_id=actor_id,
            request_id=request_id,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/copy-register/approval/batch")
async def approve_v3_master_batch(request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, _source = _meta(request, payload)
        return await round2_service.human_approve_batch(
            targets=payload.get("targets") or [],
            checklist=payload.get("checklist") or {},
            approved_by=str(payload.get("approved_by") or actor_id),
            rationale=str(payload.get("rationale") or ""),
            actor_id=actor_id,
            request_id=request_id,
        )
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/copy-register/approval/receipt/{receipt_id}/verify")
async def verify_v3_approval_receipt(receipt_id: str):
    """Recompute a stored receipt's per-candidate + batch digests (tamper check)."""
    try:
        return await round2_service.verify_receipt(receipt_id)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/landbank/components")
async def get_component_landbank(product_id: str, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), formula_id: str | None = None, semantic_class: str | None = None, status: str | None = None):
    try:
        return _dump(await service.component_landbank(product_id, limit=limit, offset=offset, formula_id=formula_id, semantic_class=semantic_class, status=status))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/landbank/storyboards")
async def get_storyboard_landbank(product_id: str, limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0), status: str | None = None):
    try:
        return _dump(await service.storyboard_landbank(product_id, limit=limit, offset=offset, status=status))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/review-queue")
async def get_review_queue(product_id: str | None = None, status: list[str] | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    try:
        return _dump(await service.review_queue(product_id, statuses=tuple(status or ("DRAFT", "REVIEW_REQUIRED", "VALIDATED", "BLOCKED", "REJECTED")), limit=limit, offset=offset))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/review/{entity_type}/{entity_id}/validate")
async def validate_v3_entity(entity_type: str, entity_id: str, revision: int | None = None):
    try:
        return await service.validate_entity(entity_type, entity_id, revision)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/review/{entity_type}/{entity_id}/submit")
async def submit_v3_entity(entity_type: str, entity_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.transition(entity_type, entity_id, int(payload.get("revision") or 1), "REVIEW_REQUIRED", actor_id=actor_id, request_id=request_id, source=source, reason=payload.get("reason")))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/review/{entity_type}/{entity_id}/reject")
async def reject_v3_entity(entity_type: str, entity_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.transition(entity_type, entity_id, int(payload.get("revision") or 1), "REJECTED", actor_id=actor_id, request_id=request_id, source=source, reason=payload.get("reason")))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/review/{entity_type}/{entity_id}/archive")
async def archive_v3_entity(entity_type: str, entity_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.transition(entity_type, entity_id, int(payload.get("revision") or 1), "ARCHIVED", actor_id=actor_id, request_id=request_id, source=source, reason=payload.get("reason")))
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.delete("/drafts/{entity_type}/{entity_id}/{revision}")
async def delete_v3_draft(entity_type: str, entity_id: str, revision: int, request: Request):
    try:
        actor_id, request_id, source = _meta(request, {})
        return {"deleted": await service.delete_draft(entity_type, entity_id, revision, actor_id=actor_id, request_id=request_id, source=source), "provider_calls": 0}
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.get("/seeds/v2/preview")
async def preview_v2_seed(product_id: str, blueprint_id: str | None = None, angle_id: str | None = None):
    try:
        return await service.v2_seed_preview(product_id, blueprint_id=blueprint_id, angle_id=angle_id)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/seeds/v2/blueprints/{blueprint_id}/import-draft", status_code=201)
async def import_v2_seed(blueprint_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return await service.import_v2_blueprint_draft(str(payload.get("product_id") or ""), blueprint_id, int(payload.get("revision") or 1), actor_id=actor_id, request_id=request_id, source=source)
    except V3FactoryError as exc:
        raise _error(exc) from exc


@router.post("/seeds/v2/angles/{angle_id}/import-draft", status_code=201)
async def import_v2_angle_seed(angle_id: str, request: Request, payload: dict[str, Any]):
    try:
        actor_id, request_id, source = _meta(request, payload)
        return _dump(await service.import_v2_angle_draft(str(payload.get("product_id") or ""), angle_id, actor_id=actor_id, request_id=request_id, source=source))
    except V3FactoryError as exc:
        raise _error(exc) from exc


__all__ = ["router"]
