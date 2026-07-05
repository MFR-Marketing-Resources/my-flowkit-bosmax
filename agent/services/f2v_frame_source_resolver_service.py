"""IMG Asset Factory v1 — resolve F2V start/end frame sources.

Selector contract that assembles F2V frames from:
  - the approved product image (start frame),
  - a saved ``COMPOSITE_FRAME_REFERENCE`` creative asset (start or end frame),
  - a manual upload (start or end frame).

Poster / rendered-text assets are excluded from clean video-support frames via
``validate_selectable_asset(..., disallow_rendered_text=True)`` unless explicitly
approved for video support. Start frame is required; end frame is optional.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agent.models.creative_asset import CreativeAssetRecord
from agent.models.f2v_frame_source_resolver import (
    F2VFrameSourceResolverRequest,
    F2VFrameSourceResolverResponse,
    F2VResolvedFrame,
)
from agent.services.approved_product_package_service import get_approved_product_package
from agent.services.creative_asset_service import validate_selectable_asset


def _fingerprint(*parts: str) -> str:
    return "frame_" + hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


def _frame_from_asset(asset: CreativeAssetRecord, slot_key: str) -> F2VResolvedFrame:
    source_value = (
        asset.local_file_path or asset.download_url or asset.preview_url or asset.asset_id
    )
    return F2VResolvedFrame(
        slot_key=slot_key,  # type: ignore[arg-type]
        source_kind="COMPOSITE_FRAME_REFERENCE",
        asset_id=asset.asset_id,
        display_name=asset.display_name,
        asset_fingerprint=_fingerprint(asset.asset_id, slot_key, str(source_value)),
        preview_url=asset.preview_url,
        download_url=asset.download_url,
        media_id=asset.media_id,
        local_file_path=asset.local_file_path,
    )


async def _resolve_product_start_frame(product_id: str) -> F2VResolvedFrame | None:
    try:
        package = await get_approved_product_package(product_id, "F2V")
    except Exception:
        return None
    slots = package.get("asset_slots", []) if isinstance(package, dict) else []
    slot = next(
        (
            s
            for s in slots
            if s.get("slot_key") == "start_frame" and s.get("resolved_asset")
        ),
        None,
    )
    if not slot:
        return None
    resolved: dict[str, Any] = slot["resolved_asset"]
    return F2VResolvedFrame(
        slot_key="start_frame",
        source_kind="PRODUCT_IMAGE",
        asset_id=resolved.get("asset_id"),
        display_name=resolved.get("label"),
        asset_fingerprint=resolved.get("asset_fingerprint"),
        preview_url=resolved.get("preview_url"),
        download_url=resolved.get("download_url"),
        media_id=resolved.get("media_id"),
        local_file_path=resolved.get("local_file_path"),
    )


async def resolve_f2v_frame_sources(
    request: F2VFrameSourceResolverRequest,
) -> F2VFrameSourceResolverResponse:
    blockers: list[str] = []
    warnings: list[str] = []
    start_frame: F2VResolvedFrame | None = None
    end_frame: F2VResolvedFrame | None = None

    # ── Start frame (required) ──────────────────────────────────────────────
    if request.start_frame_asset_id:
        validation = await validate_selectable_asset(
            request.start_frame_asset_id,
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            allowed_mode="F2V",
            engine_slot="start_frame",
            disallow_rendered_text=True,
            require_approved=True,
        )
        if not validation.valid or validation.asset is None:
            blockers.extend([f"START_FRAME_{item}" for item in validation.blockers])
        else:
            start_frame = _frame_from_asset(validation.asset, "start_frame")
    elif request.start_frame_manual_upload_present:
        start_frame = F2VResolvedFrame(slot_key="start_frame", source_kind="MANUAL_UPLOAD")
    elif request.use_product_image_as_start and request.product_id:
        start_frame = await _resolve_product_start_frame(request.product_id)
        if start_frame is None:
            blockers.append("START_FRAME_PRODUCT_IMAGE_MISSING")
    else:
        blockers.append("START_FRAME_REQUIRED")

    # ── End frame (optional) ────────────────────────────────────────────────
    if request.end_frame_asset_id:
        validation = await validate_selectable_asset(
            request.end_frame_asset_id,
            semantic_role="COMPOSITE_FRAME_REFERENCE",
            allowed_mode="F2V",
            engine_slot="end_frame",
            disallow_rendered_text=True,
            require_approved=True,
        )
        if not validation.valid or validation.asset is None:
            blockers.extend([f"END_FRAME_{item}" for item in validation.blockers])
        else:
            end_frame = _frame_from_asset(validation.asset, "end_frame")
    elif request.end_frame_manual_upload_present:
        end_frame = F2VResolvedFrame(slot_key="end_frame", source_kind="MANUAL_UPLOAD")
    else:
        warnings.append("END_FRAME_OPTIONAL_NOT_SELECTED")

    resolved_frames = [frame for frame in (start_frame, end_frame) if frame is not None]
    return F2VFrameSourceResolverResponse(
        start_frame=start_frame,
        end_frame=end_frame,
        resolved_frames=resolved_frames,
        warnings=warnings,
        blockers=sorted(set(blockers)),
    )
