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
) -> ChoreographyStep:
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


def _apply_contact(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, cap, target = spec.product, spec.component, spec.target
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
        _st("product", "support hand or visible nearby", "SUPPORT_HAND", True, f"{product} identity unchanged"),
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
        _st("product", "table or support hand, label-forward", "TABLE", True, f"{product} closed or placed label-forward"),
        _st("component", "reseated on product", "TABLE", True, f"{cap} returned to the same {product}"),
        _st("target", target, "FRAME_STATIC", True, f"{target} unchanged after application"),
    ]
    s6i = s5r
    return [
        _step(1, 0.0, 1.0, f"The {product}, {cap}, and {target} are already present in the first frame. No object materializes after the scene begins.", initial=s1, resulting=list(s1), visibility="all required props and target visible", rules=["first-frame presence", "no thin-air entry"]),
        _step(2, 1.0, 2.3, f"The same two hands open or expose the {cap}. Keep the removed component visible. The {product} stays in the support hand.", initial=s2i, resulting=s2r, visibility=f"{product} and {cap} remain visible", rules=["component custody retained", "no hand swap"]),
        _step(3, 2.3, 4.5, f"Perform one controlled application pass only onto the same {target}. Do not invent extra applicators or a second product.", initial=s3i, resulting=s3r, visibility=f"{product}, {cap}, and {target} stay in frame", rules=["one pass only", "preserve product identity"]),
        _step(4, 4.5, 5.5, f"Stop contact with the {target} and return the {product} to a safe visible position.", initial=s4i, resulting=s4r, visibility="product and component remain visible after contact stops", rules=["explicit withdrawal"]),
        _step(5, 5.5, 7.0, f"Close or place the {product} label-forward. The same {cap} is reseated or left in its declared visible location.", initial=s5i, resulting=s5r, visibility="closed/placed product label-forward", rules=["explicit close/place"]),
        _step(6, 7.0, 8.0, "Hold the approved result context with no before/after transformation, no new prop, and no duplicate hand.", initial=s6i, resulting=list(s5r), visibility="final approved result held", rules=["final-state lock", "no new prop"], final=True),
    ]


def _material_transfer(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, cap, receiver = spec.product, spec.component, spec.receiver
    s1 = [
        _st("product", "upright in support hand or on table", "SUPPORT_HAND", True, f"closed/upright {product} already present"),
        _st("component", f"seated on {product}", "SUPPORT_HAND", True, f"{cap} closed and visible"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} already in frame"),
    ]
    s2r = [
        _st("product", "support hand, ready to dispense", "SUPPORT_HAND", True, f"{product} opened/readied"),
        _st("component", "active hand or visible table spot", "ACTIVE_HAND", True, f"{cap} custody retained"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} fixed"),
    ]
    s3r = [
        _st("product", "support hand over receiver", "SUPPORT_HAND", True, f"{product} after one controlled transfer"),
        _st("component", "active hand or visible table spot", "ACTIVE_HAND", True, f"{cap} still in declared custody"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"exactly one controlled amount now on {receiver}"),
    ]
    s4r = [
        _st("product", "upright in support hand", "SUPPORT_HAND", True, f"{product} flow stopped and upright"),
        _st("component", "active hand or visible table spot", "ACTIVE_HAND", True, f"{cap} unchanged"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"measured material remains only on {receiver}"),
    ]
    s5r = [
        _st("product", "table, label-forward", "TABLE", True, f"{product} closed or placed label-forward"),
        _st("component", "reseated or visibly placed", "TABLE", True, f"{cap} resolved"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} still holds the same amount"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the source {product} and the same {receiver}. Both are already present; nothing appears after the first frame.", initial=s1, resulting=list(s1), visibility="source and receiver visible", rules=["first-frame presence"]),
        _step(2, 1.0, 2.2, f"Open or ready the dispenser while retaining {cap} custody in the active hand or a declared visible place.", initial=s1, resulting=s2r, visibility=f"{cap} never leaves frame", rules=["component custody retained"]),
        _step(3, 2.2, 4.2, f"Transfer exactly one controlled amount to the same {receiver}. No airborne spray, extra stream, or second container.", initial=s2r, resulting=s3r, visibility="continuous coverage through the transfer", rules=["one controlled transfer", "no cut while material moves"]),
        _step(4, 4.2, 5.2, f"Stop the flow and return the {product} upright. The {receiver} stays fixed.", initial=s3r, resulting=s4r, visibility="source upright, receiver fixed", rules=["explicit stop-flow"]),
        _step(5, 5.2, 6.8, f"Close the {product} or place it label-forward. Resolve the same {cap}.", initial=s4r, resulting=s5r, visibility="closed/placed source still visible", rules=["explicit close/place"]),
        _step(6, 6.8, 8.0, f"Hold the source {product} and the {receiver} together in frame. No new prop or extra amount.", initial=s5r, resulting=list(s5r), visibility="source and result together", rules=["final-state lock"], final=True),
    ]


def _spray(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, cap, target = spec.product, spec.component, spec.target
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
        _st("product", "same hand or table, label-forward", "SUPPORT_HAND", True, f"{product} recapped/nozzle-safe"),
        _st("component", "reseated on product", "SUPPORT_HAND", True, f"same {cap} replaced"),
        _st("target", target, "FRAME_STATIC", True, f"{target} still in frame"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the closed {product} and the approved {target} at a safe distance. Both already exist in frame one.", initial=s1, resulting=list(s1), visibility="product and target visible", rules=["first-frame presence"]),
        _step(2, 1.0, 2.0, f"Remove or expose the nozzle while retaining {cap} custody in the other hand.", initial=s1, resulting=s2r, visibility=f"{cap} remains visible", rules=["component custody retained"]),
        _step(3, 2.0, 4.0, f"Aim once and perform one controlled spray toward the same {target}. No fake particles, extra bursts, or second bottle.", initial=s2r, resulting=s3r, visibility="continuous shot through the spray", rules=["one spray only"]),
        _step(4, 4.0, 5.5, f"Lower the {product} and stop spraying. The same hand still owns the bottle.", initial=s3r, resulting=s4r, visibility="product still in the same hand", rules=["no hand swap"]),
        _step(5, 5.5, 7.0, f"Replace the same {cap} or lock the nozzle. Do not duplicate or lose the cap.", initial=s4r, resulting=s5r, visibility="recapped product visible", rules=["explicit recap"]),
        _step(6, 7.0, 8.0, f"Hold the {product} label-forward in the final state. No new prop.", initial=s5r, resulting=list(s5r), visibility="final label-forward hold", rules=["final-state lock"], final=True),
    ]


def _food_cook(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, cap, receiver = spec.product, spec.component, spec.receiver
    s1 = [
        _st("product", "counter, label-forward", "TABLE", True, f"closed {product} already present"),
        _st("component", f"on {product}", "TABLE", True, f"{cap} seated"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} already present"),
        _st("utensil", "beside pack", "TABLE", True, "declared utensil already present"),
    ]
    s2r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} opened"),
        _st("component", "active hand or table", "ACTIVE_HAND", True, f"{cap} custody retained"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} fixed"),
        _st("utensil", "active or support hand", "ACTIVE_HAND", True, "same utensil"),
    ]
    s3r = [
        _st("product", "support hand or counter", "SUPPORT_HAND", True, f"{product} after one portion"),
        _st("component", "active hand or table", "ACTIVE_HAND", True, f"{cap} still declared"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"one normal portion now in {receiver}"),
        _st("utensil", "in or beside receiver", "ACTIVE_HAND", True, "same utensil after transfer"),
    ]
    s4r = [
        _st("product", "counter, label-forward", "TABLE", True, f"{product} placed label-forward"),
        _st("component", "reseated or visibly placed", "TABLE", True, f"{cap} resolved"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"{receiver} still holds the portion"),
        _st("utensil", "in receiver or on rest", "TABLE", True, "utensil visible"),
    ]
    s5r = [
        _st("product", "counter, label-forward", "TABLE", True, f"{product} stationary beside the dish"),
        _st("component", "reseated or visibly placed", "TABLE", True, f"{cap} unchanged"),
        _st("receiver", receiver, "FRAME_STATIC", True, f"only the declared food action completed in {receiver}"),
        _st("utensil", "in receiver or on rest", "TABLE", True, "same utensil"),
    ]
    return [
        _step(1, 0.0, 1.0, f"Establish the {product}, utensil, and {receiver}. All three are already present.", initial=s1, resulting=list(s1), visibility="pack, utensil, and receiver visible", rules=["first-frame presence"]),
        _step(2, 1.0, 2.2, f"Open the {product} while retaining {cap} custody.", initial=s1, resulting=s2r, visibility=f"{cap} stays visible", rules=["component custody retained"]),
        _step(3, 2.2, 4.0, f"Measure and transfer one normal portion into the same {receiver}.", initial=s2r, resulting=s3r, visibility="continuous transfer coverage", rules=["one portion only"]),
        _step(4, 4.0, 5.0, f"Set the {product} label-forward in a visible location. Do not hide the pack.", initial=s3r, resulting=s4r, visibility="pack remains visible", rules=["explicit placement"]),
        _step(5, 5.0, 7.2, f"Stir or complete only the declared food action. The original {product} stays visible.", initial=s4r, resulting=s5r, visibility="product remains in frame during the food action", rules=["no off-camera pack move"]),
        _step(6, 7.2, 8.0, f"Hold the finished context with the original {product} still visible.", initial=s5r, resulting=list(s5r), visibility="finished context plus original product", rules=["final-state lock"], final=True),
    ]


def _open_close(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, cap = spec.product, spec.component
    s1 = [
        _st("product", "support hand or table", "SUPPORT_HAND", True, f"closed {product} already visible"),
        _st("component", f"seated on {product}", "SUPPORT_HAND", True, f"{cap} closed"),
    ]
    s2r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} stabilized by support hand"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened once and held"),
    ]
    s3r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"{product} still in support hand"),
        _st("component", "active hand or table", "ACTIVE_HAND", True, f"{cap} kept in the same hand or placed visibly"),
    ]
    s4r = [
        _st("product", "support hand", "SUPPORT_HAND", True, f"only the declared reveal shown on {product}"),
        _st("component", "active hand or table", "ACTIVE_HAND", True, f"{cap} still declared"),
    ]
    s5r = [
        _st("product", "support hand or table", "SUPPORT_HAND", True, f"{product} reclosed/resealed"),
        _st("component", "reseated", "SUPPORT_HAND", True, f"same {cap} returned"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the closed {product}. Opening mechanism and both hands are already in frame.", initial=s1, resulting=list(s1), visibility="closed product visible", rules=["first-frame presence"]),
        _step(2, 1.2, 3.0, f"The active hand opens once while the support hand stabilizes the {product}.", initial=s1, resulting=s2r, visibility="both hands and product visible", rules=["support hand never releases mid-opening"]),
        _step(3, 3.0, 4.5, f"Keep the {cap} in the same hand or place it visibly. Do not lose or duplicate it.", initial=s2r, resulting=s3r, visibility=f"{cap} remains visible", rules=["component custody retained"]),
        _step(4, 4.5, 6.2, f"Perform only the declared reveal. No invented parts or extra openings.", initial=s3r, resulting=s4r, visibility="product and component visible during reveal", rules=["declared reveal only"]),
        _step(5, 6.2, 7.3, f"Reclose or reseal if required using the same {cap}.", initial=s4r, resulting=s5r, visibility="final package state resolving the component", rules=["explicit reclose"]),
        _step(6, 7.3, 8.0, "Hold the final package state. No missing or duplicate cap/lid/wrapper.", initial=s5r, resulting=list(s5r), visibility="final package state held", rules=["final-state lock"], final=True),
    ]


def _prop_transfer(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, dest = spec.product, spec.receiver
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
        _step(1, 0.0, 1.2, f"Establish the {product} and the {dest}. Source and destination are both already visible.", initial=s1, resulting=list(s1), visibility="source and destination in frame", rules=["first-frame presence"]),
        _step(2, 1.2, 2.5, f"Grasp and orient the same {product}. No second copy appears.", initial=s1, resulting=s2r, visibility="same product in hand", rules=["no product duplication"]),
        _step(3, 2.5, 5.0, f"Move, align, connect, or place the same {product} onto the {dest} in one continuous motion.", initial=s2r, resulting=s3r, visibility="continuous transfer", rules=["explicit placement", "no cut during transfer"]),
        _step(4, 5.0, 6.2, "Release hands only after physical support is clear.", initial=s3r, resulting=s4r, visibility="product supported at destination", rules=["explicit release"]),
        _step(5, 6.2, 7.2, "Make one small adjustment without changing identity.", initial=s4r, resulting=s5r, visibility="same product at destination", rules=["identity preserved"]),
        _step(6, 7.2, 8.0, f"Hold the completed arrangement. The same {product} remains at the {dest}.", initial=s5r, resulting=list(s5r), visibility="completed arrangement held", rules=["final-state lock"], final=True),
    ]


def _static_lock(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product = spec.product
    s1 = [
        _st("product", "support hand or stable surface, label/feature visible", "SUPPORT_HAND", True, f"complete static {product} already present"),
        _st("support", "declared support or surface", "FRAME_STATIC", True, "original support already in frame"),
    ]
    s2r = [
        _st("product", "same support/hand after one show/point/rotate", "SUPPORT_HAND", True, f"{product} shown once without opening or inventing parts"),
        _st("support", "declared support or surface", "FRAME_STATIC", True, "support unchanged"),
    ]
    s3r = [
        _st("product", "returned to original support or surface", "TABLE", True, f"{product} back on the original support"),
        _st("support", "declared support or surface", "FRAME_STATIC", True, "same support"),
    ]
    return [
        _step(1, 0.0, 1.5, f"Establish the complete static setup. The {product} and support are already present, label/feature visible.", initial=s1, resulting=list(s1), visibility="complete static setup visible", rules=["first-frame presence", "global continuity lock"]),
        _step(2, 1.5, 4.5, f"Show, point, or rotate once without opening, transferring, or inventing parts. One controlled hand path only.", initial=s1, resulting=s2r, visibility="one hand path, no extra fingers or duplicate parts", rules=["static or one slow motivated move"]),
        _step(3, 4.5, 6.5, "Return the product to the original support or surface. No off-camera hand swap.", initial=s2r, resulting=s3r, visibility="product returns to the same support", rules=["explicit return"]),
        _step(4, 6.5, 8.0, "Hold the final label/feature view. Match-cut lock: pose, grip, and component state stay identical.", initial=s3r, resulting=list(s3r), visibility="final label/feature view held", rules=["final-state lock", "match-cut lock"], final=True),
    ]


def _device_control(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, control = spec.product, spec.component
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
        _step(1, 0.0, 1.2, f"Establish the {product} and safe environment. Cable/power state is explicit. Nothing is invented.", initial=s1, resulting=list(s1), visibility="device and control already visible", rules=["first-frame presence"]),
        _step(2, 1.2, 2.5, f"The active hand approaches the single verified {control}. The support hand stays fixed.", initial=s1, resulting=s2r, visibility="one active hand only", rules=["no extra hands"]),
        _step(3, 2.5, 4.5, f"Press or turn once and show only the expected indicator or mechanical response. No invented UI.", initial=s2r, resulting=s3r, visibility="lock framing across the control action", rules=["one actuation"]),
        _step(4, 4.5, 6.2, "Release the control and keep the device fixed.", initial=s3r, resulting=s4r, visibility="device location unchanged", rules=["device stays put"]),
        _step(5, 6.2, 7.2, "Return to the safe/off state when required. No hidden power or cable change.", initial=s4r, resulting=s5r, visibility="declared power state visible", rules=["explicit safe/off"]),
        _step(6, 7.2, 8.0, "Hold the final device state. No new parts.", initial=s5r, resulting=list(s5r), visibility="final device state held", rules=["final-state lock"], final=True),
    ]


def _manipulation(spec: StrategySpec, *, scene: str, intent: str) -> list[ChoreographyStep]:
    product, target = spec.product, spec.target
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
        _step(1, 0.0, 1.2, f"Establish the {product} and {target}. Both are already visible and correctly oriented.", initial=s1, resulting=list(s1), visibility="product and target visible", rules=["first-frame presence"]),
        _step(2, 1.2, 2.5, "The active hand takes the declared grip. Any support hand stays fixed.", initial=s1, resulting=s2r, visibility="declared grip visible", rules=["one active hand"]),
        _step(3, 2.5, 5.2, f"Perform one controlled manipulation only. Do not invent a second {product}.", initial=s2r, resulting=s3r, visibility="continuous action coverage", rules=["one manipulation"]),
        _step(4, 5.2, 6.5, f"Stop and return the {product} to a stable position.", initial=s3r, resulting=s4r, visibility="product stable again", rules=["explicit return"]),
        _step(5, 6.5, 8.0, "Hold the resulting state with all props visible.", initial=s4r, resulting=list(s4r), visibility="all props visible in the hold", rules=["final-state lock"], final=True),
    ]


def _herbal_oil_steps() -> list[ChoreographyStep]:
    s1 = [
        _st("product", "support hand, upright, label-forward", "SUPPORT_HAND", True, "heritage bottle already present, upright, label-forward, stable identity"),
        _st("component", "seated on bottle", "SUPPORT_HAND", True, "cap fully seated, not yet rotated"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "external wrist/forearm already in frame"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table already present as the later placement surface"),
    ]
    s2r = [
        _st("product", "support hand, upright", "SUPPORT_HAND", True, "bottle remains in the same support hand"),
        _st("component", "active hand on cap", "ACTIVE_HAND", True, "cap rotated exactly 90 degrees, still on the bottle, not removed"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same wrist/forearm"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table unchanged"),
    ]
    s3r = [
        _st("product", "support hand, tilted toward same wrist/forearm", "SUPPORT_HAND", True, "same bottle tilted as if dispensing a small external amount; no uncontrolled stream"),
        _st("component", "still on bottle at 90 degrees", "ACTIVE_HAND", True, "cap still attached at 90 degrees, not fully unscrewed"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same external wrist/forearm receiving the gesture"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table unchanged"),
    ]
    s4r = [
        _st("product", "table, upright, label-forward", "TABLE", True, "same bottle returned upright and placed label-forward on the table"),
        _st("component", "still on bottle at 90 degrees", "TABLE", True, "cap remains on the bottle at the same 90-degree state"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same wrist/forearm"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table now holds the bottle"),
    ]
    s5r = [
        _st("product", "table, upright, label-forward, stationary", "TABLE", True, "bottle remains stationary and visible on the table; it does not return to the hand"),
        _st("component", "still on bottle at 90 degrees", "TABLE", True, "cap state unchanged"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same external wrist/forearm being massaged"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table still holds the same bottle"),
    ]
    s6r = list(s5r)
    return [
        _step(1, 0.0, 1.0, "The bottle is already present in the avatar's support hand at the first frame, upright, label-forward, with stable product identity. It does not materialize after the scene begins.", initial=s1, resulting=list(s1), visibility="bottle, cap, support hand, and target limb already visible", rules=["first-frame presence", "no thin-air bottle"]),
        _step(2, 1.0, 2.0, "The active hand grips the cap and rotates it exactly 90 degrees. Do not fully unscrew or remove the cap. The bottle remains in the support hand.", initial=s1, resulting=s2r, visibility="bottle stays in support hand; cap stays on the bottle", rules=["cap not removed", "support hand keeps the bottle"]),
        _step(3, 2.0, 3.3, "The avatar tilts the same bottle toward the same wrist/forearm as if dispensing a small amount externally. Do not create an uncontrolled stream. Preserve bottle, cap, hand, and target-limb identity.", initial=s2r, resulting=s3r, visibility="same bottle, cap, hands, and limb", rules=["no uncontrolled liquid", "identity lock"]),
        _step(4, 3.3, 4.2, "The avatar returns the bottle upright and places it label-forward on the table. The bottle's move from hand to table is explicit.", initial=s3r, resulting=s4r, visibility="explicit hand-to-table placement", rules=["explicit placement", "hand transfer to table"]),
        _step(5, 4.2, 7.7, "The avatar massages the same external wrist/forearm. The same bottle remains stationary and visible on the table; it does not disappear or return to the hand.", initial=s4r, resulting=s5r, visibility="bottle stationary on the table during massage", rules=["bottle does not return to the hand", "same target limb"]),
        _step(6, 7.7, 8.0, "Hold the final state. No new prop, duplicate hand, cap-state change, bottle teleportation, or unexplained object motion.", initial=s5r, resulting=s6r, visibility="final lock of bottle on table and massaged limb", rules=["final-state lock", "no new prop"], final=True),
    ]


def _roll_on_steps() -> list[ChoreographyStep]:
    s1 = [
        _st("product", "support hand, capped, label-forward", "SUPPORT_HAND", True, "capped roll-on already in hand"),
        _st("component", "seated on roll-on", "SUPPORT_HAND", True, "cap seated"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "external wrist/forearm already in frame"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table already present"),
    ]
    s2r = [
        _st("product", "support hand, uncapped", "SUPPORT_HAND", True, "same roll-on, cap removed"),
        _st("component", "table, visible", "TABLE", True, "same cap placed visibly on the table"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same limb"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table now holds the cap"),
    ]
    s3r = [
        _st("product", "support hand rolling on limb", "SUPPORT_HAND", True, "one controlled roll-on pass on the same external wrist/forearm"),
        _st("component", "table, visible", "TABLE", True, "cap remains on the table"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same limb after one pass"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table unchanged"),
    ]
    s4r = [
        _st("product", "table, upright, beside cap", "TABLE", True, "roll-on placed upright beside the same cap"),
        _st("component", "table, visible, beside product", "TABLE", True, "same cap still on the table"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same limb"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table holds product and cap"),
    ]
    s5r = [
        _st("product", "table, upright, beside cap, stationary", "TABLE", True, "product remains visible and stationary"),
        _st("component", "table, visible, stationary", "TABLE", True, "cap remains visible and stationary"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same limb after authorized external massage only"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table unchanged"),
    ]
    s6r = [
        _st("product", "support hand, recapped, upright", "SUPPORT_HAND", True, "same roll-on recapped with the same cap and returned upright"),
        _st("component", "reseated on roll-on", "SUPPORT_HAND", True, "same cap replaced on the same roll-on"),
        _st("target", "same adult wrist/forearm", "FRAME_STATIC", True, "same limb"),
        _st("table", "in front of presenter", "FRAME_STATIC", True, "table now empty of product and cap"),
    ]
    return [
        _step(1, 0.0, 1.0, "Establish the capped roll-on already in hand. Cap, label, and target limb are present in the first frame.", initial=s1, resulting=list(s1), visibility="capped roll-on and limb visible", rules=["first-frame presence"]),
        _step(2, 1.0, 2.0, "The active hand removes the cap and places the same cap visibly on the table. Do not lose or duplicate the cap.", initial=s1, resulting=s2r, visibility="cap placed on the table", rules=["explicit cap placement", "component custody retained"]),
        _step(3, 2.0, 3.6, "The support hand rolls one controlled pass on the same external wrist/forearm. No extra product appears.", initial=s2r, resulting=s3r, visibility="roll-on on the same limb; cap stays on the table", rules=["one pass", "cap stays put"]),
        _step(4, 3.6, 4.4, "Place the roll-on upright beside the same cap. Placement is explicit.", initial=s3r, resulting=s4r, visibility="product and cap side by side on the table", rules=["explicit placement"]),
        _step(5, 4.4, 6.7, "Massage only if the verified label authorizes it. Product and cap remain visible and stationary. No invented medical outcome.", initial=s4r, resulting=s5r, visibility="product and cap stationary and visible", rules=["no disappearance", "label-authorized massage only"]),
        _step(6, 6.7, 7.6, "Pick up the roll-on, replace the same cap, and return it upright. This is an explicit pickup and recap.", initial=s5r, resulting=s6r, visibility="same cap returns to the same roll-on", rules=["explicit pickup", "explicit recap", "hand transfer"]),
        _step(7, 7.6, 8.0, "Hold the final recapped upright state. No new prop or duplicate cap.", initial=s6r, resulting=list(s6r), visibility="final recapped hold", rules=["final-state lock"], final=True),
    ]


def _broll_steps(spec: StrategySpec) -> list[ChoreographyStep]:
    product = spec.product
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
        _step(1, 0.0, 1.5, f"Establish the {product} already on the table, label-forward. No object enters after frame one.", initial=s1, resulting=list(s1), visibility="product already present", rules=["first-frame presence"]),
        _step(2, 1.5, 3.5, "Hold a continuous product-detail beat. No opening, transfer, or invented part.", initial=s1, resulting=list(s1), visibility="continuous product detail", rules=["no illegal state change"]),
        _step(3, 3.5, 4.0, "Declare the outgoing state before the B-roll cut: same product, same location, same closed state.", initial=s1, resulting=outgoing, visibility="outgoing state fully declared", rules=["cut outgoing state declared"], cut="OUTGOING"),
        _step(4, 4.0, 6.5, "After the cut, re-establish the compatible incoming state before any further interaction. Same product, table, and closed state.", initial=outgoing, resulting=incoming, visibility="incoming state re-established", rules=["cut re-establish required"], cut="REESTABLISH"),
        _step(5, 6.5, 8.0, "Hold the re-established final state. The cut must not hide teleportation, duplication, or a hand swap.", initial=incoming, resulting=list(incoming), visibility="final re-established hold", rules=["final-state lock", "cut cannot hide illegal change"], final=True),
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
    "HERBAL_OIL": lambda spec, **_: _herbal_oil_steps(),
    "ROLL_ON": lambda spec, **_: _roll_on_steps(),
}


P2 = "P2_STATIC"
P1 = "P1_REWRITE"
P0 = "P0_REWRITE"

SPECS: dict[str, StrategySpec] = {
    "LIP_COLOR": StrategySpec(P0, "APPLY_CONTACT", "lip colour product", "applicator cap", "lips", "lips"),
    "BEAUTY_PERSONAL_CARE": StrategySpec(P0, "MATERIAL_TRANSFER", "beauty product", "cap/lid", "clean fingertip", "clean fingertip"),
    "CLEANSER": StrategySpec(P0, "MATERIAL_TRANSFER", "cleanser", "dispenser cap", "demonstration palette", "demonstration palette"),
    "SERUM": StrategySpec(P0, "MATERIAL_TRANSFER", "serum", "dropper or pump cap", "demonstration palette", "demonstration palette"),
    "FRAGRANCE": StrategySpec(P0, "SPRAY", "fragrance bottle", "cap", "wrist or approved clothing", "wrist"),
    "SPICE_SEASONING": StrategySpec(P0, "FOOD_COOK", "seasoning pack", "lid", "pan or dish", "pan or dish"),
    "PACKAGED_SAUCE_SAMBAL": StrategySpec(P0, "FOOD_COOK", "sauce pack", "lid", "pan or dish", "pan or dish"),
    "PACKAGED_FOOD": StrategySpec(P0, "FOOD_COOK", "packaged food", "seal/lid", "serving dish", "serving dish"),
    "LAUNDRY_DETERGENT": StrategySpec(P0, "MATERIAL_TRANSFER", "detergent pack", "cap", "washer drawer or bottle", "washer drawer or bottle"),
    "FABRIC_SOFTENER": StrategySpec(P0, "MATERIAL_TRANSFER", "softener bottle", "cap", "washer compartment", "washer compartment"),
    "BABY_WIPES": StrategySpec(P0, "MATERIAL_TRANSFER", "wipes pack", "resealable lid", "clean table", "clean table"),
    "BABY_DIAPER": StrategySpec(P1, "OPEN_CLOSE", "diaper pack", "pack opening", "clean table", "clean table"),
    "APPAREL": StrategySpec(P0, "PROP_TRANSFER", "garment", "hanger", "body/hanger", "hanger or body"),
    "MODESTWEAR": StrategySpec(P0, "PROP_TRANSFER", "modest garment", "hanger", "body/hanger", "body or hanger"),
    "SPORTSWEAR": StrategySpec(P1, "PROP_TRANSFER", "sportswear garment", "hanger", "body", "body"),
    "HOUSEHOLD_CLEANER": StrategySpec(P0, "APPLY_CONTACT", "household cleaner", "nozzle/cap", "suitable household surface", "suitable surface"),
    "HOUSEHOLD_STORAGE": StrategySpec(P1, "OPEN_CLOSE", "storage organizer", "lid/door", "shelf or counter", "shelf or counter"),
    "ELECTRONICS_ACCESSORY": StrategySpec(P1, "PROP_TRANSFER", "electronics accessory", "connector", "compatible device", "compatible device"),
    "ELECTRONICS_SMALL_DEVICE": StrategySpec(P0, "DEVICE_CONTROL", "small device", "power or control button", "stable desk", "stable desk"),
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
    "RUG_MAT": StrategySpec(P1, "PROP_TRANSFER", "rug or mat", "roll", "clean dry floor", "clean dry floor"),
    "BOOK": StrategySpec(P2, "STATIC_LOCK", "book", "cover", "reading position", "hands or table"),
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
    "SLEEPWEAR": StrategySpec(P2, "STATIC_LOCK", "sleepwear", "hanger", "hanger or flat lay", "hanger or flat lay"),
    "DRESS": StrategySpec(P2, "STATIC_LOCK", "dress", "hanger", "hanger display", "hanger"),
    "FOOTWEAR": StrategySpec(P2, "STATIC_LOCK", "footwear pair", "size label", "table display", "table"),
    "FROZEN_FOOD": StrategySpec(P0, "STATIC_LOCK", "sealed frozen-food pack", "seal", "label-directed cooking setup", "counter"),
    "CURTAIN": StrategySpec(P1, "PROP_TRANSFER", "curtain panel", "heading", "compatible rod", "compatible rod"),
    "WALL_COVERING": StrategySpec(P0, "PROP_TRANSFER", "wall-covering sample", "backing", "clean dry compatible surface", "compatible surface"),
    "KNITTING_CROCHET": StrategySpec(P1, "MANIPULATION", "yarn and hook or needle", "label", "small sample", "small sample"),
    "CAR_CARE": StrategySpec(P0, "MATERIAL_TRANSFER", "car-care product", "cap", "clean detached sample panel", "sample panel"),
    "BABY_FEEDING": StrategySpec(P1, "STATIC_LOCK", "baby-feeding item", "sealed parts", "clean table", "clean table"),
    "BABY_SKINCARE": StrategySpec(P0, "MATERIAL_TRANSFER", "baby skincare pack", "cap", "adult hand only", "adult hand"),
    "BATH_LINEN": StrategySpec(P0, "PROP_TRANSFER", "bath linen", "care label", "folded display", "table"),
    "STATIONERY": StrategySpec(P1, "MANIPULATION", "stationery item", "pack", "clean document or desk", "desk"),
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
    "FITNESS_EQUIPMENT": StrategySpec(P1, "STATIC_LOCK", "fitness equipment", "adjustment", "off the doorway", "floor or bench"),
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
    builder = _BUILDERS[spec.family]
    variants: list[ChoreographyVariant] = []
    for index, scene in enumerate(scenes):
        intent = actions[index % len(actions)]
        context = contexts[index % len(contexts)]
        camera = cameras[index % len(cameras)]
        steps = builder(spec, scene=scene, intent=intent)
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
