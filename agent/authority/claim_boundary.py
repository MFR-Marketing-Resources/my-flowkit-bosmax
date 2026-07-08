"""Claim Boundary — the BOSMAX owner rule made executable.

Sales-first, market-language-first. The engine must NOT be cowardly: it must
NOT erase the customer's real problem language (kembung perut, perut berangin,
gigitan serangga, sengal, kebas, resdung, anak susah lena, ...) — that language
is exactly what makes copy sell and lets a TikTok Shop buyer understand what the
product is for.

Two tiers:
  * PROBLEM_LANGUAGE_ALLOWED — market problem / traditional-use language that is
    PRESERVED (and encouraged). Never banned.
  * OVERCLAIM_BANNED — the only thing controlled: medical cure/treatment claims,
    certainty/guarantees, clinical/certification claims, and (for stealth
    products) explicit anatomy/act. These stay hard-banned.

This module is deliberately separate from copy_family_grounding.FRAMEWORK_BANNED_TERMS
(which wrongly banned "buang angin"/"legakan") and from
claim_safe_rewrite_service.FORBIDDEN_PHRASES (a narrower runtime scan). It is the
single authority for "what may I say vs what is overclaim" in the copy brief and
the formula validator.
"""
from __future__ import annotations

# ── Preserve: market problem / traditional-use language (NEVER banned) ───────
PROBLEM_LANGUAGE_ALLOWED: list[str] = [
    # digestive / baby unsettled
    "kembung", "kembung perut", "perut berangin", "berangin", "buang angin",
    "angin dalam badan", "sakit perut", "kolik", "anak susah lena",
    "anak tak selesa", "anak merengek", "susah tidur", "berjaga malam",
    # aches / numbness
    "sengal", "sengal-sengal", "kebas", "lenguh", "urat tegang", "pegal",
    # nose / seasonal
    "resdung", "hidung tersumbat", "selesema",
    # skin / bites / minor
    "gigitan serangga", "gigitan nyamuk", "gatal", "luka kecil", "calar",
    # traditional-use framing (soft, non-medical)
    "minyak sapuan", "sapuan tradisional", "minyak urut", "minyak angin",
    "urut", "sapu", "warisan", "tradisional",
    # soft relief/comfort framing (traditional use, NOT a cure guarantee)
    "lega", "legakan", "melegakan", "selesa", "redakan", "meredakan", "tenang",
]

# ── Control: overclaim (the ONLY thing banned) ───────────────────────────────
_OVERCLAIM_MEDICAL_CURE = [
    "cure", "cures", "heal", "heals", "sembuh", "menyembuhkan", "penyembuh",
    "rawat", "merawat", "rawatan", "ubat", "perubatan", "mengubati",
]
_OVERCLAIM_CERTAINTY_GUARANTEE = [
    "100%", "100 %", "guarantee", "guaranteed", "dijamin", "jaminan", "gerenti",
    "pasti sembuh", "pasti berkesan", "miracle", "ajaib", "mukjizat",
    "instant cure", "instant relief", "serta-merta sembuh", "terus sembuh",
]
_OVERCLAIM_CLINICAL_CERTIFICATION = [
    "clinically proven", "terbukti secara klinikal", "klinikal", "kajian klinikal",
    "doctor recommended", "disyorkan doktor", "doktor mengesahkan",
    "kkm", "npra", "diluluskan kkm", "sijil kkm", "no side effects",
    "tiada kesan sampingan", "selamat 100%",
]
# Stealth / sensitive products: explicit anatomy & act (never named).
_OVERCLAIM_ANATOMY_EXPLICIT = [
    "zakar", "penis", "kemaluan", "seks", "seksual", "ereksi", "mati pucuk",
    "lemah tenaga batin",
]

OVERCLAIM_BANNED_GENERAL: list[str] = (
    _OVERCLAIM_MEDICAL_CURE
    + _OVERCLAIM_CERTAINTY_GUARANTEE
    + _OVERCLAIM_CLINICAL_CERTIFICATION
)
OVERCLAIM_BANNED_STEALTH: list[str] = OVERCLAIM_BANNED_GENERAL + _OVERCLAIM_ANATOMY_EXPLICIT


def _hits(text: str, terms: list[str]) -> list[str]:
    low = str(text or "").casefold()
    seen: list[str] = []
    for term in terms:
        t = term.casefold()
        if t and t in low and term not in seen:
            seen.append(term)
    return seen


def banned_terms_for_brief(is_stealth: bool = False) -> list[str]:
    """The corrected banned-terms list to feed the copy brief: OVERCLAIM ONLY.
    Market problem / traditional-use language is deliberately absent so the
    provider is free to speak the buyer's real problem language."""
    return list(OVERCLAIM_BANNED_STEALTH if is_stealth else OVERCLAIM_BANNED_GENERAL)


def assess_claim_boundary(text: str, is_stealth: bool = False) -> dict:
    """Classify a copy string against the two tiers.

    Returns:
      overclaim_hits: banned overclaim terms present (must be zero to be safe)
      problem_language_present: preserved market/problem terms present (>0 is a
        GOOD sign the copy is not cowardly/vague)
      safe: no overclaim hits
    """
    banned = OVERCLAIM_BANNED_STEALTH if is_stealth else OVERCLAIM_BANNED_GENERAL
    overclaim_hits = _hits(text, banned)
    return {
        "overclaim_hits": overclaim_hits,
        "problem_language_present": _hits(text, PROBLEM_LANGUAGE_ALLOWED),
        "safe": not overclaim_hits,
    }


def is_problem_language(text: str) -> bool:
    """True if the copy references at least one real market/problem term — used
    by the validator to reject vague, problem-blind ('cowardly') copy."""
    return bool(_hits(text, PROBLEM_LANGUAGE_ALLOWED))
