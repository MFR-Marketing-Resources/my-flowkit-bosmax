"""HTTP surface for the Creative Execution Recipe (Round 3).

Finalized rendered copy + production recipe + AUTO governed visual variation ->
immutable CreativeExecutionRecipeV1 -> provider-free compile to an immutable
prompt snapshot (an existing workspace_execution_package). Remix = same copy,
new visual. Thin handlers delegate to ``creative_execution_recipe_service``.

Auth: every endpoint requires an authenticated human session (401); mutations
additionally require ``products.update`` (403). Provider-free — nothing here
enqueues production, spends credits, or touches the Copy Register V2 binding.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent.models.creative_execution_recipe_v1 import (
    CreateExecutionRecipesRequest,
    RemixExecutionRecipeRequest,
)
from agent.security.access_control import get_current_auth_context
from agent.services import creative_execution_recipe_service as svc

router = APIRouter(prefix="/creative-execution-recipe", tags=["creative-execution-recipe"])

_MUTATION_PERMISSION = "products.update"


def _raise(exc: svc.CreativeExecutionRecipeError):
    raise HTTPException(
        status_code=exc.status_code,
        detail={"error": exc.code, "message": exc.message, "details": exc.details},
    ) from exc


def _require_actor():
    actor = get_current_auth_context()
    if actor is None:
        raise HTTPException(status_code=401, detail={"error": "AUTHENTICATION_REQUIRED",
                            "message": "An authenticated session is required."})
    return actor


def _require_mutation_actor():
    actor = _require_actor()
    if _MUTATION_PERMISSION not in actor.permission_codes:
        raise HTTPException(status_code=403, detail={"error": "PERMISSION_DENIED",
                            "message": f"This action requires the {_MUTATION_PERMISSION} permission."})
    return actor


@router.post("/recipes")
async def create_recipes(req: CreateExecutionRecipesRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.create_execution_recipes(
            candidate_id=req.candidate_id, production_recipe=req.production_recipe,
            visual_count=req.visual_count, duration_seconds=req.duration_seconds,
            avatar_id=req.avatar_id, treatment_id=req.treatment_id, seed=req.seed)
    except svc.CreativeExecutionRecipeError as exc:
        _raise(exc)


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: str) -> dict[str, Any]:
    _require_actor()
    recipe = await svc.get_execution_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail={"error": "EXECUTION_RECIPE_NOT_FOUND"})
    return recipe


@router.get("/recipes")
async def list_recipes(candidate_id: str | None = Query(default=None),
                       product_id: str | None = Query(default=None),
                       production_recipe: str | None = Query(default=None)) -> dict[str, Any]:
    _require_actor()
    recipes = await svc.list_execution_recipes(
        candidate_id=candidate_id, product_id=product_id, production_recipe=production_recipe)
    return {"recipes": recipes, "count": len(recipes)}


@router.post("/recipes/{recipe_id}/compile")
async def compile_recipe(recipe_id: str) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.compile_execution_recipe(recipe_id)
    except svc.CreativeExecutionRecipeError as exc:
        _raise(exc)


@router.post("/recipes/{recipe_id}/remix")
async def remix_recipe(recipe_id: str, req: RemixExecutionRecipeRequest) -> dict[str, Any]:
    _require_mutation_actor()
    try:
        return await svc.remix_execution_recipe(recipe_id, seed=req.seed, visual_count=req.visual_count)
    except svc.CreativeExecutionRecipeError as exc:
        _raise(exc)
