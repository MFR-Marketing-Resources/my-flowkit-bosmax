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

DIRECTION_PREFIXES = (
    "tonjolkan",
    "tunjukkan",
    "pastikan",
    "gunakan",
    "elakkan",
    "lihat bagaimana",
    "lihat cara",
    "sertakan",
    "tambahkan",
    "open with",
    "close with",
    "use ",
    "keep ",
    "generate ",
    "highlight ",
    "showcase ",
    "present ",
    "show how",
    "demonstrate ",
    "frame ",
    "capture ",
)

BENEFIT_HINTS = {
    "tenaga": "rutin tenaga harian",
    "vitamin": "rutin vitamin harian",
    "nutrien": "rutin nutrien harian",
    "kesihatan": "rutin kesihatan harian",
    "harian": "rutin harian",
    "aktif": "rutin harian",
    "fokus": "rutin fokus harian",
    "penjagaan": "rutin penjagaan harian",
    "kecantikan": "rutin beauty harian",
    "kulit": "rutin kulit harian",
    "rambut": "rutin rambut harian",
    "badan": "rutin badan harian",
    "serum": "rutin serum harian",
    "tablet": "rutin harian",
    "supplement": "rutin supplement harian",
    "multivitamin": "rutin multivitamin harian",
}

ADDRESS_AKU_KORANG = "AKU_KORANG"
ADDRESS_SAYA_ABANG = "SAYA_ABANG"
ADDRESS_SAYA_AKAK = "SAYA_AKAK"
SAFE_PACKAGE_GENERATOR_VERSION = "claim_safe_rewrite_service:v3"
LEGACY_CLAIM_SAFE_PHRASES = (
    "diposisikan sebagai",
    "dipersembahkan sebagai",
    "dibingkaikan sebagai",
    "tonjolkan ",
    "lihat bagaimana",
    "terokai ",
    "semak presentation",
    "fokus pada presentation",
    "bina visual",
    "product-first",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(text: str | None) -> str:
    return str(text or "").strip()


def _clean_title_for_dialog(title: str) -> str:
    cleaned = re.sub(r"\s*\[.*?\]\s*", " ", title).strip()
    return re.sub(r"\s{2,}", " ", cleaned) or title


def _contains_bracket_tags(text: str) -> bool:
    return bool(re.search(r"\[.+?\]", text))


def _starts_with_direction_prefix(text: str) -> bool:
    lowered = _normalize(text).casefold()
    return any(lowered.startswith(prefix) for prefix in DIRECTION_PREFIXES)


def _contains_unsafe_language(text: str) -> bool:
    lowered = _normalize(text).casefold()
    return any(pattern.casefold() in lowered for pattern in [*RISKY_PATTERNS, *FORBIDDEN_PHRASES])


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def _normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", _normalize(text)).strip(" .,!?:;")


def _sanitize_generated_line(line: str, fallback: str) -> str:
    normalized = _normalize_sentence(line) or _normalize_sentence(fallback)
    if (
        not normalized
        or _contains_bracket_tags(normalized)
        or _starts_with_direction_prefix(normalized)
        or _contains_unsafe_language(normalized)
    ):
        normalized = _normalize_sentence(fallback)
    unsafe_claims, risky_claim_tokens, forbidden_removed = _detect_unsafe_claims([normalized], [])
    if unsafe_claims or risky_claim_tokens or forbidden_removed:
        normalized = _normalize_sentence(fallback)
    return normalized + "."


def _detect_address_style(title: str, text_blocks: list[str]) -> str:
    combined = " ".join([title, *text_blocks]).casefold()
    male_signals = (
        "lelaki",
        "men ",
        "men's",
        "man ",
        "testosterone",
        "kelelakian",
        "prostate",
        "libido",
        "stamina lelaki",
        "vitamin lelaki",
        "supplement lelaki",
        "untuk lelaki",
    )
    female_signals = (
        # Explicit gender / address markers
        "wanita",
        "perempuan",
        "akak",
        "ladies",
        "women",
        "untuk wanita",
        "untuk perempuan",
        # Beauty & skincare
        "serum wajah",
        "serum bibir",
        "skincare",
        "lip care",
        "brightening",
        "moisturis",
        "foundation",
        "lipstick",
        "blush",
        "eyeliner",
        "mascara",
        "blusher",
        # Fashion / apparel — Malay traditional & modern
        "kurung",
        "kebaya",
        "hijab",
        "tudung",
        "selendang",
        "baju kurung",
        "baju kebaya",
        "blouse",
        " skirt",
        " dress ",
        "dresses",
        "fesyen wanita",
        "baju wanita",
        "ladies fashion",
        "ladies wear",
        "ladieswear",
        # Baby & childcare (primary buyer = mother)
        "bayi",
        "baby ",
        "diapers",
        "diaper",
        "lampin",
        "kanak-kanak",
        "susu bayi",
        "susu ibu",
        "breastfeed",
        "penyusuan",
        "stroller",
        "baby carrier",
    )
    if any(signal in combined for signal in male_signals):
        return ADDRESS_SAYA_ABANG
    if any(signal in combined for signal in female_signals):
        return ADDRESS_SAYA_AKAK
    return ADDRESS_AKU_KORANG


def _extract_usable_benefit_sentences(text_blocks: list[str]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for block in text_blocks:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", block):
            normalized = _normalize_sentence(sentence)
            lowered = normalized.casefold()
            if not normalized or lowered in seen:
                continue
            if _word_count(normalized) < 5 or _word_count(normalized) > 25:
                continue
            if _contains_bracket_tags(normalized) or _starts_with_direction_prefix(normalized):
                continue
            if _contains_unsafe_language(normalized):
                continue
            seen.add(lowered)
            candidates.append(normalized)
    return candidates


def _pick_benefit_focus(clean_title: str, text_blocks: list[str]) -> str:
    lowered = " ".join([clean_title, *text_blocks]).casefold()
    for keyword, phrase in BENEFIT_HINTS.items():
        if keyword in lowered:
            return phrase
    return "rutin harian"


def _trim_routine_prefix(text: str) -> str:
    lowered = text.casefold()
    if lowered.startswith("rutin "):
        return text[6:]
    return text


def _personalize_benefit_sentence(
    sentence: str,
    index: int,
    address_style: str = ADDRESS_AKU_KORANG,
) -> str:
    normalized = _normalize_sentence(sentence)
    if not normalized:
        return normalized
    lowered = normalized.casefold()
    personal_prefixes = (
        "aku ",
        "pada aku",
        "bagi aku",
        "saya ",
        "pada saya",
        "bagi saya",
        "jujur",
        "serius",
    )
    if lowered.startswith(personal_prefixes):
        return normalized
    lead = normalized[0].lower() + normalized[1:] if len(normalized) > 1 else normalized.lower()
    if address_style == ADDRESS_AKU_KORANG:
        prefixes = ("Pada aku, ", "Aku suka sebab ", "Bagi aku, ")
    else:
        prefixes = ("Pada saya, ", "Saya suka sebab ", "Bagi saya, ")
    return prefixes[min(index, len(prefixes) - 1)] + lead


def _build_dialog_copy(
    title: str,
    text_blocks: list[str],
    unsafe_claims: list[str],
    address_style: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    if address_style is None:
        address_style = _detect_address_style(title, text_blocks)
    clean_title = _clean_title_for_dialog(title)
    usable_sentences = _extract_usable_benefit_sentences(text_blocks)
    unsafe_lowered = {_normalize_sentence(sentence).casefold() for sentence in unsafe_claims}
    rewrite_sentences = [
        sentence for sentence in usable_sentences if _normalize_sentence(sentence).casefold() not in unsafe_lowered
    ]
    benefit_focus = _pick_benefit_focus(clean_title, text_blocks)
    benefit_focus_short = _trim_routine_prefix(benefit_focus)

    if address_style == ADDRESS_SAYA_ABANG:
        fallback_rewrite = f"{clean_title} ni saya sendiri guna - memang jadi rutin harian saya"
        hook_fallback = f"Saya rasa {clean_title} ni okay je untuk rutin harian abang"
        cta_fallback = f"{clean_title} ni saya suggest abang cuba kalau sesuai dengan rutin abang"
        hooks = [
            f"Abang, kalau tengah cari untuk {benefit_focus_short} - saya dah cuba {clean_title} ni dan memang okay",
            f"Saya rasa {clean_title} ni sesuai je untuk abang yang nak jaga {benefit_focus_short} setiap hari",
            f"Jujur cakap, saya sendiri guna {clean_title} ni untuk {benefit_focus_short} - abang boleh try tengok",
        ]
        ctas = [
            f"Kalau abang tengah cari untuk {benefit_focus_short}, boleh la try {clean_title} ni dulu",
            f"Saya suggest abang cuba {clean_title} ni - ikut je rutin {benefit_focus_short} biasa",
            f"Abang boleh try {clean_title} ni dalam masa seminggu, tengok sendiri macam mana",
        ]
        usps = [
            f"Yang saya suka pasal {clean_title} - nampak sesuai untuk rutin {benefit_focus_short} abang",
            f"Saya rasa {clean_title} ni okay je untuk abang masukkan dalam rutin {benefit_focus_short}",
            f"Dari pengalaman saya, {clean_title} ni boleh fit dalam rutin {benefit_focus_short} abang",
        ]
    elif address_style == ADDRESS_SAYA_AKAK:
        fallback_rewrite = f"{clean_title} ni saya sendiri guna - memang jadi rutin harian saya"
        hook_fallback = f"Saya rasa {clean_title} ni okay je untuk rutin harian akak"
        cta_fallback = f"{clean_title} ni saya suggest akak cuba kalau sesuai dengan rutin akak"
        hooks = [
            f"Akak, kalau tengah cari untuk {benefit_focus_short} - saya dah cuba {clean_title} ni dan memang okay",
            f"Saya rasa {clean_title} ni sesuai je untuk akak yang nak jaga {benefit_focus_short} setiap hari",
            f"Jujur cakap, saya sendiri guna {clean_title} ni untuk {benefit_focus_short} - akak boleh try tengok",
        ]
        ctas = [
            f"Kalau akak tengah cari untuk {benefit_focus_short}, boleh la try {clean_title} ni dulu",
            f"Saya suggest akak cuba {clean_title} ni - ikut je rutin {benefit_focus_short} biasa",
            f"Akak boleh try {clean_title} ni dalam masa seminggu, tengok sendiri macam mana",
        ]
        usps = [
            f"Yang saya suka pasal {clean_title} - nampak sesuai untuk rutin {benefit_focus_short} akak",
            f"Saya rasa {clean_title} ni okay je untuk akak masukkan dalam rutin {benefit_focus_short}",
            f"Dari pengalaman saya, {clean_title} ni boleh fit dalam rutin {benefit_focus_short} akak",
        ]
    else:
        fallback_rewrite = f"{clean_title} ni memang jadi pilihan aku untuk hari-hari"
        hook_fallback = f"{clean_title} ni memang okay je untuk rutin harian aku"
        cta_fallback = f"{clean_title} ni aku rasa okay je kalau nak masuk dalam rutin harian"
        hooks = [
            f"Weh korang, aku dah try {clean_title} ni untuk {benefit_focus} - memang okay lah",
            f"Jujur cakap, aku tak sangka {clean_title} ni jadi pilihan aku untuk {benefit_focus}",
            f"Serius, aku dah guna {clean_title} ni untuk {benefit_focus} aku - best je",
        ]
        ctas = [
            f"Kalau korang tengah cari untuk {benefit_focus}, boleh la try {clean_title} ni",
            f"Aku rasa okay je kalau korang nak cuba {clean_title} ni untuk {benefit_focus}",
            f"{clean_title} ni aku pun dah buat rutin - kalau korang nak try pun boleh je",
        ]
        usps = [
            f"Yang aku suka pasal {clean_title} - nampak praktikal untuk {benefit_focus} aku",
            f"Aku rasa {clean_title} ni sesuai je masuk dalam rutin {benefit_focus_short}",
            f"Dari pengalaman aku, {clean_title} ni okay untuk {benefit_focus} hari-hari",
        ]

    safe_claim_rewrite = " ".join(
        _sanitize_generated_line(_personalize_benefit_sentence(sentence, index, address_style), fallback_rewrite)
        for index, sentence in enumerate(rewrite_sentences[:3])
    ) or _sanitize_generated_line(fallback_rewrite, fallback_rewrite)
    safe_hook_angles = [_sanitize_generated_line(line, hook_fallback) for line in hooks]
    safe_cta_angles = [_sanitize_generated_line(line, cta_fallback) for line in ctas]
    safe_usp_list = [_sanitize_generated_line(line, hook_fallback) for line in usps]
    return safe_claim_rewrite, safe_hook_angles, safe_cta_angles, safe_usp_list


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


def _should_scan_registration_draft(product: dict[str, Any]) -> bool:
    source = _normalize(product.get("source")).upper()
    if source in {"MANUAL", "OWNED"}:
        return True
    title = _normalize(product.get("raw_product_title") or product.get("product_display_name")).casefold()
    return "bosmax" in title


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
    address_style = _detect_address_style(title, text_blocks)
    safe_claim_rewrite, safe_hook_angles, safe_cta_angles, safe_usp_list = _build_dialog_copy(
        title,
        text_blocks,
        unsafe_claims_detected,
        address_style=address_style,
    )
    approval_phrase = APPROVAL_PHRASE
    audit_notes = [
        "Unsafe source claims preserved for audit only.",
        "Safe copy removes explicit male-performance promises and medical certainty.",
        "Dry-run preview can proceed after review-ready approval, but production claim gate stays human-reviewed.",
    ]
    provenance = [
        SAFE_PACKAGE_GENERATOR_VERSION,
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
        "address_style": address_style,
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


def _hydrate_payload_status(product: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    payload["claim_safe_copy_status"] = product.get("claim_safe_copy_status") or payload.get("claim_safe_copy_status")
    payload["claim_safe_copy_updated_at"] = product.get("claim_safe_copy_updated_at")
    return payload


def _payload_text_lines(payload: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("safe_claim_rewrite",):
        value = _normalize(payload.get(key))
        if value:
            lines.append(value)
    for key in ("safe_hook_angles", "safe_usp_list", "safe_cta_angles"):
        raw_values = payload.get(key) or []
        if isinstance(raw_values, list):
            lines.extend(_normalize(str(item)) for item in raw_values if _normalize(str(item)))
    return lines


def _is_stale_claim_safe_payload(payload: dict[str, Any]) -> bool:
    provenance = payload.get("provenance") or []
    if SAFE_PACKAGE_GENERATOR_VERSION in provenance:
        return False
    if not _normalize(payload.get("address_style")):
        return True
    if not isinstance(payload.get("safe_usp_list"), list):
        return True
    for line in _payload_text_lines(payload):
        lowered = line.casefold()
        if any(phrase in lowered for phrase in LEGACY_CLAIM_SAFE_PHRASES):
            return True
        if _contains_bracket_tags(line):
            return True
        if _starts_with_direction_prefix(line):
            return True
    return False


def _merge_preserved_claim_safe_metadata(
    refreshed: dict[str, Any],
    stored: dict[str, Any],
    product: dict[str, Any],
) -> dict[str, Any]:
    row_status = (
        product.get("claim_safe_copy_status")
        or stored.get("claim_safe_copy_status")
        or refreshed.get("claim_safe_copy_status")
    )
    refreshed["claim_safe_copy_status"] = row_status
    refreshed["approval_required"] = (
        bool(stored.get("approval_required"))
        if "approval_required" in stored
        else row_status != STATUS_APPROVED
    )
    for key in (
        "approval_note",
        "approved_at",
        "production_generation_allowed",
        "auto_approval_eligible",
    ):
        if key in stored:
            refreshed[key] = stored[key]
    refreshed["audit_notes"] = [
        *list(refreshed.get("audit_notes") or []),
        "Stored claim-safe payload refreshed from legacy template output.",
    ]
    refreshed["provenance"] = [
        *list(refreshed.get("provenance") or []),
        "claim_safe_copy:refreshed_from_legacy_payload",
    ]
    legacy_markers = [
        item
        for item in list(stored.get("provenance") or [])
        if isinstance(item, str) and item.startswith("claim_safe_copy:")
    ]
    for marker in legacy_markers:
        if marker not in refreshed["provenance"]:
            refreshed["provenance"].append(marker)
    return refreshed


async def refresh_claim_safe_package_if_stale(product_id: str) -> dict[str, Any] | None:
    product = await crud.get_product(product_id)
    if not product:
        return None
    stored = _parse_payload(product)
    if not stored:
        return None
    if not _is_stale_claim_safe_payload(stored):
        return _hydrate_payload_status(product, stored)
    draft = _match_bosmax_draft(product) if _should_scan_registration_draft(product) else None
    refreshed = _merge_preserved_claim_safe_metadata(
        _build_safe_package(product, draft),
        stored,
        product,
    )
    refreshed_at = _now()
    await crud.update_product(
        product_id,
        claim_safe_copy_status=refreshed.get("claim_safe_copy_status"),
        claim_safe_copy_payload=json.dumps(refreshed, ensure_ascii=False),
        claim_safe_copy_updated_at=refreshed_at,
    )
    product["claim_safe_copy_updated_at"] = refreshed_at
    return _hydrate_payload_status(product, refreshed)


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
    if _is_stale_claim_safe_payload(payload):
        return await refresh_claim_safe_package_if_stale(product_id)
    return _hydrate_payload_status(product, payload)
