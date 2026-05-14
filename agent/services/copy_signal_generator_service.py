from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.api.operator import ContentPackSummary, OperatorProduct, _content_pack_summary
from agent.config import OPERATOR_PACK_DIR
from agent.db import crud
from agent.models.copy_signal_generator import (
    CopySignalGenerateRequest,
    CopySignalGenerateResponse,
    CopySignalRoutesResponse,
)
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics
from agent.services.product_preflight import (
    build_product_preflight,
    evaluate_mapping_status,
    resolve_creative_profile,
)


COPY_SIGNAL_SCOPE = "COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER"
SUPPORTED_ROUTES = ["DIRECT", "STEALTH", "REVIEW_REQUIRED"]
SUPPORTED_CONTENT_STYLE_MODES = ["UGC_IPHONE", "CINEMATIC_PRO"]
AUTHORITY_FILE_TARGETS = [
    "SCRIPT_REGISTRY_UNIFIED.yaml",
    "SCRIPT_VARIANT_LIBRARY.yaml",
    "SOVEREIGN_03_CORE_LOGIC.yaml",
]
STEALTH_KEYWORDS = [
    "stealth",
    "supplement",
    "capsule",
    "detox",
    "slimming",
    "relief",
    "pain",
    "wellness",
    "health",
]
REVIEW_CLAIM_LEVELS = {"HIGH", "VERY_HIGH", "CRITICAL"}
UGC_CAMERA_LOCK = (
    "Raw iPhone handheld footage with subtle hand jitter, natural micro-shake, imperfect creator framing, "
    "quick autofocus breathing, and close-up product-in-hand demo under natural room light. "
    "Do not make it cinematic or overly stabilized."
)
CINEMATIC_CAMERA_LOCK = (
    "Controlled cinematic camera with stable hero framing, smooth push-in, controlled pan, "
    "premium product lighting, and clean commercial composition."
)


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_product_key(value: str | None) -> str:
    return _normalize_text(value).casefold()


async def _load_product_seed(
    request: CopySignalGenerateRequest,
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


def _enrich_product(product_seed: dict[str, Any]) -> dict[str, Any]:
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


def _operator_pack_summary() -> ContentPackSummary | None:
    try:
        return _content_pack_summary()
    except HTTPException:
        return None


def _build_operator_lookup(
    operator_pack: ContentPackSummary | None,
) -> dict[str, OperatorProduct]:
    lookup: dict[str, OperatorProduct] = {}
    for product in operator_pack.products if operator_pack else []:
        for value in [
            product.product_id,
            product.product_name,
            product.raw_product_title,
            product.product_display_name,
            product.product_short_name,
        ]:
            key = _normalize_product_key(value)
            if key and key not in lookup:
                lookup[key] = product
    return lookup


def _match_operator_product(
    product: dict[str, Any],
    lookup: dict[str, OperatorProduct],
) -> OperatorProduct | None:
    for value in [
        product.get("id"),
        product.get("product_id"),
        product.get("product_display_name"),
        product.get("raw_product_title"),
        product.get("product_short_name"),
    ]:
        key = _normalize_product_key(value)
        if key and key in lookup:
            return lookup[key]
    return None


def _authority_files() -> tuple[list[str], list[str]]:
    found: list[str] = []
    root = Path(OPERATOR_PACK_DIR)
    if root.exists():
        available = {path.name for path in root.rglob("*.yaml")}
        for name in AUTHORITY_FILE_TARGETS:
            if name in available:
                found.append(name)
    missing = [name for name in AUTHORITY_FILE_TARGETS if name not in found]
    return found, missing


def get_copy_signal_routes_summary() -> CopySignalRoutesResponse:
    found, missing = _authority_files()
    return CopySignalRoutesResponse(
        scope=COPY_SIGNAL_SCOPE,
        routes=SUPPORTED_ROUTES,
        content_style_modes=SUPPORTED_CONTENT_STYLE_MODES,
        authority_files_found=found,
        authority_files_missing=missing,
    )


def _build_route(product: dict[str, Any]) -> tuple[str, str, bool, str]:
    haystack = " ".join(
        _normalize_text(product.get(field))
        for field in [
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "category",
            "subcategory",
            "type",
            "product_type",
            "product_type_id",
            "silo",
            "trigger_id",
        ]
    ).casefold()
    claim_risk = _normalize_text(product.get("claim_risk_level")).upper()
    is_stealth = any(keyword in haystack for keyword in STEALTH_KEYWORDS) or "stealth" in _normalize_text(product.get("silo")).casefold()
    requires_review = is_stealth or claim_risk in REVIEW_CLAIM_LEVELS
    if is_stealth:
        return "STEALTH", "REVIEW_REQUIRED", True, "STEALTH_PRODUCT_REQUIRES_DIALOGUE_ONLY_REVIEW"
    if requires_review:
        return "REVIEW_REQUIRED", "REVIEW_REQUIRED", True, "CLAIM_SAFETY_REVIEW_REQUIRED"
    return "DIRECT", "AUTO_APPROVED", False, "SAFE_DIRECT_PRODUCT"


def _extract_verified_dimensions(product: dict[str, Any]) -> str | None:
    candidate_flags = [
        product.get("product_dimensions_verified"),
        product.get("dimensions_verified"),
        _normalize_text(product.get("product_dimensions_source")).lower() == "verified",
    ]
    measurement_parts: list[str] = []
    for key, suffix in [
        ("length_cm", "cm"),
        ("width_cm", "cm"),
        ("height_cm", "cm"),
        ("depth_cm", "cm"),
        ("diameter_cm", "cm"),
        ("volume_ml", "ml"),
        ("net_weight_g", "g"),
    ]:
        value = product.get(key)
        if value not in (None, ""):
            measurement_parts.append(f"{key}={value}{suffix}")
    text_candidates = [
        _normalize_text(product.get("product_dimensions")),
        _normalize_text(product.get("dimensions")),
        _normalize_text(product.get("verified_dimensions")),
        _normalize_text(product.get("product_dimensions_text")),
    ]
    text_candidates = [item for item in text_candidates if item]
    if any(candidate_flags) and (measurement_parts or text_candidates):
        return "; ".join(text_candidates + measurement_parts)
    return None


def _scale_anchor(product: dict[str, Any]) -> str | None:
    haystack = " ".join(
        _normalize_text(product.get(field))
        for field in [
            "type",
            "product_type",
            "product_scale",
            "physics_class",
        ]
    ).casefold()
    if any(token in haystack for token in ["lip balm", "balm", "dropper", "oil bottle", "roll on", "roll-on", "serum"]):
        return "EXACTLY lip balm size, fit into fingers naturally."
    if any(token in haystack for token in ["envelope", "duit raya", "money packet", "angpow", "red packet"]):
        return "EXACTLY thin envelope size, flat paper packet scale, held naturally between fingers."
    if any(token in haystack for token in ["accessory", "earring", "brooch", "pin", "charm", "pendant", "keychain"]):
        return "EXACTLY small accessory size, pinched lightly between fingertips without enlargement."
    if any(token in haystack for token in ["bottle", "jar", "tube", "mist", "perfume", "supplement"]):
        return "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise."
    if any(token in haystack for token in ["wipes", "soft pack", "pack", "pouch", "diaper"]):
        return "EXACTLY soft-pack size, compressible in hand without oversized enlargement."
    if any(token in haystack for token in ["garment", "textile", "sarung", "telekung", "jersey"]):
        return "EXACTLY wearable garment scale with natural two-hand drape and no enlargement."
    if any(token in haystack for token in ["small", "slim", "flat", "compact"]):
        return "EXACTLY small product scale, held naturally in hand without enlargement."
    if any(
        _normalize_text(product.get(field))
        for field in [
            "product_scale",
            "product_type",
            "recommended_grip",
            "hand_object_interaction",
            "section_5_product_physics_prompt",
        ]
    ):
        return "EXACTLY product-true scale, handled naturally in hand without enlargement."
    return None


def _build_scale_lock(product: dict[str, Any]) -> tuple[str | None, str, str | None, list[str]]:
    verified_dimensions = _extract_verified_dimensions(product)
    anchor = _scale_anchor(product)
    warnings: list[str] = []
    if not anchor:
        return None, "SCALE_NOT_FOUND", "PRODUCT_SCALE_NOT_FOUND", warnings
    details: list[str] = [anchor]
    if verified_dimensions:
        details.append(f"Verified dimensions: {verified_dimensions}.")
        truth_status = "VERIFIED_DIMENSION_SCALE"
        warning = None
    else:
        truth_status = "DERIVED_RELATIVE_SCALE"
        warning = "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"
        warnings.append(warning)
    for label, value in [
        ("Grip", product.get("recommended_grip")),
        ("Hand interaction", product.get("hand_object_interaction")),
        ("Product physics", product.get("section_5_product_physics_prompt") or product.get("physics_class")),
    ]:
        text = _normalize_text(value)
        if text:
            details.append(f"{label}: {text}.")
    return " ".join(details), truth_status, warning, warnings


def _camera_fields(content_style_mode: str) -> tuple[str, str | None, str | None, str]:
    normalized = _normalize_text(content_style_mode).upper() or "UGC_IPHONE"
    if normalized == "CINEMATIC_PRO":
        return (
            "CINEMATIC_PRO_CONTROLLED",
            None,
            CINEMATIC_CAMERA_LOCK,
            "CAMERA_LOCK_PRESENT",
        )
    return (
        "UGC_IPHONE_RAW",
        UGC_CAMERA_LOCK,
        None,
        "CAMERA_LOCK_PRESENT",
    )


def _copy_value(value: str | None, fallback: str) -> str:
    text = _normalize_text(value)
    return text or fallback


def _derived_copy_signals(
    product: dict[str, Any],
    dialogue_metaphor_hint: str | None,
) -> dict[str, str]:
    product_name = _normalize_text(product.get("product_display_name") or product.get("raw_product_title") or "This product")
    angle = _normalize_text(product.get("copywriting_angle") or product.get("section_6_copy_hint") or "Grounded product-first framing")
    handling = _normalize_text(product.get("handling_notes") or product.get("recommended_grip") or "Natural product handling")
    scene = _normalize_text(product.get("scene_context") or "real-world context")
    metaphor = _normalize_text(dialogue_metaphor_hint)
    hook = f"{product_name} leads with {angle.lower()}."
    if metaphor:
        hook = f"{hook} Dialogue cue: {metaphor}."
    return {
        "hook": hook,
        "usp_1": f"Use {product_name} with {handling.lower()}.",
        "usp_2": f"Keep the demo grounded in {scene.lower()}.",
        "usp_3": "Show the product clearly before any performance implication.",
        "cta": f"Review the prompt package for {product_name} before any execution.",
        "copy_readiness_status": "COPY_DERIVED_SUGGESTION",
    }


def build_copy_signal_response_for_product(
    product: dict[str, Any],
    *,
    content_style_mode: str = "UGC_IPHONE",
    dialogue_metaphor_hint: str | None = None,
    operator_pack: ContentPackSummary | None = None,
) -> CopySignalGenerateResponse:
    found_files, _ = _authority_files()
    route, review_status, requires_review, route_reason = _build_route(product)
    operator_lookup = _build_operator_lookup(operator_pack)
    operator_product = _match_operator_product(product, operator_lookup)
    normalized_hint = _normalize_text(dialogue_metaphor_hint)
    product_scale_prompt, scale_truth_status, scale_warning, scale_warnings = _build_scale_lock(product)
    camera_capture_mode, ugc_camera_lock_prompt, cinematic_camera_prompt, camera_truth_status = _camera_fields(content_style_mode)

    if operator_product and route == "DIRECT":
        copy_signals = {
            "hook": _copy_value(operator_product.hook, "Hook not found."),
            "usp_1": _copy_value(operator_product.usp_1, "USP 1 not found."),
            "usp_2": _copy_value(operator_product.usp_2, "USP 2 not found."),
            "usp_3": _copy_value(operator_product.usp_3, "USP 3 not found."),
            "cta": _copy_value(operator_product.cta, "CTA not found."),
            "copy_readiness_status": "COPY_READY",
        }
    else:
        copy_signals = _derived_copy_signals(
            product,
            normalized_hint if route == "STEALTH" else None,
        )

    warnings = list(scale_warnings)
    if route != "DIRECT":
        warnings.append("COPY_ROUTE_REVIEW_REQUIRED")
    if route == "DIRECT" and not operator_product:
        warnings.append("COPY_SIGNAL_DERIVED_OPERATOR_PACK_FALLBACK")
    if not ugc_camera_lock_prompt and _normalize_text(content_style_mode).upper() == "UGC_IPHONE":
        warnings.append("UGC_CAMERA_LOCK_MISSING")
    if scale_truth_status == "SCALE_NOT_FOUND":
        warnings.append("PRODUCT_SCALE_PROMPT_MISSING")

    product_context = {
        "product_id": product.get("id") or product.get("product_id"),
        "product_display_name": product.get("product_display_name"),
        "raw_product_title": product.get("raw_product_title"),
        "product_type": product.get("product_type") or product.get("product_type_id"),
        "scene_context": product.get("scene_context"),
        "camera_style": product.get("camera_style"),
        "camera_behavior": product.get("camera_behavior"),
        "product_scale": product.get("product_scale"),
        "recommended_grip": product.get("recommended_grip"),
        "hand_object_interaction": product.get("hand_object_interaction"),
        "product_physics": product.get("section_5_product_physics_prompt") or product.get("physics_class"),
        "product_scale_prompt": product_scale_prompt,
        "scale_truth_status": scale_truth_status,
        "scale_warning": scale_warning,
        "camera_capture_mode": camera_capture_mode,
        "ugc_camera_lock_prompt": ugc_camera_lock_prompt,
        "cinematic_camera_prompt": cinematic_camera_prompt or CINEMATIC_CAMERA_LOCK,
        "camera_truth_status": camera_truth_status,
    }

    return CopySignalGenerateResponse(
        scope=COPY_SIGNAL_SCOPE,
        route=route,
        review_status=review_status,
        content_style_mode=_normalize_text(content_style_mode).upper() or "UGC_IPHONE",
        authority_files_found=found_files,
        product_context=product_context,
        copy_signals=copy_signals,
        claim_safety={
            "requires_human_review": requires_review,
            "claim_risk_level": _normalize_text(product.get("claim_risk_level")),
            "reason": route_reason,
        },
        visual_dialogue_isolation={
            "status": "ENFORCED" if route == "STEALTH" else "PASS",
            "visual_metaphor_allowed": False,
            "dialogue_metaphor_allowed": route == "STEALTH",
            "dialogue_metaphor_hint": normalized_hint if route == "STEALTH" else None,
            "blocked_visual_fields": [
                "product_scale_prompt",
                "ugc_camera_lock_prompt",
                "cinematic_camera_prompt",
                "scene_context",
                "camera_behavior",
                "product_handling",
            ],
        },
        warnings=warnings,
        provenance={
            "scope": COPY_SIGNAL_SCOPE,
            "operator_pack_available": bool(operator_pack),
            "operator_pack_copy_signals_used": bool(operator_product and route == "DIRECT"),
        },
    )


async def generate_copy_signal_response(
    request_input: dict[str, Any] | CopySignalGenerateRequest,
) -> CopySignalGenerateResponse:
    request = (
        request_input
        if isinstance(request_input, CopySignalGenerateRequest)
        else CopySignalGenerateRequest.model_validate(request_input)
    )
    product_seed, error = await _load_product_seed(request)
    if error == "PRODUCT_NOT_FOUND":
        return CopySignalGenerateResponse(
            scope=COPY_SIGNAL_SCOPE,
            route="REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            content_style_mode=request.content_style_mode,
            warnings=["PRODUCT_NOT_FOUND"],
            provenance={"scope": COPY_SIGNAL_SCOPE},
        )
    if error == "PRODUCT_CONTEXT_REQUIRED":
        return CopySignalGenerateResponse(
            scope=COPY_SIGNAL_SCOPE,
            route="REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            content_style_mode=request.content_style_mode,
            warnings=["PRODUCT_CONTEXT_REQUIRED"],
            provenance={"scope": COPY_SIGNAL_SCOPE},
        )

    enriched = _enrich_product(product_seed or {})
    operator_pack = _operator_pack_summary()
    return build_copy_signal_response_for_product(
        enriched,
        content_style_mode=request.content_style_mode,
        dialogue_metaphor_hint=request.dialogue_metaphor_hint or request.stealth_metaphor,
        operator_pack=operator_pack,
    )