"""Stale choreography lineage detection for historical treatments.

Historical approved treatments remain readable. Production generation must
call ``assert_production_treatment_payload`` and fail closed when the stored
payload is atomic-only, placeholder-based, or hash-stale.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent.models.scene_choreography_v2 import (
    PLACEHOLDER_STATE_MARKERS,
    ChoreographyValidationError,
)
from agent.services.scene_choreography_catalog import (
    all_choreography_variants,
    choreography_sha256,
    select_variant_for_strategy,
)


def treatment_is_historically_readable(row: Mapping[str, Any]) -> bool:
    return bool(row.get("treatment_id") and row.get("action_sequence_json") is not None)


def assert_current_choreography_lineage(
    *,
    strategy_id: str,
    choreography_id: str | None,
    choreography_sha: str | None,
    action_sequence: list[Mapping[str, Any]] | None = None,
    variation_index: int = 0,
) -> None:
    if not choreography_id or not choreography_sha:
        raise ChoreographyValidationError(
            "STALE_TREATMENT_LINEAGE",
            strategy_id=strategy_id,
            choreography_id=choreography_id,
        )
    variants = all_choreography_variants().get(strategy_id, ())
    variant = next(
        (item for item in variants if item.choreography_id == choreography_id),
        None,
    )
    if variant is None:
        variant = select_variant_for_strategy(strategy_id, variation_index)
    live = choreography_sha256(variant)
    if live != choreography_sha or variant.choreography_id != choreography_id:
        raise ChoreographyValidationError(
            "STALE_TREATMENT_LINEAGE",
            strategy_id=strategy_id,
            choreography_id=choreography_id,
            details={"stored": choreography_sha, "live": live},
        )
    blob = " ".join(
        str(step.get(key) or "")
        for step in action_sequence or []
        for key in ("action_text", "initial_state", "resulting_state")
    ).casefold()
    if any(marker in blob for marker in PLACEHOLDER_STATE_MARKERS):
        raise ChoreographyValidationError(
            "PLACEHOLDER_STATE_FORBIDDEN",
            strategy_id=strategy_id,
            choreography_id=choreography_id,
        )


def assert_production_treatment_payload(
    *,
    strategy_id: str,
    decoded: Mapping[str, Any],
) -> None:
    if "FALLBACK" in str(strategy_id or "").upper():
        raise ChoreographyValidationError(
            "GENERIC_FALLBACK_BLOCKED",
            strategy_id=strategy_id,
        )
    sequence = list(decoded.get("action_sequence") or [])
    blob = " ".join(
        str(step.get(key) or "")
        for step in sequence
        if isinstance(step, Mapping)
        for key in ("action_text", "initial_state", "resulting_state")
    ).casefold()
    if any(marker in blob for marker in PLACEHOLDER_STATE_MARKERS):
        raise ChoreographyValidationError(
            "PLACEHOLDER_STATE_FORBIDDEN",
            strategy_id=strategy_id,
        )
    choreography_id = decoded.get("choreography_id")
    if not choreography_id or len(sequence) < 2:
        raise ChoreographyValidationError(
            "LEGACY_ATOMIC_TREATMENT_REJECTED",
            strategy_id=strategy_id,
        )
    assert_current_choreography_lineage(
        strategy_id=strategy_id,
        choreography_id=str(choreography_id),
        choreography_sha=str(decoded.get("choreography_sha256") or "") or None,
        action_sequence=[step for step in sequence if isinstance(step, Mapping)],
    )
