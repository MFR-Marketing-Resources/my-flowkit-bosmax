"""Canonical per-mode Google Flow reference-count contract (product authority).

F2V, HYBRID, I2V and T2V are INPUT MODES over ONE transport pipeline
(`make_video.start_generate`). The ONLY thing that differs per mode is the
reference-image contract:

| Surface (user mode)   | Transport mode | References sent to Google Flow |
|-----------------------|----------------|--------------------------------|
| F2V / FRAMES          | F2V            | 1 or 2 (start [+ end] frame)   |
| HYBRID                | F2V            | exactly 1 (the product image)  |
| I2V / INGREDIENTS     | I2V            | 2 or 3 (ordered ingredient refs)|
| T2V                   | T2V            | 0 (text prompt only)           |

Any other count fails closed BEFORE generation — never silently dropped,
never silently added, never converted to a text-only run.

Two enforcement layers, one source of truth:
  * `validate_reference_count` — the full user-mode contract (upper AND lower
    bounds). Applied wherever the user's surface mode is authoritative: the
    operator manual lane (`source_mode` from the dashboard payload) and the
    durable full-video job (the execution package's mode).
  * `service_hard_violation` — the transport-level hard caps applied inside the
    one-door service itself (T2V must be text-only; F2V > 2 and I2V > 3 are
    impossible upstream contracts). Lower bounds stay at the operator layers so
    proven programmatic callers (registry lanes, fixtures) keep their existing
    at-least-one-reference behaviour.
"""
from __future__ import annotations

from typing import Optional

ERR_REFERENCE_COUNT_CONTRACT = "ERR_REFERENCE_COUNT_CONTRACT"
ERR_T2V_REFERENCES_FORBIDDEN = "ERR_T2V_REFERENCES_FORBIDDEN"

# Transport-mode bounds (make_video modes). IMG has no video reference contract.
_TRANSPORT_BOUNDS: dict[str, tuple[int, int]] = {
    "F2V": (1, 2),
    "I2V": (2, 3),
    "T2V": (0, 0),
}

# Surface / user-mode refinements (the dashboard's declared source_mode or the
# execution package's mode). HYBRID is F2V transport restricted to EXACTLY the
# one selected product image.
_SOURCE_MODE_BOUNDS: dict[str, tuple[int, int]] = {
    "F2V": (1, 2),
    "FRAMES": (1, 2),
    "HYBRID": (1, 1),
    "I2V": (2, 3),
    "INGREDIENTS": (2, 3),
    "T2V": (0, 0),
}

# One-door hard caps (upper bounds only — see module docstring).
_SERVICE_HARD_MAX: dict[str, int] = {"F2V": 2, "I2V": 3, "T2V": 0}


def reference_bounds(mode: str, source_mode: Optional[str] = None) -> Optional[tuple[int, int]]:
    """(min, max) reference bounds for a mode, refined by the user surface mode
    when declared. None → no video reference contract applies (e.g. IMG)."""
    surface = (source_mode or "").strip().upper()
    if surface in _SOURCE_MODE_BOUNDS:
        return _SOURCE_MODE_BOUNDS[surface]
    return _TRANSPORT_BOUNDS.get((mode or "").strip().upper())


def validate_reference_count(
    mode: str, count: int, source_mode: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Full user-mode contract. Returns (ok, error_code, human_detail)."""
    bounds = reference_bounds(mode, source_mode)
    if bounds is None:
        return True, None, None
    lo, hi = bounds
    if lo <= count <= hi:
        return True, None, None
    label = (source_mode or mode or "").strip().upper()
    if label == "T2V" or hi == 0:
        return False, ERR_T2V_REFERENCES_FORBIDDEN, (
            f"T2V is text-only — {count} reference image(s) attached; remove the "
            "image state (never inherited from a previous job) before generating")
    expected = f"exactly {lo}" if lo == hi else f"{lo}-{hi}"
    return False, ERR_REFERENCE_COUNT_CONTRACT, (
        f"{label} requires {expected} reference image(s) per the user-selected "
        f"option, got {count} — refusing to silently add, drop, or convert to "
        "a text-only generation")


def service_hard_violation(mode: str, count: int) -> Optional[str]:
    """Transport-level hard cap check for the one-door service. Returns the
    rejection string (code-prefixed) or None when within caps."""
    hard = _SERVICE_HARD_MAX.get((mode or "").strip().upper())
    if hard is None or count <= hard:
        return None
    if hard == 0:
        return (f"{ERR_T2V_REFERENCES_FORBIDDEN}: T2V is text-only but "
                f"{count} reference image(s) were attached")
    return (f"{ERR_REFERENCE_COUNT_CONTRACT}: {(mode or '').upper()} supports at "
            f"most {hard} reference image(s), got {count}")


# ── SERVER-OWNED source-mode authority (PR321 closure, Defect 1) ─────────────
ERR_SOURCE_MODE_AUTHORITY_MISMATCH = "ERR_SOURCE_MODE_AUTHORITY_MISMATCH"

# Compiler-canonical lineages (ugc_video_prompt_compiler_service.CANONICAL_SOURCE_MODES).
_CANONICAL_SOURCE_MODES = {"T2V", "HYBRID", "FRAMES", "INGREDIENTS", "IMAGES"}

# UI / transport aliases → canonical lineage (the dashboard's F2V surface IS the
# FRAMES lineage; its I2V surface IS INGREDIENTS).
_SOURCE_MODE_ALIASES = {
    "F2V": "FRAMES", "FRAMES": "FRAMES", "HYBRID": "HYBRID",
    "I2V": "INGREDIENTS", "INGREDIENTS": "INGREDIENTS", "T2V": "T2V",
    "IMAGES": "IMAGES", "IMG": "IMAGES",
}

# The compiler's documented per-mode DEFAULT lineage when a package predates the
# persisted compiler lineage (see _source_lineage_default_warning: a bare F2V
# compile defaults to the HYBRID product-anchor branch).
_PACKAGE_MODE_DEFAULT_LINEAGE = {"T2V": "T2V", "I2V": "INGREDIENTS", "F2V": "HYBRID"}


def normalize_source_mode(value) -> str | None:
    """Canonical lineage for a UI/transport surface declaration (None if unknown)."""
    return _SOURCE_MODE_ALIASES.get(str(value or "").strip().upper())


def derive_package_source_mode(pkg: dict | None) -> str | None:
    """The SERVER-OWNED canonical source mode of a persisted execution package.

    Authority order (never a client declaration):
      1. the compiler lineage persisted at package-compile time
         (`request_lineage_payload.compiler.source_mode` — canonical set);
      2. the compiler's documented per-mode default for legacy packages.
    """
    if not pkg:
        return None
    import json as _json
    try:
        lineage = _json.loads(pkg.get("request_lineage_payload") or "{}")
    except (TypeError, ValueError):
        lineage = {}
    compiled = str(((lineage.get("compiler") or {}).get("source_mode")) or "").strip().upper()
    if compiled in _CANONICAL_SOURCE_MODES:
        return compiled
    return _PACKAGE_MODE_DEFAULT_LINEAGE.get(str(pkg.get("mode") or "").strip().upper())
