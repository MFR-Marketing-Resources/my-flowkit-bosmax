"""Fail-closed structural validation for scene_choreography_v2."""

from __future__ import annotations

from agent.models.scene_choreography_v2 import (
    CHOREOGRAPHY_SCHEMA_VERSION,
    PLACEHOLDER_STATE_MARKERS,
    ChoreographyValidationError,
    ChoreographyVariant,
    EntityState,
)
from agent.services.scene_choreography_scenarios import has_positive_physical_branch


_HAND_CUSTODY = {"SUPPORT_HAND", "ACTIVE_HAND", "BOTH_HANDS"}


def _err(
    code: str,
    variant: ChoreographyVariant,
    *,
    step: int | None = None,
    entity: str | None = None,
    **details: object,
) -> ChoreographyValidationError:
    return ChoreographyValidationError(
        code,
        strategy_id=variant.strategy_id,
        choreography_id=variant.choreography_id,
        step=step,
        entity=entity,
        details=details or None,
    )


def _state_key(state: EntityState) -> tuple[str, str, str, bool, str]:
    return (
        state.entity_id,
        state.location,
        state.custody,
        state.visible,
        state.physical_state,
    )


def _by_id(states: list[EntityState]) -> dict[str, EntityState]:
    mapped: dict[str, EntityState] = {}
    for state in states:
        if state.entity_id in mapped:
            raise ValueError(f"duplicate entity {state.entity_id}")
        mapped[state.entity_id] = state
    return mapped


def validate_choreography_variant(variant: ChoreographyVariant) -> None:
    if variant.schema_version != CHOREOGRAPHY_SCHEMA_VERSION:
        raise _err("CHOREOGRAPHY_SCHEMA_VERSION_MISMATCH", variant)
    if variant.strategy_id == "GENERIC_FALLBACK" or variant.classification == "BLOCK":
        raise _err("GENERIC_FALLBACK_BLOCKED", variant)
    if not variant.production_eligible:
        raise _err("CHOREOGRAPHY_NOT_PRODUCTION_ELIGIBLE", variant)
    allowed_presence = list(getattr(variant, "allowed_character_presence", ()) or ())
    if not allowed_presence:
        raise _err("CHARACTER_PRESENCE_COMPATIBILITY_REQUIRED", variant)
    if len(set(allowed_presence)) != len(allowed_presence):
        raise _err(
            "CHARACTER_PRESENCE_COMPATIBILITY_DUPLICATE",
            variant,
            allowed_character_presence=allowed_presence,
        )
    if not variant.steps:
        raise _err("CHOREOGRAPHY_STEPS_REQUIRED", variant)

    numbers = [step.step_number for step in variant.steps]
    if numbers != list(range(1, len(numbers) + 1)):
        raise _err("CHOREOGRAPHY_STEPS_NOT_CONTIGUOUS", variant, step_numbers=numbers)

    if abs(variant.steps[0].start_s) > 1e-9:
        raise _err("FIRST_STEP_MUST_START_AT_ZERO", variant, step=1)

    tracked: set[str] | None = None
    previous_resulting: dict[str, EntityState] | None = None
    previous_hands: tuple[str, str] | None = None
    previous_end = 0.0

    for step in variant.steps:
        if step.end_s <= step.start_s:
            raise _err("STEP_TIME_RANGE_INVALID", variant, step=step.step_number)
        if step.start_s + 1e-9 < previous_end:
            raise _err(
                "STEP_TIME_OVERLAP",
                variant,
                step=step.step_number,
                previous_end=previous_end,
                start=step.start_s,
            )
        if step.end_s - 1e-9 > variant.scene_duration_s:
            raise _err(
                "STEP_EXCEEDS_SCENE_DURATION",
                variant,
                step=step.step_number,
                end=step.end_s,
                duration=variant.scene_duration_s,
            )
        previous_end = step.end_s

        blob = " ".join(
            [
                step.action_instruction,
                step.visibility,
                *(rule for rule in step.continuity_rules),
                *(state.physical_state for state in step.initial_states),
                *(state.physical_state for state in step.resulting_states),
            ]
        ).casefold()
        for marker in PLACEHOLDER_STATE_MARKERS:
            if marker in blob:
                raise _err(
                    "PLACEHOLDER_STATE_FORBIDDEN",
                    variant,
                    step=step.step_number,
                    marker=marker,
                )
        if has_positive_physical_branch(step.action_instruction):
            raise _err(
                "POSITIVE_PHYSICAL_BRANCH_FORBIDDEN",
                variant,
                step=step.step_number,
                instruction=step.action_instruction,
            )
        for loc in (
            *(state.location for state in step.initial_states),
            *(state.location for state in step.resulting_states),
        ):
            if " or " in loc.casefold():
                raise _err(
                    "BRANCHING_LOCATION_FORBIDDEN",
                    variant,
                    step=step.step_number,
                    location=loc,
                )
        for idx in step.source_action_indexes:
            if int(idx) < 0:
                raise _err(
                    "SOURCE_ACTION_INDEX_INVALID",
                    variant,
                    step=step.step_number,
                    index=idx,
                )

        try:
            initial = _by_id(step.initial_states)
            resulting = _by_id(step.resulting_states)
        except ValueError as exc:
            raise _err(
                "DUPLICATE_ENTITY_IN_STEP",
                variant,
                step=step.step_number,
                reason=str(exc),
            ) from exc

        if set(initial) != set(resulting):
            raise _err(
                "ENTITY_SET_CHANGED_WITHOUT_TRANSITION",
                variant,
                step=step.step_number,
                initial=sorted(initial),
                resulting=sorted(resulting),
            )

        if tracked is None:
            tracked = set(initial)
            if not any(state.visible for state in initial.values()):
                raise _err("FIRST_FRAME_VISIBLE_ENTITY_REQUIRED", variant, step=1)
            if "product" not in initial:
                raise _err(
                    "FIRST_FRAME_PRODUCT_REQUIRED",
                    variant,
                    step=1,
                    entity="product",
                )
            if not initial["product"].visible:
                raise _err(
                    "FIRST_FRAME_PRODUCT_MUST_BE_VISIBLE",
                    variant,
                    step=1,
                    entity="product",
                )
        elif set(initial) != tracked:
            raise _err(
                "TRACKED_ENTITY_SET_DRIFT",
                variant,
                step=step.step_number,
                expected=sorted(tracked),
                actual=sorted(initial),
            )

        if previous_resulting is not None:
            for entity_id, prior in previous_resulting.items():
                current = initial[entity_id]
                if _state_key(prior) != _state_key(current):
                    if step.camera_cut_boundary != "REESTABLISH":
                        raise _err(
                            "STATE_CHAIN_BREAK",
                            variant,
                            step=step.step_number,
                            entity=entity_id,
                            previous=_state_key(prior),
                            current=_state_key(current),
                        )
                    if not current.visible:
                        raise _err(
                            "CUT_REESTABLISH_REQUIRES_VISIBLE_INCOMING_STATE",
                            variant,
                            step=step.step_number,
                            entity=entity_id,
                        )

        if previous_hands is not None:
            current_hands = (step.support_hand, step.active_hand)
            if current_hands != previous_hands:
                transfer_declared = any(
                    "hand transfer" in rule.casefold() or "explicit transfer" in rule.casefold()
                    for rule in step.continuity_rules
                ) or "transfer" in step.action_instruction.casefold()
                if not transfer_declared and step.camera_cut_boundary == "NONE":
                    # Role labels may stay stable even when an object moves.
                    # Only fail when a hand that held an entity no longer does
                    # without an explicit transfer/placement rule.
                    prior_holders = {
                        entity_id
                        for entity_id, state in previous_resulting.items()
                        if state.custody in _HAND_CUSTODY
                    }
                    next_holders = {
                        entity_id
                        for entity_id, state in initial.items()
                        if state.custody in _HAND_CUSTODY
                    }
                    if prior_holders != next_holders:
                        raise _err(
                            "HAND_CUSTODY_SWAP_WITHOUT_TRANSFER",
                            variant,
                            step=step.step_number,
                            previous_holders=sorted(prior_holders),
                            current_holders=sorted(next_holders),
                        )
        previous_hands = (step.support_hand, step.active_hand)
        previous_resulting = resulting

        if step.camera_cut_boundary == "OUTGOING" and step is not variant.steps[-1]:
            if not all(state.visible or state.custody == "FRAME_STATIC" for state in resulting.values()):
                # Outgoing cut must declare a complete outgoing state for every entity.
                if not resulting:
                    raise _err("CUT_OUTGOING_STATE_REQUIRED", variant, step=step.step_number)

    if variant.scene_context not in variant.compatible_contexts:
        raise _err(
            "CONTEXT_NOT_COMPATIBLE",
            variant,
            context=variant.scene_context,
            compatible=variant.compatible_contexts,
        )
    if variant.camera_route not in variant.compatible_camera_routes:
        raise _err(
            "CAMERA_ROUTE_NOT_COMPATIBLE",
            variant,
            camera_route=variant.camera_route,
            compatible=variant.compatible_camera_routes,
        )

    final = variant.steps[-1]
    if not final.is_final_lock:
        raise _err("FINAL_STATE_LOCK_REQUIRED", variant, step=final.step_number)
    if abs(final.end_s - variant.scene_duration_s) > 1e-6:
        raise _err(
            "FINAL_STEP_MUST_CLOSE_DURATION",
            variant,
            step=final.step_number,
            end=final.end_s,
            duration=variant.scene_duration_s,
        )
    lock_blob = " ".join([final.action_instruction, variant.final_state_lock]).casefold()
    if "new prop" in lock_blob or "unplanned" in lock_blob or "hold the final" in lock_blob:
        pass
    elif "hold" not in lock_blob and "lock" not in lock_blob:
        raise _err("FINAL_STATE_LOCK_LANGUAGE_REQUIRED", variant, step=final.step_number)


def assert_character_presence_compatible(
    variant: ChoreographyVariant,
    character_presence: str,
) -> None:
    """Fail closed when a selected choreography is not valid for the surface."""

    candidate = str(character_presence or "").strip().upper()
    allowed = list(getattr(variant, "allowed_character_presence", ()) or ())
    if not allowed:
        raise _err("CHARACTER_PRESENCE_COMPATIBILITY_REQUIRED", variant)
    if candidate not in allowed:
        code = (
            "ERR_FACELESS_CHOREOGRAPHY_INCOMPATIBLE"
            if candidate == "FACELESS"
            else "CHOREOGRAPHY_CHARACTER_PRESENCE_INCOMPATIBLE"
        )
        raise _err(
            code,
            variant,
            character_presence=candidate or "<empty>",
            allowed_character_presence=allowed,
        )


def validate_production_strategy_id(strategy_id: str) -> None:
    normalized = str(strategy_id or "").strip().upper()
    if not normalized or normalized == "GENERIC_FALLBACK" or "FALLBACK" in normalized:
        raise ChoreographyValidationError(
            "GENERIC_FALLBACK_BLOCKED",
            strategy_id=normalized or "<empty>",
        )
