from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.db import crud
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED as CLAIM_SAFE_STATUS_APPROVED,
    STATUS_REVIEW_READY,
    get_stored_claim_safe_package,
)
from agent.services.product_intelligence import IMAGE_READY_STATES, enrich_product
from agent.services.production_prompt_approval_service import (
    get_production_approved_modes,
    is_production_prompt_approved,
    scan_prompt_text,
)
from agent.services.prompt_package_dryrun_service import generate_prompt_dryrun


SUPPORTED_MODES = {"T2V", "F2V", "I2V", "IMG"}
IMAGE_REQUIRED_MODES = {"F2V", "I2V", "IMG"}
MODE_ALIASES = {
    "TEXT_TO_VIDEO": "T2V",
    "T2V": "T2V",
    "FRAMES": "F2V",
    "F2V": "F2V",
    "INGREDIENTS": "I2V",
    "I2V": "I2V",
    "IMAGE": "IMG",
    "IMG": "IMG",
}
DERIVED_APPROVAL_STATUS = "DERIVED_FROM_APPROVED_PRODUCT_PACKAGE"


def normalize_mode(mode: str | None) -> str:
    return MODE_ALIASES.get(str(mode or "").strip().upper(), str(mode or "").strip().upper())


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _fingerprint(*parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return digest


def _prompt_fingerprint(prompt_text: str) -> str:
    return _fingerprint(prompt_text)


def _package_snapshot_id(product_id: str, mode: str, prompt_fingerprint: str, approval_status: str) -> str:
    return f"pkg_{_fingerprint(product_id, mode, prompt_fingerprint, approval_status)[:16]}"


def _asset_fingerprint(product_id: str, slot_key: str, source_value: str) -> str:
    return f"asset_{_fingerprint(product_id, slot_key, source_value)[:16]}"


def _default_prompt_notice() -> str:
    return "Manual override remains available, but the approved package is the default source of truth."


def _product_image_asset(product: dict[str, Any], slot_key: str, label: str) -> dict[str, Any] | None:
    product_id = _clean(product.get("id") or product.get("product_id"))
    if not product_id or _clean(product.get("image_readiness_status")) not in IMAGE_READY_STATES:
        return None
    source_value = _clean(product.get("local_image_path") or product.get("image_url") or product_id)
    return {
        "asset_id": f"product-image:{product_id}:{slot_key}",
        "asset_fingerprint": _asset_fingerprint(product_id, slot_key, source_value),
        "slot_key": slot_key,
        "asset_source": "PRODUCT_IMAGE_CACHE" if _clean(product.get("local_image_path")) else "PRODUCT_IMAGE_URL",
        "label": label,
        "file_name": f"{product_id}.jpg",
        "preview_url": f"/api/products/{product_id}/image",
        "download_url": f"/api/products/{product_id}/image",
        "media_id": product.get("media_id"),
    }


def _asset_slots_for_mode(product: dict[str, Any], mode: str) -> tuple[list[str], list[dict[str, Any]]]:
    has_image = _clean(product.get("image_readiness_status")) in IMAGE_READY_STATES
    blockers: list[str] = []
    slots: list[dict[str, Any]] = []

    if mode == "T2V":
        return blockers, [
            {
                "slot_key": "prompt_text",
                "required": True,
                "default_source": "APPROVED_PROMPT_PACKAGE",
                "allowed_sources": ["APPROVED_PROMPT_PACKAGE", "MANUAL_OVERRIDE"],
                "resolved_asset": None,
            }
        ]

    if mode == "F2V":
        if not has_image:
            blockers.append("START_FRAME_REQUIRED")
        slots.extend(
            [
                {
                    "slot_key": "start_frame",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE" if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "USER_UPLOAD"],
                    "resolved_asset": _product_image_asset(product, "start_frame", "Product cached image"),
                },
                {
                    "slot_key": "end_frame",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
            ]
        )
        return blockers, slots

    if mode == "I2V":
        if not has_image:
            blockers.append("SUBJECT_REQUIRED")
        slots.extend(
            [
                {
                    "slot_key": "subject",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE" if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "USER_UPLOAD"],
                    "resolved_asset": _product_image_asset(product, "subject", "Product cached image"),
                },
                {
                    "slot_key": "scene",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
                {
                    "slot_key": "style",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
            ]
        )
        return blockers, slots

    if mode == "IMG":
        if not has_image:
            blockers.append("SUBJECT_REQUIRED")
        slots.extend(
            [
                {
                    "slot_key": "subject",
                    "required": True,
                    "default_source": "PRODUCT_IMAGE_CACHE" if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "USER_UPLOAD"],
                    "resolved_asset": _product_image_asset(product, "subject", "Product cached image"),
                },
                {
                    "slot_key": "scene",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
                {
                    "slot_key": "style",
                    "required": False,
                    "default_source": "NONE",
                    "allowed_sources": ["USER_UPLOAD"],
                    "resolved_asset": None,
                },
            ]
        )
        return blockers, slots

    blockers.append("UNSUPPORTED_MODE")
    return blockers, slots


def _manual_fallback_payload(product: dict[str, Any], mode: str, asset_slots: list[dict[str, Any]]) -> dict[str, Any]:
    product_id = _clean(product.get("id") or product.get("product_id"))
    image_url = f"/api/products/{product_id}/image" if product_id and _clean(product.get("image_readiness_status")) in IMAGE_READY_STATES else None
    checklist = [
        "Copy the approved prompt text from this package.",
        "Use the cached product image when the mode requires a subject or start frame.",
        "Keep manual edits clearly separate from the approved package payload.",
        "Record the later handoff attempt with the workspace execution package id.",
    ]
    if mode == "F2V":
        checklist.insert(1, "Use the cached product image as the default Start Frame. End Frame stays optional.")
    if mode == "I2V":
        checklist.insert(1, "Use the cached product image as the Subject. Scene and Style remain optional uploads.")
    if mode == "IMG":
        checklist.insert(1, "Use the cached product image as the default Subject/Reference.")
    if mode == "T2V":
        checklist.insert(1, "No image is required by default for T2V.")
    return {
        "allowed": True,
        "copy_prompt_available": True,
        "image_preview_url": image_url,
        "image_download_url": image_url,
        "asset_slots": [slot["slot_key"] for slot in asset_slots],
        "execution_checklist": checklist,
        "operator_warning": "Google Flow automation is optional here. Manual fallback is supported by design.",
    }


def _f2v_prompt(product: dict[str, Any], claim_safe_rewrite: str, hook: str, cta: str) -> str:
    name = _clean(product.get("product_display_name") or product.get("raw_product_title"))
    return (
        f"Create a premium frames-to-video sequence for {name}. Start from the cached real product image as the opening frame. "
        f"Preserve bottle scale, label visibility, cap integrity, and discreet masculine wellness tone. {hook} "
        f"{claim_safe_rewrite} End frame remains optional; if supplied, transition into it smoothly without inventing new label details. "
        f"Overlay direction: {cta}"
    )


def _i2v_prompt(product: dict[str, Any], claim_safe_rewrite: str, hook: str, cta: str) -> str:
    name = _clean(product.get("product_display_name") or product.get("raw_product_title"))
    return (
        f"Use {name} as the verified subject reference from the cached real product image. "
        f"Allow optional scene and style uploads to refine environment and visual treatment without changing product truth. "
        f"{hook} {claim_safe_rewrite} Keep wording commercial, discreet, and non-medical. Overlay direction: {cta}"
    )


async def _resolved_safe_package(product_id: str) -> dict[str, Any]:
    package = await get_stored_claim_safe_package(product_id)
    if not package or package.get("claim_safe_copy_status") not in {STATUS_REVIEW_READY, CLAIM_SAFE_STATUS_APPROVED}:
        raise ValueError("CLAIM_SAFE_PACKAGE_NOT_READY")
    return package


async def _approved_prompt_payload(product_id: str, mode: str) -> tuple[str, str, list[str]]:
    if mode in {"T2V", "IMG"}:
        dryrun = await generate_prompt_dryrun(product_id, mode)
        if dryrun.get("status") != "PRODUCTION_READY":
            raise ValueError("PRODUCTION_APPROVAL_REQUIRED")
        prompt_text = _clean(dryrun.get("prompt_preview"))
        return prompt_text, "PRODUCTION_PROMPT_APPROVED", list(dryrun.get("warnings") or [])
    raise ValueError("DERIVED_MODE")


async def get_approved_product_package(product_id: str, mode: str) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)
    if normalized_mode not in SUPPORTED_MODES:
        raise ValueError("UNSUPPORTED_MODE")

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")

    enriched = await enrich_product(product, persist=False)
    if _clean(enriched.get("lifecycle_status")) == "ARCHIVED":
        raise ValueError("PRODUCT_ARCHIVED")

    safe_package = await _resolved_safe_package(product_id)
    claim_safe_rewrite = _clean(safe_package.get("safe_claim_rewrite"))
    safe_hooks = safe_package.get("safe_hook_angles") or ["Discreet masculine wellness positioning only."]
    safe_ctas = safe_package.get("safe_cta_angles") or ["Keep the messaging premium, calm, and discreet."]

    production_approved = is_production_prompt_approved(enriched)
    production_modes = set(get_production_approved_modes(enriched))

    if normalized_mode in {"T2V", "IMG"} and normalized_mode not in production_modes:
        raise ValueError("PRODUCTION_APPROVAL_REQUIRED")
    if normalized_mode in {"F2V", "I2V"} and not (production_approved and {"T2V", "IMG"}.issubset(production_modes)):
        raise ValueError("PRODUCTION_APPROVAL_REQUIRED")

    warnings: list[str] = []
    if normalized_mode in {"T2V", "IMG"}:
        prompt_text, approval_status, dryrun_warnings = await _approved_prompt_payload(product_id, normalized_mode)
        warnings.extend(dryrun_warnings)
        production_generation_allowed = True
    else:
        approval_status = DERIVED_APPROVAL_STATUS
        hook = _clean(safe_hooks[0])
        cta = _clean(safe_ctas[0])
        prompt_text = (
            _f2v_prompt(enriched, claim_safe_rewrite, hook, cta)
            if normalized_mode == "F2V"
            else _i2v_prompt(enriched, claim_safe_rewrite, hook, cta)
        )
        production_generation_allowed = False

    prompt_scan = scan_prompt_text(prompt_text, product_id=product_id)
    rewrite_scan = scan_prompt_text(claim_safe_rewrite, product_id=product_id)
    if any(prompt_scan.values()) or any(rewrite_scan.values()):
        raise ValueError("PACKAGE_SCAN_FAILED")

    blockers, asset_slots = _asset_slots_for_mode(enriched, normalized_mode)
    image_reference_status = _clean(enriched.get("image_readiness_status")) or "IMAGE_NOT_AVAILABLE"
    if normalized_mode in IMAGE_REQUIRED_MODES and image_reference_status not in IMAGE_READY_STATES:
        if normalized_mode == "F2V" and "START_FRAME_REQUIRED" not in blockers:
            blockers.append("START_FRAME_REQUIRED")
        if normalized_mode in {"I2V", "IMG"} and "SUBJECT_REQUIRED" not in blockers:
            blockers.append("SUBJECT_REQUIRED")

    prompt_fingerprint = _prompt_fingerprint(prompt_text)
    package_snapshot_id = _package_snapshot_id(product_id, normalized_mode, prompt_fingerprint, approval_status)

    asset_requirements = [
        "PROMPT_TEXT_REQUIRED",
        *(
            ["START_FRAME_REQUIRED", "END_FRAME_OPTIONAL"]
            if normalized_mode == "F2V"
            else ["SUBJECT_REQUIRED", "SCENE_OPTIONAL", "STYLE_OPTIONAL"]
            if normalized_mode in {"I2V", "IMG"}
            else ["NO_IMAGE_REQUIRED"]
        ),
    ]

    source_of_truth_notes = [
        "Product truth remains on the product row.",
        "Claim-safe rewrite remains on product.claim_safe_copy_payload.",
        "T2V and IMG prompts are loaded from the approved production prompt path.",
        "F2V and I2V are derived workspace packages built from approved product and claim-safe truth.",
        _default_prompt_notice(),
    ]

    return {
        "prompt_package_snapshot_id": package_snapshot_id,
        "product_id": product_id,
        "product_name": enriched.get("product_display_name") or enriched.get("raw_product_title"),
        "mode": normalized_mode,
        "approval_status": approval_status,
        "production_generation_allowed": production_generation_allowed,
        "prompt_text": prompt_text,
        "prompt_fingerprint": prompt_fingerprint,
        "claim_safe_rewrite": claim_safe_rewrite,
        "image_reference_status": image_reference_status,
        "asset_requirements": asset_requirements,
        "asset_slots": asset_slots,
        "manual_fallback": _manual_fallback_payload(enriched, normalized_mode, asset_slots),
        "provenance": [
            "approved_product_package_service:v1",
            f"claim_safe_copy_status:{safe_package.get('claim_safe_copy_status')}",
            f"production_prompt_approval_status:{enriched.get('production_prompt_approval_status')}",
            f"image_reference_status:{image_reference_status}",
        ],
        "warnings": warnings,
        "blockers": blockers,
        "source_of_truth_notes": source_of_truth_notes,
    }

