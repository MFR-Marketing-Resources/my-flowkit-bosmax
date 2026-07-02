"""THE canonical final prompt compiler — single engine-facing authority (ADR-008).

One deterministic, section-driven, source-mode-aware, WPS-governed renderer for
every final engine-facing prompt across T2V / HYBRID / FRAMES / INGREDIENTS /
IMAGES. Authority = the retained pack files vendored under agent/authority/:

- VIDEO_PROMPT_COMPILER_TEMPLATES.yaml   canonical 9 sections + source-mode law
- BOSMAX_CUSTOM_INSTRUCTION.txt          prompt language lock + scrub law
- wps_blocking_authority.json            block plans (1-7) + per-language WPS
- AVATAR_POOL_NORMALIZED.csv             presenter registry (via avatar_registry)
- COPYWRITING_FRAMEWORK_UNIVERSAL.yaml   copy intelligence (secondary reference)

Contract highlights (retained law):
- exactly one complete 9-section set per block, canonical order;
- Sections 1,2,3,4,5,7,8,9 = English instruction prose; Section 6 = target
  language spoken dialogue ONLY;
- SafeWPS default, SweetWPS deliberate mode (Malay Sweet = 2.7 from workbook);
- dialogue budget is per block, never whole-prompt filler;
- CTA lands only in the final block;
- NO_OVERLAY default;
- no leakage: no source-mode taxonomy, WPS numbers, block plans, debug JSON,
  avatar-pool references, or generic placeholder presenter wording.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.services import avatar_registry

_AUTHORITY_DIR = Path(__file__).resolve().parent.parent / "authority"

CANONICAL_SECTIONS = (
    "SECTION 1 - ROLE & OBJECTIVE",
    "SECTION 2 - PRODUCT TRUTH LOCK",
    "SECTION 3 - CONTINUITY & STATE LOCK",
    "SECTION 4 - VISUAL STORY",
    "SECTION 5 - SHOT & CAMERA RULES",
    "SECTION 6 - SPOKEN DIALOGUE",
    "SECTION 7 - VOICE & DELIVERY",
    "SECTION 8 - CTA & END FRAME",
    "SECTION 9 - NO_OVERLAY",
)

SOURCE_MODES = ("T2V", "HYBRID", "FRAMES", "INGREDIENTS", "IMAGES")

_LANGUAGE_NAMES = {
    "BM_MS": "Malay", "MALAY": "Malay", "MS": "Malay",
    "EN": "English", "ENGLISH": "English",
    "ID": "Indonesian", "INDONESIAN": "Indonesian",
    "ZH": "Mandarin", "MANDARIN": "Mandarin",
    "TA": "Tamil", "TAMIL": "Tamil",
    "TH": "Thai", "THAI": "Thai",
}

_FORMULA_FAMILIES = ("PAS", "AIDA", "HSO", "BAB", "PESTA", "PASTOR")


@lru_cache(maxsize=1)
def _wps_authority() -> dict:
    with open(_AUTHORITY_DIR / "wps_blocking_authority.json", encoding="utf-8") as f:
        return json.load(f)


def language_name(target_language: str | None) -> str:
    key = str(target_language or "BM_MS").strip().upper()
    return _LANGUAGE_NAMES.get(key, "Malay")


def wps_profile(target_language: str | None) -> dict:
    profile = _wps_authority()["language_wps"].get(language_name(target_language))
    if not profile:
        raise ValueError(f"LANGUAGE_WPS_MISSING:{target_language}")
    return profile


def dialogue_word_budget(
    block_seconds: int, target_language: str | None, *, wps_mode: str = "SAFE",
) -> int:
    """Per-block dialogue budget from WORKBOOK authority. SafeWPS default;
    SweetWPS is the deliberate dialogue-targeting mode (Malay Sweet = 2.7)."""
    profile = wps_profile(target_language)
    rate = profile["sweet_wps"] if str(wps_mode).upper() == "SWEET" else profile["safe_wps"]
    return max(4, round(block_seconds * float(rate)))


def resolve_block_plan(
    engine: str, duration_seconds: int, *, preferred_lane: str | None = None,
) -> list[int]:
    """Block plan from workbook authority ONLY (1-7 blocks). Never accept a
    manual block plan. Google Flow 40s requires a preferred lane choice."""
    eng = str(engine or "GOOGLE_FLOW").strip().upper().replace(" ", "_")
    matches = [
        p for p in _wps_authority()["block_plans"]
        if p["engine"] == eng and p["duration_seconds"] == int(duration_seconds)
    ]
    if not matches:
        raise ValueError(f"UNSUPPORTED_ENGINE_DURATION:{eng}:{duration_seconds}")
    if len(matches) > 1:
        if not preferred_lane:
            raise ValueError(f"PREFERRED_LANE_REQUIRED:{eng}:{duration_seconds}")
        lane = str(preferred_lane).strip().lower()
        for p in matches:
            row_lane = str(p.get("preferred_lane") or "").strip().lower()
            aliases = {
                row_lane,                          # "lane a"
                row_lane.split()[-1] if row_lane else "",  # "a"
                f"{p['blocks'][0]}s",              # "10s" / "8s" (block size lane)
            }
            if lane in aliases:
                return list(p["blocks"])
        raise ValueError(f"UNKNOWN_PREFERRED_LANE:{preferred_lane}")
    return list(matches[0]["blocks"])


# ── copy intelligence ─────────────────────────────────────────────────────────

def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_copy_intelligence(
    copy: dict[str, Any] | None, *, product: dict[str, Any] | None = None,
) -> dict:
    """Structured copywriting fields (angle/hook/subhook/usp/cta/formula).
    The copy bank is a SECONDARY reference that keeps dialogue from going mute —
    missing fields degrade gracefully, they never fail the compile."""
    copy = copy or {}
    product = product or {}
    formula = _clean(copy.get("formula_family") or copy.get("formula")).upper() or "HSO"
    if formula not in _FORMULA_FAMILIES:
        formula = "HSO"
    angle = _clean(copy.get("angle") or copy.get("copywriting_angle") or product.get("copywriting_angle"))
    cta = _clean(copy.get("cta"))
    usps = [
        _clean(u) for u in (
            copy.get("usps")
            or [copy.get("usp1"), copy.get("usp2"), copy.get("usp3"), copy.get("usp")]
        ) if _clean(u)
    ]
    family = _infer_product_family(product, {"angle": angle})
    product_name = _product_name(product)
    hook = _clean(copy.get("hook"))
    subhook = _clean(copy.get("subhook"))
    copy_angle = _clean(copy.get("copywriting_angle") or product.get("copywriting_angle"))
    hook = "" if _is_low_signal_legacy_copy(hook, product_name=product_name) else hook
    subhook = "" if _is_low_signal_legacy_copy(subhook, product_name=product_name) else subhook
    cta = "" if _is_low_signal_legacy_copy(cta, product_name=product_name) else cta
    copy_angle = "" if _is_low_signal_legacy_copy(copy_angle, product_name=product_name) else copy_angle
    usps = [usp for usp in usps if not _is_low_signal_legacy_copy(usp, product_name=product_name)]
    trigger_id = _guard_trigger_for_family(
        _infer_trigger_id(product, copy, family=family, angle=angle),
        family=family,
    )
    return {
        "angle": angle,
        "hook": hook,
        "subhook": subhook,
        "usps": usps,
        "cta": cta,
        "formula_family": formula,
        "copywriting_angle": copy_angle,
        "trigger_id": trigger_id,
        "cta_type": _infer_cta_type(copy, cta),
    }


def _is_low_signal_legacy_copy(text: str, *, product_name: str) -> bool:
    clause = _clean(text)
    if not clause:
        return False
    lowered = clause.lower()
    product_lower = _clean(product_name).lower()
    generic_markers = (
        "rutin penjagaan diri yang lebih kemas",
        "rutin penjagaan diri yang lebih kemas dan premium",
        "presentation yang jelas",
        "pilihan yang praktikal",
        "manfaat utama dan penggunaan yang lebih jelas",
        "rutin harian yang lebih teratur",
        "lebih teratur dan mudah difahami",
        "senang nak faham bila cerita pasal",
        "okay je untuk masuk dalam rutin harian",
        "self-care luaran",
        "tone discreet",
        "non-explicit",
        "tanpa tuntutan perubatan atau prestasi",
    )
    if any(marker in lowered for marker in generic_markers):
        return True
    if len(clause.split()) >= 6 and lowered.startswith(
        ("lihat bagaimana", "terokai", "semak bagaimana", "gunakan ", "fokus ")
    ):
        return True
    if product_lower and lowered.startswith(product_lower):
        tail = lowered[len(product_lower):].strip(" ,.-")
        if len(clause.split()) >= 10 and any(
            token in tail for token in ("menonjolkan", "letakkan", "angkat", "lihat bagaimana", "terokai", "semak bagaimana")
        ):
            return True
        if len(clause.split()) >= 12 and any(
            token in tail for token in ("support", "routine", "premium", "jelas", "praktikal", "mudah difahami")
        ):
            return True
    return False


def _product_name(product: dict[str, Any]) -> str:
    raw = (
        _clean(
            product.get("name")
            or product.get("product_name")
            or product.get("product_display_name")
            or product.get("raw_product_title")
            or product.get("product_short_name")
        )
        or "the product"
    )
    cleaned = re.sub(r"\s*\[[^\]]*\]\s*", " ", raw)
    cleaned = re.sub(r"\s*\([^)]*\)\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"\s+-\s+", " - ", cleaned).strip(" -")
    return cleaned or raw


def _product_visual_alias(product: dict[str, Any], family: str) -> str:
    explicit = _clean(
        product.get("product_short_name")
        or product.get("product_display_name_short")
        or product.get("visual_display_name")
    )
    if explicit:
        return explicit
    full = _product_name(product)
    alias = full
    split_markers = (
        " | ",
        " serasi dengan ",
        " suitable for ",
        " ready stock",
        " preorder ",
        " buy ",
        " free ",
        " sku:",
    )
    lowered = alias.lower()
    for marker in split_markers:
        idx = lowered.find(marker)
        if idx > 0:
            alias = alias[:idx]
            lowered = alias.lower()
    alias = re.sub(r"\bsku\s*:\s*.*$", "", alias, flags=re.IGNORECASE).strip(" ,.-")
    words = alias.split()
    fallback_type = _clean(product.get("type"))
    if family == "baby_care" and fallback_type and len(words) > 6:
        return fallback_type
    if family == "fashion_apparel" and fallback_type and len(words) > 8:
        return fallback_type
    max_words = {
        "electronics": 8,
        "wellness": 7,
        "baby_care": 6,
        "fashion_apparel": 7,
    }.get(family, 8)
    if len(words) > max_words:
        alias = " ".join(words[:max_words]).strip(" ,.-")
    alias_words = alias.split()
    while alias_words and alias_words[-1].lower() in {"&", "dan", "with", "for", "or", "atau", "dengan"}:
        alias_words.pop()
    alias = " ".join(alias_words).strip(" ,.-")
    return alias or full


def _product_category(product: dict[str, Any]) -> str:
    return _clean(
        product.get("category")
        or product.get("product_category")
        or product.get("subcategory")
        or product.get("type")
    )


def _humanize_label(value: str) -> str:
    return _clean(value).replace("_", " ")


def _product_family_haystack(product: dict[str, Any], copy: dict | None = None) -> str:
    return " ".join(
        [
            _clean(product.get("category")),
            _clean(product.get("product_category")),
            _clean(product.get("group")),
            _clean(product.get("sub_group")),
            _clean(product.get("type")),
            _product_name(product),
            _clean((copy or {}).get("angle")),
        ]
    ).lower()


def _normalize_explicit_family(product: dict[str, Any]) -> str:
    raw = _clean(
        product.get("bosmax_product_family")
        or product.get("product_family")
        or product.get("family")
    ).lower()
    if not raw:
        return ""
    normalized = raw.replace("-", "_").replace(" ", "_")
    haystack = _product_family_haystack(product)
    fashion_terms = (
        "fashion", "womenswear", "menswear", "muslim fashion", "hijab", "tudung", "shawl", "bawal",
        "telekung", "seluar", "trousers", "pants", "skirt", "dress", "jersey", "shirt", "blouse", "apparel",
    )
    electronics_terms = (
        "phone", "mobile", "iphone", "android", "usb", "charger", "cable", "mount", "holder", "magsafe", "tripod", "adapter",
    )
    if "female_health_sensitive" in normalized and _contains_any_term(haystack, fashion_terms):
        return "fashion_apparel"
    if "household_storage_organizer" in normalized and _contains_any_term(haystack, fashion_terms):
        return "fashion_apparel"
    if any(token in normalized for token in ("accessory_small_item", "auto_tool_general")) and _contains_any_term(haystack, electronics_terms):
        return "electronics"
    if any(token in normalized for token in ("baby", "wipes", "newborn", "diaper")):
        return "baby_care"
    if any(token in normalized for token in ("fragrance", "perfume", "body_mist", "body_spray", "aroma")):
        return "fragrance"
    if any(token in normalized for token in ("beauty_personal_care", "beauty", "skincare", "cosmetic", "personal_care")):
        return "beauty_personal_care"
    if any(token in normalized for token in ("laundry", "detergent", "softener", "refill")):
        return "laundry_care"
    if any(token in normalized for token in ("household", "cleaner", "kitchen", "organizer", "storage")):
        return "household_care"
    if any(token in normalized for token in ("electronics", "wearable", "device", "gadget")):
        return "electronics"
    if any(token in normalized for token in ("food", "beverage", "drink", "snack")):
        return "food_beverage"
    if any(token in normalized for token in ("fashion", "apparel", "garment")):
        return "fashion_apparel"
    if any(token in normalized for token in ("wellness", "health", "supplement", "vitamin", "male_health")):
        return "wellness"
    return ""


def _infer_product_family(product: dict[str, Any], copy: dict | None = None) -> str:
    haystack = _product_family_haystack(product, copy)
    
    # 1. Medicated / traditional oils override -> must map to wellness
    if any(token in haystack for token in ("minyak", "herbal oil", "medicated oil", "traditional oil", "minyak angin", "minyak urut", "medicated")):
        return "wellness"
        
    # 2. Milk / Milk powder override -> must map to food_beverage (unless skincare milk bath etc.)
    if ("milk" in haystack or "susu" in haystack) and not any(
        token in haystack for token in ("lotion", "cream", "wash", "soap", "bath", "shampoo", "cleanser", "moisturizer", "oil")
    ):
        return "food_beverage"

    explicit = _normalize_explicit_family(product)
    if explicit:
        return explicit
    if any(token in haystack for token in ("baby", "diaper", "wipes", "newborn", "parent")):
        return "baby_care"
    if any(token in haystack for token in ("supplement", "wellness", "vitamin", "health")):
        return "wellness"
    if any(token in haystack for token in ("perfume", "fragrance", "body mist", "body spray", "aroma")):
        return "fragrance"
    if any(token in haystack for token in ("beauty", "skincare", "serum", "cosmetic", "body care", "personal care")):
        return "beauty_personal_care"
    if any(token in haystack for token in ("detergent", "laundry", "softener", "refill")):
        return "laundry_care"
    if any(token in haystack for token in ("cleaner", "household", "kitchen", "storage", "organizer")):
        return "household_care"
    if any(token in haystack for token in ("food", "snack", "drink", "coffee", "tea", "sauce", "cookie")):
        return "food_beverage"
    if any(token in haystack for token in ("shirt", "baju", "telekung", "pajamas", "fashion", "wear", "garment", "apparel", "hijab", "tudung", "shawl", "bawal", "seluar", "trousers", "pants", "dress", "skirt", "jersey")):
        return "fashion_apparel"
    if any(token in haystack for token in ("watch", "device", "gadget", "earbud", "electronics", "screen", "phone", "mobile", "usb", "charger", "cable", "mount", "holder", "magsafe", "adapter")):
        return "electronics"
    return "general"



def _family_focus_terms(family: str) -> dict[str, str]:
    table = {
        "fragrance": {
            "context": "scent-led confidence and first-impression freshness",
            "detail": "nozzle, bottle finish, and premium scent ritual cues",
            "closing": "a soft but memorable scent-confidence payoff",
        },
        "beauty_personal_care": {
            "context": "routine-upgrade beauty handling and polished self-care",
            "detail": "texture-adjacent handling, packaging finish, and neat routine context",
            "closing": "a polished beauty-routine payoff",
        },
        "laundry_care": {
            "context": "practical routine utility and clean-results framing",
            "detail": "pour-ready grip, cap detail, and label-forward function clarity",
            "closing": "a useful routine CTA with practical confidence",
        },
        "household_care": {
            "context": "practical home utility and easy-use clarity",
            "detail": "functional surfaces, grip logic, and believable household context",
            "closing": "a clean utility payoff",
        },
        "baby_care": {
            "context": "gentle parent-trust reassurance and everyday ease",
            "detail": "soft handling, parent-safe trust cues, and calm domestic context",
            "closing": "a trust-led parenting payoff",
        },
        "food_beverage": {
            "context": "appetite, convenience, and everyday craving pull",
            "detail": "sealed-pack truth, serving temptation, and appetite-led framing",
            "closing": "a crave-and-try payoff",
        },
        "fashion_apparel": {
            "context": "fit, drape, texture, and wearable confidence",
            "detail": "fabric fall, seam detail, and styling movement",
            "closing": "a wear-it confidence payoff",
        },
        "electronics": {
            "context": "feature clarity and daily-use usefulness",
            "detail": "screen, controls, ports, or tactile feature reveal",
            "closing": "a feature-led close with credible utility",
        },
        "wellness": {
            "context": "careful routine support and trust-led presentation",
            "detail": "clean bottle truth, measured handling, and non-claim routine context",
            "closing": "a careful trust-led routine payoff",
        },
        "general": {
            "context": "credible product-first commercial framing",
            "detail": "honest product truth, readable packaging, and native social pacing",
            "closing": "a clear product-first payoff",
        },
    }
    return table[family]


def _family_clause_bank(family: str) -> dict[str, Any]:
    table: dict[str, dict[str, Any]] = {
        "fragrance": {
            "dialogue_opening": {
                "Malay": "Bau dia terus bagi rasa lebih yakin.",
                "English": "The scent reads confident immediately.",
            },
            "dialogue_middle": {
                "Malay": "Botol dia pun nampak kemas dan mahal bila pegang.",
                "English": "The bottle reads neat and premium in hand.",
            },
            "dialogue_cta": {
                "Malay": "Memang jenis bau yang orang perasan bila lalu.",
                "English": "It lands like the kind of scent people remember.",
            },
            "visual_proof": "make the bottle, nozzle, and reflective finish read expensive before any spoken benefit lands",
            "end_payoff": "a clean shot of the bottle showing the nozzle detail clearly centered with elegant perfume aesthetic",
        },
        "beauty_personal_care": {
            "dialogue_opening": {
                "Malay": "Terus rasa pagi tu lebih tersusun.",
                "English": "It makes the routine feel cleaner immediately.",
            },
            "dialogue_middle": {
                "Malay": "Packaging dia memang nampak senang capai masa siap-siap.",
                "English": "The packaging reads easy to slot into a daily routine.",
            },
            "dialogue_cta": {
                "Malay": "Jenis benda yang memang tinggal dekat sinki sebab senang capai.",
                "English": "It feels like the kind of product people will repeat naturally.",
            },
            "visual_proof": "make the packaging and handling feel routine-ready, polished, and easy to repeat",
            "end_payoff": "a neat sink-side placement showing the brand name clearly with clean skincare context",
        },
        "laundry_care": {
            "dialogue_opening": {
                "Malay": "Saiz refill dia terus nampak berbaloi.",
                "English": "The refill size reads worth it immediately.",
            },
            "dialogue_middle": {
                "Malay": "Terus boleh bayang rutin baju bersih dan wangi.",
                "English": "It instantly maps to a clean, fresh laundry routine.",
            },
            "dialogue_cta": {
                "Malay": "Memang jenis stok rumah yang senang nak ulang beli.",
                "English": "It feels like practical home stock that gets repurchased easily.",
            },
            "visual_proof": "make refill scale, cap logic, and pakaian-wangi utility read clearly before any claim wording tries to help",
            "end_payoff": "a clear pack shot of the refill showing the cap and wash benefits clearly with utility laundry context",
        },
        "household_care": {
            "dialogue_opening": {
                "Malay": "Sekali tengok terus nampak practical untuk rumah.",
                "English": "It looks practical at first glance.",
            },
            "dialogue_middle": {
                "Malay": "Grip, nozzle, dan cara guna dia terus masuk akal.",
                "English": "The way it is held and used reads logical immediately.",
            },
            "dialogue_cta": {
                "Malay": "Memang senang nampak guna dia hari-hari.",
                "English": "The home-use value reads clearly by the end.",
            },
            "visual_proof": "make grip logic, opening direction, and home-use practicality obvious in-frame",
            "end_payoff": "a clean household shot showing the spray or storage container centered and organized in the domestic space",
        },
        "baby_care": {
            "dialogue_opening": {
                "Malay": "Sekali tengok terus rasa tenang nak guna.",
                "English": "It reads gentle and reassuring at first glance.",
            },
            "dialogue_middle": {
                "Malay": "Pump dia senang, pegang pun tak kalut masa nak pakai.",
                "English": "The pack reads easy to trust for a baby-care routine.",
            },
            "dialogue_cta": {
                "Malay": "Parent memang suka simpan benda ni dekat-dekat.",
                "English": "It feels like the kind of item parents keep on standby.",
            },
            "visual_proof": "make softness, pack integrity, and calm parent-trust handling read before any spoken reassurance",
            "end_payoff": "a clean pack shot showing the brand label clearly with gentle parenting nursery context",
        },
        "food_beverage": {
            "dialogue_opening": {
                "Malay": "Packaging dia terus buat rasa nak cuba.",
                "English": "The packaging makes it feel try-worthy instantly.",
            },
            "dialogue_middle": {
                "Malay": "Terus nampak sedap dan senang bayang cara makan dia.",
                "English": "It reads tasty fast and makes the serving moment easy to imagine.",
            },
            "dialogue_cta": {
                "Malay": "Jenis produk yang buat orang simpan dalam kepala lepas tengok.",
                "English": "It feels like the kind of product people keep craving after seeing it.",
            },
            "visual_proof": "make appetite, serving temptation, and sealed-pack truth work together instead of relying on copy alone",
            "end_payoff": "a tempting serving presentation showing the texture and fresh food details clearly",
        },
        "fashion_apparel": {
            "dialogue_opening": {
                "Malay": "Jatuh dia terus nampak kemas.",
                "English": "The drape reads neat immediately.",
            },
            "dialogue_middle": {
                "Malay": "Bila gerak sikit, fit dia terus nampak jadi.",
                "English": "A small movement makes the fit read correctly right away.",
            },
            "dialogue_cta": {
                "Malay": "Pakai sekali terus nampak jadi.",
                "English": "It lands like the kind of piece that makes the wearer feel put together.",
            },
            "visual_proof": "make fit, drape, and seam finish prove themselves through movement and silhouette",
            "end_payoff": "a clear visual detail of the fabric fall and drape with styling movement in clean light",
        },
        "electronics": {
            "dialogue_opening": {
                "Malay": "Sekali tengok terus nampak function dia.",
                "English": "The function reads clearly at first glance.",
            },
            "dialogue_middle": {
                "Malay": "Screen dan detail dia terus buat orang faham point dia.",
                "English": "The screen and details make the use-case read instantly.",
            },
            "dialogue_cta": {
                "Malay": "Memang senang nampak kenapa benda ni berguna.",
                "English": "It becomes obvious why the device is useful.",
            },
            "visual_proof": "make screen, controls, and profile shape create a feature-proof read instead of a generic gadget beauty shot",
            "end_payoff": "a close-up detail of the device screen or ports showing utility features clearly",
        },
        "wellness": {
            "dialogue_opening": {
                "Malay": "Nampak kemas, terus rasa boleh percaya.",
                "English": "It looks easy to trust in a routine.",
            },
            "dialogue_middle": {
                "Malay": "Botol dia tersusun, memang tak rasa hype.",
                "English": "The packaging reads careful and non-hype immediately.",
            },
            "dialogue_cta": {
                "Malay": "Memang jenis benda yang senang kekal dalam routine.",
                "English": "It feels like something people can keep in a routine comfortably.",
            },
            "visual_proof": "make the bottle, dosage logic, and routine fit feel careful and measured rather than loud",
            "end_payoff": "a clean bottle shot showing dosage instructions clearly with measured wellness context",
        },
        "general": {
            "dialogue_opening": {
                "Malay": "Sekali tengok terus nampak kemas.",
                "English": "It reads clean at first glance.",
            },
            "dialogue_middle": {
                "Malay": "Cara pegang dan guna dia terus nampak masuk akal.",
                "English": "The handling makes the value feel believable immediately.",
            },
            "dialogue_cta": {
                "Malay": "Memang senang faham kenapa orang nak cuba.",
                "English": "It becomes easy to see why someone would try it.",
            },
            "visual_proof": "make product truth and usage context do the convincing work first",
            "end_payoff": "a clean product shot centered, label readable, with balanced native-commercial context",
        },
    }
    return table.get(family, table["general"])


def _family_dialogue_clause(family: str, stage: str, target_language: str) -> str:
    family_bank = _family_clause_bank(family)
    lang = language_name(target_language)
    key = f"dialogue_{stage}"
    phrase_bank = family_bank.get(key) or family_bank["dialogue_middle"]
    return _clean(phrase_bank.get(lang) or phrase_bank.get("Malay") or "")


def _family_voice_clause(family: str, target_language: str) -> str:
    lang = language_name(target_language)
    bank = {
        "laundry_care": {
            "Malay": "Bunyi macam tengah urus basuh baju betul-betul dan nampak apa yang memudahkan, bukan macam demo refill yang terlalu tersusun.",
            "English": "Sound like someone genuinely handling laundry and noticing what makes it easier, not like an overly staged refill demo.",
        },
        "fashion_apparel": {
            "Malay": "Bunyi macam tengah siap keluar dan baru perasan potongan dia memang jadi, bukan macam fashion shoot yang terlalu sedar kamera.",
            "English": "Sound like someone genuinely getting ready to head out and noticing the fit works, not like a camera-aware fashion shoot.",
        },
        "electronics": {
            "Malay": "Bunyi macam tunjuk benda yang memang membantu dalam rutin harian, bukan macam baca spec sheet depan kamera.",
            "English": "Sound like showing something that genuinely helps in daily life, not like reading a spec sheet to camera.",
        },
        "household_care": {
            "Malay": "Bunyi macam tengah buat kerja rumah betul-betul dan terjumpa benda yang memudahkan, bukan macam product showcase yang dibuat-buat.",
            "English": "Sound like someone genuinely doing housework and noticing what makes it easier, not like a staged product showcase.",
        },
        "beauty_personal_care": {
            "Malay": "Bunyi macam tengah siap-siap betul sebelum keluar, bukan macam pitch studio yang terlalu sedar kamera.",
            "English": "Sound like someone genuinely getting ready before heading out, not like a camera-aware studio pitch.",
        },
        "fragrance": {
            "Malay": "Bunyi macam kongsi bau yang orang memang akan perasan dekat dunia sebenar, bukan macam baca tagline mewah.",
            "English": "Sound like sharing a scent people would genuinely notice in real life, not like reciting a luxury tagline.",
        },
        "baby_care": {
            "Malay": "Bunyi macam parent kongsi benda yang betul-betul mudahkan routine, bukan macam tengah hard sell.",
            "English": "Sound like a parent sharing something that genuinely calms the routine, not like a hard sell.",
        },
        "wellness": {
            "Malay": "Bunyi grounded dan tak hype, macam cadang benda yang memang kita keep dalam routine sendiri.",
            "English": "Sound grounded and non-hype, like recommending something that genuinely stays in a personal routine.",
        },
    }
    phrase_bank = bank.get(family)
    if not phrase_bank:
        return ""
    return _clean(phrase_bank.get(lang) or phrase_bank.get("Malay") or "")


def _family_t2v_scene_clause(family: str) -> dict[str, str]:
    bank = {
        "laundry_care": {
            "continuity": "Let the product appear inside a believable laundry beat such as sorting clothes, reaching for detergent before a wash cycle, checking the refill near the machine, or resetting laundry supplies, never as a posed refill showcase.",
            "opening": "Start with the presenter already mid-laundry task so the product enters as part of a real wash routine, not as a staged reveal.",
            "middle": "Use one practical laundry habit such as lifting a basket, checking the load, or reaching toward the machine so the refill value feels discovered in context.",
            "closing": "Resolve like the refill naturally stays in the laundry corner ready for the next cycle, not like a showroom-perfect household end frame.",
        },
        "fashion_apparel": {
            "continuity": "Let the product appear inside a believable getting-dressed beat such as adjusting sleeves, checking the mirror, smoothing the fabric, or grabbing a bag before leaving, never as a posed fashion-editorial reveal.",
            "opening": "Start with the presenter already mid-adjustment so the outfit feels worn for a real reason before it becomes the spoken subject.",
            "middle": "Use one dressing habit such as turning slightly at the mirror, fixing the cuff, or taking a step toward the door so the fit and drape prove themselves through movement.",
            "closing": "Resolve like the outfit is already chosen and the presenter is about to walk out feeling put together, not like a frozen runway ending.",
        },
        "electronics": {
            "continuity": "Let the product appear inside a believable everyday-use beat such as checking time at the door, glancing at a notification while walking, adjusting a strap before leaving, or reacting to a quick alert, never as a scripted gadget demo.",
            "opening": "Start with the presenter already mid-task and using the device for a real reason before the product becomes the spoken focus.",
            "middle": "Use one natural device habit such as waking the screen, dismissing a notification, or checking the time while moving so the feature proof feels discovered in use.",
            "closing": "Resolve like the device quietly proves itself useful and stays on the body for the next task, not like a frozen tech-spec ending.",
        },
        "household_care": {
            "continuity": "Let the product appear inside a believable housework beat such as wiping a spill, resetting a counter before guests arrive, or grabbing the bottle during a quick cleanup, never as a posed cleaning showcase.",
            "opening": "Start with the presenter already mid-cleanup so the product enters as part of solving a small real mess, not as a staged reveal.",
            "middle": "Use one practical cleanup habit such as reaching around clutter, spraying a real surface, or shifting an item aside so the utility reads from action rather than explanation.",
            "closing": "Resolve like the area is quickly sorted and the bottle goes back within easy reach for the next cleanup, not like a showroom-perfect product tableau.",
        },
        "beauty_personal_care": {
            "continuity": "Let the product appear inside a believable getting-ready beat such as rushed sink-side prep, mirror check, makeup-before-leaving flow, or a midday touch-up, never as a creator-studio demo.",
            "opening": "Start with the presenter already fixing hair, checking skin, or reaching across the counter so the routine feels underway before the product becomes the subject.",
            "middle": "Use one real prep habit such as checking shine in the mirror, setting the product beside makeup, or applying while multitasking so the value feels embedded in the routine.",
            "closing": "Resolve like the product naturally stays within reach for the next rushed morning or touch-up, not like a staged beauty reveal for the camera.",
        },
        "fragrance": {
            "continuity": "Let the product appear inside a believable social-ready beat such as stepping out the door, grabbing keys, a last mirror glance, or a quick bag check, never as a slow luxury tabletop reveal.",
            "opening": "Start with the presenter already halfway out the door or mid-prep so the scent enters as part of the real moment, not as a posed introduction.",
            "middle": "Use one social cue such as a last wrist spray, a collar adjustment, or a second glance before leaving so the confidence payoff feels lived rather than narrated.",
            "closing": "Resolve like the scent is what lingers as the presenter heads out and would be noticed by people nearby, not like a frozen prestige-beauty end card.",
        },
        "baby_care": {
            "continuity": "Let the product appear inside a believable parent-care beat such as after-bath lotion prep, diaper-bag packing, or a calm wind-down routine, never as a studio demo.",
            "opening": "Start with the presenter already mid-routine, settling a real caregiving moment before the product becomes the focus.",
            "middle": "Use one gentle caregiving action or parent-check habit so the benefit feels observed inside the routine, not announced from outside it.",
            "closing": "Resolve like a parent deciding this stays within easy reach for the next routine, not like a public-facing sales performance.",
        },
        "wellness": {
            "continuity": "Let the product appear inside a measured self-maintenance beat such as morning water prep, a kitchen-counter check, or a quiet routine reset, never as a dramatic wellness reveal.",
            "opening": "Start with the presenter already moving through a real routine moment before the product becomes the spoken subject.",
            "middle": "Use one measured habit cue such as reaching for water, glancing at the label, or setting the bottle back with intention so the value feels routine-native.",
            "closing": "Resolve like someone quietly deciding this stays in the routine, not like a loud health-claim finale.",
        },
    }
    return bank.get(family, {"continuity": "", "opening": "", "middle": "", "closing": ""})


def _contains_term(text: str, term: str) -> bool:
    normalized = _clean(text).lower()
    if not normalized:
        return False
    escaped = re.escape(term.lower())
    escaped = escaped.replace(r"\ ", r"[\s_-]+")
    pattern = rf"\b{escaped}\b"
    return re.search(pattern, normalized) is not None


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def _infer_trigger_id(
    product: dict[str, Any], copy: dict[str, Any], *, family: str, angle: str,
) -> str:
    explicit = _clean(
        copy.get("trigger_id")
        or product.get("trigger_id")
        or product.get("suggested_trigger_id")
        or ((product.get("product_intelligence") or {}).get("trigger_id") if isinstance(product.get("product_intelligence"), dict) else "")
    ).upper()
    if explicit:
        return explicit
    haystack = " ".join(
        [
            angle,
            _clean(copy.get("copywriting_angle")),
            _clean(product.get("copywriting_angle")),
            _product_name(product),
            _product_category(product),
        ]
    ).lower()
    if _contains_any_term(haystack, ("gift", "gifting", "festive", "raya", "present")):
        return "GIFTING_01"
    if _contains_any_term(haystack, ("authority", "feature", "tech", "screen", "wearable")):
        return "AUTHORITY_01"
    if _contains_any_term(haystack, ("comfort", "soft", "cozy", "selesa", "home")):
        return "COMFORT_01"
    if _contains_any_term(haystack, ("ego", "masculine", "alpha", "presence", "padu")):
        return "EGO_01"
    if _contains_any_term(haystack, ("female", "feminine", "wanita", "muslimah", "girly")):
        return "FEMALE_01"
    if _contains_any_term(haystack, ("confidence", "style", "fit", "premium", "scent", "beauty", "fashion")):
        return "CONFIDENCE_01"
    if _contains_any_term(haystack, ("trust", "gentle", "baby", "routine support", "safe")):
        return "TRUST_01"
    return {
        "fragrance": "CONFIDENCE_01",
        "beauty_personal_care": "CONFIDENCE_01",
        "fashion_apparel": "CONFIDENCE_01",
        "electronics": "AUTHORITY_01",
        "food_beverage": "COMFORT_01",
        "wellness": "TRUST_01",
        "baby_care": "TRUST_01",
        "laundry_care": "TRUST_01",
        "household_care": "TRUST_01",
        "general": "TRUST_01",
    }.get(family, "TRUST_01")


def _infer_cta_type(copy: dict[str, Any], cta_text: str) -> str:
    allowed = {
        "direct_checkout",
        "standby_now",
        "add_to_kit",
        "save_for_later",
        "comment_signal",
        "private_action",
    }
    explicit = _clean(copy.get("cta_type")).lower()
    if explicit in allowed:
        return explicit
    cta = cta_text.lower()
    if any(token in cta for token in ("dm", "pm", "inbox", "ws", "whatsapp")):
        return "private_action"
    if any(token in cta for token in ("comment", "komen", "reply", "drop", "nak link")):
        return "comment_signal"
    if any(token in cta for token in ("save", "simpan", "bookmark")):
        return "save_for_later"
    if any(token in cta for token in ("kit", "routine", "stash", "cart", "troli")):
        return "add_to_kit"
    if any(token in cta for token in ("checkout", "check out", "grab", "beg kuning", "buy now", "order now")):
        return "direct_checkout"
    if any(token in cta for token in ("jangan tunggu", "before habis", "promo habis", "sekarang", "today only", "stok")):
        return "standby_now"
    return "direct_checkout" if cta_text else ""


def _guard_trigger_for_family(trigger_id: str, *, family: str) -> str:
    guarded = {
        "baby_care": {"TRUST_01", "COMFORT_01"},
        "wellness": {"TRUST_01", "COMFORT_01", "AUTHORITY_01"},
    }
    if trigger_id and family in guarded and trigger_id not in guarded[family]:
        return "TRUST_01"
    return trigger_id


def _infer_angle_signal(copy: dict[str, Any], family: str) -> str:
    haystack = " ".join(
        [
            _clean(copy.get("angle")),
            _clean(copy.get("copywriting_angle")),
            _clean(copy.get("hook")),
            _clean(copy.get("subhook")),
            " ".join(_clean(usp) for usp in (copy.get("usps") or [])),
            _clean(copy.get("cta")),
        ]
    ).lower()
    if _contains_any_term(haystack, ("gift", "gifting", "festive", "present")):
        return "gifting"
    if _contains_any_term(haystack, ("authority", "feature", "tech", "screen", "precision")):
        return "authority"
    if _contains_any_term(haystack, ("comfort", "soft", "selesa", "cozy", "home")):
        return "comfort"
    if _contains_any_term(haystack, ("trust", "gentle", "parent", "baby", "reassur")):
        return "trust"
    if _contains_any_term(haystack, ("confidence", "style", "fit", "premium", "scent", "freshness", "beauty")):
        return "confidence"
    if _contains_any_term(haystack, ("routine", "daily", "harian", "self-care", "self care")):
        return "routine"
    if _contains_any_term(haystack, ("utility", "practical", "clean", "refill", "organize")):
        return "utility"
    if family == "food_beverage" and _contains_any_term(
        haystack, ("taste", "appetite", "sedap", "pedas", "snack", "drink", "craving", "bancuh", "makan", "minum")
    ):
        return "taste"
    if _contains_any_term(haystack, ("taste", "appetite", "snack", "drink", "craving", "bancuh", "makan", "minum")):
        return "taste"
    if _contains_any_term(haystack, ("ego", "presence", "masculine", "alpha", "padu")):
        return "ego"
    if _contains_any_term(haystack, ("female", "feminine", "wanita", "muslimah", "lady")):
        return "female"
    return {
        "fragrance": "confidence",
        "beauty_personal_care": "routine",
        "laundry_care": "utility",
        "household_care": "utility",
        "baby_care": "trust",
        "food_beverage": "taste",
        "fashion_apparel": "confidence",
        "electronics": "authority",
        "wellness": "trust",
        "general": "trust",
    }.get(family, "trust")


def _strategic_opening_clause(trigger_id: str, target_language: str) -> str:
    bm = {
        "TRUST_01": "Sekali tengok terus rasa boleh percaya.",
        "CONFIDENCE_01": "Terus naik rasa yakin.",
        "AUTHORITY_01": "Terus nampak point dia.",
        "COMFORT_01": "Terus rasa senang nak guna.",
        "EGO_01": "Aura dia terus naik.",
        "GIFTING_01": "Memang nampak presentable.",
        "FEMALE_01": "Terus nampak manis.",
    }
    en = {
        "TRUST_01": "This feels easy to trust.",
        "CONFIDENCE_01": "It lifts the confidence fast.",
        "AUTHORITY_01": "The value shows immediately.",
        "COMFORT_01": "Most importantly, it feels comfortable.",
        "EGO_01": "It gives a stronger presence.",
        "GIFTING_01": "It looks gift-ready instantly.",
        "FEMALE_01": "It reads soft and feminine.",
    }
    bank = bm if language_name(target_language) == "Malay" else en
    return bank.get(trigger_id, bank["TRUST_01"])


def _hook_needs_strategic_opening(copy: dict[str, Any], family: str) -> bool:
    hooks = _split_clauses(copy.get("hook"))
    if not hooks:
        return True
    hook_text = " ".join(hooks).lower()
    if len(hook_text.split()) <= 5:
        return True
    weak_markers = (
        "baru try", "mula-mula", "nampak biasa", "okay je", "cuba tengok",
        "tak serabut", "aku suka", "pada aku", "senang nak faham",
    )
    if any(marker in hook_text for marker in weak_markers):
        return True
    strong_terms = {
        "fragrance": ("bau", "wangi", "spray", "perasan"),
        "beauty_personal_care": ("sinki", "routine", "pagi", "kemas", "sapuan"),
        "baby_care": ("bayi", "parent", "wipes", "lampin", "tenang", "lembut", "diaper", "pants", "susu", "milk", "powder", "infant", "toddler", "anak"),
        "electronics": ("function", "spec", "screen", "charger", "port", "cable", "battery"),
        "fashion_apparel": ("fit", "jatuh", "pakai", "jadi", "drape", "kain"),
        "wellness": ("routine", "percaya", "botol", "hype", "supplement", "minyak", "angin", "urut", "herba", "lenguh", "sakit", "kejang", "perut", "standby", "anak", "selesa", "leher", "dapur", "pinggang", "sendi", "bisa", "kebas", "sejuk", "kembung"),
        "laundry_care": ("refill", "detergent", "baju", "stok rumah", "basuh"),
        "household_care": ("praktical", "lipat", "susun", "ruang", "storage", "kotak"),
        "food_beverage": ("lapar", "pedas", "sedap", "sambal", "rangup", "makan", "minum", "susu", "milk", "powder", "kopi", "coffee", "teh", "tea", "cuba"),
    }
    if any(term in hook_text for term in strong_terms.get(family, ())):
        return False
    return len(hook_text.split()) <= 8


def _strategic_middle_clause(angle_signal: str, target_language: str) -> str:
    bm = {
        "routine": "Memang senang masuk routine harian.",
        "confidence": "Terus nampak lebih kemas dan yakin.",
        "trust": "Nampak kemas dan senang percaya.",
        "utility": "Terus nampak practical untuk guna hari-hari.",
        "comfort": "Rasa lebih selesa dan tak serabut.",
        "taste": "Terus nampak sedap dan senang nak cuba.",
        "authority": "Detail dia terus nampak jelas dan masuk akal.",
        "gifting": "Nampak presentable kalau nak bagi orang.",
        "ego": "Vibe dia terus rasa lebih padu.",
        "female": "Nampak manis, kemas, dan feminine.",
    }
    en = {
        "routine": "It drops into a daily routine easily.",
        "confidence": "It reads cleaner and more confident instantly.",
        "trust": "It looks grounded and easy to trust.",
        "utility": "It feels practical for everyday use.",
        "comfort": "It feels easier and more comfortable to keep using.",
        "taste": "It looks tempting and easy to try.",
        "authority": "The details read clearly and credibly.",
        "gifting": "It already looks presentable enough to gift.",
        "ego": "The vibe feels sharper without trying too hard.",
        "female": "It reads neat, soft, and feminine.",
    }
    bank = bm if language_name(target_language) == "Malay" else en
    return bank.get(angle_signal, bank["trust"])


def _cta_has_native_signal(cta_text: str, cta_type: str) -> bool:
    cta = cta_text.lower()
    checks = {
        "direct_checkout": ("checkout", "grab", "beg kuning", "buy", "order", "try", "cuba"),
        "standby_now": ("jangan tunggu", "promo", "stok", "today", "sekarang"),
        "add_to_kit": ("cart", "troli", "kit", "routine", "stash"),
        "save_for_later": ("save", "simpan", "bookmark"),
        "comment_signal": ("comment", "komen", "reply", "drop"),
        "private_action": ("dm", "pm", "inbox", "whatsapp", "ws"),
    }
    return any(token in cta for token in checks.get(cta_type, ()))


def _strategic_cta_bridge(cta_type: str, cta_text: str, target_language: str) -> str:
    if not cta_type or _cta_has_native_signal(cta_text, cta_type):
        return ""
    bm = {
        "direct_checkout": "Kalau dah suka, terus grab.",
        "standby_now": "Kalau tengah fikir, jangan tunggu.",
        "add_to_kit": "Memang senang masuk routine.",
        "save_for_later": "Kalau belum grab, simpan dulu.",
        "comment_signal": "Kalau nak detail, komen je.",
        "private_action": "Kalau nak link, DM terus.",
    }
    en = {
        "direct_checkout": "If you already like it, just check out.",
        "standby_now": "If you are still thinking, do not wait.",
        "add_to_kit": "This slips into the routine easily.",
        "save_for_later": "If you are not grabbing it yet, save it first.",
        "comment_signal": "If you want the details, just comment.",
        "private_action": "If you want the link, DM directly.",
    }
    bank = bm if language_name(target_language) == "Malay" else en
    return bank.get(cta_type, "")


def _merge_unique_clauses(*clause_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in clause_groups:
        for clause in group:
            cleaned = _clean(clause)
            if not cleaned:
                continue
            if cleaned[-1] not in ".!?":
                cleaned = f"{cleaned}."
            key = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
            if key and key not in seen:
                if any(_clauses_are_too_similar(cleaned, existing) for existing in merged):
                    continue
                seen.add(key)
                merged.append(cleaned)
    return merged


def _clauses_are_too_similar(left: str, right: str) -> bool:
    left_prefix = re.findall(r"[a-z0-9]+", left.lower())[:4]
    right_prefix = re.findall(r"[a-z0-9]+", right.lower())[:4]
    if len(left_prefix) >= 4 and len(right_prefix) >= 4 and left_prefix == right_prefix:
        return True
    stopwords = {
        "aku", "dia", "ni", "itu", "ini", "yang", "dan", "atau", "pun", "je",
        "terus", "memang", "kalau", "dah", "lagi", "lebih", "untuk", "dengan",
        "buat", "rasa", "nampak", "jenis", "produk", "benda", "orang", "suka",
        "the", "and", "with", "that", "this", "just", "really", "very",
    }
    left_tokens = {
        token for token in re.findall(r"[a-z0-9]+", left.lower())
        if len(token) > 2 and token not in stopwords
    }
    right_tokens = {
        token for token in re.findall(r"[a-z0-9]+", right.lower())
        if len(token) > 2 and token not in stopwords
    }
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    if len(overlap) < 2:
        return False
    smaller = min(len(left_tokens), len(right_tokens))
    return (len(overlap) / smaller) >= 0.6


def _visual_story_terms(family: str, angle_signal: str, trigger_id: str, cta_type: str) -> dict[str, str]:
    family_bank = _family_clause_bank(family)
    opening_bank = {
        "TRUST_01": "reassuring, easy-to-believe commercial energy",
        "CONFIDENCE_01": "self-assured desirability and social-confidence energy",
        "AUTHORITY_01": "proof-led credibility and feature-first energy",
        "COMFORT_01": "ease-first, pressure-free commercial energy",
        "EGO_01": "status-aware, high-presence commercial energy",
        "GIFTING_01": "gift-worthy presentation and occasion-readiness energy",
        "FEMALE_01": "soft feminine polish with neat desirability energy",
    }
    middle_bank = {
        "routine": "show the product sliding naturally into a repeatable everyday routine",
        "confidence": "show why the product makes the presenter look or feel more put-together",
        "trust": "show believable handling that makes the benefit easy to trust",
        "utility": "show why the format, grip, or packaging logic makes practical sense immediately",
        "comfort": "show how the product reduces friction and feels easy to keep using",
        "taste": "show appetite or temptation through believable serving or craving cues",
        "authority": "show one concrete proof cue so the value reads clearly on camera",
        "gifting": "show why the presentation already feels neat enough to give to someone",
        "ego": "show a presence-upgrade beat without turning theatrical or fake",
        "female": "show neat feminine polish through details, poise, and finish",
    }
    closing_bank = {
        "direct_checkout": "a decision-ready end hold that feels checkout-primed without shouting",
        "standby_now": "a light-urgency end hold that feels timely, not desperate",
        "add_to_kit": "a routine-slotting end hold that makes the product feel easy to keep around",
        "save_for_later": "a bookmark-worthy end hold that stays memorable even if the buyer does not act yet",
        "comment_signal": "a response-inviting end hold that naturally opens a comment or reply impulse",
        "private_action": "a quiet insider end hold that feels DM-worthy rather than loud",
    }
    fallback_middle = {
        "fragrance": "show scent-confidence through elegant handling and believable first-impression cues",
        "beauty_personal_care": "show how the product upgrades a neat self-care routine",
        "laundry_care": "show routine utility through believable household use logic",
        "household_care": "show practical use-value through clean domestic context",
        "baby_care": "show calm trust cues that feel parent-safe and believable",
        "food_beverage": "show appetite pull and everyday try-now temptation",
        "fashion_apparel": "show fit, drape, or styling payoff through natural movement",
        "electronics": "show one clear feature-led proof moment with credible handling",
        "wellness": "show careful routine support without overclaiming performance",
        "general": "show the product's value through believable usage context",
    }
    return {
        "opening": opening_bank.get(trigger_id, "credible, native-commercial energy"),
        "middle": (
            f"{middle_bank.get(angle_signal, fallback_middle.get(family, fallback_middle['general']))}; "
            f"{family_bank['visual_proof']}"
        ),
        "closing": (
            f"{closing_bank.get(cta_type, 'a clean memorable end hold with clear commercial intent')}, carrying "
            f"{family_bank['end_payoff']}"
        ),
    }


def _sentence_case(text: str) -> str:
    cleaned = _clean(text)
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def _family_end_frame_hold_phrase(family: str, visual_name: str) -> str:
    table = {
        "fragrance": f"End on a confident last-look hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "beauty_personal_care": f"End on a routine-ready counter hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "baby_care": f"End on a calm standby hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "electronics": f"End on a proof-to-camera hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "fashion_apparel": f"End on a wear-ready hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "wellness": f"End on a measured routine-counter hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "laundry_care": f"End on a stock-up hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "household_care": f"End on a practical home-use hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "food_beverage": f"End on a craving-trigger hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
        "general": f"End on a confident creator-to-camera hold with {visual_name} upright, label readable, and the exact uploaded-product packaging still matching perfectly",
    }
    return table.get(family, table["general"])


def _trim_to_budget(text: str, budget: int) -> str:
    words = _clean(text).split()
    if len(words) <= budget:
        return " ".join(words)
    trimmed = " ".join(words[:budget])
    return re.sub(r"[,;:\-]+$", "", trimmed).strip()


def _split_clauses(text: str) -> list[str]:
    cleaned = _clean(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\s*[;:]\s+|\s+[—-]\s+", cleaned)
    clauses: list[str] = []
    seen: set[str] = set()
    for part in parts:
        clause = _clean(part).strip(" ,;:")
        if not clause:
            continue
        if clause[-1] not in ".!?":
            clause = f"{clause}."
        key = re.sub(r"[^a-z0-9]+", "", clause.lower())
        if key and key not in seen:
            seen.add(key)
            clauses.append(clause)
    return clauses


def _finalize_dialogue_text(text: str) -> str:
    cleaned = _clean(text).strip(" ,;:-")
    terminal_punct = cleaned[-1] if cleaned and cleaned[-1] in ".!?" else "."
    cleaned = cleaned.rstrip(".!?").strip(" ,;:-")
    cleaned = re.sub(
        r"\b(and|or|dan|atau|sebab|because|kalau|if|bila|when|supaya|untuk|rasa|tak|yang|pun|je|memang)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")
    if cleaned and cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}{terminal_punct}"
    return cleaned


def _pack_dialogue_clauses(clauses: list[str], budget: int) -> str:
    if budget <= 0:
        return ""
    chosen: list[str] = []
    used_words = 0
    for clause in clauses:
        words = clause.split()
        if not words:
            continue
        if not chosen and len(words) > budget:
            return _finalize_dialogue_text(_trim_to_budget(clause, budget))
        if used_words + len(words) <= budget:
            chosen.append(clause)
            used_words += len(words)
            continue
        remaining = budget - used_words
        if chosen and remaining >= 9:
            chosen.append(_finalize_dialogue_text(_trim_to_budget(clause, remaining)))
            used_words = budget
            break
    if not chosen and clauses:
        return _finalize_dialogue_text(_trim_to_budget(clauses[0], budget))
    return _finalize_dialogue_text(" ".join(chosen))


def _usp_slice(usps: list[str], block_index: int, total_blocks: int) -> list[str]:
    if not usps:
        return []
    if total_blocks <= 1:
        return usps[:2]
    if block_index == 1:
        return usps[:1]
    if block_index == total_blocks:
        return usps[-1:]
    middle_slots = max(1, total_blocks - 2)
    pointer = min(len(usps) - 1, ((block_index - 2) * len(usps)) // middle_slots)
    return usps[pointer:pointer + 1]


def _formula_dialogue_clauses(
    copy: dict, block_index: int, total_blocks: int, *, target_language: str, family: str,
) -> list[str]:
    formula = copy.get("formula_family") or "HSO"
    hooks = _split_clauses(copy.get("hook"))
    subhooks = _split_clauses(copy.get("subhook"))
    angle = _split_clauses(copy.get("angle"))
    usps = [clause for usp in (copy.get("usps") or []) for clause in _split_clauses(usp)]
    ctas = _split_clauses(copy.get("cta"))
    opening = (
        [_strategic_opening_clause(copy.get("trigger_id", ""), target_language)]
        if _hook_needs_strategic_opening(copy, family)
        else []
    )
    middle = [_strategic_middle_clause(_infer_angle_signal(copy, family), target_language)]
    cta_bridge = [_strategic_cta_bridge(copy.get("cta_type", ""), copy.get("cta", ""), target_language)]
    family_opening = (
        [_family_dialogue_clause(family, "opening", target_language)]
        if _hook_needs_strategic_opening(copy, family)
        else []
    )
    family_middle = [_family_dialogue_clause(family, "middle", target_language)]
    family_cta = [_family_dialogue_clause(family, "cta", target_language)]
    chosen_usps = _usp_slice(usps, block_index, total_blocks)
    native_cta_first = family in {"baby_care", "wellness", "fragrance"}
    if total_blocks <= 1:
        single_block_map = {
            "PAS": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1], chosen_usps[:1], middle, family_middle, cta_bridge, ctas[:1], family_cta),
            "AIDA": _merge_unique_clauses(hooks, opening, family_opening, chosen_usps[:2], middle, family_middle, cta_bridge, ctas[:1], family_cta),
            "HSO": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1], chosen_usps[:1], middle, family_middle, cta_bridge, ctas[:1], family_cta),
            "BAB": _merge_unique_clauses(subhooks[:1], opening, family_opening, chosen_usps[:2], middle, family_middle, cta_bridge, ctas[:1], family_cta),
            "PESTA": _merge_unique_clauses(hooks, opening, family_opening, angle[:1], chosen_usps[:1], middle, family_middle, cta_bridge, ctas[:1], family_cta),
            "PASTOR": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1], angle[:1], middle, family_middle, cta_bridge, ctas[:1], family_cta),
        }
        return single_block_map.get(
            formula,
            _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1], chosen_usps[:1], middle, family_middle, cta_bridge, ctas[:1], family_cta),
        )
    if block_index == 1:
        opening_map = {
            "PAS": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1]),
            "AIDA": _merge_unique_clauses(hooks, opening, family_opening, chosen_usps[:1]),
            "HSO": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1]),
            "BAB": _merge_unique_clauses(subhooks[:1], opening, family_opening, hooks[:1]),
            "PESTA": _merge_unique_clauses(hooks, opening, family_opening, angle[:1]),
            "PASTOR": _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1]),
        }
        return opening_map.get(formula, _merge_unique_clauses(hooks, opening, family_opening, subhooks[:1])) or hooks or subhooks
    if block_index == total_blocks:
        closing_stack = (
            _merge_unique_clauses(chosen_usps[:1], family_cta, cta_bridge, ctas[:1], middle, family_middle)
            if native_cta_first
            else _merge_unique_clauses(chosen_usps[:1], cta_bridge, ctas[:1], family_cta, middle, family_middle)
        )
        closing_map = {
            "PAS": closing_stack,
            "AIDA": closing_stack,
            "HSO": closing_stack,
            "BAB": closing_stack,
            "PESTA": closing_stack,
            "PASTOR": (
                _merge_unique_clauses(angle[:1], family_cta, cta_bridge, ctas[:1], middle, family_middle)
                if native_cta_first
                else _merge_unique_clauses(angle[:1], cta_bridge, ctas[:1], family_cta, middle, family_middle)
            ),
        }
        return closing_map.get(formula, closing_stack) or ctas or chosen_usps
    middle_map = {
        "PAS": _merge_unique_clauses(subhooks[:1], chosen_usps[:1], middle, family_middle),
        "AIDA": _merge_unique_clauses(chosen_usps[:2] or angle[:1], middle, family_middle),
        "HSO": _merge_unique_clauses(subhooks[:1], chosen_usps[:1], middle, family_middle),
        "BAB": _merge_unique_clauses(chosen_usps[:1], angle[:1], middle, family_middle),
        "PESTA": _merge_unique_clauses(angle[:1], chosen_usps[:1], middle, family_middle),
        "PASTOR": _merge_unique_clauses(subhooks[:1], chosen_usps[:1], middle, family_middle),
    }
    return middle_map.get(formula, _merge_unique_clauses(chosen_usps[:1], angle[:1], middle, family_middle)) or chosen_usps or subhooks or angle


def build_block_dialogue(
    *,
    copy: dict,
    block_index: int,
    total_blocks: int,
    budget: int,
    target_language: str,
    family: str,
    approved_dialogue: str | None = None,
) -> str:
    """Per-block target-language dialogue from the structured copy fields.

    Layout law: hook opens block 1; subhook + USPs fill the middle; the CTA
    lands ONLY in the final block. Approved dialogue (operator-supplied) is
    never rewritten — only placed and, at most, split across blocks."""
    if approved_dialogue:
        # Approved dialogue law: place, never rewrite. Split evenly across blocks.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean(approved_dialogue)) if s.strip()]
        if sentences:
            per_block = max(1, len(sentences) // total_blocks)
            start = (block_index - 1) * per_block
            chunk = sentences[start:start + per_block] if block_index < total_blocks else sentences[start:]
            if chunk:
                return _pack_dialogue_clauses(_split_clauses(" ".join(chunk)), budget)
    clauses = _formula_dialogue_clauses(
        copy, block_index, total_blocks, target_language=target_language, family=family,
    )
    if not clauses:
        clauses = _split_clauses(copy.get("hook") or copy.get("cta") or "")
    return _pack_dialogue_clauses(clauses, budget)


# ── source-mode section renderers ─────────────────────────────────────────────

def _product_line(product: dict[str, Any]) -> str:
    return _product_name(product)


def _mode_story_polish(source_mode: str) -> dict[str, str]:
    table = {
        "HYBRID": {
            "continuity": (
                "The presenter is the persuasion engine: whenever dialogue lands, keep face, hand, and product inside the same selling moment. "
                "Do not drift into a detached product-only montage while the creator is still selling."
            ),
            "opening": "the creator must do the selling on-camera from the first beat, not hand off to product montage language",
            "middle": "keep creator-to-product persuasion alive so the benefit feels socially sold, not merely demonstrated",
            "closing": "the close must feel label-safe, eye-contact-led, and natively sellable without becoming a hard ad tableau",
        },
        "FRAMES": {
            "continuity": (
                "Treat the uploaded finished frame as a mid-thought continuation point, not a reset. "
                "All persuasion must feel inherited from that frame's existing tension, never freshly staged."
            ),
            "opening": "the first beat must preserve inherited continuation tension instead of acting like a new hook setup",
            "middle": "every motion change should feel like micro-resolution of existing frame energy, not a fresh commercial restaging",
            "closing": "the close must feel like continuation pressure resolving inside the same frame world, not a newly performed CTA tableau",
        },
        "INGREDIENTS": {
            "continuity": (
                "Authority hierarchy is strict: product reference outranks everything for packaging truth, avatar reference outranks everything for face and identity, "
                "and style or scene guidance may decorate the world only after product and avatar truth are already satisfied."
            ),
            "opening": "the first beat must prove reference hierarchy immediately instead of blending all references into one mushy reveal",
            "middle": "every environment or style cue must stay subordinate to product truth and avatar truth while persuasion is happening",
            "closing": "the close must feel reference-faithful and balanced, never like style mood has overridden the product or the presenter",
        },
        "IMAGES": {
            "continuity": (
                "Still-image persuasion only: no implied video sequencing, no cinematic continuation language, and no fake motion logic. "
                "Everything must sell through hierarchy, packaging read, composition, and static credibility."
            ),
            "opening": "the still must establish product hierarchy instantly before atmosphere starts competing for attention",
            "middle": "every composition choice must increase static sellability, packaging read, and believable premium hierarchy",
            "closing": "the final read must feel commerce-ready through composition alone, not through implied motion or narration logic",
        },
        "T2V": {
            "continuity": (
                "Scene-first persuasion only: the world, timing, and lived-in behaviour must make the product feel native before any sales intent becomes obvious. "
                "Do not let this lane drift into creator-studio pitch language or continuation-frame logic borrowed from other workflows."
            ),
            "opening": "the first beat must feel like a real moment already happening before the product enters the selling conversation",
            "middle": "every benefit beat must feel discovered inside the scene, not announced like a detached ad script",
            "closing": "the close must resolve as a believable social moment with product payoff, not as a creator-led hard sell tableau",
        },
    }
    return table.get(source_mode, {
        "continuity": "",
        "opening": "",
        "middle": "",
        "closing": "",
    })


def _default_shot_plan(
    source_mode: str,
    *,
    product: dict[str, Any],
    shot_count: int,
    block_index: int,
    total_blocks: int,
    family: str,
    angle_hint: str,
    angle_signal: str,
    trigger_id: str,
    cta_type: str,
) -> list[str]:
    pname = _product_visual_alias(product, family)
    focus = _family_focus_terms(family)
    story = _visual_story_terms(family, angle_signal, trigger_id, cta_type)
    mode_polish = _mode_story_polish(source_mode)
    scene_native = _family_t2v_scene_clause(family)
    is_final = block_index == total_blocks
    if source_mode == "HYBRID":
        templates = [
            f"Creator-led opening beat with {pname} already in hand, matching the uploaded product image exactly while the first spoken hook lands inside a {focus['context']} setup driven by {story['opening']}; {mode_polish['opening']}.",
            f"Tight handling close-up of {pname} with the label readable, controlled reflections, and {focus['detail']} that supports the {angle_hint or 'core commercial angle'} while the frame continues to {story['middle']}; {mode_polish['middle']}.",
            f"Reaction or routine beat that keeps the same presenter and lets {pname} stay visible in-frame while the main benefit is spoken naturally through {story['middle']}, with face-product co-presence preserved while dialogue is landing.",
            f"Steady closing beat with {pname} held at chest level, eye contact to camera, and enough stillness for {story['closing']} to land cleanly while the shot still helps {story['middle']}; {mode_polish['closing']}.",
        ]
    elif source_mode == "FRAMES":
        templates = [
            f"Continue from the exact pose, grip, and camera distance already visible in the uploaded finished frame. The first beat is motion continuation only, not a new reveal, and it should carry {story['opening']}; {mode_polish['opening']}.",
            f"Ease into one believable motion-delta beat that keeps {pname} in the same position family, with no restyle, no jump cut, and no scene rebuild, while preserving {focus['detail']} and helping {story['middle']}; {mode_polish['middle']}.",
            f"Add a subtle expression or hand adjustment while keeping {pname} readable, the finished-frame lighting unchanged, and the {angle_hint or 'commercial'} tension alive through {story['middle']}, with no fresh hero re-block or new reveal logic.",
            f"Let the motion settle into a clean held frame with {pname} still truthful to the uploaded frame, ready for {story['closing']} and {focus['closing']} or a seam-safe stop while still helping {story['middle']}; {mode_polish['closing']}.",
        ]
    elif source_mode == "INGREDIENTS":
        templates = [
            f"Reference-led opening beat: the presenter must match the avatar reference while introducing {pname} exactly as shown by the product reference, with {story['opening']}; {mode_polish['opening']}.",
            f"Product truth beat: move closer to {pname} for readable packaging, honest scale, natural hand-object interaction, and {focus['detail']} without overpowering the presenter reference, while the scene helps {story['middle']}; {mode_polish['middle']}.",
            f"Environment beat: preserve the supplied scene or style direction only at the background and mood level while the product remains the visual authority and continues to {story['middle']}, with no style cue allowed to outrank product or avatar truth.",
            f"Final hold beat with presenter and {pname} in the same frame, balanced and believable, so {story['closing']} and {focus['closing']} can land without any fake demonstration while the image still helps {story['middle']}; {mode_polish['closing']}.",
        ]
    elif source_mode == "IMAGES":
        templates = [
            f"One polished commercial still of {pname} with honest scale, clean packaging readability, {focus['detail']}, {story['opening']}, and a premium but believable composition that supports {story['closing']}; {mode_polish['opening']}; {mode_polish['middle']}."
        ]
    else:  # T2V
        templates = [
            f"Open inside the lived-in scene first, then let the presenter bring {pname} into the frame naturally so the hook feels native, not staged, with {focus['context']} already visible and powered by {story['opening']}; {mode_polish['opening']}. {_clean(scene_native['opening'])}",
            f"Routine-context beat that shows why {pname} belongs in the moment, with the packaging readable, the action grounded in normal human behaviour, and {focus['detail']} carrying a middle beat that helps {story['middle']}; {mode_polish['middle']}. {_clean(scene_native['middle'])}",
            f"Confidence or payoff beat where the presenter stays on camera, keeps {pname} visible, and sells the main benefit through expression and handling rather than hard claims, aligned to {angle_hint or 'the commercial promise'} while continuing to {story['middle']}, with the scene still doing persuasion work around the product.",
            f"Clean closing beat with {pname} held clearly to camera, the presenter steady, and enough pause for {story['closing']} to feel intentional while the shot still helps {story['middle']}; {mode_polish['closing']}. {_clean(scene_native['closing'])}",
        ]
    if block_index > 1 and source_mode != "IMAGES":
        continuation_overrides = {
            "HYBRID": (
                f"Continue immediately from the previous block with the same presenter, same grip on {pname}, same lighting, and the same camera path already in progress while preserving {focus['context']}; "
                "keep the creator visibly selling, with face-product co-presence still doing persuasion work."
            ),
            "FRAMES": (
                f"Continue immediately from the previous block with the same visible frame logic around {pname}, the same lighting, and the same camera path already in progress while preserving {focus['context']}; "
                "the continuation must inherit tension from the finished frame rather than restart the commercial."
            ),
            "INGREDIENTS": (
                f"Continue immediately from the previous block with the same presenter, same grip on {pname}, same lighting, and the same camera path already in progress while preserving {focus['context']}; "
                "product truth and avatar truth must remain locked above all style cues."
            ),
            "T2V": (
                f"Continue immediately from the previous block with the same presenter, same grip on {pname}, same lighting, and the same camera path already in progress while preserving {focus['context']}; "
                "the moment must still feel lived-in, scene-native, and socially believable rather than like a reset into ad mode."
            ),
        }
        templates[0] = continuation_overrides.get(
            source_mode,
            f"Continue immediately from the previous block with the same presenter, same grip on {pname}, same lighting, and the same camera path already in progress while preserving {focus['context']}.",
        )
    selected = templates[: max(1, shot_count)]
    if is_final and source_mode != "IMAGES":
        selected[-1] = templates[-1]
    return selected


def _section_3_continuity(
    source_mode: str,
    *,
    product: dict[str, Any],
    presenter_prose: str | None,
    asset_role_map: dict | None,
    style_scene_source: str | None,
    is_continuation: bool,
    scene_context: str,
) -> str:
    """Naturalized source-mode prose — NO taxonomy labels, per retained law."""
    lines: list[str] = []
    pname = _product_line(product)
    if source_mode == "HYBRID":
        lines.append(
            f"Use the uploaded product image as the exact visual reference for {pname}: "
            "match its colour, label, cap, shape, material, and scale precisely in every shot."
        )
        lines.append(_mode_story_polish(source_mode)["continuity"])
        if presenter_prose:
            lines.append(presenter_prose)
    elif source_mode == "FRAMES":
        lines.append(
            "Use the uploaded finished frame as the single visual reference. Continue only "
            "from the visible frame state: the same subject, the same product position, the "
            "same environment, and the same lighting. Animate forward with motion only — do "
            "not rebuild, restyle, or reintroduce the subject, the product, or the scene."
        )
        lines.append(_mode_story_polish(source_mode)["continuity"])
    elif source_mode == "INGREDIENTS":
        lines.append(
            "Use the uploaded reference images exactly as provided: the product reference "
            "controls the product's true appearance, and the person reference controls the "
            "presenter's identity, face, and styling."
        )
        lines.append(_mode_story_polish(source_mode)["continuity"])
        if style_scene_source == "SCENE_CONTEXT_ONLY" or not (asset_role_map or {}).get("STYLE_SCENE_REFERENCE"):
            env = scene_context or "a clean, believable everyday setting"
            lines.append(f"The environment comes from this description only: {env}.")
        else:
            lines.append("The style reference controls the environment and mood only — never the product or the presenter.")
        lines.append("The product's true appearance outranks every other reference if they conflict.")
    elif source_mode == "T2V":
        scene_native = _family_t2v_scene_clause(_infer_product_family(product))
        if presenter_prose:
            lines.append(presenter_prose)
        lines.append(
            f"Build the scene from this description: {scene_context or 'a bright, believable everyday setting'}. "
            f"Keep {pname} visually consistent in every shot."
        )
        lines.append(_mode_story_polish(source_mode)["continuity"])
        if scene_native["continuity"]:
            lines.append(scene_native["continuity"])
        lines.append("The first beat must feel like a real moment already happening before the product enters the selling conversation.")
        lines.append("Every benefit beat must feel discovered inside the scene, not announced like a detached ad script.")
    else:  # IMAGES
        lines.append(
            f"Compose a single still image. Keep {pname} exactly true to its real packaging, "
            "label, and proportions."
        )
        lines.append(_mode_story_polish(source_mode)["continuity"])
        if presenter_prose:
            lines.append(presenter_prose)
    if is_continuation:
        lines.append(
            "This block continues the previous clip. Start from the exact final visible state "
            "of the previous block: same presenter, same grip on the product, same camera "
            "distance, same lighting, same emotional tone, and same motion direction. The "
            "first half second must contain active continuation with no pause, dead air, or freeze."
        )
    return "\n".join(lines)


def _section_8_end_frame(
    *,
    mode: str,
    pname: str,
    visual_name: str,
    is_final: bool,
    focus: dict[str, str],
    family: str,
    angle_signal: str,
    trigger_id: str,
    cta_type: str,
) -> str:
    story = _visual_story_terms(family, angle_signal, trigger_id, cta_type)
    scene_native = _family_t2v_scene_clause(family)
    if mode == "IMAGES":
        return (
            f"The final composition holds {visual_name} clearly readable as the visual anchor, with "
            f"{focus['closing']} expressed through the still image alone and {story['closing']} baked into the final read. {_sentence_case(_mode_story_polish(mode)['closing'])}"
        )
    if not is_final:
        return (
            "End on a seam-ready hold: the presenter mid-gesture with the product in grip, face "
            "toward camera, motion direction preserved so the next block can continue exactly "
            "from this state. Do not close the commercial arc yet."
        )
    if mode == "FRAMES":
        return (
            f"End by easing the existing motion into a clean held frame: {visual_name} stays truthful to the uploaded finished frame, "
            f"the presenter remains in the same scene state, and {story['closing']} guides how the closing CTA line lands without any new reveal. {_sentence_case(_mode_story_polish(mode)['closing'])}"
        )
    if mode == "INGREDIENTS":
        return (
            f"End on a balanced two-subject hold: the presenter stays faithful to the avatar reference while {visual_name} remains clearly readable and dominant as the product truth anchor, "
            f"with {story['closing']} shaping the last commercial impression. {_sentence_case(_mode_story_polish(mode)['closing'])}"
        )
    if mode == "HYBRID":
        return (
            f"{_family_end_frame_hold_phrase(family, visual_name)} while {story['closing']} carries the CTA landing. {_sentence_case(_mode_story_polish(mode)['closing'])}"
        )
    t2v_mode_close = "The close must resolve as a believable social moment with the product centered and the label readable, not as a creator-led hard sell tableau."
    if scene_native["closing"]:
        return (
            f"{_family_end_frame_hold_phrase(family, visual_name)} while {story['closing']} carries the closing line. "
            f"{scene_native['closing']} {t2v_mode_close}"
        )
    return f"{_family_end_frame_hold_phrase(family, visual_name)} while {story['closing']} carries the closing line. {t2v_mode_close}"


_LEAK_PATTERNS = (
    r"\bHYBRID\b", r"\bFRAMES MODE\b", r"\bINGREDIENTS\b", r"\bT2V\b", r"\bI2V\b", r"\bF2V\b",
    r"\bWPS\b", r"\bblock_plan\b", r"\bprompt_set_count\b", r"\bavatar pool\b",
    r"\bAVATAR_POOL\b", r"\bsource.mode\b", r"\bintake.mode\b", r"one visible creator",
    r"\bBOS_[MF]_", r"\{.*\"", r"\[camera, background, action\]",
)


def scrub_check(engine_text: str) -> list[str]:
    """QA fail conditions from retained authority: return leak violations."""
    violations = []
    for pattern in _LEAK_PATTERNS:
        if re.search(pattern, engine_text, flags=re.IGNORECASE):
            violations.append(pattern)
    return violations


def render_block(
    *,
    source_mode: str,
    engine: str,
    block_index: int,
    total_blocks: int,
    block_seconds: int,
    product: dict[str, Any],
    scene_context: str = "",
    copy: dict[str, Any] | None = None,
    approved_dialogue: str | None = None,
    presenter_profile: dict | None = None,
    asset_role_map: dict | None = None,
    style_scene_source: str | None = None,
    target_language: str = "BM_MS",
    wps_mode: str = "SAFE",
    overlay_allowed: bool = False,
    overlay_text: str | None = None,
    camera_notes: str = "",
    handling_notes: str = "",
    shot_plan: list[str] | None = None,
    shot_count_hint: int | None = None,
) -> dict[str, Any]:
    """Render ONE complete canonical 9-section engine-facing prompt block."""
    mode = str(source_mode or "").strip().upper()
    if mode not in SOURCE_MODES:
        raise ValueError(f"UNSUPPORTED_SOURCE_MODE:{source_mode}")
    lang = language_name(target_language)
    is_final = block_index == total_blocks
    is_continuation = block_index > 1
    budget = 0 if mode == "IMAGES" else dialogue_word_budget(
        block_seconds, target_language, wps_mode=wps_mode,
    )
    norm_copy = normalize_copy_intelligence(copy, product=product)
    presenter = None
    presenter_text = None
    family = _infer_product_family(product, norm_copy)
    if mode in ("HYBRID", "T2V") or (mode == "IMAGES" and presenter_profile):
        presenter = presenter_profile or avatar_registry.resolve_presenter(
            seed=_clean(product.get("id") or product.get("name") or "bosmax"),
        )
        presenter_text = avatar_registry.presenter_prose(presenter)
    pname = _product_line(product)
    visual_name = _product_visual_alias(product, family)
    category = _product_category(product)
    angle_hint = _humanize_label(norm_copy.get("angle", "")).lower()
    angle_signal = _infer_angle_signal(norm_copy, family)
    trigger_id = norm_copy.get("trigger_id", "")
    cta_type = norm_copy.get("cta_type", "")
    focus = _family_focus_terms(family)

    s1 = (
        f"You are generating {'a single commercial product image' if mode == 'IMAGES' else f'an {block_seconds}-second vertical commercial video block'} "
        f"({'final block' if is_final and total_blocks > 1 else ('continuation block' if is_continuation else 'opening block')}"
        f"{f' {block_index} of {total_blocks}' if total_blocks > 1 else ''}). "
        f"The objective is a believable, native-feeling social commerce shot that keeps {pname} "
        "credible and desirable without exaggerated claims."
    )
    if category:
        s1 += f" Treat it as a real {category.lower()} product, not a generic prop."
    if angle_hint:
        s1 += f" The commercial angle is {angle_hint}."
    s2_lines = [
        f"Preserve the exact real-world appearance of {pname}: label, cap, shape, scale, "
        "material, colour, and any readable text must match the true product in every frame.",
    ]
    if handling_notes:
        s2_lines.append(handling_notes)
    s2_lines.append("Never redesign, restyle, resize, or invent packaging.")
    s2 = "\n".join(s2_lines)
    s3 = _section_3_continuity(
        mode, product=product, presenter_prose=presenter_text,
        asset_role_map=asset_role_map, style_scene_source=style_scene_source,
        is_continuation=is_continuation, scene_context=_clean(scene_context),
    )
    shots = list(shot_plan or [])
    if not shots:
        shot_count = shot_count_hint or (1 if mode == "IMAGES" else 2)
        shots = _default_shot_plan(
            mode,
            product=product,
            shot_count=shot_count,
            block_index=block_index,
            total_blocks=total_blocks,
            family=family,
            angle_hint=angle_hint,
            angle_signal=angle_signal,
            trigger_id=trigger_id,
            cta_type=cta_type,
        )
    s4 = "\n".join(f"Shot {i + 1}: {s}" for i, s in enumerate(shots))
    if mode == "IMAGES":
        still_camera_note = (
            "Build a static 9:16 commercial still with crisp subject separation, controlled lighting, and no implied motion blur."
            if "CINEMATIC" in camera_notes.upper()
            else "Build a static 9:16 native-commercial still with believable natural light, crisp packaging readability, and no implied motion blur."
        )
        lens_note = (
            "Use a still-photography mindset: balanced composition, premium edge control, and product-first depth separation."
        )
        s5_lines = [
            "Clean commercial framing with the product sharply in focus.",
            f"{still_camera_note} {lens_note}",
        ]
    else:
        s5_lines = [
            "Handheld vertical 9:16 framing with natural micro-jitter and organic human sway.",
            camera_notes or "Eye-level medium close-up to close-up range; soft natural light; no flash, no hard fill.",
        ]
    if is_continuation:
        s5_lines.append(
            "For the first half second, continue the exact motion already in progress. For the "
            "first one to two seconds, keep the presenter's face and mouth clearly visible and "
            "synchronized to every spoken word — the product may stay near chest level, but "
            "there is no product-only shot during the opening spoken line."
        )
    s5 = "\n".join(s5_lines)
    dialogue = "" if mode == "IMAGES" else build_block_dialogue(
        copy=norm_copy, block_index=block_index, total_blocks=total_blocks,
        budget=budget, target_language=target_language, family=family,
        approved_dialogue=approved_dialogue,
    )
    s6 = dialogue if dialogue else "(No spoken dialogue in this block.)"
    family_voice = _family_voice_clause(family, target_language)
    s7 = (
        f"The presenter speaks {lang} only, direct to camera, in short, natural, conversational phrasing — present in the moment, never narrating from outside it. "
        f"{family_voice + ' ' if family_voice else ''}"
        "No voice-over. No off-camera speech. No audio-only dialogue."
    ) if mode != "IMAGES" else "Not applicable — still image output."
    s8 = _section_8_end_frame(
        mode=mode,
        pname=pname,
        visual_name=visual_name,
        is_final=is_final,
        focus=focus,
        family=family,
        angle_signal=angle_signal,
        trigger_id=trigger_id,
        cta_type=cta_type,
    )
    if overlay_allowed and overlay_text:
        s9 = f"On-screen text is permitted for this block only: '{_clean(overlay_text)}'. No other captions, subtitles, price text, or sticker text."
    else:
        s9 = (
            "No on-screen text of any kind: no captions, no subtitles, no lower-thirds, no "
            "sticker text, no price text, no watermarks. Everything persuasive is spoken."
        )

    bodies = (s1, s2, s3, s4, s5, s6, s7, s8, s9)
    engine_text = "\n\n".join(
        f"{header}\n{body}" for header, body in zip(CANONICAL_SECTIONS, bodies)
    )
    violations = scrub_check(engine_text)
    return {
        "block_index": block_index,
        "block_seconds": block_seconds,
        "is_final": is_final,
        "engine_prompt_text": engine_text,
        "dialogue": dialogue,
        "dialogue_word_budget": budget,
        "dialogue_word_count": len(dialogue.split()) if dialogue else 0,
        "presenter": presenter,
        "scrub_violations": violations,
        "sections": dict(zip(CANONICAL_SECTIONS, bodies)),
    }


def compile_prompt_set(
    *,
    source_mode: str,
    engine: str = "GOOGLE_FLOW",
    duration_seconds: int = 8,
    preferred_lane: str | None = None,
    product: dict[str, Any],
    scene_context: str = "",
    copy: dict[str, Any] | None = None,
    approved_dialogue: str | None = None,
    avatar_id: str | None = None,
    presenter_profile: dict | None = None,
    asset_role_map: dict | None = None,
    style_scene_source: str | None = None,
    target_language: str = "BM_MS",
    wps_mode: str = "SAFE",
    overlay_allowed: bool = False,
    overlay_text: str | None = None,
    camera_notes: str = "",
    handling_notes: str = "",
) -> dict[str, Any]:
    """Compile the full MULTI-PROMPT SET: one complete 9-section block per
    workbook-derived block (1-7). This is THE canonical entrypoint."""
    mode = str(source_mode or "").strip().upper()
    if mode not in SOURCE_MODES:
        raise ValueError(f"UNSUPPORTED_SOURCE_MODE:{source_mode}")
    if mode == "IMAGES":
        plan = [0]
    else:
        plan = resolve_block_plan(engine, duration_seconds, preferred_lane=preferred_lane)
    # HYBRID law: resolve ONE concrete presenter BEFORE rendering, reuse across blocks.
    resolved_profile = presenter_profile
    if mode in ("HYBRID", "T2V") and not resolved_profile:
        resolved_profile = avatar_registry.resolve_presenter(
            avatar_id,
            usage_context=_clean(product.get("category")),
            seed=_clean(product.get("id") or product.get("name") or "bosmax"),
        )
    if mode == "INGREDIENTS":
        roles = {str(k).upper(): v for k, v in (asset_role_map or {}).items()}
        if not (roles.get("PRODUCT_REFERENCE") and roles.get("AVATAR_REFERENCE")):
            raise ValueError("INGREDIENTS_ASSET_ROLE_MAP_INCOMPLETE: PRODUCT_REFERENCE + AVATAR_REFERENCE required")
        if not roles.get("STYLE_SCENE_REFERENCE"):
            style_scene_source = "SCENE_CONTEXT_ONLY"
        asset_role_map = roles
    total = len(plan)
    blocks = []
    for i, seconds in enumerate(plan, start=1):
        blocks.append(render_block(
            source_mode=mode, engine=engine, block_index=i, total_blocks=total,
            block_seconds=seconds or duration_seconds, product=product,
            scene_context=scene_context, copy=copy, approved_dialogue=approved_dialogue,
            presenter_profile=resolved_profile, asset_role_map=asset_role_map,
            style_scene_source=style_scene_source, target_language=target_language,
            wps_mode=wps_mode, overlay_allowed=overlay_allowed, overlay_text=overlay_text,
            camera_notes=camera_notes, handling_notes=handling_notes,
            shot_count_hint=1 if mode == "IMAGES" else min(4, max(2, round((seconds or duration_seconds) / 4))),
        ))
    all_violations = [v for b in blocks for v in b["scrub_violations"]]
    if all_violations:
        raise ValueError(f"ENGINE_OUTPUT_SCRUB_FAILED:{sorted(set(all_violations))}")
    return {
        "compiler_authority": "canonical_prompt_compiler_v1",
        "source_mode": mode,
        "engine": str(engine).strip().upper().replace(" ", "_"),
        "block_plan": plan if mode != "IMAGES" else [],
        "total_blocks": total,
        "wps_mode": str(wps_mode).upper(),
        "target_language": target_language,
        "presenter": resolved_profile,
        "blocks": blocks,
    }
