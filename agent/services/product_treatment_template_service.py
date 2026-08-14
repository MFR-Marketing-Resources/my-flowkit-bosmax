from __future__ import annotations

from agent.models.creative_treatment import (
    TreatmentActionStep,
    TreatmentCompatibilityProfile,
    TreatmentShot,
)
from agent.models.product_readiness import (
    ApplicabilityProfileProjection,
    EvidenceRequirementResult,
    ProductReadinessEvaluateRequest,
)
from agent.models.product_treatment_factory import TreatmentTemplateProjection
from agent.models.scene_choreography_v2 import PLACEHOLDER_STATE_MARKERS
from agent.services.creative_treatment_service import canonical_sha256
from agent.services.scene_choreography_catalog import (
    choreography_sha256,
    select_variant_for_strategy,
)
from agent.services.scene_choreography_validator import validate_production_strategy_id


TEMPLATE_VERSION = "product-treatment-template-v2"

_SOURCE_MODE_BY_LOGICAL_MODE = {
    "T2V": "T2V",
    "HYBRID": "HYBRID",
    "F2V": "FRAMES",
    "I2V": "INGREDIENTS",
}

_FORMAT_GRAMMAR = {
    "UGC": (
        ("creator context", "natural medium close-up", "restrained handheld drift", "presenter and governed product"),
        ("governed action proof", "clear action close-up", "controlled push-in", "approved product interaction"),
        ("product-led close", "stable product close-up", "gentle settle", "product and presenter"),
    ),
    "PGC": (
        ("product hero", "clean product medium shot", "measured lateral reveal", "product"),
        ("governed action detail", "precise product close-up", "controlled push-in", "product action"),
        ("commercial proof close", "stable hero close-up", "locked settle", "product"),
    ),
    "CINEMATIC": (
        ("cinematic reveal", "wide-to-medium product reveal", "slow parallax", "product in environment"),
        ("material action detail", "macro action close-up", "precision tracking", "product action"),
        ("cinematic hero close", "sculpted hero frame", "slow final settle", "product"),
    ),
}


class ProductTreatmentTemplateError(ValueError):
    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _shot_durations(total_seconds: int) -> list[float]:
    total = float(total_seconds)
    if total < 3:
        return [total]
    first = round(total * 0.3, 3)
    second = round(total * 0.4, 3)
    return [first, second, round(total - first - second, 3)]


def _actor_role(format_name: str) -> str:
    if format_name == "UGC":
        return "PRESENTER"
    return "PRODUCT"


def _serialize_states(states) -> str:
    return "; ".join(
        f"{state.entity_id}@{state.location}/{state.custody}:{state.physical_state}"
        for state in states
    )


def resolve_treatment_template(
    *,
    context: ProductReadinessEvaluateRequest,
    profile: ApplicabilityProfileProjection,
    requirements: list[EvidenceRequirementResult],
) -> TreatmentTemplateProjection:
    if not profile.supported:
        raise ProductTreatmentTemplateError(
            profile.unsupported_code or "UNSUPPORTED_PRODUCT_TAXONOMY",
            details={"scene_strategy_id": profile.scene_strategy_id},
        )
    try:
        validate_production_strategy_id(profile.scene_strategy_id)
        authorized_indexes = {
            action.allowed_action_index for action in profile.indexed_actions
        }
        if context.allowed_action_index not in authorized_indexes:
            raise ProductTreatmentTemplateError(
                "ACTION_INDEX_NOT_AUTHORIZED",
                details={
                    "scene_strategy_id": profile.scene_strategy_id,
                    "selected_action_index": context.allowed_action_index,
                },
            )
        variant = select_variant_for_strategy(
            profile.scene_strategy_id,
            context.allowed_action_index,
        )
    except Exception as exc:
        raise ProductTreatmentTemplateError(
            "ACTION_INDEX_NOT_AUTHORIZED",
            details={
                "scene_strategy_id": profile.scene_strategy_id,
                "selected_action_index": context.allowed_action_index,
                "reason": str(exc),
            },
        ) from exc
    selected_action = next(
        (
            action
            for action in profile.indexed_actions
            if action.allowed_action_index == context.allowed_action_index
        ),
        None,
    )
    if selected_action is None:
        raise ProductTreatmentTemplateError(
            "ACTION_INDEX_NOT_AUTHORIZED",
            details={
                "scene_strategy_id": profile.scene_strategy_id,
                "selected_action_index": context.allowed_action_index,
            },
        )
    actor_policy = profile.actor_policy_by_format.get(context.creative_format)
    if actor_policy is None:
        raise ProductTreatmentTemplateError(
            "FORMAT_POLICY_NOT_AUTHORIZED",
            details={"format": context.creative_format},
        )
    source_mode = _SOURCE_MODE_BY_LOGICAL_MODE[context.logical_mode]
    required_asset_roles = sorted(
        profile.required_asset_roles_by_mode.get(context.logical_mode, []),
    )
    actor_role = _actor_role(context.creative_format)
    action_sequence: list[TreatmentActionStep] = []
    for step in variant.steps:
        initial_state = _serialize_states(step.initial_states)
        resulting_state = _serialize_states(step.resulting_states)
        lowered = f"{initial_state} {resulting_state} {step.action_instruction}".casefold()
        if any(marker in lowered for marker in PLACEHOLDER_STATE_MARKERS):
            raise ProductTreatmentTemplateError(
                "PLACEHOLDER_STATE_FORBIDDEN",
                details={
                    "choreography_id": variant.choreography_id,
                    "step": step.step_number,
                },
            )
        product_state = next(
            (state for state in step.resulting_states if state.entity_id == "product"),
            step.resulting_states[0],
        )
        component_state = next(
            (state for state in step.resulting_states if state.entity_id == "component"),
            None,
        )
        action_sequence.append(
            TreatmentActionStep(
                sequence=step.step_number,
                allowed_action_index=context.allowed_action_index,
                action_text=step.action_instruction,
                actor_role=actor_role,
                initial_state=initial_state,
                resulting_state=resulting_state,
                continuity_requirements=[
                    *step.continuity_rules,
                    f"visibility={step.visibility}",
                    f"cut={step.camera_cut_boundary}",
                    *([variant.final_state_lock] if step.is_final_lock else []),
                ],
                start_time_seconds=step.start_s,
                end_time_seconds=step.end_s,
                support_hand=step.support_hand,
                active_hand=step.active_hand,
                visibility=step.visibility,
                camera_cut_boundary=step.camera_cut_boundary,
                product_location=product_state.location,
                component_custody=(
                    None if component_state is None else component_state.custody
                ),
            )
        )
    grammar = _FORMAT_GRAMMAR[context.creative_format]
    durations = _shot_durations(context.duration_seconds)
    step_count = len(action_sequence)
    cursor = 1
    shot_grammar: list[TreatmentShot] = []
    for index, duration in enumerate(durations, start=1):
        if index < len(durations):
            take = max(1, round(step_count * (duration / float(context.duration_seconds))))
            assigned = list(range(cursor, min(cursor + take, step_count + 1)))
            cursor = assigned[-1] + 1 if assigned else cursor
        else:
            assigned = list(range(cursor, step_count + 1)) or [step_count]
        shot_grammar.append(
            TreatmentShot(
                sequence=index,
                action_sequences=assigned,
                purpose=grammar[min(index - 1, len(grammar) - 1)][0],
                framing=grammar[min(index - 1, len(grammar) - 1)][1],
                camera_motion=grammar[min(index - 1, len(grammar) - 1)][2],
                subject=grammar[min(index - 1, len(grammar) - 1)][3],
                duration_seconds=duration,
                continuity_in=["approved product identity", "choreography incoming state"],
                continuity_out=["approved product identity", "choreography outgoing state"],
            )
        )
    compatibility = TreatmentCompatibilityProfile(
        logical_mode=context.logical_mode,
        source_mode=source_mode,
        model_keys=[context.model_key],
        required_asset_roles=required_asset_roles,
    )
    content = {
        "template_version": TEMPLATE_VERSION,
        "scene_strategy_id": profile.scene_strategy_id,
        "profile_version": profile.profile_version,
        "profile_sha256": profile.profile_sha256,
        "risk_flags": sorted(profile.risk_flags),
        "selected_action_index": selected_action.allowed_action_index,
        "action_text": variant.intent_label,
        "action_classes": sorted(selected_action.action_classes),
        "format": context.creative_format,
        "actor_policy": actor_policy,
        "logical_mode": context.logical_mode,
        "generation_mode": context.generation_mode,
        "duration_seconds": context.duration_seconds,
        "evidence_requirements": [
            item.model_dump(mode="json") for item in requirements
        ],
        "action_sequence": [
            item.model_dump(mode="json") for item in action_sequence
        ],
        "shot_grammar": [item.model_dump(mode="json") for item in shot_grammar],
        "compatibility_profile": compatibility.model_dump(mode="json"),
        "choreography_schema_version": variant.schema_version,
        "choreography_id": variant.choreography_id,
        "choreography_sha256": choreography_sha256(variant),
    }
    template_sha256 = canonical_sha256(content)
    return TreatmentTemplateProjection(
        template_id=f"ptt_{template_sha256[:24]}",
        template_sha256=template_sha256,
        **content,
    )
