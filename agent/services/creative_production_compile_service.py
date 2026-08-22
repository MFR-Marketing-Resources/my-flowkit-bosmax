"""Credit-free compiler adapters for P6 production items."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from agent.db import crud as core_crud
from agent.db import creative_production_crud as p6db
from agent.models.creative_production import PlanActionRequest, ProductionRecipe
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services import workspace_generation_package_service as wgp_service
from agent.services import workspace_execution_package_service as wep_service
from agent.services.creative_production_plan_service import (
    CreativeProductionError,
    _decode_row,
    _loads,
    _now,
    _require_plan,
    _stable_json,
    mark_compilation_ready,
    record_audit_event,
    resolve_item_treatment,
)
from agent.services.poster_prompt_draft_service import PosterPromptDraftService
from agent.services.copy_execution_resolver import (
    CopyExecutionResolutionError,
    resolve_persisted_copy_execution_binding,
)
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled
from agent.services.creative_production_recipe_service import (
    ProductionRecipeError,
    resolve_production_recipe,
)


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _ordered_prompt_sha256s(package: dict[str, Any]) -> list[str]:
    """Hash each ordered engine-facing block carried by a recipe authority."""
    raw_blocks = package.get("prompt_blocks")
    if raw_blocks is None:
        raw_blocks = _loads(package.get("prompt_blocks_json"), [])
    if not isinstance(raw_blocks, list):
        return []
    hashes: list[str] = []
    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        prompt = str(
            block.get("engine_prompt_text")
            or block.get("compiled_prompt_text")
            or ""
        )
        hashes.append(_prompt_sha(prompt))
    return hashes


def _plan_copy_v2_context(plan: dict[str, Any]) -> dict[str, Any] | None:
    pool = _loads(plan.get("pool_snapshot_json"), {})
    context = pool.get("copy_v2_context") if isinstance(pool, dict) else None
    return context if isinstance(context, dict) else None


def _item_round3_selection(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return the exact per-item V2 copy selection persisted by Round 3 allocation.

    Real production items durably carry the manifest selection in
    ``round3_manifest_item_json``.  When present, compile MUST resolve copy from
    THIS exact blueprint revision — not the product-global activation pointer.
    """

    raw = item.get("round3_manifest_item_json")
    if not raw or raw in ("{}", ""):
        return None
    selection = _loads(raw, {})
    if not isinstance(selection, dict) or not selection.get("v2_blueprint_id"):
        return None
    return {
        "v2_blueprint_id": selection.get("v2_blueprint_id"),
        "v2_blueprint_revision": selection.get("v2_blueprint_revision"),
        "v2_approval_snapshot_id": selection.get("v2_approval_snapshot_id"),
    }


def _with_round3_selection(
    copy_v2_context: dict[str, Any] | None,
    item: dict[str, Any],
    *,
    lane: str,
) -> dict[str, Any] | None:
    selection = _item_round3_selection(item)
    if selection is None:
        return copy_v2_context
    base = dict(copy_v2_context) if isinstance(copy_v2_context, dict) else {}
    base["round3_selection"] = selection
    base.setdefault("lane", lane)
    return base


async def _create_p6_execution_bridge(
    *,
    item: dict[str, Any],
    plan: dict[str, Any],
    package: dict[str, Any],
    source_lane: str,
    recipe_metadata: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Persist a P6-readable wrapper around an existing recipe authority.

    Faceless and Montage canonically prepare ``workspace_execution_package``
    rows, while the P6 ledger historically points at a generation package.  A
    thin, deterministic bridge preserves that common attribution without
    recompiling the prompt or creating a second execution authority.
    """

    prompt = str(package.get("prompt_text") or package.get("final_prompt_text") or "")
    if not prompt.strip():
        raise CreativeProductionError(
            "EMPTY_COMPILED_PROMPT",
            "The canonical recipe authority returned an empty prompt.",
        )
    execution_package_id = str(
        package.get("workspace_execution_package_id") or ""
    ).strip()
    if not execution_package_id:
        raise CreativeProductionError(
            "RECIPE_EXECUTION_PACKAGE_REQUIRED",
            "The canonical recipe authority returned no execution package identity.",
        )
    bridge_id = f"p6recipe_{_prompt_sha(item['item_id'] + execution_package_id + str(item.get('staff_id') or ''))[:24]}"
    existing = await core_crud.get_workspace_generation_package(bridge_id)
    if existing is None:
        await core_crud.create_workspace_generation_package(
            bridge_id,
            mode=str(package.get("mode") or "F2V").upper(),
            product_id=str(item["product_id"]),
            staff_id=item.get("staff_id"),
            staff_display_name_snapshot=item.get("staff_display_name_snapshot"),
            product_name_snapshot=str(package.get("product_name_snapshot") or ""),
            source_lane=source_lane,
            prompt_package_snapshot_id=str(
                package.get("prompt_package_snapshot_id") or ""
            ),
            workspace_execution_package_id=execution_package_id,
            generation_mode=str(package.get("generation_mode") or "SINGLE").upper(),
            final_prompt_text=prompt,
            prompt_blocks_json=_stable_json(package.get("prompt_blocks") or []),
            selected_assets_json=_stable_json(
                _loads(package.get("asset_slots"), [])
                if isinstance(package.get("asset_slots"), str)
                else package.get("asset_slots") or package.get("selected_assets") or {}
            ),
            resolved_engine_slots_json=_stable_json(
                package.get("resolved_engine_slots") or {}
            ),
            resolver_output_json=_stable_json(
                {
                    "production_recipe": recipe_metadata.get("production_recipe"),
                    "recipe_adapter": recipe_metadata,
                    "faceless_resolution": package.get("faceless_resolution"),
                    "copy_architecture_v2": package.get("copy_architecture_v2"),
                }
            ),
            image_assets_json=_stable_json(package.get("image_assets") or {}),
            manual_handoff_json=_stable_json(package.get("manual_fallback") or {}),
            dom_handoff_payload_json=_stable_json(
                package.get("dom_handoff_payload")
                or {
                    "settings": {
                        "duration_seconds": package.get("duration_seconds"),
                        "model": package.get("model"),
                        "aspect_ratio": package.get("aspect_ratio"),
                    }
                }
            ),
            blockers_json=_stable_json(package.get("blockers") or []),
            warnings_json=_stable_json(package.get("warnings") or []),
            status=(
                "READY_MANUAL"
                if bool(package.get("execution_allowed"))
                or not package.get("blockers")
                else "BLOCKED"
            ),
            batch_run_id=str(plan["plan_id"]),
        )
    fingerprint = str(
        package.get("prompt_fingerprint") or _prompt_sha(prompt)
    )
    return bridge_id, fingerprint, {
        "kind": "PRODUCTION_RECIPE_EXECUTION_BRIDGE",
        "production_recipe": recipe_metadata.get("production_recipe"),
        "canonical_authority": recipe_metadata.get("canonical_authority"),
        "internal_logical_mode": recipe_metadata.get("internal_logical_mode"),
        "workspace_generation_package_id": bridge_id,
        "workspace_execution_package_id": execution_package_id,
        "final_prompt_text": prompt,
        "prompt_fingerprint": fingerprint,
        "ordered_prompt_sha256s": _ordered_prompt_sha256s(package),
        "wps_mode": package.get("wps_mode"),
        "product_presence_type": package.get("product_presence_type"),
        "actor_contract": package.get("actor_contract"),
        "product_temporal_custody": package.get("product_temporal_custody"),
        "temporal_occupancy": package.get("temporal_occupancy"),
        "shot_handling": package.get("shot_handling"),
        "generation_mode": str(package.get("generation_mode") or "SINGLE").upper(),
        "recipe_execution": recipe_metadata,
        "copy_architecture_v2": package.get("copy_architecture_v2"),
        "status": package.get("status") or package.get("readiness"),
    }


async def _compile_faceless_recipe(
    *,
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
    aspect: str,
    copy_v2_context: dict[str, Any] | None,
    treatment: dict[str, Any] | None,
    generation_mode: str,
    total_duration: int,
    engine_block_duration: int,
) -> tuple[str, str, dict[str, Any]]:
    """Prepare Faceless through its existing lane and WEP authority."""

    from agent.services import faceless_lane_service as faceless

    model = str(dimensions.get("model_key") or "").strip()
    ok, code, detail = faceless.validate_faceless_inputs(
        product_id=str(item["product_id"]),
        hook_id="AUTO",
        background_id="AUTO",
        actor_profile="AUTO",
        model=model,
        generation_mode=generation_mode,
        duration_seconds=engine_block_duration,
        total_duration_seconds=total_duration,
        require_model=True,
        reference_override=False,
    )
    if not ok:
        raise CreativeProductionError(
            str(code or "FACELESS_INPUT_INVALID"),
            str(detail or "Faceless input validation failed."),
        )
    ok_video, code_video, detail_video, orchestration = (
        faceless.resolve_faceless_video_configuration(
            model=model,
            generation_mode=generation_mode,
            duration_seconds=engine_block_duration,
            total_duration_seconds=total_duration,
        )
    )
    if not ok_video or not orchestration:
        raise CreativeProductionError(
            str(code_video or "FACELESS_MODEL_DURATION_INVALID"),
            str(detail_video or "Faceless model/duration is not governed."),
        )
    scene_authority = await faceless.resolve_faceless_scene_authority(
        product_id=str(item["product_id"]),
        hook_id="AUTO",
        background_id="AUTO",
        actor_profile="AUTO",
        scene_context_hint=dimensions.get("scene_strategy_context"),
    )
    resolution = faceless.build_faceless_resolution(
        product_id=str(item["product_id"]),
        hook_id="AUTO",
        background_id="AUTO",
        actor_profile="AUTO",
        scene_context_hint=dimensions.get("scene_strategy_context"),
        scene_authority=scene_authority,
    )
    from agent.services import workspace_execution_package_service as wep_service

    lane_context = (
        {**copy_v2_context, "lane": "FACELESS"}
        if isinstance(copy_v2_context, dict)
        else {"lane": "FACELESS"}
    )
    package = await wep_service.create_workspace_execution_package(
        product_id=str(item["product_id"]),
        mode=str(resolution.get("transport_mode") or faceless.FACELESS_TRANSPORT_MODE),
        duration_seconds=int(orchestration["engine_block_duration_seconds"]),
        aspect_ratio=aspect,
        model=model,
        manual_override=False,
        staff_id=item.get("staff_id"),
        staff_display_name_snapshot=item.get("staff_display_name_snapshot"),
        generation_mode=str(orchestration["generation_mode"]),
        character_presence=faceless.FACELESS_CHARACTER_PRESENCE,
        creator_persona="DEFAULT_CREATOR",
        source_mode=str(resolution.get("source_mode") or faceless.FACELESS_SOURCE_MODE),
        scene_context_override=faceless.build_faceless_scene_context(resolution),
        faceless_resolution=resolution.get("faceless_resolution"),
        requested_total_duration_seconds=(
            total_duration if generation_mode == "EXTEND" else None
        ),
        creative_treatment=treatment,
        copy_v2_context=lane_context,
    )
    if not isinstance(package, dict) or not bool(package.get("execution_allowed")):
        raise CreativeProductionError(
            "FACELESS_PACKAGE_BLOCKED",
            "The canonical Faceless execution package is not ready.",
            details={"blockers": package.get("blockers") if isinstance(package, dict) else []},
        )
    metadata = {
        "production_recipe": ProductionRecipe.FACELESS.value,
        "canonical_authority": "faceless_lane_service + workspace_execution_package_service",
        "internal_logical_mode": "F2V",
        "transport_mode": resolution.get("transport_mode"),
        "source_mode": resolution.get("source_mode"),
        "faceless_resolution": resolution.get("faceless_resolution"),
    }
    return await _create_p6_execution_bridge(
        item=item,
        plan=plan,
        package=package,
        source_lane="FACELESS",
        recipe_metadata=metadata,
    )


def _montage_story_beats(treatment: dict[str, Any] | None) -> list[Any]:
    shots = treatment.get("shot_grammar") if isinstance(treatment, dict) else None
    if isinstance(shots, list) and shots:
        beats: list[Any] = []
        for index, shot in enumerate(shots, start=1):
            if not isinstance(shot, dict):
                continue
            beats.append(
                SimpleNamespace(
                    beat_id=f"treatment-shot-{index}",
                    role="BODY" if index < len(shots) else "CTA",
                    objective=str(shot.get("purpose") or "Approved treatment beat"),
                    visual_action=str(shot.get("subject") or "Product-led scene"),
                )
            )
        if beats:
            return beats
    return [
        SimpleNamespace(
            beat_id="hook",
            role="HOOK",
            objective="Open with product truth",
            visual_action="Hero product plate",
        ),
        SimpleNamespace(
            beat_id="body",
            role="BODY",
            objective="Demonstrate the approved product benefit",
            visual_action="Product in context",
        ),
        SimpleNamespace(
            beat_id="cta",
            role="CTA",
            objective="Close with the approved call to action",
            visual_action="Pack shot and CTA",
        ),
    ]


async def _compile_montage_recipe(
    *,
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
    copy_v2_context: dict[str, Any] | None,
    treatment: dict[str, Any] | None,
    engine_block_duration: int,
) -> tuple[str, str, dict[str, Any]]:
    """Create the durable Montage run through its canonical orchestrator."""

    from agent.services import montage_run_service
    from agent.services import workspace_execution_package_service as wep_service
    from agent.services.montage_scene_reference_policy import SceneReferencePolicy

    model = str(dimensions.get("model_key") or "").strip()
    lane_context = (
        {**copy_v2_context, "lane": "MONTAGE"}
        if isinstance(copy_v2_context, dict)
        else {"lane": "MONTAGE"}
    )
    run = await montage_run_service.create_montage_discrete_run(
        product_id=str(item["product_id"]),
        story_beats=_montage_story_beats(treatment),
        package_factory=wep_service.create_workspace_execution_package,
        default_policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        model=model,
        duration_seconds=engine_block_duration,
        staff_id=item.get("staff_id"),
        staff_display_name_snapshot=item.get("staff_display_name_snapshot"),
        copy_fallback_confirmed=False,
        copy_v2_context=lane_context,
    )
    if not bool(run.get("ok")) or not run.get("montage_run_id"):
        raise CreativeProductionError(
            "MONTAGE_PREPARATION_BLOCKED",
            "The canonical Montage run could not be prepared.",
            details={"run": run},
        )
    scenes = run.get("scenes") or []
    first_scene = next(
        (
            scene
            for scene in scenes
            if str(scene.get("workspace_execution_package_id") or "").strip()
        ),
        None,
    )
    if not isinstance(first_scene, dict):
        raise CreativeProductionError(
            "MONTAGE_SCENE_PACKAGE_REQUIRED",
            "The canonical Montage run returned no prepared scene package.",
        )
    wep = await core_crud.get_workspace_execution_package(
        str(first_scene["workspace_execution_package_id"])
    )
    if not wep:
        raise CreativeProductionError(
            "MONTAGE_SCENE_PACKAGE_NOT_FOUND",
            "The prepared Montage scene package could not be reloaded.",
        )
    metadata = {
        "production_recipe": ProductionRecipe.MONTAGE.value,
        "canonical_authority": "montage_run_service.create_montage_discrete_run",
        "internal_logical_mode": "F2V",
        "montage_run_id": str(run["montage_run_id"]),
        "total_scenes": int(run.get("total_scenes") or len(scenes)),
        "assembly_authority": "montage_run_service.assemble_from_montage_run",
    }
    bridge_package = {
        **wep,
        "prompt_text": first_scene.get("package_prompt") or wep.get("prompt_text"),
        "generation_mode": "SINGLE",
        "recipe_execution": metadata,
    }
    bridge_id, fingerprint, evidence = await _create_p6_execution_bridge(
        item=item,
        plan=plan,
        package=bridge_package,
        source_lane="MONTAGE",
        recipe_metadata=metadata,
    )
    evidence["montage_run_id"] = str(run["montage_run_id"])
    evidence["montage_scene_count"] = int(run.get("total_scenes") or len(scenes))
    return bridge_id, fingerprint, evidence


async def _compile_video(
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    generation_mode = str(
        dimensions.get("generation_mode") or "SINGLE"
    ).upper()
    total_duration = int(dimensions["duration_seconds"])
    engine_block_duration = int(
        dimensions.get("engine_block_duration_seconds") or total_duration
    )
    execution_policy = _loads(plan.get("execution_policy_json"), {})
    copy_v2_context = _plan_copy_v2_context(plan)
    if copy_v2_context is not None:
        copy_v2_context = {**copy_v2_context, "lane": "PRODUCTION_STUDIO_P6"}
    copy_v2_context = _with_round3_selection(
        copy_v2_context, item, lane="PRODUCTION_STUDIO_P6"
    )
    aspect = str(execution_policy.get("aspect") or "9:16")
    logical_mode = str(plan["logical_mode"])
    production_recipe = str(plan.get("production_recipe") or "").strip().upper()
    treatment = await resolve_item_treatment(dimensions, plan)
    segment_plan = (treatment or {}).get("segment_plan") or []
    if treatment and generation_mode == "EXTEND" and not isinstance(segment_plan, dict):
        raise CreativeProductionError(
            "TREATMENT_SEGMENT_PLAN_INVALID",
            "Governed EXTEND compilation requires immutable segment lineage.",
        )

    if production_recipe:
        try:
            recipe_adapter = resolve_production_recipe(production_recipe)
        except ProductionRecipeError as exc:
            raise CreativeProductionError(exc.code, str(exc), status_code=422) from exc
        logical_mode = recipe_adapter.internal_logical_mode
        if recipe_adapter.recipe is ProductionRecipe.FACELESS:
            return await _compile_faceless_recipe(
                item=item,
                plan=plan,
                dimensions=dimensions,
                aspect=aspect,
                copy_v2_context=copy_v2_context,
                treatment=treatment,
                generation_mode=generation_mode,
                total_duration=total_duration,
                engine_block_duration=engine_block_duration,
            )
        if recipe_adapter.recipe is ProductionRecipe.MONTAGE:
            return await _compile_montage_recipe(
                item=item,
                plan=plan,
                dimensions=dimensions,
                copy_v2_context=copy_v2_context,
                treatment=treatment,
                engine_block_duration=engine_block_duration,
            )

    workspace_execution_package_id: str | None = None
    if generation_mode == "EXTEND":
        wep = await wep_service.create_workspace_execution_package(
            product_id=item["product_id"],
            mode=logical_mode,
            duration_seconds=engine_block_duration,
            aspect_ratio=aspect,
            model=str(dimensions["model_key"]),
            manual_override=False,
            staff_id=item.get("staff_id"),
            staff_display_name_snapshot=item.get("staff_display_name_snapshot"),
            generation_mode="EXTEND",
            requested_total_duration_seconds=total_duration,
            wps_mode="SWEET",
            enforce_temporal_contract=True,
            source_mode=str(
                (treatment or {}).get("compatibility_profile", {}).get("source_mode") or ""
            ) or None,
            copy_set_id=(
                treatment.get("copy_set_id")
                if legacy_copy_maintenance_enabled()
                else None
            ),
            avatar_id=dimensions.get("avatar_code") or None,
            scene_context_override=(
                dimensions.get("scene_strategy_context") or None
            ),
            product_reference_asset_id=(
                (dimensions.get("product_reference_asset_id") or None)
                if logical_mode not in {"HYBRID", "I2V"}
                else None
            ),
            start_frame_asset_id=(
                (dimensions.get("finished_frame_asset_id") or None)
                if logical_mode == "F2V"
                else None
            ),
            character_reference_asset_id=(
                dimensions.get("character_asset_id") or None
            ),
            scene_context_reference_asset_id=(
                dimensions.get("scene_asset_id") or None
            ),
            style_reference_asset_id=(
                dimensions.get("style_asset_id") or None
            ),
            creative_treatment=treatment,
            copy_v2_context=copy_v2_context,
        )
        if wep.get("readiness") != "READY" or wep.get("blockers"):
            raise CreativeProductionError(
                "WEP_COMPILATION_BLOCKED",
                "Workspace execution package refused governed EXTEND.",
                details={"blockers": wep.get("blockers") or []},
            )
        workspace_execution_package_id = str(
            wep["workspace_execution_package_id"]
        )

    common: dict[str, Any] = {
        "product_id": item["product_id"],
        "workspace_execution_package_id": workspace_execution_package_id,
        "generation_mode": generation_mode,
        "duration_seconds": engine_block_duration,
        "wps_mode": "SWEET",
        "enforce_temporal_contract": True,
        "requested_total_duration_seconds": (
            total_duration if generation_mode == "EXTEND" else None
        ),
        "batch_run_id": plan["plan_id"],
        "copy_set_id": (
            dimensions.get("copy_set_id") or None
            if legacy_copy_maintenance_enabled()
            else None
        ),
        "scene_context_override": (
            dimensions.get("scene_strategy_context") or None
        ),
        "operator_notes": (
            "P6 immutable content-matrix item "
            f"{item['item_id']} DNA {item['creative_dna_sha256']}"
        ),
        "creative_treatment": treatment,
        "copy_v2_context": copy_v2_context,
    }
    if logical_mode == "T2V":
        package = await wgp_service.create_t2v_generation_package(
            **common,
            avatar_id=dimensions.get("avatar_code") or None,
        )
    elif logical_mode == "HYBRID":
        package = await wgp_service.create_hybrid_generation_package(
            **common,
            avatar_id=dimensions.get("avatar_code") or None,
        )
    elif logical_mode == "F2V":
        package = await wgp_service.create_f2v_generation_package(
            **common,
            source_mode="FRAMES",
            start_frame_asset_id=(
                dimensions.get("finished_frame_asset_id") or None
            ),
        )
    elif logical_mode == "I2V":
        i2v_common = {
            key: value
            for key, value in common.items()
            if key != "duration_seconds"
        }
        package = await wgp_service.create_i2v_generation_package(
            **i2v_common,
            duration_seconds=engine_block_duration,
            character_reference_asset_id=(
                dimensions.get("character_asset_id") or None
            ),
            scene_context_reference_asset_id=(
                dimensions.get("scene_asset_id") or None
            ),
            style_reference_asset_id=(
                dimensions.get("style_asset_id") or None
            ),
        )
    else:
        raise CreativeProductionError(
            "UNSUPPORTED_LOGICAL_MODE",
            f"Unsupported P6 video mode {logical_mode}.",
        )
    blockers = _loads(package.get("blockers_json"), [])
    if package.get("status") == "BLOCKED" or blockers:
        raise CreativeProductionError(
            "WGP_COMPILATION_BLOCKED",
            "Existing workspace package compiler refused the item.",
            details={
                "item_id": item["item_id"],
                "blockers": blockers,
            },
        )
    prompt = str(package.get("final_prompt_text") or "")
    if not prompt.strip():
        raise CreativeProductionError(
            "EMPTY_COMPILED_PROMPT",
            "Existing compiler returned an empty prompt.",
        )
    return (
        str(package["workspace_generation_package_id"]),
        str(package.get("prompt_fingerprint") or _prompt_sha(prompt)),
        {
            "kind": "WORKSPACE_GENERATION_PACKAGE",
            "workspace_generation_package_id": package[
                "workspace_generation_package_id"
            ],
            "prompt_fingerprint": package.get("prompt_fingerprint"),
            "ordered_prompt_sha256s": _ordered_prompt_sha256s(package),
            "wps_mode": package.get("wps_mode"),
            "product_presence_type": package.get("product_presence_type"),
            "actor_contract": package.get("actor_contract"),
            "product_temporal_custody": package.get("product_temporal_custody"),
            "temporal_occupancy": package.get("temporal_occupancy"),
            "shot_handling": package.get("shot_handling"),
            "final_prompt_text": prompt,
            "production_recipe": production_recipe or None,
            "logical_mode": logical_mode,
            "recipe_execution": (
                {
                    "production_recipe": production_recipe,
                    "canonical_authority": (
                        "workspace_generation_package_service.create_hybrid_generation_package"
                        if production_recipe == ProductionRecipe.HYBRID.value
                        else None
                    ),
                    "internal_logical_mode": logical_mode,
                }
                if production_recipe
                else None
            ),
            "generation_mode": generation_mode,
            "requested_total_duration_seconds": total_duration,
            "engine_block_duration_seconds": engine_block_duration,
            "segment_count": int(dimensions.get("segment_count") or 1),
            "execution_route": str(
                dimensions.get("execution_route") or "SINGLE_SHOT_QUEUE"
            ),
            "workspace_execution_package_id": workspace_execution_package_id,
            "video_job_id": None,
            "video_job_plan_fingerprint": None,
            "treatment_lineage": (
                {
                    "treatment_id": treatment["treatment_id"],
                    "treatment_sha256": treatment["treatment_sha256"],
                    "visual_fingerprint_sha256": treatment[
                        "visual_fingerprint_sha256"
                    ],
                    "dependency_hashes": treatment["dependency_hashes"],
                    "variation_group": treatment["variation_group"],
                    "format": treatment["format"],
                    "generation_mode": generation_mode,
                    "segment_plan_sha256": segment_plan.get(
                        "segment_plan_sha256"
                    ) if isinstance(segment_plan, dict) else None,
                    "ordered_segment_sha256s": segment_plan.get(
                        "ordered_segment_sha256s", []
                    ) if isinstance(segment_plan, dict) else [],
                }
                if treatment
                else None
            ),
            "compiled_shot_grammar": treatment["shot_grammar"] if treatment else [],
            "status": package.get("status"),
            "copy_architecture_v2": package.get("copy_architecture_v2"),
            "copy_execution_binding": package.get("copy_execution_binding"),
        },
    )


async def _compile_image(
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    copy_v2_context = _plan_copy_v2_context(plan)
    if copy_v2_context is not None:
        copy_v2_context = {**copy_v2_context, "lane": "IMAGE_GEN"}
    copy_v2_context = _with_round3_selection(copy_v2_context, item, lane="IMAGE_GEN")
    package = await wgp_service.create_img_generation_package(
        product_id=item["product_id"],
        generation_mode="SINGLE",
        scene_context_asset_id=dimensions.get("scene_asset_id") or None,
        style_asset_id=dimensions.get("style_asset_id") or None,
        operator_notes=(
            "P6 immutable content-matrix item "
            f"{item['item_id']} DNA {item['creative_dna_sha256']}"
        ),
        batch_run_id=plan["plan_id"],
        copy_v2_context=copy_v2_context,
        copy_v2_lane="IMAGE_GEN",
    )
    blockers = _loads(package.get("blockers_json"), [])
    if package.get("status") == "BLOCKED" or blockers:
        raise CreativeProductionError(
            "IMG_COMPILATION_BLOCKED",
            "Existing IMG compiler refused the item.",
            details={
                "item_id": item["item_id"],
                "blockers": blockers,
            },
        )
    prompt = str(package.get("final_prompt_text") or "")
    if not prompt.strip():
        raise CreativeProductionError(
            "EMPTY_COMPILED_PROMPT",
            "Existing IMG compiler returned an empty prompt.",
        )
    return (
        str(package["workspace_generation_package_id"]),
        str(package.get("prompt_fingerprint") or _prompt_sha(prompt)),
        {
            "kind": "WORKSPACE_GENERATION_PACKAGE",
            "workspace_generation_package_id": package[
                "workspace_generation_package_id"
            ],
            "prompt_fingerprint": package.get("prompt_fingerprint"),
            "final_prompt_text": prompt,
            "logical_mode": "IMG",
            "status": package.get("status"),
            "copy_architecture_v2": package.get("copy_architecture_v2"),
        },
    )


async def _compile_poster(
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
) -> tuple[None, str, dict[str, Any]]:
    copy_v2_context = _plan_copy_v2_context(plan)
    copy_v2_context = _with_round3_selection(copy_v2_context, item, lane="POSTER_BUILDER")
    try:
        v2_resolution = await resolve_persisted_copy_execution_binding(
            item["product_id"],
            "POSTER_BUILDER",
            copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        raise CreativeProductionError(
            exc.code,
            str(exc),
            status_code=exc.status_code,
            details=exc.details,
        ) from exc
    poster_fields = {}
    if v2_resolution is not None and v2_resolution.v2_enabled:
        derived = v2_resolution.projection.derived_copy
        poster_fields = {
            "hook": derived.hook if derived else "",
            "usp_1": derived.body if derived else "",
            "cta": derived.cta if derived else "",
            "copy_source": "COPY_BLUEPRINT_V2_APPROVED",
            "copy_fallback_confirmed": False,
            "poster_copy_set_id": "",
        }
    draft_values = {
        "product_id": item["product_id"],
        "poster_objective": dimensions.get("marketing_angle") or "",
        "hook": dimensions.get("hook") or "",
        "cta": dimensions.get("cta") or "",
        "copy_source": (
            "APPROVED_COPY_SET"
            if legacy_copy_maintenance_enabled()
            else "COPY_BLUEPRINT_V2_APPROVED"
        ),
        "poster_copy_set_id": (
            dimensions.get("copy_set_id") or ""
            if legacy_copy_maintenance_enabled()
            else ""
        ),
        "poster_recipe_id": dimensions.get("layout_id") or "",
        "operator_notes": (
            "P6 immutable content-matrix item "
            f"{item['item_id']} DNA {item['creative_dna_sha256']}"
        ),
        "copy_v2_context": copy_v2_context,
    }
    draft_values.update(poster_fields)
    response = await PosterPromptDraftService.build_draft(
        PosterPromptDraftRequest(**draft_values)
    )
    package = response.model_dump(mode="json")
    if v2_resolution is not None and v2_resolution.v2_enabled:
        package["copy_architecture_v2"] = v2_resolution.to_metadata(
            consumer_context=copy_v2_context
        )
        package["copy_execution_binding"] = (
            v2_resolution.binding.model_dump(mode="json")
            if v2_resolution.binding is not None
            else None
        )
    else:
        package.pop("copy_architecture_v2", None)
        package.pop("copy_execution_binding", None)
    prompt = str(
        package.get("final_prompt")
        or package.get("prompt")
        or package.get("compiled_prompt")
        or ""
    )
    package_status = str(package.get("status") or "")
    blockers = package.get("blockers") or []
    if package_status == "BLOCKED" or blockers:
        raise CreativeProductionError(
            "POSTER_COMPILATION_BLOCKED",
            "Existing poster compiler refused the item.",
            details={
                "item_id": item["item_id"],
                "blockers": blockers,
            },
        )
    if not prompt:
        prompt = _stable_json(package)
    fingerprint = _prompt_sha(prompt)
    return (
        None,
        fingerprint,
        {
            "kind": "POSTER_PROMPT_DRAFT",
            "prompt_fingerprint": fingerprint,
            "package": package,
            "copy_architecture_v2": package.get("copy_architecture_v2"),
            "copy_execution_binding": package.get("copy_execution_binding"),
        },
    )


async def compile_plan(
    plan_id: str,
    action: PlanActionRequest | None = None,
) -> dict[str, Any]:
    """Compile all planned items without provider or media-credit activity."""

    plan = await _require_plan(plan_id)
    if plan["status"] not in {"PREFLIGHT_READY", "PENDING_APPROVAL"}:
        raise CreativeProductionError(
            "ILLEGAL_PLAN_TRANSITION",
            f"Cannot compile a plan in {plan['status']} state.",
            status_code=409,
        )
    items = await p6db.list_items(plan_id)
    if not items:
        raise CreativeProductionError(
            "CONTENT_MATRIX_EMPTY",
            "Materialize the content matrix before compilation.",
            status_code=409,
        )

    compiled = 0
    failures: list[dict[str, Any]] = []
    treatment_evidence: list[dict[str, Any]] = []
    for item in items:
        dimensions = _loads(item.get("creative_dimensions_json"), {})
        try:
            media_type = str(item["media_type"])
            if media_type == "VIDEO":
                treatment = await resolve_item_treatment(dimensions, plan)
                treatment_evidence.append(
                    {
                        "item_id": item["item_id"],
                        "treatment_id": treatment["treatment_id"],
                        "treatment_sha256": treatment["treatment_sha256"],
                        "visual_fingerprint_sha256": treatment[
                            "visual_fingerprint_sha256"
                        ],
                        "variation_group_id": treatment[
                            "variation_group_id"
                        ],
                        "variation_group_sha256": (
                            treatment.get("variation_group") or {}
                        ).get("group_sha256"),
                    }
                )
            if item["status"] in {"COMPILED", "PENDING_APPROVAL"}:
                compiled += 1
                continue
            if media_type == "VIDEO":
                wgp_id, fingerprint, package = await _compile_video(
                    item,
                    plan,
                    dimensions,
                )
            elif media_type == "IMAGE":
                wgp_id, fingerprint, package = await _compile_image(
                    item,
                    plan,
                    dimensions,
                )
            elif media_type == "POSTER":
                wgp_id, fingerprint, package = await _compile_poster(
                    item,
                    plan,
                    dimensions,
                )
            else:
                raise CreativeProductionError(
                    "UNSUPPORTED_MEDIA_TYPE",
                    f"Unsupported media type {media_type}.",
                )
            await p6db.update_item(
                item["item_id"],
                workspace_generation_package_id=wgp_id,
                prompt_fingerprint=fingerprint,
                prompt_package_json=_stable_json(package),
                status="COMPILED",
                updated_at=_now(),
            )
            compiled += 1
        except Exception as exc:  # noqa: BLE001
            code = (
                exc.code
                if isinstance(exc, CreativeProductionError)
                else "COMPILATION_EXCEPTION"
            )
            failure = {
                "item_id": item["item_id"],
                "code": code,
                "message": str(exc),
            }
            failures.append(failure)
            await p6db.update_item(
                item["item_id"],
                prompt_package_json=_stable_json({"compile_error": failure}),
                status="FAILED",
                updated_at=_now(),
            )

    compile_snapshot = {
        "credit_spend": 0,
        "provider_media_calls": 0,
        "compiled": compiled,
        "failed": len(failures),
        "failures": failures,
        "compiler_authorities": [
            "workspace_generation_package_service",
            "PosterPromptDraftService",
        ],
        "item_treatment_lineage": treatment_evidence,
    }
    await p6db.update_plan(
        plan_id,
        compile_snapshot_json=_stable_json(compile_snapshot),
        blockers_json=_stable_json(failures),
        updated_at=_now(),
    )
    if failures:
        if action is not None:
            await record_audit_event(
                plan_id=plan_id,
                request_id=action.request_id,
                actor_id=action.operator_id,
                action="COMPILE_PLAN",
                source_state=str(plan["status"]),
                target_state=str(plan["status"]),
                evidence={
                    "compiled": compiled,
                    "failed": len(failures),
                    "credit_spend": 0,
                },
            )
        return {
            "plan_id": plan_id,
            **compile_snapshot,
            "status": "COMPILATION_BLOCKED",
        }
    await mark_compilation_ready(plan_id)
    if action is not None:
        await record_audit_event(
            plan_id=plan_id,
            request_id=action.request_id,
            actor_id=action.operator_id,
            action="COMPILE_PLAN",
            source_state=str(plan["status"]),
            target_state="PENDING_APPROVAL",
            evidence={"compiled": compiled, "failed": 0, "credit_spend": 0},
        )
    return {
        "plan_id": plan_id,
        **compile_snapshot,
        "status": "PENDING_APPROVAL",
        "items": [
            _decode_row(row) for row in await p6db.list_items(plan_id)
        ],
    }
