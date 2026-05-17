from __future__ import annotations

from typing import Any

from agent.db import crud
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED,
    STATUS_REVIEW_READY,
    get_stored_claim_safe_package,
)
from agent.services.product_intelligence import enrich_product


VALID_MODES = {"T2V", "IMG"}


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _image_reference_line(product: dict[str, Any]) -> str:
    if _clean(product.get("local_image_path")):
        return "Use the cached real product photo as the visual reference anchor."
    if _clean(product.get("image_url")):
        return "Use the available product image URL as the visual reference anchor."
    return "No verified image reference is available."


def _t2v_prompt(product: dict[str, Any], package: dict[str, Any]) -> str:
    name = _clean(product.get("product_display_name") or product.get("raw_product_title"))
    overlay = package.get("safe_cta_angles", ["Rutin penjagaan diri lelaki yang premium dan discreet."])[0]
    hook = package.get("safe_hook_angles", ["Rutin penjagaan diri lelaki yang premium dan discreet."])[0]
    safe_rewrite = package.get("safe_claim_rewrite", "")
    return "\n\n".join(
        [
            "1. Subject & Product Anchor: Feature Bosmax Herbs 5 ML as a small 5ML traditional herbal oil bottle. Keep the product scale realistic, premium, and discreet with no exaggerated body-detail or outcome cues.",
            "2. Lighting & Scene Physics: Clean premium UGC lighting with soft studio contrast, realistic shadows, and a calm masculine wellness atmosphere.",
            "3. Camera & Framing: Start with a controlled close-up of the bottle, then move into slow handheld premium product coverage with stable label-forward framing and no shaky gimmicks.",
            f"4. Visual Action & Expansion: {hook} Show careful external-use self-care context only, with hands presenting the bottle naturally and respectfully.",
            f"5. Product Physics & Handling: {product.get('section_5_product_physics_prompt') or 'Maintain believable small-bottle handling with label visibility and cap integrity.'}",
            f"6. Dialogue & Copy Safety: {safe_rewrite}",
            "7. Audio & Tone: Calm, premium, confident, and non-explicit. No medical certainty, no guaranteed results, and no overclaiming.",
            "8. Temporal Continuity: Keep motion smooth, product scale stable, and bottle identity consistent from shot to shot.",
            f"9. Overlay & CTA: {overlay}",
        ]
    )


def _img_prompt(product: dict[str, Any], package: dict[str, Any]) -> str:
    name = _clean(product.get("product_display_name") or product.get("raw_product_title"))
    safe_rewrite = package.get("safe_claim_rewrite", "")
    return (
        f"Premium product hero image of {name}, a small 5ML traditional herbal oil bottle. "
        f"{_image_reference_line(product)} Use clean studio styling, realistic bottle proportions, "
        "matte-to-satin packaging finish, label-safe framing, and discreet masculine wellness direction. "
        f"Copy intent: {safe_rewrite} No explicit adult cues, no medical claims, no invented label text."
    )


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
    prompt_preview = _t2v_prompt(enriched, package) if normalized_mode == "T2V" else _img_prompt(enriched, package)
    warnings = []
    if package.get("claim_safe_copy_status") == STATUS_REVIEW_READY:
        warnings.append("PRODUCTION_CLAIM_REVIEW_STILL_REQUIRED")
    return {
        "status": "DRY_RUN_READY",
        "product_id": product_id,
        "mode": normalized_mode,
        "prompt_preview": prompt_preview,
        "prompt_length": len(prompt_preview),
        "claim_safe_copy_status": package.get("claim_safe_copy_status"),
        "dry_run_preview_allowed": True,
        "production_generation_allowed": package.get("claim_safe_copy_status") == STATUS_APPROVED,
        "warnings": warnings,
        "provenance": [
            "prompt_package_dryrun_service:v1",
            f"claim_safe_copy_status:{package.get('claim_safe_copy_status')}",
            f"image_reference_status:{enriched.get('image_readiness_status')}",
        ],
    }
