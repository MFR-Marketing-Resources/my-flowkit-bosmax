"""Copy Similarity service — zero-provider near-duplicate detection.

Deterministic, zero-dependency utilities for comparing Copy Set fields
(angle, hook, subhook, USP set, CTA) against one another.  Exact
duplication remains the responsibility of the existing `dedupe_key` in
`agent/models/copy_set.py`; this module answers the *near*-duplicate
question for warning / uniqueness scoring only.

Rules:
- No embeddings.
- No external API / provider calls.
- No heavy dependencies (stdlib only).
- Threshold defaults to 0.80 (configurable per call).
"""

from __future__ import annotations

import math
import re
from typing import Any


def _clean(value: Any) -> str:
    """Normalise a copy field to a canonical comparable string."""
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def token_set(text: str) -> set[str]:
    """Return a set of word tokens (split on whitespace / punctuation)."""
    return set(re.findall(r"\w+", _clean(text)))


def jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two token sets.

    Returns 1.0 when both are empty (vacuous truth).
    """
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def levenshtein_ratio(a: str, b: str) -> float:
    """Simple edit-distance ratio: 1.0 = identical, 0.0 = completely different."""
    a = _clean(a)
    b = _clean(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    # Optimised O(min(m,n)) space Wagner-Fischer
    if len(a) > len(b):
        a, b = b, a
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(
                min(
                    curr[-1] + 1,
                    prev[j] + 1,
                    prev[j - 1] + (0 if ca == cb else 1),
                )
            )
        prev = curr
    distance = prev[-1]
    max_len = max(m, n)
    return 1.0 - (distance / max_len)


def _field_string(fields: dict[str, Any]) -> str:
    """Flatten the main copy fields into one comparable string."""
    parts = [
        fields.get("hook", ""),
        fields.get("subhook", ""),
        " ".join(fields.get("usp_set") or []),
        fields.get("cta", ""),
    ]
    return " | ".join(p for p in parts if p)


def _angle_string(fields: dict[str, Any]) -> str:
    return str(fields.get("angle", "") or "")


def combined_similarity(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    *,
    hook_weight: float = 0.55,
    angle_weight: float = 0.15,
    token_weight: float = 0.30,
) -> float:
    """Weighted similarity score (0.0 - 1.0) combining:

    - Levenshtein on the canonical copy string (hook + subhook + USPs + CTA)
    - Levenshtein on the angle alone
    - Jaccard token-set overlap

    Default weights favour hook-heavy copy similarity (most important for
    avoiding repetitive UGC).
    """
    cand_str = _field_string(candidate)
    exist_str = _field_string(existing)
    # Both empty = no meaningful signal. Exact duplicate is handled by
    # the existing dedupe_key, not by near-duplicate detection.
    if not cand_str or not exist_str:
        return 0.0
    hook_sim = levenshtein_ratio(cand_str, exist_str)
    angle_sim = levenshtein_ratio(_angle_string(candidate), _angle_string(existing))
    token_sim = jaccard(token_set(cand_str), token_set(exist_str))
    return (
        hook_weight * hook_sim
        + angle_weight * angle_sim
        + token_weight * token_sim
    )


def is_near_duplicate(
    candidate: dict[str, Any],
    existing: dict[str, Any],
    threshold: float = 0.80,
) -> tuple[bool, float]:
    """Return ``(is_near_duplicate, score)``.

    ``is_near_duplicate`` is True when ``score >= threshold``.
    """
    score = combined_similarity(candidate, existing)
    return score >= threshold, score


def find_nearest(
    candidate: dict[str, Any],
    existing_candidates: list[dict[str, Any]],
    threshold: float = 0.80,
) -> tuple[dict[str, Any] | None, float]:
    """Return the nearest existing Copy Set (and its similarity score) that
    meets or exceeds the threshold, or ``(None, 0.0)`` if none qualify.
    """
    best: dict[str, Any] | None = None
    best_score = 0.0
    for cs in existing_candidates:
        score = combined_similarity(candidate, cs)
        if score > best_score:
            best_score = score
            best = cs
    if best_score >= threshold and best is not None:
        return best, best_score
    return None, 0.0


def compute_uniqueness_score(
    candidate: dict[str, Any],
    existing_approved: list[dict[str, Any]],
) -> float:
    """How different is this candidate from all approved Copy Sets for the
    same product?

    1.0 = completely unique (no similarity to any existing approved).
    """
    if not existing_approved:
        return 1.0
    max_sim = max(
        combined_similarity(candidate, cs) for cs in existing_approved
    )
    return 1.0 - max_sim
