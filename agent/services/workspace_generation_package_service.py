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
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    blocks: list[dict] | None = None,
    start_frame_asset_id: str | None = None,
    start_frame_preview_url: str | None = None,
    start_frame_download_url: str | None = None,
    end_frame_asset_id: str | None = None,
    end_frame_preview_url: str | None = None,
    end_frame_download_url: str | None = None,
    operator_notes: str | None = None,
) -> dict:
    """Create a durable F2V workspace generation package."""
    mode = "F2V"
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    # Compile final prompt via existing UGC compiler (reused — not rewritten)
    compiler_result = await compile_ugc_video_prompt(
        product_id=product_id,
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
    }

    wgp_id = _wgp_id(product_id, mode, "F2V", prompt_fingerprint)

    manual_handoff = _build_manual_handoff(
        mode=mode,
        final_prompt_text=final_prompt_text,
        image_assets=image_assets,
        upload_order=upload_order,
        blockers=blockers,
        warnings=warnings,
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
    )

    row = await crud.create_workspace_generation_package(
        wgp_id,
        mode=mode,
        product_id=product_id,
        product_name_snapshot=product_name_snapshot,
        source_lane="F2V",
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
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    product_reference_asset_id: str | None = None,
    character_reference_asset_id: str | None = None,
    scene_context_reference_asset_id: str | None = None,
    style_reference_asset_id: str | None = None,
    operator_notes: str | None = None,
) -> dict:
    """Create a durable I2V workspace generation package."""
    mode = "I2V"
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))

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
    resolver_output = await resolve_i2v_semantic_slots(resolver_req)

    resolved_slots: list = resolver_output.get("resolved_slots", [])
    resolver_warnings: list = resolver_output.get("warnings", [])
    resolver_blockers: list = resolver_output.get("blockers", [])

    # Build I2V handoff prompt (thin layer on top of compiler/resolver — not a second compiler stack)
    compiler_result = await compile_ugc_video_prompt(
        product_id=product_id,
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

    base_prompt: str = compiler_result.get("final_compiled_prompt_text", "")
    prompt_blocks: list = compiler_result.get("prompt_blocks", [])

    # Inject resolver context into final I2V blended prompt
    compiler_context: str = resolver_output.get("compiler_context_summary", "")
    final_prompt_text = base_prompt
    if compiler_context:
        final_prompt_text = f"{base_prompt}\n\n[I2V Semantic Context]\n{compiler_context}"

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
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
    blocks: list[dict] | None = None,
    operator_notes: str | None = None,
    batch_run_id: str | None = None,
) -> dict:
    """Create a durable T2V workspace generation package (text-only, no frame uploads)."""
    mode = "T2V"
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    compiler_result = await compile_ugc_video_prompt(
        product_id=product_id,
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
    overlay_enabled: bool = True,
    dialogue_enabled: bool = True,
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
) -> dict:
    """Create a durable IMG workspace generation package (image generation mode)."""
    mode = "IMG"
    product_row = await crud.get_product(product_id)
    _assert_not_reference_only(product_id, product_row)
    approved = await get_approved_product_package(product_id, normalize_mode(mode))

    product_name_snapshot = approved.get("product_name", "")
    prompt_package_snapshot_id = approved.get("prompt_package_snapshot_id", "")

    compiler_result = await compile_ugc_video_prompt(
        product_id=product_id,
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

_MODE_CREATORS = {
    "F2V": create_f2v_generation_package,
    "I2V": create_i2v_generation_package,
    "T2V": create_t2v_generation_package,
    "IMG": create_img_generation_package,
}


async def _run_batch_generation_task(
    batch_run_id: str,
    product_id: str,
    modes: list[str],
    quantity_per_mode: int,
    interval_seconds: int,
    generation_mode: str,
) -> None:
    """Background coroutine: generates packages sequentially with interval sleep."""
    completed = 0
    failed = 0
    errors: list[str] = []

    await crud.update_batch_generation_run(batch_run_id, status="RUNNING")

    for mode in modes:
        creator = _MODE_CREATORS.get(mode)
        if not creator:
            errors.append(f"Unsupported mode: {mode}")
            _batch_logger.warning("Batch %s: unsupported mode %s, skipping", batch_run_id, mode)
            continue

        for idx in range(quantity_per_mode):
            try:
                await creator(
                    product_id=product_id,
                    generation_mode=generation_mode,
                    batch_run_id=batch_run_id,
                )
                completed += 1
                _batch_logger.info("Batch %s: %s #%d completed (%d total)", batch_run_id, mode, idx + 1, completed)
            except Exception as exc:
                failed += 1
                errors.append(f"{mode}#{idx+1}: {exc}")
                _batch_logger.error("Batch %s: %s #%d failed: %s", batch_run_id, mode, idx + 1, exc)

            await crud.update_batch_generation_run(
                batch_run_id,
                total_completed=completed,
                total_failed=failed,
                error_log_json=_json(errors[-50:]),
            )

            # Only sleep if more items remain
            remaining = (len(modes) * quantity_per_mode) - (completed + failed)
            if remaining > 0 and interval_seconds > 0:
                await _asyncio.sleep(interval_seconds)

    final_status = "COMPLETED" if failed == 0 else ("FAILED" if completed == 0 else "COMPLETED")
    await crud.update_batch_generation_run(
        batch_run_id,
        status=final_status,
        total_completed=completed,
        total_failed=failed,
        error_log_json=_json(errors[-50:]),
    )
    _batch_logger.info("Batch %s finished: %d completed, %d failed", batch_run_id, completed, failed)


async def start_batch_generation(
    *,
    product_id: str,
    modes: list[str],
    quantity_per_mode: int = 10,
    interval_seconds: int = 5,
    generation_mode: str = "SINGLE",
) -> dict:
    """Create a batch run record and fire the background task. Returns the run record."""
    import json as _json_mod
    batch_run_id = f"bgr_{_fingerprint(product_id, str(modes), str(quantity_per_mode), str(uuid.uuid4()))[:16]}"
    total_expected = len(modes) * quantity_per_mode

    run = await crud.create_batch_generation_run(
        batch_run_id,
        product_id=product_id,
        modes_json=_json_mod.dumps(modes),
        quantity_per_mode=quantity_per_mode,
        interval_seconds=interval_seconds,
        generation_mode=generation_mode,
        total_expected=total_expected,
    )

    # Fire-and-forget background task
    _asyncio.ensure_future(
        _run_batch_generation_task(
            batch_run_id=batch_run_id,
            product_id=product_id,
            modes=modes,
            quantity_per_mode=quantity_per_mode,
            interval_seconds=interval_seconds,
            generation_mode=generation_mode,
        )
    )

    return run


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
