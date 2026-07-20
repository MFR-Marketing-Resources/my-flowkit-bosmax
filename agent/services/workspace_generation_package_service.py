"""Workspace Generation Package service.

Durable final operator handoff package for F2V and I2V modes.

Rules:
- workspace_generation_package is the durable handoff artifact.
- workspace_execution_package remains the compile-time snapshot / readiness gate.
- manual_handoff_ready=True when no blockers.
- dom_handoff_ready MUST remain False in this wave.
- Never mutates product truth rows.
- Never touches Chrome extension runtime or Google Flow DOM.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from agent.db import crud
from agent.services.approved_product_package_service import (
    get_approved_product_package,
    normalize_mode,
)
from agent.services.fastmoss_product_reference_service import (
    FASTMOSS_REFERENCE_BLOCKER,
    is_fastmoss_reference_product_id,
)
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
from agent.services.i2v_semantic_slot_resolver_service import resolve_i2v_semantic_slots
from agent.models.i2v_semantic_slot_resolver import I2VSemanticSlotResolverRequest


def _assert_not_reference_only(product_id: str, product_row: dict[str, Any] | None) -> None:
    """Raise ValueError(REFERENCE_ONLY_PRODUCT) if product is a FastMoss
    reference row that cannot be used for generation package creation.
    Belt-and-suspenders guard — get_approved_product_package also blocks these,
    but explicit early rejection gives a cleaner error path."""
    if is_fastmoss_reference_product_id(product_id):
        raise ValueError(FASTMOSS_REFERENCE_BLOCKER)
    if product_row and product_row.get("reference_only"):
        raise ValueError(FASTMOSS_REFERENCE_BLOCKER)


# ─── Helpers ────────────────────────────────────────────────


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=True)


def _wgp_id(product_id: str, mode: str, source_lane: str, prompt_fp: str) -> str:
    digest = _fingerprint(product_id, mode, source_lane, prompt_fp, str(uuid.uuid4()))
    return f"wgp_{digest[:16]}"


def _normalize_f2v_source_lane(source_mode: str | None) -> str:
    candidate = str(source_mode or "").strip().upper()
    if not candidate:
        # Documented F2V-surface default: product-image anchor = HYBRID intake.
        return "HYBRID"
    if candidate in {"FRAMES", "HYBRID"}:
        return candidate
    # A typo or unknown lane must never silently become HYBRID (2026-07-09
    # corrective audit: silent lineage flips are a prompt-integrity defect).
    raise ValueError(f"SOURCE_MODE_INVALID:{candidate}")


def _build_dom_scaffold(
    *,
    mode: str,
    product_id: str,
    prompt_package_snapshot_id: str,
    workspace_execution_package_id: str | None,
    workspace_generation_package_id: str,
    final_prompt_text: str,
    prompt_blocks: list,
    generation_mode: str,
    asset_map: dict,
    settings: dict,
    semantic_resolution: dict,
    upload_order: list[str],
    blockers: list,
    warnings: list,
    prompt_fingerprint: str,
    asset_fingerprints: list,
    planner_result: dict | None = None,
) -> dict:
    """Build the future DOM payload scaffold. dom_handoff_ready MUST stay False."""
    return {
        "mode": mode,
        "lineage": {
            "product_id": product_id,
            "prompt_package_snapshot_id": prompt_package_snapshot_id,
            "workspace_execution_package_id": workspace_execution_package_id,
            "workspace_generation_package_id": workspace_generation_package_id,
            "prompt_fingerprint": prompt_fingerprint,
            "asset_fingerprints": asset_fingerprints,
        },
        "prompt": {
            "final_text": final_prompt_text,
            "blocks": prompt_blocks,
            "generation_mode": generation_mode,
            "planner_result": planner_result,
        },
        "assets": asset_map,
        "settings": settings,
        "semantic_resolution": semantic_resolution,
        "manual_handoff": {
            "upload_order": upload_order,
        },
        "readiness": {
            "manual_handoff_ready": len(blockers) == 0,
            "dom_handoff_ready": False,  # locked — never set True in this wave
            "blockers": blockers,
            "warnings": warnings,
        },
    }


def _build_manual_handoff(
    *,
    mode: str,
    final_prompt_text: str,
    image_assets: dict,
    upload_order: list[str],
    blockers: list,
    warnings: list,
    planner_result: dict | None = None,
) -> dict:
    """Build the manual operator handoff payload."""
    actions: list[dict] = [
        {"action": "copy_prompt", "label": "Copy Final Prompt", "available": True}
    ]

    for slot_key, asset in image_assets.items():
        if asset:
            label = asset.get("label") or slot_key
            actions.append({
                "action": "open_image",
                "label": f"Open {label}",
                "slot_key": slot_key,
                "preview_url": asset.get("preview_url"),
                "available": bool(asset.get("preview_url")),
            })
            actions.append({
                "action": "download_image",
                "label": f"Download {label}",
                "slot_key": slot_key,
                "download_url": asset.get("download_url"),
                "available": bool(asset.get("download_url")),
            })

    return {
        "copy_prompt_available": True,
        "final_prompt_text": final_prompt_text,
        "upload_order": upload_order,
        "actions": actions,
        "blockers": blockers,
        "warnings": warnings,
        "manual_fallback_ready": len(blockers) == 0,
        "dom_handoff_note": "DOM handoff not enabled in this wave.",
        "storyboard_plan": planner_result,
    }


# ─── F2V Package ─────────────────────────────────────────────


async def create_f2v_generation_package(
    *,
    product_id: str,
    workspace_execution_package_id: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    source_mode: str | None = None,
    blocks: list[dict] | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    start_frame_asset_id: str | None = None,
    start_frame_preview_url: str | None = None,
    start_frame_download_url: str | None = None,
    end_frame_asset_id: str | None = None,
    end_frame_preview_url: str | None = None,
    end_frame_download_url: str | None = None,
    operator_notes: str | None = None,
    batch_run_id: str | None = None,
    avatar_id: str | None = None,
    copy_intelligence: dict | None = None,
    copy_set_id: str | None = None,
    scene_context_override: str | None = None,
) -> dict:
    """Create a durable F2V workspace generation package."""
    mode = "F2V"
    copy_intelligence = await _resolve_bound_copy_intelligence(
        product_id, copy_set_id, copy_intelligence
    )
    resolved_source_lane = _normalize_f2v_source_lane(source_mode)
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))
    if scene_context_override:
        approved = {**approved, "scene_context": scene_context_override}

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    # Compile final prompt via existing UGC compiler (reused — not rewritten)
    compiler_result = compile_ugc_video_prompt(
        product={
            "id": product_id,
            "name": product_name_snapshot or (product_row or {}).get("name", ""),
            "category": (product_row or {}).get("category", ""),
        },
        approved_package=approved,
        mode=mode,
        duration_seconds=duration_seconds,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        source_mode=resolved_source_lane,
        blocks=blocks or [],
        engine_duration_target=engine_duration_target,
        requested_total_duration_seconds=requested_total_duration_seconds,
        avatar_id=avatar_id,
        copy_intelligence=copy_intelligence,
    )

    final_prompt_text: str = compiler_result.get("final_compiled_prompt_text", "")
    prompt_blocks: list = compiler_result.get("prompt_blocks", [])
    prompt_fingerprint: str = compiler_result.get("prompt_fingerprint", _fingerprint(final_prompt_text))

    # Resolve start frame — product image auto-seeds if no operator replacement
    product_image_url = f"/api/products/{product_id}/image"
    start_frame = {
        "slot_key": "start_frame",
        "label": "Start Frame",
        "asset_id": start_frame_asset_id or f"product-image:{product_id}:start_frame",
        "preview_url": start_frame_preview_url or product_image_url,
        "download_url": start_frame_download_url or product_image_url,
        "source": "OPERATOR_SELECTED" if start_frame_asset_id else "PRODUCT_IMAGE_AUTO_SEED",
    }

    end_frame: dict | None = None
    if end_frame_asset_id or end_frame_preview_url:
        end_frame = {
            "slot_key": "end_frame",
            "label": "End Frame",
            "asset_id": end_frame_asset_id,
            "preview_url": end_frame_preview_url,
            "download_url": end_frame_download_url,
            "source": "OPERATOR_SELECTED",
        }

    # Blockers / warnings
    blockers: list = []
    warnings: list = []
    if not final_prompt_text:
        blockers.append("final_prompt_text is empty")

    status = "BLOCKED" if blockers else "READY_MANUAL"

    # Asset map for DOM scaffold
    asset_map = {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "subject": None,
        "scene": None,
        "style": None,
        "product_reference": None,
    }

    # Upload order F2V: Start Frame -> End Frame
    upload_order = ["start_frame"]
    if end_frame:
        upload_order.append("end_frame")

    image_assets = {k: v for k, v in asset_map.items() if v and k in ("start_frame", "end_frame")}
    asset_fingerprints = [_fingerprint(a.get("asset_id", "")) for a in image_assets.values() if a]

    selected_assets = {
        "start_frame": start_frame,
        "end_frame": end_frame,
    }
    resolved_engine_slots = {
        "start_frame": start_frame.get("asset_id"),
        "end_frame": end_frame.get("asset_id") if end_frame else None,
    }
    settings = {
        "duration_seconds": duration_seconds,
        "generation_mode": generation_mode,
        "target_language": target_language,
        "camera_style": camera_style,
        "character_presence": character_presence,
        "creator_persona": creator_persona,
        "overlay_enabled": overlay_enabled,
        "dialogue_enabled": dialogue_enabled,
        "source_mode": resolved_source_lane,
    }

    wgp_id = _wgp_id(product_id, mode, resolved_source_lane, prompt_fingerprint)

    manual_handoff = _build_manual_handoff(
        mode=mode,
        final_prompt_text=final_prompt_text,
        image_assets=image_assets,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        planner_result=compiler_result.get("planner_result"),
    )

    dom_scaffold = _build_dom_scaffold(
        mode=mode,
        product_id=product_id,
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        workspace_generation_package_id=wgp_id,
        final_prompt_text=final_prompt_text,
        prompt_blocks=prompt_blocks,
        generation_mode=generation_mode,
        asset_map=asset_map,
        settings=settings,
        semantic_resolution={},
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        prompt_fingerprint=prompt_fingerprint,
        asset_fingerprints=asset_fingerprints,
        planner_result=compiler_result.get("planner_result"),
    )

    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id=product_id,
        product_name_snapshot=product_name_snapshot,
        source_lane=resolved_source_lane,
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        generation_mode=generation_mode,
        final_prompt_text=final_prompt_text,
        prompt_blocks_json=_json(prompt_blocks),
        selected_assets_json=_json(selected_assets),
        resolved_engine_slots_json=_json(resolved_engine_slots),
        resolver_output_json=_json({}),
        image_assets_json=_json(image_assets),
        manual_handoff_json=_json(manual_handoff),
        dom_handoff_payload_json=_json(dom_scaffold),
        blockers_json=_json(blockers),
        warnings_json=_json(warnings),
        status=status,
        batch_run_id=batch_run_id,
    )

    return _enrich_row(row)


# ─── I2V Package ─────────────────────────────────────────────


async def create_i2v_generation_package(
    *,
    product_id: str,
    workspace_execution_package_id: str | None = None,
    recipe_id: str = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE",
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    product_reference_asset_id: str | None = None,
    character_reference_asset_id: str | None = None,
    scene_context_reference_asset_id: str | None = None,
    style_reference_asset_id: str | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    operator_notes: str | None = None,
    batch_run_id: str | None = None,
    copy_intelligence: dict | None = None,
    copy_set_id: str | None = None,
    scene_context_override: str | None = None,
) -> dict:
    """Create a durable I2V workspace generation package."""
    mode = "I2V"
    copy_intelligence = await _resolve_bound_copy_intelligence(
        product_id, copy_set_id, copy_intelligence
    )
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))
    if scene_context_override:
        approved = {**approved, "scene_context": scene_context_override}

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    # Resolve I2V semantic slots via existing resolver (not rewritten)
    resolver_req = I2VSemanticSlotResolverRequest(
        product_id=product_id,
        recipe_id=recipe_id,
        product_reference_asset_id=product_reference_asset_id,
        character_reference_asset_id=character_reference_asset_id,
        scene_context_reference_asset_id=scene_context_reference_asset_id,
        style_reference_asset_id=style_reference_asset_id,
    )
    # The resolver returns a pydantic I2VSemanticSlotResolverResponse; this
    # function consumed it with dict .get() and a non-existent "resolved_slots"
    # key, so EVERY I2V package creation crashed live ('...object has no
    # attribute get') — I2V was never creatable through this door (the test
    # stubs returned plain dicts, hiding it). Normalize to a dict and read the
    # real field (resolved_assets: [{slot_key, asset_id, ...}]).
    resolver_output = await resolve_i2v_semantic_slots(resolver_req)
    if hasattr(resolver_output, "model_dump"):
        resolver_output = resolver_output.model_dump()

    resolved_slots: list = resolver_output.get("resolved_assets", [])
    resolver_warnings: list = resolver_output.get("warnings", [])
    resolver_blockers: list = resolver_output.get("blockers", [])

    # ADR-008 sovereignty: the resolver's semantic context flows INTO the canonical
    # compile (scene_context) — never appended onto final output after compile.
    _i2v_context = str(resolver_output.get("compiler_context_summary", "") or "")
    if _i2v_context:
        approved = {**approved, "scene_context": " ".join(
            x for x in (str(approved.get("scene_context", "") or ""), _i2v_context) if x)}
    compiler_result = compile_ugc_video_prompt(
        product={
            "id": product_id,
            "name": product_name_snapshot or (product_row or {}).get("name", ""),
            "category": (product_row or {}).get("category", ""),
        },
        approved_package=approved,
        mode=mode,
        duration_seconds=8,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        blocks=[],
        engine_duration_target=engine_duration_target,
        requested_total_duration_seconds=requested_total_duration_seconds,
        copy_intelligence=copy_intelligence,
    )

    base_prompt: str = compiler_result.get("final_compiled_prompt_text", "")
    prompt_blocks: list = compiler_result.get("prompt_blocks", [])

    # ADR-008: no post-compile prompt mutation — the canonical output IS final.
    final_prompt_text = base_prompt

    prompt_fingerprint: str = compiler_result.get("prompt_fingerprint", _fingerprint(final_prompt_text))

    # Map resolved slots to Subject/Scene/Style
    slot_map: dict[str, dict | None] = {"subject": None, "scene": None, "style": None, "product_reference": None}
    for slot in resolved_slots:
        sk = (slot.get("slot_key") or "").lower()
        if "subject" in sk or "character" in sk:
            slot_map["subject"] = slot
        elif "scene" in sk or "context" in sk:
            slot_map["scene"] = slot
        elif "style" in sk or "mood" in sk:
            slot_map["style"] = slot
        elif "product_ref" in sk or "product" in sk:
            slot_map["product_reference"] = slot

    # Product reference auto-loads from product image if not supplied
    if not slot_map["product_reference"]:
        product_image_url = f"/api/products/{product_id}/image"
        slot_map["product_reference"] = {
            "slot_key": "product_reference",
            "label": "Product Reference",
            "asset_id": product_reference_asset_id or f"product-image:{product_id}:product_reference",
            "preview_url": product_image_url,
            "download_url": product_image_url,
            "source": "PRODUCT_IMAGE_AUTO_SEED",
        }

    # Blockers / warnings
    blockers = list(resolver_blockers)
    warnings = list(resolver_warnings)
    if not final_prompt_text:
        blockers.append("final_prompt_text is empty")

    status = "BLOCKED" if blockers else "READY_MANUAL"

    # Upload order I2V: Subject -> Scene -> Style
    upload_order = []
    for slot_key in ("subject", "scene", "style"):
        if slot_map.get(slot_key):
            upload_order.append(slot_key)

    asset_map = {
        "start_frame": None,
        "end_frame": None,
        "subject": slot_map.get("subject"),
        "scene": slot_map.get("scene"),
        "style": slot_map.get("style"),
        "product_reference": slot_map.get("product_reference"),
    }

    image_assets = {k: v for k, v in slot_map.items() if v}
    asset_fingerprints = [
        _fingerprint(a.get("asset_id", ""))
        for a in image_assets.values()
        if a and a.get("asset_id")
    ]

    settings = {
        "recipe_id": recipe_id,
        "generation_mode": generation_mode,
        "target_language": target_language,
        "camera_style": camera_style,
        "character_presence": character_presence,
        "creator_persona": creator_persona,
        "overlay_enabled": overlay_enabled,
        "dialogue_enabled": dialogue_enabled,
    }

    semantic_resolution = {
        "resolved_slots": resolved_slots,
        "recipe_id": recipe_id,
    }

    wgp_id = _wgp_id(product_id, mode, "I2V", prompt_fingerprint)

    manual_handoff = _build_manual_handoff(
        mode=mode,
        final_prompt_text=final_prompt_text,
        image_assets=image_assets,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        planner_result=compiler_result.get("planner_result"),
    )

    dom_scaffold = _build_dom_scaffold(
        mode=mode,
        product_id=product_id,
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        workspace_generation_package_id=wgp_id,
        final_prompt_text=final_prompt_text,
        prompt_blocks=prompt_blocks,
        generation_mode=generation_mode,
        asset_map=asset_map,
        settings=settings,
        semantic_resolution=semantic_resolution,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        prompt_fingerprint=prompt_fingerprint,
        asset_fingerprints=asset_fingerprints,
        planner_result=compiler_result.get("planner_result"),
    )

    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id=product_id,
        product_name_snapshot=product_name_snapshot,
        source_lane="I2V",
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        generation_mode=generation_mode,
        final_prompt_text=final_prompt_text,
        prompt_blocks_json=_json(prompt_blocks),
        selected_assets_json=_json(slot_map),
        resolved_engine_slots_json=_json({s: a.get("asset_id") if a else None for s, a in slot_map.items()}),
        resolver_output_json=_json(resolver_output),
        image_assets_json=_json(image_assets),
        manual_handoff_json=_json(manual_handoff),
        dom_handoff_payload_json=_json(dom_scaffold),
        blockers_json=_json(blockers),
        warnings_json=_json(warnings),
        status=status,
        batch_run_id=batch_run_id,
    )

    return _enrich_row(row)


# ─── Read ────────────────────────────────────────────────────


async def get_workspace_generation_package(wgp_id: str) -> dict | None:
    row = await crud.get_workspace_generation_package(wgp_id)
    if not row:
        return None
    return _enrich_row(row)


async def list_workspace_generation_packages(
    mode: str | None = None,
    status: str | None = None,
    product_id: str | None = None,
    batch_run_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    rows = await crud.list_workspace_generation_packages(
        mode=mode, status=status, product_id=product_id, batch_run_id=batch_run_id, limit=limit
    )
    return [_enrich_row(r) for r in rows]


# ─── Enrich row ──────────────────────────────────────────────


def _enrich_row(row: dict) -> dict:
    """Parse JSON columns and add dom_handoff_ready=False assertion."""
    if not row:
        return row
    out = dict(row)
    for col in (
        "prompt_blocks_json",
        "selected_assets_json",
        "resolved_engine_slots_json",
        "resolver_output_json",
        "image_assets_json",
        "manual_handoff_json",
        "dom_handoff_payload_json",
        "blockers_json",
        "warnings_json",
    ):
        raw = out.get(col)
        if raw:
            try:
                out[col] = json.loads(raw)
            except Exception:
                pass
    # Enforce dom_handoff_ready=False at the service layer
    dom = out.get("dom_handoff_payload_json")
    if isinstance(dom, dict) and "readiness" in dom:
        dom["readiness"]["dom_handoff_ready"] = False
    return out


# ─── T2V ─────────────────────────────────────────────────────


async def _resolve_bound_copy_intelligence(
    product_id: str,
    copy_set_id: str | None,
    copy_intelligence: dict | None,
) -> dict | None:
    """Bind an APPROVED Copy Set into compiler copy for durable package creation.

    Closes the Stage 2B gap: ``create_workspace_execution_package`` could bind a
    copy variant, but seeding a durable package re-compiled WITHOUT it, so the
    per-item copy binding was lost before the package existed. Bulk fan-out needs
    each package to carry its own approved variant, otherwise "no duplicate
    dialogue" is unenforceable at the package level.

    Reuses the existing ``resolve_compiler_copy_intelligence`` seam — only
    ``to_compiler_copy`` fields cross into the compiler, and an invalid /
    product-mismatched / unapproved copy_set_id raises CopyBindingError
    (fail-closed). Never fires a provider and never approves anything.

    Precedence: the resolved Copy Set is the BASE; explicitly passed
    ``copy_intelligence`` keys win on top of it (so the batch path's
    ``hook_override`` still applies over a bound variant).

    ``copy_set_id=None`` short-circuits — no resolver call, no DB read — so every
    pre-existing caller keeps its exact current behaviour.
    """
    if not copy_set_id:
        return copy_intelligence
    from agent.services.copy_binding_service import resolve_compiler_copy_intelligence

    binding = await resolve_compiler_copy_intelligence(product_id, copy_set_id)
    bound = binding.get("copy_intelligence")
    if not bound:
        return copy_intelligence
    return {**bound, **(copy_intelligence or {})}


async def create_t2v_generation_package(
    *,
    product_id: str,
    workspace_execution_package_id: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    blocks: list[dict] | None = None,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    operator_notes: str | None = None,
    batch_run_id: str | None = None,
    avatar_id: str | None = None,
    copy_intelligence: dict | None = None,
    copy_set_id: str | None = None,
    scene_context_override: str | None = None,
) -> dict:
    """Create a durable T2V workspace generation package (text-only, no frame uploads)."""
    mode = "T2V"
    copy_intelligence = await _resolve_bound_copy_intelligence(
        product_id, copy_set_id, copy_intelligence
    )
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))
    if scene_context_override:
        approved = {**approved, "scene_context": scene_context_override}

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    compiler_result = compile_ugc_video_prompt(
        product={
            "id": product_id,
            "name": product_name_snapshot or (product_row or {}).get("name", ""),
            "category": (product_row or {}).get("category", ""),
        },
        approved_package=approved,
        mode=mode,
        duration_seconds=duration_seconds,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        blocks=blocks or [],
        engine_duration_target=engine_duration_target,
        requested_total_duration_seconds=requested_total_duration_seconds,
        avatar_id=avatar_id,
        copy_intelligence=copy_intelligence,
    )

    final_prompt_text: str = compiler_result.get("final_compiled_prompt_text", "")
    prompt_blocks: list = compiler_result.get("prompt_blocks", [])
    prompt_fingerprint: str = compiler_result.get("prompt_fingerprint", _fingerprint(final_prompt_text))

    blockers: list = []
    warnings: list = []
    if not final_prompt_text:
        blockers.append("final_prompt_text is empty")

    status = "BLOCKED" if blockers else "READY_MANUAL"

    # T2V has no image assets
    asset_map: dict = {
        "start_frame": None, "end_frame": None,
        "subject": None, "scene": None, "style": None, "product_reference": None,
    }
    upload_order: list[str] = []
    image_assets: dict = {}
    asset_fingerprints: list = []

    settings = {
        "duration_seconds": duration_seconds,
        "generation_mode": generation_mode,
        "target_language": target_language,
        "camera_style": camera_style,
        "character_presence": character_presence,
        "creator_persona": creator_persona,
        "overlay_enabled": overlay_enabled,
        "dialogue_enabled": dialogue_enabled,
    }

    wgp_id = _wgp_id(product_id, mode, "T2V", prompt_fingerprint)

    manual_handoff = _build_manual_handoff(
        mode=mode,
        final_prompt_text=final_prompt_text,
        image_assets=image_assets,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        planner_result=compiler_result.get("planner_result"),
    )

    dom_scaffold = _build_dom_scaffold(
        mode=mode,
        product_id=product_id,
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        workspace_generation_package_id=wgp_id,
        final_prompt_text=final_prompt_text,
        prompt_blocks=prompt_blocks,
        generation_mode=generation_mode,
        asset_map=asset_map,
        settings=settings,
        semantic_resolution={},
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        prompt_fingerprint=prompt_fingerprint,
        asset_fingerprints=asset_fingerprints,
        planner_result=compiler_result.get("planner_result"),
    )

    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id=product_id,
        product_name_snapshot=product_name_snapshot,
        source_lane="T2V",
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        generation_mode=generation_mode,
        final_prompt_text=final_prompt_text,
        prompt_blocks_json=_json(prompt_blocks),
        selected_assets_json=_json({}),
        resolved_engine_slots_json=_json({}),
        resolver_output_json=_json({}),
        image_assets_json=_json(image_assets),
        manual_handoff_json=_json(manual_handoff),
        dom_handoff_payload_json=_json(dom_scaffold),
        blockers_json=_json(blockers),
        warnings_json=_json(warnings),
        status=status,
        batch_run_id=batch_run_id,
    )

    return _enrich_row(row)


# ─── IMG ─────────────────────────────────────────────────────


async def create_img_generation_package(
    *,
    product_id: str,
    workspace_execution_package_id: str | None = None,
    generation_mode: str = "SINGLE",
    target_language: str = "BM_MS",
    camera_style: str = "UGC_IPHONE_RAW",
    character_presence: str = "VISIBLE_CREATOR",
    creator_persona: str = "DEFAULT_CREATOR",
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
    dialogue_enabled: bool = True,
    engine_duration_target: str | None = None,
    requested_total_duration_seconds: int | None = None,
    subject_asset_id: str | None = None,
    subject_preview_url: str | None = None,
    subject_download_url: str | None = None,
    scene_context_asset_id: str | None = None,
    scene_context_preview_url: str | None = None,
    scene_context_download_url: str | None = None,
    style_asset_id: str | None = None,
    style_preview_url: str | None = None,
    style_download_url: str | None = None,
    operator_notes: str | None = None,
    batch_run_id: str | None = None,
    prompt_override: str | None = None,
) -> dict:
    """Create a durable IMG workspace generation package (image generation mode)."""
    mode = "IMG"
    # IMG is an IMAGE mode, NOT a video duration mode: Extend total-duration block
    # planning is not applicable. Fail closed rather than silently degrade into a
    # nonsensical multi-block image plan.
    if requested_total_duration_seconds is not None:
        raise ValueError("IMG_MODE_NO_EXTEND_TOTAL_DURATION")
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    compiler_result = compile_ugc_video_prompt(
        product={
            "id": product_id,
            "name": product_name_snapshot or (product_row or {}).get("name", ""),
            "category": (product_row or {}).get("category", ""),
        },
        approved_package=approved,
        mode=mode,
        duration_seconds=8,
        generation_mode=generation_mode,
        target_language=target_language,
        camera_style=camera_style,
        character_presence=character_presence,
        creator_persona=creator_persona,
        overlay_enabled=overlay_enabled,
        dialogue_enabled=dialogue_enabled,
        blocks=[],
    )

    final_prompt_text: str = compiler_result.get("final_compiled_prompt_text", "")
    if prompt_override:
        final_prompt_text = prompt_override
    prompt_blocks: list = compiler_result.get("prompt_blocks", [])
    prompt_fingerprint: str = compiler_result.get("prompt_fingerprint", _fingerprint(final_prompt_text))

    # Subject auto-seeds from product image
    product_image_url = f"/api/products/{product_id}/image"
    subject_slot = {
        "slot_key": "subject",
        "label": "Subject",
        "asset_id": subject_asset_id or f"product-image:{product_id}:subject",
        "preview_url": subject_preview_url or product_image_url,
        "download_url": subject_download_url or product_image_url,
        "source": "OPERATOR_SELECTED" if subject_asset_id else "PRODUCT_IMAGE_AUTO_SEED",
    }

    scene_slot: dict | None = None
    if scene_context_asset_id or scene_context_preview_url:
        scene_slot = {
            "slot_key": "scene",
            "label": "Scene Context",
            "asset_id": scene_context_asset_id,
            "preview_url": scene_context_preview_url,
            "download_url": scene_context_download_url,
            "source": "OPERATOR_SELECTED",
        }

    style_slot: dict | None = None
    if style_asset_id or style_preview_url:
        style_slot = {
            "slot_key": "style",
            "label": "Style Reference",
            "asset_id": style_asset_id,
            "preview_url": style_preview_url,
            "download_url": style_download_url,
            "source": "OPERATOR_SELECTED",
        }

    blockers: list = []
    warnings: list = []
    if not final_prompt_text:
        blockers.append("final_prompt_text is empty")
    if not subject_slot.get("asset_id"):
        blockers.append("subject image is required for IMG mode")

    status = "BLOCKED" if blockers else "READY_MANUAL"

    asset_map = {
        "start_frame": None, "end_frame": None,
        "subject": subject_slot,
        "scene": scene_slot,
        "style": style_slot,
        "product_reference": None,
    }
    image_assets = {k: v for k, v in asset_map.items() if v and k in ("subject", "scene", "style")}
    upload_order = [k for k in ("subject", "scene", "style") if asset_map.get(k)]
    asset_fingerprints = [_fingerprint(a.get("asset_id", "")) for a in image_assets.values() if a]

    settings = {
        "generation_mode": generation_mode,
        "target_language": target_language,
        "camera_style": camera_style,
        "character_presence": character_presence,
        "creator_persona": creator_persona,
        "overlay_enabled": overlay_enabled,
        "dialogue_enabled": dialogue_enabled,
    }

    wgp_id = _wgp_id(product_id, mode, "IMG", prompt_fingerprint)

    manual_handoff = _build_manual_handoff(
        mode=mode,
        final_prompt_text=final_prompt_text,
        image_assets=image_assets,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        planner_result=compiler_result.get("planner_result"),
    )

    dom_scaffold = _build_dom_scaffold(
        mode=mode,
        product_id=product_id,
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        workspace_generation_package_id=wgp_id,
        final_prompt_text=final_prompt_text,
        prompt_blocks=prompt_blocks,
        generation_mode=generation_mode,
        asset_map=asset_map,
        settings=settings,
        semantic_resolution={},
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
        prompt_fingerprint=prompt_fingerprint,
        asset_fingerprints=asset_fingerprints,
        planner_result=compiler_result.get("planner_result"),
    )

    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id=product_id,
        product_name_snapshot=product_name_snapshot,
        source_lane="IMG",
        prompt_package_snapshot_id=prompt_package_snapshot_id,
        workspace_execution_package_id=workspace_execution_package_id,
        generation_mode=generation_mode,
        final_prompt_text=final_prompt_text,
        prompt_blocks_json=_json(prompt_blocks),
        selected_assets_json=_json({"subject": subject_slot, "scene": scene_slot, "style": style_slot}),
        resolved_engine_slots_json=_json({
            "subject": subject_slot.get("asset_id") if subject_slot else None,
            "scene": scene_slot.get("asset_id") if scene_slot else None,
            "style": style_slot.get("asset_id") if style_slot else None,
        }),
        resolver_output_json=_json({}),
        image_assets_json=_json(image_assets),
        manual_handoff_json=_json(manual_handoff),
        dom_handoff_payload_json=_json(dom_scaffold),
        blockers_json=_json(blockers),
        warnings_json=_json(warnings),
        status=status,
        batch_run_id=batch_run_id,
    )

    return _enrich_row(row)


# ─── Batch Generation Runner ─────────────────────────────────


import asyncio as _asyncio
import logging as _logging

_batch_logger = _logging.getLogger(__name__)

async def create_hybrid_generation_package(**kwargs) -> dict:
    """HYBRID as a first-class logical mode: product image is the visual truth
    anchor, the presenter comes from the avatar registry. Rides the F2V
    creator with source_mode=HYBRID — source_lane stays HYBRID (never
    relabelled as generic F2V/I2V in stored data or UI)."""
    kwargs.setdefault("source_mode", "HYBRID")
    return await create_f2v_generation_package(**kwargs)


_MODE_CREATORS = {
    "F2V": create_f2v_generation_package,
    "HYBRID": create_hybrid_generation_package,
    "I2V": create_i2v_generation_package,
    "T2V": create_t2v_generation_package,
    "IMG": create_img_generation_package,
}

# P3B: cancel flags — set True to signal the batch loop to stop
_batch_cancel_flags: dict[str, bool] = {}


def _build_asset_kwargs(
    mode: str,
    char_id: str | None,
    scene_id: str | None,
    style_id: str | None,
    asset_cache: dict,
) -> dict:
    """Map asset IDs to the correct keyword arguments for each mode creator."""
    def _urls(asset_id: str | None) -> dict:
        if not asset_id:
            return {}
        row = asset_cache.get(asset_id, {})
        return {"preview_url": row.get("preview_url"), "download_url": row.get("download_url")}

    if mode == "F2V":
        kwargs = {}
        if char_id:
            kwargs["start_frame_asset_id"] = char_id
            u = _urls(char_id)
            if u.get("preview_url"):
                kwargs["start_frame_preview_url"] = u["preview_url"]
            if u.get("download_url"):
                kwargs["start_frame_download_url"] = u["download_url"]
        return kwargs

    if mode == "I2V":
        kwargs = {}
        if char_id:
            kwargs["character_reference_asset_id"] = char_id
        if scene_id:
            kwargs["scene_context_reference_asset_id"] = scene_id
        if style_id:
            kwargs["style_reference_asset_id"] = style_id
        return kwargs

    if mode == "IMG":
        kwargs = {}
        if char_id:
            kwargs["subject_asset_id"] = char_id
            u = _urls(char_id)
            if u.get("preview_url"):
                kwargs["subject_preview_url"] = u["preview_url"]
            if u.get("download_url"):
                kwargs["subject_download_url"] = u["download_url"]
        if scene_id:
            kwargs["scene_context_asset_id"] = scene_id
            u = _urls(scene_id)
            if u.get("preview_url"):
                kwargs["scene_context_preview_url"] = u["preview_url"]
            if u.get("download_url"):
                kwargs["scene_context_download_url"] = u["download_url"]
        if style_id:
            kwargs["style_asset_id"] = style_id
            u = _urls(style_id)
            if u.get("preview_url"):
                kwargs["style_preview_url"] = u["preview_url"]
            if u.get("download_url"):
                kwargs["style_download_url"] = u["download_url"]
        return kwargs

    # T2V — no direct asset params
    return {}


async def _run_batch_generation_task(
    batch_run_id: str,
    product_ids: list[str],
    modes: list[str],
    quantity_per_mode: int,
    interval_seconds: int,
    generation_mode: str,
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    img_prompt_template: str | None = None,
) -> None:
    """Background coroutine: generates packages sequentially with interval sleep.

    Supports a combination matrix: each (character × scene × style) slot tuple
    is run quantity_per_mode times per mode, across all product_ids.
    """
    from itertools import product as _iter_product

    char_slots: list[str | None] = character_asset_ids if character_asset_ids else [None]
    scene_slots: list[str | None] = scene_asset_ids if scene_asset_ids else [None]
    style_slots: list[str | None] = style_asset_ids if style_asset_ids else [None]
    combinations = list(_iter_product(char_slots, scene_slots, style_slots))

    # Pre-fetch all unique asset rows needed for URL resolution
    all_asset_ids = {a for a in (character_asset_ids or []) + (scene_asset_ids or []) + (style_asset_ids or []) if a}
    asset_cache: dict = {}
    for asset_id in all_asset_ids:
        try:
            row = await crud.get_creative_asset(asset_id)
            if row:
                asset_cache[asset_id] = row
        except Exception:
            pass

    completed = 0
    failed = 0
    errors: list[str] = []
    total_expected = len(product_ids) * len(modes) * len(combinations) * quantity_per_mode
    cancelled = False

    await crud.update_batch_generation_run(batch_run_id, status="RUNNING")

    outer_break = False
    for product_id in product_ids:
        if outer_break:
            break
        for mode in modes:
            if _batch_cancel_flags.get(batch_run_id):
                cancelled = True
                outer_break = True
                break
            creator = _MODE_CREATORS.get(mode)
            if not creator:
                errors.append(f"Unsupported mode: {mode}")
                _batch_logger.warning("Batch %s: unsupported mode %s, skipping", batch_run_id, mode)
                continue

            for combo_idx, (char_id, scene_id, style_id) in enumerate(combinations):
                if _batch_cancel_flags.get(batch_run_id):
                    cancelled = True
                    outer_break = True
                    break
                asset_kwargs = _build_asset_kwargs(mode, char_id, scene_id, style_id, asset_cache)
                combo_label = f"pid={product_id} char={char_id or '-'} scene={scene_id or '-'} style={style_id or '-'}"

                for idx in range(quantity_per_mode):
                    if _batch_cancel_flags.get(batch_run_id):
                        cancelled = True
                        outer_break = True
                        break
                    try:
                        extra: dict = {}
                        if mode == "IMG" and img_prompt_template:
                            char_row = asset_cache.get(char_id or "", {})
                            scene_row = asset_cache.get(scene_id or "", {})
                            style_row = asset_cache.get(style_id or "", {})
                            try:
                                rendered = img_prompt_template.format(
                                    character_dna=char_row.get("character_dna", ""),
                                    scene_context_dna=scene_row.get("scene_context_dna", ""),
                                    style_mood_dna=style_row.get("style_mood_dna", ""),
                                    mode_a_metadata_handoff=char_row.get("mode_a_metadata_handoff", ""),
                                )
                                extra["prompt_override"] = rendered
                            except (KeyError, IndexError):
                                extra["prompt_override"] = img_prompt_template
                        await creator(
                            product_id=product_id,
                            generation_mode=generation_mode,
                            batch_run_id=batch_run_id,
                            **asset_kwargs,
                            **extra,
                        )
                        completed += 1
                        _batch_logger.info(
                            "Batch %s: %s combo[%d] #%d completed (%d total) [%s]",
                            batch_run_id, mode, combo_idx, idx + 1, completed, combo_label,
                        )
                    except Exception as exc:
                        failed += 1
                        errors.append(f"{mode}[{combo_label}]#{idx+1}: {exc}")
                        _batch_logger.error(
                            "Batch %s: %s combo[%d] #%d failed: %s",
                            batch_run_id, mode, combo_idx, idx + 1, exc,
                        )

                    await crud.update_batch_generation_run(
                        batch_run_id,
                        total_completed=completed,
                        total_failed=failed,
                        error_log_json=_json(errors[-50:]),
                    )

                    remaining = total_expected - (completed + failed)
                    if remaining > 0 and interval_seconds > 0:
                        await _asyncio.sleep(interval_seconds)

    if cancelled:
        _batch_cancel_flags.pop(batch_run_id, None)
        await crud.update_batch_generation_run(
            batch_run_id,
            status="CANCELLED",
            total_completed=completed,
            total_failed=failed,
            error_log_json=_json(errors[-50:]),
        )
        _batch_logger.info("Batch %s cancelled: %d completed, %d failed", batch_run_id, completed, failed)
        return

    final_status = "COMPLETED" if failed == 0 else ("FAILED" if completed == 0 else "COMPLETED")
    await crud.update_batch_generation_run(
        batch_run_id,
        status=final_status,
        total_completed=completed,
        total_failed=failed,
        error_log_json=_json(errors[-50:]),
    )
    _batch_logger.info("Batch %s finished: %d completed, %d failed", batch_run_id, completed, failed)


# ─── Batch Prompt Runner (prompt/production split) ───────────


async def _resolve_hybrid_anchor_916(product_id: str) -> tuple[str | None, list[str]]:
    """Auto-pick the product's padded 9:16 PRODUCT_REFERENCE anchor for a
    HYBRID batch.

    HYBRID's visual truth is the product anchor, and the production queue's
    aspect gate (frame slots only) refuses any start frame that does not match
    the 9:16 production standard — a raw catalog image (e.g. 1122x1402) blocks
    at the gate. Deterministic pick: APPROVED PRODUCT_REFERENCE assets whose
    LOCAL image parses to 9:16 (same stdlib parser as the gate, +-3%), ordered
    by asset_id. No match -> (None, warning): the batch still builds against
    the raw product image and the queue gate stays the enforcement point.
    """
    import os
    from agent.services.production_queue_service import _image_dimensions

    rows = await crud.list_creative_assets(
        semantic_role="PRODUCT_REFERENCE", product_id=product_id,
    )
    candidates = sorted(
        (r for r in rows if r.get("review_status") == "APPROVED"),
        key=lambda r: str(r.get("asset_id") or ""),
    )
    target = 9 / 16
    for row in candidates:
        path = row.get("local_file_path") or ""
        if not path or not os.path.isfile(path):
            continue
        dims = _image_dimensions(path)
        if not dims or not dims[1]:
            continue
        ratio = dims[0] / dims[1]
        if abs(ratio - target) / target <= 0.03:
            return str(row["asset_id"]), []
    return None, [
        "HYBRID_ANCHOR_916_NOT_FOUND:raw_product_image_will_block_at_queue_gate:"
        "create_a_padded_916_PRODUCT_REFERENCE_asset"
    ]


def _plan_creator_kwargs(plan: dict, asset_cache: dict) -> dict:
    """Map one planner item plan to creator kwargs for its logical mode."""
    mode = plan["logical_mode"]
    kwargs: dict = {}
    if plan.get("scene_context_override"):
        kwargs["scene_context_override"] = plan["scene_context_override"]
    if plan.get("hook_override"):
        kwargs["copy_intelligence"] = {"hook": plan["hook_override"]}
    if mode in ("T2V", "HYBRID") and plan.get("avatar_code"):
        kwargs["avatar_id"] = plan["avatar_code"]
    if mode == "F2V" and plan.get("finished_frame_asset_id"):
        frame_id = plan["finished_frame_asset_id"]
        kwargs["start_frame_asset_id"] = frame_id
        row = asset_cache.get(frame_id, {})
        if row.get("preview_url"):
            kwargs["start_frame_preview_url"] = row["preview_url"]
        if row.get("download_url"):
            kwargs["start_frame_download_url"] = row["download_url"]
    if mode == "HYBRID" and plan.get("product_reference_asset_id"):
        # The padded 9:16 PRODUCT_REFERENCE anchor rides the F2V creator's
        # start-frame slot (HYBRID = F2V creator with source_mode=HYBRID).
        ref_id = plan["product_reference_asset_id"]
        kwargs["start_frame_asset_id"] = ref_id
        row = asset_cache.get(ref_id, {})
        if row.get("preview_url"):
            kwargs["start_frame_preview_url"] = row["preview_url"]
        if row.get("download_url"):
            kwargs["start_frame_download_url"] = row["download_url"]
    if mode == "I2V":
        if plan.get("character_asset_id"):
            kwargs["character_reference_asset_id"] = plan["character_asset_id"]
        if plan.get("scene_asset_id"):
            kwargs["scene_context_reference_asset_id"] = plan["scene_asset_id"]
        if plan.get("style_asset_id"):
            kwargs["style_reference_asset_id"] = plan["style_asset_id"]
    return kwargs


async def _annotate_batch_prompt_item(
    row: dict,
    plan: dict,
    fingerprints: dict,
    hard: list[str],
    soft: list[str],
) -> None:
    """Persist variation + redundancy metadata on a freshly created package."""
    from agent.services import batch_prompt_planner as _planner

    wgp_id = row.get("workspace_generation_package_id")
    if not wgp_id:
        return
    slots = row.get("resolved_engine_slots_json")
    if isinstance(slots, str):
        try:
            slots = json.loads(slots)
        except Exception:
            slots = {}
    update: dict = {
        "logical_mode": plan["logical_mode"],
        "variation_strategy": plan["variation_strategy"],
        "prompt_fingerprint": fingerprints["prompt_fingerprint"],
        "variation_fingerprints_json": _json(_planner.public_fingerprints(fingerprints)),
        "anti_redundancy_json": _json({"hard_blocks": hard, "warnings": soft}),
    }
    if hard:
        update["status"] = "BLOCKED"
    await crud.update_workspace_generation_package(wgp_id, **update)


async def _run_batch_prompt_plan_task(
    batch_run_id: str,
    *,
    product_id: str,
    logical_mode: str,
    variation_strategy: str,
    interval_seconds: int,
    generation_mode: str,
    item_plans: list[dict],
    creator_base_kwargs: dict,
    rotation_pool_size: int,
) -> None:
    """Background coroutine for the Batch Prompt Builder: one logical mode,
    planner-driven variation, per-item anti-redundancy annotation.

    Prompt generation ONLY — no Google Flow execution, no credits."""
    from agent.services import batch_prompt_planner as _planner
    from agent.services import copy_rotation_service as _rotation

    creator = _MODE_CREATORS.get(logical_mode)
    if creator is None:
        await crud.update_batch_generation_run(
            batch_run_id, status="FAILED",
            error_log_json=_json([f"Unsupported logical mode: {logical_mode}"]),
        )
        return

    history_rows = await crud.list_recent_prompt_fingerprints(product_id, logical_mode)
    history_fps = {r["prompt_fingerprint"] for r in history_rows if r.get("prompt_fingerprint")}

    asset_cache: dict = {}
    _plan0 = item_plans[0] if item_plans else {}
    for _aid in (
        _plan0.get("finished_frame_asset_id"),
        _plan0.get("product_reference_asset_id"),
    ):
        if not _aid:
            continue
        try:
            _row = await crud.get_creative_asset(_aid)
            if _row:
                asset_cache[_aid] = _row
        except Exception:
            pass

    completed = 0
    failed = 0
    errors: list[str] = []
    batch_seen: list[dict] = []
    cancelled = False

    await crud.update_batch_generation_run(batch_run_id, status="RUNNING")

    total = len(item_plans)
    for plan in item_plans:
        if _batch_cancel_flags.get(batch_run_id):
            cancelled = True
            break
        try:
            # Combination ledger gate (P2): the same (script x avatar x scene)
            # must never be produced twice — the on-platform uniqueness law.
            # Pre-create refusal applies only to Script Library items, whose
            # text is FIXED before compile; angle-based items diverge their
            # dialogue at compile time, so their real script identity (the
            # dialogue fingerprint) is only known post-create and is checked
            # at record time below.
            if plan.get("copy_set_id"):
                combo_fp = _rotation.plan_combination_fingerprint(product_id, plan)
                if await _rotation.combination_already_used(combo_fp):
                    raise ValueError(
                        "COMBINATION_ALREADY_USED:"
                        "same_script_avatar_scene_already_produced:"
                        "vary_scripts_or_visuals"
                    )
            row = await creator(
                product_id=product_id,
                generation_mode=generation_mode,
                batch_run_id=batch_run_id,
                **creator_base_kwargs,
                **_plan_creator_kwargs(plan, asset_cache),
            )
            slots = row.get("resolved_engine_slots_json")
            if isinstance(slots, str):
                try:
                    slots = json.loads(slots)
                except Exception:
                    slots = {}
            fingerprints = _planner.compute_fingerprints(
                final_prompt_text=row.get("final_prompt_text", ""),
                item_plan=plan,
                resolved_engine_slots=slots if isinstance(slots, dict) else {},
            )
            hard, soft = _planner.check_redundancy(
                fingerprints=fingerprints,
                batch_seen=batch_seen,
                history_fingerprints=history_fps,
                variation_strategy=variation_strategy,
                quantity=total,
                rotation_pool_size=rotation_pool_size,
            )
            await _annotate_batch_prompt_item(row, plan, fingerprints, hard, soft)
            if hard:
                failed += 1
                errors.append(
                    f"item#{plan['item_index'] + 1}: BLOCKED {','.join(hard)}"
                )
            else:
                # P2: burn the combination + record one real script use only
                # for a package that actually came out usable (not BLOCKED).
                # Angle-based items get their true script identity here — the
                # compiled dialogue fingerprint — so the UNIQUE index catches
                # a real duplicate even across batches.
                dialogue_fp = fingerprints.get("dialogue_fingerprint") or None
                combo_fp = _rotation.plan_combination_fingerprint(
                    product_id, plan, dialogue_fingerprint=dialogue_fp
                )
                combo_row = await _rotation.record_combination(
                    product_id=product_id,
                    logical_mode=logical_mode,
                    plan=plan,
                    fingerprint=combo_fp,
                    dialogue_fingerprint=dialogue_fp,
                    workspace_generation_package_id=row.get(
                        "workspace_generation_package_id"
                    ),
                    batch_run_id=batch_run_id,
                )
                if combo_row is None:
                    failed += 1
                    errors.append(
                        f"item#{plan['item_index'] + 1}: COMBINATION_DUPLICATE_AT_RECORD"
                    )
                    wgp_id = row.get("workspace_generation_package_id")
                    if wgp_id:
                        await crud.update_workspace_generation_package(
                            wgp_id, status="BLOCKED"
                        )
                else:
                    completed += 1
                    batch_seen.append(fingerprints)
                    if plan.get("copy_set_id"):
                        try:
                            await _rotation.record_rotation_usage(
                                plan["copy_set_id"], logical_mode
                            )
                        except Exception as usage_exc:
                            _batch_logger.warning(
                                "BatchPrompt %s: usage record failed for %s: %s",
                                batch_run_id, plan["copy_set_id"], usage_exc,
                            )
        except Exception as exc:
            failed += 1
            errors.append(f"item#{plan['item_index'] + 1}: {exc}")
            _batch_logger.error(
                "BatchPrompt %s: item #%d failed: %s",
                batch_run_id, plan["item_index"] + 1, exc,
            )

        await crud.update_batch_generation_run(
            batch_run_id,
            total_completed=completed,
            total_failed=failed,
            error_log_json=_json(errors[-50:]),
        )
        remaining = total - (completed + failed)
        if remaining > 0 and interval_seconds > 0:
            await _asyncio.sleep(interval_seconds)

    if cancelled:
        _batch_cancel_flags.pop(batch_run_id, None)
        await crud.update_batch_generation_run(
            batch_run_id, status="CANCELLED",
            total_completed=completed, total_failed=failed,
            error_log_json=_json(errors[-50:]),
        )
        return

    final_status = "FAILED" if completed == 0 and failed > 0 else "COMPLETED"
    await crud.update_batch_generation_run(
        batch_run_id, status=final_status,
        total_completed=completed, total_failed=failed,
        error_log_json=_json(errors[-50:]),
    )
    _batch_logger.info(
        "BatchPrompt %s finished: %d completed, %d failed", batch_run_id, completed, failed
    )


def allowed_batch_durations(engine: str = "GOOGLE_FLOW") -> list[int]:
    """Authoritative total durations for batch prompts — sourced from the WPS
    workbook (agent/authority/wps_blocking_authority.json, ADR-008). The UI
    duration selector and the server-side gate both read THIS list."""
    from agent.services import canonical_prompt_compiler as _canonical

    plans = _canonical._wps_authority().get("block_plans", [])
    return sorted({
        int(p["duration_seconds"]) for p in plans
        if p.get("engine") == engine and p.get("duration_seconds")
    })


# ── Stage 1 quantity PREVIEW (credit-free; never fires, approves, or enqueues) ──

QUANTITY_PREVIEW_MAX = 5


def _norm_dialogue(text: str) -> str:
    """Whitespace/case-normalised spoken dialogue for stable in-preview hashing."""
    return " ".join(str(text or "").split()).strip().lower()


def _preview_dialogue_text(compiled: dict) -> str:
    """Full spoken dialogue of one compiled item, robust across SINGLE and EXTEND.

    Prefers the storyboard planner's canonical full dialogue (EXTEND), then the
    per-block exact slices, then SECTION-6 extraction from the final prompt text.
    """
    from agent.services import batch_prompt_planner as _planner

    planner_result = compiled.get("planner_result") or {}
    full = str((planner_result.get("full_dialogue_plan") or {}).get("full_dialogue_text") or "").strip()
    if full:
        return full
    slices = [
        str((b or {}).get("exact_dialogue_slice") or "").strip()
        for b in (compiled.get("prompt_blocks") or [])
    ]
    slices = [s for s in slices if s]
    if slices:
        return "\n".join(slices)
    return _planner.extract_dialogue(str(compiled.get("final_compiled_prompt_text") or ""))


def _extract_seam_voice_preview(compiled: dict) -> dict | None:
    """Read-only echo of the PR #428 seam/voice contract from a compiled EXTEND
    preview (the preview never generates — this only surfaces the compiled fields)."""
    blocks = compiled.get("prompt_blocks") or []
    if len(blocks) < 2:
        return None
    first = (blocks[0] or {}).get("audio_seam_contract") or {}
    last = (blocks[-1] or {}).get("audio_seam_contract") or {}
    return {
        "outgoing_dialogue_deadline_s": first.get("outgoing_dialogue_deadline_s"),
        "seam_outgoing_margin_s": first.get("seam_outgoing_margin_s"),
        "incoming_new_dialogue_onset_floor_s": last.get("incoming_new_dialogue_onset_floor_s"),
        "seam_incoming_margin_s": last.get("seam_incoming_margin_s"),
        "voice_continuity_required": last.get("voice_continuity_required"),
        "voice_profile_lock": last.get("voice_profile_lock"),
    }


def _evaluate_preview_uniqueness(items: list[dict]) -> dict:
    """FAIL-CLOSED dialogue-uniqueness verdict over compiled preview items.

    A preview passes ONLY when every item compiled to a non-empty dialogue AND all
    dialogue fingerprints are distinct. Any exact-duplicate dialogue (the pool<N
    reuse case) or any item that failed to compile / produced empty dialogue BLOCKS
    the whole preview. This is the 'no repeated same dialogue' contract made
    fail-closed instead of warning-only.
    """
    blockers: list[str] = []
    by_fp: dict[str, list] = {}
    for it in items:
        idx = it.get("item_index")
        if it.get("compile_error"):
            blockers.append(f"ITEM_{idx}_COMPILE_FAILED:{it['compile_error']}")
            continue
        fp = it.get("dialogue_fingerprint")
        if not fp or not str(it.get("dialogue_summary") or "").strip():
            blockers.append(f"ITEM_{idx}_EMPTY_DIALOGUE")
            continue
        by_fp.setdefault(fp, []).append(idx)
    duplicate_groups = [idxs for idxs in by_fp.values() if len(idxs) > 1]
    for group in duplicate_groups:
        blockers.append("DUPLICATE_DIALOGUE_ACROSS_ITEMS:" + ",".join(str(i) for i in group))
    status = "UNIQUE" if not blockers else "DUPLICATE_DIALOGUE_BLOCKED"
    return {"status": status, "blockers": blockers, "duplicate_groups": duplicate_groups}


# Bound on how many approved copy sets a single readiness scan will compile.
# Readiness early-exits as soon as it has found `quantity` distinct dialogues, so
# this cap only bites on genuinely duplicate-heavy pools; it keeps one operator
# click from compiling an unbounded pool. Compilation is credit-free either way.
COPY_POOL_SCAN_CAP = 12

READINESS_READY = "READY"
READINESS_SHORTAGE = "COPY_POOL_SHORTAGE"
READINESS_NO_APPROVED = "NO_APPROVED_COPY_AVAILABLE"


async def evaluate_copy_pool_readiness(
    *,
    product_id: str,
    logical_mode: str,
    source_mode: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    requested_total_duration_seconds: int | None = None,
    quantity: int = 1,
    target_language: str = "BM_MS",
) -> dict:
    """Can this product supply ``quantity`` UNIQUE approved dialogues? (credit-free)

    A copy set stores copy *ingredients* (angle/hook/subhook/usp/cta) — there is no
    dialogue column anywhere on ``copy_set``. Dialogue only exists once the canonical
    compiler renders SECTION 6, so "N unique dialogues available" is NOT answerable
    by counting approved rows: two distinct approved copy sets can compile to the
    same dialogue. This walks the rotation-eligible pool in rotation order, compiles
    each candidate (ZERO provider calls, ZERO Flow calls, ZERO DB writes, ZERO
    credit) and counts DISTINCT dialogue fingerprints.

    Reports the shortage instead of hiding it; it never approves, never generates
    and never relaxes the fail-closed uniqueness contract enforced by
    ``_evaluate_preview_uniqueness`` at preview time.
    """
    import hashlib

    from agent.services import batch_prompt_planner as _planner  # noqa: F401
    from agent.services import copy_rotation_service as _rotation
    from agent.services import workspace_execution_package_service as _wxp

    mode = str(logical_mode or "").strip().upper()
    n = int(quantity)
    if n < 1 or n > QUANTITY_PREVIEW_MAX:
        raise ValueError(f"QUANTITY_OUT_OF_RANGE:1..{QUANTITY_PREVIEW_MAX}")

    is_extend = str(generation_mode or "").strip().upper() == "EXTEND"
    engine_duration_target = "GOOGLE_FLOW" if is_extend else None

    pool = await _rotation.list_eligible_copy_sets(product_id)
    approved_copy_count = len(pool)

    if not approved_copy_count:
        return {
            "product_id": product_id,
            "quantity_requested": n,
            "quantity_max": QUANTITY_PREVIEW_MAX,
            "approved_copy_count": 0,
            "unique_dialogue_count": 0,
            "shortage_count": n,
            "readiness_status": READINESS_NO_APPROVED,
            "duplicate_fingerprint_groups": [],
            "scanned_copy_set_count": 0,
            "pool_scan_capped": False,
            "compile_errors": [],
            "next_action": "GENERATE_AND_APPROVE_COPY",
            "credit": "NONE",
            "provider_calls": 0,
            "flow_calls": 0,
        }

    scan = pool[:COPY_POOL_SCAN_CAP]
    by_fp: dict[str, list[str]] = {}
    compile_errors: list[str] = []
    scanned = 0

    for row in scan:
        cs_id = str(row.get("copy_set_id") or "")
        scanned += 1
        try:
            compiled = await _wxp.compile_workspace_prompt_preview(
                product_id=product_id,
                mode=mode,
                duration_seconds=int(duration_seconds),
                generation_mode=generation_mode,
                target_language=target_language,
                source_mode=source_mode,
                engine_duration_target=engine_duration_target,
                requested_total_duration_seconds=requested_total_duration_seconds,
                copy_set_id=cs_id,
            )
        except Exception as exc:  # a bad copy set blocks itself, never the report
            compile_errors.append(f"{cs_id}:{type(exc).__name__}:{str(exc)[:80]}")
            continue
        norm = _norm_dialogue(_preview_dialogue_text(compiled))
        if not norm:
            compile_errors.append(f"{cs_id}:EMPTY_DIALOGUE")
            continue
        fp = hashlib.sha1(norm.encode("utf-8")).hexdigest()
        by_fp.setdefault(fp, []).append(cs_id)
        # Early exit: enough DISTINCT dialogue already proven for this quantity.
        if len(by_fp) >= n:
            break

    unique_dialogue_count = len(by_fp)
    shortage = max(0, n - unique_dialogue_count)
    status = READINESS_READY if shortage == 0 else READINESS_SHORTAGE

    return {
        "product_id": product_id,
        "quantity_requested": n,
        "quantity_max": QUANTITY_PREVIEW_MAX,
        "approved_copy_count": approved_copy_count,
        "unique_dialogue_count": unique_dialogue_count,
        "shortage_count": shortage,
        "readiness_status": status,
        "duplicate_fingerprint_groups": [
            {"dialogue_fingerprint": fp, "copy_set_ids": ids}
            for fp, ids in by_fp.items()
            if len(ids) > 1
        ],
        "scanned_copy_set_count": scanned,
        "pool_scan_capped": approved_copy_count > COPY_POOL_SCAN_CAP and shortage > 0,
        "compile_errors": compile_errors,
        "next_action": None if shortage == 0 else "GENERATE_AND_APPROVE_COPY",
        "credit": "NONE",
        "provider_calls": 0,
        "flow_calls": 0,
    }


async def plan_bulk_fanout_intents(
    *,
    product_id: str,
    logical_mode: str,
    source_mode: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    requested_total_duration_seconds: int | None = None,
    quantity: int = 1,
    target_language: str = "BM_MS",
) -> dict:
    """Stage 2A: plan N ITEMIZED live-production intents. CREDIT-FREE.

    Bulk live must never be one blind ``count:N`` submission — ``count`` is the
    provider's per-submission copy count (clamped 1..4), NOT an item multiplier.
    This produces N SEPARATE intents, each carrying its own identity, so the
    fan-out is auditable item-by-item instead of being an untracked batch.

    Fail-closed chain, in order: copy-pool readiness must be READY, then the
    quantity preview must be UNIQUE. Either failing yields a plan that is NOT
    authorizable — duplicate dialogue can never reach the live fan-out.

    Plans only. Creates no package, approves nothing, enqueues nothing, fires
    nothing: ZERO provider calls, ZERO Flow calls, ZERO credit. Live execution
    additionally requires the server-side BULK_FANOUT gate, which stops at the
    Stage 3 credit boundary.
    """
    mode = str(logical_mode or "").strip().upper()
    n = int(quantity)
    if n < 1 or n > QUANTITY_PREVIEW_MAX:
        raise ValueError(f"QUANTITY_OUT_OF_RANGE:1..{QUANTITY_PREVIEW_MAX}")

    common = {
        "product_id": product_id,
        "logical_mode": mode,
        "source_mode": source_mode,
        "generation_mode": generation_mode,
        "duration_seconds": duration_seconds,
        "requested_total_duration_seconds": requested_total_duration_seconds,
        "quantity": n,
        "target_language": target_language,
    }
    blockers: list[str] = []

    readiness = await evaluate_copy_pool_readiness(**common)
    if readiness["readiness_status"] != READINESS_READY:
        blockers.append(
            f"COPY_POOL_NOT_READY:{readiness['readiness_status']}:"
            f"short_by_{readiness['shortage_count']}"
        )

    preview = await preview_quantity_copy_plans(**common)
    if not preview["preview_ready"]:
        blockers.append(f"PREVIEW_NOT_UNIQUE:{preview['dialogue_uniqueness_status']}")

    # Bulk EXTEND stays blocked: the single-shot production lane fails closed on
    # EXTEND packages (multi-block belongs to the durable /video-jobs
    # orchestrator, which is per-job, not per-run). Surfaced as an exact blocker
    # rather than silently truncating a 16s request to one 8s block.
    if str(generation_mode or "").strip().upper() == "EXTEND":
        blockers.append(
            "BULK_EXTEND_NOT_SUPPORTED:use_video_jobs_orchestrator_per_item"
        )

    intents: list[dict] = []
    for item in preview.get("items") or []:
        intents.append({
            "item_index": item.get("item_index"),
            "copy_variant_id": item.get("copy_variant_id"),
            "variation_salt": item.get("variation_salt"),
            "dialogue_fingerprint": item.get("dialogue_fingerprint"),
            "hook": item.get("hook"),
            "dialogue_summary": item.get("dialogue_summary"),
            "seam_voice": item.get("seam_voice"),
            "logical_mode": mode,
            "source_mode": source_mode,
            "generation_mode": generation_mode,
            # Lineage stays UNBOUND until the package actually exists — reported
            # as null rather than invented, so no intent claims a package it
            # does not have.
            "workspace_generation_package_id": None,
            "production_run_id": None,
            "production_job_id": None,
            "item_status": "PLANNED" if not item.get("compile_error") else "BLOCKED",
            "compile_error": item.get("compile_error"),
            # Per-item credit metadata: every item is its own credit event.
            "credit_state": "NOT_AUTHORIZED",
            "credit_warning": "This item spends provider credit when fired.",
        })

    # One fingerprint over the whole authorized set. The live gate re-derives the
    # per-item fingerprints and refuses if the set drifted from what was shown.
    dialogue_fps = [str(i["dialogue_fingerprint"] or "") for i in intents]
    plan_fingerprint = hashlib.sha256(
        json.dumps(
            {"product_id": product_id, "mode": mode, "generation_mode": generation_mode,
             "quantity": n, "dialogue_fingerprints": sorted(dialogue_fps)},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "product_id": product_id,
        "quantity_requested": n,
        "quantity_max": QUANTITY_PREVIEW_MAX,
        "logical_mode": mode,
        "generation_mode": generation_mode,
        "planned_intent_count": len(intents),
        "intents": intents,
        "bulk_plan_fingerprint": plan_fingerprint,
        "copy_pool_readiness_status": readiness["readiness_status"],
        "dialogue_uniqueness_status": preview["dialogue_uniqueness_status"],
        "blockers": blockers,
        # Authorizable == every prerequisite proven. It does NOT mean the run may
        # fire: the server gate still stops at the Stage 3 credit boundary.
        "bulk_authorizable": not blockers and len(intents) == n,
        "live_bulk_status": "Bulk live fan-out not certified yet",
        "live_bulk_stage": "STAGE_3_RUNTIME_CERTIFICATION_REQUIRED",
        "required_confirm_phrase": "AUTHORIZE_BULK_FANOUT_LIVE_RUN",
        "credit": "NONE",
        "provider_calls": 0,
        "flow_calls": 0,
    }


BULK_PREPARE_SUPPORTED_MODES = ("T2V", "F2V", "HYBRID", "I2V")


async def prepare_bulk_fanout_packages(
    *,
    product_id: str,
    logical_mode: str,
    source_mode: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    requested_total_duration_seconds: int | None = None,
    quantity: int = 1,
    target_language: str = "BM_MS",
    model: str | None = None,
    aspect: str = "9:16",
    expect_bulk_plan_fingerprint: str | None = None,
    start_frame_asset_id: str | None = None,
    product_reference_asset_id: str | None = None,
    character_reference_asset_id: str | None = None,
    scene_context_reference_asset_id: str | None = None,
) -> dict:
    """Stage 2C: create → approve → enqueue N DURABLE packages. CREDIT-FREE.

    Turns the Stage 2A itemized plan into N real ``workspace_generation_package``
    rows, one per planned item, each bound to its OWN approved Copy Set via the
    Stage 2B ``copy_set_id`` seam — so "no duplicate dialogue" is enforced at the
    package level, not just in a preview.

    Never a ``count:N`` submission: ``count`` is the provider's per-submission
    copy count (clamped 1..4). This enqueues N SEPARATE package ids into one run,
    which is what the queue's item loop and per-item dry run already understand.

    FAIL-CLOSED, in order, and every check runs BEFORE anything is written:
      1. copy-pool readiness must be READY and the preview UNIQUE (re-derived
         server-side — a client cannot assert its own readiness);
      2. ``expect_bulk_plan_fingerprint``, when supplied, must match the
         server-recomputed plan, so a STALE client preview cannot be prepared;
      3. every intent must carry a copy_variant_id and a dialogue_fingerprint;
      4. fingerprints must be distinct across the batch.

    Package creation is all-or-nothing: if any item fails, NOTHING is approved
    and NOTHING is enqueued, and the failing item is reported by index.

    Idempotent: re-running the same plan returns the existing batch instead of
    silently creating a second set of packages.

    Spends ZERO credit and makes ZERO provider/Flow calls — approval and
    enqueueing are pure DB state transitions, and the run is created dry_run=1.
    Live firing additionally needs the BULK_FANOUT gate, which stops at the
    Stage 3 credit boundary.
    """
    from agent.db import crud as _crud
    from agent.services import copy_rotation_service as _rotation
    from agent.services import production_queue_service as _pq

    mode = str(logical_mode or "").strip().upper()
    if mode not in BULK_PREPARE_SUPPORTED_MODES:
        raise ValueError(f"BULK_PREPARE_UNSUPPORTED_MODE:{mode or 'UNKNOWN'}")

    # Bulk prepare is BULK-only. A single item must stay on its mode-exact
    # one-serial path, which carries stricter per-lane rules than the bulk gate;
    # the bulk LIVE gate already refuses a 1-item run
    # (BULK_REQUIRES_MULTIPLE_ITEMS), so preparing one here would only ever
    # produce a batch that can never be authorized as bulk. Refused BEFORE the
    # plan and before any create/approve/enqueue/dry-run.
    if int(quantity) < 2:
        raise ValueError(f"BULK_PREPARE_REQUIRES_MULTIPLE_ITEMS:{int(quantity)}")

    # B-08: HYBRID is a LOGICAL mode; the compiler only knows the engine modes and
    # raises UNSUPPORTED_MODE for "HYBRID". It compiles as F2V + source_mode=HYBRID
    # (the same mapping the Studio applies client-side). `mode` stays the logical
    # identity for creator dispatch; only the compile call is remapped.
    compile_mode = "F2V" if mode == "HYBRID" else mode
    resolved_source_mode = source_mode or ("HYBRID" if mode == "HYBRID" else None)

    plan = await plan_bulk_fanout_intents(
        product_id=product_id, logical_mode=compile_mode, source_mode=resolved_source_mode,
        generation_mode=generation_mode, duration_seconds=duration_seconds,
        requested_total_duration_seconds=requested_total_duration_seconds,
        quantity=quantity, target_language=target_language,
    )
    if not plan["bulk_authorizable"]:
        raise ValueError("BULK_PREPARE_REFUSED:" + ";".join(plan["blockers"]))

    # A stale client preview must never be prepared: the operator authorizes the
    # dialogue set they SAW, and the server owns the comparison.
    if expect_bulk_plan_fingerprint and expect_bulk_plan_fingerprint != plan["bulk_plan_fingerprint"]:
        raise ValueError(
            f"BULK_PLAN_FINGERPRINT_STALE:expected={expect_bulk_plan_fingerprint[:12]},"
            f"server={plan['bulk_plan_fingerprint'][:12]}"
        )

    intents = plan["intents"]
    seen_fp: dict[str, int] = {}
    for intent in intents:
        idx = intent["item_index"]
        if not intent.get("copy_variant_id"):
            raise ValueError(f"BULK_ITEM_MISSING_COPY_VARIANT:item#{idx}")
        fp = str(intent.get("dialogue_fingerprint") or "")
        if not fp:
            raise ValueError(f"BULK_ITEM_MISSING_DIALOGUE_FINGERPRINT:item#{idx}")
        if fp in seen_fp:
            raise ValueError(f"BULK_DUPLICATE_DIALOGUE:item#{seen_fp[fp]},item#{idx}")
        seen_fp[fp] = idx

    # One durable group key per plan. `batch_run_id` is a REAL column with a
    # crud filter, so the batch survives restart and gives us idempotency for
    # free — no schema change, no in-memory bookkeeping.
    # B-09: the plan fingerprint is computed from the COMPILE mode, which is F2V
    # for both F2V and HYBRID (see B-08). Keying the batch on it alone made a
    # HYBRID request reuse an F2V batch — same dialogue, but FRAMES packages
    # instead of the product-anchor ones. The group key must carry the LOGICAL
    # lane identity, not just the compiled copy identity.
    bulk_run_id = "bulk_" + hashlib.sha256(
        f"{plan['bulk_plan_fingerprint']}|{mode}|{resolved_source_mode or ''}".encode("utf-8")
    ).hexdigest()[:16]
    existing = await _crud.list_workspace_generation_packages(
        batch_run_id=bulk_run_id, limit=200
    )
    if existing:
        # B-02: the listing comes back ordered created_at DESC, so zipping it
        # against the plan's intents mis-attributed each dialogue to the wrong
        # package on every re-run. Pair by the DURABLE item_index each package
        # carries instead of by list order; if any package is missing that
        # identity we cannot prove the pairing, so fail closed rather than
        # report a manifest that might be wrong.
        by_index: dict[int, str] = {}
        for row in existing:
            ident = row.get("generation_identity_json")
            try:
                ident = json.loads(ident) if isinstance(ident, str) and ident else (ident or {})
            except (TypeError, ValueError):
                ident = {}
            bulk_item = (ident or {}).get("bulk_fanout_item") or {}
            idx = bulk_item.get("item_index")
            if idx is None:
                raise ValueError(
                    "BULK_REUSE_IDENTITY_MISSING:"
                    f"{row['workspace_generation_package_id']}:cannot_pair_item_index"
                )
            by_index[int(idx)] = row["workspace_generation_package_id"]

        expected = [int(i["item_index"]) for i in plan["intents"]]
        missing = [i for i in expected if i not in by_index]
        if missing:
            raise ValueError(f"BULK_REUSE_INCOMPLETE_BATCH:missing_item_indexes={missing}")

        # B-07: a prior attempt can leave packages behind that never completed —
        # e.g. created but BLOCKED, so approval refused and nothing was ever
        # enqueued. Returning those as "PREPARED" produced a manifest claiming a
        # prepared batch with production_run_id=None. Reuse only a batch that is
        # genuinely usable; otherwise fail closed and name the reason.
        blocked = [
            r["workspace_generation_package_id"] for r in existing
            if str(r.get("status") or "").upper() == "BLOCKED"
        ]
        if blocked:
            raise ValueError(
                f"BULK_REUSE_BATCH_BLOCKED:{','.join(sorted(blocked)[:5])}"
                ":previous_attempt_left_blocked_packages"
            )
        prior_run = existing[0].get("production_run_id")
        if not prior_run:
            raise ValueError(
                f"BULK_REUSE_BATCH_NOT_ENQUEUED:{bulk_run_id}"
                ":previous_attempt_never_reached_a_production_run"
            )

        return _bulk_manifest(
            plan, bulk_run_id,
            [by_index[i] for i in expected],
            production_run_id=(existing[0].get("production_run_id")),
            reused=True,
        )

    # B-10 (pre-check): bulk consumes the copy pool, so it must PAY into the same
    # content_combination ledger the batch lane does — it never did, which let a
    # later plan re-select and re-produce already-produced dialogue (live proof:
    # the 2026-07-20 T2V bulk run left 0 ledger rows and 0 usage increments, so
    # the very next plan re-picked the same two variants byte-identically).
    # This advisory pass rejects a plan whose dialogue is already in the ledger
    # BEFORE any package exists; the UNIQUE index at record time below remains
    # the authority. Runs only on the fresh-create path — a reused batch already
    # paid when it was first prepared.
    combo_fps: dict[int, str] = {}
    for intent in intents:
        idx = intent["item_index"]
        combo_fps[idx] = _rotation.plan_combination_fingerprint(
            product_id,
            _bulk_combination_plan(mode, intent),
            dialogue_fingerprint=str(intent["dialogue_fingerprint"]),
        )
        if await _rotation.combination_already_used(combo_fps[idx]):
            raise ValueError(
                f"BULK_DUPLICATE_COMBINATION:item#{idx}"
                ":dialogue_already_produced_for_this_product_and_lane"
                ":created_before_failure=0"
            )

    creator_kwargs: dict = {
        "product_id": product_id,
        "generation_mode": generation_mode,
        "target_language": target_language,
        "batch_run_id": bulk_run_id,
        "requested_total_duration_seconds": requested_total_duration_seconds,
    }
    if mode in ("T2V", "F2V", "HYBRID"):
        creator_kwargs["duration_seconds"] = duration_seconds

    created: list[str] = []
    for intent in intents:
        idx = intent["item_index"]
        try:
            if mode == "T2V":
                pkg = await create_t2v_generation_package(
                    copy_set_id=intent["copy_variant_id"], **creator_kwargs)
            elif mode in ("F2V", "HYBRID"):
                # B-06: create_f2v_generation_package accepts start_frame_asset_id,
                # NOT product_reference_asset_id (that is the I2V creator's param).
                # Passing it raised TypeError and broke F2V/HYBRID bulk prepare
                # outright — the mocked creators in the orchestration tests hid it.
                # HYBRID's padded 9:16 PRODUCT_REFERENCE anchor rides the F2V
                # creator's start-frame slot, exactly as the batch lane does it
                # (see _annotate kwargs: "HYBRID = F2V creator with
                # source_mode=HYBRID").
                frame_id = (
                    product_reference_asset_id if mode == "HYBRID" else start_frame_asset_id
                )
                pkg = await create_f2v_generation_package(
                    copy_set_id=intent["copy_variant_id"],
                    source_mode=source_mode or ("HYBRID" if mode == "HYBRID" else "FRAMES"),
                    start_frame_asset_id=frame_id,
                    **creator_kwargs)
            else:  # I2V
                pkg = await create_i2v_generation_package(
                    copy_set_id=intent["copy_variant_id"],
                    character_reference_asset_id=character_reference_asset_id,
                    scene_context_reference_asset_id=scene_context_reference_asset_id,
                    **creator_kwargs)
        except Exception as exc:
            # All-or-nothing: report the exact failing item and stop. Nothing is
            # approved or enqueued, so a partial batch can never reach a run.
            raise ValueError(
                f"BULK_PACKAGE_CREATE_FAILED:item#{idx}:{type(exc).__name__}:{str(exc)[:120]}"
                f":created_before_failure={len(created)}"
            ) from exc
        wgp_id = pkg["workspace_generation_package_id"]
        created.append(wgp_id)
        # Durable per-item identity, merge-written into generation_identity_json
        # (the column already has a read-modify-merge precedent). No migration.
        await _persist_bulk_item_identity(wgp_id, bulk_run_id, plan, intent)
        # B-10 (authority): burn the combination under the UNIQUE index BEFORE
        # anything can be approved or enqueued. A duplicate here (a race the
        # pre-check cannot see) aborts the whole batch — all-or-nothing holds
        # because approve/enqueue only run after every item recorded cleanly.
        combo_row = await _rotation.record_combination(
            product_id=product_id,
            logical_mode=mode,
            plan=_bulk_combination_plan(mode, intent),
            fingerprint=combo_fps[idx],
            dialogue_fingerprint=str(intent["dialogue_fingerprint"]),
            workspace_generation_package_id=wgp_id,
            batch_run_id=bulk_run_id,
        )
        if combo_row is None:
            raise ValueError(
                f"BULK_DUPLICATE_COMBINATION:item#{idx}"
                ":combination_already_in_ledger"
                f":created_before_failure={len(created)}"
            )
        # One real script use per consumed variant, so the LRU pool ADVANCES and
        # the next plan rotates to fresh copy instead of replaying this one.
        # Fail-soft exactly like the batch lane: a usage-counter hiccup must
        # never strand packages that already burned their combination.
        try:
            await _rotation.record_rotation_usage(intent["copy_variant_id"], mode)
        except Exception as usage_exc:  # noqa: BLE001
            _batch_logger.warning(
                "BulkFanout %s: usage record failed for %s: %s",
                bulk_run_id, intent["copy_variant_id"], usage_exc,
            )

    approve = await _pq.approve_packages(created)
    if approve.get("approved") != len(created):
        failures = [r for r in approve.get("results") or [] if not r.get("ok")]
        raise ValueError("BULK_APPROVE_FAILED:" + json.dumps(failures)[:300])

    run = await _pq.send_to_production(
        created, aspect=aspect, model=model,
        count=1,  # provider copies per submission — NOT the item fan-out
    )
    run_id = run["production_run_id"]

    cfg = json.loads(run.get("config_json") or "{}") if isinstance(run.get("config_json"), str) else (run.get("config_json") or {})
    cfg["bulk_fanout_manifest"] = {
        "schema_version": "bulk-fanout-manifest-v1",
        "bulk_run_id": bulk_run_id,
        "bulk_plan_fingerprint": plan["bulk_plan_fingerprint"],
        "items": [
            {**{k: intent[k] for k in (
                "item_index", "copy_variant_id", "variation_salt",
                "dialogue_fingerprint", "logical_mode", "source_mode",
                "generation_mode")},
             "workspace_generation_package_id": wgp_id,
             "requested_total_duration_seconds": requested_total_duration_seconds,
             "duration_seconds": duration_seconds}
            for intent, wgp_id in zip(intents, created)
        ],
    }
    await _crud.update_production_run(run_id, config_json=json.dumps(cfg, ensure_ascii=False))

    return _bulk_manifest(plan, bulk_run_id, created, production_run_id=run_id, reused=False)


def _bulk_combination_plan(logical_mode: str, intent: dict) -> dict:
    """Ledger identity of ONE bulk item: product x LOGICAL lane x compiled dialogue.

    Deliberately WITHOUT copy_set_id: ``script_key_for_plan`` gives the copy set
    precedence, which would pin the ledger identity to the variant itself and
    permanently burn it after a single bulk use — breaking the reuse-under-cap
    rotation design (REUSE_CAP allows a variant back once its dialogue diverges).
    The bulk item's script truth is its compiled dialogue fingerprint, exactly
    the batch lane's angle-based precedent: reusing a copy set stays legal until
    it would compile the SAME dialogue again, and that is refused.

    ``logical_mode`` is the LOGICAL lane (T2V/F2V/HYBRID/I2V), never the compile
    remap — B-09's lesson: HYBRID compiles as F2V but is a different lane, and
    the same dialogue on different lanes is a different on-platform combination.
    """
    return {"logical_mode": str(logical_mode or "").upper()}


async def _persist_bulk_item_identity(
    wgp_id: str, bulk_run_id: str, plan: dict, intent: dict
) -> None:
    """Merge per-item bulk identity into generation_identity_json (no migration).

    Merge-write, mirroring _persist_binding_outcome: read the column back and add
    a namespaced sub-object, so nothing already stored there is clobbered.
    Fail-soft — identity bookkeeping must never break package creation.
    """
    from agent.db import crud as _crud
    try:
        row = await _crud.get_workspace_generation_package(wgp_id) or {}
        raw = row.get("generation_identity_json")
        identity = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
        if not isinstance(identity, dict):
            identity = {}
        identity["bulk_fanout_item"] = {
            "schema_version": "bulk-fanout-item-v1",
            "bulk_run_id": bulk_run_id,
            "bulk_plan_fingerprint": plan["bulk_plan_fingerprint"],
            "item_index": intent["item_index"],
            "copy_variant_id": intent["copy_variant_id"],
            "variation_salt": intent["variation_salt"],
            "dialogue_fingerprint": intent["dialogue_fingerprint"],
            "logical_mode": intent["logical_mode"],
            "source_mode": intent["source_mode"],
            "generation_mode": intent["generation_mode"],
        }
        await _crud.update_workspace_generation_package(
            wgp_id, generation_identity_json=json.dumps(identity, ensure_ascii=False)
        )
    except Exception:  # noqa: BLE001 — bookkeeping must not break creation
        _batch_logger.warning(
            "bulk item identity persist failed wgp=%s", wgp_id, exc_info=True
        )


def _bulk_manifest(
    plan: dict, bulk_run_id: str, package_ids: list[str],
    *, production_run_id: str | None, reused: bool,
) -> dict:
    """The itemized prepare result the Studio renders and the live gate pins."""
    return {
        "bulk_run_id": bulk_run_id,
        "bulk_plan_fingerprint": plan["bulk_plan_fingerprint"],
        "production_run_id": production_run_id,
        "product_id": plan["product_id"],
        "logical_mode": plan["logical_mode"],
        "generation_mode": plan["generation_mode"],
        "quantity_requested": plan["quantity_requested"],
        "prepared_package_count": len(package_ids),
        "package_ids": package_ids,
        "expect_dialogue_fingerprints": [
            i["dialogue_fingerprint"] for i in plan["intents"]
        ],
        "items": [
            {**{k: i[k] for k in (
                "item_index", "copy_variant_id", "variation_salt",
                "dialogue_fingerprint", "hook", "dialogue_summary",
                "logical_mode", "source_mode", "generation_mode")},
             "workspace_generation_package_id": pkg,
             "item_status": "PREPARED",
             "credit_state": "NOT_AUTHORIZED"}
            for i, pkg in zip(plan["intents"], package_ids)
        ],
        "reused_existing_batch": reused,
        "stage": "PACKAGES_PREPARED",
        "next_step": "DRY_RUN_VALIDATE_ALL_ITEMS",
        "live_bulk_status": "Bulk live fan-out not certified yet",
        "live_bulk_stage": "STAGE_3_RUNTIME_CERTIFICATION_REQUIRED",
        "required_confirm_phrase": "AUTHORIZE_BULK_FANOUT_LIVE_RUN",
        "credit": "NONE",
        "provider_calls": 0,
        "flow_calls": 0,
    }


async def preview_quantity_copy_plans(
    *,
    product_id: str,
    logical_mode: str,
    source_mode: str | None = None,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    requested_total_duration_seconds: int | None = None,
    quantity: int = 1,
    target_language: str = "BM_MS",
    variation_strategy: str = "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
) -> dict:
    """Stage-1 CREDIT-FREE quantity preview.

    Plans N items and compiles each item's prompt with ZERO provider calls, ZERO
    Flow calls, ZERO DB writes and ZERO credit — purely to preview the planned
    copy/dialogue variants. Dialogue uniqueness is enforced FAIL-CLOSED (see
    ``_evaluate_preview_uniqueness``): an approved-copy pool smaller than N, or any
    repeated dialogue, BLOCKS the preview rather than warning. This NEVER approves,
    enqueues, or fires anything; live bulk fan-out is Stage 2 and stays unbuilt.
    """
    import hashlib

    from agent.services import batch_prompt_planner as _planner
    from agent.services import copy_rotation_service as _rotation
    from agent.services import workspace_execution_package_service as _wxp

    mode = str(logical_mode or "").strip().upper()
    n = int(quantity)
    if n < 1 or n > QUANTITY_PREVIEW_MAX:
        raise ValueError(f"QUANTITY_OUT_OF_RANGE:1..{QUANTITY_PREVIEW_MAX}")

    is_extend = str(generation_mode or "").strip().upper() == "EXTEND"

    # Resolve up to N approved copy sets (deterministic LRU) — the dialogue source.
    # B-12: a variant's dialogue is a pure function of (product, lane, copy set) —
    # variation_salt does NOT diverge it — so a variant whose dialogue is already
    # in the content_combination ledger can never be prepared again on this lane.
    # Selecting blindly by rotation order therefore produced plans the prepare
    # gate was guaranteed to 409 (live proof 2026-07-21: plan kept proposing the
    # burned head of the pool, a closed plan->prepare loop). Filter candidates
    # against the SAME ledger fingerprint prepare checks, walking the rotation
    # order past burned variants, so the plan only ever proposes dialogue that
    # prepare will accept. Fail-closed: fewer than N fresh variants is a blocker,
    # never a silent shrink.
    resolved_hooks: list[str] = []
    resolved_copy_set_ids: list[str] = []
    copy_rotation_warnings: list[str] = []
    ledger_blockers: list[str] = []
    compiled_cache: dict[str, dict] = {}
    fresh_fp_by_copy_set: dict[str, str | None] = {}
    copy_source: str | None = None
    try:
        pool = await _rotation.list_eligible_copy_sets(product_id)
        if not pool:
            copy_rotation_warnings.append(
                "NO_APPROVED_COPY_AVAILABLE:generate_and_approve_scripts_first"
            )
        elif len(pool) < n:
            copy_rotation_warnings.append(
                f"POOL_SMALLER_THAN_BATCH:{len(pool)}<{n}:scripts_repeat_with_different_visuals"
            )
        seen: set[str] = set()
        for row in pool:
            if len(resolved_copy_set_ids) >= n:
                break
            cs_id = str(row.get("copy_set_id") or "")
            cs_hook = str(row.get("hook") or row.get("angle") or "").strip()
            if not cs_id or cs_id in seen:
                continue
            seen.add(cs_id)
            try:
                candidate = await _wxp.compile_workspace_prompt_preview(
                    product_id=product_id,
                    mode=mode,
                    duration_seconds=int(duration_seconds),
                    generation_mode=generation_mode,
                    target_language=target_language,
                    source_mode=source_mode,
                    engine_duration_target=(
                        "GOOGLE_FLOW" if is_extend else None
                    ),
                    requested_total_duration_seconds=requested_total_duration_seconds,
                    copy_set_id=cs_id,
                )
            except Exception:
                # A variant that cannot compile cannot prove its dialogue is
                # fresh. Keep it OUT of the selection (fail-closed) but surface
                # it, so one broken variant does not block the healthy pool.
                copy_rotation_warnings.append(f"CANDIDATE_COMPILE_FAILED:{cs_id[:8]}")
                continue
            cand_norm = _norm_dialogue(_preview_dialogue_text(candidate))
            cand_fp = (
                hashlib.sha1(cand_norm.encode("utf-8")).hexdigest() if cand_norm else None
            )
            if cand_fp:
                cand_combo_fp = _rotation.plan_combination_fingerprint(
                    product_id,
                    _bulk_combination_plan(mode, {}),
                    dialogue_fingerprint=cand_fp,
                )
                if await _rotation.combination_already_used(cand_combo_fp):
                    copy_rotation_warnings.append(
                        f"LEDGER_SKIP:{cs_id[:8]}:dialogue_already_produced_this_lane"
                    )
                    continue
            compiled_cache[cs_id] = candidate
            fresh_fp_by_copy_set[cs_id] = cand_fp
            resolved_copy_set_ids.append(cs_id)
            resolved_hooks.append(cs_hook)
        if pool and len(resolved_copy_set_ids) < n:
            ledger_blockers.append(
                "DIALOGUE_POOL_EXHAUSTED:"
                f"fresh={len(resolved_copy_set_ids)}<{n}:"
                "approve_new_copy_or_lower_quantity"
            )
        if resolved_copy_set_ids:
            copy_source = "SCRIPT_LIBRARY"
    except Exception as exc:  # rotation must never fire a provider; surface, don't crash
        copy_rotation_warnings.append(f"COPY_ROTATION_UNAVAILABLE:{type(exc).__name__}")

    item_plans = _planner.plan_batch_items(
        logical_mode=mode,
        variation_strategy=variation_strategy,
        quantity=n,
        product_id=product_id,
        hook_angles=resolved_hooks,
        copy_set_ids=resolved_copy_set_ids,
    )

    engine_duration_target = "GOOGLE_FLOW" if is_extend else None
    items: list[dict] = []
    for plan in item_plans:
        copy_set_id = plan.get("copy_set_id")
        entry: dict = {
            "item_index": plan.get("item_index"),
            "variation_salt": plan.get("variation_salt"),
            "copy_variant_id": copy_set_id,
            "hook": plan.get("hook_override"),
            "dialogue_summary": None,
            "dialogue_fingerprint": None,
            "seam_voice": None,
            "compile_error": None,
        }
        try:
            # B-12: candidates were already compiled during ledger filtering —
            # reuse that exact result so the fingerprint the operator authorizes
            # is byte-identical to the one that was ledger-checked.
            compiled = compiled_cache.get(str(copy_set_id) or "")
            if compiled is None:
                compiled = await _wxp.compile_workspace_prompt_preview(
                    product_id=product_id,
                    mode=mode,
                    duration_seconds=int(duration_seconds),
                    generation_mode=generation_mode,
                    target_language=target_language,
                    source_mode=source_mode,
                    engine_duration_target=engine_duration_target,
                    requested_total_duration_seconds=requested_total_duration_seconds,
                    copy_set_id=copy_set_id,
                )
        except Exception as exc:  # compile is credit-free; a failure blocks that item only
            entry["compile_error"] = f"{type(exc).__name__}:{str(exc)[:80]}"
            items.append(entry)
            continue
        dialogue = _preview_dialogue_text(compiled)
        norm = _norm_dialogue(dialogue)
        entry["dialogue_fingerprint"] = hashlib.sha1(norm.encode("utf-8")).hexdigest() if norm else None
        entry["hook"] = entry["hook"] or _planner.extract_hook(dialogue) or None
        collapsed = " ".join(dialogue.split())
        entry["dialogue_summary"] = (collapsed[:220] + "…") if len(collapsed) > 220 else collapsed
        if is_extend:
            entry["seam_voice"] = _extract_seam_voice_preview(compiled)
        items.append(entry)

    verdict = _evaluate_preview_uniqueness(items)
    blockers = list(verdict["blockers"])
    # B-12: ledger exhaustion is a hard blocker — the plan may only claim
    # readiness for dialogue prepare will actually accept.
    blockers.extend(ledger_blockers)
    pool_short = any("POOL_SMALLER_THAN_BATCH" in w for w in copy_rotation_warnings)
    if pool_short and verdict["status"] != "UNIQUE":
        blockers.append(f"APPROVED_COPY_POOL_SMALLER_THAN_QUANTITY:pool<{n}")

    return {
        "quantity_requested": n,
        "quantity_max": QUANTITY_PREVIEW_MAX,
        "planned_item_count": len(items),
        "logical_mode": mode,
        "generation_mode": generation_mode,
        "variation_strategy": variation_strategy,
        "copy_source": copy_source,
        "copy_rotation_warnings": copy_rotation_warnings,
        "items": items,
        "dialogue_uniqueness_status": verdict["status"],
        "duplicate_dialogue_groups": verdict["duplicate_groups"],
        "blockers": blockers,
        "preview_ready": verdict["status"] == "UNIQUE" and not blockers,
        "live_bulk_status": "Bulk live fan-out not enabled yet",
        "live_bulk_stage": "STAGE_2_REQUIRED",
        "credit": "NONE",
        "provider_calls": 0,
        "flow_calls": 0,
    }


async def start_batch_prompt_run(
    *,
    product_id: str,
    logical_mode: str,
    quantity: int = 10,
    variation_strategy: str | None = None,
    interval_seconds: int = 5,
    generation_mode: str = "SINGLE",
    duration_seconds: int = 8,
    target_language: str = "BM_MS",
    avatar_codes: list[str] | None = None,
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    scene_contexts: list[str] | None = None,
    hook_angles: list[str] | None = None,
    finished_frame_asset_id: str | None = None,
    product_reference_asset_id: str | None = None,
) -> dict:
    """Batch Prompt Builder entry point. ONE logical mode per batch (mode law).

    Validates the mode input contract fail-closed, expands Qty N into a
    deterministic variation plan, then generates N polished prompt packages
    into the Prompt Queue. Raises ValueError("MODE_CONTRACT_VIOLATION:…")
    on any contract breach.
    """
    from agent.services import batch_prompt_planner as _planner

    logical_mode = str(logical_mode or "").strip().upper()
    variation_strategy = variation_strategy or _planner.DEFAULT_VARIATION_STRATEGY
    product_row = await crud.get_product(product_id)

    contract_errors = _planner.validate_mode_inputs(
        logical_mode,
        quantity=quantity,
        variation_strategy=variation_strategy,
        finished_frame_asset_id=finished_frame_asset_id,
        character_asset_ids=character_asset_ids,
        scene_asset_ids=scene_asset_ids,
        style_asset_ids=style_asset_ids,
        product_row=product_row,
    )
    if contract_errors:
        raise ValueError("MODE_CONTRACT_VIOLATION:" + ",".join(contract_errors))

    # Duration authority (ADR-008): total durations come from the WPS workbook
    # only — arbitrary values fail closed, never silently coerced.
    if logical_mode in ("T2V", "HYBRID", "F2V"):
        from agent.services import canonical_prompt_compiler as _canonical
        try:
            _canonical.resolve_block_plan("GOOGLE_FLOW", int(duration_seconds))
        except (TypeError, ValueError):
            raise ValueError(
                f"MODE_CONTRACT_VIOLATION:DURATION_NOT_IN_AUTHORITY:{duration_seconds}"
            )

    # HYBRID product anchor: explicit PRODUCT_REFERENCE asset wins, else
    # auto-pick the padded 9:16 anchor (queue aspect gate refuses raw images).
    anchor_warnings: list[str] = []
    if logical_mode == "HYBRID" and not product_reference_asset_id:
        product_reference_asset_id, anchor_warnings = await _resolve_hybrid_anchor_916(
            product_id
        )

    # Avatar rotation pool: explicit subset, else the full approved registry.
    resolved_avatars = [a for a in (avatar_codes or []) if a]
    if logical_mode in ("T2V", "HYBRID") and not resolved_avatars:
        try:
            from agent.services import avatar_registry as _avatars
            resolved_avatars = [
                p.get("avatar_code") for p in _avatars.list_pool() if p.get("avatar_code")
            ]
        except Exception:
            resolved_avatars = []

    # Script source priority (Script Library P2): explicit hooks win, then
    # the approved Script Library via deterministic LRU rotation, then the
    # claim-safe hook angles from product truth (legacy fallback so products
    # with an empty library keep working).
    resolved_hooks = [h for h in (hook_angles or []) if h]
    resolved_copy_set_ids: list[str] = []
    copy_rotation_warnings: list[str] = []
    copy_source = "EXPLICIT_HOOKS" if resolved_hooks else None
    if not resolved_hooks:
        try:
            from agent.services import copy_rotation_service as _rotation
            selection = await _rotation.select_rotation_copy_sets(product_id, quantity)
            copy_rotation_warnings = list(selection.get("warnings") or [])
            seen_cs: set[str] = set()
            for cs_row in selection.get("items") or []:
                cs_id = str(cs_row.get("copy_set_id") or "")
                cs_hook = str(cs_row.get("hook") or cs_row.get("angle") or "").strip()
                if not cs_id or not cs_hook or cs_id in seen_cs:
                    continue
                seen_cs.add(cs_id)
                resolved_copy_set_ids.append(cs_id)
                resolved_hooks.append(cs_hook)
            if resolved_hooks:
                copy_source = "SCRIPT_LIBRARY"
        except Exception as exc:
            _batch_logger.warning("BatchPrompt: script library unavailable: %s", exc)
            resolved_hooks, resolved_copy_set_ids = [], []
    if not resolved_hooks and product_row:
        try:
            payload = json.loads(product_row.get("claim_safe_copy_payload") or "{}")
            resolved_hooks = [h for h in (payload.get("safe_hook_angles") or []) if h]
            if resolved_hooks:
                copy_source = "CLAIM_SAFE_ANGLES"
        except Exception:
            resolved_hooks = []

    item_plans = _planner.plan_batch_items(
        logical_mode=logical_mode,
        variation_strategy=variation_strategy,
        quantity=quantity,
        product_id=product_id,
        avatar_codes=resolved_avatars,
        character_asset_ids=character_asset_ids,
        scene_asset_ids=scene_asset_ids,
        style_asset_ids=style_asset_ids,
        scene_contexts=scene_contexts,
        hook_angles=resolved_hooks,
        copy_set_ids=resolved_copy_set_ids,
        finished_frame_asset_id=finished_frame_asset_id,
        product_reference_asset_id=product_reference_asset_id,
    )

    rotation_pool_size = max(
        len(resolved_avatars) or 0,
        len(character_asset_ids or []) or 0,
        1,
    )

    creator_base_kwargs: dict = {
        "target_language": target_language,
    }
    if logical_mode in ("T2V", "HYBRID", "F2V"):
        creator_base_kwargs["duration_seconds"] = duration_seconds

    batch_run_id = f"bgr_{_fingerprint(product_id, logical_mode, str(quantity), str(uuid.uuid4()))[:16]}"
    config = {
        "product_ids": [product_id],
        "modes": [logical_mode],
        "logical_mode": logical_mode,
        "variation_strategy": variation_strategy,
        "quantity_per_mode": quantity,
        "interval_seconds": interval_seconds,
        "generation_mode": generation_mode,
        "duration_seconds": duration_seconds,
        "target_language": target_language,
        "avatar_codes": resolved_avatars,
        "character_asset_ids": character_asset_ids or [],
        "scene_asset_ids": scene_asset_ids or [],
        "style_asset_ids": style_asset_ids or [],
        "scene_contexts": scene_contexts or [],
        "hook_angles": resolved_hooks,
        "copy_source": copy_source,
        "copy_set_ids": resolved_copy_set_ids,
        "copy_rotation_warnings": copy_rotation_warnings,
        "finished_frame_asset_id": finished_frame_asset_id,
        "product_reference_asset_id": product_reference_asset_id,
        "anchor_warnings": anchor_warnings,
    }

    run = await crud.create_batch_generation_run(
        batch_run_id,
        product_id=product_id,
        modes_json=json.dumps([logical_mode]),
        quantity_per_mode=quantity,
        interval_seconds=interval_seconds,
        generation_mode=generation_mode,
        total_expected=quantity,
        product_ids_json=json.dumps([product_id]),
        config_json=json.dumps(config),
    )
    # Stamp mode-law metadata on the run row (additive columns).
    from agent.db.schema import get_db as _get_db
    _db = await _get_db()
    await _db.execute(
        "UPDATE batch_generation_run SET logical_mode=?, variation_strategy=? WHERE batch_run_id=?",
        (logical_mode, variation_strategy, batch_run_id),
    )
    await _db.commit()
    run["logical_mode"] = logical_mode
    run["variation_strategy"] = variation_strategy

    _asyncio.ensure_future(
        _run_batch_prompt_plan_task(
            batch_run_id,
            product_id=product_id,
            logical_mode=logical_mode,
            variation_strategy=variation_strategy,
            interval_seconds=interval_seconds,
            generation_mode=generation_mode,
            item_plans=item_plans,
            creator_base_kwargs=creator_base_kwargs,
            rotation_pool_size=rotation_pool_size,
        )
    )
    return run


async def start_batch_generation(
    *,
    product_id: str,
    product_ids: list[str] | None = None,
    modes: list[str],
    quantity_per_mode: int = 10,
    interval_seconds: int = 5,
    generation_mode: str = "SINGLE",
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    img_prompt_template: str | None = None,
) -> dict:
    """Create a batch run record and fire the background task. Returns the run record."""
    import json as _json_mod

    all_product_ids = product_ids if product_ids else [product_id]
    char_slots = character_asset_ids or [None]
    scene_slots = scene_asset_ids or [None]
    style_slots = style_asset_ids or [None]
    combinations = len(char_slots) * len(scene_slots) * len(style_slots)

    batch_run_id = f"bgr_{_fingerprint(all_product_ids[0], str(modes), str(quantity_per_mode), str(uuid.uuid4()))[:16]}"
    total_expected = len(all_product_ids) * len(modes) * combinations * quantity_per_mode

    config = {
        "product_ids": all_product_ids,
        "modes": modes,
        "quantity_per_mode": quantity_per_mode,
        "interval_seconds": interval_seconds,
        "generation_mode": generation_mode,
        "character_asset_ids": character_asset_ids or [],
        "scene_asset_ids": scene_asset_ids or [],
        "style_asset_ids": style_asset_ids or [],
        "img_prompt_template": img_prompt_template,
    }

    run = await crud.create_batch_generation_run(
        batch_run_id,
        product_id=all_product_ids[0],
        modes_json=_json_mod.dumps(modes),
        quantity_per_mode=quantity_per_mode,
        interval_seconds=interval_seconds,
        generation_mode=generation_mode,
        total_expected=total_expected,
        product_ids_json=_json_mod.dumps(all_product_ids),
        config_json=_json_mod.dumps(config),
    )

    # Fire-and-forget background task
    _asyncio.ensure_future(
        _run_batch_generation_task(
            batch_run_id=batch_run_id,
            product_ids=all_product_ids,
            modes=modes,
            quantity_per_mode=quantity_per_mode,
            interval_seconds=interval_seconds,
            generation_mode=generation_mode,
            character_asset_ids=character_asset_ids or [],
            scene_asset_ids=scene_asset_ids or [],
            style_asset_ids=style_asset_ids or [],
            img_prompt_template=img_prompt_template,
        )
    )

    return run


# ─── Scheduled Batch Runs ────────────────────────────────────


async def create_scheduled_batch_run(
    *,
    product_ids: list[str],
    modes: list[str],
    quantity_per_mode: int = 10,
    interval_seconds: int = 5,
    generation_mode: str = "SINGLE",
    character_asset_ids: list[str] | None = None,
    scene_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    img_prompt_template: str | None = None,
    scheduled_at: str,
    label: str | None = None,
) -> dict:
    """Persist a scheduled batch run. The scheduler loop fires it when scheduled_at is reached."""
    import json as _json_mod

    scheduled_run_id = f"sbr_{_fingerprint(product_ids[0] if product_ids else '', str(modes), scheduled_at, str(uuid.uuid4()))[:16]}"
    return await crud.create_scheduled_batch_run(
        scheduled_run_id,
        product_ids_json=_json_mod.dumps(product_ids),
        modes_json=_json_mod.dumps(modes),
        quantity_per_mode=quantity_per_mode,
        interval_seconds=interval_seconds,
        generation_mode=generation_mode,
        character_asset_ids_json=_json_mod.dumps(character_asset_ids or []),
        scene_asset_ids_json=_json_mod.dumps(scene_asset_ids or []),
        style_asset_ids_json=_json_mod.dumps(style_asset_ids or []),
        img_prompt_template=img_prompt_template,
        scheduled_at=scheduled_at,
        label=label,
    )


async def list_scheduled_batch_runs_service(
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    import json as _json_mod
    rows = await crud.list_scheduled_batch_runs(status=status, limit=limit)
    for row in rows:
        try:
            row["product_ids"] = _json_mod.loads(row.get("product_ids_json", "[]"))
            row["modes"] = _json_mod.loads(row.get("modes_json", "[]"))
        except Exception:
            row["product_ids"] = []
            row["modes"] = []
    return rows


async def cancel_scheduled_batch_run(scheduled_run_id: str) -> dict | None:
    rows = await crud.list_scheduled_batch_runs(limit=1000)
    run = next((r for r in rows if r["scheduled_run_id"] == scheduled_run_id), None)
    if not run:
        return None
    if run.get("status") == "SCHEDULED":
        await crud.update_scheduled_batch_run(scheduled_run_id, status="CANCELLED")
        run["status"] = "CANCELLED"
    return run


async def _scheduler_loop() -> None:
    """Background loop: fires scheduled batch runs when their scheduled_at time is reached."""
    import datetime as _dt
    import json as _json_mod

    _batch_logger.info("Scheduled batch runner started")
    while True:
        try:
            now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            due = await crud.get_due_scheduled_batch_runs(now_iso)
            for row in due:
                srun_id = row["scheduled_run_id"]
                _batch_logger.info("Firing scheduled batch run %s", srun_id)
                try:
                    await crud.update_scheduled_batch_run(srun_id, status="RUNNING")
                    product_ids = _json_mod.loads(row.get("product_ids_json", "[]"))
                    modes = _json_mod.loads(row.get("modes_json", "[]"))
                    char_ids = _json_mod.loads(row.get("character_asset_ids_json", "[]"))
                    scene_ids = _json_mod.loads(row.get("scene_asset_ids_json", "[]"))
                    style_ids = _json_mod.loads(row.get("style_asset_ids_json", "[]"))

                    run = await start_batch_generation(
                        product_id=product_ids[0] if product_ids else "",
                        product_ids=product_ids,
                        modes=modes,
                        quantity_per_mode=row.get("quantity_per_mode", 10),
                        interval_seconds=row.get("interval_seconds", 5),
                        generation_mode=row.get("generation_mode", "SINGLE"),
                        character_asset_ids=char_ids or None,
                        scene_asset_ids=scene_ids or None,
                        style_asset_ids=style_ids or None,
                        img_prompt_template=row.get("img_prompt_template"),
                    )
                    await crud.update_scheduled_batch_run(
                        srun_id,
                        status="COMPLETED",
                        batch_run_id=run.get("batch_run_id"),
                    )
                    _batch_logger.info("Scheduled run %s fired → batch %s", srun_id, run.get("batch_run_id"))
                except Exception as exc:
                    _batch_logger.error("Scheduled run %s failed to fire: %s", srun_id, exc)
                    await crud.update_scheduled_batch_run(srun_id, status="FAILED")
        except Exception as exc:
            _batch_logger.error("Scheduler loop error: %s", exc)

        await _asyncio.sleep(60)


async def list_batch_generation_runs(
    product_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    import json as _json_mod
    rows = await crud.list_batch_generation_runs(product_id=product_id, limit=limit)
    for run in rows:
        try:
            run["modes"] = _json_mod.loads(run.get("modes_json", "[]"))
        except Exception:
            run["modes"] = []
    return rows


async def cancel_batch_generation_run(batch_run_id: str) -> dict | None:
    """Signal a running batch to stop after the current item. Returns updated run."""
    _batch_cancel_flags[batch_run_id] = True
    run = await crud.get_batch_generation_run(batch_run_id)
    if not run:
        return None
    if run.get("status") in ("PENDING", "RUNNING"):
        await crud.update_batch_generation_run(batch_run_id, status="CANCELLED")
        run["status"] = "CANCELLED"
    return run


async def retry_batch_generation_run(batch_run_id: str) -> dict | None:
    """Create a new batch run from the stored config of a failed/cancelled run.

    quantity_per_mode is set to the total_failed count divided by
    (products × modes × combinations), rounded up — so every failed slot
    gets one retry attempt.
    """
    import json as _json_mod
    import math

    run = await crud.get_batch_generation_run(batch_run_id)
    if not run:
        return None

    try:
        config: dict = _json_mod.loads(run.get("config_json") or "{}")
    except Exception:
        config = {}

    if not config:
        return None

    total_failed = run.get("total_failed", 0) or 1
    product_ids: list[str] = config.get("product_ids") or [run.get("product_id", "")]
    modes: list[str] = config.get("modes") or []
    char_ids: list[str] = config.get("character_asset_ids") or []
    scene_ids: list[str] = config.get("scene_asset_ids") or []
    style_ids: list[str] = config.get("style_asset_ids") or []

    char_slots = max(1, len(char_ids))
    scene_slots = max(1, len(scene_ids))
    style_slots = max(1, len(style_ids))
    denominator = len(product_ids) * max(1, len(modes)) * char_slots * scene_slots * style_slots
    retry_qty = max(1, math.ceil(total_failed / denominator))

    return await start_batch_generation(
        product_id=product_ids[0],
        product_ids=product_ids,
        modes=modes,
        quantity_per_mode=retry_qty,
        interval_seconds=config.get("interval_seconds", 5),
        generation_mode=config.get("generation_mode", "SINGLE"),
        character_asset_ids=char_ids or None,
        scene_asset_ids=scene_ids or None,
        style_asset_ids=style_ids or None,
        img_prompt_template=config.get("img_prompt_template"),
    )


async def get_batch_generation_run_status(batch_run_id: str) -> dict | None:
    run = await crud.get_batch_generation_run(batch_run_id)
    if not run:
        return None
    try:
        import json as _json_mod
        run["modes"] = _json_mod.loads(run.get("modes_json", "[]"))
        run["error_log"] = _json_mod.loads(run.get("error_log_json", "[]"))
    except Exception:
        pass
    # Attach packages generated so far
    packages = await crud.list_workspace_generation_packages(batch_run_id=batch_run_id, limit=200)
    run["packages_count"] = len(packages)
    run["packages"] = [p.get("workspace_generation_package_id") for p in packages]
    return run
