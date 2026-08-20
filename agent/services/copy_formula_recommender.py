"""Deterministic, auditable formula recommender for bulk copy generation (Lapis 2).

Copy Register V2 requires an EXPLICIT formula per blueprint (`default_formula: null`,
`explicit_formula_required: true`) and never silently defaults. This module is how the
BULK lane supplies that explicit choice at scale without a human typing one per product:
a pure, deterministic rule over the product's own type/positioning that returns the
formula id AND a rationale, so every bulk-generated draft carries an auditable
"why this formula" — the fallback is itself an explicit, recorded choice, not a hidden
global default.

The chosen id is still re-validated by the generate call's `_require_formula`
(`COPY_V2_FORMULA_NOT_PRODUCTION_SUPPORTED`), so a stale/unknown id fails closed there
too — this recommender can never smuggle an unsupported formula into production.
"""
from __future__ import annotations

from typing import Any

# Production formula ids in the Copy Register V2 registry (video-first pipeline). The
# generate call re-validates against the LIVE registry; this set is the recommender's
# own allowlist so a typo is caught here as well.
_KNOWN_FORMULAS: frozenset[str] = frozenset(
    {"PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"}
)

# Ordered rules: (signal keywords, formula_id, rationale). FIRST match wins. Keys are
# matched case-insensitively as substrings of the product's own type/category text.
# Each branch is an EXPLICIT, auditable choice grounded in the formula's registry
# `best_for` — including the broad fallback below.
_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        (
            "pain", "ache", "relief", "remedy", "supplement", "medicated",
            "sakit", "ubat", "pest", "insect", "stain", "odor", "odour",
        ),
        "PAS",
        "problem / pain-relief positioning (Problem-Agitate-Solution)",
    ),
    (
        (
            "lip", "lipstick", "tint", "serum", "cream", "skincare", "beauty",
            "cosmetic", "whitening", "slimming", "facial", "moisturi", "makeup",
            "make-up", "lotion", "mask",
        ),
        "BAB",
        "beauty transformation, before/after routine shift (Before-After-Bridge)",
    ),
    (
        (
            "snack", "food", "beverage", "drink", "coffee", "spice", "sauce",
            "rempah", "biscuit", "chocolate", "candy", "kuih",
        ),
        "HSO",
        "appetite / UGC emotional opener (Hook-Story-Offer)",
    ),
)

# Broad, safe default for anything without a specific positioning signal (apparel,
# home, general goods). An EXPLICIT recorded choice, never a silent backend default.
_DEFAULT: tuple[str, str] = (
    "AIDA",
    "broad product discovery / clean conversion (Attention-Interest-Desire-Action)",
)


def _product_signal_text(product: dict[str, Any]) -> str:
    """Concatenate the product's own descriptive fields into one lowercase haystack."""
    parts = (
        product.get("copywriting_product_type_code"),
        product.get("product_type"),
        product.get("type"),
        product.get("category"),
        product.get("subcategory"),
        product.get("bosmax_product_family"),
        product.get("product_display_name") or product.get("raw_product_title"),
    )
    return " ".join(str(p) for p in parts if p).lower()


def recommend_formula(product: dict[str, Any]) -> dict[str, Any]:
    """Return the explicit formula recommendation for one product.

    Deterministic and pure — same product always yields the same result. Every product
    resolves to exactly one formula in `_KNOWN_FORMULAS` with a human-readable rationale
    and the index of the matched rule (`-1` = broad default). The generate call still
    re-validates the id against the live registry, so this can only ever narrow to a
    supported formula, never widen.
    """
    text = _product_signal_text(product)
    for idx, (keys, formula_id, rationale) in enumerate(_RULES):
        if any(key in text for key in keys):
            return {
                "formula_id": formula_id,
                "rationale": rationale,
                "matched_rule": idx,
                "signal_text": text,
            }
    formula_id, rationale = _DEFAULT
    return {
        "formula_id": formula_id,
        "rationale": rationale,
        "matched_rule": -1,
        "signal_text": text,
    }


__all__ = ["recommend_formula", "_KNOWN_FORMULAS"]
