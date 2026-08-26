"""Creative Execution Recipe service (Round 3) — provider-free.

Binds an immutable rendered-copy identity (BENEFIT_COPY_RENDER_V1) + a production
recipe + a deterministic governed visual variation into the durable, immutable
CreativeExecutionRecipeV1, and compiles it (provider-free) into an existing
workspace_execution_package which serves as the immutable prompt snapshot.

Laws honoured:
  * SYSTEM OWNS VISUAL VARIATION / RECIPE LINEAGE / PROMPT SNAPSHOTS.
  * NO new copy LLM, NO new visual LLM, NO new prompt compiler.
  * SAME copy + NEW visual = REMIX (a new recipe; no text-provider call).
  * EXACT REPLAY: identical immutable inputs -> identical recipe_id.
  * Never mutates copy_render_* or the product-global Copy Register V2 binding.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from agent.db import copy_render_crud as _cr
from agent.db import creative_execution_recipe_crud as _crud
from agent.models.creative_execution_recipe_v1 import (
    PRODUCTION_RECIPE_TO_COPY_LANE,
    RECIPE_SCHEMA_VERSION,
    SUPPORTED_PRODUCTION_RECIPES,
)
from agent.services import auto_visual_variation_service as _avv


class CreativeExecutionRecipeError(Exception):
    def __init__(self, code: str, message: str = "", *, details: Any = None,
                 status_code: int = 409) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details or {}
        self.status_code = status_code


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"),
                      default=str)


def _identity_digest(fields: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_json(dict(fields)).encode("utf-8")).hexdigest()


async def _resolve_copy_identity(candidate_id: str, production_recipe: str):
    """Read (provider-free) the finalized rendered-copy identity + the request-scoped
    BENEFIT_COPY_RENDER_V1 resolution for a candidate. Fail-closed."""
    copy_lane = PRODUCTION_RECIPE_TO_COPY_LANE[production_recipe]
    candidate = await _cr.get_candidate(candidate_id)
    if candidate is None:
        raise CreativeExecutionRecipeError(
            "EXECUTION_RECIPE_CANDIDATE_NOT_FOUND", details={"candidate_id": candidate_id})
    if str(candidate.get("status")) not in ("LOCKED", "FINALIZED"):
        raise CreativeExecutionRecipeError(
            "EXECUTION_RECIPE_CANDIDATE_NOT_SELECTED",
            "Only a LOCKED or FINALIZED rendered-copy candidate can seed an execution recipe.",
            details={"candidate_id": candidate_id, "status": candidate.get("status")})
    session = await _cr.get_session(str(candidate.get("session_id")))
    if session is None:
        raise CreativeExecutionRecipeError(
            "EXECUTION_RECIPE_SESSION_NOT_FOUND", details={"candidate_id": candidate_id})
    if str(session.get("lane")) != copy_lane:
        raise CreativeExecutionRecipeError(
            "EXECUTION_RECIPE_LANE_MISMATCH",
            f"A {production_recipe} recipe needs a {copy_lane}-lane rendered-copy candidate.",
            details={"candidate_lane": session.get("lane"), "required_lane": copy_lane})
    product_id = str(session.get("product_id"))
    # provider-free BENEFIT_COPY_RENDER_V1 resolution (validates + projects the copy)
    from agent.services.copy_render_execution_resolver import resolve_rendered_copy_execution
    from agent.services.copy_execution_resolver import CopyExecutionResolutionError
    try:
        resolution = await resolve_rendered_copy_execution(product_id, copy_lane, candidate_id)
    except CopyExecutionResolutionError as exc:
        raise CreativeExecutionRecipeError(exc.code, str(exc), details=getattr(exc, "details", {}),
                                           status_code=getattr(exc, "status_code", 409))
    return product_id, copy_lane, candidate, session, resolution


def _visual_lineage(production_recipe: str, variation: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a resolver variation into the recipe's first-class visual columns."""
    return {
        "visual_variation_fingerprint": str(variation.get("visual_variation_fingerprint") or ""),
        "avatar_id": variation.get("avatar_id"),
        "scene_template_id": variation.get("scene_template_id"),
        "camera_preset_code": variation.get("camera_preset_code"),
        "wardrobe": variation.get("wardrobe"),
        "environment": variation.get("environment"),
        "faceless_actor_profile": variation.get("faceless_actor_profile"),
        "montage_mascot_media_id": variation.get("montage_mascot_media_id"),
    }


async def create_execution_recipes(
    *, candidate_id: str, production_recipe: str, visual_count: int,
    duration_seconds: int | None = None, avatar_id: str | None = None,
    treatment_id: str | None = None, seed: str | None = None,
) -> dict[str, Any]:
    """Create ``visual_count`` immutable execution recipes from ONE finalized copy
    candidate (SAME copy, distinct governed visual variations). Provider-free +
    idempotent (identical inputs -> identical recipe_ids)."""
    recipe_kind = str(production_recipe or "").strip().upper()
    if recipe_kind not in SUPPORTED_PRODUCTION_RECIPES:
        raise CreativeExecutionRecipeError(
            "PRODUCTION_RECIPE_UNSUPPORTED", details={"production_recipe": production_recipe})

    product_id, copy_lane, candidate, session, resolution = await _resolve_copy_identity(
        candidate_id, recipe_kind)
    meta = resolution.metadata if hasattr(resolution, "metadata") else {}

    total_seconds = int(duration_seconds or session.get("duration_seconds") or 0)
    if total_seconds < 1:
        raise CreativeExecutionRecipeError("EXECUTION_RECIPE_DURATION_INVALID",
                                           details={"duration_seconds": total_seconds})
    from agent.services.copy_render_service import _resolve_execution_duration_plan
    try:
        plan = _resolve_execution_duration_plan(total_seconds)
    except ValueError as exc:
        raise CreativeExecutionRecipeError(
            "EXECUTION_RECIPE_DURATION_NOT_REPRESENTABLE", str(exc),
            details={"duration_seconds": total_seconds})
    generation_mode = str(plan.get("generation_mode"))
    orchestration_digest = _identity_digest({k: plan.get(k) for k in sorted(plan)})

    # deterministic governed visual variations (provider-free)
    try:
        visuals = await _avv.resolve_visual_variations(
            product_id, recipe_kind, int(visual_count), avatar_id=avatar_id, seed=seed)
    except _avv.AutoVisualVariationError as exc:
        raise CreativeExecutionRecipeError(exc.code, exc.message, details=exc.details,
                                           status_code=exc.status_code)

    created: list[dict[str, Any]] = []
    for variation in visuals["variations"]:
        vl = _visual_lineage(recipe_kind, variation)
        identity = {
            "schema": RECIPE_SCHEMA_VERSION,
            "product_id": product_id,
            "production_recipe": recipe_kind,
            "candidate_id": candidate_id,
            "copy_text_digest": str(candidate.get("text_digest") or meta.get("text_digest") or ""),
            "visual_variation_fingerprint": vl["visual_variation_fingerprint"],
            "visual_resolver_version": visuals["resolver_version"],
            "requested_total_duration_seconds": total_seconds,
            "generation_mode": generation_mode,
            "pi_snapshot_id": session.get("pi_snapshot_id"),
            "pi_snapshot_version": session.get("pi_snapshot_version"),
            "treatment_id": treatment_id,
        }
        digest = _identity_digest(identity)
        row = {
            "recipe_identity_digest": digest,
            "product_id": product_id,
            "production_recipe": recipe_kind,
            "benefit_id": session.get("benefit_id"),
            "benefit_digest": session.get("benefit_digest"),
            "copy_session_id": str(candidate.get("session_id")),
            "candidate_id": candidate_id,
            "artifact_id": str(candidate.get("artifact_id")),
            "copy_text_digest": identity["copy_text_digest"],
            "copy_source": str(meta.get("authority_kind") or "BENEFIT_COPY_RENDER_V1"),
            "formula_id": session.get("formula_id"),
            "formula_version": session.get("formula_version"),
            "atom_recipe_fingerprint": candidate.get("recipe_fingerprint"),
            "angle_id": candidate.get("angle_id"),
            "hook_id": candidate.get("hook_id"),
            "body_id": candidate.get("body_id"),
            "cta_id": candidate.get("cta_id"),
            "requested_total_duration_seconds": total_seconds,
            "generation_mode": generation_mode,
            "orchestration_digest": orchestration_digest,
            "visual_resolver_version": visuals["resolver_version"],
            "treatment_id": treatment_id,
            "visual_config_json": {**variation, "treatment_id": treatment_id},
            "pi_snapshot_id": session.get("pi_snapshot_id"),
            "pi_snapshot_version": session.get("pi_snapshot_version"),
            "product_truth_digest": session.get("benefit_digest"),
            "compiler_version": None,
            "recipe_schema_version": RECIPE_SCHEMA_VERSION,
            "lineage_json": {
                "copy_metadata": dict(meta),
                "visual_summary": {"unique_capacity": visuals["unique_capacity"],
                                   "controlled_reuse_count": visuals["controlled_reuse_count"]},
                "reuse": bool(variation.get("reuse")),
                "reuse_reason": variation.get("reuse_reason"),
            },
            **vl,
        }
        created.append(await _crud.get_or_create_recipe(row))

    return {
        "product_id": product_id,
        "production_recipe": recipe_kind,
        "copy_lane": copy_lane,
        "candidate_id": candidate_id,
        "requested_count": int(visual_count),
        "unique_visual_capacity": visuals["unique_capacity"],
        "controlled_reuse_count": visuals["controlled_reuse_count"],
        "recipes": created,
    }


async def compile_execution_recipe(recipe_id: str) -> dict[str, Any]:
    """Compile a recipe into an immutable prompt snapshot (an existing
    workspace_execution_package). Provider-free. Idempotent: a FINALIZED recipe
    returns its frozen snapshot unchanged (exact replay)."""
    recipe = await _crud.get_recipe(recipe_id)
    if recipe is None:
        raise CreativeExecutionRecipeError("EXECUTION_RECIPE_NOT_FOUND",
                                           details={"recipe_id": recipe_id}, status_code=404)
    if str(recipe.get("status")) == "FINALIZED":
        return {"recipe": recipe, "reused": True,
                "workspace_execution_package_id": recipe.get("workspace_execution_package_id"),
                "prompt_fingerprint": recipe.get("prompt_fingerprint")}

    production_recipe = str(recipe.get("production_recipe"))
    copy_lane = PRODUCTION_RECIPE_TO_COPY_LANE[production_recipe]
    product_id = str(recipe.get("product_id"))
    candidate_id = str(recipe.get("candidate_id"))
    total_seconds = int(recipe.get("requested_total_duration_seconds") or 0)

    from agent.services import faceless_lane_service as fl
    from agent.services.copy_render_service import _resolve_execution_duration_plan
    from agent.services.workspace_execution_package_service import (
        CopyBindingError, create_workspace_execution_package)

    plan = _resolve_execution_duration_plan(total_seconds)
    generation_mode = str(plan.get("generation_mode"))
    block_duration = int(plan.get("engine_block_duration_seconds") or total_seconds)
    requested_total = total_seconds if generation_mode == "EXTEND" else None
    session = await _cr.get_session(str(recipe.get("copy_session_id"))) or {}
    visual = recipe.get("visual_config_json") or {}
    descriptor = visual.get("descriptor") or {}

    kwargs: dict[str, Any] = dict(
        product_id=product_id, mode=fl.FACELESS_TRANSPORT_MODE, duration_seconds=block_duration,
        aspect_ratio="9:16", model=str(plan.get("model")), manual_override=False,
        generation_mode=generation_mode,
        target_language=str(session.get("target_language") or "BM_MS"),
        wps_mode=str(session.get("wps_mode") or "SWEET"),
        engine_duration_target="GOOGLE_FLOW", requested_total_duration_seconds=requested_total,
        copy_fallback_confirmed=False, source_mode=fl.FACELESS_SOURCE_MODE,
        copy_v2_context={"lane": copy_lane, "benefit_copy_render": {"candidate_id": candidate_id}},
    )
    if production_recipe == "HYBRID":
        kwargs.update(
            character_presence="VISIBLE_CREATOR",
            avatar_id=recipe.get("avatar_id"),
            scene_template=descriptor.get("scene_template"),
            camera_preset=descriptor.get("camera_preset"),
        )
    else:  # FACELESS or MONTAGE (presenter-free) — bind the resolved faceless scene identity
        vidx = int(visual.get("variation_index") or 0)
        try:
            scene_authority = await fl.resolve_faceless_scene_authority(
                product_id=product_id, hook_id="AUTO", background_id="AUTO",
                actor_profile="AUTO", variation_index=vidx)
            faceless_resolution = fl.build_faceless_resolution(
                product_id=product_id, actor_profile="AUTO", hook_id="AUTO",
                background_id="AUTO", scene_authority=scene_authority)
        except Exception as exc:  # noqa: BLE001 - surface a deterministic compile blocker
            raise CreativeExecutionRecipeError(
                "EXECUTION_RECIPE_VISUAL_UNRESOLVED",
                f"{type(exc).__name__}: {exc}", details={"recipe_id": recipe_id})
        kwargs.update(
            character_presence=fl.FACELESS_CHARACTER_PRESENCE, avatar_id=None,
            faceless_resolution=faceless_resolution,
        )
        if production_recipe == "MONTAGE":
            kwargs.update(product_presence_type="PRODUCT_MASCOT")

    try:
        pkg = await create_workspace_execution_package(**kwargs)
    except CopyBindingError as exc:
        raise CreativeExecutionRecipeError(getattr(exc, "code", "EXECUTION_RECIPE_COMPILE_BLOCKED"),
                                           str(exc), details={"recipe_id": recipe_id},
                                           status_code=getattr(exc, "status_code", 409))

    wep_id = str(pkg.get("workspace_execution_package_id") or "")
    prompt_fingerprint = str(pkg.get("prompt_fingerprint") or "")
    snapshot = {
        "workspace_execution_package_id": wep_id,
        "prompt_fingerprint": prompt_fingerprint,
        "canonical_package_fingerprint": pkg.get("canonical_package_fingerprint"),
        "compiler_version": pkg.get("compiler_version"),
        "execution_allowed": bool(pkg.get("execution_allowed")),
        "blockers": pkg.get("blockers") or [],
        "generation_mode": pkg.get("generation_mode"),
        "total_duration_seconds": pkg.get("total_duration_seconds"),
    }
    finalized = await _crud.bind_prompt_snapshot(
        recipe_id, workspace_execution_package_id=wep_id,
        prompt_fingerprint=prompt_fingerprint, prompt_snapshot=snapshot)
    return {"recipe": finalized, "reused": False,
            "workspace_execution_package_id": wep_id,
            "prompt_fingerprint": prompt_fingerprint,
            "execution_allowed": snapshot["execution_allowed"],
            "blockers": snapshot["blockers"]}


async def remix_execution_recipe(recipe_id: str, *, seed: str,
                                 visual_count: int = 1) -> dict[str, Any]:
    """Remix an existing recipe: SAME copy identity, NEW governed visual variation(s).
    No copy-provider call."""
    src = await _crud.get_recipe(recipe_id)
    if src is None:
        raise CreativeExecutionRecipeError("EXECUTION_RECIPE_NOT_FOUND",
                                           details={"recipe_id": recipe_id}, status_code=404)
    return await create_execution_recipes(
        candidate_id=str(src.get("candidate_id")),
        production_recipe=str(src.get("production_recipe")),
        visual_count=int(visual_count),
        duration_seconds=int(src.get("requested_total_duration_seconds") or 0),
        avatar_id=src.get("avatar_id"),
        treatment_id=src.get("treatment_id"),
        seed=seed,
    )


async def get_execution_recipe(recipe_id: str) -> dict[str, Any] | None:
    return await _crud.get_recipe(recipe_id)


async def list_execution_recipes(*, candidate_id: str | None = None,
                                 product_id: str | None = None,
                                 production_recipe: str | None = None) -> list[dict[str, Any]]:
    return await _crud.list_recipes(candidate_id=candidate_id, product_id=product_id,
                                    production_recipe=production_recipe)
