"""Credit-free compiler adapters for P6 production items."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.db import creative_production_crud as p6db
from agent.models.creative_production import PlanActionRequest
from agent.models.poster_prompt_draft import PosterPromptDraftRequest
from agent.services import workspace_generation_package_service as wgp_service
from agent.services.creative_production_plan_service import (
    CreativeProductionError,
    _decode_row,
    _loads,
    _now,
    _require_plan,
    _stable_json,
    mark_compilation_ready,
    record_audit_event,
)
from agent.services.poster_prompt_draft_service import PosterPromptDraftService


def _prompt_sha(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


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
    aspect = str(execution_policy.get("aspect") or "9:16")
    logical_mode = str(plan["logical_mode"])
    workspace_execution_package_id: str | None = None
    if generation_mode == "EXTEND":
        try:
            execution_package = (
                await wgp_service._create_bulk_extend_execution_package(
                    item_index=int(item["item_ordinal"]),
                    product_id=str(item["product_id"]),
                    logical_mode=logical_mode,
                    source_mode=(
                        "FRAMES"
                        if logical_mode == "F2V"
                        else logical_mode
                        if logical_mode in {"T2V", "HYBRID"}
                        else None
                    ),
                    generation_mode="EXTEND",
                    duration_seconds=engine_block_duration,
                    requested_total_duration_seconds=total_duration,
                    target_language="BM_MS",
                    model=str(dimensions["model_key"]),
                    aspect=aspect,
                    copy_set_id=str(dimensions.get("copy_set_id") or ""),
                    start_frame_asset_id=(
                        dimensions.get("finished_frame_asset_id") or None
                    ),
                    product_reference_asset_id=(
                        dimensions.get("product_reference_asset_id") or None
                    ),
                    character_reference_asset_id=(
                        dimensions.get("character_asset_id") or None
                    ),
                    scene_context_reference_asset_id=(
                        dimensions.get("scene_asset_id") or None
                    ),
                )
            )
        except ValueError as exc:
            raise CreativeProductionError(
                "EXTEND_EXECUTION_PACKAGE_BLOCKED",
                "The existing durable Extend planner refused this item.",
                details={"item_id": item["item_id"], "detail": str(exc)},
            ) from exc
        workspace_execution_package_id = str(
            execution_package["workspace_execution_package_id"]
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
            start_frame_asset_id=(
                dimensions.get("product_reference_asset_id") or None
            ),
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
            product_reference_asset_id=(
                dimensions.get("product_reference_asset_id") or None
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
    video_job_plan: dict[str, Any] | None = None
    if generation_mode == "EXTEND":
        from agent.api.flow import (
            VideoJobPlanRequest,
            _VIDEO_ASPECT_TO_RATIO,
            _plan_video_job,
        )

        aspect_ratio = next(
            (
                enum
                for enum, ratio in _VIDEO_ASPECT_TO_RATIO.items()
                if ratio == aspect
            ),
            None,
        )
        if not aspect_ratio:
            raise CreativeProductionError(
                "EXTEND_UNSUPPORTED_ASPECT",
                f"The durable Extend lane does not support aspect {aspect}.",
            )
        video_job_plan = await _plan_video_job(
            VideoJobPlanRequest(
                product_id=str(item["product_id"]),
                execution_package_id=workspace_execution_package_id,
                requested_total_duration_seconds=total_duration,
                model=str(dimensions["model_key"]),
                aspect_ratio=aspect_ratio,
                client_request_nonce=str(
                    package["workspace_generation_package_id"]
                ),
            ),
            trust_client_authority=False,
        )
        if not str(video_job_plan.get("job_id") or "") or not str(
            video_job_plan.get("plan_fingerprint") or ""
        ):
            raise CreativeProductionError(
                "EXTEND_VIDEO_JOB_PLAN_INCOMPLETE",
                "The durable /video-jobs planner returned no complete identity.",
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
            "video_job_id": (
                video_job_plan.get("job_id") if video_job_plan else None
            ),
            "video_job_plan_fingerprint": (
                video_job_plan.get("plan_fingerprint")
                if video_job_plan
                else None
            ),
            "status": package.get("status"),
        },
    )


async def _compile_image(
    item: dict[str, Any],
    plan: dict[str, Any],
    dimensions: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    package = await wgp_service.create_img_generation_package(
        product_id=item["product_id"],
        generation_mode="SINGLE",
        subject_asset_id=(
            dimensions.get("product_reference_asset_id") or None
        ),
        scene_context_asset_id=dimensions.get("scene_asset_id") or None,
        style_asset_id=dimensions.get("style_asset_id") or None,
        operator_notes=(
            "P6 immutable content-matrix item "
            f"{item['item_id']} DNA {item['creative_dna_sha256']}"
        ),
        batch_run_id=plan["plan_id"],
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
        },
    )


async def _compile_poster(
    item: dict[str, Any],
    dimensions: dict[str, Any],
) -> tuple[None, str, dict[str, Any]]:
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
        )
    )
    package = response.model_dump(mode="json")
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
    for item in items:
        if item["status"] in {"COMPILED", "PENDING_APPROVAL"}:
            compiled += 1
            continue
        dimensions = _loads(item.get("creative_dimensions_json"), {})
        try:
            media_type = str(item["media_type"])
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
