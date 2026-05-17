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


def _is_sensitive(payload: dict[str, Any]) -> bool:
    claim_gate = _clean_text(payload.get("claim_gate")).upper()
    if claim_gate in {"CLAIM_REVIEW_REQUIRED", "CLAIM_BLOCKED"}:
        return True
    combined = " ".join(
        [
            _clean_text(payload.get("product_name")),
            _clean_text(payload.get("benefits_text")),
            _clean_text(payload.get("usage_text")),
            _clean_text(payload.get("target_customer_text")),
            _clean_text(payload.get("copy_route")),
            _clean_text(payload.get("silo")),
            " ".join(str(token) for token in payload.get("claim_tokens") or []),
        ]
    ).casefold()
    return any(token in combined for token in SENSITIVE_CLAIM_TOKENS)


def generate_registration_hook_cta(payload: dict[str, Any]) -> dict[str, list[str] | str | None]:
    product_name = _clean_text(payload.get("product_name")) or "produk ini"
    target_customer = _clean_text(payload.get("target_customer_text")) or None
    usage_text = _clean_text(payload.get("usage_text"))
    benefit_phrase = _pick_benefit_phrase(_clean_text(payload.get("benefits_text")))
    sensitive = _is_sensitive(payload)

    if sensitive:
        hooks = [
            f"{product_name} diposisikan sebagai rutin self-care luaran yang premium, discreet, dan kemas.",
            f"Gunakan {product_name} sebagai visual produk penjagaan diri luaran dengan tone yakin, tenang, dan non-explicit.",
            f"Fokus {product_name} pada pengalaman urutan luaran dan presentation produk yang clean tanpa janji hasil tertentu.",
        ]
        ctas = [
            f"Lihat bagaimana {product_name} dipersembahkan sebagai rutin penjagaan diri luaran yang lebih premium.",
            f"Terokai visual {product_name} dengan tone discreet, tenang, dan lebih kemas untuk kegunaan luaran.",
            f"Semak bagaimana {product_name} dibingkaikan sebagai self-care luaran tanpa tuntutan perubatan atau prestasi.",
        ]
    else:
        hooks = [
            f"{product_name} menonjolkan {benefit_phrase} dengan presentation yang jelas dan meyakinkan.",
            f"Letakkan {product_name} sebagai pilihan yang praktikal untuk {benefit_phrase.lower()}.",
            f"Angkat {product_name} dengan fokus pada manfaat utama, penggunaan jelas, dan visual yang kemas.",
        ]
        ctas = [
            f"Lihat bagaimana {product_name} menyokong {benefit_phrase.lower()}.",
            f"Terokai {product_name} dengan manfaat utama dan penggunaan yang lebih jelas.",
            f"Semak {product_name} untuk rutin harian yang lebih teratur dan mudah difahami.",
        ]

    usage_summary = usage_text.split(".")[0].strip() if usage_text else None

    return {
        "hook_angles": hooks,
        "cta_angles": ctas,
        "target_customer": target_customer,
        "usage_summary": usage_summary,
    }
