from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services.registration_draft_storage_service import (
    RegistrationDraftStorageService,
)


APPROVAL_PHRASE = "APPROVE_CLAIM_SAFE_COPY_REVIEW"
STATUS_PREVIEW_ONLY = "CLAIM_SAFE_COPY_PREVIEW_ONLY"
STATUS_REVIEW_READY = "CLAIM_SAFE_COPY_REVIEW_READY"
STATUS_APPROVED = "CLAIM_SAFE_COPY_APPROVED"

RISKY_PATTERNS = [
    "ubat kuat",
    "bahagian intim",
    "otot kelelakian",
    "tenaga batin",
    "prestasi fizikal lelaki",
    "batin lelaki",
    "ketegangan",
    "membesarkan",
    "memanjangkan",
    "mati pucuk",
    "tahan lama",
    "stamina",
    "kelelakian",
]

FORBIDDEN_PHRASES = [
    "ubat kuat",
    "membesarkan",
    "memanjangkan",
    "mati pucuk",
    "cure",
    "treatment",
    "guaranteed erection",
    "guaranteed stamina",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(text: str | None) -> str:
    return str(text or "").strip()


def _match_bosmax_draft(product: dict[str, Any]) -> dict[str, Any] | None:
    title = _normalize(product.get("raw_product_title") or product.get("product_display_name"))
    drafts = RegistrationDraftStorageService.list_drafts()
    matches: list[dict[str, Any]] = []
    for draft in drafts:
        names = [
            draft.declared_evidence_fields.get("product_name"),
            draft.canonical_candidate_fields.get("normalized_name"),
            draft.canonical_candidate_fields.get("product_name"),
        ]
        haystack = " ".join(_normalize(name) for name in names if _normalize(name))
        if not haystack:
            continue
        if title.casefold() in haystack.casefold() or "bosmax herbs" in haystack.casefold():
            matches.append(draft.model_dump())
    matches.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return matches[0] if matches else None


def _extract_source_text(product: dict[str, Any], draft: dict[str, Any] | None) -> list[str]:
    text_blocks: list[str] = []
    if draft:
        evidence = draft.get("declared_evidence_fields") or {}
        for key in (
            "product_knowledge_text",
            "benefits_text",
            "usage_text",
            "target_customer_text",
            "ingredients_text",
            "warnings_text",
            "paste_anything_about_product",
        ):
            value = _normalize(evidence.get(key))
            if value:
                text_blocks.append(value)
    for key in ("section_6_copy_hint", "copywriting_angle", "raw_product_title", "product_display_name"):
        value = _normalize(product.get(key))
        if value:
            text_blocks.append(value)
    return text_blocks


def _detect_unsafe_claims(text_blocks: list[str], claim_tokens: list[str]) -> tuple[list[str], list[str], list[str]]:
    joined = "\n".join(text_blocks)
    lowered = joined.casefold()
    detected_phrases: list[str] = []
    for phrase in RISKY_PATTERNS:
        if phrase.casefold() in lowered and phrase not in detected_phrases:
            detected_phrases.append(phrase)
    risky_tokens = []
    for token in claim_tokens + detected_phrases:
        normalized = _normalize(token)
        if normalized and normalized not in risky_tokens:
            risky_tokens.append(normalized)
    unsafe_claims: list[str] = []
    for block in text_blocks:
        sentences = re.split(r"(?<=[.!?])\s+|\n+", block)
        for sentence in sentences:
            sentence_text = _normalize(sentence)
            if not sentence_text:
                continue
            lowered_sentence = sentence_text.casefold()
            if any(pattern.casefold() in lowered_sentence for pattern in detected_phrases):
                if sentence_text not in unsafe_claims:
                    unsafe_claims.append(sentence_text)
    forbidden_removed = [
        phrase for phrase in FORBIDDEN_PHRASES if phrase.casefold() in lowered or phrase in risky_tokens
    ]
    return unsafe_claims, risky_tokens, forbidden_removed


def _build_safe_package(product: dict[str, Any], draft: dict[str, Any] | None) -> dict[str, Any]:
    claim_tokens = list(product.get("claim_tokens") or [])
    text_blocks = _extract_source_text(product, draft)
    unsafe_claims_detected, risky_claim_tokens, forbidden_removed = _detect_unsafe_claims(
        text_blocks,
        claim_tokens,
    )
    title = _normalize(product.get("product_display_name") or product.get("raw_product_title"))
    safe_claim_rewrite = (
        f"{title} diposisikan sebagai minyak herba luaran untuk rutin penjagaan diri lelaki "
        "yang lebih kemas, yakin, dan discreet. Fokus komunikasi kekal pada pengalaman urutan "
        "luaran, rasa premium, dan rutin self-care harian tanpa janji perubatan atau hasil tertentu."
    )
    safe_hook_angles = [
        "Rutin penjagaan diri lelaki yang premium, discreet, dan kemas untuk kegunaan luaran.",
        "Minyak herba tradisional untuk self-care lelaki dengan visual produk yang yakin dan non-explicit.",
        "Hero product premium untuk rutin urutan luaran tanpa janji hasil perubatan atau prestasi tertentu.",
    ]
    safe_usp_list = [
        "Minyak herba luaran dalam botol kecil 5ML yang mudah dibawa dan mudah digunakan.",
        "Sesuai diposisikan sebagai rutin penjagaan diri lelaki yang discreet dan premium.",
        "Komunikasi selamat berfokus pada self-care, keyakinan, dan presentation produk yang kemas.",
    ]
    safe_cta_angles = [
        "Lihat rutin penjagaan diri lelaki yang lebih premium dan discreet.",
        "Terokai self-care luaran yang lebih kemas untuk rutin harian.",
        "Semak visual produk Bosmax Herbs 5 ML dalam gaya hero yang clean dan yakin.",
    ]
    approval_phrase = APPROVAL_PHRASE
    audit_notes = [
        "Unsafe source claims preserved for audit only.",
        "Safe copy removes explicit male-performance promises and medical certainty.",
        "Dry-run preview can proceed after review-ready approval, but production claim gate stays human-reviewed.",
    ]
    provenance = [
        "claim_safe_rewrite_service:v1",
        f"product_id:{product.get('id') or product.get('product_id')}",
        f"draft_source:{(draft or {}).get('review_draft_id') or 'NOT_FOUND'}",
    ]
    return {
        "product_id": product.get("id") or product.get("product_id"),
        "product_name": title,
        "unsafe_claims_detected": unsafe_claims_detected,
        "risky_claim_tokens": risky_claim_tokens,
        "safe_claim_rewrite": safe_claim_rewrite,
        "safe_hook_angles": safe_hook_angles,
        "safe_usp_list": safe_usp_list,
        "safe_cta_angles": safe_cta_angles,
        "forbidden_phrases_removed": forbidden_removed,
        "claim_safe_copy_status": STATUS_PREVIEW_ONLY,
        "approval_required": True,
        "approval_phrase": approval_phrase,
        "claim_gate": product.get("claim_gate") or "CLAIM_REVIEW_REQUIRED",
        "audit_notes": audit_notes,
        "provenance": provenance,
    }


def _parse_payload(product: dict[str, Any]) -> dict[str, Any] | None:
    raw = product.get("claim_safe_copy_payload")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def preview_claim_safe_rewrite(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    draft = _match_bosmax_draft(product)
    package = _build_safe_package(product, draft)
    stored = _parse_payload(product)
    if stored and product.get("claim_safe_copy_status") in {STATUS_REVIEW_READY, STATUS_APPROVED}:
        package["stored_status"] = product.get("claim_safe_copy_status")
        package["stored_payload_available"] = True
    else:
        package["stored_status"] = product.get("claim_safe_copy_status")
        package["stored_payload_available"] = False
    return package


async def approve_claim_safe_rewrite(
    product_id: str,
    confirmation_phrase: str,
    approval_note: str | None = None,
) -> dict[str, Any]:
    if confirmation_phrase != APPROVAL_PHRASE:
        raise PermissionError("INVALID_APPROVAL_PHRASE")
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    package = await preview_claim_safe_rewrite(product_id)
    package["claim_safe_copy_status"] = STATUS_REVIEW_READY
    package["approval_required"] = True
    package["approval_note"] = _normalize(approval_note) or "Claim-safe rewrite approved for dry-run preview only."
    package["approved_at"] = _now()
    package["production_generation_allowed"] = False
    await crud.update_product(
        product_id,
        claim_safe_copy_status=STATUS_REVIEW_READY,
        claim_safe_copy_payload=json.dumps(package, ensure_ascii=False),
        claim_safe_copy_updated_at=package["approved_at"],
    )
    updated = await crud.get_product(product_id)
    package["product_row_updated_at"] = updated.get("updated_at") if updated else None
    return package


async def get_stored_claim_safe_package(product_id: str) -> dict[str, Any] | None:
    product = await crud.get_product(product_id)
    if not product:
        return None
    payload = _parse_payload(product)
    if not payload:
        return None
    payload["claim_safe_copy_status"] = product.get("claim_safe_copy_status") or payload.get("claim_safe_copy_status")
    payload["claim_safe_copy_updated_at"] = product.get("claim_safe_copy_updated_at")
    return payload
