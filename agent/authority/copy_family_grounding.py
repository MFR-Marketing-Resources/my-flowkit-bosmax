"""Family → copy grounding, sourced FAITHFULLY from
`agent/authority/COPYWRITING_FRAMEWORK_UNIVERSAL.yaml` + the BOSMAX copywriting /
customer-avatar method. This is the FRAMEWORK tier used when a product has no
approved product_intelligence_snapshot yet.

It crosswalks each product-intelligence family (from
product_intelligence_service.FAMILY_PROFILES) to the framework's avatar
dimensions (customer_avatar_builder), trigger library (trigger_library),
angle families (angle_generation_engine.category_examples), tone rules
(sensitive_product_mode) and claim posture (validation_rules). It defines the
AVATAR + ANGLE STRATEGY + TONE + CLAIM guardrails — NOT product claims. Product
facts (benefits/USPs/ingredients) come only from an approved snapshot.

Family keys are case-sensitive and must match FAMILY_PROFILES exactly.
"""
from __future__ import annotations

# validation_rules.banned_claims + explicit_sensitive_bans (framework lines
# 420-436) + the Malay/English claim scanner from the BOSMAX orchestrator.
FRAMEWORK_BANNED_TERMS = [
    # explicit_sensitive_bans (never name the anatomy/act)
    "zakar", "penis", "seks", "seksual", "ereksi", "mati pucuk",
    # banned_claims (no medical certainty / guarantees)
    "cure", "guarantee", "100%", "miracle", "clinically proven",
    "doctor recommended", "no side effects", "instant cure", "instant relief",
    # Malay claim terms (orchestrator claim safety)
    "sembuh", "rawat", "ubat", "dijamin", "gerenti", "klinikal", "doktor",
    "kkm", "npra", "buang angin", "legakan",
]

# Non-sensitive trigger library (framework trigger_library.non_sensitive_triggers)
_DIRECT_TRIGGERS = [
    "convenience", "speed", "compactness", "premium_look", "giftability",
    "ease_of_use", "habit_fit", "price_value",
]
# stealth_sensitive_triggers (framework trigger_library.stealth_sensitive_triggers)
_STEALTH_TRIGGERS = [
    "ego", "maruah", "self_image", "readiness", "comparison_pressure",
    "secrecy", "confidence_recovery",
]

# ── Family grounding entries ─────────────────────────────────────────────

_MALE_HEALTH_SENSITIVE = {
    "avatar": {
        "audience": "Lelaki dewasa (25–55) yang sedar imej diri & maruah; beli secara diskret.",
        "desires": [
            "rasa yakin dan 'ready' semula",
            "jaga maruah dan ego sebagai lelaki",
            "rasa bertenaga / muda semula",
            "yakin dan kawal depan pasangan",
        ],
        "fears": [
            "malu / segan dilihat membeli produk sensitif",
            "rasa 'kurang' berbanding orang lain",
            "hampakan pasangan",
            "privasi terdedah",
        ],
        "pains": [
            "keyakinan diri menurun",
            "tekanan perbandingan (comparison pressure)",
            "rutin harian terjejas",
            "enggan berjumpa doktor kerana malu",
        ],
        "objections": [
            "betul ke berkesan?",
            "selamat ke digunakan?",
            "orang nampak tak apa yang aku beli?",
            "berbaloi ke dengan harganya?",
        ],
        "triggers": _STEALTH_TRIGGERS + ["dominance_fantasy"],
        "tone": "wrapped, ego-aware, masculine teasing bila relevan; dialogue-safe; JANGAN eksplisit/anatomikal",
        "pronoun": "aku / kau / bro / abang (register STEALTH)",
    },
    "angle_strategies": [
        "stealth_masculinity", "wrapped_readiness", "maruah_and_ego",
        "compact_standby", "symbolic_power", "private_confidence",
    ],
    "copy_formula": "PAS / PESTA / SAVAGE_HPAS (STEALTH silo)",
    "metaphor_silos": [
        "tenaga_stamina", "mekanikal_enjin", "tiang_struktur",
        "agri_kebun", "premium_presence",
    ],
    "claim_posture": "CLAIM_REVIEW_REQUIRED",
}

_FEMALE_HEALTH_SENSITIVE = {
    "avatar": {
        "audience": "Wanita dewasa yang menjaga keyakinan & kebersihan diri; beli secara diskret.",
        "desires": [
            "rasa segar dan yakin sepanjang hari",
            "jaga maruah dan keyakinan diri",
            "rasa bersih dan selesa",
            "yakin dalam hubungan",
        ],
        "fears": [
            "malu / segan membeli produk sensitif",
            "rasa kurang yakin",
            "privasi terdedah",
        ],
        "pains": [
            "keyakinan diri menurun",
            "rasa tidak selesa dalam rutin harian",
            "tekanan sosial / perbandingan",
        ],
        "objections": [
            "selamat ke digunakan?",
            "berkesan ke?",
            "orang nampak tak apa yang aku beli?",
        ],
        "triggers": _STEALTH_TRIGGERS,
        "tone": "wrapped, lembut, menjaga maruah; dialogue-safe; JANGAN eksplisit/anatomikal",
        "pronoun": "aku / kau / awak (register lembut STEALTH)",
    },
    "angle_strategies": [
        "subtle_readiness", "private_confidence", "maruah_pressure",
        "compact_standby", "daily_freshness_confidence",
    ],
    "copy_formula": "PAS / HSO (STEALTH silo)",
    "metaphor_silos": ["premium_presence", "agri_kebun"],
    "claim_posture": "CLAIM_REVIEW_REQUIRED",
}

_HEALTH_SUPPLEMENT = {
    "avatar": {
        "audience": "Pengguna dewasa yang mahu sokongan rutin kesihatan tanpa janji perubatan.",
        "desires": ["rasa selesa & disokong dalam rutin", "praktikal dan mudah diamalkan"],
        "fears": ["ragu keberkesanan", "risau keselamatan"],
        "pains": ["rutin harian tak konsisten", "cari sokongan yang praktikal"],
        "objections": ["betul ke membantu?", "selamat ke?"],
        "triggers": ["comfort", "routine_support", "habit_fit"],
        "tone": "comfort / routine-support / bahasa berhati-hati tanpa kepastian (careful non-certainty)",
        "pronoun": "saya / anda",
    },
    "angle_strategies": [
        "routine_support", "daily_convenience", "practical_standby",
        "trust_and_transparency", "compact_carry",
    ],
    "copy_formula": "HSO / PAS (review-gated)",
    "metaphor_silos": [],
    "claim_posture": "CLAIM_REVIEW_REQUIRED",
}

_FRAGRANCE = {
    "avatar": {
        "audience": "Pengguna yang mahu kehadiran wangian & keyakinan diri.",
        "desires": ["first impression yang menyerlah", "kehadiran & keyakinan", "signature diri"],
        "fears": ["bau tidak tahan lama", "tidak menyerlah"],
        "pains": ["mahu tampil yakin di tempat kerja / temujanji"],
        "objections": ["tahan lama tak?", "berbaloi tak harganya?"],
        "triggers": _DIRECT_TRIGGERS,
        "tone": "premium, benefit-led, bersih & langsung",
        "pronoun": "saya / anda",
    },
    "angle_strategies": [
        "first_impression", "lasting_presence", "premium_aura",
        "office_clean_confidence", "date_night_presence", "giftable_signature",
    ],
    "copy_formula": "PAS / HSO / AIDA",
    "metaphor_silos": [],
    "claim_posture": "CLAIM_SAFE",
}

_BEAUTY_PERSONAL_CARE = {
    "avatar": {
        "audience": "Pengguna yang mahu naik taraf rutin & keyakinan penampilan.",
        "desires": ["rutin lebih kemas", "penampilan lebih yakin", "mudah & pantas"],
        "fears": ["rutin leceh", "hasil tak konsisten"],
        "pains": ["mahu penampilan yakin tanpa leceh"],
        "objections": ["senang guna tak?", "sesuai tak untuk saya?"],
        "triggers": _DIRECT_TRIGGERS,
        "tone": "bersih, benefit-led, mesra",
        "pronoun": "saya / anda",
    },
    "angle_strategies": [
        "routine_upgrade", "polished_finish", "portable_touch_up",
        "confidence_boost", "daily_convenience",
    ],
    "copy_formula": "PAS / AIDA",
    "metaphor_silos": [],
    "claim_posture": "CLAIM_SAFE",
}

# Generic direct / non-sensitive families — angles built from the framework's
# five mandatory angle dimensions (pain, aspiration, context, objection, urgency).
_DIRECT_DEFAULT = {
    "avatar": {
        "audience": "Pembeli praktikal yang mahu penyelesaian mudah & berbaloi.",
        "desires": ["mudah & jimat masa", "berbaloi dengan harga", "hasil yang jelas"],
        "fears": ["membazir wang", "produk tak berbaloi"],
        "pains": ["mahu selesaikan keperluan harian dengan cepat"],
        "objections": ["berbaloi ke?", "senang guna tak?", "berkualiti ke?"],
        "triggers": _DIRECT_TRIGGERS,
        "tone": "praktikal, premium bila sesuai, benefit-led",
        "pronoun": "saya / anda",
    },
    "angle_strategies": [
        "daily_convenience", "compact_carry", "value_for_money",
        "premium_quality", "problem_solution_clarity",
    ],
    "copy_formula": "PAS / HSO / AIDA",
    "metaphor_silos": [],
    "claim_posture": "CLAIM_SAFE",
}

# Fail-closed default for UNKNOWN_REVIEW_REQUIRED / unmapped families.
_UNKNOWN_DEFAULT = {
    "avatar": {
        "audience": "",
        "desires": [], "fears": [], "pains": [], "objections": [],
        "triggers": [], "tone": "berhati-hati; review diperlukan", "pronoun": "saya / anda",
    },
    "angle_strategies": ["daily_convenience", "value_for_money", "trust_and_transparency"],
    "copy_formula": "PAS / HSO (review-gated)",
    "metaphor_silos": [],
    "claim_posture": "CLAIM_REVIEW_REQUIRED",
}

# Exact FAMILY_PROFILES keys → grounding (case-sensitive).
COPY_FAMILY_GROUNDING: dict[str, dict] = {
    "MALE_HEALTH_SENSITIVE": _MALE_HEALTH_SENSITIVE,
    "FEMALE_HEALTH_SENSITIVE": _FEMALE_HEALTH_SENSITIVE,
    "HEALTH_SUPPLEMENT": _HEALTH_SUPPLEMENT,
    "beauty_fragrance": _FRAGRANCE,
    "BEAUTY_PERSONAL_CARE": _BEAUTY_PERSONAL_CARE,
    # Direct / non-sensitive families → shared direct grounding
    "LAUNDRY_DETERGENT_LIQUID_REFILL": _DIRECT_DEFAULT,
    "FABRIC_SOFTENER_LIQUID": _DIRECT_DEFAULT,
    "HOUSEHOLD_CLEANER_GENERAL": _DIRECT_DEFAULT,
    "HOUSEHOLD_STORAGE_ORGANIZER": _DIRECT_DEFAULT,
    "HOME_TEXTILE": _DIRECT_DEFAULT,
    "APPAREL_SLEEPWEAR": _DIRECT_DEFAULT,
    "fashion_modestwear": _DIRECT_DEFAULT,
    "fashion_sportswear": _DIRECT_DEFAULT,
    "fashion_apparel": _DIRECT_DEFAULT,
    "ACCESSORY_SMALL_ITEM": _DIRECT_DEFAULT,
    "BABY_DIAPER": _DIRECT_DEFAULT,
    "BABY_WIPES": _DIRECT_DEFAULT,
    "food_packaged": _DIRECT_DEFAULT,
    "stationery_paper": _DIRECT_DEFAULT,
    "electronics_wearable": _DIRECT_DEFAULT,
    "PET_CARE_GENERAL": _DIRECT_DEFAULT,
    "AUTO_TOOL_GENERAL": _DIRECT_DEFAULT,
    "toy_play": _DIRECT_DEFAULT,
    "REAL_ESTATE_OR_SERVICE": _UNKNOWN_DEFAULT,
    "UNKNOWN_REVIEW_REQUIRED": _UNKNOWN_DEFAULT,
}


def grounding_for_family(family: str) -> dict:
    """Return the framework-sourced grounding for a family key (fail-closed to
    the review-required default for any unmapped/unknown family)."""
    return COPY_FAMILY_GROUNDING.get(family) or _UNKNOWN_DEFAULT
