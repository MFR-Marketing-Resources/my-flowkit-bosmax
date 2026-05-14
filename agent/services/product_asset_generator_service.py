from __future__ import annotations

import asyncio
from typing import Any

from agent.db import crud
from agent.models.product_asset_generator import (
    ProductAssetGeneratorRequest,
    ProductAssetGeneratorResponse,
)
from agent.services.asset_registry_service import list_assets_by_type
from agent.services.copy_signal_generator_service import build_copy_signal_response_for_product
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics
from agent.services.product_preflight import (
    build_product_preflight,
    evaluate_mapping_status,
    resolve_creative_profile,
)


ALLOWED_TARGET_ASSET_INTENTS = {
    "CHARACTER_CONCEPT",
    "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
    "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
    "SCENE_REFERENCE_PROMPT",
    "STYLE_REFERENCE_PROMPT",
    "INGREDIENTS_ASSET_BUNDLE",
}
ALLOWED_DESTINATION_MODES = {"TEXT_TO_VIDEO", "FRAMES", "INGREDIENTS", "IMAGE"}
REGISTRY_HINT_TYPES = (
    "WARDROBE",
    "HEADWEAR",
    "CAMERA_STYLE",
    "CAMERA_BEHAVIOR",
    "SCENE_CONTEXT",
    "STYLE_REFERENCE",
    "PRODUCT_REFERENCE",
    "LANGUAGE",
    "PLATFORM",
)

FORBIDDEN_IMAGE_GENERATION_KEYS = {
    "generate_image_now",
    "image_generation_requested",
    "trigger_image_generation",
    "generate_product_asset",
}
FORBIDDEN_UPLOAD_KEYS = {
    "upload_to_flow",
    "upload_asset",
    "upload_generated_image",
}
FORBIDDEN_FLOW_KEYS = {
    "execute_flow",
    "flow_execution",
    "send_to_flow",
    "generate_in_flow",
}
FORBIDDEN_EXTENSION_KEYS = {
    "execute_extension",
    "chrome_extension_execution",
    "extension_runtime_execution",
}
FORBIDDEN_BATCH_KEYS = {"batch_execution", "execute_batch", "batch_execute"}
FORBIDDEN_QUEUE_KEYS = {"queue_execution", "create_queue_job", "queue_job_create"}
FORBIDDEN_PERSISTENCE_KEYS = {
    "persist_output",
    "save_generated_asset",
    "write_preview_result",
}
FORBIDDEN_CANONICAL_WRITE_KEYS = {
    "canonical_registry_write",
    "save_as_canonical_registry",
    "write_canonical_registry",
}
FORBIDDEN_TRUTH_OVERRIDE_KEYS = {
    "mark_derived_verified",
    "mark_unverified_truth_verified",
    "mark_external_asset_verified",
}
FORBIDDEN_DIMENSION_INVENTION_KEYS = {"invent_product_dimensions", "invent_dimensions"}
FORBIDDEN_CLAIM_INVENTION_KEYS = {"invent_product_claims", "invent_claims"}


def _unique_append(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _normalize_request(
    request_input: dict[str, Any] | ProductAssetGeneratorRequest,
) -> tuple[ProductAssetGeneratorRequest, dict[str, Any]]:
    if isinstance(request_input, ProductAssetGeneratorRequest):
        return request_input, request_input.model_dump()
    parsed = ProductAssetGeneratorRequest.model_validate(request_input)
    return parsed, dict(request_input)


def _has_truthy_flag(raw_request: dict[str, Any], keys: set[str]) -> bool:
    return any(bool(raw_request.get(key)) for key in keys)


async def _resolve_product_seed(
    request: ProductAssetGeneratorRequest,
) -> tuple[dict[str, Any] | None, str | None]:
    if request.product_id:
        existing = await crud.get_product(request.product_id)
        if not existing:
            return None, "PRODUCT_NOT_FOUND"
        if request.product_payload:
            merged = dict(existing)
            merged.update(request.product_payload)
            return merged, None
        return dict(existing), None

    if request.product_payload:
        return dict(request.product_payload), None

    return None, "PRODUCT_CONTEXT_REQUIRED"


def _build_enriched_product(product_seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product_seed)
    payload["id"] = payload.get("id") or payload.get("product_id")

    mapping = resolve_product_mapping(
        product=payload,
        product_name=payload.get("raw_product_title")
        or payload.get("product_display_name")
        or payload.get("product_short_name"),
        source_hint=payload.get("source"),
    )
    for key, value in mapping.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    physics = resolve_product_physics(product=payload)
    for key, value in physics.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    creative_profile = resolve_creative_profile(payload)
    for key, value in creative_profile.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value
    payload.update(evaluate_mapping_status(payload))
    payload.update(evaluate_prompt_readiness(payload, physics))
    payload["preflight"] = build_product_preflight(payload)
    payload["product_id"] = payload.get("id") or payload.get("product_id")
    return payload


async def _load_registry_hints() -> dict[str, Any]:
    responses = await asyncio.gather(
        *(list_assets_by_type(asset_type) for asset_type in REGISTRY_HINT_TYPES)
    )
    return {response.asset_type: response for response in responses}


def _build_provenance(
    product_seed: dict[str, Any],
    registry_hints: dict[str, Any],
) -> dict[str, Any]:
    return {
        "scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY",
        "product_lookup": "crud.get_product"
        if product_seed.get("id") or product_seed.get("product_id")
        else "inline_payload",
        "reused_services": [
            "agent.services.product_mapping.resolve_product_mapping",
            "agent.services.product_physics.resolve_product_physics",
            "agent.services.product_physics.evaluate_prompt_readiness",
            "agent.services.product_preflight.resolve_creative_profile",
            "agent.services.product_preflight.evaluate_mapping_status",
            "agent.services.product_preflight.build_product_preflight",
            "agent.services.asset_registry_service.list_assets_by_type",
        ],
        "registry_hint_asset_types": sorted(registry_hints.keys()),
        "preview_only": True,
        "execution_allowed": False,
        "image_generation_allowed": False,
        "flow_execution_allowed": False,
        "batch_execution_allowed": False,
        "uses_flow_execution": False,
        "uses_extension_runtime": False,
        "uses_batch_execution": False,
        "uses_queue_jobs": False,
        "uses_persistence_writes": False,
    }


def _build_failure_response(
    request: ProductAssetGeneratorRequest,
    *,
    errors: list[str],
    warnings: list[str],
    provenance: dict[str, Any],
    product_context: dict[str, Any] | None = None,
    truth_status: dict[str, Any] | None = None,
) -> ProductAssetGeneratorResponse:
    return ProductAssetGeneratorResponse(
        preview_status="FAIL",
        target_asset_intent=request.target_asset_intent,
        product_context=product_context or {},
        warning_summary=warnings,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        truth_status=truth_status or {},
        dry_run_only=True,
        execution_allowed=False,
        image_generation_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
    )


def _has_product_image(product: dict[str, Any]) -> bool:
    return any(bool(product.get(field)) for field in ("image_url", "local_image_path", "media_id"))


def _build_product_context(
    product: dict[str, Any],
    request: ProductAssetGeneratorRequest,
    ugc_copy_signal: dict[str, Any] | None = None,
    cinematic_copy_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "product_id": product.get("id") or product.get("product_id"),
        "source": product.get("source"),
        "raw_product_title": product.get("raw_product_title"),
        "product_display_name": product.get("product_display_name"),
        "product_short_name": product.get("product_short_name"),
        "category": product.get("category"),
        "subcategory": product.get("subcategory"),
        "type": product.get("type"),
        "product_type": product.get("product_type"),
        "claim_risk_level": product.get("claim_risk_level"),
        "mapping_status": product.get("mapping_status"),
        "prompt_readiness_status": product.get("prompt_readiness_status"),
        "scene_context": request.scene_context or product.get("scene_context"),
        "camera_style": request.camera_style or product.get("camera_style"),
        "camera_behavior": request.camera_behavior or product.get("camera_behavior"),
        "product_scale": product.get("product_scale"),
        "recommended_grip": product.get("recommended_grip"),
        "hand_object_interaction": product.get("hand_object_interaction"),
        "image_url": product.get("image_url"),
        "local_image_path": product.get("local_image_path"),
        "media_id": product.get("media_id"),
        "user_controls": {
            "gender": request.gender,
            "ethnicity": request.ethnicity,
            "age_range": request.age_range,
            "wardrobe": request.wardrobe,
            "headwear": request.headwear,
            "language": request.language,
            "platform": request.platform,
        },
    }
    if ugc_copy_signal:
        context.update(
            {
                "hook": ugc_copy_signal.get("copy_signals", {}).get("hook"),
                "usp_1": ugc_copy_signal.get("copy_signals", {}).get("usp_1"),
                "usp_2": ugc_copy_signal.get("copy_signals", {}).get("usp_2"),
                "usp_3": ugc_copy_signal.get("copy_signals", {}).get("usp_3"),
                "cta": ugc_copy_signal.get("copy_signals", {}).get("cta"),
                "overlay_copy": ugc_copy_signal.get("copy_signals", {}).get("overlay_copy"),
                "dialogue_opening": ugc_copy_signal.get("copy_signals", {}).get("dialogue_opening"),
                "dialogue_body": ugc_copy_signal.get("copy_signals", {}).get("dialogue_body"),
                "dialogue_cta": ugc_copy_signal.get("copy_signals", {}).get("dialogue_cta"),
                "problem": ugc_copy_signal.get("copy_signals", {}).get("problem"),
                "agitate": ugc_copy_signal.get("copy_signals", {}).get("agitate"),
                "solution": ugc_copy_signal.get("copy_signals", {}).get("solution"),
                "stealth_silo": ugc_copy_signal.get("copy_signals", {}).get("stealth_silo"),
                "metaphor_family": ugc_copy_signal.get("copy_signals", {}).get("metaphor_family"),
                "formula": ugc_copy_signal.get("copy_signals", {}).get("formula"),
                "human_review_reason": ugc_copy_signal.get("copy_signals", {}).get("human_review_reason"),
                "copy_route": ugc_copy_signal.get("route"),
                "copy_review_status": ugc_copy_signal.get("review_status"),
                "copy_quality_status": ugc_copy_signal.get("copy_quality_status"),
                "copy_quality_detail": ugc_copy_signal.get("copy_signals", {}).get("copy_quality_detail"),
                "product_scale_prompt": ugc_copy_signal.get("product_context", {}).get("product_scale_prompt"),
                "scale_truth_status": ugc_copy_signal.get("product_context", {}).get("scale_truth_status"),
                "scale_warning": ugc_copy_signal.get("product_context", {}).get("scale_warning"),
                "camera_capture_mode": ugc_copy_signal.get("product_context", {}).get("camera_capture_mode"),
                "ugc_camera_lock_prompt": ugc_copy_signal.get("product_context", {}).get("ugc_camera_lock_prompt"),
                "camera_truth_status": ugc_copy_signal.get("product_context", {}).get("camera_truth_status"),
                "claim_safety": ugc_copy_signal.get("claim_safety", {}),
                "visual_dialogue_isolation": ugc_copy_signal.get("visual_dialogue_isolation", {}),
            }
        )
    if cinematic_copy_signal:
        context["cinematic_camera_prompt"] = cinematic_copy_signal.get(
            "product_context", {}
        ).get("cinematic_camera_prompt")
    return context


def _has_copy_signal_value(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip()
    return bool(normalized) and normalized != "NOT_FOUND"


def _build_copy_readiness_status(
    product: dict[str, Any],
    ugc_copy_signal: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if ugc_copy_signal:
        status = ugc_copy_signal.get(
            "copy_quality_status",
            ugc_copy_signal.get("copy_signals", {}).get("copy_quality_status", "COPY_MISSING"),
        )
        if status == "COMMERCIAL_COPY_READY":
            return "COPY_READY", "Hook, USP, and CTA are present."
        if status == "FALLBACK_COPY_DRAFT":
            return (
                "COPY_DERIVED_SUGGESTION",
                "Fallback draft exists, but commercial copy quality still needs improvement before production.",
            )
        if status == "REVIEW_REQUIRED":
            return (
                "COPY_DERIVED_SUGGESTION",
                "Review-gated copy exists, but a human must approve it before production.",
            )
    copy_keys = ("hook", "usp_1", "usp_2", "usp_3", "cta")
    missing = [key for key in copy_keys if not _has_copy_signal_value(product.get(key))]
    if not missing:
        return "COPY_READY", "Hook, USP, and CTA are present."
    return (
        "COPY_MISSING",
        "COPY_MISSING — hook/USP/CTA must be generated before TEXT_TO_VIDEO can be READY.",
    )


def _build_character_attribute_truth(value: str | None) -> str:
    return "INPUT_SLOT_ONLY" if value else "NOT_PROVIDED"


def _build_character_readiness_status(product: dict[str, Any]) -> str:
    if product.get("subject_character_asset_ready"):
        return "CHARACTER_ASSET_READY"
    return "CHARACTER_CONCEPT_ONLY"


def _build_asset_readiness_status(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
) -> str:
    has_scene = bool(request.scene_context or product.get("scene_context"))
    has_style = bool(request.camera_style or product.get("camera_style"))
    has_product = bool(product.get("id") or product.get("product_id"))
    if request.target_destination_mode == "INGREDIENTS":
        return "NEEDS_ASSET_BUNDLE"
    if request.target_destination_mode == "FRAMES":
        return "NEEDS_ASSET"
    if has_product and has_scene and has_style:
        return "PROMPT_ONLY"
    return "NEEDS_ASSET"


def _character_description(product: dict[str, Any], request: ProductAssetGeneratorRequest) -> str:
    segments = []
    age = request.age_range or "adult"
    segments.append(f"{age} product presenter")
    if request.gender:
        segments.append(request.gender)
    if request.ethnicity:
        segments.append(request.ethnicity)
    segments.append(
        f"styled for {product.get('product_display_name') or product.get('raw_product_title') or 'the product'}"
    )
    if request.wardrobe:
        segments.append(f"wardrobe: {request.wardrobe}")
    if request.headwear:
        segments.append(f"headwear: {request.headwear}")
    return ", ".join(segments)


def _build_truth_status(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
    registry_hints: dict[str, Any],
    ugc_copy_signal: dict[str, Any] | None = None,
    cinematic_copy_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    copy_readiness_status, copy_readiness_detail = _build_copy_readiness_status(
        product, ugc_copy_signal
    )
    copy_quality_status = (ugc_copy_signal or {}).get(
        "copy_quality_status",
        (ugc_copy_signal or {}).get("copy_signals", {}).get("copy_quality_status", "COPY_MISSING"),
    )
    copy_quality_detail = (ugc_copy_signal or {}).get("copy_signals", {}).get(
        "copy_quality_detail",
        copy_readiness_detail,
    )
    product_scale_prompt = (ugc_copy_signal or {}).get("product_context", {}).get(
        "product_scale_prompt"
    )
    ugc_camera_lock_prompt = (ugc_copy_signal or {}).get("product_context", {}).get(
        "ugc_camera_lock_prompt"
    )
    cinematic_camera_prompt = (cinematic_copy_signal or {}).get(
        "product_context", {}
    ).get("cinematic_camera_prompt")
    claim_safety = (ugc_copy_signal or {}).get("claim_safety", {})
    visual_dialogue_isolation = (ugc_copy_signal or {}).get(
        "visual_dialogue_isolation", {}
    )
    has_product = bool(product.get("id") or product.get("product_id"))
    has_scene = bool(request.scene_context or product.get("scene_context"))
    has_camera = bool(
        (request.camera_style or product.get("camera_style"))
        and (request.camera_behavior or product.get("camera_behavior"))
    )
    text_to_video_ready = (
        has_product
        and has_scene
        and has_camera
        and bool(product_scale_prompt)
        and bool(ugc_camera_lock_prompt)
        and copy_quality_status == "COMMERCIAL_COPY_READY"
        and not claim_safety.get("requires_human_review", False)
        and visual_dialogue_isolation.get("status") in {"ENFORCED", "PASS"}
    )
    image_ready = has_product and has_scene and bool(product_scale_prompt)
    if copy_quality_status == "COPY_MISSING":
        text_to_video_readiness_status = "COPY_MISSING"
    elif text_to_video_ready:
        text_to_video_readiness_status = "READY"
    else:
        text_to_video_readiness_status = "NEEDS_REVIEW"
    return {
        "overall_source_status": "DERIVED_FROM_PRODUCT_DATA",
        "profile_source_status": "EPHEMERAL_PREVIEW",
        "persistence_truth": "NOT_PERSISTED",
        "canonical_status": "NOT_CANONICAL",
        "product_mapping_status": product.get("mapping_status") or "MISSING",
        "copy_quality_status": copy_quality_status,
        "copy_quality_detail": copy_quality_detail,
        "copy_readiness_status": copy_readiness_status,
        "copy_readiness_detail": copy_readiness_detail,
        "character_readiness_status": _build_character_readiness_status(product),
        "asset_readiness_status": _build_asset_readiness_status(request, product),
        "execution_readiness_status": "DRY_RUN_ONLY",
        "product_dimensions": "NOT_VERIFIED",
        "scale_truth_status": (ugc_copy_signal or {}).get("product_context", {}).get(
            "scale_truth_status", "SCALE_NOT_FOUND"
        ),
        "camera_truth_status": (ugc_copy_signal or {}).get("product_context", {}).get(
            "camera_truth_status", "CAMERA_LOCK_MISSING"
        ),
        "camera_capture_mode": (ugc_copy_signal or {}).get("product_context", {}).get(
            "camera_capture_mode", "UGC_IPHONE_RAW"
        ),
        "text_to_video_readiness_status": text_to_video_readiness_status,
        "image_prompt_readiness_status": "READY_FOR_PROMPT" if image_ready else "NEEDS_REVIEW",
        "claim_safety_requires_human_review": claim_safety.get("requires_human_review", False),
        "visual_dialogue_isolation_status": visual_dialogue_isolation.get("status", "PASS"),
        "product_claims": "NOT_HARD_ENFORCED",
        "character_attributes": {
            "gender": _build_character_attribute_truth(request.gender),
            "ethnicity": _build_character_attribute_truth(request.ethnicity),
            "age_range": _build_character_attribute_truth(request.age_range),
        },
        "wardrobe": registry_hints["WARDROBE"].source_status,
        "headwear": registry_hints["HEADWEAR"].source_status,
        "camera_style": registry_hints["CAMERA_STYLE"].source_status,
        "camera_behavior": registry_hints["CAMERA_BEHAVIOR"].source_status,
        "language": registry_hints["LANGUAGE"].source_status,
        "platform": registry_hints["PLATFORM"].source_status,
        "ugc_camera_lock_prompt": ugc_camera_lock_prompt,
        "cinematic_camera_prompt": cinematic_camera_prompt,
    }


def _build_common_warnings(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
    registry_hints: dict[str, Any],
    ugc_copy_signal: dict[str, Any] | None = None,
) -> list[str]:
    warnings: list[str] = [
        "PREVIEW_ONLY_NOT_GENERATED_ASSET",
        "CHARACTER_IMAGE_NOT_GENERATED_YET",
        "NOT_CHROME_EXTENSION_VISIBLE_YET",
        "NOT_GOOGLE_FLOW_READY_EXECUTION",
        "READINESS_PROFILE_NOT_PERSISTED",
        "PRODUCT_CLAIMS_NOT_HARD_ENFORCED",
        "PRODUCT_HANDLING_INFERRED_FROM_RULES",
        "PHYSICS_HANDLING_DERIVED_FROM_PRODUCT_RULES",
    ]
    warnings.append("PRODUCT_DIMENSIONS_NOT_REPO_VERIFIED")
    if not _has_product_image(product):
        warnings.append("PRODUCT_IMAGE_MISSING")
    if request.gender or request.ethnicity or request.age_range:
        warnings.append("CHARACTER_ATTRIBUTES_USER_SUPPLIED_OR_DERIVED_NOT_CANONICAL")
    if request.wardrobe or registry_hints["WARDROBE"].source_status != "REPO_VERIFIED":
        warnings.append("WARDROBE_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    if request.headwear or registry_hints["HEADWEAR"].source_status != "REPO_VERIFIED":
        warnings.append("HEADWEAR_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    if request.camera_style or registry_hints["CAMERA_STYLE"].source_status != "REPO_VERIFIED":
        warnings.append("CAMERA_STYLE_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    if request.camera_behavior or registry_hints["CAMERA_BEHAVIOR"].source_status != "REPO_VERIFIED":
        warnings.append("CAMERA_BEHAVIOR_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    if request.language or registry_hints["LANGUAGE"].source_status != "REPO_VERIFIED":
        warnings.append("LANGUAGE_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    if request.platform or registry_hints["PLATFORM"].source_status != "REPO_VERIFIED":
        warnings.append("PLATFORM_DATASET_INPUT_SLOT_ONLY_OR_NOT_VERIFIED")
    copy_readiness_status, _ = _build_copy_readiness_status(product, ugc_copy_signal)
    copy_quality_status = (ugc_copy_signal or {}).get(
        "copy_quality_status",
        (ugc_copy_signal or {}).get("copy_signals", {}).get("copy_quality_status", "COPY_MISSING"),
    )
    if copy_readiness_status == "COPY_MISSING":
        warnings.append("COPY_MISSING_TEXT_TO_VIDEO_NOT_READY")
    if copy_quality_status == "FALLBACK_COPY_DRAFT":
        warnings.append("COPY_QUALITY_FALLBACK_DRAFT")
    if ugc_copy_signal:
        scale_warning = ugc_copy_signal.get("product_context", {}).get("scale_warning")
        if scale_warning:
            warnings.append(scale_warning)
        if ugc_copy_signal.get("claim_safety", {}).get("requires_human_review"):
            warnings.append("COPY_ROUTE_REVIEW_REQUIRED")
        if ugc_copy_signal.get("product_context", {}).get("scale_truth_status") == "SCALE_NOT_FOUND":
            warnings.append("PRODUCT_SCALE_PROMPT_MISSING")
    return warnings


def _build_derived_asset_suggestions(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
    registry_hints: dict[str, Any],
) -> list[dict[str, Any]]:
    product_label = product.get("product_display_name") or product.get("raw_product_title") or "Product"
    character_status = "INPUT_SLOT_ONLY" if any(
        [request.gender, request.ethnicity, request.age_range]
    ) else "DERIVED_FROM_PRODUCT_DATA"
    return [
        {
            "asset_role": "SUBJECT_CHARACTER",
            "asset_type": "CHARACTER",
            "label": f"{product_label} Presenter Concept",
            "description": _character_description(product, request),
            "source_status": character_status,
            "verified_level": "DERIVED_NOT_CANONICAL",
            "is_canonical": False,
            "warnings": ["CHARACTER_CONCEPT_PREVIEW_ONLY_NOT_GENERATED_ASSET"],
            "provenance": {"derived_from": "product + optional user controls"},
        },
        {
            "asset_role": "PRODUCT_REFERENCE",
            "asset_type": "PRODUCT_REFERENCE",
            "label": product_label,
            "description": "Derived product reference from the product row or inline product payload.",
            "source_status": "DERIVED_FROM_PRODUCT_DATA",
            "verified_level": "DERIVED_NOT_CANONICAL",
            "is_canonical": False,
            "warnings": ["PRODUCT_REFERENCE_IS_NOT_CANONICAL_REGISTRY_TRUTH"],
            "provenance": {"derived_from": "product row or payload"},
        },
        {
            "asset_role": "SCENE_REFERENCE",
            "asset_type": "SCENE_CONTEXT",
            "label": request.scene_context or product.get("scene_context") or "Scene Context Suggestion",
            "description": "Suggested scene context for preview planning.",
            "source_status": registry_hints["SCENE_CONTEXT"].source_status,
            "verified_level": "DERIVED_NOT_CANONICAL",
            "is_canonical": False,
            "warnings": list(registry_hints["SCENE_CONTEXT"].warnings),
            "provenance": dict(registry_hints["SCENE_CONTEXT"].provenance),
        },
        {
            "asset_role": "STYLE_REFERENCE",
            "asset_type": "STYLE_REFERENCE",
            "label": request.camera_style or product.get("camera_style") or "Style Reference Suggestion",
            "description": "Suggested visual style reference for preview planning.",
            "source_status": registry_hints["STYLE_REFERENCE"].source_status,
            "verified_level": "DERIVED_NOT_CANONICAL",
            "is_canonical": False,
            "warnings": list(registry_hints["STYLE_REFERENCE"].warnings),
            "provenance": dict(registry_hints["STYLE_REFERENCE"].provenance),
        },
    ]


def _build_required_assets(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    base = [
        {"asset_role": "SUBJECT_CHARACTER", "asset_type": "CHARACTER", "required": True},
        {"asset_role": "PRODUCT_REFERENCE", "asset_type": "PRODUCT_REFERENCE", "required": True},
        {"asset_role": "SCENE_REFERENCE", "asset_type": "SCENE_CONTEXT", "required": True},
        {"asset_role": "STYLE_REFERENCE", "asset_type": "STYLE_REFERENCE", "required": True},
    ]
    if request.include_product_in_hand or request.target_asset_intent == "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT":
        base.append(
            {
                "asset_role": "PRODUCT_IN_HAND_BEHAVIOR",
                "asset_type": "PRODUCT_HANDLING",
                "required": True,
                "recommended_grip": product.get("recommended_grip"),
            }
        )
    return base


def _build_missing_assets(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = [
        {
            "asset_role": "SUBJECT_CHARACTER_IMAGE",
            "reason": "Character image does not exist yet; this response is preview-only.",
            "source_status": "EMPTY_NOT_VERIFIED",
        }
    ]
    if not _has_product_image(product):
        missing.append(
            {
                "asset_role": "PRODUCT_IMAGE",
                "reason": "Product image is missing from the product row or inline payload.",
                "source_status": "EMPTY_NOT_VERIFIED",
            }
        )
    if request.wardrobe:
        missing.append(
            {
                "asset_role": "WARDROBE_REFERENCE",
                "reason": "Wardrobe is an input-slot-only suggestion, not a repo-verified asset.",
                "source_status": "INPUT_SLOT_ONLY",
            }
        )
    if request.headwear:
        missing.append(
            {
                "asset_role": "HEADWEAR_REFERENCE",
                "reason": "Headwear is an input-slot-only suggestion, not a repo-verified asset.",
                "source_status": "INPUT_SLOT_ONLY",
            }
        )
    return missing


def _build_handling_notes(product: dict[str, Any], request: ProductAssetGeneratorRequest) -> list[str]:
    notes = []
    if product.get("recommended_grip"):
        notes.append(f"Recommended grip: {product['recommended_grip']}")
    if product.get("hand_object_interaction"):
        notes.append(f"Hand-object interaction: {product['hand_object_interaction']}")
    if product.get("handling_notes"):
        notes.append(str(product["handling_notes"]))
    if request.include_product_in_hand:
        notes.append("Product should remain clearly readable in hand without implying exact verified dimensions.")
    if not notes:
        notes.append("Handling guidance is inferred from product mapping and physics rules.")
    return notes


def _build_physics_notes(product: dict[str, Any]) -> list[str]:
    notes = []
    for key, label in (
        ("physics_class", "Physics class"),
        ("product_scale", "Product scale"),
        ("material_behavior", "Material behavior"),
        ("surface_behavior", "Surface behavior"),
        ("fragility_level", "Fragility"),
    ):
        if product.get(key):
            notes.append(f"{label}: {product[key]}")
    if product.get("camera_handling_notes"):
        notes.append(f"Camera handling: {product['camera_handling_notes']}")
    if not notes:
        notes.append("Physics guidance is derived from product rules and remains not fully verified.")
    return notes


def _build_scene_notes(product: dict[str, Any], request: ProductAssetGeneratorRequest) -> list[str]:
    scene_context = request.scene_context or product.get("scene_context")
    notes = [f"Scene context: {scene_context}"] if scene_context else []
    if product.get("section_4_hint"):
        notes.append(f"Visual action hint: {product['section_4_hint']}")
    if product.get("section_9_overlay_hint"):
        notes.append(f"Overlay hint: {product['section_9_overlay_hint']}")
    if not notes:
        notes.append("Scene framing is derived from product context and not canonical.")
    return notes


def _build_camera_notes(product: dict[str, Any], request: ProductAssetGeneratorRequest) -> list[str]:
    notes = []
    if request.camera_style or product.get("camera_style"):
        notes.append(f"Camera style: {request.camera_style or product.get('camera_style')}")
    if request.camera_behavior or product.get("camera_behavior"):
        notes.append(
            f"Camera behavior: {request.camera_behavior or product.get('camera_behavior')}"
        )
    if product.get("camera_shot"):
        notes.append(f"Camera shot: {product['camera_shot']}")
    if not notes:
        notes.append("Camera behavior is preview-only and not repo-verified.")
    return notes


def _build_prompt_suggestions(
    request: ProductAssetGeneratorRequest,
    product: dict[str, Any],
    ugc_copy_signal: dict[str, Any] | None = None,
    cinematic_copy_signal: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    product_name = product.get("product_display_name") or product.get("raw_product_title") or "the product"
    scene_context = request.scene_context or product.get("scene_context") or "clean studio environment"
    camera_style = request.camera_style or product.get("camera_style") or "product-led composition"
    camera_behavior = request.camera_behavior or product.get("camera_behavior") or "stable framing"
    character_description = _character_description(product, request)
    handling = product.get("recommended_grip") or "natural two-finger support"
    interaction = product.get("hand_object_interaction") or "keep the product readable without claiming exact dimensions"
    language = request.language or "default language"
    platform = request.platform or "generic platform"
    product_scale_prompt = (ugc_copy_signal or {}).get("product_context", {}).get(
        "product_scale_prompt"
    ) or "PRODUCT_SCALE_PROMPT_MISSING"
    ugc_camera_lock_prompt = (ugc_copy_signal or {}).get("product_context", {}).get(
        "ugc_camera_lock_prompt"
    ) or "UGC_CAMERA_LOCK_MISSING"
    cinematic_camera_prompt = (cinematic_copy_signal or {}).get("product_context", {}).get(
        "cinematic_camera_prompt"
    ) or "CINEMATIC_CAMERA_LOCK_MISSING"

    prompts: dict[str, list[dict[str, Any]]] = {
        "CHARACTER_CONCEPT": [
            {
                "suggestion_type": "character_concept_card",
                "character_description": character_description,
                "wardrobe_note": request.wardrobe or "Wardrobe remains an input-slot suggestion.",
                "headwear_note": request.headwear or "Headwear remains an input-slot suggestion.",
                "product_scale_prompt": product_scale_prompt,
                "ugc_camera_lock_prompt": ugc_camera_lock_prompt,
                "cinematic_camera_prompt": cinematic_camera_prompt,
            }
        ],
        "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT": [
            {
                "suggestion_type": "image_prompt",
                "image_prompt_text": (
                    f"Create a preview-only concept for {character_description} holding {product_name} "
                    f"in a {scene_context}. Use {camera_style} framing with {camera_behavior}. "
                    f"Show {handling}. Hand interaction: {interaction}. Scale lock: {product_scale_prompt}. "
                    f"UGC camera lock: {ugc_camera_lock_prompt}. Keep product claims neutral and avoid invented dimensions."
                ),
                "product_handling_note": handling,
                "hand_object_interaction_note": interaction,
                "product_scale_prompt": product_scale_prompt,
            }
        ],
        "PRODUCT_LIFESTYLE_IMAGE_PROMPT": [
            {
                "suggestion_type": "image_prompt",
                "image_prompt_text": (
                    f"Create a preview-only lifestyle concept for {product_name} in {scene_context}. "
                    f"Use {camera_style} with {camera_behavior}. Product placement should respect "
                    f"derived handling and avoid unverified dimension or claim assertions. Scale lock: {product_scale_prompt}."
                ),
                "scene_prompt": scene_context,
                "product_placement_note": "Keep the product hero-readable without implying verified measurements.",
                "product_scale_prompt": product_scale_prompt,
            }
        ],
        "SCENE_REFERENCE_PROMPT": [
            {
                "suggestion_type": "scene_reference_prompt",
                "scene_context": scene_context,
                "background_environment": f"{scene_context} tuned for {platform} delivery.",
                "prompt_text": (
                    f"Preview-only scene reference: {scene_context}. Present {product_name} in a way that supports "
                    f"{language} copy without claiming execution readiness. Scale lock: {product_scale_prompt}."
                ),
                "product_scale_prompt": product_scale_prompt,
            }
        ],
        "STYLE_REFERENCE_PROMPT": [
            {
                "suggestion_type": "style_reference_prompt",
                "visual_style": camera_style,
                "camera_behavior": camera_behavior,
                "prompt_text": (
                    f"Preview-only style reference for {product_name}: {camera_style}, {camera_behavior}, "
                    f"product-led composition, neutral claim-safe presentation. Scale lock: {product_scale_prompt}."
                ),
                "ugc_camera_lock_prompt": ugc_camera_lock_prompt,
                "cinematic_camera_prompt": cinematic_camera_prompt,
            }
        ],
        "INGREDIENTS_ASSET_BUNDLE": [
            {
                "suggestion_type": "ingredients_asset_bundle",
                "subject_character_asset": f"{product_name} presenter concept",
                "product_reference_asset": f"{product_name} reference",
                "scene_reference_asset": scene_context,
                "style_reference_asset": camera_style,
                "not_verified_fields": [
                    "character_image",
                    "product_dimensions",
                    "product_claims",
                ],
                "product_scale_prompt": product_scale_prompt,
            }
        ],
    }
    return prompts[request.target_asset_intent]


async def generate_product_asset_preview(
    request_input: dict[str, Any] | ProductAssetGeneratorRequest,
) -> ProductAssetGeneratorResponse:
    request, raw_request = _normalize_request(request_input)
    warnings: list[str] = []
    errors: list[str] = []

    if request.target_asset_intent not in ALLOWED_TARGET_ASSET_INTENTS:
        _unique_append(errors, f"UNKNOWN_TARGET_ASSET_INTENT:{request.target_asset_intent}")
    if request.target_destination_mode and request.target_destination_mode not in ALLOWED_DESTINATION_MODES:
        _unique_append(errors, f"UNKNOWN_TARGET_DESTINATION_MODE:{request.target_destination_mode}")
    if request.dry_run_only is False:
        _unique_append(errors, "DRY_RUN_ONLY_FALSE_NOT_ALLOWED")

    for keys, error in (
        (FORBIDDEN_IMAGE_GENERATION_KEYS, "IMAGE_GENERATION_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_UPLOAD_KEYS, "UPLOAD_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_FLOW_KEYS, "FLOW_EXECUTION_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_EXTENSION_KEYS, "CHROME_EXTENSION_EXECUTION_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_BATCH_KEYS, "BATCH_EXECUTION_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_QUEUE_KEYS, "QUEUE_CREATION_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_PERSISTENCE_KEYS, "PERSISTENCE_WRITE_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_CANONICAL_WRITE_KEYS, "CANONICAL_REGISTRY_WRITE_NOT_ALLOWED_IN_ROUND_10"),
        (FORBIDDEN_TRUTH_OVERRIDE_KEYS, "UNVERIFIED_TRUTH_CANNOT_BE_MARKED_VERIFIED"),
        (FORBIDDEN_DIMENSION_INVENTION_KEYS, "PRODUCT_DIMENSION_INVENTION_NOT_ALLOWED"),
        (FORBIDDEN_CLAIM_INVENTION_KEYS, "PRODUCT_CLAIM_INVENTION_NOT_ALLOWED"),
    ):
        if _has_truthy_flag(raw_request, keys):
            _unique_append(errors, error)

    product_seed, lookup_error = await _resolve_product_seed(request)
    if lookup_error == "PRODUCT_NOT_FOUND":
        return _build_failure_response(
            request,
            errors=["PRODUCT_NOT_FOUND"],
            warnings=[],
            provenance={
                "scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY",
                "product_lookup": "crud.get_product",
            },
        )
    if lookup_error == "PRODUCT_CONTEXT_REQUIRED":
        return _build_failure_response(
            request,
            errors=["PRODUCT_CONTEXT_REQUIRED"],
            warnings=[],
            provenance={
                "scope": "ROUND_10_PRODUCT_TO_ASSET_GENERATOR_PREVIEW_ONLY",
                "product_lookup": "none",
            },
        )

    enriched_product = _build_enriched_product(product_seed or {})
    copy_signal_product = dict(enriched_product)
    if request.language:
        copy_signal_product["language"] = request.language
    if request.platform:
        copy_signal_product["platform"] = request.platform
    registry_hints = await _load_registry_hints()
    provenance = _build_provenance(product_seed or {}, registry_hints)
    ugc_copy_signal = build_copy_signal_response_for_product(
        copy_signal_product,
        content_style_mode="UGC_IPHONE",
    ).model_dump()
    cinematic_copy_signal = build_copy_signal_response_for_product(
        copy_signal_product,
        content_style_mode="CINEMATIC_PRO",
    ).model_dump()
    product_context = _build_product_context(
        enriched_product,
        request,
        ugc_copy_signal,
        cinematic_copy_signal,
    )
    truth_status = _build_truth_status(
        request,
        enriched_product,
        registry_hints,
        ugc_copy_signal,
        cinematic_copy_signal,
    )

    if errors:
        return _build_failure_response(
            request,
            errors=errors,
            warnings=[],
            provenance=provenance,
            product_context=product_context,
            truth_status=truth_status,
        )

    warnings.extend(
        _build_common_warnings(
            request,
            enriched_product,
            registry_hints,
            ugc_copy_signal,
        )
    )
    handling_notes = _build_handling_notes(enriched_product, request)
    physics_notes = _build_physics_notes(enriched_product)
    scene_notes = _build_scene_notes(enriched_product, request)
    camera_notes = _build_camera_notes(enriched_product, request)
    derived_asset_suggestions = _build_derived_asset_suggestions(
        request, enriched_product, registry_hints
    )
    prompt_suggestions = _build_prompt_suggestions(
        request,
        enriched_product,
        ugc_copy_signal,
        cinematic_copy_signal,
    )
    required_assets = _build_required_assets(request, enriched_product)
    missing_assets = _build_missing_assets(request, enriched_product)

    preview_status = "FAIL" if errors else "WARN" if warnings else "PASS"
    return ProductAssetGeneratorResponse(
        preview_status=preview_status,
        target_asset_intent=request.target_asset_intent,
        product_context=product_context,
        derived_asset_suggestions=derived_asset_suggestions,
        prompt_suggestions=prompt_suggestions,
        required_assets=required_assets,
        missing_assets=missing_assets,
        handling_notes=handling_notes,
        physics_notes=physics_notes,
        scene_notes=scene_notes,
        camera_notes=camera_notes,
        warning_summary=warnings,
        warnings=warnings,
        errors=errors,
        provenance=provenance,
        truth_status=truth_status,
        dry_run_only=True,
        execution_allowed=False,
        image_generation_allowed=False,
        flow_execution_allowed=False,
        batch_execution_allowed=False,
    )
