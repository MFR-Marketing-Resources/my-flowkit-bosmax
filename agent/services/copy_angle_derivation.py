"""Derive product-specific copy ANGLES from an approved buyer persona.

Phase A1 of `.ai/architecture/COPY_ANGLE_AND_COMPONENT_ARCHITECTURE.md`.

WHY THIS EXISTS
---------------
`product_intelligence_snapshot.copy_strategy_summary_json` is a pass-through
field: nothing ever derived its `angles` from the product's own persona, so
every draft inherited the framework FAMILY template. Measured 2026-07-24: all
30 approved snapshots carry one of 7 generic family templates and ZERO carry
product-specific angles — a herbal colic oil shares its angle list with a hair
clipper and a lip tint. The copy generator rotates those angles correctly
(`ai_copy_assist_service._rotation_angles`), so a wrong axis produces a
correct-looking rotation over irrelevant labels, and the model falls back to
the single most vivid persona pain every time.

This module is the missing derivation. It is PURE (no I/O, no LLM, no DB) so it
is cheap to test and impossible to make non-deterministic.

CONTRACT
--------
* Angle granularity is **pain x audience** (owner decision 2026-07-24).
* One angle per persona pain. Pains are the use-case axis.
* `desires` / `fears` / `triggers` are matched to a pain by TOKEN OVERLAP, never
  by list index: the arrays are not reliably index-aligned in live data (one
  product has 3 pains but 4 triggers, and a MWTCB trigger belongs to a different
  pain than its index implies).
* Audience is taken from the product-level `persona.audience`, because 78% of
  live pains (67/86) contain no audience token at all, so per-pain audience is
  NOT derivable from text. Where a pain names a subject that conflicts with the
  product audience, the angle is flagged `audience_conflict` for the operator to
  split during snapshot approval. The machine never guesses.
* FAIL-CLOSED: no persona, no pains, or unusable shapes -> empty list. The
  caller then keeps today's behaviour (framework family fallback). This module
  never invents an angle.
* `angle_key` is a stable hash of the NORMALISED pain text, not a slug of it, so
  that Phase B components keyed to an angle survive copy-editing of the pain
  wording. It changes only when the pain genuinely changes.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

__all__ = [
    "derive_angles",
    "angle_keys",
    "AUDIENCE_UNSPECIFIED",
    "MAX_ANGLES",
]

AUDIENCE_UNSPECIFIED = "UNSPECIFIED"

# A persona with more pains than this is almost certainly malformed; cap so a
# bad snapshot cannot explode the rotation axis.
MAX_ANGLES = 12

# Malay/English function words carry no thematic signal for overlap scoring.
_STOPWORDS = frozenset(
    """
    yang dan atau di ke dari untuk pada dengan ini itu adalah akan tidak tak nak
    sebab kerana bila boleh ada jadi lebih sangat semua juga saya anda dia mereka
    kita kami awak nya se para si oleh dalam luar atas bawah antara serta agar
    supaya jika kalau bagi tanpa sudah telah masih pun lagi sahaja hanya cuma
    macam seperti bagai amat terlalu paling kena perlu mesti harus dapat mahu
    ingin rasa jadi buat bikin the a an of to for with and or in on at is are was
    were be been being this that these those it its as by from
    """.split()
)

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Explicit audience subjects that DO appear in pain text. Only used to detect a
# CONFLICT with the product-level audience — never to invent an audience.
_AUDIENCE_TOKENS: dict[str, tuple[str, ...]] = {
    "anak": ("anak", "bayi", "budak", "si kecil"),
    "ibu_bapa": ("ibu", "bapa", "emak", "ayah", "mak", "parent"),
    "wanita": ("wanita", "perempuan", "isteri"),
    "lelaki": ("lelaki", "suami"),
    "warga_emas": ("warga emas", "orang tua", "nenek", "datuk"),
    "pekerja": ("bekerja", "pekerja", "kerja", "office", "pejabat"),
    "pelajar": ("pelajar", "sekolah", "belajar", "student"),
}


def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WS_RE.sub(" ", value).strip()


def _normalize(text: str) -> str:
    """Casefold + strip accents/punctuation + collapse whitespace.

    Used for the stable angle key, so re-capitalising or re-punctuating a pain
    does not orphan the components hanging off its angle.
    """
    folded = unicodedata.normalize("NFKD", _clean(text).casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", folded)).strip()


def _tokens(text: str) -> set[str]:
    return {
        w for w in _normalize(text).split() if len(w) > 2 and w not in _STOPWORDS
    }


def _overlap(a: set[str], b: set[str]) -> float:
    """Jaccard similarity. 0.0 when either side is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _best_match(pain_tokens: set[str], candidates: list[str]) -> tuple[str, float]:
    """Highest-overlap candidate for this pain. ('', 0.0) when nothing overlaps.

    Deliberately NOT index-based: live personas are not index-aligned.
    """
    best, best_score = "", 0.0
    for cand in candidates:
        score = _overlap(pain_tokens, _tokens(cand))
        if score > best_score:
            best, best_score = cand, score
    return best, best_score


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [c for c in (_clean(v) for v in value) if c]


# A pain's SUFFERER is not always the BUYER. A colic pain about `anak` sitting
# under an `ibu_bapa` audience is one coherent use-case (parent buys for child),
# not a conflict. Only genuinely disjoint subjects — e.g. a working-adult ache
# under a parent audience — mean the product spans multiple audiences and needs
# an operator split.
_COMPATIBLE_SUBJECTS: dict[str, frozenset[str]] = {
    "anak": frozenset({"ibu_bapa"}),
    "ibu_bapa": frozenset({"anak"}),
    "warga_emas": frozenset({"ibu_bapa"}),
}


def _is_audience_conflict(pain_subjects: set[str], product_subjects: set[str]) -> bool:
    """True only when the pain names a subject the audience cannot cover."""
    if not pain_subjects or not product_subjects:
        return False  # nothing to compare — never guess
    if pain_subjects & product_subjects:
        return False
    for subject in pain_subjects:
        if _COMPATIBLE_SUBJECTS.get(subject, frozenset()) & product_subjects:
            return False
    return True


def _audience_subjects(text: str) -> set[str]:
    """Audience subjects explicitly named in this text (may be empty)."""
    low = f" {_normalize(text)} "
    found = set()
    for label, needles in _AUDIENCE_TOKENS.items():
        if any(f" {_normalize(n)} " in low or _normalize(n) in low for n in needles):
            found.add(label)
    return found


def _angle_key(pain: str) -> str:
    digest = hashlib.sha256(_normalize(pain).encode("utf-8")).hexdigest()
    return f"ang_{digest[:12]}"


def derive_angles(persona: Any, *, max_angles: int = MAX_ANGLES) -> dict[str, Any]:
    """Persona -> product-specific angles. Pure; never raises on bad input.

    Returns::

        {
          "angles": [
            {
              "angle_key": "ang_1a2b3c4d5e6f",   # stable across re-wording
              "label": str,                       # the pain, human-readable
              "pain": str,
              "desire": str, "fear": str, "trigger": str,   # matched, may be ""
              "audience": str,                    # product-level, or UNSPECIFIED
              "audience_subjects": [str],         # subjects named IN the pain
              "audience_conflict": bool,          # pain subject != product audience
            }, ...
          ],
          "audience": str,
          "derived": bool,          # False -> caller MUST fall back to family
          "warnings": [str],
        }
    """
    warnings: list[str] = []
    if not isinstance(persona, dict) or not persona:
        return {"angles": [], "audience": "", "derived": False,
                "warnings": ["PERSONA_MISSING"]}

    # Some snapshots nest the real persona one level down.
    if not persona.get("pains") and isinstance(persona.get("persona"), dict):
        persona = persona["persona"]
        warnings.append("PERSONA_NESTED_UNWRAPPED")

    pains = _string_list(persona.get("pains"))
    if not pains:
        return {"angles": [], "audience": _clean(persona.get("audience")),
                "derived": False, "warnings": warnings + ["NO_PAINS"]}

    if len(pains) > max_angles:
        warnings.append(f"PAINS_TRUNCATED:{len(pains)}->{max_angles}")
        pains = pains[:max_angles]

    audience = _clean(persona.get("audience")) or AUDIENCE_UNSPECIFIED
    if audience == AUDIENCE_UNSPECIFIED:
        warnings.append("AUDIENCE_MISSING")
    audience_subjects_product = _audience_subjects(audience)

    desires = _string_list(persona.get("desires"))
    fears = _string_list(persona.get("fears"))
    triggers = _string_list(persona.get("triggers"))

    angles: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for pain in pains:
        key = _angle_key(pain)
        if key in seen_keys:  # duplicate pain text in the persona
            warnings.append(f"DUPLICATE_PAIN_SKIPPED:{key}")
            continue
        seen_keys.add(key)

        ptok = _tokens(pain)
        desire, _ = _best_match(ptok, desires)
        fear, _ = _best_match(ptok, fears)
        trigger, _ = _best_match(ptok, triggers)

        subjects = _audience_subjects(pain)
        # A conflict means the pain names a subject the product audience cannot
        # cover: e.g. MWTCB's audience is "Ibu bapa..." but one pain is about
        # working adults. A child's pain under a parent audience is NOT a
        # conflict. Flagged, never auto-resolved.
        conflict = _is_audience_conflict(subjects, audience_subjects_product)
        if conflict:
            warnings.append(f"AUDIENCE_CONFLICT:{key}")

        angles.append({
            "angle_key": key,
            "label": pain,
            "pain": pain,
            "desire": desire,
            "fear": fear,
            "trigger": trigger,
            "audience": audience,
            "audience_subjects": sorted(subjects),
            "audience_conflict": conflict,
        })

    return {
        "angles": angles,
        "audience": audience,
        "derived": bool(angles),
        "warnings": warnings,
    }


def angle_keys(derivation: dict[str, Any]) -> list[str]:
    """Just the stable keys, in order — what the rotation axis consumes."""
    return [a["angle_key"] for a in (derivation or {}).get("angles", [])]
