from __future__ import annotations

from typing import Any


SENSITIVE_CLAIM_TOKENS = {
    "bahagian intim",
    "tenaga batin",
    "batin lelaki",
    "ketegangan",
    "kelelakian",
    "prestasi fizikal lelaki",
    "otot kelelakian",
    "mati pucuk",
    "membesarkan",
    "memanjangkan",
    "tightening",
    "vagina",
    "faraj",
    "miss v",
    "keputihan",
}

BEAUTY_CONTEXT_TOKENS = {
    "beauty",
    "personal care",
    "skincare",
    "lip",
    "lip serum",
    "lip tint",
    "lipmatte",
    "lipstick",
    "sunscreen",
    "serum",
    "body serum",
    "setting spray",
    "primer",
    "mist",
    "cosmetic",
    "brightening",
}

ADDRESS_AKU_KORANG = "AKU_KORANG"
ADDRESS_SAYA_ABANG = "SAYA_ABANG"
ADDRESS_SAYA_AKAK = "SAYA_AKAK"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _pick_benefit_phrase(benefits: str) -> str:
    benefit = _clean_text(benefits)
    if not benefit:
        return "rutin penjagaan diri yang lebih kemas dan premium"
    sentence = benefit.split(".")[0].strip()
    if not sentence:
        return "rutin penjagaan diri yang lebih kemas dan premium"
    return sentence.rstrip(".")


def _combined_payload_text(payload: dict[str, Any]) -> str:
    return " ".join(
        [
            _clean_text(payload.get("product_name")),
            _clean_text(payload.get("benefits_text")),
            _clean_text(payload.get("usage_text")),
            _clean_text(payload.get("target_customer_text")),
            _clean_text(payload.get("category")),
            _clean_text(payload.get("subcategory")),
            _clean_text(payload.get("type")),
            _clean_text(payload.get("copy_route")),
            _clean_text(payload.get("silo")),
            " ".join(str(token) for token in payload.get("claim_tokens") or []),
        ]
    ).casefold()


def _is_sensitive(payload: dict[str, Any]) -> bool:
    claim_gate = _clean_text(payload.get("claim_gate")).upper()
    if claim_gate in {"CLAIM_REVIEW_REQUIRED", "CLAIM_BLOCKED"}:
        return True
    combined = _combined_payload_text(payload)
    return any(token in combined for token in SENSITIVE_CLAIM_TOKENS)


def _is_beauty(payload: dict[str, Any]) -> bool:
    combined = _combined_payload_text(payload)
    return any(token in combined for token in BEAUTY_CONTEXT_TOKENS)


FEMALE_SENSITIVE_TOKENS = {"vagina", "faraj", "miss v", "keputihan", "tightening"}


def _detect_address_style(payload: dict[str, Any], *, sensitive: bool, beauty: bool) -> str:
    if sensitive:
        combined = _combined_payload_text(payload)
        if any(token in combined for token in FEMALE_SENSITIVE_TOKENS):
            return ADDRESS_SAYA_AKAK
        return ADDRESS_SAYA_ABANG
    if beauty:
        return ADDRESS_SAYA_AKAK
    target_customer = _clean_text(payload.get("target_customer_text")).casefold()
    if any(token in target_customer for token in ("lelaki", "men", "man", "abang")):
        return ADDRESS_SAYA_ABANG
    if any(token in target_customer for token in ("wanita", "perempuan", "ladies", "women", "akak")):
        return ADDRESS_SAYA_AKAK
    return ADDRESS_AKU_KORANG


def generate_registration_hook_cta(payload: dict[str, Any]) -> dict[str, list[str] | str | None]:
    product_name = _clean_text(payload.get("product_name")) or "produk ini"
    target_customer = _clean_text(payload.get("target_customer_text")) or None
    usage_text = _clean_text(payload.get("usage_text"))
    benefit_phrase = _pick_benefit_phrase(_clean_text(payload.get("benefits_text")))
    sensitive = _is_sensitive(payload)
    beauty = _is_beauty(payload)
    address_style = _detect_address_style(payload, sensitive=sensitive, beauty=beauty)

    if sensitive:
        audience = "akak" if address_style == ADDRESS_SAYA_AKAK else "abang"
        hooks = [
            f"{audience.capitalize()}, saya guna {product_name} ni untuk rutin luaran je - senang nak masuk dalam rutin harian.",
            f"Kalau cerita pasal {product_name} ni, saya lagi selesa kekalkan pada penggunaan luaran yang ringkas dan tenang.",
            f"Pada saya, {product_name} ni lebih ngam bila orang share pengalaman luaran je tanpa overclaim.",
        ]
        ctas = [
            f"Kalau {audience} cari produk luaran, {product_name} ni boleh je tengok dulu mana yang ngam dengan rutin sendiri.",
            f"Saya rasa {product_name} ni okay je kalau {audience} nak masuk dalam rutin luaran yang simple dan tak over sangat.",
            f"{product_name} ni sesuai je kalau {audience} nak try untuk kegunaan luaran tanpa cerita lebih-lebih.",
        ]
    else:
        if address_style == ADDRESS_SAYA_AKAK:
            hooks = [
                f"Akak, kalau tengah cari produk beauty harian, saya rasa {product_name} ni memang senang nak cuba.",
                f"Saya suka {product_name} ni sebab produk beauty harian macam ni tak rasa serabut sangat nak masuk rutin.",
                f"Jujur cakap, pada saya {product_name} ni jenis produk beauty harian yang nampak simple dan senang capai.",
            ]
            ctas = [
                f"Kalau akak tengah cari produk beauty harian, boleh la try {product_name} ni dulu.",
                f"Saya rasa {product_name} ni okay je kalau akak nak masuk dalam rutin produk beauty harian sendiri.",
                f"{product_name} ni senang je nak cuba kalau akak suka produk beauty harian yang tak over sangat.",
            ]
        elif address_style == ADDRESS_SAYA_ABANG:
            hooks = [
                f"Abang, kalau tengah cari untuk {benefit_phrase.lower()}, saya rasa {product_name} ni okay je.",
                f"Saya suka {product_name} ni sebab abang boleh terus faham kegunaan dia tanpa cerita panjang.",
                f"Pada saya, {product_name} ni memang senang nak masuk dalam rutin harian abang.",
            ]
            ctas = [
                f"Kalau abang rasa ngam dengan {benefit_phrase.lower()}, boleh la try {product_name} ni dulu.",
                f"Saya rasa {product_name} ni okay je kalau abang nak cuba ikut rutin biasa abang.",
                f"{product_name} ni senang je nak tengok sama ada sesuai atau tak dengan rutin harian abang.",
            ]
        else:
            hooks = [
                f"Weh korang, {product_name} ni memang senang nak faham bila cerita pasal {benefit_phrase.lower()}.",
                f"Aku suka {product_name} ni sebab kegunaan dia terus jelas dan tak serabut sangat.",
                f"Pada aku, {product_name} ni okay je untuk masuk dalam rutin harian bila nak benda yang simple.",
            ]
            ctas = [
                f"Kalau korang rasa ngam dengan {benefit_phrase.lower()}, boleh la try {product_name} ni.",
                f"Aku rasa {product_name} ni okay je kalau korang nak cuba ikut apa yang korang perlukan hari-hari.",
                f"{product_name} ni senang je nak tengok sama ada sesuai atau tak dengan rutin korang.",
            ]

    usage_summary = usage_text.split(".")[0].strip() if usage_text else None

    return {
        "hook_angles": hooks,
        "cta_angles": ctas,
        "target_customer": target_customer,
        "usage_summary": usage_summary,
    }
