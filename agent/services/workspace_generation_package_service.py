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
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
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
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
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
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
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
    overlay_enabled: bool = False,  # NO_OVERLAY law (ADR-008)
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
    prompt_override: str | None = None,
) -> dict:
    """Create a durable IMG workspace generation package (image generation mode)."""
    mode = "IMG"
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
