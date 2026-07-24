"""Compose copy sets from atomic components.

Phase C1 of `.ai/architecture/COPY_ANGLE_AND_COMPONENT_ARCHITECTURE.md`.

This is the CONSUMER of the Phase B1 pool, and therefore the thing that defines
what a component must be. Its output slots mirror `CopySetResponse` exactly
(angle / hook / subhook / usp_set / cta) — which is why the component
vocabulary is HOOK/SUBHOOK/USP_SET/CTA and why there is no `BODY`.

FOUR PROPERTIES, each one load-bearing
--------------------------------------
1. ANGLE-COHERENT. Components only combine inside their own angle. A hook about
   infant colic must never meet a subhook about post-work body aches. Angles are
   alternatives, not factors.
2. DETERMINISTIC. Same pool + same request => same output, always. Mirrors
   `copy_rotation_service`, which is explicitly "repeatable, never random".
   Nothing here calls random() or reads the clock.
3. LRU-FIRST. Components are consumed least-used-first so fatigue spreads
   evenly instead of hammering whichever hook happens to sort first.
4. ANGLE ROUND-ROBIN. Requests are spread ACROSS angles before going deep into
   any one of them. This is the anti-monoculture property built into the engine
   itself: the failure this whole workstream exists to fix was 57 of 58 sets
   landing on one theme, and a composer that drained angle 1 before touching
   angle 2 would reproduce it exactly.

The hook is the fastest-varying digit of the combination odometer, so the first
N compositions differ in the most visible element rather than sharing a hook
and differing only in the CTA.

Composed output is NOT approved copy. It still flows through the existing
dedupe / near-dup / claim gates unchanged — this module only assembles.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

from agent.services.copy_component_service import (
    COMPONENT_TYPES,
    CTA,
    HOOK,
    STATUS_APPROVED,
    SUBHOOK,
    USP_SET,
)

__all__ = ["compose", "combination_fingerprint"]

_GLOBAL_ANGLE = ""
# Odometer digit order: leftmost varies FASTEST.
_SLOT_ORDER = (HOOK, SUBHOOK, USP_SET, CTA)


def combination_fingerprint(component_ids: Iterable[str], formula: str) -> str:
    """Stable identity of one composed copy.

    Order-insensitive over components so the same four parts cannot be
    re-emitted as a 'new' combination by shuffling them.
    """
    basis = "|".join(sorted(str(c) for c in component_ids)) + "#" + str(formula or "")
    return "cc_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _is_live(component: dict[str, Any]) -> bool:
    return (
        not int(component.get("archived") or 0)
        and str(component.get("status") or "") == STATUS_APPROVED
    )


def _lru_key(component: dict[str, Any]) -> tuple:
    """Least-used first, then oldest use, then a total-order tiebreak so the
    ordering is fully determined even when usage is identical."""
    return (
        int(component.get("usage_count") or 0),
        str(component.get("last_used_at") or ""),
        str(component.get("component_id") or ""),
    )


def _pools_for_angle(
    components: Iterable[dict[str, Any]], angle_key: str
) -> dict[str, list[dict[str, Any]]]:
    """Per-type pools for one angle, LRU-sorted, with global components folded
    in (an empty angle_key means 'applies to every angle' — how CTAs behave)."""
    pools: dict[str, list[dict[str, Any]]] = {t: [] for t in COMPONENT_TYPES}
    for c in components:
        if not _is_live(c):
            continue
        ctype = str(c.get("component_type") or "")
        if ctype not in pools:
            continue
        akey = str(c.get("angle_key") or _GLOBAL_ANGLE)
        if akey in (angle_key, _GLOBAL_ANGLE):
            pools[ctype].append(c)
    for ctype in pools:
        pools[ctype].sort(key=_lru_key)
    return pools


def _usp_value(component: dict[str, Any]) -> list[str]:
    """USP_SET content is a JSON array; tolerate a plain string too."""
    import json

    raw = component.get("content")
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    text = str(raw or "").strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:  # noqa: BLE001
            pass
    return [text] if text else []


def compose(
    components: Iterable[dict[str, Any]],
    angles: list[dict[str, Any]],
    count: int,
    *,
    formula_families: list[str] | None = None,
    exclude_fingerprints: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Assemble up to `count` distinct copy sets from the pool.

    `angles` are the Phase A records ({'angle_key', 'label', ...}); their ORDER
    is the round-robin order.

    Never raises and never pads: if the pool cannot supply `count` distinct
    combinations it returns what it can plus a `shortfall`, because silently
    emitting duplicates is exactly the monoculture this workstream is fixing.
    """
    components = list(components or [])
    angles = [a for a in (angles or []) if a and a.get("angle_key")]
    formulas = [f for f in (formula_families or []) if str(f).strip()] or [""]
    want = max(0, int(count or 0))
    seen: set[str] = {str(f) for f in (exclude_fingerprints or [])}

    if not want or not angles:
        return {
            "items": [], "requested": want, "produced": 0, "shortfall": want,
            "blocked_angles": [a["angle_key"] for a in angles], "warnings": [],
        }

    warnings: list[str] = []
    per_angle: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for angle in angles:
        akey = str(angle["angle_key"])
        pools = _pools_for_angle(components, akey)
        missing = [t for t in COMPONENT_TYPES if not pools[t]]
        if missing:
            blocked.append(akey)
            warnings.append(f"ANGLE_BLOCKED:{akey}:missing={','.join(missing)}")
            continue
        per_angle[akey] = {"angle": angle, "pools": pools, "cursor": 0}

    items: list[dict[str, Any]] = []
    live = [a for a in angles if str(a["angle_key"]) in per_angle]
    exhausted: set[str] = set()

    # Round-robin across angles; within an angle walk the odometer with HOOK as
    # the fastest-varying digit.
    while len(items) < want and len(exhausted) < len(live):
        progressed = False
        for angle in live:
            if len(items) >= want:
                break
            akey = str(angle["angle_key"])
            if akey in exhausted:
                continue
            state = per_angle[akey]
            pools = state["pools"]
            sizes = [len(pools[t]) for t in _SLOT_ORDER]
            total = 1
            for s in sizes:
                total *= s
            total *= len(formulas)

            picked = None
            while state["cursor"] < total:
                k = state["cursor"]
                state["cursor"] += 1
                rem = k
                chosen: dict[str, Any] = {}
                for slot, size in zip(_SLOT_ORDER, sizes):
                    chosen[slot] = pools[slot][rem % size]
                    rem //= size
                formula = formulas[rem % len(formulas)]
                ids = [str(chosen[s].get("component_id") or "") for s in _SLOT_ORDER]
                fp = combination_fingerprint(ids, formula)
                if fp in seen:
                    continue
                seen.add(fp)
                picked = (chosen, formula, ids, fp)
                break

            if picked is None:
                exhausted.add(akey)
                continue

            chosen, formula, ids, fp = picked
            items.append({
                "angle_key": akey,
                "angle": str(angle.get("label") or angle.get("angle_label") or ""),
                "hook": str(chosen[HOOK].get("content") or ""),
                "subhook": str(chosen[SUBHOOK].get("content") or ""),
                "usp_set": _usp_value(chosen[USP_SET]),
                "cta": str(chosen[CTA].get("content") or ""),
                "formula_family": formula,
                "component_ids": ids,
                "combination_fingerprint": fp,
            })
            progressed = True
        if not progressed:
            break

    if blocked:
        warnings.append(f"BLOCKED_ANGLE_COUNT:{len(blocked)}")

    return {
        "items": items,
        "requested": want,
        "produced": len(items),
        "shortfall": max(0, want - len(items)),
        "blocked_angles": blocked,
        "warnings": warnings,
    }
