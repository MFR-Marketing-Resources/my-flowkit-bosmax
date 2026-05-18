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
CLAIM_SAFE_READY_STATES = {STATUS_REVIEW_READY, CLAIM_SAFE_STATUS_APPROVED}
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


def _claim_safe_ready(package: dict[str, Any] | None) -> bool:
    return bool(package and package.get("claim_safe_copy_status") in CLAIM_SAFE_READY_STATES)


def _image_gate_for_mode(mode: str) -> str:
    if mode == "F2V":
        return "START_FRAME_REQUIRED"
    if mode in {"I2V", "IMG"}:
        return "SUBJECT_REQUIRED"
    return "NO_IMAGE_REQUIRED"


def _detail_for_blocker(blocker: str, *, mode: str, image_reference_status: str | None = None) -> str:
    if blocker == "READY":
        return f"{mode} package is eligible to load."
    if blocker == "CLAIM_SAFE_PACKAGE_NOT_READY":
        return "This product has no approved claim-safe package yet. Complete claim-safe review before loading a generation package."
    if blocker == "PRODUCTION_APPROVAL_REQUIRED":
        return "This product is not production-approved for this mode yet."
    if blocker == "START_FRAME_REQUIRED":
        return "F2V requires a product image as Start Frame."
    if blocker == "SUBJECT_REQUIRED":
        return "This mode requires a product image/subject reference."
    if blocker == "PRODUCT_ARCHIVED":
        return "Archived products cannot be loaded for generation."
    if blocker == "UNSUPPORTED_MODE":
        return "This workspace mode is not supported by the approved package bridge."
    if blocker == "PRODUCT_NOT_FOUND":
        return "Product not found."
    if blocker == "PACKAGE_SCAN_FAILED":
        return "The approved package failed safety scanning and cannot be loaded."
    if blocker == "IMAGE_REQUIRED":
        return f"Image evidence is not ready for this mode. Current image state: {image_reference_status or 'UNKNOWN'}."
    return blocker


def _checklist_entry(key: str, label: str, ready: bool, detail: str) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "ready": ready,
        "detail": detail,
    }


def _preview_detail_for_source(product: dict[str, Any], *, uses_local_cache: bool) -> tuple[str, str | None]:
    if uses_local_cache:
        if _clean(product.get("local_image_path")):
            return "RENDERABLE", None
        return "ERROR", "Local cache path is missing."
    if _clean(product.get("image_url")):
        return "REMOTE_URL_DIRECT", None
    return "ERROR", "Remote image URL is missing."


def _product_image_asset(product: dict[str, Any], slot_key: str, label: str) -> dict[str, Any] | None:
    product_id = _clean(product.get("id") or product.get("product_id"))
    if not product_id or _clean(product.get("image_readiness_status")) not in IMAGE_READY_STATES:
        return None
    local_image_path = _clean(product.get("local_image_path"))
    remote_image_url = _clean(product.get("image_url"))
    uses_local_cache = bool(local_image_path)
    source_value = _clean(local_image_path or remote_image_url or product_id)
    preview_renderable_status, preview_error_detail = _preview_detail_for_source(
        product,
        uses_local_cache=uses_local_cache,
    )
    return {
        "asset_id": f"product-image:{product_id}:{slot_key}",
        "asset_fingerprint": _asset_fingerprint(product_id, slot_key, source_value),
        "slot_key": slot_key,
        "asset_source": "PRODUCT_IMAGE_CACHE" if uses_local_cache else "PRODUCT_IMAGE_URL",
        "label": label if uses_local_cache else "Product remote image URL",
        "file_name": f"{product_id}.jpg",
        "preview_url": f"/api/products/{product_id}/image" if uses_local_cache else remote_image_url,
        "download_url": f"/api/products/{product_id}/image" if uses_local_cache else remote_image_url,
        "media_id": product.get("media_id"),
        "preview_renderable_status": preview_renderable_status,
        "preview_error_detail": preview_error_detail,
        "local_image_path_present": uses_local_cache,
        "remote_image_url_present": bool(remote_image_url),
    }


def _asset_slots_for_mode(product: dict[str, Any], mode: str) -> tuple[list[str], list[dict[str, Any]]]:
    has_image = _clean(product.get("image_readiness_status")) in IMAGE_READY_STATES
    blockers: list[str] = []
    slots: list[dict[str, Any]] = []
    default_asset_source = (
        "PRODUCT_IMAGE_CACHE"
        if _clean(product.get("local_image_path"))
        else "PRODUCT_IMAGE_URL"
        if _clean(product.get("image_url"))
        else "NONE"
    )

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
                    "default_source": default_asset_source if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "PRODUCT_IMAGE_URL", "USER_UPLOAD"],
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
                    "default_source": default_asset_source if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "PRODUCT_IMAGE_URL", "USER_UPLOAD"],
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
                    "default_source": default_asset_source if has_image else "NONE",
                    "allowed_sources": ["PRODUCT_IMAGE_CACHE", "PRODUCT_IMAGE_URL", "USER_UPLOAD"],
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
    resolved_assets = [
        slot.get("resolved_asset")
        for slot in asset_slots
        if slot.get("resolved_asset")
    ]
    preview_asset = resolved_assets[0] if resolved_assets else None
    image_url = preview_asset.get("preview_url") if preview_asset else None
    image_download_url = preview_asset.get("download_url") if preview_asset else None
    checklist = [
        "Copy the approved prompt text from this package.",
        "Use the resolved product image source when the mode requires a subject or start frame.",
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
        "image_download_url": image_download_url,
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
    if not _claim_safe_ready(package):
        raise ValueError("CLAIM_SAFE_PACKAGE_NOT_READY")
    return package


async def get_product_package_readiness(product_id: str, mode: str) -> dict[str, Any]:
    normalized_mode = normalize_mode(mode)
    if normalized_mode not in SUPPORTED_MODES:
        blocker = "UNSUPPORTED_MODE"
        return {
            "product_id": product_id,
            "mode": normalized_mode or str(mode or "").strip().upper(),
            "readiness_status": blocker,
            "blocker": blocker,
            "detail": _detail_for_blocker(blocker, mode=normalized_mode),
            "checklist": [
                _checklist_entry("mode_eligibility", "Mode eligibility", False, _detail_for_blocker(blocker, mode=normalized_mode)),
            ],
        }

    product = await crud.get_product(product_id)
    if not product:
        blocker = "PRODUCT_NOT_FOUND"
        return {
            "product_id": product_id,
            "mode": normalized_mode,
            "readiness_status": blocker,
            "blocker": blocker,
            "detail": _detail_for_blocker(blocker, mode=normalized_mode),
            "checklist": [
                _checklist_entry("product_exists", "Product exists", False, _detail_for_blocker(blocker, mode=normalized_mode)),
            ],
        }

    enriched = await enrich_product(product, persist=False)
    safe_package = await get_stored_claim_safe_package(product_id)
    product_name = enriched.get("product_display_name") or enriched.get("raw_product_title")
    lifecycle_status = _clean(enriched.get("lifecycle_status")) or "ACTIVE"
    claim_safe_ready = _claim_safe_ready(safe_package)
    production_approved = is_production_prompt_approved(enriched)
    production_modes = set(get_production_approved_modes(enriched))
    image_reference_status = _clean(enriched.get("image_readiness_status")) or "IMAGE_NOT_AVAILABLE"
    image_ready = image_reference_status in IMAGE_READY_STATES
    production_ready = (
        normalized_mode in production_modes
        if normalized_mode in {"T2V", "IMG"}
        else production_approved and {"T2V", "IMG"}.issubset(production_modes)
    )
    image_gate = _image_gate_for_mode(normalized_mode)
    image_requirement_ready = normalized_mode not in IMAGE_REQUIRED_MODES or image_ready

    blocker = "READY"
    if lifecycle_status == "ARCHIVED":
        blocker = "PRODUCT_ARCHIVED"
    elif not claim_safe_ready:
        blocker = "CLAIM_SAFE_PACKAGE_NOT_READY"
    elif not production_ready:
        blocker = "PRODUCTION_APPROVAL_REQUIRED"
    elif not image_requirement_ready:
        blocker = image_gate

    checklist = [
        _checklist_entry(
            "claim_safe_package",
            "Claim-safe package",
            claim_safe_ready,
            "Claim-safe package is approved for workspace use."
            if claim_safe_ready
            else _detail_for_blocker("CLAIM_SAFE_PACKAGE_NOT_READY", mode=normalized_mode),
        ),
        _checklist_entry(
            "production_approval",
            "Production approval",
            production_ready,
            "Product is production-approved for this mode."
            if production_ready
            else _detail_for_blocker("PRODUCTION_APPROVAL_REQUIRED", mode=normalized_mode),
        ),
        _checklist_entry(
            "image_reference",
            "Image cache / subject / start frame",
            image_requirement_ready,
            "Image requirement satisfied for this mode."
            if image_requirement_ready
            else _detail_for_blocker(image_gate, mode=normalized_mode, image_reference_status=image_reference_status),
        ),
        _checklist_entry(
            "mode_eligibility",
            "Mode eligibility",
            normalized_mode in SUPPORTED_MODES and lifecycle_status != "ARCHIVED",
            "Mode is supported and product is active."
            if normalized_mode in SUPPORTED_MODES and lifecycle_status != "ARCHIVED"
            else _detail_for_blocker(
                "PRODUCT_ARCHIVED" if lifecycle_status == "ARCHIVED" else "UNSUPPORTED_MODE",
                mode=normalized_mode,
            ),
        ),
    ]

    return {
        "product_id": product_id,
        "product_name": product_name,
        "mode": normalized_mode,
        "readiness_status": blocker,
        "blocker": None if blocker == "READY" else blocker,
        "detail": _detail_for_blocker(blocker, mode=normalized_mode, image_reference_status=image_reference_status),
        "image_reference_status": image_reference_status,
        "claim_safe_copy_status": (safe_package or {}).get("claim_safe_copy_status"),
        "production_prompt_approved_modes": sorted(production_modes),
        "checklist": checklist,
        "quick_actions": {
            "smart_registration_path": "/product-registration",
            "approved_packages_path": "/approved-packages",
            "products_path": "/products",
        },
    }


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

