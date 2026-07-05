"""IMG Asset Factory v1 — save an approved, real IMG output into the Library.

This is the governance bridge between a REAL image output and the Creative
Library. It:
  - derives ``semantic_role`` / ``allowed_modes`` / ``engine_slot_eligibility`` /
    rendered-text / poster classification from the LANE (operator cannot
    mislabel a poster as a clean frame),
  - records lineage (product / avatar / scene / style / prompt fingerprint /
    workspace package / lane id),
  - fails closed unless a REAL output is supplied (a finished
    ``generated_artifact`` image, or real uploaded base64 bytes) — it never
    fabricates a generation.
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
from agent.services.creative_asset_service import create_creative_asset
from agent.services.img_asset_lane_config import (
    derive_asset_governance,
    list_img_asset_lanes,
    validate_img_lane_inputs,
)


def list_img_lane_summaries() -> list[ImgAssetLaneSummary]:
    return [ImgAssetLaneSummary(**lane) for lane in list_img_asset_lanes()]


def get_img_provider_status() -> ImgProviderStatusResponse:
    """Honest report of the IMG generation runtime boundary.

    IMG generation itself runs through the proven API-first lane
    (``POST /api/flow/execute-flow-job`` with ``mode=IMG`` ->
    ``make_video.start_generate``), which was live-proven end-to-end. The Asset
    Factory adds review + save + reuse governance ON TOP of that real lane — it
    does not introduce (or fake) a separate image provider.
    """
    return ImgProviderStatusResponse(
        provider_state="RUNTIME_PROVEN",
        detail=(
            "IMG generation runs through the proven API-first lane; the Asset "
            "Factory governs review, save-to-library, and reuse of REAL outputs "
            "only. No separate/fake image provider is introduced."
        ),
        generation_endpoint="/api/flow/execute-flow-job",
        extra={"mode": "IMG", "save_endpoint": "/api/img-factory/save"},
    )


async def _resolve_real_output(
    request: SaveImgOutputRequest,
) -> tuple[str, str | None, str]:
    """Return ``(image_base64, file_name, source_type)`` from a REAL output.

    Fail closed if neither a real image artifact nor real bytes are supplied.
    """
    if request.generated_artifact_media_id:
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

    if request.image_base64:
        return request.image_base64, request.file_name, "UPLOAD"

    raise ValueError("NO_REAL_OUTPUT_SOURCE")


async def save_img_output_to_library(request: SaveImgOutputRequest) -> CreativeAssetRecord:
    # Lane must exist (fail closed on unknown lane).
    governance = derive_asset_governance(request.lane_id)

    # Lane input requirements (e.g. product-truth lanes require a product_id).
    blockers = validate_img_lane_inputs(
        request.lane_id,
        product_id=request.product_id,
        character_reference_asset_id=request.source_character_asset_id,
        scene_reference_asset_id=request.source_scene_asset_id,
        style_reference_asset_id=request.source_style_asset_id,
    )
    if blockers:
        raise ValueError("IMG_LANE_INPUT_BLOCKED:" + ",".join(blockers))

    image_base64, file_name, source_type = await _resolve_real_output(request)

    # Product truth is derived, not operator-set: PRESERVED only when a product
    # is actually bound to the asset; otherwise NOT_APPLICABLE.
    product_truth_status = "PRESERVED" if request.product_id else "NOT_APPLICABLE"

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
        identity_lock_status=request.identity_lock_status or "UNVERIFIED",
        scale_truth_status=request.scale_truth_status or "UNVERIFIED",
        claim_safety_status=request.claim_safety_status or "UNVERIFIED",
        review_status=request.review_status,
        image_base64=image_base64,
        file_name=file_name,
    )
    return await create_creative_asset(create_request)
