from __future__ import annotations

import re
from typing import Any

from agent.db import crud
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED,
    STATUS_REVIEW_READY,
    get_stored_claim_safe_package,
)
from agent.services.production_prompt_approval_service import is_mode_production_approved
from agent.services.product_intelligence import enrich_product


VALID_MODES = {"T2V", "IMG"}
REAL_ESTATE_PRIMARY_KEYWORDS = (
    "condo",
    "kondo",
    "apartment",
    "property",
    "real estate",
    "villa",
    "residence",
)
APPAREL_KEYWORDS = (
    "kurung",
    "kebaya",
    "hijab",
    "tudung",
    "blouse",
    "dress",
    "shirt",
    "apparel",
    "fashion",
)
PRODUCT_KEYWORDS = (
    "serum",
    "bottle",
    "packaging",
    "skincare",
    "supplement",
    "cream",
    "oil",
    "jar",
)


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _clean_name(value: str | None) -> str:
    cleaned = re.sub(r"\s*\[[^\]]*\]\s*", " ", _clean(value))
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned or _clean(value)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(token in haystack for token in needles)


def _infer_image_route(product: dict[str, Any]) -> str:
    text = " ".join(
        filter(
            None,
            [
                _clean(product.get("product_display_name")).casefold(),
                _clean(product.get("raw_product_title")).casefold(),
                _clean(product.get("source")).casefold(),
                _clean(product.get("source_lane")).casefold(),
            ],
        )
    )
    if _contains_any(text, REAL_ESTATE_PRIMARY_KEYWORDS):
        return "REAL_ESTATE_LISTING"
    if _contains_any(text, APPAREL_KEYWORDS):
        return "ECOMMERCE_FASHION_HERO"
    if _contains_any(text, PRODUCT_KEYWORDS) or _clean(product.get("source")):
        return "ECOMMERCE_PRODUCT_HERO"
    return "STATIC_PRODUCT"


def _resolve_product_identity(product: dict[str, Any]) -> str | None:
    name = _clean_name(product.get("product_display_name") or product.get("raw_product_title"))
    return name or None


def _is_micro_product(name: str) -> bool:
    lowered = name.casefold()
    return bool(re.search(r"\b(5|10)\s*ml\b", lowered))


def _image_reference_line(product: dict[str, Any]) -> str:
    if _clean(product.get("local_image_path")):
        return "Use the cached real product photo as the visual reference anchor."
    if _clean(product.get("image_url")):
        return "Use the available product image URL as the visual reference anchor."
    return "No verified image reference is available."


def _t2v_prompt(product: dict[str, Any], package: dict[str, Any], *, product_name: str) -> str:
    overlay = package.get("safe_cta_angles", ["Semak butiran produk dan tentukan sama ada ia sesuai untuk kegunaan anda."])[0]
    hook = package.get("safe_hook_angles", ["Sorot produk dengan jelas menggunakan sudut komersial yang ringkas dan tepat."])[0]
    safe_rewrite = package.get("safe_claim_rewrite", "")
    reference_line = _image_reference_line(product)
    return "\n\n".join(
        [
            f"1. Subject & Product Anchor: Feature {product_name} as the exact product reference. Preserve packaging, label, color, silhouette, and scale truth. {reference_line}",
            "2. Lighting & Scene Physics: Clean commercial lighting with coherent shadows, stable product geometry, and no exaggerated beauty, body, or outcome framing.",
            f"3. Camera & Framing: Start with a clear hero view of {product_name}, then move into controlled product coverage with stable identity continuity and no shaky gimmicks.",
            f"4. Visual Action & Expansion: {hook} Keep the scene commercially appropriate for the real product category and show only truthful handling or placement.",
            f"5. Product Physics & Handling: {product.get('section_5_product_physics_prompt') or 'Maintain believable handling, readable label fidelity, and consistent product scale throughout the sequence.'}",
            f"6. Dialogue & Copy Safety: {safe_rewrite}",
            "7. Audio & Tone: Calm, product-led, and commercially clear. No medical certainty, no guaranteed results, no fake testimonials, and no overclaiming.",
            "8. Temporal Continuity: Keep motion smooth, preserve exact product identity from shot to shot, and avoid inventing extra accessories or packaging details.",
            f"9. Overlay & CTA: {overlay}",
        ]
    )


def _img_prompt(product: dict[str, Any], package: dict[str, Any]) -> str:
    return _compile_img_contract(product, package)["image_prompt"]


def _camera_profile(route: str, *, micro_product: bool) -> dict[str, str]:
    if route == "REAL_ESTATE_LISTING":
        return {
            "focal_length": "24mm lens",
            "depth_of_field": "deep depth of field",
            "movement": "stable tripod perspective",
            "angle": "eye-level architectural angle with vertical line correction",
        }
    if route == "ECOMMERCE_FASHION_HERO":
        return {
            "focal_length": "50mm lens",
            "depth_of_field": "moderate depth of field",
            "movement": "static commercial framing",
            "angle": "front-facing product angle with full silhouette readability",
        }
    if micro_product:
        return {
            "focal_length": "100mm macro lens",
            "depth_of_field": "shallow depth of field",
            "movement": "static product framing",
            "angle": "tight eye-level product angle with fingertip-scale realism",
        }
    return {
        "focal_length": "50mm lens",
        "depth_of_field": "shallow depth of field",
        "movement": "static product framing",
        "angle": "clean eye-level product angle",
    }


def _route_guidance(route: str) -> dict[str, str]:
    if route == "REAL_ESTATE_LISTING":
        return {
            "subject": "Photorealistic Malaysian/SEA property hero image with structure-dominant framing and realistic scale.",
            "context": "Premium real-estate marketing visual with uncluttered foreground and architecture kept dominant.",
            "lighting": "Balanced daylight or blue-hour lighting with one coherent shadow direction, no clipped windows, and no overexposed sky.",
            "composition": "Straight verticals, clean horizon control, deep spatial readability, and no text covering key architecture.",
            "technical": "sRGB output, realistic materials, preserved edge sharpness, and no perspective warping.",
            "negative": "no vertical line bending, no sky clipping, no warped reflections, no missing shadows, no fake signage",
            "export_ratio": "4:5 or 16:9 depending platform target",
        }
    if route == "ECOMMERCE_FASHION_HERO":
        return {
            "subject": "Photorealistic apparel hero image preserving exact garment cut, embroidery, fabric drape, and color truth.",
            "context": "Mobile-first SEA e-commerce hero visual with the garment as the single dominant subject.",
            "lighting": "Clean studio or daylight-balanced lighting with one light direction, visible textile texture, and no mixed color temperatures.",
            "composition": "Centered or near-centered garment framing, full silhouette visibility, readable hems and seams, and uncluttered negative space.",
            "technical": "sRGB output, realistic fabric geometry, crisp stitch detail, and no warped garment proportions.",
            "negative": "no mannequin distortion, no folded-edge cutoff, no unreadable embroidery, no cluttered props, no garbled text",
            "export_ratio": "1:1 preferred for marketplace hero",
        }
    return {
        "subject": "Photorealistic e-commerce product hero image preserving exact packaging, label, color, and scale truth.",
        "context": "Mobile-first SEA commercial product visual with one dominant subject and no background clutter.",
        "lighting": "Clean studio lighting with one consistent shadow direction, controlled reflections, and label-safe clarity.",
        "composition": "Centered or near-centered hero framing with the product fully visible, uncluttered edges, and resilient negative space for mobile crops.",
        "technical": "sRGB output, realistic geometry, readable label fidelity, and no invented packaging text.",
        "negative": "no warped geometry, no logo distortion, no unreadable labels, no extra objects, no fake promotional text",
        "export_ratio": "1:1 preferred for ecommerce hero",
    }


def _overlay_spec(route: str) -> dict[str, Any]:
    if route in {"ECOMMERCE_PRODUCT_HERO", "ECOMMERCE_FASHION_HERO", "STATIC_PRODUCT"}:
        return {
            "render_text_inside_image": False,
            "recommended_text": None,
            "placement": "metadata_only",
            "reason": "Hero image defaults to no rendered overlay; CTA text belongs to secondary assets or Layer B metadata.",
        }
    return {
        "render_text_inside_image": False,
        "recommended_text": None,
        "placement": "metadata_only",
        "reason": "Text overlay is not emitted by default; keep the image prompt visually clean and route copy to metadata.",
    }


def _export_spec(route: str) -> dict[str, Any]:
    if route == "REAL_ESTATE_LISTING":
        return {
            "platform_target": "UNSPECIFIED",
            "recommended_aspect_ratio": "4:5",
            "allowed_aspect_ratios": ["4:5", "16:9"],
            "recommended_resolution": "1080x1350px",
            "color_profile": "sRGB",
        }
    return {
        "platform_target": "UNSPECIFIED",
        "recommended_aspect_ratio": "1:1",
        "allowed_aspect_ratios": ["1:1", "4:5", "9:16"],
        "recommended_resolution": "2000x2000px",
        "color_profile": "sRGB",
    }


def _compile_img_contract(product: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    name = _clean_name(product.get("product_display_name") or product.get("raw_product_title") or "the product")
    route = _infer_image_route(product)
    micro_product = _is_micro_product(name)
    camera = _camera_profile(route, micro_product=micro_product)
    guidance = _route_guidance(route)
    reference_line = _image_reference_line(product)
    safe_rewrite = _clean(package.get("safe_claim_rewrite"))
    image_prompt = "\n".join(
        [
            f"Subject: {guidance['subject']} Use {name} as the exact reference subject.",
            f"Context: {guidance['context']} {reference_line}",
            f"Environment & Lighting: {guidance['lighting']}",
            (
                "Camera Specifications: "
                f"{camera['focal_length']}, {camera['depth_of_field']}, {camera['movement']}, "
                f"{camera['angle']}."
            ),
            f"Composition Rules: {guidance['composition']}",
            (
                "Technical Constraints: "
                f"{guidance['technical']} Keep the composition suitable for {guidance['export_ratio']} and do not render interface guides."
            ),
            (
                "Negative Prompting: "
                f"{guidance['negative']}, no metadata labels, no safe-zone guides, no invented claims. "
                f"No explicit adult cues, no medical claims. Copy intent remains off-image: {safe_rewrite}"
            ),
        ]
    )
    metadata_handoff = {
        "route": route,
        "image_prompt_metadata_isolated": True,
        "platform_target": "UNSPECIFIED",
        "safe_zone_strategy": "Translate platform layout rules to natural composition language only in Layer B.",
        "camera_profile": camera,
        "copy_intent": safe_rewrite or None,
    }
    overlay = _overlay_spec(route)
    export = _export_spec(route)
    return {
        "image_prompt": image_prompt,
        "metadata_handoff": metadata_handoff,
        "overlay_spec": overlay,
        "export_spec": export,
        "route": route,
    }


async def generate_prompt_dryrun(product_id: str, mode: str) -> dict[str, Any]:
    normalized_mode = _clean(mode).upper()
    if normalized_mode not in VALID_MODES:
        return {
            "status": "INVALID_MODE",
            "mode": normalized_mode,
            "errors": ["SUPPORTED_MODES:T2V,IMG"],
        }
    product = await crud.get_product(product_id)
    if not product:
        return {"status": "PRODUCT_NOT_FOUND", "mode": normalized_mode, "errors": ["PRODUCT_NOT_FOUND"]}
    enriched = await enrich_product(product, persist=False)
    package = await get_stored_claim_safe_package(product_id)
    if not package or package.get("claim_safe_copy_status") not in {STATUS_REVIEW_READY, STATUS_APPROVED}:
        return {
            "status": "CLAIM_SAFE_COPY_REWRITE_REQUIRED",
            "mode": normalized_mode,
            "errors": ["CLAIM_SAFE_COPY_REWRITE_REQUIRED"],
            "product_id": product_id,
        }
    product_name = _resolve_product_identity(enriched)
    if not product_name:
        return {
            "status": "PRODUCT_IDENTITY_REQUIRED",
            "mode": normalized_mode,
            "errors": ["PRODUCT_IDENTITY_REQUIRED"],
            "product_id": product_id,
        }
    img_contract = _compile_img_contract(enriched, package) if normalized_mode == "IMG" else None
    prompt_preview = (
        _t2v_prompt(enriched, package, product_name=product_name)
        if normalized_mode == "T2V"
        else img_contract["image_prompt"]
    )
    production_mode_approved = is_mode_production_approved(product, normalized_mode)
    result = {
        "status": "PRODUCTION_READY" if production_mode_approved else "DRY_RUN_READY",
        "product_id": product_id,
        "product_name": product_name,
        "mode": normalized_mode,
        "prompt_preview": prompt_preview,
        "prompt_length": len(prompt_preview),
        "claim_safe_copy_status": package.get("claim_safe_copy_status"),
        "dry_run_preview_allowed": True,
        "production_generation_allowed": production_mode_approved or package.get("claim_safe_copy_status") == STATUS_APPROVED,
        "warnings": [],
        "provenance": [
            "prompt_package_dryrun_service:v1",
            f"claim_safe_copy_status:{package.get('claim_safe_copy_status')}",
            f"image_reference_status:{enriched.get('image_readiness_status')}",
        ],
    }
    if img_contract:
        result.update(img_contract)
    return result
