"""Authoritative per-product scene-strategy contract evaluator.

Every product carries ONE `matched_scene_strategy_id` in the strategy-taxonomy sidecar.
That id resolves to an entry in the scene-strategy library which holds the actual grammar:
the allowed scene variants, allowed actions, scene contexts and camera routes. Operations
reporting previously selected neither the id nor its coverage, so a product with no usable
scene grammar looked identical to a fully-covered one.

There is deliberately NO minimum-variant threshold. A sensitive product may legitimately
have exactly one safe concrete scene; `PET_CAGE_ACCESSORY` is exactly that. A contract is
complete when it is concrete and usable, not when it is numerous.

A product has a COMPLETE scene contract when ALL of the following hold:
  * `matched_scene_strategy_id` is non-empty;
  * that id exists in the scene-strategy library;
  * it is not the generic fallback;
  * `scene_coverage_status` is COVERED;
  * `fallback_used` is false;
  * `allowed_scene_strategy`, `allowed_actions`, `scene_contexts` and `camera_routes`
    each contain at least one entry.

`scene_variants_count` is exactly `len(entry["allowed_scene_strategy"])` — the number of
scene variants inside the ONE matched strategy. It is not a count of strategies.
"""
from __future__ import annotations

from typing import Any, Mapping

from agent.services.scene_strategy_library import SCENE_STRATEGIES

GENERIC_FALLBACK_ID = "GENERIC_FALLBACK"

# The four arrays a usable scene grammar must provide.
REQUIRED_ARRAYS: tuple[tuple[str, str], ...] = (
    ("allowed_scene_strategy", "EMPTY_SCENE_VARIANTS"),
    ("allowed_actions", "EMPTY_ACTIONS"),
    ("scene_contexts", "EMPTY_CONTEXTS"),
    ("camera_routes", "EMPTY_CAMERA_ROUTES"),
)

GAP_NO_BINDING = "NO_STRATEGY_BINDING"
GAP_NOT_IN_LIBRARY = "STRATEGY_ID_NOT_IN_LIBRARY"
GAP_GENERIC_FALLBACK = "GENERIC_FALLBACK"
GAP_PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
GAP_STALE_FINGERPRINT = "STALE_PRODUCT_FINGERPRINT"

STATUS_COMPLETE = "COMPLETE"
STATUS_GAP = "GAP"


def _entry(strategy_id: str) -> Mapping[str, Any] | None:
    entry = SCENE_STRATEGIES.get(strategy_id)
    if entry is None:
        return None
    if isinstance(entry, Mapping):
        return entry
    return getattr(entry, "_asdict", lambda: vars(entry))()


def library_strategy_is_usable(strategy_id: str) -> bool:
    """True when the library entry itself provides every required array."""
    entry = _entry(strategy_id)
    if entry is None:
        return False
    return all(entry.get(field) for field, _reason in REQUIRED_ARRAYS)


def scene_variants_count(strategy_id: str) -> int:
    entry = _entry(strategy_id)
    if entry is None:
        return 0
    return len(entry.get("allowed_scene_strategy") or ())


# Ids whose library grammar is complete. Precomputed because the library is static, which
# lets the reporting layer express "scene gap" as a SQL predicate over an id allowlist
# instead of loading every product into Python to count a KPI card.
COMPLETE_SCENE_STRATEGY_IDS: frozenset[str] = frozenset(
    sid for sid in SCENE_STRATEGIES
    if sid != GENERIC_FALLBACK_ID and library_strategy_is_usable(sid)
)


def evaluate_scene_contract(
    taxonomy: Mapping[str, Any] | None,
    *,
    fingerprint_stale: bool = False,
) -> dict[str, Any]:
    """Pure evaluation of one product's scene contract. Reads nothing, writes nothing."""
    strategy_id = str((taxonomy or {}).get("matched_scene_strategy_id") or "").strip()
    coverage = str((taxonomy or {}).get("scene_coverage_status") or "").strip()
    fallback_used = bool((taxonomy or {}).get("fallback_used"))

    reasons: list[str] = []
    if not strategy_id:
        reasons.append(GAP_NO_BINDING)
    elif strategy_id == GENERIC_FALLBACK_ID:
        reasons.append(GAP_GENERIC_FALLBACK)
    elif _entry(strategy_id) is None:
        reasons.append(GAP_NOT_IN_LIBRARY)
    else:
        entry = _entry(strategy_id) or {}
        for field, reason in REQUIRED_ARRAYS:
            if not entry.get(field):
                reasons.append(reason)

    if fallback_used and GAP_GENERIC_FALLBACK not in reasons:
        reasons.append(GAP_GENERIC_FALLBACK)
    if coverage and coverage != "COVERED":
        reasons.append(GAP_PARTIAL_COVERAGE)
    elif not coverage and GAP_NO_BINDING not in reasons:
        reasons.append(GAP_PARTIAL_COVERAGE)
    if fingerprint_stale:
        reasons.append(GAP_STALE_FINGERPRINT)

    # preserve first-seen order without duplicates
    ordered = list(dict.fromkeys(reasons))
    return {
        "scene_strategy_id": strategy_id or None,
        "scene_variants_count": scene_variants_count(strategy_id) if strategy_id else 0,
        "scene_coverage": coverage or None,
        "scene_contract_status": STATUS_GAP if ordered else STATUS_COMPLETE,
        "scene_gap_reasons": ordered,
    }


def scene_gap_sql_predicate(alias: str = "t") -> str:
    """SQL mirror of the STRUCTURAL half of `evaluate_scene_contract`.

    Covers everything decidable from stored columns plus the precomputed library
    allowlist: missing binding, unknown id, generic fallback, fallback_used, non-COVERED
    coverage and library entries with an empty required array (such ids are simply absent
    from the allowlist).

    `STALE_PRODUCT_FINGERPRINT` is intentionally NOT in this predicate: deciding it needs
    the product fingerprint recomputed per row, which cannot run inside a COUNT over the
    whole catalogue. Staleness is still reported per row by `evaluate_scene_contract`, and
    is separately counted by the existing strategy-taxonomy stale reporting.
    """
    ids = ", ".join("'" + sid.replace("'", "''") + "'"
                    for sid in sorted(COMPLETE_SCENE_STRATEGY_IDS))
    if not ids:  # defensive: an empty library means every product is a gap
        return "1=1"
    return (
        f"({alias}.matched_scene_strategy_id IS NULL"
        f" OR TRIM({alias}.matched_scene_strategy_id) = ''"
        f" OR {alias}.matched_scene_strategy_id NOT IN ({ids})"
        f" OR COALESCE({alias}.scene_coverage_status, '') <> 'COVERED'"
        f" OR COALESCE({alias}.fallback_used, 0) = 1)"
    )
