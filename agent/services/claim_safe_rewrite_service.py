from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services.product_mapping import resolve_product_mapping
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
    "eye protection",
    "perlindungan mata",
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
FIRST_PERSON_COPY_PATTERNS = (
    "aku dah try",
    "aku dah guna",
    "aku sendiri",
    "pilihan aku",
    "pengalaman aku",
    "pada aku",
    "bagi aku",
    "weh korang",
    "jujur cakap",
    "saya dah cuba",
    "saya dah try",
    "saya sendiri guna",
    "rutin harian saya",
    "pengalaman saya",
    "yang saya suka",
    "saya suggest",
    "pada saya",
    "bagi saya",
)
INTERNAL_METADATA_PREFIXES = (
    "product:",
    "category:",
    "subcategory:",
    "type:",
    "sold count:",
    "commission:",
    "price:",
    "product id:",
    "sku:",
    "shop name:",
    "seller:",
    "source:",
)
INTERNAL_METADATA_MARKERS = (
    "sold count",
    "commission",
    "category:",
    "subcategory:",
    "product id:",
    "sku:",
)
SENSITIVE_DEVOTIONAL_KEYWORDS = (
    "zikir",
    "wirid",
    "doa",
    "rasulullah",
    "quran",
    "al-quran",
    "hadith",
    "solat",
    "taubat",
)
REVIEW_DECISION_APPROVE_CANDIDATE = "APPROVE_CANDIDATE"
REVIEW_DECISION_NEEDS_COPY_EDIT = "NEEDS_COPY_EDIT"
REVIEW_DECISION_HOLD_SENSITIVE_REVIEW = "HOLD_SENSITIVE_REVIEW"
REVIEW_DECISION_DO_NOT_APPROVE = "DO_NOT_APPROVE"
REVIEW_DECISION_DATA_ISSUE = "DATA_ISSUE"
MAPPING_MISMATCH_RULES = (
    {
        "id": "cookware_mapped_as_appliance",
        "title_keywords": ("grill pan", "griddle", "kuali pemanggang", "bbq grill pan"),
        "taxonomy_markers": ("electric grill", "electric grills", "kitchen appliances", "household appliances"),
        "fallback_mapping": "Home & Living / Kitchenware / Grill Pan",
        "reason": "Cookware title appears to be stored under an electric-appliance taxonomy.",
    },
    {
        "id": "bowl_set_mapped_as_storage",
        "title_keywords": ("bowl", "mangkuk", "ceramic bowl"),
        "taxonomy_markers": ("storage boxes", "storage bins", "home organizers", "organizer"),
        "fallback_mapping": "Home & Living / Kitchenware / Bowl Set",
        "reason": "Kitchenware bowl set appears to be stored under a storage-organizer taxonomy.",
    },
    {
        "id": "sewing_needles_mapped_as_party_gifts",
        "title_keywords": ("jarum", "menjahit", "jahitan", "kuilt", "sewing"),
        "taxonomy_markers": ("party bags", "party supplies", "gifts"),
        "fallback_mapping": "Arts, Crafts & Sewing / Sewing Tools / Hand Needles",
        "reason": "Sewing title appears to be stored under a party-gift taxonomy.",
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(text: str | None) -> str:
    return str(text or "").strip()


def _clean_title_for_dialog(title: str) -> str:
    cleaned = re.sub(r"\s*\[.*?\]\s*", " ", title).strip()
    for phrase in RISKY_PATTERNS:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -|,") or title


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


def _contains_first_person_copy(text: str) -> bool:
    lowered = _normalize(text).casefold()
    return any(pattern in lowered for pattern in FIRST_PERSON_COPY_PATTERNS)


def _contains_internal_metadata(text: str) -> bool:
    lowered = _normalize(text).casefold()
    return any(marker in lowered for marker in INTERNAL_METADATA_MARKERS)


def _split_source_segments(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"[|\n\r]+", text) if segment.strip()]


def _sanitize_source_block(block: str) -> str:
    safe_segments: list[str] = []
    for segment in _split_source_segments(block):
        segment = re.sub(r"\beye protection\b", "", segment, flags=re.IGNORECASE)
        segment = re.sub(r"\bperlindungan mata\b", "", segment, flags=re.IGNORECASE)
        lowered = _normalize(segment).casefold()
        if any(lowered.startswith(prefix) for prefix in INTERNAL_METADATA_PREFIXES):
            continue
        if _starts_with_direction_prefix(segment):
            continue
        if _contains_first_person_copy(segment):
            continue
        cleaned = _normalize_sentence(segment)
        if cleaned:
            safe_segments.append(cleaned)
    return ". ".join(safe_segments)


def _sanitize_generated_line(line: str, fallback: str) -> str:
    normalized = _normalize_sentence(line) or _normalize_sentence(fallback)
    if (
        not normalized
        or _contains_bracket_tags(normalized)
        or _starts_with_direction_prefix(normalized)
        or _contains_unsafe_language(normalized)
        or _contains_first_person_copy(normalized)
        or _contains_internal_metadata(normalized)
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
            if _contains_first_person_copy(normalized) or _contains_internal_metadata(normalized):
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
    return _normalize_sentence(sentence)


def _build_unique_lines(candidates: list[str], fallbacks: list[str], *, count: int) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()
    all_candidates = [*candidates, *fallbacks]
    for index, candidate in enumerate(all_candidates):
        fallback = fallbacks[min(index, len(fallbacks) - 1)]
        line = _sanitize_generated_line(candidate, fallback)
        lowered = line.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        results.append(line)
        if len(results) >= count:
            return results
    while len(results) < count:
        fallback = _sanitize_generated_line(fallbacks[min(len(results), len(fallbacks) - 1)], fallbacks[-1])
        lowered = fallback.casefold()
        if lowered not in seen:
            seen.add(lowered)
            results.append(fallback)
            continue
        results.append(fallback)
    return results


def _build_dialog_copy(
    title: str,
    text_blocks: list[str],
    unsafe_claims: list[str],
    address_style: str | None = None,
) -> tuple[str, str, str, str, list[str], list[str], list[str]]:
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

    fallback_rewrite = f"{clean_title} dengan fokus pada fungsi asas dan penggunaan yang praktikal"
    hook_fallbacks = [
        f"{clean_title} untuk kegunaan harian yang ringkas dan praktikal",
        f"{clean_title} dengan ciri utama yang mudah difahami",
        f"{clean_title} sesuai dipilih berdasarkan fungsi produk dan keperluan sebenar",
    ]
    subhook_fallbacks = [
        f"{clean_title} membantu kekalkan fokus copy pada ciri produk tanpa janji berlebihan",
        f"Maklumat {clean_title} boleh disusun secara terus dan mudah difahami",
        f"{clean_title} sesuai dipersembahkan melalui ciri yang jelas dan manfaat asas",
    ]
    usp_fallbacks = [
        f"{clean_title} mengekalkan fokus pada fungsi produk yang jelas",
        f"Penerangan {clean_title} boleh kekal ringkas tanpa testimoni atau janji sensitif",
        f"{clean_title} sesuai disemak melalui ciri asas dan kegunaan sebenar",
    ]
    cta_fallbacks = [
        f"Semak ciri utama {clean_title} sebelum membuat pilihan",
        f"Pilih {clean_title} jika spesifikasinya sepadan dengan keperluan anda",
        f"Lihat fungsi asas {clean_title} dan tentukan sama ada ia sesuai untuk kegunaan anda",
    ]

    neutral_sentences = [
        _personalize_benefit_sentence(sentence, index, address_style)
        for index, sentence in enumerate(rewrite_sentences[:3])
    ]
    safe_product_name = clean_title
    safe_claim_rewrite = " ".join(
        _sanitize_generated_line(sentence, fallback_rewrite)
        for sentence in neutral_sentences[:2]
    ) or _sanitize_generated_line(fallback_rewrite, fallback_rewrite)
    safe_hook = _sanitize_generated_line(
        neutral_sentences[0] if neutral_sentences else hook_fallbacks[0],
        hook_fallbacks[0],
    )
    safe_subhook = _sanitize_generated_line(
        neutral_sentences[1] if len(neutral_sentences) > 1 else subhook_fallbacks[0],
        subhook_fallbacks[0],
    )
    safe_hook_angles = _build_unique_lines(neutral_sentences, hook_fallbacks, count=3)
    safe_cta_angles = _build_unique_lines(cta_fallbacks, cta_fallbacks, count=3)
    safe_usp_list = _build_unique_lines(neutral_sentences, usp_fallbacks, count=3)
    return (
        safe_product_name,
        safe_claim_rewrite,
        safe_hook,
        safe_subhook,
        safe_hook_angles,
        safe_cta_angles,
        safe_usp_list,
    )


_DRAFTS_CACHE: tuple[float, list, object] | None = None
_DRAFTS_CACHE_TTL_SECONDS = 60.0


def _cached_drafts() -> list:
    """One drafts snapshot per minute instead of one per product.

    `list_drafts()` globs and JSON-parses EVERY draft on disk. Measured on the
    operator machine: 4,352 files, ~78s per call. `_match_bosmax_draft` called it
    once per product, and the product catalog calls that per row — roughly 52
    minutes of blocking disk I/O for a single 40-row page, all of it inside the
    async event loop. The whole runtime died: every later request on every
    endpoint hung until the process was killed, which read as "the app freezes
    when I open the page".

    The drafts directory does not change during a catalog read, so re-reading it
    per row buys nothing. A short TTL keeps a newly saved draft visible within a
    minute without paying for the scan again on the next row.

    The cache is keyed on the PRODUCER, not just time: a monkeypatched
    `list_drafts` is a different callable, so a cached snapshot is never served
    across a patch. Without that, one test's fixture leaked into the next and a
    cache built for performance would have quietly made this code untestable.
    """
    global _DRAFTS_CACHE
    producer = RegistrationDraftStorageService.list_drafts
    now = time.monotonic()
    if (
        _DRAFTS_CACHE is not None
        and _DRAFTS_CACHE[2] is producer
        and (now - _DRAFTS_CACHE[0]) < _DRAFTS_CACHE_TTL_SECONDS
    ):
        return _DRAFTS_CACHE[1]
    drafts = producer()
    _DRAFTS_CACHE = (now, drafts, producer)
    return drafts


async def _warm_drafts_cache() -> None:
    """Pay for the scan on a worker thread, never on the event loop.

    Caching alone is not enough: the FIRST call still costs ~78s, and on the loop
    that is still a dead runtime. Async callers warm it here so the loop stays
    responsive; the sync `_match_bosmax_draft` then reads an already-warm cache.
    """
    await asyncio.to_thread(_cached_drafts)


def _match_bosmax_draft(product: dict[str, Any]) -> dict[str, Any] | None:
    title = _normalize(product.get("raw_product_title") or product.get("product_display_name"))
    drafts = _cached_drafts()
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
            value = _sanitize_source_block(_normalize(evidence.get(key)))
            if value:
                text_blocks.append(value)
    for key in ("section_6_copy_hint", "copywriting_angle", "raw_product_title", "product_display_name"):
        value = _sanitize_source_block(_normalize(product.get(key)))
        if value:
            text_blocks.append(value)
    return text_blocks


def _is_sensitive_devotional_product(title: str, text_blocks: list[str]) -> bool:
    lowered = " ".join([title, *text_blocks]).casefold()
    return any(keyword in lowered for keyword in SENSITIVE_DEVOTIONAL_KEYWORDS)


def _detect_mapping_review(product: dict[str, Any], title: str) -> dict[str, Any] | None:
    stored_taxonomy = " | ".join(
        _normalize(product.get(field))
        for field in ("category", "subcategory", "type")
        if _normalize(product.get(field))
    )
    if not stored_taxonomy:
        return None
    normalized_title = _normalize(title).casefold()
    normalized_taxonomy = stored_taxonomy.casefold()
    for rule in MAPPING_MISMATCH_RULES:
        if not any(keyword in normalized_title for keyword in rule["title_keywords"]):
            continue
        if not any(marker in normalized_taxonomy for marker in rule["taxonomy_markers"]):
            continue
        suggested = resolve_product_mapping(product_name=title, source_hint=_normalize(product.get("source")) or None)
        suggested_taxonomy = " / ".join(
            part for part in (suggested.get("category"), suggested.get("subcategory"), suggested.get("type")) if part
        )
        return {
            "status": "MAPPING_REPAIR_REQUIRED",
            "reason": rule["reason"],
            "current_taxonomy": stored_taxonomy,
            "proposed_taxonomy": suggested_taxonomy or rule["fallback_mapping"],
            "rule_id": rule["id"],
        }
    return None


def _build_review_summary(
    product: dict[str, Any],
    title: str,
    text_blocks: list[str],
    unsafe_claims_detected: list[str],
    risky_claim_tokens: list[str],
) -> tuple[str, bool, list[str], dict[str, Any] | None, dict[str, Any] | None]:
    notes: list[str] = []
    if not _normalize(title):
        return (
            REVIEW_DECISION_DATA_ISSUE,
            False,
            ["Product title is missing, so claim-safe preview cannot be trusted."],
            None,
            None,
        )
    if unsafe_claims_detected or risky_claim_tokens:
        notes.append("Unsafe claim tokens were detected in the source evidence.")
        return REVIEW_DECISION_DO_NOT_APPROVE, False, notes, None, None
    if _is_sensitive_devotional_product(title, text_blocks):
        sensitive_review = {
            "status": "SENIOR_SENSITIVE_REVIEW_REQUIRED",
            "reason": "Religious/devotional product requires respectful senior review before claim-safe approval.",
            "safe_direction": "Use bibliographic, respectful product-led wording only. Avoid slang, testimony, or spiritual outcome promises.",
        }
        return REVIEW_DECISION_HOLD_SENSITIVE_REVIEW, False, notes, None, sensitive_review
    mapping_review = _detect_mapping_review(product, title)
    if mapping_review:
        notes.append("Stored taxonomy appears unrelated to the product title and should be repaired first.")
        return REVIEW_DECISION_DO_NOT_APPROVE, False, notes, mapping_review, None
    return REVIEW_DECISION_APPROVE_CANDIDATE, True, notes, None, None


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
    (
        safe_product_name,
        safe_claim_rewrite,
        safe_hook,
        safe_subhook,
        safe_hook_angles,
        safe_cta_angles,
        safe_usp_list,
    ) = _build_dialog_copy(
        title,
        text_blocks,
        unsafe_claims_detected,
        address_style=address_style,
    )
    review_decision, approval_after_operator_review, review_notes, mapping_review, sensitive_review = (
        _build_review_summary(
            product,
            title,
            text_blocks,
            unsafe_claims_detected,
            risky_claim_tokens,
        )
    )
    approval_phrase = APPROVAL_PHRASE
    audit_notes = [
        "Unsafe source claims preserved for audit only.",
        "Safe copy removes fabricated first-person/testimonial framing and internal metadata.",
        "Safe copy removes explicit male-performance promises and medical certainty.",
        "Dry-run preview can proceed after review-ready approval, but production claim gate stays human-reviewed.",
        *review_notes,
    ]
    provenance = [
        SAFE_PACKAGE_GENERATOR_VERSION,
        f"product_id:{product.get('id') or product.get('product_id')}",
        f"draft_source:{(draft or {}).get('review_draft_id') or 'NOT_FOUND'}",
    ]
    return {
        "product_id": product.get("id") or product.get("product_id"),
        "product_name": title,
        "safe_product_name": safe_product_name,
        "unsafe_claims_detected": unsafe_claims_detected,
        "risky_claim_tokens": risky_claim_tokens,
        "safe_claim_rewrite": safe_claim_rewrite,
        "safe_hook": safe_hook,
        "safe_subhook": safe_subhook,
        "safe_hook_angles": safe_hook_angles,
        "safe_usp_list": safe_usp_list,
        "safe_cta_angles": safe_cta_angles,
        "address_style": address_style,
        "forbidden_phrases_removed": forbidden_removed,
        "claim_safe_copy_status": STATUS_PREVIEW_ONLY,
        "approval_required": True,
        "approval_after_operator_review": approval_after_operator_review,
        "approval_phrase": approval_phrase,
        "claim_gate": product.get("claim_gate") or "CLAIM_REVIEW_REQUIRED",
        "review_decision": review_decision,
        "mapping_review": mapping_review,
        "sensitive_review": sensitive_review,
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
        for line in _payload_text_lines(payload):
            if _contains_first_person_copy(line) or _contains_internal_metadata(line):
                return True
        return False
    if not _normalize(payload.get("address_style")):
        return True
    if not isinstance(payload.get("safe_usp_list"), list):
        return True
    for line in _payload_text_lines(payload):
        lowered = line.casefold()
        if any(phrase in lowered for phrase in LEGACY_CLAIM_SAFE_PHRASES):
            return True
        if _contains_first_person_copy(line) or _contains_internal_metadata(line):
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
    if _should_scan_registration_draft(product):
        # Warm off-thread BEFORE the sync match, so the drafts scan can never run
        # on the event loop. This is the read path the product catalog hits per
        # row — it is the one that froze the runtime.
        await _warm_drafts_cache()
        draft = _match_bosmax_draft(product)
    else:
        draft = None
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
    await _warm_drafts_cache()
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
    if not package.get("approval_after_operator_review"):
        raise PermissionError(f"CLAIM_SAFE_REVIEW_BLOCKED:{package.get('review_decision') or 'UNKNOWN'}")
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
