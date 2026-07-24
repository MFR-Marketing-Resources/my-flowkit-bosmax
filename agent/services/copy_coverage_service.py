"""Angle coverage gate — Phase C2.

THE CONTROL THAT DID NOT EXIST
------------------------------
Every gate in the copy lane measures *sameness*: `dedupe_key` catches identical
text, SCAN NEAR-DUP catches near-identical text, `content_combination` catches a
repeated script x avatar x scene. Not one of them measures *spread*.

That is why the live failure was invisible to the whole system: 57 of 58 MWTCB
copy sets were about one theme (`anak` + `perut kembung`) while three of the
product's four real use-cases were nearly absent (sengal 13/58, gigitan 4/58).
Every one of those 58 was "unique" and passed every existing check.

    Uniqueness != Diversity.

This module supplies the missing half. It is PURE (no I/O, no DB, no LLM).

WHAT IT MEASURES
----------------
Items are counted per `angle_key` (Phase A). Coverage is judged on two axes,
because either one alone can be gamed:

* CONCENTRATION — the largest angle's share of the batch. One angle owning most
  of the output is monoculture even if every angle is technically present.
* BREADTH — how many of the AVAILABLE angles appear at all. A perfectly even
  split across 2 of 5 angles still ignores three real use-cases.

Verdicts are advisory by default (`COVERAGE_SKEWED`) and only escalate to
`COVERAGE_MONOCULTURE` when concentration is severe, so this can be surfaced in
the UI without blocking an operator who genuinely wants a single-angle batch.
`blocking=True` turns the same measurement into a hard gate.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

__all__ = [
    "evaluate_coverage",
    "STATUS_OK",
    "STATUS_SKEWED",
    "STATUS_MONOCULTURE",
    "DEFAULT_MAX_SHARE",
    "MONOCULTURE_SHARE",
]

STATUS_OK = "COVERAGE_OK"
STATUS_SKEWED = "COVERAGE_SKEWED"
STATUS_MONOCULTURE = "COVERAGE_MONOCULTURE"

# Thresholds are RELATIVE to the even split (1/n), not absolute, because an
# absolute bar is wrong for small angle counts: with 2 angles the dominant share
# can never drop below 0.50, so a fixed 0.35 bar would flag every 2-angle batch
# as skewed — a permanent false alarm. Multipliers are applied to the even share
# and capped so a large angle count cannot make the bar meaninglessly low.
SKEW_FACTOR = 1.4
MONOCULTURE_FACTOR = 2.4
SKEW_CAP = 0.60
MONOCULTURE_CAP = 0.90

# Kept for callers that want the 4-angle reference points (MWTCB's shape):
# even 0.25 -> skewed above 0.35, monoculture above 0.60. The live failure was
# 0.98.
DEFAULT_MAX_SHARE = 0.35
MONOCULTURE_SHARE = 0.60


def _thresholds(
    angle_count: int, max_share: float | None, monoculture_share: float | None
) -> tuple[float, float]:
    """(skew, monoculture) bars for this many angles. Explicit values win."""
    even = 1.0 / angle_count if angle_count > 0 else 1.0
    skew = float(max_share) if max_share is not None else min(SKEW_CAP, even * SKEW_FACTOR)
    mono = (
        float(monoculture_share)
        if monoculture_share is not None
        else min(MONOCULTURE_CAP, even * MONOCULTURE_FACTOR)
    )
    # The two bars must never invert: raising the skew bar explicitly widens
    # what counts as acceptable concentration, so monoculture cannot fire
    # underneath it.
    return skew, max(mono, skew)


def _angle_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("angle_key") or "").strip()
    return str(getattr(item, "angle_key", "") or "").strip()


def evaluate_coverage(
    items: Iterable[Any],
    angle_keys: Iterable[str] | None = None,
    *,
    max_share: float | None = None,
    monoculture_share: float | None = None,
    labels: dict[str, str] | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    """Measure angle spread over a batch.

    `angle_keys` is the set of angles that WERE available. Supplying it is what
    makes "three use-cases never appeared" visible; without it only the angles
    actually present can be judged, which is exactly the blind spot being fixed.

    Returns a report; `blocked` is only ever True when `blocking=True`.
    """
    items = list(items or [])
    labels = labels or {}
    available = [a for a in (angle_keys or []) if str(a).strip()]

    counts = Counter(a for a in (_angle_of(i) for i in items) if a)
    unattributed = len(items) - sum(counts.values())
    total = sum(counts.values())

    universe = list(dict.fromkeys(available + list(counts)))
    per_angle = [
        {
            "angle_key": key,
            "angle_label": labels.get(key, ""),
            "count": counts.get(key, 0),
            "share": round(counts.get(key, 0) / total, 4) if total else 0.0,
        }
        for key in universe
    ]
    per_angle.sort(key=lambda e: (-e["count"], e["angle_key"]))

    missing = [e["angle_key"] for e in per_angle if e["count"] == 0]
    covered = len(universe) - len(missing)

    dominant = per_angle[0] if per_angle and total else None
    dominant_share = dominant["share"] if dominant else 0.0

    skew_bar, mono_bar = _thresholds(len(universe), max_share, monoculture_share)
    max_share, monoculture_share = skew_bar, mono_bar

    warnings: list[str] = []
    status = STATUS_OK
    # A single available angle cannot be a monoculture — there is nothing to
    # spread across, so concentration carries no information.
    multi = len(universe) > 1
    if total and multi:
        if dominant_share >= monoculture_share:
            status = STATUS_MONOCULTURE
            warnings.append(
                f"ANGLE_MONOCULTURE:{dominant['angle_key']}:{dominant_share:.0%}"
            )
        elif dominant_share > max_share:
            status = STATUS_SKEWED
            warnings.append(
                f"ANGLE_SKEWED:{dominant['angle_key']}:{dominant_share:.0%}"
            )
    if missing and total:
        warnings.append(f"ANGLES_UNUSED:{len(missing)}/{len(universe)}")
        if status == STATUS_OK:
            status = STATUS_SKEWED
    if unattributed:
        warnings.append(f"ITEMS_WITHOUT_ANGLE:{unattributed}")

    return {
        "status": status,
        "total_items": len(items),
        "attributed_items": total,
        "unattributed_items": unattributed,
        "angles_available": len(universe),
        "angles_covered": covered,
        "missing_angles": missing,
        "dominant_angle": dominant["angle_key"] if dominant else None,
        "dominant_label": dominant["angle_label"] if dominant else "",
        "dominant_share": dominant_share,
        "max_share": max_share,
        "per_angle": per_angle,
        "warnings": warnings,
        "blocked": bool(blocking and status == STATUS_MONOCULTURE),
    }
