from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services.claim_safe_rewrite_service import (
    STATUS_APPROVED as CLAIM_SAFE_COPY_APPROVED,
    STATUS_REVIEW_READY,
    get_stored_claim_safe_package,
)
from agent.services.product_intelligence import IMAGE_READY_STATES, enrich_product


APPROVAL_PHRASE = "APPROVE_PRODUCTION_PROMPT_PACKAGE"
STATUS_APPROVED = "PRODUCTION_PROMPT_APPROVED"
SUPPORTED_MODES = {"T2V", "IMG"}
FORBIDDEN_TERMS = {
    "ubat kuat",
    "bahagian intim",
    "ketegangan",
    "mati pucuk",
    "guaranteed erection",
    "guaranteed stamina",
}
METADATA_TOKENS = {
    "product_id",
    "local_image_path",
    "claim_safe_copy_status",
    "production_prompt_approval_status",
    "draft-",
    "c:\\users\\user\\desktop\\_ref_flowkit",
}
PLACEHOLDER_TOKENS = {"{{", "}}", "todo", "tbd", "<placeholder>", "[insert"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(value: str | None) -> str:
    return str(value or "").strip()


def normalize_modes(modes: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for mode in modes or []:
        clean = _normalize(mode).upper()
        if clean in SUPPORTED_MODES and clean not in normalized:
            normalized.append(clean)
    return normalized


def get_production_approved_modes(product: dict[str, Any]) -> list[str]:
    raw = product.get("production_prompt_approved_modes")
    if isinstance(raw, list):
        return normalize_modes(raw)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_modes([str(item) for item in parsed])


def is_production_prompt_approved(product: dict[str, Any]) -> bool:
    return _normalize(product.get("production_prompt_approval_status")) == STATUS_APPROVED


def is_mode_production_approved(product: dict[str, Any], mode: str) -> bool:
    normalized_mode = _normalize(mode).upper()
    return is_production_prompt_approved(product) and normalized_mode in get_production_approved_modes(product)


def scan_prompt_text(text: str, *, product_id: str | None = None) -> dict[str, list[str]]:
    lowered = _normalize(text).casefold()
    forbidden_hits = sorted(term for term in FORBIDDEN_TERMS if term in lowered)
    metadata_hits = sorted(token for token in METADATA_TOKENS if token in lowered)
    if product_id and product_id.casefold() in lowered:
        metadata_hits.append(product_id)
    placeholder_hits = sorted(token for token in PLACEHOLDER_TOKENS if token in lowered)
    return {
        "forbidden_hits": forbidden_hits,
        "metadata_hits": metadata_hits,
        "placeholder_hits": placeholder_hits,
    }


async def approve_production_prompt_package(
    product_id: str,
    approval_phrase: str,
    approved_modes: list[str] | None,
    reviewer_note: str | None,
    confirm_no_google_flow_execution: bool,
) -> dict[str, Any]:
    if approval_phrase != APPROVAL_PHRASE:
        raise PermissionError("INVALID_APPROVAL_PHRASE")
    if confirm_no_google_flow_execution is not True:
        raise PermissionError("CONFIRM_NO_GOOGLE_FLOW_EXECUTION_REQUIRED")

    requested_modes = normalize_modes(approved_modes)
    if not requested_modes:
        raise ValueError("APPROVED_MODES_REQUIRED")

    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    if _normalize(product.get("lifecycle_status")) != "ACTIVE":
        raise ValueError("PRODUCT_NOT_ACTIVE")
    if _normalize(product.get("source")).upper() not in {"MANUAL", "OWNED"}:
        raise ValueError("PRODUCT_SOURCE_NOT_ALLOWED")
    if _normalize(product.get("claim_safe_copy_status")) not in {STATUS_REVIEW_READY, CLAIM_SAFE_COPY_APPROVED}:
        raise ValueError("CLAIM_SAFE_COPY_REVIEW_NOT_READY")

    enriched = await enrich_product(product, persist=False)
    if enriched.get("image_readiness_status") not in IMAGE_READY_STATES:
        raise ValueError("IMAGE_REFERENCE_REQUIRED")

    package = await get_stored_claim_safe_package(product_id)
    if not package:
        raise ValueError("CLAIM_SAFE_COPY_PACKAGE_MISSING")

    safe_rewrite_scan = scan_prompt_text(package.get("safe_claim_rewrite", ""), product_id=product_id)
    if any(safe_rewrite_scan.values()):
        raise ValueError("SAFE_CLAIM_REWRITE_SCAN_FAILED")

    from agent.services.prompt_package_dryrun_service import generate_prompt_dryrun

    prompt_packages: dict[str, dict[str, Any]] = {}
    scan_results: dict[str, dict[str, list[str]]] = {"safe_claim_rewrite": safe_rewrite_scan}
    for mode in requested_modes:
        prompt_package = await generate_prompt_dryrun(product_id, mode)
        if prompt_package.get("status") not in {"DRY_RUN_READY", "PRODUCTION_READY"}:
            raise ValueError(f"PROMPT_PACKAGE_NOT_READY:{mode}")
        prompt_scan = scan_prompt_text(prompt_package.get("prompt_preview", ""), product_id=product_id)
        if any(prompt_scan.values()):
            raise ValueError(f"PROMPT_SCAN_FAILED:{mode}")
        prompt_packages[mode] = prompt_package
        scan_results[mode] = prompt_scan

    approved_at = _now()
    note = _normalize(reviewer_note) or "Approved claim-safe prompt package for production handoff only."
    provenance = [
        "production_prompt_approval_service:v1",
        f"product_id:{product_id}",
        f"approved_modes:{','.join(requested_modes)}",
        "google_flow_execution:false",
        "prompt_scan:clean",
    ]
    await crud.update_product(
        product_id,
        production_prompt_approval_status=STATUS_APPROVED,
        production_prompt_approved_modes=json.dumps(requested_modes),
        production_prompt_approved_at=approved_at,
        production_prompt_approval_note=note,
        production_prompt_approval_provenance=json.dumps(provenance),
    )

    return {
        "product_id": product_id,
        "product_name": enriched.get("product_display_name") or enriched.get("raw_product_title"),
        "approval_phrase": APPROVAL_PHRASE,
        "production_prompt_approval_status": STATUS_APPROVED,
        "approved_modes": requested_modes,
        "production_prompt_approved_at": approved_at,
        "production_prompt_approval_note": note,
        "production_prompt_approval_provenance": provenance,
        "claim_safe_copy_status": product.get("claim_safe_copy_status"),
        "claim_safe_rewrite": package.get("safe_claim_rewrite"),
        "image_reference_status": enriched.get("image_readiness_status"),
        "prompt_packages": prompt_packages,
        "scan_results": scan_results,
        "execution_allowed": False,
        "warnings": ["GOOGLE_FLOW_EXECUTION_NOT_STARTED"],
        "next_operator_step": "Submit the approved T2V or IMG prompt package to Google Flow in the next operator task. Do not click Generate in this task.",
    }
