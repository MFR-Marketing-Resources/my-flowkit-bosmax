"""Copy Formula Registry — the slot contracts for BOSMAX formula-driven copy.

Formulas are NOT free-text labels. Each formula is a structured contract:
ordered required slots, slot purposes, best/unsuitable use cases, an output
mapping (slot -> angle/hook/subhook/USP/CTA), and validation rules. Copy is
generated FROM these slots, then validated against them.

The 6 canonical formulas are transcribed FAITHFULLY from the (previously unused)
`formula_library` in agent/authority/COPYWRITING_FRAMEWORK_UNIVERSAL.yaml
(lines 226-286). SavagePAS and HPAS existed only as string labels in
copy_family_grounding.py (e.g. "SAVAGE_HPAS") with no definition, so they are
registered here with EXPLICIT operator-review-draft slots — never pretending a
canonical contract exists.

`compiler_family` maps every formula onto the 6 families the canonical prompt
compiler whitelists (PAS/AIDA/HSO/BAB/PASTOR/PESTA); anything else silently
downgrades to HSO in normalize_copy_intelligence. So SavagePAS/HPAS carry their
true `formula_id` in the copy-set breakdown while presenting a compiler-safe
family to the deterministic compiler.
"""
from __future__ import annotations

from typing import Any

DEFINITION_CANONICAL = "CANONICAL"
DEFINITION_OPERATOR_REVIEW_DRAFT = "OPERATOR_REVIEW_DRAFT"

# Copy fields the generator/compiler ultimately consumes.
COPY_FIELDS = ("angle", "hook", "subhook", "usp", "cta")


def _slot(slot_id: str, purpose: str, required: bool = True) -> dict[str, Any]:
    return {"slot_id": slot_id, "purpose": purpose, "required": required}


# ── Canonical formulas (source: COPYWRITING_FRAMEWORK_UNIVERSAL.yaml) ─────────

_PAS = {
    "formula_id": "PAS",
    "display_name": "Problem · Agitate · Solution",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "PAS",
    "slots": [
        _slot("problem", "Name the buyer's real problem in their own market language."),
        _slot("agitate", "Twist the knife — the cost/annoyance of leaving it unsolved."),
        _slot("solution", "Position the product (grounded facts) as the relief."),
        _slot("cta", "One concrete next action tied to the buyer situation."),
    ],
    "best_for": ["frustration", "urgency", "pain_relief_positioning"],
    "unsuitable_for": ["pure_brand_awareness", "no_clear_problem"],
    "output_mapping": {
        "angle": "problem",
        "hook": "problem",
        "subhook": "agitate",
        "usp": ["solution"],
        "cta": "cta",
    },
}

_AIDA = {
    "formula_id": "AIDA",
    "display_name": "Attention · Interest · Desire · Action",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "AIDA",
    "slots": [
        _slot("attention", "Grab attention in the first 3 seconds."),
        _slot("interest", "Build interest with a relevant angle/benefit."),
        _slot("desire", "Bridge to desire — why THIS buyer wants it now."),
        _slot("action", "Direct, low-friction action."),
    ],
    "best_for": ["product_discovery", "clean_conversion", "broad_market_entries"],
    "unsuitable_for": ["heavy_emotional_problem_stories"],
    "output_mapping": {
        "angle": "desire",
        "hook": "attention",
        "subhook": "interest",
        "usp": ["desire"],
        "cta": "action",
    },
}

_HSO = {
    "formula_id": "HSO",
    "display_name": "Hook · Story · Offer",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "HSO",
    "slots": [
        _slot("hook", "Scroll-stopping opener rooted in the avatar."),
        _slot("story", "A short relatable situation the buyer lives."),
        _slot("offer", "The product as the offer/resolution (grounded)."),
    ],
    "best_for": ["UGC", "short_video_dialogue", "emotional_openers"],
    "unsuitable_for": ["dry_spec_comparison"],
    "output_mapping": {
        "angle": "hook",
        "hook": "hook",
        "subhook": "story",
        "usp": ["offer"],
        "cta": "offer",
    },
}

_BAB = {
    "formula_id": "BAB",
    "display_name": "Before · After · Bridge",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "BAB",
    "slots": [
        _slot("before", "The buyer's current painful/annoying state."),
        _slot("after", "The desired state once the problem is gone."),
        _slot("bridge", "The product as the bridge from before to after."),
    ],
    "best_for": ["transformation", "routine_shift"],
    "unsuitable_for": ["no_visible_transformation"],
    "output_mapping": {
        "angle": "after",
        "hook": "before",
        "subhook": "after",
        "usp": ["bridge"],
        "cta": "bridge",
    },
}

_PASTOR = {
    "formula_id": "PASTOR",
    "display_name": "Problem · Amplify · Story · Transformation · Offer · Response",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "PASTOR",
    "slots": [
        _slot("problem", "The buyer problem in market language."),
        _slot("amplify", "Amplify the stakes/emotion."),
        _slot("story", "Relatable proof-by-story (no fabricated testimonial)."),
        _slot("transformation", "The believable change the buyer gets."),
        _slot("offer", "The grounded product offer."),
        _slot("response", "The response/CTA to act now."),
    ],
    "best_for": ["more_persuasive_long_form_variants"],
    "unsuitable_for": ["ultra_short_hook_only"],
    "output_mapping": {
        "angle": "transformation",
        "hook": "problem",
        "subhook": "amplify",
        "usp": ["story", "transformation", "offer"],
        "cta": "response",
    },
}

_PESTA = {
    "formula_id": "PESTA",
    "display_name": "Pain · Emotion · Solution · Transformation · Action",
    "definition_status": DEFINITION_CANONICAL,
    "compiler_family": "PESTA",
    "slots": [
        _slot("pain", "The buyer's pain in market language."),
        _slot("emotion", "The emotional weight of that pain."),
        _slot("solution", "The grounded product solution."),
        _slot("transformation", "The believable improvement."),
        _slot("action", "The action to take now."),
    ],
    "best_for": ["high_emotion_social_copy", "stealth_pressure_lanes"],
    "unsuitable_for": ["flat_utility_products"],
    "output_mapping": {
        "angle": "emotion",
        "hook": "pain",
        "subhook": "emotion",
        "usp": ["solution", "transformation"],
        "cta": "action",
    },
}

# ── Operator-review-draft formulas (no canonical def existed in-repo) ─────────

_SAVAGE_PAS = {
    "formula_id": "SavagePAS",
    "display_name": "Savage PAS (bold call-out) — DRAFT",
    "definition_status": DEFINITION_OPERATOR_REVIEW_DRAFT,
    "compiler_family": "PAS",  # savage variant of PAS ordering for the compiler
    "slots": [
        _slot("problem", "Name the problem bluntly in market language."),
        _slot("savage_agitate", "Bold, provocative call-out of the cost of inaction (still claim-safe)."),
        _slot("solution", "The grounded product as the direct fix."),
        _slot("cta", "Blunt, confident CTA."),
    ],
    "best_for": ["bold_tiktok_hooks", "pattern_interrupt"],
    "unsuitable_for": ["conservative_brands", "highly_regulated_medical"],
    "output_mapping": {
        "angle": "problem",
        "hook": "problem",
        "subhook": "savage_agitate",
        "usp": ["solution"],
        "cta": "cta",
    },
}

_HPAS = {
    "formula_id": "HPAS",
    "display_name": "Hook + PAS (hook-first PAS) — DRAFT",
    "definition_status": DEFINITION_OPERATOR_REVIEW_DRAFT,
    "compiler_family": "PAS",
    "slots": [
        _slot("hook", "Scroll-stopping hook before the problem."),
        _slot("problem", "The buyer problem in market language."),
        _slot("agitate", "Agitate the cost of leaving it."),
        _slot("solution", "The grounded product solution."),
        _slot("cta", "Concrete CTA."),
    ],
    "best_for": ["hook_first_surfaces", "short_video_dialogue"],
    "unsuitable_for": ["long_form_narrative"],
    "output_mapping": {
        "angle": "problem",
        "hook": "hook",
        "subhook": "agitate",
        "usp": ["solution"],
        "cta": "cta",
    },
}

FORMULA_REGISTRY: dict[str, dict[str, Any]] = {
    f["formula_id"]: f
    for f in (_PAS, _AIDA, _HSO, _BAB, _PASTOR, _PESTA, _SAVAGE_PAS, _HPAS)
}

# Case-insensitive + common-alias resolution (e.g. "SAVAGE_HPAS", "savage pas").
_ALIASES = {
    "SAVAGE_PAS": "SavagePAS",
    "SAVAGEPAS": "SavagePAS",
    "SAVAGE_HPAS": "HPAS",
    "H_PAS": "HPAS",
    "HOOK_PAS": "HPAS",
}


def normalize_formula_id(value: Any) -> str:
    """Resolve a free-text formula label (from copy_family_grounding, a landbank
    row, or an operator field) to a canonical registry id. Falls back to HSO —
    the same compiler-safe default the rest of the system uses."""
    token = str(value or "").strip()
    if not token:
        return "HSO"
    # A grounding string can be "PAS / HSO / AIDA (STEALTH silo)" — take the first.
    first = token.replace("/", " ").split()[0] if token else ""
    for candidate in (token, first):
        key = candidate.upper().replace(" ", "_")
        if candidate in FORMULA_REGISTRY:
            return candidate
        if key in _ALIASES:
            return _ALIASES[key]
        for fid in FORMULA_REGISTRY:
            if fid.upper() == key:
                return fid
    return "HSO"


def get_formula(formula_id: Any) -> dict[str, Any]:
    """Return the resolved formula contract (never raises; falls back to HSO)."""
    return FORMULA_REGISTRY[normalize_formula_id(formula_id)]


def list_formulas() -> list[dict[str, Any]]:
    return list(FORMULA_REGISTRY.values())


def required_slot_ids(formula_id: Any) -> list[str]:
    return [s["slot_id"] for s in get_formula(formula_id)["slots"] if s.get("required")]


def compiler_family_for(formula_id: Any) -> str:
    return get_formula(formula_id)["compiler_family"]


def recommend_formula(
    *, is_stealth: bool = False, family: str = "", claim_posture: str = ""
) -> str:
    """Recommend a starting formula from grounding signals (selection_rules:
    PAS/HSO/AIDA first for short-form; stealth pressure -> PESTA/PAS).
    Deterministic — the operator can always override."""
    if is_stealth or "SENSITIVE" in (family or "").upper():
        return "PESTA"  # high-emotion / stealth pressure lane
    return "PAS"  # safe, problem-first default for short-form video
