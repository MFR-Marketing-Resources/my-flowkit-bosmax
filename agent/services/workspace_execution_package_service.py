from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from agent.db import crud
from agent.services.approved_product_package_service import (
    get_approved_product_package,
    normalize_mode,
)
from agent.services.copy_binding_service import (
    COPY_FALLBACK_CONFIRMATION_SOURCE,
    COPY_FALLBACK_POLICY,
    ERR_PRODUCTION_VALID_COPY_REQUIRED,
    CopyBindingError,
    resolve_compiler_copy_intelligence,
)
from agent.services.copy_execution_resolver import (
    CopyExecutionResolution,
    CopyExecutionResolutionError,
    copy_v2_handoff_context,
    lane_for_request,
    resolve_persisted_copy_execution_binding,
)
from agent.models.copy_blueprint_v2 import legacy_copy_maintenance_enabled
from agent.services.claim_safe_rewrite_service import get_stored_claim_safe_package
from agent.services.product_intelligence import enrich_product
from agent.services.production_prompt_approval_service import scan_prompt_text
from agent.services.prompt_compiler_runtime_config_service import get_runtime_config
from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)
from agent.services.i2v_semantic_slot_resolver_service import (
    resolve_i2v_semantic_slots,
)
from agent.services.creative_asset_service import (
    _asset_has_resolvable_source,
    build_resolved_workspace_asset,
    validate_selectable_asset,
)
from agent.models.i2v_semantic_slot_resolver import (
    I2VSemanticSlotResolverRequest,
)


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _workspace_execution_package_id(
    product_id: str,
    mode: str,
    prompt_fingerprint: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str,
    manual_override: bool,
    generation_mode: str,
    target_language: str,
    camera_style: str,
    character_presence: str,
    asset_fingerprints: list[str],
) -> str:
    # asset_fingerprints are part of the package identity: two packages with
    # different operator-selected reference bindings must never share one id
    # (a same-id create_or_replace silently swapped resolved assets under an
    # already-planned job's execution_package_id — PR#338 regression).
    digest = _fingerprint(
        product_id,
        mode,
        prompt_fingerprint,
        str(duration_seconds),
        aspect_ratio,
        model,
        str(manual_override).lower(),
        generation_mode,
        target_language,
        camera_style,
        character_presence,
        "|".join(asset_fingerprints),
    )
    return f"wep_{digest[:16]}"


def _resolved_assets(asset_slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [slot["resolved_asset"] for slot in asset_slots if slot.get("resolved_asset")]


def _merge_i2v_resolved_assets(
    asset_slots: list[dict[str, Any]],
    resolver_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    resolved_by_slot = {
        item["slot_key"]: {
            "asset_id": item["asset_id"],
            "asset_fingerprint": item.get("asset_fingerprint"),
            "slot_key": item["slot_key"],
            "asset_source": item.get("asset_source"),
            "label": item.get("display_name"),
            "file_name": item.get("asset_id"),
            "preview_url": item.get("preview_url"),
            "download_url": item.get("download_url"),
            "media_id": item.get("media_id"),
            "local_file_path": item.get("local_file_path"),
            "preview_renderable_status": "RENDERABLE" if item.get("preview_url") else "NOT_AVAILABLE",
            "preview_error_detail": None if item.get("preview_url") else "Preview URL is not available.",
            "local_image_path_present": item.get("local_image_path_present"),
            "remote_image_url_present": item.get("remote_image_url_present"),
        }
        for item in resolver_payload.get("resolved_assets", [])
    }
    merged = copy.deepcopy(asset_slots)
    for slot in merged:
        slot_key = slot.get("slot_key")
        if slot_key in resolved_by_slot:
            slot["resolved_asset"] = resolved_by_slot[slot_key]
            slot["default_source"] = resolved_by_slot[slot_key].get("asset_source") or slot.get("default_source")
    return merged


async def _bind_f2v_reference_assets(
    asset_slots: list[dict[str, Any]],
    *,
    product_id: str,
    source_mode: str | None,
    product_reference_asset_id: str | None,
    start_frame_asset_id: str | None,
    end_frame_asset_id: str | None,
) -> list[dict[str, Any]]:
    """Bind operator-selected F2V reference slots with server-validated assets.

    HYBRID: the Product Registration Official Product Visual in the approved
    package's own product anchor (start_frame slot) is the sole authority.
    Product reference and start-frame overrides are ignored so a P6/creative
    asset cannot reintroduce cosmetic product imagery. FRAMES: an explicit
    start frame is REQUIRED (end frame
    optional) — the raw product image is never a silent stand-in for a finished
    composite frame. Every explicit selection is validated server-side: role,
    mode, slot, approval, rendered-text ban, product ownership, and
    resolvable media source (media_id OR local/preview/download/remote URL —
    same contract as _asset_has_resolvable_source / eligibility audit).
    """
    normalized_source_mode = str(source_mode or "").upper()
    selected_slots: list[tuple[str, str, str]] = []
    if normalized_source_mode == "HYBRID":
        if end_frame_asset_id:
            raise ValueError("HYBRID_END_FRAME_OVERRIDE_NOT_ALLOWED")
        # All product-reference overrides are intentionally ignored. The
        # package's resolved Product Registration visual stands as the only
        # effective HYBRID product anchor.
    if normalized_source_mode == "FRAMES":
        if not start_frame_asset_id:
            raise ValueError("FRAMES_START_FRAME_REFERENCE_REQUIRED")
        selected_slots.append(("start_frame", start_frame_asset_id, "COMPOSITE_FRAME_REFERENCE"))
        if end_frame_asset_id:
            selected_slots.append(("end_frame", end_frame_asset_id, "COMPOSITE_FRAME_REFERENCE"))

    merged = copy.deepcopy(asset_slots)
    for slot_key, asset_id, semantic_role in selected_slots:
        validation = await validate_selectable_asset(
            asset_id,
            semantic_role=semantic_role,
            allowed_mode="F2V",
            engine_slot=slot_key,  # type: ignore[arg-type]
            disallow_rendered_text=True,
            require_approved=True,
        )
        blockers = list(validation.blockers)
        asset = validation.asset
        if asset is not None:
            if asset.product_id and asset.product_id != product_id:
                blockers.append("WRONG_PRODUCT")
            if not _asset_has_resolvable_source(asset):
                blockers.append("MEDIA_IDENTITY_MISSING")
        if asset is None or blockers:
            raise ValueError(
                f"{slot_key.upper()}_REFERENCE_INVALID:{','.join(blockers)}"
            )
        resolved_asset = build_resolved_workspace_asset(
            asset=asset,
            slot_key=slot_key,
        )
        resolved_asset["semantic_role"] = semantic_role
        for slot in merged:
            if slot.get("slot_key") == slot_key:
                slot["resolved_asset"] = resolved_asset
                slot["default_source"] = resolved_asset["asset_source"]
                break
    return merged


def _default_model_for_mode(mode: str) -> str:
    if mode == "IMG":
        return "Nano Banana 2"
    if mode == "T2V":
        return "Veo 3.1 - Pro"
    return "Veo 3.1 - Lite"


def _compile_img_workspace_prompt_preview(
    *,
    product_id: str,
    mode: str,
    duration_seconds: int,
    generation_mode: str,
    target_language: str,
    camera_style: str,
    character_presence: str,
    creator_persona: str,
    approved_package: dict[str, Any],
) -> dict[str, Any]:
    image_prompt = str(
        approved_package.get("image_prompt")
        or approved_package.get("prompt_text")
        or ""
    )
    metadata_handoff = copy.deepcopy(approved_package.get("metadata_handoff") or {})
    overlay_spec = copy.deepcopy(approved_package.get("overlay_spec") or {})
    export_spec = copy.deepcopy(approved_package.get("export_spec") or {})
    return {
        "final_compiled_prompt_text": image_prompt,
        "prompt_blocks": [
            {
                "block_id": "block_1",
                "block_index": 1,
                "block_role": "IMAGE_SINGLE",
                "duration_seconds": duration_seconds,
                "shot_count": 1,
                "dialogue_word_budget": 0,
                "continuation_from_block_id": None,
                "compiled_prompt_text": image_prompt,
                "shot_plan": ["Frame 1: Single-image render only."],
            }
        ],
        "compiler_version": "img_prompt_compiler_v1",
        "generation_mode": generation_mode,
        "total_duration_seconds": duration_seconds,
        "camera_style": camera_style,
        "character_presence": character_presence,
        "creator_persona": creator_persona,
        "target_language": target_language,
        "shot_plan": [
            {
                "block_index": 1,
                "shot_count": 1,
                "shots": ["Frame 1: Single-image render only."],
            }
        ],
        "dialogue_word_budget_per_block": [],
        "prompt_fingerprint": _fingerprint(image_prompt),
        "warnings": list(approved_package.get("warnings") or []),
        "blockers": [],
        "source_of_truth_notes": [
            "IMG compiler separates image prompt from metadata handoff, overlay policy, and export spec.",
        ],
        "continuation_lineage": [],
        "runtime_config_snapshot": get_runtime_config(),
        "product_id": product_id,
        "mode": mode,
        "metadata_handoff": metadata_handoff,
        "overlay_spec": overlay_spec,
        "export_spec": export_spec,
        "image_route": approved_package.get("image_route"),
    }


async def create_workspace_execution_package(
    product_id: str,
    mode: str,
    duration_seconds: int,
    aspect_ratio: str,
    model: str,
    manual_override: bool,
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    recipe_id: str = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
    product_reference_asset_id: str | None = None,
    start_frame_asset_id: str | None = None,
    end_frame_asset_id: str | None = None,
    character_reference_asset_id: str | None = None,
    scene_context_reference_asset_id: str | None = None,
    style_reference_asset_id: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    source_mode: str | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    copy_set_id: str | None = None,
    copy_fallback_confirmed: bool = False,
    avatar_id: str | None = None,
    scene_context_override: str | None = None,
    scene_context_code: str | None = None,
    creative_treatment: dict[str, Any] | None = None,
    # Recipe descriptors (Step F), pre-resolved by the route to keep this file free of
    # any creative-service import. Absent -> compiler unchanged.
    scene_template: dict[str, Any] | None = None,
    camera_preset: dict[str, Any] | None = None,
    copy_v2_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)
    try:
        v2_resolution = await resolve_persisted_copy_execution_binding(
            product_id,
            str((copy_v2_context or {}).get("lane") or lane_for_request(normalized_mode, source_mode=source_mode)),
            copy_v2_context,
        )
    except CopyExecutionResolutionError as exc:
        raise CopyBindingError(exc.code, status_code=exc.status_code, detail=exc.details or str(exc)) from exc
    v2_enabled = v2_resolution.v2_enabled
    if copy_set_id and not legacy_copy_maintenance_enabled():
        raise CopyBindingError(
            "LEGACY_COPY_STORAGE_DISABLED",
            status_code=410,
            detail="Client-selected legacy CopySet IDs are disabled; the persisted V2 binding is authoritative.",
        )
    # Preserve the existing flag-off production-copy gate exactly. V2-enabled
    # video requests never reach this branch: they carry a validated V2 binding.
    if normalized_mode != "IMG" and not copy_set_id and not v2_enabled:
        raise CopyBindingError(
            ERR_PRODUCTION_VALID_COPY_REQUIRED,
            status_code=409,
            detail=(
                "Generate Final Prompt for video modes requires a currently "
                "production-valid approved Copy Set."
            ),
        )
    package = await get_approved_product_package(product_id, mode)
    # Resolve the source lineage from the RAW mode BEFORE normalization, so a
    # caller-named canonical lineage (e.g. mode="FRAMES") is preserved into the
    # SAVED package instead of flipping to HYBRID. Without this, preview
    # (raw mode) and the stored execution package (normalized to "F2V") could
    # disagree on lineage — a silent preview-vs-final flip (2026-07-09 audit).
    resolved_source_mode = _resolve_preview_source_mode(mode, source_mode)
    resolved_model = model or _default_model_for_mode(normalized_mode)
    compiler_result = await compile_workspace_prompt_preview(
        product_id=product_id,
        mode=normalized_mode,
        duration_seconds=duration_seconds,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        blocks=blocks or [],
        approved_package=package,
        source_mode=resolved_source_mode,
        engine_duration_target=engine_duration_target,
        requested_total_duration_seconds=requested_total_duration_seconds,
        avatar_id=avatar_id,
        scene_context_override=scene_context_override,
        copy_set_id=copy_set_id,
        copy_v2_resolution=v2_resolution if v2_enabled else None,
        approved_dialogue=(v2_resolution.approved_dialogue if v2_enabled else None),
        creative_treatment=creative_treatment,
        scene_template=scene_template,
        camera_preset=camera_preset,
    )
    copy_binding_lineage = compiler_result.get("copy_binding")
    # Explicit-Fallback-Confirmation V1: when the operator confirmed fallback
    # (no copy_set_id), stamp the confirmation onto the lineage as SEPARATE audit
    # metadata. The fallback is still recorded as NOT_SELECTED / landbank_fallback
    # with the COPY_SET_NOT_SELECTED warning — confirmation never relabels
    # fallback copy as approved copy.
    if copy_binding_lineage is not None and not copy_set_id and copy_fallback_confirmed:
        copy_binding_lineage = {
            **copy_binding_lineage,
            "copy_fallback_confirmed": True,
            "copy_fallback_confirmation_required": True,
            "copy_fallback_confirmation_source": COPY_FALLBACK_CONFIRMATION_SOURCE,
            "copy_fallback_policy": COPY_FALLBACK_POLICY,
        }
    prompt_fingerprint = compiler_result["prompt_fingerprint"]
    total_duration_seconds = int(compiler_result["total_duration_seconds"])
    semantic_slot_resolver: dict[str, Any] | None = None
    package_asset_slots = copy.deepcopy(package["asset_slots"])
    if normalized_mode == "F2V":
        package_asset_slots = await _bind_f2v_reference_assets(
            package_asset_slots,
            product_id=product_id,
            source_mode=resolved_source_mode,
            product_reference_asset_id=product_reference_asset_id,
            start_frame_asset_id=start_frame_asset_id,
            end_frame_asset_id=end_frame_asset_id,
        )
    elif normalized_mode == "I2V":
        semantic_slot_resolver = (
            await resolve_i2v_semantic_slots(
                I2VSemanticSlotResolverRequest(
                    product_id=product_id,
                    recipe_id=recipe_id,
                    product_reference_asset_id=product_reference_asset_id,
                    character_reference_asset_id=character_reference_asset_id,
                    scene_context_reference_asset_id=scene_context_reference_asset_id,
                    style_reference_asset_id=style_reference_asset_id,
                )
            )
        ).model_dump()
        package_asset_slots = _merge_i2v_resolved_assets(
            package_asset_slots,
            semantic_slot_resolver,
        )

    resolved_assets = _resolved_assets(package_asset_slots)
    asset_fingerprints = [
        asset["asset_fingerprint"]
        for asset in resolved_assets
        if asset.get("asset_fingerprint")
    ]
    execution_package_id = _workspace_execution_package_id(
        product_id,
        normalized_mode,
        prompt_fingerprint,
        total_duration_seconds,
        aspect_ratio,
        resolved_model,
        manual_override,
        compiler_result["generation_mode"],
        compiler_result["target_language"],
        compiler_result["camera_style"],
        compiler_result["character_presence"],
        asset_fingerprints,
    )
    request_lineage_payload = {
        "product_id": product_id,
        "mode": normalized_mode,
        "prompt_package_snapshot_id": package["prompt_package_snapshot_id"],
        "workspace_execution_package_id": execution_package_id,
        "prompt_fingerprint": prompt_fingerprint,
        "asset_fingerprints": asset_fingerprints,
        "compiler": {
            "compiler_version": compiler_result["compiler_version"],
            "source_mode": compiler_result.get("source_mode"),
            "generation_mode": compiler_result["generation_mode"],
            "total_duration_seconds": compiler_result["total_duration_seconds"],
            "camera_style": compiler_result["camera_style"],
            "character_presence": compiler_result["character_presence"],
            "creator_persona": compiler_result["creator_persona"],
        "avatar_id": (str(avatar_id).strip() if avatar_id else None),
        "scene_context_code": (str(scene_context_code).strip() if scene_context_code else None),
        "scene_context_override_applied": bool(str(scene_context_override or "").strip()),
            "target_language": compiler_result["target_language"],
            "dialogue_word_budget_per_block": compiler_result["dialogue_word_budget_per_block"],
            "prompt_blocks": compiler_result["prompt_blocks"],
            "shot_plan": compiler_result["shot_plan"],
            "continuation_lineage": compiler_result["continuation_lineage"],
            "warnings": compiler_result["warnings"],
            "planner_result": compiler_result.get("planner_result"),
            "planner_version": compiler_result.get("planner_version"),
            "planner_fingerprint": compiler_result.get("planner_fingerprint"),
            "canonical_package_fingerprint": compiler_result.get("canonical_package_fingerprint"),
        },
    }
    if creative_treatment:
        segment_plan = creative_treatment.get("segment_plan") or {}
        request_lineage_payload["creative_treatment_lineage"] = {
            "treatment_id": creative_treatment.get("treatment_id"),
            "treatment_sha256": creative_treatment.get("treatment_sha256"),
            "visual_fingerprint_sha256": creative_treatment.get(
                "visual_fingerprint_sha256"
            ),
            "format": creative_treatment.get("format"),
            "generation_mode": creative_treatment.get("generation_mode"),
            "segment_plan_sha256": segment_plan.get("segment_plan_sha256")
            if isinstance(segment_plan, dict)
            else None,
            "ordered_segment_sha256s": segment_plan.get(
                "ordered_segment_sha256s", []
            ) if isinstance(segment_plan, dict) else [],
        }
    for key in ("metadata_handoff", "overlay_spec", "export_spec", "image_route"):
        if compiler_result.get(key) is not None:
            request_lineage_payload["compiler"][key] = compiler_result.get(key)
    # Copy Selection & Compiler Binding V1: record the selected-copy lineage at the
    # top level of the request lineage payload (audit only — copy_set_id lives here,
    # never in the engine-facing prompt text).
    if copy_binding_lineage is not None:
        request_lineage_payload["copy_binding"] = copy_binding_lineage
    if v2_enabled:
        v2_metadata = v2_resolution.to_metadata(
            consumer_context=copy_v2_handoff_context(copy_v2_context, v2_resolution)
        )
        request_lineage_payload["copy_architecture_v2"] = v2_metadata
        if v2_resolution.binding is not None:
            request_lineage_payload["copy_execution_binding"] = v2_resolution.binding.model_dump(mode="json")
    if semantic_slot_resolver:
        request_lineage_payload.update(
            {
                "recipe_id": semantic_slot_resolver["recipe_id"],
                "semantic_roles": semantic_slot_resolver["semantic_roles"],
                "engine_slot_mapping": semantic_slot_resolver["engine_slot_mapping"],
                "creative_asset_ids": semantic_slot_resolver["creative_asset_ids"],
                "resolved_assets": semantic_slot_resolver["resolved_assets"],
                "compiler_context_summary": semantic_slot_resolver["compiler_context_summary"],
                "resolver_warnings": semantic_slot_resolver["warnings"],
                "resolver_blockers": semantic_slot_resolver["blockers"],
                "semantic_slot_resolver": semantic_slot_resolver,
            }
        )
    all_blockers = [
        *list(package["blockers"]),
        *(
            list(semantic_slot_resolver["blockers"])
            if semantic_slot_resolver
            else []
        ),
    ]
    readiness = "READY" if not all_blockers else "BLOCKED"
    execution_allowed = readiness == "READY"

    await crud.create_or_replace_workspace_execution_package(
        workspace_execution_package_id=execution_package_id,
        product_id=product_id,
        mode=normalized_mode,
        duration_seconds=total_duration_seconds,
        aspect_ratio=aspect_ratio,
        model=resolved_model,
        manual_override=manual_override,
        prompt_package_snapshot_id=package["prompt_package_snapshot_id"],
        prompt_fingerprint=prompt_fingerprint,
        prompt_text=compiler_result["final_compiled_prompt_text"],
        asset_slots=_json(package_asset_slots),
        resolved_assets=_json(resolved_assets),
        readiness=readiness,
        execution_allowed=execution_allowed,
        production_generation_allowed=package["production_generation_allowed"],
        manual_fallback=_json(package["manual_fallback"]),
        blockers=_json(all_blockers),
        request_lineage_payload=_json(request_lineage_payload),
        source_of_truth_notes=_json(
            [
                *package["source_of_truth_notes"],
                *compiler_result["source_of_truth_notes"],
                *(
                    [f"I2V semantic recipe: {semantic_slot_resolver['recipe_id']}"]
                    if semantic_slot_resolver
                    else []
                ),
            ],
        ),
    )

    result = {
        "workspace_execution_package_id": execution_package_id,
        "product_id": product_id,
        "product_name": package["product_name"],
        "mode": normalized_mode,
        "duration_seconds": total_duration_seconds,
        "aspect_ratio": aspect_ratio,
        "model": resolved_model,
        "manual_override": manual_override,
        "prompt_text": compiler_result["final_compiled_prompt_text"],
        "prompt_fingerprint": prompt_fingerprint,
        "prompt_package_snapshot_id": package["prompt_package_snapshot_id"],
        "asset_slots": package_asset_slots,
        "resolved_assets": resolved_assets,
        "readiness": readiness,
        "execution_allowed": execution_allowed,
        "production_generation_allowed": package["production_generation_allowed"],
        "manual_fallback": package["manual_fallback"],
        "blockers": all_blockers,
        "copy_binding": copy_binding_lineage,
        "request_lineage_payload": request_lineage_payload,
        "source_of_truth_notes": [
            *package["source_of_truth_notes"],
            *compiler_result["source_of_truth_notes"],
            *(
                [f"I2V semantic recipe: {semantic_slot_resolver['recipe_id']}"]
                if semantic_slot_resolver
                else []
            ),
        ],
        "semantic_slot_resolver": semantic_slot_resolver,
        "compiler_version": compiler_result["compiler_version"],
        "source_mode": compiler_result.get("source_mode"),
        "generation_mode": compiler_result["generation_mode"],
        "total_duration_seconds": compiler_result["total_duration_seconds"],
        "camera_style": compiler_result["camera_style"],
        "character_presence": compiler_result["character_presence"],
        "creator_persona": compiler_result["creator_persona"],
        "target_language": compiler_result["target_language"],
        "shot_plan": compiler_result["shot_plan"],
        "dialogue_word_budget_per_block": compiler_result["dialogue_word_budget_per_block"],
        "prompt_blocks": compiler_result["prompt_blocks"],
        "warnings": compiler_result["warnings"],
        "compiler_blockers": compiler_result["blockers"],
        "continuation_lineage": compiler_result["continuation_lineage"],
        "planner_result": compiler_result.get("planner_result"),
        "planner_version": compiler_result.get("planner_version"),
        "planner_fingerprint": compiler_result.get("planner_fingerprint"),
        "canonical_package_fingerprint": compiler_result.get("canonical_package_fingerprint"),
        "runtime_config_snapshot": compiler_result["runtime_config_snapshot"],
        "metadata_handoff": compiler_result.get("metadata_handoff"),
        "overlay_spec": compiler_result.get("overlay_spec"),
        "export_spec": compiler_result.get("export_spec"),
        "image_route": compiler_result.get("image_route"),
    }
    if v2_enabled:
        result["copy_architecture_v2"] = v2_resolution.to_metadata(
            consumer_context=copy_v2_handoff_context(copy_v2_context, v2_resolution)
        )
        if v2_resolution.binding is not None:
            result["copy_execution_binding"] = v2_resolution.binding.model_dump(mode="json")
    return result


def _resolve_preview_source_mode(
    raw_mode: str | None, source_mode: str | None
) -> str | None:
    """Resolve the compile lineage from the caller's mode + source_mode.

    - explicit source_mode wins, but must be a canonical lineage (fail closed);
    - a raw mode that IS a canonical lineage (FRAMES/INGREDIENTS/T2V) pins that
      lineage instead of silently defaulting into the HYBRID branch;
    - ambiguous surface modes (F2V/I2V/IMG) return None so the compiler applies
      its documented per-mode defaults.
    """
    from agent.services.ugc_video_prompt_compiler_service import (
        CANONICAL_SOURCE_MODES,
    )

    resolved = str(source_mode or "").strip().upper() or None
    if resolved is not None:
        if resolved not in CANONICAL_SOURCE_MODES:
            raise ValueError(f"SOURCE_MODE_INVALID:{resolved}")
        return resolved
    raw = str(raw_mode or "").strip().upper()
    if raw in CANONICAL_SOURCE_MODES:
        return raw
    return None


def _source_lineage_default_warning(
    raw_mode: str | None, source_mode: str | None
) -> str | None:
    """Warn when an F2V-surface request will DEFAULT to HYBRID lineage.

    In-app operator surfaces always pin source_mode (OperatorPage.resolveSourceMode),
    so this only fires for EXTERNAL / programmatic callers that send mode=F2V with no
    source_mode. Behaviour is unchanged (the documented HYBRID product-anchor default);
    the warning just makes the otherwise-silent lineage choice visible so a caller who
    meant FRAMES (finished-frame continuation) can correct it.
    """
    if source_mode and str(source_mode).strip():
        return None
    from agent.services.ugc_video_prompt_compiler_service import (
        CANONICAL_SOURCE_MODES,
    )

    raw = str(raw_mode or "").strip().upper()
    if raw in CANONICAL_SOURCE_MODES:
        return None
    if normalize_mode(raw) == "F2V":
        return (
            "SOURCE_MODE_DEFAULTED_TO_HYBRID: mode=F2V without an explicit "
            "source_mode compiles as HYBRID (product-image anchor). Pass "
            "source_mode=FRAMES for finished-frame continuation, or "
            "source_mode=HYBRID to silence this warning."
        )
    return None


async def compile_workspace_prompt_preview(
    *,
    product_id: str,
    mode: str,
    duration_seconds: int,
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    blocks: list[dict[str, Any]] | None = None,
    approved_package: dict[str, Any] | None = None,
    source_mode: str | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    copy_set_id: str | None = None,
    avatar_id: str | None = None,
    scene_context_override: str | None = None,
    creative_treatment: dict[str, Any] | None = None,
    # Recipe descriptors (Step F), pre-resolved by the CALLER (keeps this generation-
    # purity-scoped service free of any creative-service import). Absent -> compiler
    # unchanged.
    scene_template: dict[str, Any] | None = None,
    camera_preset: dict[str, Any] | None = None,
    copy_v2_resolution: CopyExecutionResolution | None = None,
    approved_dialogue: str | None = None,
    copy_v2_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)
    if copy_v2_resolution is None:
        try:
            copy_v2_resolution = await resolve_persisted_copy_execution_binding(
                product_id,
                str((copy_v2_context or {}).get("lane") or lane_for_request(normalized_mode, source_mode=source_mode)),
                copy_v2_context,
            )
        except CopyExecutionResolutionError as exc:
            raise CopyBindingError(
                exc.code,
                status_code=exc.status_code,
                detail=exc.details or str(exc),
            ) from exc
    if copy_v2_resolution.v2_enabled:
        approved_dialogue = copy_v2_resolution.approved_dialogue
    # Source-lineage law (2026-07-09 corrective audit): a caller that names a
    # canonical source mode ("FRAMES"/"INGREDIENTS"/"T2V") keeps that lineage —
    # it must never silently compile as HYBRID. Only the ambiguous surface
    # modes (F2V/I2V) fall through to their documented compiler defaults.
    _lineage_warning = _source_lineage_default_warning(mode, source_mode)
    source_mode = _resolve_preview_source_mode(mode, source_mode)
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    enriched_product = await enrich_product(product, persist=False)
    package = approved_package or await get_approved_product_package(product_id, normalized_mode)
    # Copy Selection & Compiler Binding V1: resolve the operator-selected Copy Set
    # (fail-closed if an explicit copy_set_id is invalid) into clean compiler copy.
    # Only to_compiler_copy fields cross into the compiler; the lineage below is
    # audit-only and never enters the engine-facing prompt text.
    if copy_v2_resolution.v2_enabled:
        copy_binding = {
            "copy_intelligence": copy_v2_resolution.compiler_copy_intelligence or {},
            "lineage": copy_v2_resolution.to_metadata(
                consumer_context=copy_v2_handoff_context(
                    copy_v2_context, copy_v2_resolution
                )
            ),
            "warning": None,
        }
    else:
        copy_binding = await resolve_compiler_copy_intelligence(product_id, copy_set_id)
    if normalized_mode == "IMG":
        compiler_result = _compile_img_workspace_prompt_preview(
            product_id=product_id,
            mode=normalized_mode,
            duration_seconds=duration_seconds,
            generation_mode=generation_mode,
            target_language=target_language,
            camera_style=camera_style,
            character_presence=character_presence,
            creator_persona=creator_persona,
            approved_package=package,
        )
    else:
        safe_package = await get_stored_claim_safe_package(product_id) or {}
        compiler_result = compile_ugc_video_prompt(
            product=enriched_product,
            approved_package=package,
            mode=normalized_mode,
            camera_style=camera_style,
            character_presence=character_presence,
            creator_persona=creator_persona,
            target_language=target_language,
            generation_mode=generation_mode,
            duration_seconds=duration_seconds,
            blocks=blocks or [],
            engine_target=normalized_mode,
            overlay_enabled=overlay_enabled,
            dialogue_enabled=dialogue_enabled,
            claim_safe_rewrite=package.get("claim_safe_rewrite"),
            safe_hook_angles=list(safe_package.get("safe_hook_angles") or []),
            safe_cta_angles=list(safe_package.get("safe_cta_angles") or []),
            source_mode=source_mode,
            engine_duration_target=engine_duration_target,
            requested_total_duration_seconds=requested_total_duration_seconds,
            avatar_id=avatar_id,
            scene_context_override=scene_context_override,
            copy_intelligence=copy_binding["copy_intelligence"],
            approved_dialogue=approved_dialogue,
            creative_treatment=creative_treatment,
            scene_template=scene_template,
            camera_preset=camera_preset,
        )
    prompt_scan = scan_prompt_text(
        compiler_result["final_compiled_prompt_text"],
        product_id=product_id,
    )
    if any(prompt_scan.values()):
        raise ValueError("PACKAGE_SCAN_FAILED")
    compiler_result["runtime_config_snapshot"] = get_runtime_config()
    compiler_result["product_id"] = product_id
    compiler_result["mode"] = normalized_mode
    # Attach safe copy-binding lineage + surface a soft warning when no approved
    # Copy Set was selected (degraded fallback mode). Never fails the compile.
    compiler_result["copy_binding"] = copy_binding["lineage"]
    warnings = list(compiler_result.get("warnings") or [])
    if copy_binding["warning"] and copy_binding["warning"] not in warnings:
        warnings.append(copy_binding["warning"])
    if _lineage_warning and _lineage_warning not in warnings:
        warnings.append(_lineage_warning)
    compiler_result["warnings"] = warnings
    return compiler_result


async def list_workspace_execution_packages(
    *,
    product_id: str | None = None,
    mode: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = await crud.list_workspace_execution_packages(product_id=product_id, mode=normalize_mode(mode) if mode else None, limit=limit)
    items: list[dict[str, Any]] = []
    for row in rows:
        request_lineage_payload = json.loads(row.get("request_lineage_payload") or "{}")
        compiler_lineage = request_lineage_payload.get("compiler") or {}
        items.append(
            {
                "workspace_execution_package_id": row["workspace_execution_package_id"],
                "product_id": row["product_id"],
                "mode": row["mode"],
                "source_mode": compiler_lineage.get("source_mode"),
                "prompt_package_snapshot_id": row.get("prompt_package_snapshot_id"),
                "prompt_fingerprint": row.get("prompt_fingerprint"),
                "readiness": row.get("readiness"),
                "execution_allowed": bool(row.get("execution_allowed")),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "manual_override": bool(row.get("manual_override")),
                "asset_slots": json.loads(row.get("asset_slots") or "[]"),
                "resolved_assets": json.loads(row.get("resolved_assets") or "[]"),
                "manual_fallback": json.loads(row.get("manual_fallback") or "{}"),
                "blockers": json.loads(row.get("blockers") or "[]"),
                "request_lineage_payload": request_lineage_payload,
                "source_of_truth_notes": json.loads(row.get("source_of_truth_notes") or "[]"),
                "prompt_preview": str(row.get("prompt_text") or "")[:240],
                "prompt_text": row.get("prompt_text") or "",
                "prompt_blocks": json.loads(row.get("prompt_blocks_json") or "[]"),
            }
        )
    return items
