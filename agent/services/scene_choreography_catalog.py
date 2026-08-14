"""Production choreography catalog for every current scene strategy.

Atomic ``allowed_actions`` remain on the strategy library for audit/read
compatibility. Production selection uses these cohesive variants only.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from agent.models.scene_choreography_v2 import (
    CHOREOGRAPHY_SCHEMA_VERSION,
    ChoreographyStep,
    ChoreographyValidationError,
    ChoreographyVariant,
    EntityState,
)
from agent.services.creative_treatment_service import canonical_sha256
from agent.services.scene_choreography_scenarios import (
    COMPOSED_FAMILIES,
    SPECIAL_STRATEGY_BUILDERS,
    has_positive_physical_branch,
    herbal_oil_steps_composed,
    resolve_intent_scenario,
    roll_on_steps_composed,
)
from agent.services.scene_choreography_validator import (
    validate_choreography_variant,
    validate_production_strategy_id,
)
from agent.services.scene_strategy_library import SCENE_STRATEGIES, SceneStrategyEntry


Family = Literal[
    "APPLY_CONTACT",
    "MATERIAL_TRANSFER",
    "SPRAY",
    "FOOD_COOK",
    "OPEN_CLOSE",
    "PROP_TRANSFER",
    "STATIC_LOCK",
    "DEVICE_CONTROL",
    "MANIPULATION",
    "HERBAL_OIL",
    "ROLL_ON",
]


@dataclass(frozen=True)
class StrategySpec:
    classification: Literal["P0_REWRITE", "P1_REWRITE", "P2_STATIC", "BLOCK"]
    family: Family
    product: str
    component: str
    target: str
    receiver: str


def _st(
    entity_id: str,
    location: str,
    custody: str,
    visible: bool,
    physical_state: str,
) -> EntityState:
    return EntityState(
        entity_id=entity_id,
        location=location,
        custody=custody,  # type: ignore[arg-type]
        visible=visible,
        physical_state=physical_state,
    )


def _step(
    number: int,
    start: float,
    end: float,
    instruction: str,
    *,
    initial: list[EntityState],
    resulting: list[EntityState],
    support: str = "SUPPORT_HAND",
    active: str = "ACTIVE_HAND",
    visibility: str,
    rules: list[str],
    cut: str = "NONE",
    final: bool = False,
    actor: str = "PRESENTER",
    sources: list[int] | None = None,
    transition: str = "",
) -> ChoreographyStep:
    if has_positive_physical_branch(instruction):
        raise ChoreographyValidationError(
            "POSITIVE_PHYSICAL_BRANCH_FORBIDDEN",
            details={"instruction": instruction},
        )
    return ChoreographyStep(
        step_number=number,
        start_s=start,
        end_s=end,
        actor_role=actor,  # type: ignore[arg-type]
        support_hand=support,  # type: ignore[arg-type]
        active_hand=active,  # type: ignore[arg-type]
        action_instruction=instruction,
        initial_states=initial,
        resulting_states=resulting,
        visibility=visibility,
        camera_cut_boundary=cut,  # type: ignore[arg-type]
        continuity_rules=rules,
        is_final_lock=final,
        source_action_indexes=list(sources or []),
        transition_signature=transition,
    )


def _variant(
    *,
    strategy_id: str,
    index: int,
    spec: StrategySpec,
    family: str,
    scene: str,
    context: str,
    camera: str,
    intent: str,
    steps: list[ChoreographyStep],
    extra_contexts: list[str],
    extra_cameras: list[str],
    suffix: str = "",
) -> ChoreographyVariant:
    lock = (
        "Hold the final state. No new prop, duplicate hand, unexplained motion, "
        "or unplanned action."
    )
    return ChoreographyVariant(
        choreography_id=f"{strategy_id.lower()}.v{index}{suffix}",
        schema_version=CHOREOGRAPHY_SCHEMA_VERSION,
        strategy_id=strategy_id,
        classification=spec.classification,
        family=family,  # type: ignore[arg-type]
        scene_duration_s=8.0,
        scene_strategy_label=scene,
        scene_context=context,
        camera_route=camera,
        intent_label=intent,
        compatible_contexts=list(dict.fromkeys([context, *extra_contexts])),
        compatible_camera_routes=list(dict.fromkeys([camera, *extra_cameras])),
        steps=steps,
        final_state_lock=lock,
        production_eligible=True,
    )


def _apply_contact(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="APPLY_CONTACT",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, cap, target = spec.product, spec.component, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", f"support hand, label-forward", "SUPPORT_HAND", True, f"closed {product} already present"),
        _st("component", f"attached to {product}", "SUPPORT_HAND", True, f"{cap} seated/closed"),
        _st("target", target, "FRAME_STATIC", True, f"{target} already in frame"),
    ]
    s2i = s1
    s2r = [
        _st("product", "support hand, stable", "SUPPORT_HAND", True, f"{product} still in support hand"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened/exposed and kept visible"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged"),
    ]
    s3i = s2r
    s3r = [
        _st("product", "support hand, still in frame", "SUPPORT_HAND", True, f"{product} identity unchanged"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still in the same active hand"),
        _st("target", target, "FRAME_STATIC", True, f"one controlled pass completed on {target}"),
    ]
    s4i = s3r
    s4r = [
        _st("product", "safe visible position", "SUPPORT_HAND", True, f"{product} withdrawn from {target}"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still visible in active hand"),
        _st("target", target, "FRAME_STATIC", True, f"contact with {target} has stopped"),
    ]
    s5i = s4r
    s5r = [
        _st("product", "table, label-forward", "TABLE", True, f"{product} closed and placed label-forward on the table"),
        _st("component", "reseated on product", "TABLE", True, f"{cap} returned to the same {product}"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged after application"),
    ]
    s6i = s5r
    return [
        _step(1, 0.0, 1.0, f"The {product}, {cap}, and {target} are already present in the first frame. No object materializes after the scene begins.", initial=s1, resulting=list(s1), visibility="all required props and target visible", rules=["first-frame presence", "no thin-air entry"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.0, 2.3, f"The same two hands open the {cap}. Keep the removed component visible. The {product} stays in the support hand.", initial=s2i, resulting=s2r, visibility=f"{product} and {cap} remain visible", rules=["component custody retained", "no hand swap"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.3, 4.5, f"Perform one controlled application pass only onto the same {target}. Intent: {intent}. Do not invent extra applicators or a second product.", initial=s3i, resulting=s3r, visibility=f"{product}, {cap}, and {target} stay in frame", rules=["one pass only", "preserve product identity"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.5, 5.5, f"Stop contact with the {target} and return the {product} to a safe visible position.", initial=s4i, resulting=s4r, visibility="product and component remain visible after contact stops", rules=["explicit withdrawal"], sources=src, transition=f"{tr}:s",),
        _step(5, 5.5, 7.0, f"Close the {product} label-forward. The same {cap} is reseated on the same product.", initial=s5i, resulting=s5r, visibility="closed product label-forward on the table", rules=["explicit close/place"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.0, 8.0, "Hold the approved result context with no before/after transformation, no new prop, and no duplicate hand.", initial=s6i, resulting=list(s5r), visibility="final approved result held", rules=["final-state lock", "no new prop"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _material_transfer(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="MATERIAL_TRANSFER",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, cap, receiver = spec.product, spec.component, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "upright in support hand", "SUPPORT_HAND", True, f"closed/upright {product} already present"),
        _st("component", f"seated on {product}", "SUPPORT_HAND", True, f"{cap} closed and visible"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} already in frame"),
    ]
    s2r = [
        _st("product", "support hand, ready to dispense", "SUPPORT_HAND", True, f"{product} opened/readied"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} custody retained"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} fixed"),
    ]
    s3r = [
        _st("product", "support hand over receiver", "SUPPORT_HAND", True, f"{product} after one controlled transfer"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still in declared custody"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"exactly one controlled amount now on {receiver}"),
    ]
    s4r = [
        _st("product", "upright in support hand", "SUPPORT_HAND", True, f"{product} flow stopped and upright"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} unchanged"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"measured material remains only on {receiver}"),
    ]
    s5r = [
        _st("product", "table, label-forward", "TABLE", True, f"{product} closed and placed label-forward on the table"),
        _st("component", "reseated on the product", "TABLE", True, f"{cap} resolved"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} still holds the same amount"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the source {product} and the same {receiver}. Both are already present; nothing appears after the first frame.", initial=s1, resulting=list(s1), visibility="source and receiver visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.0, 2.2, f"Open the dispenser while retaining {cap} custody in the active hand.", initial=s1, resulting=s2r, visibility=f"{cap} never leaves frame", rules=["component custody retained"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.2, 4.2, f"Transfer exactly one controlled amount to the same {receiver}. Intent: {intent}. No airborne spray, extra stream, or second container.", initial=s2r, resulting=s3r, visibility="continuous coverage through the transfer", rules=["one controlled transfer", "no cut while material moves"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.2, 5.2, f"Stop the flow and return the {product} upright. The {receiver} stays fixed.", initial=s3r, resulting=s4r, visibility="source upright, receiver fixed", rules=["explicit stop-flow"], sources=src, transition=f"{tr}:s",),
        _step(5, 5.2, 6.8, f"Close the {product} and place it label-forward on the table. Reseat the same {cap} on the product.", initial=s4r, resulting=s5r, visibility="closed source still visible on the table", rules=["explicit close/place"], sources=src, transition=f"{tr}:s",),
        _step(6, 6.8, 8.0, f"Hold the source {product} and the {receiver} together in frame. No new prop or extra amount.", initial=s5r, resulting=list(s5r), visibility="source and result together", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _spray(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="SPRAY",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, cap, target = spec.product, spec.component, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "one hand, label-forward", "SUPPORT_HAND", True, f"closed {product} already in hand"),
        _st("component", f"on {product}", "SUPPORT_HAND", True, f"{cap} seated"),
        _st("target", target, "FRAME_STATIC", True, f"{target} and safe distance already established"),
    ]
    s2r = [
        _st("product", "same hand", "SUPPORT_HAND", True, f"{product} nozzle exposed"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} retained in the other hand"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged"),
    ]
    s3r = [
        _st("product", "same hand, aimed once", "SUPPORT_HAND", True, f"{product} after one controlled spray"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still in the same hand"),
        _st("target", target, "FRAME_STATIC", True, f"one spray completed toward {target}"),
    ]
    s4r = [
        _st("product", "same hand, lowered", "SUPPORT_HAND", True, f"{product} no longer spraying"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still held"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged after spray"),
    ]
    s5r = [
        _st("product", "same hand, label-forward", "SUPPORT_HAND", True, f"{product} recapped/nozzle-safe"),
        _st("component", "reseated on product", "SUPPORT_HAND", True, f"same {cap} replaced"),
        _st("target", target, "FRAME_STATIC", True, f"{target} still in frame"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the closed {product} and the approved {target} at a safe distance. Both already exist in frame one.", initial=s1, resulting=list(s1), visibility="product and target visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.0, 2.0, f"Remove the cap and expose the nozzle while retaining {cap} custody in the other hand.", initial=s1, resulting=s2r, visibility=f"{cap} remains visible", rules=["component custody retained"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.0, 4.0, f"Aim once and perform one controlled spray toward the same {target}. Intent: {intent}. No fake particles, extra bursts, or second bottle.", initial=s2r, resulting=s3r, visibility="continuous shot through the spray", rules=["one spray only"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.0, 5.5, f"Lower the {product} and stop spraying. The same hand still owns the bottle.", initial=s3r, resulting=s4r, visibility="product still in the same hand", rules=["no hand swap"], sources=src, transition=f"{tr}:s",),
        _step(5, 5.5, 7.0, f"Replace the same {cap} on the nozzle. Do not duplicate or lose the cap.", initial=s4r, resulting=s5r, visibility="recapped product visible", rules=["explicit recap"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.0, 8.0, f"Hold the {product} label-forward in the final state. No new prop.", initial=s5r, resulting=list(s5r), visibility="final label-forward hold", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _food_cook(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="FOOD_COOK",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, cap, receiver = spec.product, spec.component, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "counter, label-forward", "TABLE", True, f"closed {product} already present"),
        _st("component", f"on {product}", "TABLE", True, f"{cap} seated"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} already present"),
        _st("utensil", "beside pack", "TABLE", True, "declared utensil already present"),
    ]
    s2r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} opened"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} custody retained"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} fixed"),
        _st("utensil", "active hand", "ACTIVE_HAND", True, "same utensil"),
    ]
    s3r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} after one portion"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still declared"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"one normal portion now in {receiver}"),
        _st("utensil", "in receiver", "ACTIVE_HAND", True, "same utensil after transfer"),
    ]
    s4r = [
        _st("product", "counter, label-forward", "TABLE", True, f"{product} placed label-forward"),
        _st("component", "reseated on the product", "TABLE", True, f"{cap} resolved"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} still holds the portion"),
        _st("utensil", "in receiver", "TABLE", True, "utensil visible"),
    ]
    s5r = [
        _st("product", "counter, label-forward", "TABLE", True, f"{product} stationary beside the dish"),
        _st("component", "reseated on the product", "TABLE", True, f"{cap} unchanged"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"only the declared food action completed in {receiver}"),
        _st("utensil", "in receiver", "TABLE", True, "same utensil"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the {product}, utensil, and {receiver}. All three are already present.", initial=s1, resulting=list(s1), visibility="pack, utensil, and receiver visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.0, 2.2, f"Open the {product} while retaining {cap} custody.", initial=s1, resulting=s2r, visibility=f"{cap} stays visible", rules=["component custody retained"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.2, 4.0, f"Transfer one normal portion into the same {receiver}. Intent: {intent}.", initial=s2r, resulting=s3r, visibility="continuous transfer coverage", rules=["one portion only"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.0, 5.0, f"Set the {product} label-forward in a visible location. Do not hide the pack.", initial=s3r, resulting=s4r, visibility="pack remains visible", rules=["explicit placement"], sources=src, transition=f"{tr}:s",),
        _step(5, 5.0, 7.2, f"Stir only the declared food action. The original {product} stays visible.", initial=s4r, resulting=s5r, visibility="product remains in frame during the food action", rules=["no off-camera pack move"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.2, 8.0, f"Hold the finished context with the original {product} still visible.", initial=s5r, resulting=list(s5r), visibility="finished context plus original product", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _open_close(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="OPEN_CLOSE",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, cap = spec.product, spec.component
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"closed {product} already visible"),
        _st("component", f"seated on {product}", "SUPPORT_HAND", True, f"{cap} closed"),
    ]
    s2r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} stabilized by support hand"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened once and held"),
    ]
    s3r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} still in support hand"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} kept in the same active hand"),
    ]
    s4r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"only the declared reveal shown on {product}"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} still declared"),
    ]
    s5r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} reclosed/resealed"),
        _st("component", "reseated", "SUPPORT_HAND", True, f"same {cap} returned"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the closed {product}. Opening mechanism and both hands are already in frame.", initial=s1, resulting=list(s1), visibility="closed product visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.2, 3.0, f"The active hand opens once while the support hand stabilizes the {product}. Intent: {intent}.", initial=s1, resulting=s2r, visibility="both hands and product visible", rules=["support hand never releases mid-opening"], sources=src, transition=f"{tr}:s",),
        _step(3, 3.0, 4.5, f"Keep the {cap} in the same active hand. Do not lose or duplicate it.", initial=s2r, resulting=s3r, visibility=f"{cap} remains visible", rules=["component custody retained"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.5, 6.2, f"Perform only the declared reveal. No invented parts or extra openings.", initial=s3r, resulting=s4r, visibility="product and component visible during reveal", rules=["declared reveal only"], sources=src, transition=f"{tr}:s",),
        _step(5, 6.2, 7.3, f"Reclose using the same {cap}.", initial=s4r, resulting=s5r, visibility="final package state resolving the component", rules=["explicit reclose"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.3, 8.0, "Hold the final package state. No missing or duplicate cap/lid/wrapper.", initial=s5r, resulting=list(s5r), visibility="final package state held", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _prop_transfer(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="PROP_TRANSFER",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, dest = spec.product, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "source location", "TABLE", True, f"{product} already at its source"),
        _st("destination", dest, "FRAME_STATIC", True, f"{dest} already visible"),
    ]
    s2r = [
        _st("product", "active hand", "ACTIVE_HAND", True, f"same {product} grasped and oriented"),
        _st("destination", dest, "FRAME_STATIC", True, f"{dest} unchanged"),
    ]
    s3r = [
        _st("product", dest, "SURFACE", True, f"same {product} moved to {dest} in one continuous motion"),
        _st("destination", dest, "FRAME_STATIC", True, f"{dest} now supporting the product"),
    ]
    s4r = [
        _st("product", dest, "SURFACE", True, f"{product} released only after support is clear"),
        _st("destination", dest, "FRAME_STATIC", True, f"{dest} holds the product"),
    ]
    s5r = [
        _st("product", dest, "SURFACE", True, f"{product} identity unchanged after one small adjustment"),
        _st("destination", dest, "FRAME_STATIC", True, f"{dest} unchanged"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the {product} and the {dest}. Source and destination are both already visible.", initial=s1, resulting=list(s1), visibility="source and destination in frame", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.2, 2.5, f"Grasp and orient the same {product}. No second copy appears.", initial=s1, resulting=s2r, visibility="same product in hand", rules=["no product duplication"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.5, 5.0, f"Place the same {product} onto the {dest} in one continuous motion. Intent: {intent}.", initial=s2r, resulting=s3r, visibility="continuous transfer", rules=["explicit placement", "no cut during transfer"], sources=src, transition=f"{tr}:s",),
        _step(4, 5.0, 6.2, "Release hands only after physical support is clear.", initial=s3r, resulting=s4r, visibility="product supported at destination", rules=["explicit release"], sources=src, transition=f"{tr}:s",),
        _step(5, 6.2, 7.2, "Make one small adjustment without changing identity.", initial=s4r, resulting=s5r, visibility="same product at destination", rules=["identity preserved"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.2, 8.0, f"Hold the completed arrangement. The same {product} remains at the {dest}.", initial=s5r, resulting=list(s5r), visibility="completed arrangement held", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _static_lock(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="STATIC_LOCK",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product = spec.product
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "support hand, label/feature visible", "SUPPORT_HAND", True, f"complete static {product} already present"),
        _st("support", "declared table surface", "FRAME_STATIC", True, "original support already in frame"),
    ]
    s2r = [
        _st("product", "same support/hand after one show/point/rotate", "SUPPORT_HAND", True, f"{product} shown once without opening or inventing parts"),
        _st("support", "declared table surface", "FRAME_STATIC", True, "support unchanged"),
    ]
    s3r = [
        _st("product", "returned to original table surface", "TABLE", True, f"{product} back on the original support"),
        _st("support", "declared table surface", "FRAME_STATIC", True, "same support"),
    ]
    return [
        _step(1, 0.0, 1.5, f"Establish the complete static setup. The {product} and support are already present, label/feature visible.", initial=s1, resulting=list(s1), visibility="complete static setup visible", rules=["first-frame presence", "global continuity lock"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.5, 4.5, f"Rotate the product once without opening, transferring, or inventing parts. Intent: {intent}. One controlled hand path only.", initial=s1, resulting=s2r, visibility="one hand path, no extra fingers or duplicate parts", rules=["one slow motivated rotate"], sources=src, transition=f"{tr}:s",),
        _step(3, 4.5, 6.5, "Return the product to the original table surface. No off-camera hand swap.", initial=s2r, resulting=s3r, visibility="product returns to the same support", rules=["explicit return"], sources=src, transition=f"{tr}:s",),
        _step(4, 6.5, 8.0, "Hold the final label/feature view. Match-cut lock: pose, grip, and component state stay identical.", initial=s3r, resulting=list(s3r), visibility="final label/feature view held", rules=["final-state lock", "match-cut lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _device_control(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="DEVICE_CONTROL",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, control = spec.product, spec.component
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "stable compatible surface", "SURFACE", True, f"{product} already assembled and placed"),
        _st("control", f"on {product}", "ATTACHED", True, f"single verified {control} already visible"),
    ]
    s2r = [
        _st("product", "stable compatible surface", "SURFACE", True, f"{product} unmoved"),
        _st("control", "approached by active hand", "ATTACHED", True, f"hand approaching the same {control}"),
    ]
    s3r = [
        _st("product", "stable compatible surface", "SURFACE", True, f"{product} shows only the expected indicator/response"),
        _st("control", "pressed/turned once", "ATTACHED", True, f"{control} actuated once"),
    ]
    s4r = [
        _st("product", "stable compatible surface", "SURFACE", True, f"{product} remains fixed"),
        _st("control", "released", "ATTACHED", True, f"{control} released, still attached"),
    ]
    s5r = [
        _st("product", "stable compatible surface", "SURFACE", True, f"{product} returned to the declared safe/off state when required"),
        _st("control", "at rest", "ATTACHED", True, f"{control} at rest"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the {product} and safe environment. Cable/power state is explicit. Nothing is invented.", initial=s1, resulting=list(s1), visibility="device and control already visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.2, 2.5, f"The active hand approaches the single verified {control}. The support hand stays fixed.", initial=s1, resulting=s2r, visibility="one active hand only", rules=["no extra hands"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.5, 4.5, f"Press the {control} once and show only the expected indicator response. Intent: {intent}. No invented UI.", initial=s2r, resulting=s3r, visibility="lock framing across the control action", rules=["one actuation"], sources=src, transition=f"{tr}:s",),
        _step(4, 4.5, 6.2, "Release the control and keep the device fixed.", initial=s3r, resulting=s4r, visibility="device location unchanged", rules=["device stays put"], sources=src, transition=f"{tr}:s",),
        _step(5, 6.2, 7.2, "Return to the safe/off state when required. No hidden power or cable change.", initial=s4r, resulting=s5r, visibility="declared power state visible", rules=["explicit safe/off"], sources=src, transition=f"{tr}:s",),
        _step(6, 7.2, 8.0, "Hold the final device state. No new parts.", initial=s5r, resulting=list(s5r), visibility="final device state held", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _manipulation(spec: StrategySpec, *, scene: str, intent: str, action_index: int = 0) -> list[ChoreographyStep]:
    scenario = resolve_intent_scenario(
        strategy_id="",
        family="MANIPULATION",
        intent=intent,
        default_target=spec.target,
        default_receiver=spec.receiver,
        action_index=action_index,
    )
    product, target = spec.product, scenario.physical_target
    src, tr = [action_index], scenario.transition_key
    s1 = [
        _st("product", "stable orientation", "TABLE", True, f"{product} already visible, stable, correctly oriented"),
        _st("target", target, "FRAME_STATIC", True, f"{target} already visible"),
    ]
    s2r = [
        _st("product", "active hand", "ACTIVE_HAND", True, f"declared grip taken on {product}"),
        _st("target", target, "FRAME_STATIC", True, f"{target} fixed"),
    ]
    s3r = [
        _st("product", "active hand", "ACTIVE_HAND", True, f"one controlled manipulation completed on {product}"),
        _st("target", target, "FRAME_STATIC", True, f"{target} still present"),
    ]
    s4r = [
        _st("product", "stable position", "TABLE", True, f"{product} returned to a stable position"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the {product} and {target}. Both are already visible and correctly oriented.", initial=s1, resulting=list(s1), visibility="product and target visible", rules=["first-frame presence"], sources=src, transition=f"{tr}:s",),
        _step(2, 1.2, 2.5, "The active hand takes the declared grip. Any support hand stays fixed.", initial=s1, resulting=s2r, visibility="declared grip visible", rules=["one active hand"], sources=src, transition=f"{tr}:s",),
        _step(3, 2.5, 5.2, f"Perform one controlled manipulation only. Intent: {intent}. Do not invent a second {product}.", initial=s2r, resulting=s3r, visibility="continuous action coverage", rules=["one manipulation"], sources=src, transition=f"{tr}:s",),
        _step(4, 5.2, 6.5, f"Stop and return the {product} to a stable position.", initial=s3r, resulting=s4r, visibility="product stable again", rules=["explicit return"], sources=src, transition=f"{tr}:s",),
        _step(5, 6.5, 8.0, "Hold the resulting state with all props visible.", initial=s4r, resulting=list(s4r), visibility="all props visible in the hold", rules=["final-state lock"], final=True, sources=src, transition=f"{tr}:s",),
    ]


def _herbal_oil_steps() -> list[ChoreographyStep]:
    return herbal_oil_steps_composed()


def _roll_on_steps() -> list[ChoreographyStep]:
    return roll_on_steps_composed()


def _broll_steps(spec: StrategySpec) -> list[ChoreographyStep]:
    product = spec.product
    src: list[int] = []
    tr = "broll"
    s1 = [
        _st("product", "table, label-forward", "TABLE", True, f"{product} already on the table"),
        _st("component", "seated", "TABLE", True, f"{spec.component} seated"),
    ]
    outgoing = [
        _st("product", "table, label-forward", "TABLE", True, f"outgoing state: {product} still on the table, closed"),
        _st("component", "seated", "TABLE", True, "outgoing state: component seated"),
    ]
    incoming = [
        _st("product", "table, label-forward", "TABLE", True, f"re-established incoming state: same {product} on the same table, closed"),
        _st("component", "seated", "TABLE", True, "re-established incoming state: same component seated"),
    ]
    return [
        _step(1, 0.0, 1.5, f"Establish the {product} already on the table, label-forward. No object enters after frame one.", initial=s1, resulting=list(s1), visibility="product already present", rules=["first-frame presence"], sources=[], transition="broll:step",),
        _step(2, 1.5, 3.5, "Hold a continuous product-detail beat. No opening, transfer, or invented part.", initial=s1, resulting=list(s1), visibility="continuous product detail", rules=["no illegal state change"], sources=[], transition="broll:step",),
        _step(3, 3.5, 4.0, "Declare the outgoing state before the B-roll cut: same product, same location, same closed state.", initial=s1, resulting=outgoing, visibility="outgoing state fully declared", rules=["cut outgoing state declared"], cut="OUTGOING", sources=[], transition="broll:step",),
        _step(4, 4.0, 6.5, "After the cut, re-establish the compatible incoming state before any further interaction. Same product, table, and closed state.", initial=outgoing, resulting=incoming, visibility="incoming state re-established", rules=["cut re-establish required"], cut="REESTABLISH", sources=[], transition="broll:step",),
        _step(5, 6.5, 8.0, "Hold the re-established final state. The cut must not hide teleportation, duplication, or a hand swap.", initial=incoming, resulting=list(incoming), visibility="final re-established hold", rules=["final-state lock", "cut cannot hide illegal change"], final=True, sources=[], transition="broll:step",),
    ]


_BUILDERS = {
    "APPLY_CONTACT": _apply_contact,
    "MATERIAL_TRANSFER": _material_transfer,
    "SPRAY": _spray,
    "FOOD_COOK": _food_cook,
    "OPEN_CLOSE": _open_close,
    "PROP_TRANSFER": _prop_transfer,
    "STATIC_LOCK": _static_lock,
    "DEVICE_CONTROL": _device_control,
    "MANIPULATION": _manipulation,
    "HERBAL_OIL": lambda spec, scene="", intent="", action_index=0, **_: _herbal_oil_steps(),
    "ROLL_ON": lambda spec, scene="", intent="", action_index=0, **_: _roll_on_steps(),
}


P2 = "P2_STATIC"
P1 = "P1_REWRITE"
P0 = "P0_REWRITE"

SPECS: dict[str, StrategySpec] = {
    "LIP_COLOR": StrategySpec(P0, "APPLY_CONTACT", "lip colour product", "applicator cap", "lips", "lips"),
    "BEAUTY_PERSONAL_CARE": StrategySpec(P0, "MATERIAL_TRANSFER", "beauty product", "cap/lid", "clean fingertip", "clean fingertip"),
    "CLEANSER": StrategySpec(P0, "MATERIAL_TRANSFER", "cleanser", "dispenser cap", "demonstration palette", "demonstration palette"),
    "SERUM": StrategySpec(P0, "MATERIAL_TRANSFER", "serum", "dropper cap", "demonstration palette", "demonstration palette"),
    "FRAGRANCE": StrategySpec(P0, "SPRAY", "fragrance bottle", "cap", "wrist", "wrist"),
    "SPICE_SEASONING": StrategySpec(P0, "FOOD_COOK", "seasoning pack", "lid", "pan", "pan"),
    "PACKAGED_SAUCE_SAMBAL": StrategySpec(P0, "FOOD_COOK", "sauce pack", "lid", "dish", "dish"),
    "PACKAGED_FOOD": StrategySpec(P0, "FOOD_COOK", "packaged food", "seal/lid", "serving dish", "serving dish"),
    "LAUNDRY_DETERGENT": StrategySpec(P0, "MATERIAL_TRANSFER", "detergent pack", "cap", "washer drawer", "washer drawer"),
    "FABRIC_SOFTENER": StrategySpec(P0, "MATERIAL_TRANSFER", "softener bottle", "cap", "washer compartment", "washer compartment"),
    "BABY_WIPES": StrategySpec(P0, "MATERIAL_TRANSFER", "wipes pack", "resealable lid", "clean table", "clean table"),
    "BABY_DIAPER": StrategySpec(P1, "OPEN_CLOSE", "diaper pack", "pack opening", "clean table", "clean table"),
    "APPAREL": StrategySpec(P0, "PROP_TRANSFER", "garment", "hanger", "body/hanger", "hanger"),
    "MODESTWEAR": StrategySpec(P0, "PROP_TRANSFER", "modest garment", "hanger", "body/hanger", "body"),
    "SPORTSWEAR": StrategySpec(P1, "PROP_TRANSFER", "sportswear garment", "hanger", "body", "body"),
    "HOUSEHOLD_CLEANER": StrategySpec(P0, "APPLY_CONTACT", "household cleaner", "nozzle/cap", "suitable household surface", "suitable surface"),
    "HOUSEHOLD_STORAGE": StrategySpec(P1, "OPEN_CLOSE", "storage organizer", "lid/door", "shelf", "shelf"),
    "ELECTRONICS_ACCESSORY": StrategySpec(P1, "PROP_TRANSFER", "electronics accessory", "connector", "compatible device", "compatible device"),
    "ELECTRONICS_SMALL_DEVICE": StrategySpec(P0, "DEVICE_CONTROL", "small device", "power button", "stable desk", "stable desk"),
    "TRADITIONAL_HERBAL_OIL": StrategySpec(P0, "HERBAL_OIL", "heritage oil bottle", "cap", "adult wrist/forearm", "table"),
    "HERBAL_ROLL_ON_OIL": StrategySpec(P0, "ROLL_ON", "herbal roll-on", "cap", "adult wrist/forearm", "table"),
    "SENSITIVE_WELLNESS": StrategySpec(P1, "STATIC_LOCK", "sealed sensitive product", "outer pack", "private tabletop", "private tabletop"),
    "BOTTOM_APPAREL": StrategySpec(P2, "STATIC_LOCK", "bottom garment", "hanger", "hanger display", "hanger"),
    "BODY_CLEANSER": StrategySpec(P0, "MATERIAL_TRANSFER", "body cleanser", "dispenser cap", "wet palm", "wet palm"),
    "FACIAL_CLEANSER": StrategySpec(P0, "MATERIAL_TRANSFER", "facial cleanser", "cap", "clean fingertips", "clean fingertips"),
    "COMPLEXION_MAKEUP": StrategySpec(P0, "APPLY_CONTACT", "complexion makeup", "applicator/cap", "jawline", "jawline"),
    "NAIL_COLOR": StrategySpec(P0, "APPLY_CONTACT", "nail colour bottle", "brush cap", "clean fingernail", "clean fingernail"),
    "FACIAL_SERUM": StrategySpec(P0, "MATERIAL_TRANSFER", "facial serum", "dropper cap", "back of a clean hand", "back of a clean hand"),
    "MASCARA": StrategySpec(P0, "APPLY_CONTACT", "mascara tube", "wand", "upper lashes", "upper lashes"),
    "EYELINER": StrategySpec(P0, "APPLY_CONTACT", "eyeliner", "cap/tip cover", "external upper lash line", "external upper lash line"),
    "WELLNESS_SUPPLEMENT": StrategySpec(P1, "STATIC_LOCK", "sealed supplement pack", "seal", "glass of water nearby", "table beside water"),
    "PACKAGED_SNACK": StrategySpec(P0, "MATERIAL_TRANSFER", "snack pack", "seal", "clean bowl", "clean bowl"),
    "PET_FOOD": StrategySpec(P0, "MATERIAL_TRANSFER", "pet food pack", "seal", "clean pet bowl", "clean pet bowl"),
    "PACKAGED_BEVERAGE": StrategySpec(P0, "MATERIAL_TRANSFER", "beverage pack", "seal/cap", "clean glass", "clean glass"),
    "PANTRY_INGREDIENT": StrategySpec(P0, "FOOD_COOK", "pantry ingredient", "pack seal", "prepared dish", "prepared dish"),
    "BEDDING": StrategySpec(P1, "PROP_TRANSFER", "bedding", "fold", "clean bed", "clean bed"),
    "RUG_MAT": StrategySpec(P1, "PROP_TRANSFER", "rug", "roll", "clean dry floor", "clean dry floor"),
    "BOOK": StrategySpec(P2, "STATIC_LOCK", "book", "cover", "reading position", "table"),
    "HOME_FAN": StrategySpec(P0, "DEVICE_CONTROL", "home fan", "control", "stable surface", "stable surface"),
    "VACUUM_CLEANER": StrategySpec(P0, "DEVICE_CONTROL", "vacuum cleaner", "control", "dry compatible floor", "dry compatible floor"),
    "VACUUM_SEALER": StrategySpec(P0, "DEVICE_CONTROL", "vacuum sealer", "lid/control", "kitchen counter", "kitchen counter"),
    "GENERIC_FALLBACK": StrategySpec("BLOCK", "STATIC_LOCK", "unclassified product", "packaging", "everyday context", "everyday context"),  # type: ignore[arg-type]
    "FACE_MASK": StrategySpec(P0, "APPLY_CONTACT", "face mask packet", "packet opening", "external facial skin avoiding eyes and lips", "external face"),
    "MOISTURIZER": StrategySpec(P0, "MATERIAL_TRANSFER", "moisturizer", "dispenser cap", "clean external skin", "clean external skin"),
    "SUNSCREEN": StrategySpec(P0, "APPLY_CONTACT", "sunscreen", "cap", "external skin as directed", "external skin"),
    "EYE_TREATMENT": StrategySpec(P0, "MATERIAL_TRANSFER", "eye treatment", "applicator cap", "outer orbital area avoiding the eye", "outer orbital area"),
    "MAKEUP_SETTING_SPRAY": StrategySpec(P0, "SPRAY", "setting spray", "cap", "external face with eyes and mouth closed", "external face"),
    "EYEBROW_MAKEUP": StrategySpec(P0, "APPLY_CONTACT", "eyebrow makeup", "cap", "external eyebrow", "external eyebrow"),
    "EYESHADOW": StrategySpec(P0, "APPLY_CONTACT", "eyeshadow palette", "lid", "external eyelid with the eye closed", "external eyelid"),
    "FALSE_EYELASHES": StrategySpec(P0, "PROP_TRANSFER", "lash strip", "pack", "closed eyelid for measuring only", "closed eyelid"),
    "FACE_PRIMER": StrategySpec(P0, "MATERIAL_TRANSFER", "face primer", "dispenser cap", "clean external facial skin", "clean external facial skin"),
    "MAKEUP_SET": StrategySpec(P1, "PROP_TRANSFER", "makeup set items", "case", "clean vanity layout", "vanity"),
    "FACE_POWDER": StrategySpec(P0, "APPLY_CONTACT", "face powder", "compact lid", "external facial skin", "external facial skin"),
    "BODY_OIL": StrategySpec(P0, "MATERIAL_TRANSFER", "body oil bottle", "cap", "adult forearm", "adult forearm"),
    "BODY_EXFOLIANT": StrategySpec(P0, "MATERIAL_TRANSFER", "body exfoliant", "cap", "wet adult forearm", "wet adult forearm"),
    "DEODORANT": StrategySpec(P1, "OPEN_CLOSE", "deodorant", "applicator cap", "product-only table", "table"),
    "HAIR_WASH": StrategySpec(P0, "MATERIAL_TRANSFER", "hair-wash bottle", "cap", "wet palm", "wet palm"),
    "HAIR_COLOR": StrategySpec(P2, "STATIC_LOCK", "sealed hair-colour kit", "sealed components", "protected surface", "protected surface"),
    "HAIR_TREATMENT": StrategySpec(P0, "MATERIAL_TRANSFER", "hair treatment", "cap", "hair lengths", "hair lengths"),
    "MAKEUP_REMOVER": StrategySpec(P0, "MATERIAL_TRANSFER", "makeup remover", "cap", "clean cotton pad", "clean cotton pad"),
    "LIP_TREATMENT": StrategySpec(P0, "MATERIAL_TRANSFER", "lip treatment", "cap", "external lips", "external lips"),
    "ORAL_CARE": StrategySpec(P0, "MANIPULATION", "oral-care product", "cap", "toothbrush", "toothbrush"),
    "FEMININE_HYGIENE": StrategySpec(P1, "STATIC_LOCK", "sealed feminine-hygiene pack", "wrapper", "clean table", "clean table"),
    "TOP_APPAREL": StrategySpec(P2, "STATIC_LOCK", "top garment", "hanger", "hanger display", "hanger"),
    "UNDERGARMENT": StrategySpec(P2, "STATIC_LOCK", "undergarment", "size label", "flat lay", "flat lay"),
    "SLEEPWEAR": StrategySpec(P2, "STATIC_LOCK", "sleepwear", "hanger", "hanger", "hanger"),
    "DRESS": StrategySpec(P2, "STATIC_LOCK", "dress", "hanger", "hanger display", "hanger"),
    "FOOTWEAR": StrategySpec(P2, "STATIC_LOCK", "footwear pair", "size label", "table display", "table"),
    "FROZEN_FOOD": StrategySpec(P0, "STATIC_LOCK", "sealed frozen-food pack", "seal", "label-directed cooking setup", "counter"),
    "CURTAIN": StrategySpec(P1, "PROP_TRANSFER", "curtain panel", "heading", "compatible rod", "compatible rod"),
    "WALL_COVERING": StrategySpec(P0, "PROP_TRANSFER", "wall-covering sample", "backing", "clean dry compatible surface", "compatible surface"),
    "KNITTING_CROCHET": StrategySpec(P1, "MANIPULATION", "yarn and hook", "label", "small sample", "small sample"),
    "CAR_CARE": StrategySpec(P0, "MATERIAL_TRANSFER", "car-care product", "cap", "clean detached sample panel", "sample panel"),
    "BABY_FEEDING": StrategySpec(P1, "STATIC_LOCK", "baby-feeding item", "sealed parts", "clean table", "clean table"),
    "BABY_SKINCARE": StrategySpec(P0, "MATERIAL_TRANSFER", "baby skincare pack", "cap", "adult hand only", "adult hand"),
    "BATH_LINEN": StrategySpec(P0, "PROP_TRANSFER", "bath linen", "care label", "folded display", "table"),
    "STATIONERY": StrategySpec(P1, "MANIPULATION", "stationery item", "pack", "clean desk", "desk"),
    "FASHION_ACCESSORY": StrategySpec(P0, "PROP_TRANSFER", "fashion accessory", "fastening", "detached compatible fabric swatch", "fabric swatch"),
    "HEALTH_TEST_DEVICE": StrategySpec(P2, "STATIC_LOCK", "sealed health-test pack", "unopened components", "clean table", "clean table"),
    "OUTDOOR_LIGHTING": StrategySpec(P0, "DEVICE_CONTROL", "outdoor light", "control", "controlled low-light area", "safe surface"),
    "PLANT_CARE": StrategySpec(P0, "MATERIAL_TRANSFER", "plant-care pack", "seal", "measuring cup, not a live plant", "measuring cup"),
    "ELECTRICAL_DEVICE": StrategySpec(P2, "STATIC_LOCK", "unpowered electrical device", "plug", "inspection table", "table"),
    "CLEANING_TOOL": StrategySpec(P1, "MANIPULATION", "cleaning tool", "pack", "small clean dry sample surface", "sample surface"),
    "FOOD_COVER": StrategySpec(P1, "PROP_TRANSFER", "food cover", "pack", "empty compatible container", "empty container"),
    "HOME_DECOR": StrategySpec(P1, "PROP_TRANSFER", "home decor item", "mount", "compatible sample display surface", "display surface"),
    "COOKWARE": StrategySpec(P0, "MANIPULATION", "empty cookware", "lid", "cold compatible hob, switched off", "cold hob"),
    "DRINKWARE": StrategySpec(P1, "STATIC_LOCK", "empty drinkware", "lid", "dry assembly table", "table"),
    "SMALL_LIGHT": StrategySpec(P0, "DEVICE_CONTROL", "small USB light", "control", "compatible test power source", "desk"),
    "BLUSH": StrategySpec(P0, "APPLY_CONTACT", "blush", "applicator", "clean adult forearm", "adult forearm"),
    "FISHING_GEAR": StrategySpec(P0, "DEVICE_CONTROL", "fishing reel", "handle/drag", "safe dry bench", "bench"),
    "FITNESS_EQUIPMENT": StrategySpec(P1, "STATIC_LOCK", "fitness equipment", "adjustment", "off the doorway", "floor"),
    "AUTOMOTIVE_ACCESSORY": StrategySpec(P0, "PROP_TRANSFER", "automotive accessory", "mount", "detached sample surface", "sample surface"),
    "AUDIO_DEVICE": StrategySpec(P0, "DEVICE_CONTROL", "audio device", "power control", "table, not worn", "table"),
    "SEWING_TOOL": StrategySpec(P1, "STATIC_LOCK", "sewing tool pack", "case", "magnetic-safe work mat", "work mat"),
    "PET_CAGE_ACCESSORY": StrategySpec(P1, "PROP_TRANSFER", "cage liner", "pack", "clean empty cage base", "empty cage base"),
    "PET_LITTER": StrategySpec(P0, "MATERIAL_TRANSFER", "pet litter pack", "seal", "clean empty sample tray", "sample tray"),
    "CRAFT_MATERIAL": StrategySpec(P2, "STATIC_LOCK", "sealed craft components", "unopened packs", "protected surface", "protected surface"),
    "PERSONAL_CARE_DEVICE": StrategySpec(P0, "DEVICE_CONTROL", "personal-care device", "control", "away from hair and skin", "table"),
    "BODY_MOISTURIZER": StrategySpec(P0, "APPLY_CONTACT", "body moisturizer", "cap", "clean adult hand", "adult hand"),
    "BODY_BATH": StrategySpec(P0, "MATERIAL_TRANSFER", "bath product", "seal", "dry measuring cup, no bath prepared", "measuring cup"),
    "CLEANING_EQUIPMENT": StrategySpec(P0, "DEVICE_CONTROL", "cleaning equipment", "control", "safe dry bench, no debris", "bench"),
    "PEST_CONTROL": StrategySpec(P2, "STATIC_LOCK", "sealed pest-control pack", "unopened pack", "labelled placement diagram only", "table"),
    "KITCHEN_TOOL": StrategySpec(P1, "STATIC_LOCK", "kitchen tool", "components", "clean dry assembly table", "table"),
}


def _aligned(entry: SceneStrategyEntry, index: int, key: str) -> str:
    values = list(entry[key])  # type: ignore[literal-required]
    return str(values[index % len(values)])


def _build_strategy_variants(strategy_id: str) -> list[ChoreographyVariant]:
    if strategy_id == "GENERIC_FALLBACK":
        return []
    spec = SPECS[strategy_id]
    entry = SCENE_STRATEGIES[strategy_id]
    scenes = list(entry["allowed_scene_strategy"])
    contexts = list(entry["scene_contexts"])
    cameras = list(entry["camera_routes"])
    actions = list(entry["allowed_actions"])
    variants: list[ChoreographyVariant] = []

    if spec.family in COMPOSED_FAMILIES:
        builder = _BUILDERS[spec.family]
        steps = builder(spec, scene=scenes[0], intent="|".join(actions), action_index=0)
        variants.append(
            _variant(
                strategy_id=strategy_id,
                index=0,
                spec=spec,
                family=spec.family,
                scene=scenes[0],
                context=contexts[0],
                camera=cameras[0],
                intent="composed sequence: " + " -> ".join(actions),
                steps=steps,
                extra_contexts=contexts,
                extra_cameras=cameras,
            )
        )
        return variants

    special = SPECIAL_STRATEGY_BUILDERS.get(strategy_id)
    builder = _BUILDERS[spec.family]
    for index, intent in enumerate(actions):
        scene = scenes[index % len(scenes)]
        context = contexts[index % len(contexts)]
        camera = cameras[index % len(cameras)]
        if special is not None:
            steps = special(index, intent)
        else:
            steps = builder(spec, scene=scene, intent=intent, action_index=index)
        variants.append(
            _variant(
                strategy_id=strategy_id,
                index=index,
                spec=spec,
                family=spec.family,
                scene=scene,
                context=context,
                camera=camera,
                intent=intent,
                steps=steps,
                extra_contexts=contexts,
                extra_cameras=cameras,
            )
        )
    if strategy_id == "HOUSEHOLD_CLEANER":
        variants.append(
            _variant(
                strategy_id=strategy_id,
                index=len(variants),
                spec=spec,
                family="BROLL_MATCH_CUT",
                scene="label walkthrough with an explicit match-cut",
                context=contexts[0],
                camera=cameras[0],
                intent="show the label, cut, and re-establish the same closed product",
                steps=_broll_steps(spec),
                extra_contexts=contexts,
                extra_cameras=cameras,
                suffix="_broll",
            )
        )
    return variants


@lru_cache(maxsize=1)
def all_choreography_variants() -> dict[str, tuple[ChoreographyVariant, ...]]:
    missing = sorted(set(SCENE_STRATEGIES) - set(SPECS))
    extra = sorted(set(SPECS) - set(SCENE_STRATEGIES))
    if missing or extra:
        raise ChoreographyValidationError(
            "CHOREOGRAPHY_SPEC_INVENTORY_MISMATCH",
            details={"missing": missing, "extra": extra},
        )
    catalog: dict[str, tuple[ChoreographyVariant, ...]] = {}
    for strategy_id in SCENE_STRATEGIES:
        variants = tuple(_build_strategy_variants(strategy_id))
        for variant in variants:
            validate_choreography_variant(variant)
        catalog[strategy_id] = variants
    return catalog


def list_production_variants(strategy_id: str) -> tuple[ChoreographyVariant, ...]:
    validate_production_strategy_id(strategy_id)
    variants = all_choreography_variants().get(strategy_id, ())
    if not variants:
        raise ChoreographyValidationError(
            "NO_PRODUCTION_CHOREOGRAPHY",
            strategy_id=strategy_id,
        )
    return variants


def select_variant_for_strategy(strategy_id: str, variation_index: int) -> ChoreographyVariant:
    variants = list_production_variants(strategy_id)
    offset = max(int(variation_index), 0)
    return variants[offset % len(variants)]


def choreography_sha256(variant: ChoreographyVariant) -> str:
    return canonical_sha256(variant.model_dump(mode="json"))


def library_choreography_sha256() -> str:
    payload = {
        strategy_id: [variant.model_dump(mode="json") for variant in variants]
        for strategy_id, variants in all_choreography_variants().items()
    }
    return canonical_sha256(payload)


def _step_graph_fingerprint(variant: ChoreographyVariant) -> str:
    payload = []
    for step in variant.steps:
        payload.append(
            {
                "n": step.step_number,
                "sig": step.transition_signature,
                "src": list(step.source_action_indexes),
                "instruction": step.action_instruction,
                "initial": [
                    (s.entity_id, s.location, s.custody, s.visible, s.physical_state)
                    for s in step.initial_states
                ],
                "resulting": [
                    (s.entity_id, s.location, s.custody, s.visible, s.physical_state)
                    for s in step.resulting_states
                ],
            }
        )
    return canonical_sha256(payload)


def action_coverage_receipt() -> list[dict[str, object]]:
    """Semantic map of every atomic action to exact source-tagged steps."""

    catalog = all_choreography_variants()
    rows: list[dict[str, object]] = []
    for strategy_id, entry in SCENE_STRATEGIES.items():
        actions = list(entry["allowed_actions"])
        variants = [v for v in catalog[strategy_id] if v.family != "BROLL_MATCH_CUT"]
        if strategy_id == "GENERIC_FALLBACK":
            for index, action in enumerate(actions):
                rows.append(
                    {
                        "action_id": f"{strategy_id}:{index}",
                        "strategy_id": strategy_id,
                        "action_index": index,
                        "action_text": action,
                        "coverage_status": "BLOCKED",
                        "coverage_kind": "BLOCKED",
                        "coverage": "BLOCKED",
                        "choreography_ids": [],
                        "choreography_id": None,
                        "exact_step_numbers": [],
                        "step_numbers": [],
                        "structured_physical_target": None,
                        "structured_transition_signature": None,
                        "actor_hand_ownership": None,
                        "initial_location": None,
                        "resulting_location": None,
                        "component_custody": None,
                        "block_reason": "GENERIC_FALLBACK_BLOCKED",
                    }
                )
            continue

        spec = SPECS[strategy_id]
        composed = spec.family in COMPOSED_FAMILIES
        by_action: dict[int, list[tuple[ChoreographyVariant, ChoreographyStep]]] = {
            i: [] for i in range(len(actions))
        }
        for variant in variants:
            for step in variant.steps:
                for idx in step.source_action_indexes:
                    if idx in by_action:
                        by_action[idx].append((variant, step))

        fingerprints: dict[str, tuple[str, tuple[int, ...]]] = {}
        for variant in variants:
            fp = _step_graph_fingerprint(variant)
            covered = tuple(
                sorted({i for step in variant.steps for i in step.source_action_indexes})
            )
            prior = fingerprints.get(fp)
            if prior is not None and prior[1] != covered:
                raise ChoreographyValidationError(
                    "SEMANTIC_FINGERPRINT_COLLISION",
                    strategy_id=strategy_id,
                    details={
                        "a": prior[0],
                        "b": variant.choreography_id,
                        "covered_a": list(prior[1]),
                        "covered_b": list(covered),
                    },
                )
            fingerprints[fp] = (variant.choreography_id, covered)

        for index, action in enumerate(actions):
            hits = by_action[index]
            if not hits:
                raise ChoreographyValidationError(
                    "ATOMIC_ACTION_SEMANTIC_GAP",
                    strategy_id=strategy_id,
                    details={"action_index": index, "action": action},
                )
            choreography_ids = sorted({v.choreography_id for v, _ in hits})
            step_numbers = sorted({s.step_number for _, s in hits})
            primary = hits[0][1]
            product_states_i = [st for st in primary.initial_states if st.entity_id == "product"]
            product_states_r = [st for st in primary.resulting_states if st.entity_id == "product"]
            comp_states = [
                st for st in primary.resulting_states if st.entity_id in {"component", "control"}
            ]
            kind = (
                "COMPOSED_SEQUENCE"
                if composed
                else ("STATIC_LOCK" if spec.family == "STATIC_LOCK" else "ALTERNATIVE_VARIANT")
            )
            action_l = action.casefold()
            phys = " ".join(
                f"{st.entity_id}:{st.location}:{st.physical_state}"
                for st in primary.resulting_states
            ).casefold()
            if "back of the hand" in action_l and "back of the hand" not in phys:
                raise ChoreographyValidationError(
                    "ACTION_TARGET_INCOMPATIBLE",
                    strategy_id=strategy_id,
                    details={"action": action, "physics": phys},
                )
            if "handbag" in action_l and "handbag" not in phys and "bag" not in phys:
                raise ChoreographyValidationError(
                    "ACTION_TARGET_INCOMPATIBLE",
                    strategy_id=strategy_id,
                    details={"action": action, "physics": phys},
                )
            if "mirror" in action_l and "mirror" not in phys:
                raise ChoreographyValidationError(
                    "ACTION_TARGET_INCOMPATIBLE",
                    strategy_id=strategy_id,
                    details={"action": action, "physics": phys},
                )
            rows.append(
                {
                    "action_id": f"{strategy_id}:{index}",
                    "strategy_id": strategy_id,
                    "action_index": index,
                    "action_text": action,
                    "coverage_status": "COVERED",
                    "coverage_kind": kind,
                    "coverage": "EXPLICIT",
                    "choreography_ids": choreography_ids,
                    "choreography_id": choreography_ids[0],
                    "exact_step_numbers": step_numbers,
                    "step_numbers": step_numbers,
                    "structured_physical_target": (
                        product_states_r[0].location if product_states_r else None
                    ),
                    "structured_transition_signature": primary.transition_signature,
                    "actor_hand_ownership": f"{primary.support_hand}/{primary.active_hand}",
                    "initial_location": (
                        product_states_i[0].location if product_states_i else None
                    ),
                    "resulting_location": (
                        product_states_r[0].location if product_states_r else None
                    ),
                    "component_custody": (comp_states[0].custody if comp_states else None),
                    "block_reason": None,
                }
            )
    return rows


def coverage_map() -> list[dict[str, object]]:
    catalog = all_choreography_variants()
    rows: list[dict[str, object]] = []
    for strategy_id in SCENE_STRATEGIES:
        spec = SPECS[strategy_id]
        variants = catalog[strategy_id]
        status = "BLOCKED" if spec.classification == "BLOCK" else "MIGRATED"
        rows.append(
            {
                "strategy_id": strategy_id,
                "audit_classification": spec.classification,
                "family": spec.family,
                "migration_status": status,
                "choreography_variant_count": len(variants),
                "validation_status": "BLOCKED" if status == "BLOCKED" else "VALID",
                "production_eligible": status == "MIGRATED" and bool(variants),
            }
        )
    return rows


def assert_legacy_atomic_rejected(action_sequence: list[object]) -> None:
    if len(action_sequence) == 1:
        step = action_sequence[0]
        blob = ""
        if isinstance(step, dict):
            blob = " ".join(
                str(step.get(key) or "")
                for key in ("action_text", "initial_state", "resulting_state")
            )
        lowered = blob.casefold()
        if any(marker in lowered for marker in ("governed initial product state", "governed resulting product state")):
            raise ChoreographyValidationError("LEGACY_ATOMIC_TREATMENT_REJECTED")
        if "0.0" not in lowered and "first frame" not in lowered:
            raise ChoreographyValidationError("LEGACY_ATOMIC_TREATMENT_REJECTED")
