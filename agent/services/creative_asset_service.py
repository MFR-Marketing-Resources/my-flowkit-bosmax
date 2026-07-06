from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.config import BASE_DIR
from agent.db import crud
from agent.models.creative_asset import (
    CreativeAssetCreateRequest,
    CreativeAssetEngineSlot,
    CreativeAssetRecord,
    CreativeAssetUpdateRequest,
    CreativeAssetValidationResult,
)


CREATIVE_ASSET_UPLOAD_DIR = BASE_DIR / ".local-agent" / "creative-assets"
ACTIVE_STATUS = "ACTIVE"
ARCHIVED_STATUS = "ARCHIVED"
AVATAR_ASSET_MARKER = "AVATAR_CODE:"


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
    for _bool_col in (
        "contains_rendered_text",
        "approved_for_video_support",
        "approved_for_poster",
        "is_reusable",
        "is_canonical",
    ):
        if _bool_col in payload:
            payload[_bool_col] = bool(payload.get(_bool_col))
    if payload.get("storage_kind") == "REMOTE_URL" and payload.get("remote_source_url"):
        remote_source_url = str(payload["remote_source_url"])
        preview_url = str(payload.get("preview_url") or "")
        download_url = str(payload.get("download_url") or "")
        if not preview_url or preview_url.startswith("/api/creative-assets/"):
            payload["preview_url"] = remote_source_url
        if not download_url or download_url.startswith("/api/creative-assets/"):
            payload["download_url"] = remote_source_url
    if not payload.get("review_status"):
        payload["review_status"] = "PENDING_REVIEW"
    if not payload.get("asset_lifecycle"):
        payload["asset_lifecycle"] = "SAVED_REUSABLE_ASSET"
    if not payload.get("retention_policy"):
        payload["retention_policy"] = "PERSISTENT"
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


def _extract_avatar_code(description: str | None, explicit_avatar_code: str | None = None) -> str | None:
    if explicit_avatar_code:
        code = explicit_avatar_code.strip().upper()
        if code:
            return code
    match = re.search(r"AVATAR_CODE:([A-Z0-9_]+)", str(description or ""))
    if match:
        return match.group(1).strip().upper()
    return None


def _infer_asset_lifecycle(asset: CreativeAssetRecord) -> str:
    if asset.asset_lifecycle and asset.asset_lifecycle != "SAVED_REUSABLE_ASSET":
        return asset.asset_lifecycle
    if asset.semantic_role == "CHARACTER_REFERENCE" and _extract_avatar_code(
        asset.description,
        asset.avatar_code,
    ):
        return "CANONICAL_AVATAR_ASSET"
    if asset.semantic_role == "PRODUCT_REFERENCE":
        return "CANONICAL_PRODUCT_ASSET"
    return asset.asset_lifecycle or "SAVED_REUSABLE_ASSET"


def audit_creative_asset(asset: CreativeAssetRecord) -> dict[str, Any]:
    local_exists = False
    if asset.local_file_path:
        local_exists = Path(asset.local_file_path).is_file()
    if asset.local_file_path:
        retrievable = local_exists
        integrity_status = "LOCAL_FILE_OK" if local_exists else "LOCAL_FILE_MISSING"
    elif asset.storage_kind == "REMOTE_URL":
        retrievable = bool(asset.preview_url or asset.download_url)
        integrity_status = (
            "REMOTE_REFERENCE_PRESENT"
            if (asset.remote_source_url or asset.preview_url or asset.download_url)
            else "REMOTE_REFERENCE_MISSING"
        )
    elif asset.storage_kind == "MEDIA_ID":
        retrievable = bool(asset.media_id)
        integrity_status = "MEDIA_REFERENCE_READY" if retrievable else "MEDIA_REFERENCE_MISSING"
    elif asset.storage_kind == "PRODUCT_IMAGE_CACHE":
        retrievable = bool(asset.preview_url or asset.download_url)
        if retrievable:
            integrity_status = "PRODUCT_CACHE_REFERENCE_PRESENT"
        elif asset.product_id:
            integrity_status = "PRODUCT_CACHE_PRODUCT_LINK_ONLY"
        else:
            integrity_status = "PRODUCT_CACHE_MISSING"
    else:
        retrievable = bool(asset.preview_url or asset.download_url or asset.remote_source_url)
        integrity_status = "REFERENCE_READY" if retrievable else "REFERENCE_MISSING"

    if retrievable:
        avatar_status = "GENERATED"
    elif asset.local_file_path:
        avatar_status = "MISSING_ASSET"
    elif asset.preview_url or asset.download_url or asset.remote_source_url or asset.media_id:
        avatar_status = "BROKEN_LINK"
    elif asset.description or asset.display_name:
        avatar_status = "GENERATED_METADATA_ONLY"
    else:
        avatar_status = "NEEDS_REGENERATION"

    return {
        "retrievable": retrievable,
        "local_file_exists": local_exists,
        "integrity_status": integrity_status,
        "avatar_status": avatar_status,
    }


def _is_image_library_eligible(
    asset: CreativeAssetRecord,
    *,
    lifecycle: str,
    retrievable: bool,
) -> bool:
    if not retrievable:
        return False
    if lifecycle not in {
        "CANONICAL_AVATAR_ASSET",
        "CANONICAL_PRODUCT_ASSET",
        "SAVED_REUSABLE_ASSET",
    }:
        return False
    return asset.semantic_role in {
        "CHARACTER_REFERENCE",
        "PRODUCT_REFERENCE",
        "SCENE_CONTEXT_REFERENCE",
        "STYLE_REFERENCE",
        "COMPOSITE_FRAME_REFERENCE",
    }


def _fingerprint(asset_id: str, slot_key: str, source_value: str) -> str:
    digest = hashlib.sha1(f"{asset_id}||{slot_key}||{source_value}".encode("utf-8")).hexdigest()
    return f"creative_{digest[:16]}"


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
        asset_lifecycle=request.asset_lifecycle,
        retention_policy=request.retention_policy,
        expires_at=request.expires_at,
        is_reusable=request.is_reusable,
        is_canonical=request.is_canonical,
        source_job_id=request.source_job_id,
        avatar_code=_extract_avatar_code(request.description, request.avatar_code),
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

    blockers: list[str] = []
    if asset.status != ACTIVE_STATUS:
        blockers.append("ASSET_ARCHIVED")
    if asset.semantic_role != semantic_role:
        blockers.append("SEMANTIC_ROLE_MISMATCH")
    if asset.allowed_modes and allowed_mode not in asset.allowed_modes:
        blockers.append("MODE_NOT_ALLOWED")
    if asset.engine_slot_eligibility and engine_slot not in asset.engine_slot_eligibility:
        blockers.append("ENGINE_SLOT_NOT_ALLOWED")
    # Reuse safety: a downstream generation (I2V/F2V) may only consume an asset that
    # has passed operator review. PENDING_REVIEW / REJECTED / DRAFT are NOT reusable.
    if require_approved and asset.review_status != "APPROVED":
        blockers.append("NOT_APPROVED_FOR_REUSE")
    # Poster exclusion: a rendered-text asset (poster ad) must not become a clean
    # video-support frame unless it was explicitly approved for video support.
    if (
        disallow_rendered_text
        and asset.contains_rendered_text
        and not asset.approved_for_video_support
    ):
        blockers.append("RENDERED_TEXT_NOT_ALLOWED_FOR_VIDEO_FRAME")

    return CreativeAssetValidationResult(
        valid=not blockers,
        blockers=blockers,
        warnings=[],
        asset=asset,
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


async def list_avatar_asset_index() -> dict[str, dict[str, Any]]:
    assets = await list_creative_assets(
        semantic_role="CHARACTER_REFERENCE",
        status=ACTIVE_STATUS,
        limit=1000,
    )
    mapping: dict[str, dict[str, Any]] = {}
    for asset in assets:
        avatar_code = _extract_avatar_code(asset.description, asset.avatar_code)
        if not avatar_code:
            continue
        audit = audit_creative_asset(asset)
        payload = {
            "asset_id": asset.asset_id,
            "avatar_code": avatar_code,
            "preview_url": asset.preview_url,
            "download_url": asset.download_url,
            "local_file_path": asset.local_file_path,
            "media_id": asset.media_id,
            "created_at": asset.created_at,
            "display_name": asset.display_name,
            "asset_lifecycle": _infer_asset_lifecycle(asset),
            **audit,
        }
        current = mapping.get(avatar_code)
        if current is None:
            mapping[avatar_code] = payload
            continue
        current_rank = (1 if current.get("retrievable") else 0, str(current.get("created_at") or ""))
        next_rank = (1 if payload["retrievable"] else 0, str(payload.get("created_at") or ""))
        if next_rank > current_rank:
            mapping[avatar_code] = payload
    return mapping


async def list_image_library_items(limit: int = 60, mode: str | None = None) -> dict[str, Any]:
    purged = await crud.purge_expired_artifacts(retention_hours=48)
    temp_rows = await crud.list_generated_artifacts(limit=limit, kind="image", mode=mode)
    temp_items = []
    for row in temp_rows:
        expires_at = None
        expires_in_hours = None
        created_at = str(row.get("created_at") or "")
        if created_at:
            try:
                created = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc,
                )
                expires = created + timedelta(hours=48)
                expires_at = expires.strftime("%Y-%m-%dT%H:%M:%SZ")
                expires_in_hours = max(
                    0,
                    round(
                        (expires - datetime.now(timezone.utc)).total_seconds() / 3600,
                        1,
                    ),
                )
            except ValueError:
                expires_at = None
                expires_in_hours = None
        temp_items.append(
            {
                "library_key": f"artifact:{row['media_id']}",
                "library_source": "TEMP_JOB_OUTPUT",
                "artifact_kind": "image",
                "asset_lifecycle": "TEMP_JOB_OUTPUT",
                "retention_policy": "TEMP_48H",
                "source_asset_id": None,
                "semantic_role": None,
                "avatar_code": None,
                "product_id": None,
                "display_name": row.get("mode") or "Generated Image",
                "media_id": row.get("media_id"),
                "mode": row.get("mode"),
                "size_mb": row.get("size_mb"),
                "local_path": row.get("local_path"),
                "created_at": row.get("created_at"),
                "preview_url": f"/api/flow/retrieved/{row['media_id']}",
                "download_url": f"/api/flow/retrieved/{row['media_id']}",
                "expires_at": expires_at,
                "expires_in_hours": expires_in_hours,
                "integrity_status": "LOCAL_FILE_OK"
                if row.get("local_path") and Path(str(row["local_path"])).is_file()
                else "LOCAL_FILE_MISSING",
            }
        )

    asset_rows = await list_creative_assets(status=ACTIVE_STATUS, limit=1000)
    reusable_items: list[dict[str, Any]] = []
    broken_avatar_assets = 0
    reusable_avatar_assets = 0
    for asset in asset_rows:
        if mode and asset.allowed_modes and mode not in asset.allowed_modes:
            continue
        audit = audit_creative_asset(asset)
        lifecycle = _infer_asset_lifecycle(asset)
        avatar_code = _extract_avatar_code(asset.description, asset.avatar_code)
        if lifecycle == "CANONICAL_AVATAR_ASSET":
            if audit["retrievable"]:
                reusable_avatar_assets += 1
            else:
                broken_avatar_assets += 1
        if not _is_image_library_eligible(
            asset,
            lifecycle=lifecycle,
            retrievable=bool(audit["retrievable"]),
        ):
            continue
        reusable_items.append(
            {
                "library_key": f"creative:{asset.asset_id}",
                "library_source": "CREATIVE_ASSET",
                "artifact_kind": "image",
                "asset_lifecycle": lifecycle,
                "retention_policy": asset.retention_policy,
                "source_asset_id": asset.asset_id,
                "semantic_role": asset.semantic_role,
                "avatar_code": avatar_code,
                "product_id": asset.product_id,
                "display_name": asset.display_name,
                "media_id": asset.media_id,
                "mode": None,
                "size_mb": None,
                "local_path": asset.local_file_path,
                "created_at": asset.created_at,
                "preview_url": asset.preview_url,
                "download_url": asset.download_url or asset.preview_url,
                "expires_at": asset.expires_at,
                "expires_in_hours": None,
                "integrity_status": audit["integrity_status"],
            }
        )

    combined = sorted(
        [*temp_items, *reusable_items],
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )[:limit]
    return {
        "items": combined,
        "diagnostics": {
            "temp_image_outputs": len(temp_items),
            "reusable_image_assets": len(reusable_items),
            "reusable_avatar_assets": reusable_avatar_assets,
            "broken_avatar_assets": broken_avatar_assets,
            "purged_temp_rows": purged["purged_rows"],
        },
    }
