"""IMG Asset Factory v1 — save an approved, real IMG output into the Library.

This is the governance bridge between a REAL image output and the Creative
Library. It:
  - requires EXACTLY ONE real output source (a finished ``generated_artifact``
    image OR uploaded base64 bytes) — never zero, never both, never fabricated,
  - verifies the bound product and any supplied lineage assets actually exist
    (correct ACTIVE status + semantic role) before writing anything,
  - derives ``semantic_role`` / ``allowed_modes`` / ``engine_slot_eligibility`` /
    rendered-text / poster classification from the LANE (operator cannot mislabel
    a poster as a clean frame),
  - refuses to mark an asset APPROVED while its truth/safety gates are still
    UNVERIFIED.
"""

from __future__ import annotations

import base64
from pathlib import Path

from agent.db import crud
from agent.models.creative_asset import CreativeAssetCreateRequest, CreativeAssetRecord
from agent.models.img_asset_factory import (
    ImgAssetLaneSummary,
    ImgProviderStatusResponse,
    SaveImgOutputRequest,
)
from agent.services.creative_asset_service import create_creative_asset, get_creative_asset
from agent.services.img_asset_lane_config import (
    derive_asset_governance,
    get_img_asset_lane,
    list_img_asset_lanes,
    validate_img_lane_inputs,
)


def list_img_lane_summaries() -> list[ImgAssetLaneSummary]:
    return [ImgAssetLaneSummary(**lane) for lane in list_img_asset_lanes()]


def get_img_provider_status() -> ImgProviderStatusResponse:
    """Honest report of the IMG generation runtime boundary.

    This PR ships and tests the save-to-library governance ONLY. Image
    GENERATION itself runs through the pre-existing API-first lane
    (``POST /api/flow/execute-flow-job`` with ``mode=IMG``), which is NOT
    re-proven with live/runtime evidence in this PR — hence the deliberately
    conservative state.
    """
    return ImgProviderStatusResponse(
        provider_state="SAVE_TO_LIBRARY_READY_GENERATION_RUNTIME_EXTERNAL",
        detail=(
            "Save-to-library governance is ready and unit-tested here. Image "
            "generation runs through the external pre-existing API-first lane and "
            "is NOT re-verified with runtime evidence in this PR. The factory only "
            "accepts REAL outputs (a generated_artifact image or an upload)."
        ),
        generation_endpoint="/api/flow/execute-flow-job",
        extra={"mode": "IMG", "save_endpoint": "/api/img-factory/save"},
    )


async def _resolve_real_output(
    request: SaveImgOutputRequest,
) -> tuple[str, str | None, str]:
    """Return ``(image_base64, file_name, source_type)`` from EXACTLY ONE real
    output source. Fail closed on zero or on more-than-one source."""
    has_artifact = bool(request.generated_artifact_media_id)
    has_base64 = bool(request.image_base64)
    if has_artifact and has_base64:
        raise ValueError("MULTIPLE_OUTPUT_SOURCES_NOT_ALLOWED")
    if not has_artifact and not has_base64:
        raise ValueError("NO_REAL_OUTPUT_SOURCE")

    if has_artifact:
        artifact = await crud.get_generated_artifact(request.generated_artifact_media_id)
        if not artifact:
            raise ValueError("GENERATED_ARTIFACT_NOT_FOUND")
        if str(artifact.get("artifact_kind")) != "image":
            raise ValueError("ARTIFACT_NOT_AN_IMAGE")
        local_path = artifact.get("local_path")
        if not local_path or not Path(local_path).exists():
            raise ValueError("ARTIFACT_FILE_MISSING")
        raw = Path(local_path).read_bytes()
        encoded = base64.b64encode(raw).decode("ascii")
        return encoded, request.file_name or Path(local_path).name, "GENERATED_IMAGE"

    return request.image_base64, request.file_name, "UPLOAD"


async def _lineage_blocker(
    asset_id: str | None,
    *,
    expected_role: str,
    blocker: str,
) -> str | None:
    """Return ``blocker`` when a supplied lineage asset is missing / archived /
    the wrong semantic role; ``None`` when absent or valid."""
    if not asset_id:
        return None
    asset = await get_creative_asset(asset_id)
    if asset is None or asset.status != "ACTIVE" or asset.semantic_role != expected_role:
        return blocker
    return None


async def save_img_output_to_library(request: SaveImgOutputRequest) -> CreativeAssetRecord:
    # Lane must exist (fail closed on unknown lane).
    governance = derive_asset_governance(request.lane_id)
    lane = get_img_asset_lane(request.lane_id)

    # Lane input requirements (e.g. product-truth lanes require a product_id).
    input_blockers = validate_img_lane_inputs(
        request.lane_id,
        product_id=request.product_id,
        character_reference_asset_id=request.source_character_asset_id,
        scene_reference_asset_id=request.source_scene_asset_id,
        style_reference_asset_id=request.source_style_asset_id,
    )
    if input_blockers:
        raise ValueError("IMG_LANE_INPUT_BLOCKED:" + ",".join(input_blockers))

    # The bound product must actually exist — never bottom out in a DB FK 500.
    if lane["requires_product_id"]:
        product = await crud.get_product(request.product_id)
        if product is None:
            raise ValueError("PRODUCT_NOT_FOUND")

    # Supplied lineage assets must exist, be ACTIVE, and carry the right role.
    lineage_blockers = [
        b
        for b in (
            await _lineage_blocker(
                request.source_character_asset_id,
                expected_role="CHARACTER_REFERENCE",
                blocker="SOURCE_CHARACTER_ASSET_INVALID",
            ),
            await _lineage_blocker(
                request.source_scene_asset_id,
                expected_role="SCENE_CONTEXT_REFERENCE",
                blocker="SOURCE_SCENE_ASSET_INVALID",
            ),
            await _lineage_blocker(
                request.source_style_asset_id,
                expected_role="STYLE_REFERENCE",
                blocker="SOURCE_STYLE_ASSET_INVALID",
            ),
        )
        if b is not None
    ]
    if lineage_blockers:
        raise ValueError(",".join(lineage_blockers))

    image_base64, file_name, source_type = await _resolve_real_output(request)

    # Product truth is derived, not operator-set: PRESERVED only when a product
    # is actually bound to the asset; otherwise NOT_APPLICABLE.
    product_truth_status = "PRESERVED" if request.product_id else "NOT_APPLICABLE"
    identity_lock_status = request.identity_lock_status or "UNVERIFIED"
    scale_truth_status = request.scale_truth_status or "UNVERIFIED"
    claim_safety_status = request.claim_safety_status or "UNVERIFIED"

    # An asset can never be silently APPROVED while its truth/safety gates are
    # UNVERIFIED — approval requires an explicit operator truth review.
    if request.review_status == "APPROVED" and "UNVERIFIED" in (
        identity_lock_status,
        scale_truth_status,
        claim_safety_status,
    ):
        raise ValueError("APPROVAL_REQUIRES_TRUTH_REVIEW")

    create_request = CreativeAssetCreateRequest(
        semantic_role=governance["semantic_role"],  # type: ignore[arg-type]
        display_name=request.display_name,
        description=request.description,
        source_type=source_type,  # type: ignore[arg-type]
        storage_kind="LOCAL_FILE",
        product_id=request.product_id,
        category=request.category,
        silo=request.silo,
        product_type=request.product_type,
        allowed_modes=governance["allowed_modes"],
        engine_slot_eligibility=governance["engine_slot_eligibility"],
        source_prompt_fingerprint=request.source_prompt_fingerprint,
        source_workspace_execution_package_id=request.source_workspace_execution_package_id,
        source_prompt_package_snapshot_id=request.source_prompt_package_snapshot_id,
        asset_subtype=governance["asset_subtype"],
        generation_recipe_id=governance["generation_recipe_id"],
        source_character_asset_id=request.source_character_asset_id,
        source_scene_asset_id=request.source_scene_asset_id,
        source_style_asset_id=request.source_style_asset_id,
        contains_rendered_text=governance["contains_rendered_text"],
        approved_for_video_support=governance["approved_for_video_support"],
        approved_for_poster=governance["approved_for_poster"],
        product_truth_status=product_truth_status,
        identity_lock_status=identity_lock_status,
        scale_truth_status=scale_truth_status,
        claim_safety_status=claim_safety_status,
        review_status=request.review_status,
        image_base64=image_base64,
        file_name=file_name,
    )
    return await create_creative_asset(create_request)
