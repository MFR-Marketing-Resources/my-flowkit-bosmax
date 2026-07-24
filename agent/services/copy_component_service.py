"""Atomic copy components — capacity math for the composed-copy pool.

Phase B1 of `.ai/architecture/COPY_ANGLE_AND_COMPONENT_ARCHITECTURE.md`.

WHY
---
`copy_set` stores a FROZEN bundle, so producing N variations costs N LLM calls
and diversity collapses as N grows (measured on MWTCB: 58 sets, subhook 58/58
distinct = zero component reuse, ~90% of sets on a single theme). Components
make capacity MULTIPLICATIVE instead of linear:

    total = formulas x SUM over angles of ( hooks x subhooks x usp_sets x ctas )

so ~73 authored pieces yield ~19,200 valid combinations rather than 19,200
provider calls.

COMPOSITION IS ANGLE-COHERENT
-----------------------------
A hook about infant colic must never pair with a body about post-work body
aches. Components therefore carry the Phase A `angle_key` and only combine
within their angle. The ONE exception is a component with an EMPTY angle_key,
which means "applies to every angle of this product" — how CTAs normally
behave. Those count toward every angle's pool.

This module is PURE (no DB, no I/O, no LLM) so the capacity contract is cheap
to test and impossible to make non-deterministic.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable

__all__ = [
    "HOOK",
    "SUBHOOK",
    "USP_SET",
    "CTA",
    "COMPONENT_TYPES",
    "REQUIRED_TYPES",
    "STATUS_APPROVED",
    "make_dedupe_key",
    "pool_capacity",
]

# The component vocabulary MIRRORS the consumer's slots exactly. A composed
# copy has to satisfy CopySetResponse (angle, hook, subhook, usp_set, cta), and
# there is NO `body` field there — an earlier draft of this module used BODY,
# which mapped to nothing and would have made every authored BODY component
# (and the tokens spent on it) useless. `angle` is deliberately absent here: it
# is not a component, it is the Phase A key components are grouped BY.
HOOK = "HOOK"
SUBHOOK = "SUBHOOK"
USP_SET = "USP_SET"
CTA = "CTA"

COMPONENT_TYPES = (HOOK, SUBHOOK, USP_SET, CTA)
# Every one of these must be non-empty for an angle to produce anything at all;
# a single missing type zeroes that angle's whole product.
REQUIRED_TYPES = COMPONENT_TYPES

STATUS_APPROVED = "COMPONENT_APPROVED"

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")

# Applies-to-every-angle marker (stored as the empty string).
_GLOBAL_ANGLE = ""


def _normalize(text: Any) -> str:
    """Casefold + strip accents/punctuation + collapse whitespace."""
    raw = text if isinstance(text, str) else str(text or "")
    folded = unicodedata.normalize("NFKD", raw.casefold())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return _WS_RE.sub(" ", _PUNCT_RE.sub(" ", folded)).strip()


def make_dedupe_key(content: Any) -> str:
    """Stable identity for a component's TEXT.

    Backs the UNIQUE(product_id, component_type, dedupe_key) index, so the same
    hook cannot enter a product's pool twice under different casing or
    punctuation — the exact failure mode that let 58 near-identical copy sets
    all pass the old per-set dedupe.
    """
    return "cmp_" + hashlib.sha256(_normalize(content).encode("utf-8")).hexdigest()[:16]


def _is_live(component: dict[str, Any]) -> bool:
    if int(component.get("archived") or 0):
        return False
    return str(component.get("status") or "") == STATUS_APPROVED


def _counts_by_angle(
    components: Iterable[dict[str, Any]], angle_keys: list[str]
) -> dict[str, dict[str, int]]:
    """(angle_key -> component_type -> count), with global components folded in."""
    counts: dict[str, dict[str, int]] = {
        a: dict.fromkeys(COMPONENT_TYPES, 0) for a in angle_keys
    }
    globals_: dict[str, int] = dict.fromkeys(COMPONENT_TYPES, 0)

    for c in components:
        if not _is_live(c):
            continue
        ctype = str(c.get("component_type") or "")
        if ctype not in COMPONENT_TYPES:
            continue
        akey = str(c.get("angle_key") or _GLOBAL_ANGLE)
        if akey == _GLOBAL_ANGLE:
            globals_[ctype] += 1
        elif akey in counts:
            counts[akey][ctype] += 1

    for angle in counts:
        for ctype in COMPONENT_TYPES:
            counts[angle][ctype] += globals_[ctype]
    return counts


def pool_capacity(
    components: Iterable[dict[str, Any]],
    angle_keys: list[str],
    *,
    formula_count: int = 1,
) -> dict[str, Any]:
    """How many distinct copies this pool can compose, and what blocks more.

    Only APPROVED, non-archived components count — an unreviewed component can
    never reach a composed copy, so counting it would overstate capacity.

    Capacity is COMPONENT-BOUND: per angle, hooks x subhooks x usp_sets x ctas,
    summed over angles. Formula is deliberately NOT a multiplier. The composer
    does not use the formula to change any text (hook/subhook/usp/cta all come
    from components), so the same components under a different formula are the
    SAME copy and the text-based dedupe collapses them; counting `formula_count`
    here would overstate real unique capacity by that factor. The parameter is
    retained for call-site compatibility and echoed back, but never multiplies.

    Returns per-angle capacity, the total, the empty slots blocking each angle,
    and `next_best` — the single component type whose next addition unlocks the
    most new combinations. That last field is the actionable one: it tells the
    operator exactly what to author next instead of guessing.
    """
    angle_keys = [a for a in (angle_keys or []) if a]
    formula_count = max(1, int(formula_count or 1))
    counts = _counts_by_angle(components, angle_keys)

    per_angle: list[dict[str, Any]] = []
    total = 0
    for angle in angle_keys:
        c = counts[angle]
        missing = [t for t in REQUIRED_TYPES if c[t] == 0]
        combos = 0 if missing else c[HOOK] * c[SUBHOOK] * c[USP_SET] * c[CTA]
        total += combos

        # Marginal gain of one more component of each type, for THIS angle.
        gains: dict[str, int] = {}
        for t in COMPONENT_TYPES:
            bumped = dict(c)
            bumped[t] = c[t] + 1
            if any(bumped[x] == 0 for x in REQUIRED_TYPES):
                gains[t] = 0
            else:
                gains[t] = (
                    bumped[HOOK] * bumped[SUBHOOK] * bumped[USP_SET] * bumped[CTA]
                ) - combos

        per_angle.append({
            "angle_key": angle,
            "counts": dict(c),
            "missing_types": missing,
            "combinations": combos,
            "marginal_gain": gains,
            "next_best_type": max(gains, key=lambda k: gains[k]) if gains else None,
        })

    blocked = [a["angle_key"] for a in per_angle if a["missing_types"]]
    best = max(per_angle, key=lambda a: max(a["marginal_gain"].values(), default=0),
               default=None) if per_angle else None

    return {
        "total_combinations": total,
        "formula_count": formula_count,
        "angle_count": len(angle_keys),
        "per_angle": per_angle,
        "blocked_angles": blocked,
        "next_best": (
            {"angle_key": best["angle_key"], "component_type": best["next_best_type"],
             "unlocks": best["marginal_gain"].get(best["next_best_type"], 0)}
            if best and best["next_best_type"] else None
        ),
    }
