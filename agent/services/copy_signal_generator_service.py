from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent.api.operator import ContentPackSummary, OperatorProduct, _content_pack_summary
from agent.config import OPERATOR_PACK_DIR
from agent.db import crud
from agent.models.copy_signal_generator import (
    CopySignalGenerateRequest,
    CopySignalGenerateResponse,
    CopySignalRoutesResponse,
)
from agent.services.bosmax_product_family import derive_bosmax_product_family
from agent.services.product_mapping import resolve_product_mapping
from agent.services.product_physics import evaluate_prompt_readiness, resolve_product_physics
from agent.services.product_preflight import (
    apply_creative_profile_overrides,
    build_product_preflight,
    evaluate_mapping_status,
    resolve_creative_profile,
)


COPY_SIGNAL_SCOPE = "COPY_SIGNAL_GENERATOR_WITH_STEALTH_ROUTER"
SUPPORTED_ROUTES = ["DIRECT", "STEALTH", "REVIEW_REQUIRED"]
SUPPORTED_CONTENT_STYLE_MODES = ["UGC_IPHONE", "CINEMATIC_PRO"]
AUTHORITY_FILE_TARGETS = [
    "SCRIPT_REGISTRY_UNIFIED.yaml",
    "SCRIPT_VARIANT_LIBRARY.yaml",
    "SOVEREIGN_03_CORE_LOGIC.yaml",
]
STEALTH_KEYWORDS = [
    "stealth",
    "supplement",
    "capsule",
    "detox",
    "slimming",
    "relief",
    "pain",
    "wellness",
    "health",
]
REVIEW_CLAIM_LEVELS = {"HIGH", "VERY_HIGH", "CRITICAL"}
UGC_CAMERA_LOCK = (
    "Raw iPhone handheld footage with subtle hand jitter, natural micro-shake, imperfect creator framing, "
    "quick autofocus breathing, and close-up product-in-hand demo under natural room light. "
    "Do not make it cinematic or overly stabilized."
)
CINEMATIC_CAMERA_LOCK = (
    "Controlled cinematic camera with stable hero framing, smooth push-in, controlled pan, "
    "premium product lighting, and clean commercial composition."
)
COPY_QUALITY_FORBIDDEN_PHRASES = [
    "review the prompt package",
    "before any execution",
    "keep the demo grounded",
    "show the product clearly before",
    "not generated asset",
    "preview-only",
    "prompt package",
    "execution",
]
COPY_QUALITY_WARNING = "COPY_QUALITY_FALLBACK_DRAFT"


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_product_key(value: str | None) -> str:
    return _normalize_text(value).casefold()


async def _load_product_seed(
    request: CopySignalGenerateRequest,
) -> tuple[dict[str, Any] | None, str | None]:
    if request.product_id:
        existing = await crud.get_product(request.product_id)
        if not existing:
            return None, "PRODUCT_NOT_FOUND"
        if request.product_payload:
            merged = dict(existing)
            merged.update(request.product_payload)
            return merged, None
        return dict(existing), None
    if request.product_payload:
        return dict(request.product_payload), None
    return None, "PRODUCT_CONTEXT_REQUIRED"


def _enrich_product(product_seed: dict[str, Any]) -> dict[str, Any]:
    payload = dict(product_seed)
    payload["id"] = payload.get("id") or payload.get("product_id")

    mapping = resolve_product_mapping(
        product=payload,
        product_name=payload.get("raw_product_title")
        or payload.get("product_display_name")
        or payload.get("product_short_name"),
        source_hint=payload.get("source"),
    )
    for key, value in mapping.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    physics = resolve_product_physics(product=payload)
    for key, value in physics.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    creative_profile = resolve_creative_profile(payload)
    payload = apply_creative_profile_overrides(payload, creative_profile)
    for key, value in creative_profile.items():
        if payload.get(key) in (None, "", []):
            payload[key] = value

    payload.update(evaluate_mapping_status(payload))
    payload.update(evaluate_prompt_readiness(payload, physics))
    payload["preflight"] = build_product_preflight(payload)
    payload["product_id"] = payload.get("id") or payload.get("product_id")
    return payload


def _operator_pack_summary() -> ContentPackSummary | None:
    try:
        return _content_pack_summary()
    except HTTPException:
        return None


def _build_operator_lookup(
    operator_pack: ContentPackSummary | None,
) -> dict[str, OperatorProduct]:
    lookup: dict[str, OperatorProduct] = {}
    for product in operator_pack.products if operator_pack else []:
        for value in [
            product.product_id,
            product.product_name,
            product.raw_product_title,
            product.product_display_name,
            product.product_short_name,
        ]:
            key = _normalize_product_key(value)
            if key and key not in lookup:
                lookup[key] = product
    return lookup


def _match_operator_product(
    product: dict[str, Any],
    lookup: dict[str, OperatorProduct],
) -> OperatorProduct | None:
    for value in [
        product.get("id"),
        product.get("product_id"),
        product.get("product_display_name"),
        product.get("raw_product_title"),
        product.get("product_short_name"),
    ]:
        key = _normalize_product_key(value)
        if key and key in lookup:
            return lookup[key]
    return None


def _authority_files() -> tuple[list[str], list[str]]:
    found: list[str] = []
    root = Path(OPERATOR_PACK_DIR)
    if root.exists():
        available = {path.name for path in root.rglob("*.yaml")}
        for name in AUTHORITY_FILE_TARGETS:
            if name in available:
                found.append(name)
    missing = [name for name in AUTHORITY_FILE_TARGETS if name not in found]
    return found, missing


def get_copy_signal_routes_summary() -> CopySignalRoutesResponse:
    found, missing = _authority_files()
    return CopySignalRoutesResponse(
        scope=COPY_SIGNAL_SCOPE,
        routes=SUPPORTED_ROUTES,
        content_style_modes=SUPPORTED_CONTENT_STYLE_MODES,
        authority_files_found=found,
        authority_files_missing=missing,
    )


def _build_route(product: dict[str, Any]) -> tuple[str, str, bool, str]:
    haystack = " ".join(
        _normalize_text(product.get(field))
        for field in [
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "category",
            "subcategory",
            "type",
            "product_type",
            "product_type_id",
            "silo",
            "trigger_id",
        ]
    ).casefold()
    claim_risk = _normalize_text(product.get("claim_risk_level")).upper()
    is_stealth = any(keyword in haystack for keyword in STEALTH_KEYWORDS) or "stealth" in _normalize_text(product.get("silo")).casefold()
    requires_review = is_stealth or claim_risk in REVIEW_CLAIM_LEVELS
    if is_stealth:
        return "STEALTH", "REVIEW_REQUIRED", True, "STEALTH_PRODUCT_REQUIRES_DIALOGUE_ONLY_REVIEW"
    if requires_review:
        return "REVIEW_REQUIRED", "REVIEW_REQUIRED", True, "CLAIM_SAFETY_REVIEW_REQUIRED"
    return "DIRECT", "AUTO_APPROVED", False, "SAFE_DIRECT_PRODUCT"


def _extract_verified_dimensions(product: dict[str, Any]) -> str | None:
    candidate_flags = [
        product.get("product_dimensions_verified"),
        product.get("dimensions_verified"),
        _normalize_text(product.get("product_dimensions_source")).lower() == "verified",
    ]
    measurement_parts: list[str] = []
    for key, suffix in [
        ("length_cm", "cm"),
        ("width_cm", "cm"),
        ("height_cm", "cm"),
        ("depth_cm", "cm"),
        ("diameter_cm", "cm"),
        ("volume_ml", "ml"),
        ("net_weight_g", "g"),
    ]:
        value = product.get(key)
        if value not in (None, ""):
            measurement_parts.append(f"{key}={value}{suffix}")
    text_candidates = [
        _normalize_text(product.get("product_dimensions")),
        _normalize_text(product.get("dimensions")),
        _normalize_text(product.get("verified_dimensions")),
        _normalize_text(product.get("product_dimensions_text")),
    ]
    text_candidates = [item for item in text_candidates if item]
    if any(candidate_flags) and (measurement_parts or text_candidates):
        return "; ".join(text_candidates + measurement_parts)
    return None


def _scale_anchor(product: dict[str, Any]) -> str | None:
    family = derive_bosmax_product_family(product)["bosmax_product_family"]
    if family == "LAUNDRY_DETERGENT_LIQUID_REFILL":
        return "EXACTLY refill detergent pouch or heavy utility bottle size, carried with visible weight and stable two-hand support."
    if family == "FABRIC_SOFTENER_LIQUID":
        return "EXACTLY fabric-softener pouch or bottle size, held upright with label, cap, and pour direction visible."
    if family == "HOUSEHOLD_CLEANER_GENERAL":
        return "EXACTLY household cleaner bottle, pouch, or refill size with stable label-forward utility handling."
    if family == "HOUSEHOLD_STORAGE_ORGANIZER":
        return "EXACTLY organizer or storage-container size, held with both hands to show shape, opening, or stackability."
    if family == "HOME_TEXTILE":
        return "EXACTLY home-textile scale with natural two-hand spread, fold, or drape and no enlargement."
    if family in {"APPAREL_SLEEPWEAR", "fashion_modestwear", "fashion_sportswear", "fashion_apparel"}:
        return "EXACTLY wearable sleepwear scale with natural two-hand drape and no enlargement."
    if family == "ACCESSORY_SMALL_ITEM":
        return "EXACTLY small accessory size, pinched lightly between fingertips without enlargement."
    if family in {"BEAUTY_PERSONAL_CARE", "beauty_fragrance"}:
        return "EXACTLY palm-sized beauty or personal-care product scale unless verified dimensions say otherwise."

    haystack = " ".join(
        _normalize_text(product.get(field))
        for field in [
            "type",
            "product_type",
            "product_scale",
            "physics_class",
        ]
    ).casefold()
    if any(token in haystack for token in ["lip balm", "balm", "dropper", "oil bottle", "roll on", "roll-on", "serum"]):
        return "EXACTLY lip balm size, fit into fingers naturally."
    if any(token in haystack for token in ["envelope", "duit raya", "money packet", "angpow", "red packet"]):
        return "EXACTLY thin envelope size, flat paper packet scale, held naturally between fingers."
    if any(token in haystack for token in ["accessory", "earring", "brooch", "pin", "charm", "pendant", "keychain"]):
        return "EXACTLY small accessory size, pinched lightly between fingertips without enlargement."
    if any(token in haystack for token in ["bottle", "jar", "tube", "mist", "perfume", "supplement"]):
        return "EXACTLY palm-sized bottle scale unless verified dimensions say otherwise."
    if any(token in haystack for token in ["wipes", "soft pack", "pack", "pouch", "diaper"]):
        return "EXACTLY soft-pack size, compressible in hand without oversized enlargement."
    if any(token in haystack for token in ["garment", "textile", "sarung", "telekung", "jersey"]):
        return "EXACTLY wearable garment scale with natural two-hand drape and no enlargement."
    if any(token in haystack for token in ["small", "slim", "flat", "compact"]):
        return "EXACTLY small product scale, held naturally in hand without enlargement."
    if any(
        _normalize_text(product.get(field))
        for field in [
            "product_scale",
            "product_type",
            "recommended_grip",
            "hand_object_interaction",
            "section_5_product_physics_prompt",
        ]
    ):
        return "EXACTLY product-true scale, handled naturally in hand without enlargement."
    return None


def _build_scale_lock(product: dict[str, Any]) -> tuple[str | None, str, str | None, list[str]]:
    verified_dimensions = _extract_verified_dimensions(product)
    anchor = _scale_anchor(product)
    warnings: list[str] = []
    if not anchor:
        return None, "SCALE_NOT_FOUND", "PRODUCT_SCALE_NOT_FOUND", warnings
    details: list[str] = [anchor]
    if verified_dimensions:
        details.append(f"Verified dimensions: {verified_dimensions}.")
        truth_status = "VERIFIED_DIMENSION_SCALE"
        warning = None
    else:
        truth_status = "DERIVED_RELATIVE_SCALE"
        warning = "PRODUCT_SCALE_DERIVED_NOT_DIMENSION_VERIFIED"
        warnings.append(warning)
    for label, value in [
        ("Grip", product.get("recommended_grip")),
        ("Hand interaction", product.get("hand_object_interaction")),
        ("Product physics", product.get("section_5_product_physics_prompt") or product.get("physics_class")),
    ]:
        text = _normalize_text(value)
        if text:
            details.append(f"{label}: {text}.")
    return " ".join(details), truth_status, warning, warnings


def _camera_fields(content_style_mode: str) -> tuple[str, str | None, str | None, str]:
    normalized = _normalize_text(content_style_mode).upper() or "UGC_IPHONE"
    if normalized == "CINEMATIC_PRO":
        return (
            "CINEMATIC_PRO_CONTROLLED",
            None,
            CINEMATIC_CAMERA_LOCK,
            "CAMERA_LOCK_PRESENT",
        )
    return (
        "UGC_IPHONE_RAW",
        UGC_CAMERA_LOCK,
        None,
        "CAMERA_LOCK_PRESENT",
    )


def _copy_value(value: str | None, fallback: str) -> str:
    text = _normalize_text(value)
    return text or fallback


def _normalize_language(product: dict[str, Any]) -> str:
    for field in (
        "language",
        "requested_language",
        "language_default",
        "spoken_language",
    ):
        value = _normalize_text(product.get(field)).casefold()
        if value:
            if any(token in value for token in ["malay", "bahasa melayu", "bahasa malaysia", "bm"]):
                return "MALAY"
            return "ENGLISH"
    return "ENGLISH"


def _copy_haystack(product: dict[str, Any]) -> str:
    return " ".join(
        _normalize_text(product.get(field))
        for field in [
            "raw_product_title",
            "product_display_name",
            "product_short_name",
            "category",
            "subcategory",
            "type",
            "product_type",
            "product_type_id",
        ]
    ).casefold()


def _resolve_direct_copy_family(product: dict[str, Any]) -> str:
    return str(derive_bosmax_product_family(product)["bosmax_product_family"])


def _safe_product_label(product: dict[str, Any]) -> str:
    return _normalize_text(
        product.get("product_short_name")
        or product.get("product_display_name")
        or product.get("raw_product_title")
        or "produk ini"
    )


def _detect_bad_copy_fields(copy_signals: dict[str, Any]) -> list[str]:
    values = [
        _normalize_text(copy_signals.get(key)).casefold()
        for key in [
            "hook",
            "usp_1",
            "usp_2",
            "usp_3",
            "cta",
            "overlay_copy",
            "dialogue_opening",
            "dialogue_body",
            "dialogue_cta",
            "problem",
            "agitate",
            "solution",
        ]
    ]
    hits: list[str] = []
    for value in values:
        if not value:
            continue
        for phrase in COPY_QUALITY_FORBIDDEN_PHRASES:
            if phrase in value and phrase not in hits:
                hits.append(phrase)
        if re.search(r"\buse\b.+\bwith use\b", value) and "use_product_with_use" not in hits:
            hits.append("use_product_with_use")
    return hits


def _direct_copy_templates_malay(
    family: str,
    product_label: str,
) -> tuple[dict[str, str], bool]:
    if family in {"APPAREL_SLEEPWEAR", "fashion_modestwear", "fashion_sportswear", "fashion_apparel"}:
        return (
            {
                "hook": "Baju tidur nak selesa tapi tetap nampak kemas?",
                "usp_1": "Potongan longgar senang dipakai untuk rehat harian.",
                "usp_2": "Kain nampak ringan dan mudah digayakan di rumah.",
                "usp_3": "Sesuai untuk video demo sebab bentuk dan jatuhan kain jelas nampak.",
                "cta": "Pilih warna dan size yang sesuai sebelum checkout.",
                "overlay_copy": f"{product_label} nampak selesa, kemas, dan mudah digaya.",
                "dialogue_opening": "Baju tidur nak selesa tapi tetap nampak kemas?",
                "dialogue_body": "Potongan nampak longgar, kain pula jatuh elok dan senang ditunjuk dalam demo harian dekat rumah.",
                "dialogue_cta": "Pilih warna dan size yang sesuai sebelum checkout.",
            },
            False,
        )
    if family == "LAUNDRY_DETERGENT_LIQUID_REFILL":
        return (
            {
                "hook": "Sabun dobi isi ulang macam ni memang senang masuk rutin basuh harian.",
                "usp_1": "Format refill besar nampak jelas untuk angle nilai dan kegunaan harian.",
                "usp_2": "Senang tunjuk label, penutup, dan cara pegang produk dalam demo praktikal.",
                "usp_3": "Sesuai untuk angle pakaian bersih, wangi, dan stok rumah yang tahan lebih lama tanpa claim berlebihan.",
                "cta": "Pilih variasi yang sesuai dan terus tambah ke cart sebelum checkout.",
                "overlay_copy": f"{product_label} sesuai untuk demo rutin basuh yang praktikal dan jelas.",
                "dialogue_opening": "Kalau basuh baju hari-hari, format isi ulang macam ni memang lagi praktikal.",
                "dialogue_body": "Saiz produk terus nampak value, label senang dibaca dekat kamera, dan cara pegang atau tuang pun mudah dijadikan demo rutin laundry.",
                "dialogue_cta": "Pilih variasi yang sesuai dan terus tambah ke cart sebelum checkout.",
            },
            False,
        )
    if family == "FABRIC_SOFTENER_LIQUID":
        return (
            {
                "hook": "Kalau suka pakaian rasa lebih lembut dan wangi, format macam ni memang senang demo.",
                "usp_1": "Botol atau refill nampak praktikal untuk rutin cucian harian.",
                "usp_2": "Label, penutup, dan arah tuang mudah ditunjuk dalam close-up ringkas.",
                "usp_3": "Sesuai untuk angle pakaian wangi dan rutin dobi yang lebih kemas tanpa claim berlebihan.",
                "cta": "Check variasi yang sesuai dengan rutin cucian kau dan tambah ke cart.",
                "overlay_copy": f"{product_label} bantu demo rutin fabric-care yang lebih jelas.",
                "dialogue_opening": "Kalau rutin dobi kau memang pentingkan rasa lembut dan wangi, produk macam ni senang sangat nak tunjuk.",
                "dialogue_body": "Format produk nampak praktikal, close-up pada label dan penutup pun jelas, jadi senang nak explain kegunaan dia dalam rutin fabric-care harian.",
                "dialogue_cta": "Check variasi yang sesuai dengan rutin cucian kau dan tambah ke cart.",
            },
            False,
        )
    if family == "HOUSEHOLD_CLEANER_GENERAL":
        return (
            {
                "hook": "Produk pembersih macam ni lagi mudah jual bila fungsi dia nampak terus dekat kamera.",
                "usp_1": "Format produk nampak praktikal untuk rutin bersih-bersih harian.",
                "usp_2": "Label dan penutup mudah ditunjuk dalam demo ringkas yang terus faham.",
                "usp_3": "Sesuai untuk angle kegunaan rumah yang jelas tanpa masuk claim berlebihan.",
                "cta": "Pilih variasi yang sesuai dan tambah ke cart sekarang.",
                "overlay_copy": f"{product_label} sesuai untuk demo pembersihan rumah yang praktikal.",
                "dialogue_opening": "Kalau produk pembersih tu senang tunjuk fungsi dia, video pun cepat orang faham.",
                "dialogue_body": "Bentuk produk nampak jelas, cara pegang pun stabil, jadi senang sangat nak explain penggunaan dia dalam rutin bersih-bersih harian.",
                "dialogue_cta": "Pilih variasi yang sesuai dan tambah ke cart sekarang.",
            },
            False,
        )
    if family == "HOUSEHOLD_STORAGE_ORGANIZER":
        return (
            {
                "hook": "Nak rumah nampak lebih tersusun tanpa banyak barang?",
                "usp_1": "Mudah digunakan untuk rutin harian.",
                "usp_2": "Design praktikal, senang tunjuk fungsi dekat kamera.",
                "usp_3": "Sesuai untuk demo sebelum dan selepas yang selamat.",
                "cta": "Tambah ke cart dan pilih variasi yang kau nak.",
                "overlay_copy": f"{product_label} bantu rutin rumah nampak lebih kemas.",
                "dialogue_opening": "Nak rumah nampak lebih tersusun tanpa tambah kerja?",
                "dialogue_body": "Bentuknya nampak praktikal, mudah tunjuk cara guna, dan sesuai untuk demo rutin harian yang jelas dekat kamera.",
                "dialogue_cta": "Tambah ke cart dan pilih variasi yang kau nak.",
            },
            False,
        )
    if family == "HOME_TEXTILE":
        return (
            {
                "hook": "Tekstur dan rasa selesa macam ni memang cepat nampak bila demo dibuat betul.",
                "usp_1": "Mudah tunjuk ketebalan, tekstur, dan saiz produk dekat kamera.",
                "usp_2": "Sesuai untuk angle keselesaan rumah dan kegunaan harian.",
                "usp_3": "Boleh dijadikan demo lipat, bentang, atau sentuh tanpa perlu claim berlebihan.",
                "cta": "Pilih saiz atau variasi yang sesuai dan terus tambah ke cart.",
                "overlay_copy": f"{product_label} tonjolkan tekstur dan keselesaan dengan jelas.",
                "dialogue_opening": "Produk tekstil rumah macam ni memang lagi senang jual bila tekstur dia betul-betul nampak.",
                "dialogue_body": "Bila dibentang atau dipegang dengan stabil, ketebalan dan permukaan produk terus jelas, jadi angle keselesaan rumah lebih mudah masuk.",
                "dialogue_cta": "Pilih saiz atau variasi yang sesuai dan terus tambah ke cart.",
            },
            False,
        )
    if family in {"BEAUTY_PERSONAL_CARE", "beauty_fragrance"}:
        return (
            {
                "hook": "Nak nampak kemas tanpa routine yang leceh?",
                "usp_1": "Mudah ditunjuk dalam demo close-up.",
                "usp_2": "Saiz produk sesuai untuk genggaman tangan.",
                "usp_3": "Sesuai untuk routine harian tanpa claim berlebihan.",
                "cta": "Check pilihan produk dan cuba ikut keperluan kau.",
                "overlay_copy": f"{product_label} sesuai untuk demo close-up yang ringkas.",
                "dialogue_opening": "Nak routine nampak kemas tanpa rasa serabut?",
                "dialogue_body": "Saiz produk senang digenggam, close-up nampak jelas, dan penggunaan harian boleh ditunjuk dengan cara yang terus faham.",
                "dialogue_cta": "Check pilihan produk dan cuba ikut keperluan kau.",
            },
            False,
        )
    if family == "ACCESSORY_SMALL_ITEM":
        return (
            {
                "hook": "Detail kecil macam ni boleh terus naikkan gaya.",
                "usp_1": "Saiz kecil, mudah ditunjuk dekat kamera.",
                "usp_2": "Detail produk nampak jelas bila close-up.",
                "usp_3": "Senang padankan dengan gaya harian.",
                "cta": "Pilih design yang kau suka sekarang.",
                "overlay_copy": f"{product_label} bagi sentuhan gaya yang terus nampak dekat kamera.",
                "dialogue_opening": "Kadang-kadang detail kecil yang paling cepat ubah gaya.",
                "dialogue_body": "Bila close-up, detail produk lebih jelas, saiz pun mudah ditunjuk, jadi senang sangat nak padankan dengan gaya harian.",
                "dialogue_cta": "Pilih design yang kau suka sekarang.",
            },
            False,
        )
    return (
        {
            "hook": f"Nak tunjuk {product_label} dengan cara yang lebih jelas dan mudah faham?",
            "usp_1": "Boleh digunakan untuk demo produk ringkas yang fokus pada rupa dan fungsi asas.",
            "usp_2": "Sesuai untuk penerangan pendek tanpa claim berlebihan.",
            "usp_3": "Masih perlukan semakan manusia sebelum dijadikan copy produksi penuh.",
            "cta": "Semak butiran produk dulu sebelum terus guna untuk produksi.",
            "overlay_copy": f"{product_label} perlukan copy yang diperkemaskan sebelum produksi.",
            "dialogue_opening": f"Nak tunjuk {product_label} dengan cara yang lebih jelas?",
            "dialogue_body": "Asas copy untuk produk ini sudah ada, tetapi nada komersial dan sudut jualan masih perlukan penajaman sebelum digunakan terus.",
            "dialogue_cta": "Semak butiran produk dulu sebelum terus guna untuk produksi.",
        },
        True,
    )


def _direct_copy_templates_english(
    family: str,
    product_label: str,
) -> tuple[dict[str, str], bool]:
    if family == "APPAREL_SLEEPWEAR":
        return (
            {
                "hook": "Want sleepwear that feels comfortable and still looks neat?",
                "usp_1": "Relaxed cutting makes it easy to wear for everyday rest.",
                "usp_2": "The fabric reads light and easy to style at home.",
                "usp_3": "Works well for short demos because the shape and drape show clearly.",
                "cta": "Choose the color and size that fits before checkout.",
                "overlay_copy": f"{product_label} looks comfortable, neat, and easy to wear.",
                "dialogue_opening": "Want sleepwear that feels comfortable and still looks neat?",
                "dialogue_body": "The cut looks relaxed, the fabric drapes clearly on camera, and the overall look stays tidy for an everyday home demo.",
                "dialogue_cta": "Choose the color and size that fits before checkout.",
            },
            False,
        )
    if family == "LAUNDRY_DETERGENT_LIQUID_REFILL":
        return (
            {
                "hook": "A refill detergent format like this works well when the daily laundry value is obvious on camera.",
                "usp_1": "Large refill sizing gives a clear everyday-utility and value angle.",
                "usp_2": "Label, cap, and handling cues are easy to show in a practical demo.",
                "usp_3": "Fits a clothes-cleaning and freshness routine angle without exaggerated claims.",
                "cta": "Choose the variation that fits your laundry routine and add it to cart.",
                "overlay_copy": f"{product_label} fits a practical laundry routine demo.",
                "dialogue_opening": "If you wash clothes often, a refill format like this is easy to explain in a short demo.",
                "dialogue_body": "The product size reads as practical value, the label stays visible, and the way you carry or pour it makes sense for a laundry-routine video.",
                "dialogue_cta": "Choose the variation that fits your laundry routine and add it to cart.",
            },
            False,
        )
    if family == "FABRIC_SOFTENER_LIQUID":
        return (
            {
                "hook": "Fabric-care products like this work best when the softness and freshness routine feels easy to picture.",
                "usp_1": "Bottle or refill format reads clearly in a daily laundry setting.",
                "usp_2": "Label, cap, and pour direction are easy to show in close-up.",
                "usp_3": "Supports a freshness and fabric-care angle without exaggerated claims.",
                "cta": "Check the variation that fits your laundry routine and add it to cart.",
                "overlay_copy": f"{product_label} supports a practical fabric-care demo.",
                "dialogue_opening": "If your audience cares about a softer, fresher laundry routine, this format is easy to explain.",
                "dialogue_body": "The product shape looks practical, the close-up details stay visible, and the routine angle is easy to understand in a short demo.",
                "dialogue_cta": "Check the variation that fits your laundry routine and add it to cart.",
            },
            False,
        )
    if family == "HOUSEHOLD_CLEANER_GENERAL":
        return (
            {
                "hook": "Cleaner products like this work best when the function is obvious right away on camera.",
                "usp_1": "Practical format makes the daily-use angle easy to explain.",
                "usp_2": "Label and opening details stay readable in a short demo.",
                "usp_3": "Fits a clear household-cleaning angle without exaggerated claims.",
                "cta": "Choose the variation that fits your needs and add it to cart.",
                "overlay_copy": f"{product_label} works for a clear household-cleaning demo.",
                "dialogue_opening": "When a cleaner is easy to demonstrate, the video lands faster.",
                "dialogue_body": "The shape looks practical, the handling stays stable, and the use case is easy to understand in a short household-cleaning demo.",
                "dialogue_cta": "Choose the variation that fits your needs and add it to cart.",
            },
            False,
        )
    if family == "HOUSEHOLD_STORAGE_ORGANIZER":
        return (
            {
                "hook": "Want your space to look more organized without adding clutter?",
                "usp_1": "Easy to use in a daily routine.",
                "usp_2": "Practical design that shows its function clearly on camera.",
                "usp_3": "Safe for before-and-after style demos.",
                "cta": "Add it to cart and choose the variation you want.",
                "overlay_copy": f"{product_label} helps daily routines look more organized.",
                "dialogue_opening": "Want your space to feel more organized with less effort?",
                "dialogue_body": "The format looks practical, the use case is easy to show, and the routine benefit reads clearly in a short demo.",
                "dialogue_cta": "Add it to cart and choose the variation you want.",
            },
            False,
        )
    if family == "HOME_TEXTILE":
        return (
            {
                "hook": "Products like this sell faster when the texture and comfort are easy to see.",
                "usp_1": "Thickness, texture, and size are easy to show on camera.",
                "usp_2": "Fits a comfort-led home-use angle.",
                "usp_3": "Works for fold, spread, or touch-led demos without exaggerated claims.",
                "cta": "Choose the size or variation that fits and add it to cart.",
                "overlay_copy": f"{product_label} makes texture and comfort easier to show.",
                "dialogue_opening": "Home textiles like this work best when the surface and feel come through clearly.",
                "dialogue_body": "Once the product is spread or held steadily, the texture, thickness, and home-comfort angle read much more clearly on camera.",
                "dialogue_cta": "Choose the size or variation that fits and add it to cart.",
            },
            False,
        )
    if family == "BEAUTY_PERSONAL_CARE":
        return (
            {
                "hook": "Want a neater routine without adding extra hassle?",
                "usp_1": "Easy to show in a close-up demo.",
                "usp_2": "Product size sits naturally in hand.",
                "usp_3": "Fits an everyday routine without exaggerated claims.",
                "cta": "Check the option that fits your needs.",
                "overlay_copy": f"{product_label} fits a simple close-up routine demo.",
                "dialogue_opening": "Want your routine to look cleaner without feeling complicated?",
                "dialogue_body": "The size reads well in hand, close-up details stay visible, and the daily-use angle is easy to understand in a short video.",
                "dialogue_cta": "Check the option that fits your needs.",
            },
            False,
        )
    if family == "ACCESSORY_SMALL_ITEM":
        return (
            {
                "hook": "A small detail like this can lift the whole look fast.",
                "usp_1": "Compact size makes it easy to show on camera.",
                "usp_2": "Details stay visible in close-up.",
                "usp_3": "Easy to pair with everyday styling.",
                "cta": "Choose the design you like now.",
                "overlay_copy": f"{product_label} adds a quick style detail that reads on camera.",
                "dialogue_opening": "Sometimes a small detail changes the whole look.",
                "dialogue_body": "The close-up detail reads clearly, the size is easy to handle on camera, and it fits naturally into everyday styling.",
                "dialogue_cta": "Choose the design you like now.",
            },
            False,
        )
    return (
        {
            "hook": f"Need a clearer way to present {product_label} to shoppers?",
            "usp_1": "Usable for a simple product demo focused on visible form and basic function.",
            "usp_2": "Fits a short explanation without exaggerated claims.",
            "usp_3": "Still needs a stronger commercial angle before production use.",
            "cta": "Review the product details before using this in production.",
            "overlay_copy": f"{product_label} still needs sharper production-ready copy.",
            "dialogue_opening": f"Need a clearer way to present {product_label}?",
            "dialogue_body": "The basic copy structure is present, but the sales angle still needs refinement before it is ready for production output.",
            "dialogue_cta": "Review the product details before using this in production.",
        },
        True,
    )


def _detect_family_copy_mismatch(copy_signals: dict[str, Any], family: str) -> list[str]:
    haystack = " ".join(
        _normalize_text(copy_signals.get(key))
        for key in [
            "hook",
            "usp_1",
            "usp_2",
            "usp_3",
            "cta",
            "overlay_copy",
            "dialogue_opening",
            "dialogue_body",
            "dialogue_cta",
        ]
    ).casefold()
    mismatches: list[str] = []
    if family in {
        "LAUNDRY_DETERGENT_LIQUID_REFILL",
        "FABRIC_SOFTENER_LIQUID",
        "HOUSEHOLD_CLEANER_GENERAL",
    }:
        for phrase in [
            "rumah nampak lebih tersusun",
            "tanpa banyak barang",
            "organized without adding clutter",
            "space to look more organized",
        ]:
            if phrase in haystack and phrase not in mismatches:
                mismatches.append(phrase)
    if family == "HOUSEHOLD_STORAGE_ORGANIZER":
        for phrase in ["pakaian bersih", "laundry routine", "sabun dobi", "detergent"]:
            if phrase in haystack and phrase not in mismatches:
                mismatches.append(phrase)
    return mismatches


def _build_direct_commercial_copy(
    product: dict[str, Any],
    operator_product: OperatorProduct | None,
) -> tuple[dict[str, str], str, bool, str]:
    product_label = _safe_product_label(product)
    language = _normalize_language(product)
    family = _resolve_direct_copy_family(product)
    if operator_product:
        candidate = {
            "hook": _copy_value(operator_product.hook, ""),
            "usp_1": _copy_value(operator_product.usp_1, ""),
            "usp_2": _copy_value(operator_product.usp_2, ""),
            "usp_3": _copy_value(operator_product.usp_3, ""),
            "cta": _copy_value(operator_product.cta, ""),
        }
        if (
            not _detect_bad_copy_fields(candidate)
            and not _detect_family_copy_mismatch(candidate, family)
            and all(candidate.values())
        ):
            overlay_copy = (
                f"{product_label} nampak lebih jelas dalam demo ringkas."
                if language == "MALAY"
                else f"{product_label} looks clear and easy to understand in a short demo."
            )
            dialogue_opening = candidate["hook"]
            dialogue_body = " ".join(
                [candidate["usp_1"], candidate["usp_2"], candidate["usp_3"]]
            )
            return (
                {
                    **candidate,
                    "overlay_copy": overlay_copy,
                    "dialogue_opening": dialogue_opening,
                    "dialogue_body": dialogue_body,
                    "dialogue_cta": candidate["cta"],
                },
                "OPERATOR_PACK",
                False,
                family,
            )
    if language == "MALAY":
        payload, is_general = _direct_copy_templates_malay(family, product_label)
    else:
        payload, is_general = _direct_copy_templates_english(family, product_label)
    return (
        payload,
        "GENERIC_FALLBACK" if is_general else "BOSMAX_FAMILY_TEMPLATE",
        is_general,
        family,
    )


def _build_stealth_copy_signals(
    product: dict[str, Any],
    dialogue_metaphor_hint: str | None,
    route_reason: str,
) -> dict[str, str]:
    metaphor = _normalize_text(dialogue_metaphor_hint) or "lapisan tenang untuk rutin harian"
    product_label = _safe_product_label(product)
    language = _normalize_language(product)
    silo = _normalize_text(product.get("silo") or "STEALTH_UNSPECIFIED")
    formula = _normalize_text(product.get("formula") or "STEALTH_DIALOGUE_SAFE")
    if language == "MALAY":
        hook = "Bila hari terasa panjang, ramai suka cari rutin yang rasa lebih teratur."
        problem = "Bila mesej jualan terlalu terus terang, audiens cepat rasa menjauh."
        agitate = "Nada yang keras boleh buat produk sensitif nampak tidak selesa untuk ditonton."
        solution = f"Gunakan metafora dialog selamat seperti '{metaphor}' sambil kekalkan visual produk literal dan jelas."
        usp_1 = f"{product_label} boleh dibingkaikan melalui rutin harian yang lebih lembut."
        usp_2 = "Dialog boleh fokus pada disiplin, rasa tersusun, dan konsistensi tanpa claim sensitif."
        usp_3 = "Semua mesej perlu semakan manusia sebelum masuk ke produksi."
        cta = "Semak naratif dialog ini dulu sebelum guna untuk output video."
    else:
        hook = "When the day feels heavy, audiences respond better to a calmer routine-led story."
        problem = "Sensitive products lose trust fast when the message sounds too direct."
        agitate = "Hard-sell language can make the product feel unsafe or non-compliant on camera."
        solution = f"Use a dialogue-safe metaphor such as '{metaphor}' while keeping the visual product demo literal and grounded."
        usp_1 = f"{product_label} can be framed through a softer everyday-routine narrative."
        usp_2 = "Dialogue can stay focused on discipline, rhythm, and routine without sensitive claims."
        usp_3 = "Human review is still required before any production use."
        cta = "Review this dialogue narrative before using it in video output."
    return {
        "stealth_silo": silo,
        "metaphor_family": "DIALOGUE_SAFE_ROUTINE",
        "formula": formula,
        "hook": hook,
        "problem": problem,
        "agitate": agitate,
        "solution": solution,
        "usp_1": usp_1,
        "usp_2": usp_2,
        "usp_3": usp_3,
        "cta": cta,
        "overlay_copy": metaphor,
        "dialogue_opening": hook,
        "dialogue_body": " ".join([problem, agitate, solution]),
        "dialogue_cta": cta,
        "human_review_reason": route_reason,
    }


def _assess_copy_quality(
    product: dict[str, Any],
    route: str,
    review_status: str,
    copy_signals: dict[str, Any],
    is_general_fallback: bool,
    family: str,
    copy_source: str,
) -> tuple[str, str, list[str], str, str]:
    required_fields = ["hook", "usp_1", "usp_2", "usp_3", "cta"]
    if any(not _normalize_text(copy_signals.get(field)) for field in required_fields):
        return (
            "COPY_MISSING",
            "Copy fields are incomplete and cannot support production output yet.",
            ["COPY_MISSING_TEXT_TO_VIDEO_NOT_READY"],
            "COPY_MISSING",
            "COPY_FIELDS_INCOMPLETE",
        )
    if route in {"STEALTH", "REVIEW_REQUIRED"} or review_status == "REVIEW_REQUIRED":
        return (
            "REVIEW_REQUIRED",
            "Sensitive or stealth copy stays review-gated even when dialogue-safe suggestions exist.",
            ["COPY_ROUTE_REVIEW_REQUIRED"],
            "NEEDS_REVIEW",
            "STEALTH_OR_SENSITIVE_ROUTE_REQUIRES_REVIEW",
        )
    bad_phrases = _detect_bad_copy_fields(copy_signals)
    mismatch_phrases = _detect_family_copy_mismatch(copy_signals, family)
    if mismatch_phrases:
        return (
            "FALLBACK_COPY_DRAFT",
            "Copy theme does not semantically match the derived BOSMAX product family and must be corrected before production use.",
            [COPY_QUALITY_WARNING, "COPY_FAMILY_SEMANTIC_MISMATCH"],
            "NEEDS_REVIEW",
            "SEMANTIC_MISMATCH_WITH_BOSMAX_PRODUCT_FAMILY",
        )
    if bad_phrases or is_general_fallback:
        warnings = [COPY_QUALITY_WARNING]
        return (
            "FALLBACK_COPY_DRAFT",
            "Copy exists, but it is still generic or internally framed and must be upgraded before production use.",
            warnings,
            "NEEDS_REVIEW",
            "GENERIC_OR_INTERNAL_COPY_FALLBACK",
        )
    return (
        "COMMERCIAL_COPY_READY",
        "Copy is consumer-facing, product-safe, and semantically aligned to the derived BOSMAX product family.",
        [],
        "READY",
        "SEMANTIC_FIT_CONFIRMED",
    )


def build_copy_signal_response_for_product(
    product: dict[str, Any],
    *,
    content_style_mode: str = "UGC_IPHONE",
    dialogue_metaphor_hint: str | None = None,
    operator_pack: ContentPackSummary | None = None,
) -> CopySignalGenerateResponse:
    found_files, _ = _authority_files()
    route, review_status, requires_review, route_reason = _build_route(product)
    operator_lookup = _build_operator_lookup(operator_pack)
    operator_product = _match_operator_product(product, operator_lookup)
    normalized_hint = _normalize_text(dialogue_metaphor_hint)
    family_context = derive_bosmax_product_family(product)
    product_scale_prompt, scale_truth_status, scale_warning, scale_warnings = _build_scale_lock(product)
    camera_capture_mode, ugc_camera_lock_prompt, cinematic_camera_prompt, camera_truth_status = _camera_fields(content_style_mode)

    is_general_fallback = False
    copy_source = "GENERIC_FALLBACK"
    derived_family = str(family_context["bosmax_product_family"])
    if route == "DIRECT":
        copy_signals, copy_source, is_general_fallback, derived_family = _build_direct_commercial_copy(
            product,
            operator_product if route == "DIRECT" else None,
        )
    else:
        copy_signals = _build_stealth_copy_signals(
            product,
            normalized_hint if route == "STEALTH" else None,
            route_reason,
        )
        copy_source = "STEALTH_DIALOGUE_SAFE"
    copy_quality_status, copy_quality_detail, quality_warnings, text_to_video_status, copy_quality_reason = _assess_copy_quality(
        product,
        route,
        review_status,
        copy_signals,
        is_general_fallback,
        derived_family,
        copy_source,
    )
    copy_signals.update(
        {
            "copy_quality_status": copy_quality_status,
            "copy_quality_detail": copy_quality_detail,
            "copy_quality_reason": copy_quality_reason,
            "copy_source": copy_source,
            "warning": COPY_QUALITY_WARNING if COPY_QUALITY_WARNING in quality_warnings else None,
        }
    )

    truth_warnings = list(scale_warnings)
    truth_warnings.extend(quality_warnings)
    preview_warnings: list[str] = []
    if route != "DIRECT":
        if "COPY_ROUTE_REVIEW_REQUIRED" not in truth_warnings:
            truth_warnings.append("COPY_ROUTE_REVIEW_REQUIRED")
    if route == "DIRECT" and not operator_product and copy_source == "GENERIC_FALLBACK":
        truth_warnings.append("COPY_SIGNAL_GENERIC_FAMILY_FALLBACK")
    if not ugc_camera_lock_prompt and _normalize_text(content_style_mode).upper() == "UGC_IPHONE":
        truth_warnings.append("UGC_CAMERA_LOCK_MISSING")
    if scale_truth_status == "SCALE_NOT_FOUND":
        truth_warnings.append("PRODUCT_SCALE_PROMPT_MISSING")
    if family_context["bosmax_source_taxonomy_conflict"]:
        truth_warnings.append("BOSMAX_FAMILY_OVERRIDES_SOURCE_TAXONOMY")
    if route == "DIRECT" and not operator_product and copy_source == "BOSMAX_FAMILY_TEMPLATE":
        preview_warnings.append("OPERATOR_PACK_COPY_SIGNALS_NOT_FOUND")
    warnings = truth_warnings + preview_warnings

    product_context = {
        "product_id": product.get("id") or product.get("product_id"),
        "product_display_name": product.get("product_display_name"),
        "raw_product_title": product.get("raw_product_title"),
        "bosmax_product_family": derived_family,
        "bosmax_product_family_reason": family_context["bosmax_product_family_reason"],
        "bosmax_source_taxonomy_conflict": family_context["bosmax_source_taxonomy_conflict"],
        "bosmax_source_taxonomy_conflict_reason": family_context["bosmax_source_taxonomy_conflict_reason"],
        "product_type": product.get("product_type") or product.get("product_type_id"),
        "scene_context": product.get("scene_context"),
        "camera_style": product.get("camera_style"),
        "camera_behavior": product.get("camera_behavior"),
        "product_scale": product.get("product_scale"),
        "recommended_grip": product.get("recommended_grip"),
        "hand_object_interaction": product.get("hand_object_interaction"),
        "product_physics": product.get("section_5_product_physics_prompt") or product.get("physics_class"),
        "product_scale_prompt": product_scale_prompt,
        "scale_truth_status": scale_truth_status,
        "scale_warning": scale_warning,
        "camera_capture_mode": camera_capture_mode,
        "ugc_camera_lock_prompt": ugc_camera_lock_prompt,
        "cinematic_camera_prompt": cinematic_camera_prompt or CINEMATIC_CAMERA_LOCK,
        "camera_truth_status": camera_truth_status,
        "copy_quality_status": copy_quality_status,
        "copy_quality_detail": copy_quality_detail,
        "copy_source": copy_source,
        "copy_quality_reason": copy_quality_reason,
    }

    return CopySignalGenerateResponse(
        scope=COPY_SIGNAL_SCOPE,
        route=route,
        review_status=review_status,
        copy_quality_status=copy_quality_status,
        text_to_video_readiness_status=text_to_video_status,
        content_style_mode=_normalize_text(content_style_mode).upper() or "UGC_IPHONE",
        authority_files_found=found_files,
        product_context=product_context,
        copy_signals=copy_signals,
        claim_safety={
            "requires_human_review": requires_review,
            "claim_risk_level": _normalize_text(product.get("claim_risk_level")),
            "reason": route_reason,
        },
        visual_dialogue_isolation={
            "status": "ENFORCED" if route == "STEALTH" else "PASS",
            "visual_metaphor_allowed": False,
            "dialogue_metaphor_allowed": route == "STEALTH",
            "dialogue_metaphor_hint": normalized_hint if route == "STEALTH" else None,
            "blocked_visual_fields": [
                "product_scale_prompt",
                "ugc_camera_lock_prompt",
                "cinematic_camera_prompt",
                "scene_context",
                "camera_behavior",
                "product_handling",
            ],
        },
        warnings=warnings,
        truth_warnings=truth_warnings,
        preview_warnings=preview_warnings,
        provenance={
            "scope": COPY_SIGNAL_SCOPE,
            "operator_pack_available": bool(operator_pack),
            "operator_pack_copy_signals_used": copy_source == "OPERATOR_PACK",
        },
    )


async def generate_copy_signal_response(
    request_input: dict[str, Any] | CopySignalGenerateRequest,
) -> CopySignalGenerateResponse:
    request = (
        request_input
        if isinstance(request_input, CopySignalGenerateRequest)
        else CopySignalGenerateRequest.model_validate(request_input)
    )
    product_seed, error = await _load_product_seed(request)
    if error == "PRODUCT_NOT_FOUND":
        return CopySignalGenerateResponse(
            scope=COPY_SIGNAL_SCOPE,
            route="REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            copy_quality_status="COPY_MISSING",
            text_to_video_readiness_status="COPY_MISSING",
            content_style_mode=request.content_style_mode,
            warnings=["PRODUCT_NOT_FOUND"],
            provenance={"scope": COPY_SIGNAL_SCOPE},
        )
    if error == "PRODUCT_CONTEXT_REQUIRED":
        return CopySignalGenerateResponse(
            scope=COPY_SIGNAL_SCOPE,
            route="REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            copy_quality_status="COPY_MISSING",
            text_to_video_readiness_status="COPY_MISSING",
            content_style_mode=request.content_style_mode,
            warnings=["PRODUCT_CONTEXT_REQUIRED"],
            provenance={"scope": COPY_SIGNAL_SCOPE},
        )

    enriched = _enrich_product(product_seed or {})
    operator_pack = _operator_pack_summary()
    return build_copy_signal_response_for_product(
        enriched,
        content_style_mode=request.content_style_mode,
        dialogue_metaphor_hint=request.dialogue_metaphor_hint or request.stealth_metaphor,
        operator_pack=operator_pack,
    )
