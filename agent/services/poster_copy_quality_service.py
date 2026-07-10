"""Poster copy quality guard (POSTER_EXPERT_SYSTEM_REDESIGN_V1).

Evaluates poster-NATIVE copy the way an expert e-commerce poster reviewer would:
first-read headline, one short support line, 2-3 tight chips, a short CTA, one
core idea, mobile-readable, compliance-safe. Raises BLOCK findings (generation
must not proceed) and WARN findings (surface to operator).

Self-contained (no import from poster_prompt_draft_service) so build_draft can
import THIS without a cycle.
"""

from __future__ import annotations

import re
from typing import Any

from agent.models.poster_copy_quality import (
    BLOCK,
    WARN,
    PosterCopyFinding,
    PosterCopyQualityReport,
    PosterCopyQualityRequest,
)

# ── Expert poster limits (poster-native, stricter than video copy) ────────────
HEADLINE_MAX_WORDS = 7
HEADLINE_HARD_WORDS = 10
HEADLINE_MAX_CHARS = 48
HEADLINE_MOBILE_CHARS = 40
SUPPORT_MAX_WORDS = 14
SUPPORT_MAX_CHARS = 90
CHIP_MAX_WORDS = 5
CHIP_MAX_CHARS = 36
CTA_MAX_WORDS = 4
CTA_HARD_WORDS = 6
CTA_MAX_CHARS = 24
DEFAULT_MAX_CHIPS = 3

# Medical / symptom / relief wording — a poster must not carry these (BLOCK).
# Includes the exact forbidden defaults (perut kembung / legakan / tidur terganggu).
MEDICAL_RELIEF_TERMS: tuple[str, ...] = (
    "cure", "treat", "heal", "disease", "guaranteed relief", "pain gone", "relief",
    "symptom", "ubat", "sembuh", "rawat", "penyakit", "hilang sakit", "jamin lega",
    "legakan", "melegakan", "lega", "kembung", "perut kembung", "simptom",
    "sakit", "tidur terganggu", "meragam",
)

# Video-script / narrative markers — a poster is not a compressed video ad (WARN).
VIDEO_SCRIPT_MARKERS: tuple[str, ...] = (
    "mungkin", "jangan biar", "jangan biarkan", "berlarutan", "masalah ini",
    "esoknya", "pernah tak", "risau", "penat", "menangis", "tak boleh tidur",
)

# V1 OFFER policy: NON-PRICE promotional creative only. Numeric price/discount
# claims are BLOCKED until a real OfferSpec + offer-truth source exists.
_PRICE_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s?\d", re.IGNORECASE),
    re.compile(r"\d\s?%"),
    re.compile(r"\bdiskaun\b[^.!?]*\d", re.IGNORECASE),
    re.compile(r"\bvoucher\b[^.!?]*\d", re.IGNORECASE),
)

CHILD_TERMS: tuple[str, ...] = (
    "anak", "bayi", "baby", "kanak", "budak", "si kecil", "infant", "toddler",
)

# Distinct "selling idea" themes for the one-core-idea check.
IDEA_THEMES: dict[str, tuple[str, ...]] = {
    "size_portability": ("saiz", "size", "kecil", "mudah dibawa", "portable", "ringan", "bawa", "ml"),
    "heritage": ("warisan", "tradisional", "turun-temurun", "heritage", "sejak", "tradition"),
    "routine": ("rutin", "harian", "setiap hari", "routine", "daily", "malam"),
    "offer": ("promo", "offer", "harga", "diskaun", "jimat", "murah", "price", "sale", "rm"),
}


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _words(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])


def _sentences(s: str) -> int:
    parts = [p for p in re.split(r"[.!?]+", s) if p.strip()]
    return len(parts)


def _compile_terms(terms: tuple[str, ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile each term into a word-boundary / exact-phrase matcher.

    Multi-word terms match as an exact phrase (internal whitespace flexible);
    short standalone terms match only on word boundaries so they NEVER
    substring-match inside an unrelated word — e.g. "lega" must not fire on the
    safe brand word "Legasi", but "legakan" (its own listed term) still fires.
    """
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for term in terms:
        parts = [re.escape(p) for p in term.lower().split() if p]
        if not parts:
            continue
        pattern = r"\b" + r"\s+".join(parts) + r"\b"
        compiled.append((term, re.compile(pattern, re.IGNORECASE)))
    return tuple(compiled)


_MEDICAL_RELIEF_PATTERNS = _compile_terms(MEDICAL_RELIEF_TERMS)
_VIDEO_SCRIPT_PATTERNS = _compile_terms(VIDEO_SCRIPT_MARKERS)
_CHILD_PATTERNS = _compile_terms(CHILD_TERMS)


def _hits(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> list[str]:
    """Return the terms whose word-boundary / phrase pattern matches ``text``."""
    return [term for term, pat in patterns if pat.search(text)]


def _themes(text: str) -> set[str]:
    low = text.lower()
    found: set[str] = set()
    for theme, kws in IDEA_THEMES.items():
        if any(k in low for k in kws):
            found.add(theme)
    return found


def evaluate_poster_copy(
    request: PosterCopyQualityRequest | dict[str, Any],
) -> PosterCopyQualityReport:
    req = (
        request
        if isinstance(request, PosterCopyQualityRequest)
        else PosterCopyQualityRequest.model_validate(request)
    )
    headline = _norm(req.poster_headline)
    support = _norm(req.poster_support_line)
    chips = [_norm(c) for c in req.poster_chips if _norm(c)]
    cta = _norm(req.poster_cta)
    detail = _norm(req.product_detail_line)
    max_chips = req.max_chips if req.max_chips and req.max_chips > 0 else DEFAULT_MAX_CHIPS
    child = bool(req.child_sensitive) or bool(_hits(" ".join([headline, support, *chips]), _CHILD_PATTERNS))

    f: list[PosterCopyFinding] = []

    def add(code: str, sev: str, field: str, msg: str) -> None:
        f.append(PosterCopyFinding(code=code, severity=sev, field=field, message=msg))

    # ── Headline ──
    if not headline:
        add("HEADLINE_MISSING", BLOCK, "headline", "Poster mesti ada headline first-read.")
    else:
        hw = _words(headline)
        if hw > HEADLINE_HARD_WORDS:
            add("HEADLINE_TOO_LONG", BLOCK, "headline",
                f"Headline {hw} patah perkataan — poster headline 3–7 patah sahaja.")
        elif hw > HEADLINE_MAX_WORDS:
            add("HEADLINE_TOO_LONG", WARN, "headline",
                f"Headline {hw} patah perkataan — sasar 3–7 patah untuk first-read.")
        if len(headline) > HEADLINE_MAX_CHARS:
            add("HEADLINE_OVER_CHARS", WARN, "headline",
                f"Headline {len(headline)} aksara — pendekkan (≤{HEADLINE_MAX_CHARS}).")
        elif len(headline) > HEADLINE_MOBILE_CHARS:
            add("HEADLINE_MOBILE", WARN, "headline",
                "Headline agak panjang untuk mobile first-read — pertimbang lebih pendek.")

    # ── Support line ──
    if support:
        if _words(support) > SUPPORT_MAX_WORDS or _sentences(support) > 1:
            add("SUPPORT_TOO_LONG", WARN, "support",
                "Support line mesti satu ayat pendek (second-read), bukan perenggan.")
        if len(support) > SUPPORT_MAX_CHARS:
            add("SUPPORT_OVER_CHARS", WARN, "support",
                f"Support line {len(support)} aksara — terlalu panjang untuk poster.")

    # ── Chips ──
    if len(chips) > max_chips:
        add("TOO_MANY_CHIPS", BLOCK, "chips",
            f"{len(chips)} chip — poster benarkan {max_chips} chip sahaja.")
    for i, c in enumerate(chips, 1):
        if _words(c) > CHIP_MAX_WORDS:
            add("CHIP_TOO_LONG", WARN, "chips",
                f"Chip {i} '{c[:20]}…' terlalu panjang — 2–5 patah sahaja.")

    # ── CTA ──
    if not cta:
        add("CTA_MISSING", BLOCK, "cta", "Poster mesti ada satu CTA (2–4 patah).")
    else:
        cw = _words(cta)
        if cw > CTA_HARD_WORDS:
            add("CTA_TOO_LONG", BLOCK, "cta", f"CTA {cw} patah — CTA poster 2–4 patah sahaja.")
        elif cw > CTA_MAX_WORDS:
            add("CTA_TOO_LONG", WARN, "cta", f"CTA {cw} patah — sasar 2–4 patah.")

    # ── Compliance: medical / symptom / relief (BLOCK) ──
    blob = " ".join([headline, support, *chips, cta, detail])
    med = _hits(blob, _MEDICAL_RELIEF_PATTERNS)
    if med:
        sev = BLOCK
        add("MEDICAL_RELIEF_CLAIM", sev, "overall",
            "Copy poster mengandungi bahasa perubatan/simptom/kelegaan: "
            + ", ".join(sorted(set(med)))
            + ". Poster e-dagang mesti bebas claim rawatan/simptom.")
        if child:
            add("CHILD_HEALTH_CLAIM", BLOCK, "overall",
                "Audiens bayi/anak + bahasa kesihatan — mesti sangat konservatif; buang claim.")

    # ── OFFER V1 policy: non-price promotional only (BLOCK) ──
    if _norm(req.archetype).upper() == "OFFER":
        if any(p.search(blob) for p in _PRICE_CLAIM_PATTERNS):
            add("OFFER_PRICE_CLAIM_UNSUPPORTED", BLOCK, "overall",
                "Poster OFFER V1 adalah promosi TANPA harga: buang angka harga/"
                "diskaun/voucher (tiada sumber offer-truth lagi).")

    # ── Video-script / narrative style (WARN) ──
    narrative = _hits(blob, _VIDEO_SCRIPT_PATTERNS)
    headline_is_scenario = headline.endswith("?") and _words(headline) > HEADLINE_MAX_WORDS
    if narrative or headline_is_scenario:
        add("VIDEO_SCRIPT_STYLE", WARN, "overall",
            "Copy berbunyi gaya skrip video/ad (naratif/soalan-scenario). Poster = "
            "satu idea, headline padu, bukan cerita.")

    # ── One core idea (WARN) ──
    themes = _themes(blob)
    if len(themes) > 1:
        add("TOO_MANY_IDEAS", WARN, "overall",
            f"Poster menyentuh {len(themes)} idea jualan ({', '.join(sorted(themes))}). "
            "Poster kuat = satu idea teras sahaja.")

    blocks = sum(1 for x in f if x.severity == BLOCK)
    warns = sum(1 for x in f if x.severity == WARN)
    return PosterCopyQualityReport(
        ok=blocks == 0, findings=f, block_count=blocks, warn_count=warns
    )


def map_legacy_to_poster(fields: dict[str, Any]) -> dict[str, Any]:
    """Map legacy video-style fields (hook/subhook/usp/cta) into poster-native
    copy. Legacy fields remain the storage; posters THINK in poster language."""
    chips = [
        _norm(fields.get("usp_1")),
        _norm(fields.get("usp_2")),
        _norm(fields.get("usp_3")),
    ]
    return {
        "poster_headline": _norm(fields.get("hook")),
        "poster_support_line": _norm(fields.get("subhook")),
        "poster_chips": [c for c in chips if c],
        "poster_cta": _norm(fields.get("cta")),
        "product_detail_line": _norm(fields.get("product_detail_line")),
    }
