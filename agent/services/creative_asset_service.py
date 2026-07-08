from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from agent.config import BASE_DIR
from agent.db import crud
from agent.models.creative_asset import (
    CreativeAssetCreateRequest,
    CreativeAssetEngineSlot,
    CreativeAssetEligibilityAuditResponse,
    CreativeAssetEligibilityAuditSurface,
    CreativeAssetRecord,
    CreativeAssetUpdateRequest,
    CreativeAssetValidationResult,
)
from agent.services.i2v_slot_recipe_config import get_i2v_slot_recipe


CREATIVE_ASSET_UPLOAD_DIR = BASE_DIR / ".local-agent" / "creative-assets"
ACTIVE_STATUS = "ACTIVE"
ARCHIVED_STATUS = "ARCHIVED"
APPROVED_REVIEW_STATUS = "APPROVED"
DEFAULT_I2V_RECIPE_ID = "PRODUCT_HELD_BY_CHARACTER_IN_SCENE"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def _parse_json_text(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _normalize_record(row: dict[str, Any]) -> CreativeAssetRecord:
    payload = dict(row)
    payload["allowed_modes"] = _parse_json_text(payload.get("allowed_modes"), [])
    payload["engine_slot_eligibility"] = _parse_json_text(
        payload.get("engine_slot_eligibility"),
        [],
    )
    payload["mode_a_metadata_handoff"] = _parse_json_text(
        payload.get("mode_a_metadata_handoff"),
        payload.get("mode_a_metadata_handoff"),
    )
    # SQLite stores the governance booleans as INTEGER 0/1 — coerce to bool so the
    # record contract stays truthful (and never leaks a raw int downstream).
    for _bool_col in ("contains_rendered_text", "approved_for_video_support", "approved_for_poster"):
        if _bool_col in payload:
            payload[_bool_col] = bool(payload.get(_bool_col))
    if not payload.get("review_status"):
        payload["review_status"] = "PENDING_REVIEW"
    return CreativeAssetRecord(**payload)


def _asset_file_path(asset_id: str, file_name: str | None, mime_type: str | None = None) -> Path:
    guessed_ext = Path(file_name or "").suffix
    if not guessed_ext and mime_type:
        guessed_ext = mimetypes.guess_extension(mime_type) or ""
    if not guessed_ext:
        guessed_ext = ".png"
    CREATIVE_ASSET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return CREATIVE_ASSET_UPLOAD_DIR / f"{asset_id}{guessed_ext.lower()}"


def _decode_base64_image(image_base64: str) -> tuple[bytes, str | None]:
    stripped = image_base64.strip()
    mime_type = None
    if stripped.startswith("data:") and "," in stripped:
        header, stripped = stripped.split(",", 1)
        if ";base64" in header:
            mime_type = header[5:].split(";", 1)[0]
    return base64.b64decode(stripped), mime_type


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _build_local_preview_url(asset_id: str) -> str:
    return f"/api/creative-assets/{asset_id}/preview"


def _build_local_download_url(asset_id: str) -> str:
    return f"/api/creative-assets/{asset_id}/download"


def _fingerprint(asset_id: str, slot_key: str, source_value: str) -> str:
    digest = hashlib.sha1(f"{asset_id}||{slot_key}||{source_value}".encode("utf-8")).hexdigest()
    return f"creative_{digest[:16]}"


def _asset_has_resolvable_source(asset: CreativeAssetRecord) -> bool:
    return bool(
        asset.local_file_path
        or asset.preview_url
        or asset.download_url
        or asset.remote_source_url
        or asset.media_id
    )


def _collect_selectable_asset_blockers(
    asset: CreativeAssetRecord,
    *,
    semantic_role: str,
    allowed_mode: str,
    engine_slot: CreativeAssetEngineSlot,
    disallow_rendered_text: bool = False,
    require_approved: bool = False,
) -> list[str]:
    blockers: list[str] = []
    if asset.status != ACTIVE_STATUS:
        blockers.append("ASSET_ARCHIVED")
    if asset.semantic_role != semantic_role:
        blockers.append("SEMANTIC_ROLE_MISMATCH")
    if asset.allowed_modes and allowed_mode not in asset.allowed_modes:
        blockers.append("MODE_NOT_ALLOWED")
    if asset.engine_slot_eligibility and engine_slot not in asset.engine_slot_eligibility:
        blockers.append("ENGINE_SLOT_NOT_ALLOWED")
    if require_approved and asset.review_status != APPROVED_REVIEW_STATUS:
        blockers.append("NOT_APPROVED_FOR_REUSE")
    if (
        disallow_rendered_text
        and asset.contains_rendered_text
        and not asset.approved_for_video_support
    ):
        blockers.append("RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME")
    if not _asset_has_resolvable_source(asset):
        blockers.append("PREVIEW_OR_FILE_MISSING")
    return blockers


def _get_audit_surface_spec(
    surface: CreativeAssetEligibilityAuditSurface,
    recipe_id: str | None,
) -> dict[str, Any]:
    if surface == "F2V_START_FRAME_PICKER":
        return {
            "surface_label": "F2V Start Frame Picker",
            "required_semantic_role": "COMPOSITE_FRAME_REFERENCE",
            "required_allowed_mode": "F2V",
            "required_engine_slot": "start_frame",
            "disallow_rendered_text": True,
            "require_approved": True,
            "resolved_recipe_id": None,
        }
    if surface == "F2V_END_FRAME_PICKER":
        return {
            "surface_label": "F2V End Frame Picker",
            "required_semantic_role": "COMPOSITE_FRAME_REFERENCE",
            "required_allowed_mode": "F2V",
            "required_engine_slot": "end_frame",
            "disallow_rendered_text": True,
            "require_approved": True,
            "resolved_recipe_id": None,
        }
    if surface == "HYBRID_START_FRAME_PICKER":
        return {
            "surface_label": "Hybrid Start Frame Picker",
            "required_semantic_role": "COMPOSITE_FRAME_REFERENCE",
            "required_allowed_mode": "F2V",
            "required_engine_slot": "start_frame",
            "disallow_rendered_text": True,
            "require_approved": True,
            "resolved_recipe_id": None,
        }
    if surface == "HYBRID_END_FRAME_PICKER":
        return {
            "surface_label": "Hybrid End Frame Picker",
            "required_semantic_role": "COMPOSITE_FRAME_REFERENCE",
            "required_allowed_mode": "F2V",
            "required_engine_slot": "end_frame",
            "disallow_rendered_text": True,
            "require_approved": True,
            "resolved_recipe_id": None,
        }

    resolved_recipe_id = recipe_id or DEFAULT_I2V_RECIPE_ID
    recipe = get_i2v_slot_recipe(resolved_recipe_id)
    role_key = {
        "I2V_CHARACTER_PICKER": "character_reference",
        "I2V_SCENE_PICKER": "scene_context_reference",
        "I2V_STYLE_PICKER": "style_reference",
    }.get(surface)
    if role_key is None:
        raise ValueError("CREATIVE_ASSET_AUDIT_SURFACE_UNSUPPORTED")
    mapped_slot = next(
        (
            slot_key
            for slot_key, mapped_role in recipe["engine_slot_mapping"].items()
            if mapped_role == role_key
        ),
        "style",
    )
    return {
        "surface_label": {
            "I2V_CHARACTER_PICKER": "I2V Character Picker",
            "I2V_SCENE_PICKER": "I2V Scene Context Picker",
            "I2V_STYLE_PICKER": "I2V Style Picker",
        }[surface],
        "required_semantic_role": {
            "character_reference": "CHARACTER_REFERENCE",
            "scene_context_reference": "SCENE_CONTEXT_REFERENCE",
            "style_reference": "STYLE_REFERENCE",
        }[role_key],
        "required_allowed_mode": "I2V",
        "required_engine_slot": mapped_slot,
        "disallow_rendered_text": False,
        "require_approved": True,
        "resolved_recipe_id": resolved_recipe_id,
    }


def _auto_generate_metadata_handoff(
    *,
    asset_id: str,
    display_name: str,
    semantic_role: str,
    description: str | None,
    allowed_modes: list[str],
    engine_slot_eligibility: list[str],
) -> str:
    """Auto-derive mode_a_metadata_handoff from asset fields so the user never has to fill it manually."""
    payload: dict[str, Any] = {
        "asset_id": asset_id,
        "display_name": display_name,
        "semantic_role": semantic_role,
        "allowed_modes": allowed_modes,
        "engine_slot_eligibility": engine_slot_eligibility,
        "auto_generated": True,
    }
    if description:
        payload["description"] = description.strip()
        # Derive role-specific hint keys from the description text for prompt injection
        desc_lower = description.lower()
        if semantic_role == "CHARACTER_REFERENCE":
            payload["role_hint"] = "avatar_character"
            payload["inject_as"] = "character_reference_description"
        elif semantic_role == "SCENE_CONTEXT_REFERENCE":
            payload["role_hint"] = "scene_background"
            payload["inject_as"] = "scene_context_description"
        elif semantic_role == "STYLE_REFERENCE":
            payload["role_hint"] = "visual_style"
            payload["inject_as"] = "style_reference_description"
        elif semantic_role == "PRODUCT_REFERENCE":
            payload["role_hint"] = "product_subject"
            payload["inject_as"] = "product_reference_description"
        elif semantic_role == "COMPOSITE_FRAME_REFERENCE":
            payload["role_hint"] = "composite_frame"
            payload["inject_as"] = "frame_reference_description"
    return _json_text(payload)


async def create_creative_asset(request: CreativeAssetCreateRequest) -> CreativeAssetRecord:
    asset_id = f"ca_{uuid.uuid4().hex[:16]}"
    preview_url = _normalize_optional_text(request.preview_url)
    download_url = _normalize_optional_text(request.download_url)
    local_file_path = _normalize_optional_text(request.local_file_path)
    remote_source_url = _normalize_optional_text(request.remote_source_url)
    media_id = _normalize_optional_text(request.media_id)

    if request.image_base64:
        raw_bytes, mime_type = _decode_base64_image(request.image_base64)
        target = _asset_file_path(asset_id, request.file_name, mime_type)
        target.write_bytes(raw_bytes)
        local_file_path = str(target)
        preview_url = _build_local_preview_url(asset_id)
        download_url = _build_local_download_url(asset_id)
    elif request.storage_kind == "REMOTE_URL":
        if not (remote_source_url or preview_url or download_url):
            raise ValueError("REMOTE_SOURCE_URL_REQUIRED")
        remote_source_url = remote_source_url or preview_url or download_url
        preview_url = preview_url or remote_source_url
        download_url = download_url or remote_source_url
    elif request.storage_kind == "MEDIA_ID":
        if not media_id:
            raise ValueError("MEDIA_ID_REQUIRED")
    elif request.storage_kind == "PRODUCT_IMAGE_CACHE":
        if not request.product_id:
            raise ValueError("PRODUCT_ID_REQUIRED")
        preview_url = preview_url or f"/api/products/{request.product_id}/image"
        download_url = download_url or f"/api/products/{request.product_id}/image"
    elif request.storage_kind == "LOCAL_FILE":
        if not local_file_path:
            raise ValueError("LOCAL_FILE_REQUIRED")

    # Auto-generate mode_a_metadata_handoff from asset fields if caller did not supply one
    if request.mode_a_metadata_handoff is None:
        _handoff_value = _auto_generate_metadata_handoff(
            asset_id=asset_id,
            display_name=request.display_name,
            semantic_role=request.semantic_role,
            description=request.description,
            allowed_modes=request.allowed_modes,
            engine_slot_eligibility=request.engine_slot_eligibility,
        )
    else:
        _handoff_value = (
            _json_text(request.mode_a_metadata_handoff)
            if isinstance(request.mode_a_metadata_handoff, dict)
            else request.mode_a_metadata_handoff
        )

    row = await crud.create_creative_asset(
        asset_id=asset_id,
        semantic_role=request.semantic_role,
        display_name=request.display_name,
        description=request.description,
        source_type=request.source_type,
        storage_kind=request.storage_kind,
        preview_url=preview_url,
        download_url=download_url,
        media_id=media_id,
        local_file_path=local_file_path,
        remote_source_url=remote_source_url,
        product_id=request.product_id,
        category=request.category,
        silo=request.silo,
        product_type=request.product_type,
        allowed_modes=_json_text(request.allowed_modes),
        engine_slot_eligibility=_json_text(request.engine_slot_eligibility),
        mode_a_metadata_handoff=_handoff_value,
        visual_dna_summary=request.visual_dna_summary,
        character_dna=request.character_dna,
        scene_context_dna=request.scene_context_dna,
        style_mood_dna=request.style_mood_dna,
        source_prompt_fingerprint=request.source_prompt_fingerprint,
        source_workspace_execution_package_id=request.source_workspace_execution_package_id,
        source_prompt_package_snapshot_id=request.source_prompt_package_snapshot_id,
        asset_subtype=request.asset_subtype,
        generation_recipe_id=request.generation_recipe_id,
        source_character_asset_id=request.source_character_asset_id,
        source_scene_asset_id=request.source_scene_asset_id,
        source_style_asset_id=request.source_style_asset_id,
        contains_rendered_text=request.contains_rendered_text,
        approved_for_video_support=request.approved_for_video_support,
        approved_for_poster=request.approved_for_poster,
        product_truth_status=request.product_truth_status,
        identity_lock_status=request.identity_lock_status,
        scale_truth_status=request.scale_truth_status,
        claim_safety_status=request.claim_safety_status,
        review_status=request.review_status,
        status=ACTIVE_STATUS,
    )
    return _normalize_record(row)


async def list_creative_assets(
    *,
    semantic_role: str | None = None,
    status: str | None = None,
    allowed_mode: str | None = None,
    engine_slot: CreativeAssetEngineSlot | None = None,
    product_id: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[CreativeAssetRecord]:
    rows = await crud.list_creative_assets(
        semantic_role=semantic_role,
        status=status,
        product_id=product_id,
        search=search,
        limit=limit,
    )
    items = [_normalize_record(row) for row in rows]
    filtered: list[CreativeAssetRecord] = []
    for item in items:
        if allowed_mode and item.allowed_modes and allowed_mode not in item.allowed_modes:
            continue
        if engine_slot and item.engine_slot_eligibility and engine_slot not in item.engine_slot_eligibility:
            continue
        filtered.append(item)
    return filtered


async def get_creative_asset(asset_id: str) -> CreativeAssetRecord | None:
    row = await crud.get_creative_asset(asset_id)
    if not row:
        return None
    return _normalize_record(row)


async def update_creative_asset(
    asset_id: str,
    request: CreativeAssetUpdateRequest,
) -> CreativeAssetRecord:
    current = await crud.get_creative_asset(asset_id)
    if not current:
        raise ValueError("CREATIVE_ASSET_NOT_FOUND")
    payload = request.model_dump(exclude_unset=True)
    if "allowed_modes" in payload:
        payload["allowed_modes"] = _json_text(payload["allowed_modes"])
    if "engine_slot_eligibility" in payload:
        payload["engine_slot_eligibility"] = _json_text(payload["engine_slot_eligibility"])
    if "mode_a_metadata_handoff" in payload and isinstance(payload["mode_a_metadata_handoff"], dict):
        payload["mode_a_metadata_handoff"] = _json_text(payload["mode_a_metadata_handoff"])
    row = await crud.update_creative_asset(asset_id, **payload)
    return _normalize_record(row)


async def archive_creative_asset(asset_id: str) -> CreativeAssetRecord:
    row = await crud.update_creative_asset(asset_id, status=ARCHIVED_STATUS)
    if not row:
        raise ValueError("CREATIVE_ASSET_NOT_FOUND")
    return _normalize_record(row)


async def unarchive_creative_asset(asset_id: str) -> CreativeAssetRecord:
    row = await crud.update_creative_asset(asset_id, status=ACTIVE_STATUS)
    if not row:
        raise ValueError("CREATIVE_ASSET_NOT_FOUND")
    return _normalize_record(row)


async def validate_selectable_asset(
    asset_id: str,
    *,
    semantic_role: str,
    allowed_mode: str,
    engine_slot: CreativeAssetEngineSlot,
    disallow_rendered_text: bool = False,
    require_approved: bool = False,
) -> CreativeAssetValidationResult:
    asset = await get_creative_asset(asset_id)
    if not asset:
        return CreativeAssetValidationResult(
            valid=False,
            blockers=["ASSET_NOT_FOUND"],
            warnings=[],
            asset=None,
        )

    blockers = _collect_selectable_asset_blockers(
        asset,
        semantic_role=semantic_role,
        allowed_mode=allowed_mode,
        engine_slot=engine_slot,
        disallow_rendered_text=disallow_rendered_text,
        require_approved=require_approved,
    )

    return CreativeAssetValidationResult(
        valid=not blockers,
        blockers=blockers,
        warnings=[],
        asset=asset,
    )


async def get_creative_asset_eligibility_audit(
    *,
    surface: CreativeAssetEligibilityAuditSurface,
    recipe_id: str | None = None,
    limit: int = 1000,
) -> CreativeAssetEligibilityAuditResponse:
    spec = _get_audit_surface_spec(surface, recipe_id)
    items = await list_creative_assets(limit=limit)
    total_assets_by_semantic_role = Counter(item.semantic_role for item in items)
    matching_role_items = [
        item for item in items if item.semantic_role == spec["required_semantic_role"]
    ]
    review_status_counts = Counter(item.review_status for item in matching_role_items)
    excluded_by_reason: Counter[str] = Counter()
    eligible_assets: list[CreativeAssetRecord] = []
    excluded_count = 0

    for item in matching_role_items:
        blockers = _collect_selectable_asset_blockers(
            item,
            semantic_role=spec["required_semantic_role"],
            allowed_mode=spec["required_allowed_mode"],
            engine_slot=spec["required_engine_slot"],
            disallow_rendered_text=spec["disallow_rendered_text"],
            require_approved=spec["require_approved"],
        )
        if blockers:
            excluded_count += 1
            for blocker in set(blockers):
                excluded_by_reason[blocker] += 1
            continue
        eligible_assets.append(item)

    eligible_assets.sort(key=lambda item: (item.display_name.lower(), item.asset_id))

    return CreativeAssetEligibilityAuditResponse(
        surface=surface,
        surface_label=spec["surface_label"],
        recipe_id=spec["resolved_recipe_id"],
        required_semantic_role=spec["required_semantic_role"],
        required_allowed_mode=spec["required_allowed_mode"],
        required_engine_slots=[spec["required_engine_slot"]],
        library_total_count=len(items),
        total_assets_by_semantic_role=dict(total_assets_by_semantic_role),
        matching_role_total_count=len(matching_role_items),
        active_count=sum(1 for item in matching_role_items if item.status == ACTIVE_STATUS),
        approved_count=sum(
            1
            for item in matching_role_items
            if item.review_status == APPROVED_REVIEW_STATUS
        ),
        eligible_count=len(eligible_assets),
        excluded_count=excluded_count,
        review_status_counts=dict(review_status_counts),
        excluded_by_reason=dict(excluded_by_reason),
        eligible_assets=eligible_assets,
    )


async def get_creative_asset_file_path(asset_id: str) -> Path | None:
    asset = await get_creative_asset(asset_id)
    if not asset or not asset.local_file_path:
        return None
    path = Path(asset.local_file_path)
    if not path.exists():
        return None
    return path


def build_resolved_workspace_asset(
    *,
    asset: CreativeAssetRecord,
    slot_key: str,
) -> dict[str, Any]:
    source_value = (
        asset.local_file_path
        or asset.remote_source_url
        or asset.preview_url
        or asset.media_id
        or asset.asset_id
    )
    return {
        "asset_id": asset.asset_id,
        "asset_fingerprint": _fingerprint(asset.asset_id, slot_key, source_value),
        "slot_key": slot_key,
        "asset_source": asset.source_type,
        "label": asset.display_name,
        "file_name": Path(asset.local_file_path or asset.download_url or asset.preview_url or asset.asset_id).name,
        "preview_url": asset.preview_url,
        "download_url": asset.download_url,
        "media_id": asset.media_id,
        "local_file_path": asset.local_file_path,
        "preview_renderable_status": "RENDERABLE" if asset.preview_url else "NOT_AVAILABLE",
        "preview_error_detail": None if asset.preview_url else "Preview URL is not available.",
        "local_image_path_present": bool(asset.local_file_path),
        "remote_image_url_present": bool(asset.remote_source_url),
    }
