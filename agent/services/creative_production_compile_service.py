"""Credit-free compiler adapters for P6 production items."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.db import creative_production_crud as p6db
from agent.models.creative_production import PlanActionRequest
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
    resolve_copy_execution_binding,
)


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _plan_copy_v2_context(plan: dict[str, Any]) -> dict[str, Any] | None:
    pool = _loads(plan.get("pool_snapshot_json"), {})
    context = pool.get("copy_v2_context") if isinstance(pool, dict) else None
    return context if isinstance(context, dict) else None


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
    aspect = str(execution_policy.get("aspect") or "9:16")
    logical_mode = str(plan["logical_mode"])
    treatment = await resolve_item_treatment(dimensions, plan)
    segment_plan = treatment.get("segment_plan") or []
    if generation_mode == "EXTEND" and not isinstance(segment_plan, dict):
        raise CreativeProductionError(
            "TREATMENT_SEGMENT_PLAN_INVALID",
            "Governed EXTEND compilation requires immutable segment lineage.",
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
            generation_mode="EXTEND",
            requested_total_duration_seconds=total_duration,
            source_mode=str(
                treatment["compatibility_profile"].get("source_mode") or ""
            ) or None,
            copy_set_id=treatment["copy_set_id"],
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
        "requested_total_duration_seconds": (
            total_duration if generation_mode == "EXTEND" else None
        ),
        "batch_run_id": plan["plan_id"],
        "copy_set_id": dimensions.get("copy_set_id") or None,
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
            "final_prompt_text": prompt,
            "logical_mode": logical_mode,
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
            "treatment_lineage": {
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
            },
            "compiled_shot_grammar": treatment["shot_grammar"],
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
    v2_resolution = None
    if copy_v2_context is not None:
        try:
            v2_resolution = resolve_copy_execution_binding(
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
            "copy_source": "APPROVED_COPY_SET",
            "copy_fallback_confirmed": False,
            "poster_copy_set_id": "",
        }
    response = await PosterPromptDraftService.build_draft(
        PosterPromptDraftRequest(
            product_id=item["product_id"],
            poster_objective=dimensions.get("marketing_angle") or "",
            hook=dimensions.get("hook") or "",
            cta=dimensions.get("cta") or "",
            copy_source="APPROVED_COPY_SET",
            poster_copy_set_id=dimensions.get("copy_set_id") or "",
            poster_recipe_id=dimensions.get("layout_id") or "",
            operator_notes=(
                "P6 immutable content-matrix item "
                f"{item['item_id']} DNA {item['creative_dna_sha256']}"
            ),
            **poster_fields,
        )
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
