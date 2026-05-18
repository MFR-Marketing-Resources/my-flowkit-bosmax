from __future__ import annotations

import copy
import hashlib
from typing import Any

from agent.models.i2v_semantic_slot_resolver import (
    I2VResolvedAsset,
    I2VSemanticSlotResolverRequest,
    I2VSemanticSlotResolverResponse,
)
from agent.services.approved_product_package_service import get_approved_product_package
from agent.services.creative_asset_service import (
    build_resolved_workspace_asset,
    validate_selectable_asset,
)
from agent.services.i2v_slot_recipe_config import get_i2v_slot_recipe


ROLE_TO_LIBRARY_ROLE = {
    "product_reference": "PRODUCT_REFERENCE",
    "character_reference": "CHARACTER_REFERENCE",
    "scene_context_reference": "SCENE_CONTEXT_REFERENCE",
    "style_reference": "STYLE_REFERENCE",
}


def _fingerprint(*parts: str) -> str:
    return hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()


def _clone_product_reference_asset(
    asset: dict[str, Any],
    *,
    slot_key: str,
) -> dict[str, Any]:
    cloned = copy.deepcopy(asset)
    product_id = str(asset.get("asset_id", "product-reference")).split(":")[1]
    source_value = asset.get("preview_url") or asset.get("download_url") or product_id
    cloned["slot_key"] = slot_key
    cloned["asset_id"] = f"product-image:{product_id}:{slot_key}"
    cloned["asset_fingerprint"] = f"asset_{_fingerprint(product_id, slot_key, str(source_value))[:16]}"
    return cloned


async def resolve_i2v_semantic_slots(
    request: I2VSemanticSlotResolverRequest,
) -> I2VSemanticSlotResolverResponse:
    recipe = get_i2v_slot_recipe(request.recipe_id)
    package = await get_approved_product_package(request.product_id, "I2V")
    product_subject_asset = next(
        (
            slot.get("resolved_asset")
            for slot in package["asset_slots"]
            if slot.get("slot_key") == "subject" and slot.get("resolved_asset")
        ),
        None,
    )

    blockers: list[str] = []
    warnings: list[str] = []

    role_asset_ids = {
        "product_reference": request.product_reference_asset_id,
        "character_reference": request.character_reference_asset_id,
        "scene_context_reference": request.scene_context_reference_asset_id,
        "style_reference": request.style_reference_asset_id,
    }

    semantic_roles: dict[str, str | None] = {
        "product_reference": None,
        "character_reference": request.character_reference_asset_id,
        "scene_context_reference": request.scene_context_reference_asset_id,
        "style_reference": request.style_reference_asset_id,
    }
    creative_asset_ids: dict[str, str | None] = {
        "product_reference": request.product_reference_asset_id or (product_subject_asset or {}).get("asset_id"),
        "character_reference": request.character_reference_asset_id,
        "scene_context_reference": request.scene_context_reference_asset_id,
        "style_reference": request.style_reference_asset_id,
    }

    resolved_role_assets: dict[str, dict[str, Any]] = {}
    role_summaries: list[str] = []

    product_reference_slot = next(
        (
            slot_key
            for slot_key, mapped_role in recipe["engine_slot_mapping"].items()
            if mapped_role == "product_reference"
        ),
        "subject",
    )

    if request.product_reference_asset_id:
        validation = await validate_selectable_asset(
            request.product_reference_asset_id,
            semantic_role="PRODUCT_REFERENCE",
            allowed_mode="I2V",
            engine_slot=product_reference_slot,  # type: ignore[arg-type]
        )
        if not validation.valid or validation.asset is None:
            blockers.extend([f"PRODUCT_REFERENCE_{item}" for item in validation.blockers])
        else:
            resolved_role_assets["product_reference"] = build_resolved_workspace_asset(
                asset=validation.asset,
                slot_key=product_reference_slot,
            )
            semantic_roles["product_reference"] = validation.asset.asset_id
            role_summaries.append(f"selected product reference {validation.asset.display_name}")
    elif product_subject_asset:
        resolved_role_assets["product_reference"] = dict(product_subject_asset)
        semantic_roles["product_reference"] = product_subject_asset.get("asset_id")
        role_summaries.append("approved product reference image")
    else:
        blockers.append("MISSING_PRODUCT_REFERENCE")

    for role_key, asset_id in (
        ("character_reference", request.character_reference_asset_id),
        ("scene_context_reference", request.scene_context_reference_asset_id),
        ("style_reference", request.style_reference_asset_id),
    ):
        if not asset_id:
            continue
        mapped_slot = next(
            (
                slot_key
                for slot_key, mapped_role in recipe["engine_slot_mapping"].items()
                if mapped_role == role_key
            ),
            "style",
        )
        validation = await validate_selectable_asset(
            asset_id,
            semantic_role=ROLE_TO_LIBRARY_ROLE[role_key],
            allowed_mode="I2V",
            engine_slot=mapped_slot,
        )
        if not validation.valid or validation.asset is None:
            blockers.extend([f"{role_key.upper()}_{item}" for item in validation.blockers])
            continue
        resolved_role_assets[role_key] = build_resolved_workspace_asset(
            asset=validation.asset,
            slot_key=mapped_slot,
        )
        semantic_roles[role_key] = validation.asset.asset_id
        role_summaries.append(validation.asset.display_name)

    for required_role in recipe["required_roles"]:
        if not semantic_roles.get(required_role):
            blockers.append(f"MISSING_{required_role.upper()}")

    if not semantic_roles.get("style_reference") and "style_reference" in recipe["optional_roles"]:
        warnings.append("STYLE_REFERENCE_OPTIONAL_NOT_SELECTED")

    resolved_assets: list[I2VResolvedAsset] = []
    engine_slot_mapping: dict[str, str] = dict(recipe["engine_slot_mapping"])
    for slot_key, semantic_role in engine_slot_mapping.items():
        role_asset = resolved_role_assets.get(semantic_role)
        if not role_asset:
            continue
        if semantic_role == "product_reference" and slot_key != "subject":
            role_asset = _clone_product_reference_asset(role_asset, slot_key=slot_key)
        elif role_asset.get("slot_key") != slot_key:
            role_asset = dict(role_asset)
            role_asset["slot_key"] = slot_key
            role_asset["asset_fingerprint"] = f"asset_{_fingerprint(role_asset.get('asset_id') or '', slot_key, role_asset.get('preview_url') or role_asset.get('download_url') or '')[:16]}"
        resolved_assets.append(
            I2VResolvedAsset(
                slot_key=slot_key,  # type: ignore[arg-type]
                semantic_role=semantic_role,
                asset_id=role_asset["asset_id"],
                display_name=role_asset.get("label"),
                asset_source=role_asset.get("asset_source"),
                asset_fingerprint=role_asset.get("asset_fingerprint"),
                preview_url=role_asset.get("preview_url"),
                download_url=role_asset.get("download_url"),
                media_id=role_asset.get("media_id"),
                local_image_path_present=role_asset.get("local_image_path_present"),
                remote_image_url_present=role_asset.get("remote_image_url_present"),
            )
        )

    summary_parts = []
    if semantic_roles.get("product_reference"):
        summary_parts.append("Product reference is preserved as truth")
    if semantic_roles.get("character_reference"):
        summary_parts.append("selected creator reference is blended into the scene")
    if semantic_roles.get("scene_context_reference"):
        summary_parts.append("scene context drives environment continuity")
    if semantic_roles.get("style_reference"):
        summary_parts.append("style mood is carried as an optional visual layer")

    compiler_context_summary = ". ".join(summary_parts) if summary_parts else "I2V semantic resolver is waiting for required creative references."

    return I2VSemanticSlotResolverResponse(
        mode="I2V",
        recipe_id=request.recipe_id,
        semantic_roles=semantic_roles,
        engine_slot_mapping=engine_slot_mapping,
        creative_asset_ids=creative_asset_ids,
        resolved_assets=resolved_assets,
        compiler_context_summary=compiler_context_summary,
        warnings=warnings,
        blockers=sorted(set(blockers)),
    )
