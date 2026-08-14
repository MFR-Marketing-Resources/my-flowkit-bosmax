"""Intent → physical scenario resolution and mandatory special fixtures.

Atomic library actions are either:
- COMPOSED_SEQUENCE: one cohesive multi-step choreography covering many indexes
- ALTERNATIVE_VARIANT: separate physical scenario (different target/setup)
- STATIC_LOCK: static/hold scenarios
- BLOCKED: no production path
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent.models.scene_choreography_v2 import ChoreographyStep, EntityState


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


@dataclass(frozen=True)
class PhysicalScenario:
    """Resolved physical plan for one alternative action or composed unit."""

    coverage_kind: str  # COMPOSED_SEQUENCE | ALTERNATIVE_VARIANT | STATIC_LOCK
    physical_target: str
    setup_entities: tuple[str, ...]
    transition_key: str
    primary_mode: str
    actor_hand: str
    component_custody: str


# Positive branching phrases that choose among physical paths (not safety "do not X or Y").
_POSITIVE_BRANCH_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmove,\s*align,\s*connect,\s*or\s+place\b", re.I),
    re.compile(r"\bpress\s+or\s+turn\b", re.I),
    re.compile(r"\bopen\s+or\s+expose\b", re.I),
    re.compile(r"\bhold\s+or\s+store\b", re.I),
    re.compile(r"\bplace\s+or\s+wear\b", re.I),
    re.compile(r"\bshow,\s*point,\s*or\s+rotate\b", re.I),
    re.compile(r"\bhand\s+or\s+table\b", re.I),
    re.compile(r"\bopen\s+or\s+place\b", re.I),
    re.compile(r"\breseat\s+or\s+left\b", re.I),
    re.compile(r"\bin\s+or\s+beside\b", re.I),
)


def has_positive_physical_branch(text: str) -> bool:
    blob = str(text or "")
    if not blob.strip():
        return False
    # Allow pure prohibitions: "Do not X or Y"
    lowered = blob.casefold()
    if lowered.strip().startswith("do not ") or " do not " in f" {lowered}":
        # Still flag if the same sentence also commands alternatives before "do not"
        head = re.split(r"\bdo not\b", lowered, maxsplit=1)[0]
        return any(pat.search(head) for pat in _POSITIVE_BRANCH_RES)
    return any(pat.search(blob) for pat in _POSITIVE_BRANCH_RES)


def resolve_intent_scenario(
    *,
    strategy_id: str,
    family: str,
    intent: str,
    default_target: str,
    default_receiver: str,
    action_index: int,
) -> PhysicalScenario:
    t = intent.casefold()
    product_default = default_target or default_receiver

    if family == "STATIC_LOCK":
        mode = "rotate_once" if "rotate" in t or "show" in t or "point" in t else "hold_static"
        return PhysicalScenario(
            coverage_kind="STATIC_LOCK",
            physical_target=product_default,
            setup_entities=("product", "support"),
            transition_key=f"static:{mode}:{action_index}",
            primary_mode=mode,
            actor_hand="SUPPORT_HAND",
            component_custody="ATTACHED",
        )

    # Intent-specific physical targets (order matters: more specific first).
    if "back of the hand" in t or ("swatch" in t and "hand" in t):
        target = "back of the hand"
        mode = "swatch_hand"
        setup = ("product", "component", "target")
    elif "handbag" in t:
        target = "handbag interior then shade view"
        mode = "handbag_reveal"
        setup = ("product", "component", "handbag")
    elif "mirror" in t:
        target = "lips via mirror"
        mode = "mirror_touchup"
        setup = ("product", "component", "target", "mirror")
    elif "diaper bag" in t:
        target = "open diaper bag"
        mode = "pack_into_bag"
        setup = ("product", "component", "bag")
    elif "pull one sheet" in t or ("pull" in t and "sheet" in t):
        target = "single wipe sheet"
        mode = "pull_one_sheet"
        setup = ("product", "component", "sheet")
    elif "open and reseal" in t or ("reseal" in t and "pack" in t):
        target = "wipes pack seal"
        mode = "open_reseal_pack"
        setup = ("product", "component")
    elif "on a hanger" in t or "hold the garment on a hanger" in t:
        target = "hanger"
        mode = "hanger_hold"
        setup = ("product", "hanger")
    elif "wear the garment" in t or "fit check" in t:
        target = "body worn fit"
        mode = "worn_fit"
        setup = ("product", "body")
    elif "pinch the fabric" in t or "texture" in t and "pinch" in t:
        target = "fabric pinch zone"
        mode = "fabric_pinch"
        setup = ("product",)
    elif "seams" in t or "hem" in t or "silhouette" in t:
        target = "seams hem silhouette"
        mode = "seam_inspect"
        setup = ("product",)
    elif "packaging" in t and ("remove" in t or "unbox" in t):
        target = "packaging then desk"
        mode = "unbox_device"
        setup = ("product", "packaging", "control")
    elif "power" in t or "control button" in t or "press the correct" in t:
        target = "verified power button"
        mode = "press_control"
        setup = ("product", "control")
    elif "screen" in t or "indicator" in t or "port" in t:
        target = "screen indicator port"
        mode = "show_indicator"
        setup = ("product", "control")
    elif "wear the device" in t:
        target = "worn mount"
        mode = "wear_device"
        setup = ("product", "body_mount")
    elif "place" in t and "device" in t:
        target = "desk surface"
        mode = "place_device"
        setup = ("product", "desk")
    elif "place or wear" in t:
        # Fail-closed default: desk place only (no wear branch).
        target = "desk surface"
        mode = "place_device"
        setup = ("product", "desk")
    elif "sprinkle" in t:
        target = default_receiver
        mode = "sprinkle"
        setup = ("product", "component", "receiver", "utensil")
    elif "stir" in t:
        target = default_receiver
        mode = "stir"
        setup = ("product", "component", "receiver", "utensil")
    elif "measure" in t or "pinch a small" in t:
        target = default_receiver
        mode = "measure"
        setup = ("product", "component", "receiver", "utensil")
    elif "plated" in t or "beside the finished" in t:
        target = "plated dish"
        mode = "place_beside_dish"
        setup = ("product", "component", "receiver", "utensil")
    elif "wipe" in t and "cloth" in t:
        target = default_target
        mode = "wipe_surface"
        setup = ("product", "component", "target", "cloth")
    elif "close the nozzle" in t or "close the" in t and "cap" in t:
        target = default_target
        mode = "close_cap"
        setup = ("product", "component", "target")
    elif "lips" in t or ("apply" in t and "lip" in t):
        target = "lips"
        mode = "apply_lips"
        setup = ("product", "component", "target")
    elif family == "APPLY_CONTACT":
        target = default_target
        mode = "apply_contact"
        setup = ("product", "component", "target")
    elif family == "MATERIAL_TRANSFER":
        target = default_receiver
        mode = "material_transfer"
        setup = ("product", "component", "receiver")
    elif family == "SPRAY":
        target = default_target
        mode = "spray_once"
        setup = ("product", "component", "target")
    elif family == "FOOD_COOK":
        target = default_receiver
        mode = "food_cook"
        setup = ("product", "component", "receiver", "utensil")
    elif family == "OPEN_CLOSE":
        target = default_target
        mode = "open_close"
        setup = ("product", "component")
    elif family == "PROP_TRANSFER":
        target = default_receiver
        mode = "prop_place"
        setup = ("product", "destination")
    elif family == "DEVICE_CONTROL":
        target = default_target
        mode = "device_press"
        setup = ("product", "control")
    elif family == "MANIPULATION":
        target = default_target
        mode = "manipulate_once"
        setup = ("product", "target")
    else:
        target = product_default
        mode = "generic"
        setup = ("product",)

    return PhysicalScenario(
        coverage_kind="ALTERNATIVE_VARIANT",
        physical_target=target,
        setup_entities=tuple(setup),
        transition_key=f"{family}:{mode}:{target}:{action_index}",
        primary_mode=mode,
        actor_hand="ACTIVE_HAND",
        component_custody="ACTIVE_HAND",
    )


def lip_color_steps(action_index: int, intent: str) -> list[ChoreographyStep]:
    product, cap = "lip colour product", "applicator cap"
    if action_index == 0 or "apply one clean pass to the lips" in intent.casefold():
        target = "lips"
        s1 = [
            _st("product", "support hand, label-forward", "SUPPORT_HAND", True, f"closed {product} already present"),
            _st("component", f"attached to {product}", "SUPPORT_HAND", True, f"{cap} seated"),
            _st("target", "lips", "FRAME_STATIC", True, "lips already in frame"),
        ]
        s2r = [
            _st("product", "support hand, stable", "SUPPORT_HAND", True, f"{product} in support hand"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened and kept visible"),
            _st("target", "lips", "FRAME_STATIC", True, "lips unchanged"),
        ]
        s3r = [
            _st("product", "support hand, still in frame", "SUPPORT_HAND", True, f"{product} identity unchanged"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} in active hand"),
            _st("target", "lips", "FRAME_STATIC", True, "one clean pass completed on lips"),
        ]
        s4r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} closed label-forward on the table"),
            _st("component", "reseated on product", "TABLE", True, f"{cap} reseated on {product}"),
            _st("target", "lips", "FRAME_STATIC", True, "lips after application"),
        ]
        return [
            _step(1, 0.0, 1.0, f"The {product}, {cap}, and lips are already present. No object materializes after frame one.", initial=s1, resulting=list(s1), visibility="product, cap, lips visible", rules=["first-frame presence"], sources=[0], transition="lip:establish"),
            _step(2, 1.0, 2.3, f"Open the {cap} with the active hand. Keep the same {cap} visible. The {product} stays in the support hand.", initial=s1, resulting=s2r, visibility="cap custody retained", rules=["component custody retained"], sources=[0], transition="lip:open"),
            _step(3, 2.3, 5.0, "Apply one clean pass only onto the lips. Do not invent a second applicator.", initial=s2r, resulting=s3r, visibility="continuous lip application", rules=["one pass only"], sources=[0], transition="lip:apply_lips"),
            _step(4, 5.0, 7.0, f"Close the {product} and reseat the same {cap}. Place the product label-forward on the table.", initial=s3r, resulting=s4r, visibility="closed product on table", rules=["explicit close/place"], sources=[0], transition="lip:close"),
            _step(5, 7.0, 8.0, "Hold the final lip-application state. No new prop.", initial=s4r, resulting=list(s4r), visibility="final hold", rules=["final-state lock"], final=True, transition="lip:final"),
        ]

    if action_index == 1 or "swatch" in intent.casefold():
        target = "back of the hand"
        s1 = [
            _st("product", "support hand, label-forward", "SUPPORT_HAND", True, f"closed {product} already present"),
            _st("component", f"attached to {product}", "SUPPORT_HAND", True, f"{cap} seated"),
            _st("target", "back of the hand", "FRAME_STATIC", True, "back of the hand already in frame"),
        ]
        s2r = [
            _st("product", "support hand", "SUPPORT_HAND", True, f"{product} stabilized"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened and visible"),
            _st("target", "back of the hand", "FRAME_STATIC", True, "back of the hand ready"),
        ]
        s3r = [
            _st("product", "support hand", "SUPPORT_HAND", True, f"{product} still in support hand"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"applicator after one swatch"),
            _st("target", "back of the hand", "FRAME_STATIC", True, "one shade swatch on the back of the hand"),
        ]
        s4r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} closed beside the swatch"),
            _st("component", "reseated on product", "TABLE", True, f"{cap} reseated"),
            _st("target", "back of the hand", "FRAME_STATIC", True, "swatch remains visible on the back of the hand"),
        ]
        return [
            _step(1, 0.0, 1.0, f"Establish the closed {product} and the back of the hand already in frame one.", initial=s1, resulting=list(s1), visibility="product and hand back visible", rules=["first-frame presence"], sources=[1], transition="swatch:establish"),
            _step(2, 1.0, 2.2, f"Open the {cap}. Keep component custody in the active hand.", initial=s1, resulting=s2r, visibility="cap visible", rules=["component custody retained"], sources=[1], transition="swatch:open"),
            _step(3, 2.2, 5.0, "Swatch one shade only on the back of the hand. Do not contact the lips.", initial=s2r, resulting=s3r, visibility="hand swatch only", rules=["hand target only"], sources=[1], transition="swatch:hand"),
            _step(4, 5.0, 7.0, f"Reseat the same {cap} and place the {product} label-forward on the table. The hand swatch stays visible.", initial=s3r, resulting=s4r, visibility="product closed, swatch visible", rules=["explicit close/place"], sources=[1], transition="swatch:close"),
            _step(5, 7.0, 8.0, "Hold the shade-reveal state with the hand swatch and closed product visible.", initial=s4r, resulting=list(s4r), visibility="final swatch hold", rules=["final-state lock"], final=True, transition="swatch:final"),
        ]

    if action_index == 2 or "mirror" in intent.casefold():
        s1 = [
            _st("product", "support hand, label-forward", "SUPPORT_HAND", True, f"closed {product} already present"),
            _st("component", f"attached to {product}", "SUPPORT_HAND", True, f"{cap} seated"),
            _st("target", "lips", "FRAME_STATIC", True, "lips already in frame"),
            _st("mirror", "stationary on vanity", "FRAME_STATIC", True, "mirror already established and stationary"),
        ]
        s2r = [
            _st("product", "support hand", "SUPPORT_HAND", True, f"{product} in support hand"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened"),
            _st("target", "lips", "FRAME_STATIC", True, "lips ready for touch-up"),
            _st("mirror", "stationary on vanity", "FRAME_STATIC", True, "mirror remains stationary"),
        ]
        s3r = [
            _st("product", "support hand", "SUPPORT_HAND", True, f"{product} still visible"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} in active hand"),
            _st("target", "lips", "FRAME_STATIC", True, "one mirror-guided touch-up pass on lips"),
            _st("mirror", "stationary on vanity", "FRAME_STATIC", True, "mirror still stationary"),
        ]
        s4r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} closed on the table"),
            _st("component", "reseated on product", "TABLE", True, f"{cap} reseated"),
            _st("target", "lips", "FRAME_STATIC", True, "lips after touch-up"),
            _st("mirror", "stationary on vanity", "FRAME_STATIC", True, "mirror unchanged"),
        ]
        return [
            _step(1, 0.0, 1.2, f"Establish the {product}, lips, and a stationary mirror already in frame one. The mirror does not enter later.", initial=s1, resulting=list(s1), visibility="product, lips, mirror visible", rules=["first-frame presence", "mirror pre-established"], sources=[2], transition="mirror:establish"),
            _step(2, 1.2, 2.4, f"Open the {cap} while looking into the same stationary mirror.", initial=s1, resulting=s2r, visibility="mirror stays put", rules=["component custody retained"], sources=[2], transition="mirror:open"),
            _step(3, 2.4, 5.2, "Touch up the lip colour on the lips while looking into the same mirror. One controlled pass only.", initial=s2r, resulting=s3r, visibility="mirror-guided lip touch-up", rules=["mirror stationary"], sources=[2], transition="mirror:touchup"),
            _step(4, 5.2, 7.0, f"Close the {product}, reseat the same {cap}, and place the product on the table. Mirror remains stationary.", initial=s3r, resulting=s4r, visibility="closed product, stationary mirror", rules=["explicit close/place"], sources=[2], transition="mirror:close"),
            _step(5, 7.0, 8.0, "Hold the final mirror touch-up state. No new prop and no mirror move.", initial=s4r, resulting=list(s4r), visibility="final hold", rules=["final-state lock"], final=True, transition="mirror:final"),
        ]

    # handbag reveal
    s1 = [
        _st("product", "inside open handbag", "BAG", True, f"{product} already visible inside the open handbag"),
        _st("component", f"attached to {product}", "BAG", True, f"{cap} seated on product inside bag"),
        _st("handbag", "open on table", "FRAME_STATIC", True, "open handbag already established in frame one"),
    ]
    s2r = [
        _st("product", "active hand, label-forward", "ACTIVE_HAND", True, f"same {product} removed from the handbag"),
        _st("component", f"attached to {product}", "ACTIVE_HAND", True, f"{cap} still seated"),
        _st("handbag", "open on table", "FRAME_STATIC", True, "handbag remains open and visible"),
    ]
    s3r = [
        _st("product", "support hand, label-forward", "SUPPORT_HAND", True, f"{product} held for shade show"),
        _st("component", "active hand", "ACTIVE_HAND", True, f"{cap} opened to show shade"),
        _st("handbag", "open on table", "FRAME_STATIC", True, "handbag still in frame"),
    ]
    s4r = [
        _st("product", "support hand, label-forward", "SUPPORT_HAND", True, f"{product} recapped after shade show"),
        _st("component", "reseated on product", "SUPPORT_HAND", True, f"same {cap} reseated"),
        _st("handbag", "open on table", "FRAME_STATIC", True, "handbag unchanged"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the open handbag and the {product} already visible inside it at frame one.", initial=s1, resulting=list(s1), visibility="handbag and product in bag", rules=["first-frame presence", "handbag pre-established"], sources=[3], transition="bag:establish"),
        _step(2, 1.2, 3.0, f"Remove the same {product} from the open handbag with the active hand. The handbag stays visible.", initial=s1, resulting=s2r, visibility="explicit bag exit", rules=["explicit pickup", "hand transfer"], sources=[3], transition="bag:remove"),
        _step(3, 3.0, 5.5, f"Open the {cap} and show the shade. Do not lose the handbag from frame.", initial=s2r, resulting=s3r, visibility="shade reveal with bag still visible", rules=["component custody retained"], sources=[3], transition="bag:show_shade"),
        _step(4, 5.5, 7.0, f"Reseat the same {cap} on the {product}. Handbag remains open on the table.", initial=s3r, resulting=s4r, visibility="recapped product, bag visible", rules=["explicit recap"], sources=[3], transition="bag:recap"),
        _step(5, 7.0, 8.0, "Hold the final handbag-reveal state. No duplicate product and no bag teleport.", initial=s4r, resulting=list(s4r), visibility="final hold", rules=["final-state lock"], final=True, transition="bag:final"),
    ]


def baby_wipes_steps(action_index: int, intent: str) -> list[ChoreographyStep]:
    product, lid = "wipes pack", "resealable lid"
    t = intent.casefold()
    if action_index == 0 or "open and reseal" in t:
        s1 = [
            _st("product", "table, label-forward", "TABLE", True, f"closed {product} already on the table"),
            _st("component", f"seated on {product}", "TABLE", True, f"{lid} sealed"),
        ]
        s2r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} held stable on the table"),
            _st("component", "active hand", "ACTIVE_HAND", True, f"{lid} opened once and held"),
        ]
        s3r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} still on the table"),
            _st("component", "reseated on product", "TABLE", True, f"same {lid} resealed on the pack"),
        ]
        return [
            _step(1, 0.0, 1.2, f"Establish the closed {product} already on the table with the resealable lid visible.", initial=s1, resulting=list(s1), visibility="pack visible", rules=["first-frame presence"], sources=[0], transition="wipes:establish_seal"),
            _step(2, 1.2, 3.5, f"Open the {lid} once with the active hand. The pack stays on the table.", initial=s1, resulting=s2r, visibility="lid open, pack fixed", rules=["component custody retained"], sources=[0], transition="wipes:open"),
            _step(3, 3.5, 6.5, f"Reseal the same {lid} on the same {product}. Do not lose the lid.", initial=s2r, resulting=s3r, visibility="resealed pack", rules=["explicit reseal"], sources=[0], transition="wipes:reseal"),
            _step(4, 6.5, 8.0, "Hold the resealed pack. No sheet pull and no bag entry in this scenario.", initial=s3r, resulting=list(s3r), visibility="final resealed hold", rules=["final-state lock"], final=True, transition="wipes:final_seal"),
        ]
    if action_index == 1 or "pull one sheet" in t or "pull" in t:
        s1 = [
            _st("product", "table, label-forward", "TABLE", True, f"open {product} already on the table"),
            _st("component", "folded open on pack", "TABLE", True, f"{lid} already open and attached"),
            _st("sheet", "still inside pack", "ATTACHED", True, "sheets still inside the pack"),
        ]
        s2r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} remains on the table"),
            _st("component", "folded open on pack", "TABLE", True, f"{lid} still open on pack"),
            _st("sheet", "active hand", "ACTIVE_HAND", True, "exactly one sheet pulled and held"),
        ]
        s3r = [
            _st("product", "table, label-forward", "TABLE", True, f"{product} still visible on the table"),
            _st("component", "folded open on pack", "TABLE", True, f"{lid} unchanged"),
            _st("sheet", "active hand", "ACTIVE_HAND", True, "same single sheet shown for size and texture"),
        ]
        return [
            _step(1, 0.0, 1.2, f"Establish the open {product} already on the table. The pack body remains the fixed home of the sheets.", initial=s1, resulting=list(s1), visibility="open pack visible", rules=["first-frame presence"], sources=[1], transition="wipes:establish_open"),
            _step(2, 1.2, 4.0, f"Pull exactly one sheet with the active hand. The {product} stays visible on the table.", initial=s1, resulting=s2r, visibility="one sheet, pack fixed", rules=["one sheet only", "pack remains visible"], sources=[1], transition="wipes:pull_one"),
            _step(3, 4.0, 6.5, "Show the single sheet size and texture. Do not pull a second sheet.", initial=s2r, resulting=s3r, visibility="sheet texture hold", rules=["no second sheet"], sources=[1], transition="wipes:show_sheet"),
            _step(4, 6.5, 8.0, f"Hold the final state with the {product} still on the table and one sheet in hand.", initial=s3r, resulting=list(s3r), visibility="final one-sheet hold", rules=["final-state lock"], final=True, transition="wipes:final_sheet"),
        ]
    # place into diaper bag
    s1 = [
        _st("product", "table, label-forward", "TABLE", True, f"closed {product} already on the table"),
        _st("component", f"seated on {product}", "TABLE", True, f"{lid} sealed"),
        _st("bag", "open on table", "FRAME_STATIC", True, "open diaper bag already present in frame one"),
    ]
    s2r = [
        _st("product", "active hand", "ACTIVE_HAND", True, f"same {product} lifted from the table"),
        _st("component", f"seated on {product}", "ACTIVE_HAND", True, f"{lid} still seated"),
        _st("bag", "open on table", "FRAME_STATIC", True, "open diaper bag unchanged"),
    ]
    s3r = [
        _st("product", "inside open diaper bag", "BAG", True, f"same {product} placed into the open diaper bag"),
        _st("component", f"seated on {product}", "BAG", True, f"{lid} still seated"),
        _st("bag", "open on table", "FRAME_STATIC", True, "diaper bag still open and supporting the pack"),
    ]
    return [
        _step(1, 0.0, 1.2, f"Establish the closed {product} and the already-open diaper bag in frame one.", initial=s1, resulting=list(s1), visibility="pack and open bag visible", rules=["first-frame presence", "bag pre-established"], sources=[2], transition="wipes:bag_establish"),
        _step(2, 1.2, 3.0, f"Lift the same {product} from the table with the active hand. The diaper bag stays open and visible.", initial=s1, resulting=s2r, visibility="pack in hand, bag fixed", rules=["explicit pickup", "hand transfer"], sources=[2], transition="wipes:lift"),
        _step(3, 3.0, 6.0, f"Place the same {product} into the open diaper bag in one continuous motion. Do not invent a second pack.", initial=s2r, resulting=s3r, visibility="pack enters bag", rules=["explicit placement", "no cut during transfer"], sources=[2], transition="wipes:into_bag"),
        _step(4, 6.0, 8.0, "Hold the packed diaper-bag state. Pack identity and bag opening stay locked.", initial=s3r, resulting=list(s3r), visibility="final bag hold", rules=["final-state lock"], final=True, transition="wipes:final_bag"),
    ]


def apparel_steps(action_index: int, intent: str) -> list[ChoreographyStep]:
    product = "garment"
    t = intent.casefold()
    if action_index == 0 or "hanger" in t and "hold" in t:
        s1 = [
            _st("product", "on hanger", "ATTACHED", True, f"{product} already on the hanger"),
            _st("hanger", "held by support hand", "SUPPORT_HAND", True, "hanger already in support hand"),
        ]
        s2r = [
            _st("product", "on hanger, raised", "ATTACHED", True, f"{product} presented on the same hanger"),
            _st("hanger", "held by support hand", "SUPPORT_HAND", True, "same hanger still held"),
        ]
        return [
            _step(1, 0.0, 1.5, f"Establish the {product} already on the hanger in the support hand.", initial=s1, resulting=list(s1), visibility="hanger presentation start", rules=["first-frame presence"], sources=[0], transition="apparel:hanger_est"),
            _step(2, 1.5, 5.5, f"Hold the {product} on the same hanger and present the full silhouette. No wear step.", initial=s1, resulting=s2r, visibility="hanger hold", rules=["hanger only"], sources=[0], transition="apparel:hanger_hold"),
            _step(3, 5.5, 8.0, "Hold the final hanger presentation. No fabric pinch and no body wear in this scenario.", initial=s2r, resulting=list(s2r), visibility="final hanger hold", rules=["final-state lock"], final=True, transition="apparel:hanger_final"),
        ]
    if action_index == 1 or "wear" in t or "fit check" in t:
        s1 = [
            _st("product", "worn on body", "WORN", True, f"{product} already worn for fit check"),
            _st("body", "standing at mirror line", "FRAME_STATIC", True, "body already in frame wearing the garment"),
        ]
        s2r = [
            _st("product", "worn on body after fit adjust", "WORN", True, f"{product} after one normal fit check motion"),
            _st("body", "standing at mirror line", "FRAME_STATIC", True, "same body pose family"),
        ]
        return [
            _step(1, 0.0, 1.5, f"Establish the {product} already worn on the body. No hanger-to-body teleport after start.", initial=s1, resulting=list(s1), visibility="worn garment visible", rules=["first-frame presence", "worn state pre-established"], sources=[1], transition="apparel:wear_est"),
            _step(2, 1.5, 5.5, "Perform one normal fit check while wearing the same garment. Do not remove the garment.", initial=s1, resulting=s2r, visibility="fit check", rules=["worn fit only"], sources=[1], transition="apparel:fit_check"),
            _step(3, 5.5, 8.0, "Hold the final worn fit-check state.", initial=s2r, resulting=list(s2r), visibility="final worn hold", rules=["final-state lock"], final=True, transition="apparel:wear_final"),
        ]
    if action_index == 2 or "pinch" in t:
        s1 = [
            _st("product", "support hand, fabric accessible", "SUPPORT_HAND", True, f"{product} already held with fabric accessible"),
        ]
        s2r = [
            _st("product", "support hand, pinch zone raised", "SUPPORT_HAND", True, f"{product} after one light fabric pinch"),
        ]
        return [
            _step(1, 0.0, 1.5, f"Establish the {product} already in the support hand with a clear fabric zone.", initial=s1, resulting=list(s1), visibility="garment ready", rules=["first-frame presence"], sources=[2], transition="apparel:pinch_est"),
            _step(2, 1.5, 5.5, "Pinch the fabric lightly once with the active hand to show texture. No seam tour and no wear.", initial=s1, resulting=s2r, visibility="fabric pinch", rules=["one pinch"], sources=[2], transition="apparel:pinch"),
            _step(3, 5.5, 8.0, "Hold the final fabric-texture state.", initial=s2r, resulting=list(s2r), visibility="final pinch hold", rules=["final-state lock"], final=True, transition="apparel:pinch_final"),
        ]
    # seams / hem / silhouette
    s1 = [
        _st("product", "support hand, seams visible", "SUPPORT_HAND", True, f"{product} already oriented for seam and hem view"),
    ]
    s2r = [
        _st("product", "support hand, rotated to hem", "SUPPORT_HAND", True, f"{product} after controlled seams/hem/silhouette inspection"),
    ]
    return [
        _step(1, 0.0, 1.5, f"Establish the {product} already oriented so seams, hem, and silhouette are visible.", initial=s1, resulting=list(s1), visibility="seam-ready start", rules=["first-frame presence"], sources=[3], transition="apparel:seam_est"),
        _step(2, 1.5, 5.5, "Inspect seams, hem, and silhouette with one controlled rotation. No fabric pinch and no wear.", initial=s1, resulting=s2r, visibility="seam inspection", rules=["inspection only"], sources=[3], transition="apparel:seam_inspect"),
        _step(3, 5.5, 8.0, "Hold the final seam/hem/silhouette view.", initial=s2r, resulting=list(s2r), visibility="final inspection hold", rules=["final-state lock"], final=True, transition="apparel:seam_final"),
    ]


def electronics_small_device_steps(action_index: int, intent: str) -> list[ChoreographyStep]:
    product, control = "small device", "power button"
    t = intent.casefold()
    if action_index == 0 or "packaging" in t or "remove the device" in t:
        s1 = [
            _st("product", "inside open packaging", "SURFACE", True, f"{product} already visible inside open packaging"),
            _st("packaging", "open on desk", "FRAME_STATIC", True, "packaging already open on the desk"),
            _st("control", f"on {product}", "ATTACHED", True, f"{control} already visible on the device"),
        ]
        s2r = [
            _st("product", "active hand above desk", "ACTIVE_HAND", True, f"same {product} removed from packaging"),
            _st("packaging", "open on desk", "FRAME_STATIC", True, "empty open packaging remains on the desk"),
            _st("control", f"on {product}", "ATTACHED", True, f"{control} still attached"),
        ]
        s3r = [
            _st("product", "desk surface", "SURFACE", True, f"{product} placed on the desk after unbox"),
            _st("packaging", "open on desk", "FRAME_STATIC", True, "packaging still visible"),
            _st("control", f"on {product}", "ATTACHED", True, f"{control} visible"),
        ]
        return [
            _step(1, 0.0, 1.2, f"Establish open packaging and the {product} already inside it on the desk.", initial=s1, resulting=list(s1), visibility="packaging and device visible", rules=["first-frame presence"], sources=[0], transition="tech:unbox_est"),
            _step(2, 1.2, 3.5, f"Remove the same {product} from the packaging with the active hand. Packaging stays on the desk.", initial=s1, resulting=s2r, visibility="explicit unbox", rules=["explicit pickup", "hand transfer"], sources=[0], transition="tech:unbox"),
            _step(3, 3.5, 6.0, f"Place the {product} on the desk surface. Do not wear the device in this scenario.", initial=s2r, resulting=s3r, visibility="device on desk", rules=["explicit placement"], sources=[0], transition="tech:place_after_unbox"),
            _step(4, 6.0, 8.0, "Hold the unboxed desk state. No power press in this scenario.", initial=s3r, resulting=list(s3r), visibility="final unbox hold", rules=["final-state lock"], final=True, transition="tech:unbox_final"),
        ]
    if action_index == 1 or "press" in t or "power" in t or "control button" in t:
        s1 = [
            _st("product", "desk surface", "SURFACE", True, f"{product} already on the desk"),
            _st("control", f"on {product}", "ATTACHED", True, f"single verified {control} already visible"),
        ]
        s2r = [
            _st("product", "desk surface", "SURFACE", True, f"{product} unmoved"),
            _st("control", "approached by active hand", "ATTACHED", True, f"hand at the same {control}"),
        ]
        s3r = [
            _st("product", "desk surface", "SURFACE", True, f"{product} shows only the expected indicator response"),
            _st("control", "pressed once", "ATTACHED", True, f"{control} pressed once"),
        ]
        s4r = [
            _st("product", "desk surface", "SURFACE", True, f"{product} remains on the desk"),
            _st("control", "released at rest", "ATTACHED", True, f"{control} released"),
        ]
        return [
            _step(1, 0.0, 1.2, f"Establish the {product} on the desk with the verified {control} already visible.", initial=s1, resulting=list(s1), visibility="device and control visible", rules=["first-frame presence"], sources=[1], transition="tech:press_est"),
            _step(2, 1.2, 2.5, f"The active hand approaches the single verified {control}.", initial=s1, resulting=s2r, visibility="one hand path", rules=["no extra hands"], sources=[1], transition="tech:approach"),
            _step(3, 2.5, 5.0, f"Press the {control} once. Show only the expected indicator. Do not invent UI.", initial=s2r, resulting=s3r, visibility="one press", rules=["one actuation"], sources=[1], transition="tech:press_once"),
            _step(4, 5.0, 7.0, f"Release the {control}. Device stays on the desk.", initial=s3r, resulting=s4r, visibility="device fixed", rules=["device stays put"], sources=[1], transition="tech:release"),
            _step(5, 7.0, 8.0, "Hold the final powered-response state. No wear step.", initial=s4r, resulting=list(s4r), visibility="final press hold", rules=["final-state lock"], final=True, transition="tech:press_final"),
        ]
    if action_index == 2 or "screen" in t or "indicator" in t or "port" in t:
        s1 = [
            _st("product", "desk surface", "SURFACE", True, f"{product} already on the desk"),
            _st("control", f"on {product}", "ATTACHED", True, "verified controls already visible"),
        ]
        s2r = [
            _st("product", "desk surface, tilted to show face", "SURFACE", True, f"{product} oriented to show screen/indicator/port"),
            _st("control", f"on {product}", "ATTACHED", True, "controls still attached"),
        ]
        return [
            _step(1, 0.0, 1.5, f"Establish the {product} on the desk with screen, indicator, and port regions already visible enough to identify.", initial=s1, resulting=list(s1), visibility="device face visible", rules=["first-frame presence"], sources=[2], transition="tech:show_est"),
            _step(2, 1.5, 5.5, "Show the screen, indicator, and port on the same device. Do not invent UI chrome or menus.", initial=s1, resulting=s2r, visibility="indicator/port show", rules=["no invented UI"], sources=[2], transition="tech:show_io"),
            _step(3, 5.5, 8.0, "Hold the final screen/indicator/port view.", initial=s2r, resulting=list(s2r), visibility="final show hold", rules=["final-state lock"], final=True, transition="tech:show_final"),
        ]
    # place only (fail closed vs wear)
    s1 = [
        _st("product", "active hand above desk", "ACTIVE_HAND", True, f"{product} already in the active hand above the desk"),
        _st("desk", "clear landing zone", "FRAME_STATIC", True, "desk landing zone already in frame"),
    ]
    s2r = [
        _st("product", "desk surface", "SURFACE", True, f"{product} placed on the desk as designed for tabletop use"),
        _st("desk", "clear landing zone", "FRAME_STATIC", True, "desk supports the device"),
    ]
    return [
        _step(1, 0.0, 1.5, f"Establish the {product} in hand and the desk landing zone. Wear path is not used.", initial=s1, resulting=list(s1), visibility="hand and desk visible", rules=["first-frame presence", "place-only path"], sources=[3], transition="tech:place_est"),
        _step(2, 1.5, 5.5, f"Place the same {product} onto the desk surface in one continuous motion. Do not wear the device.", initial=s1, resulting=s2r, visibility="desk placement", rules=["explicit placement", "no wear"], sources=[3], transition="tech:place_desk"),
        _step(3, 5.5, 8.0, "Hold the final desk-placed state.", initial=s2r, resulting=list(s2r), visibility="final place hold", rules=["final-state lock"], final=True, transition="tech:place_final"),
    ]


def herbal_oil_steps_composed(action_count: int = 5) -> list[ChoreographyStep]:
    """Exact 8s oil fixture with source indexes covering all atomic actions."""
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
    # Map library actions 0..4 onto the preserved physical sequence.
    return [
        _step(1, 0.0, 1.0, "The bottle is already present in the avatar's support hand at the first frame, upright, label-forward, with stable product identity. It does not materialize after the scene begins.", initial=s1, resulting=list(s1), visibility="bottle, cap, support hand, and target limb already visible", rules=["first-frame presence", "no thin-air bottle"], sources=[0], transition="oil:hold"),
        _step(2, 1.0, 2.0, "The active hand grips the cap and rotates it exactly 90 degrees. Do not fully unscrew or remove the cap. The bottle remains in the support hand.", initial=s1, resulting=s2r, visibility="bottle stays in support hand; cap stays on the bottle", rules=["cap not removed", "support hand keeps the bottle"], sources=[1], transition="oil:cap90"),
        _step(3, 2.0, 3.3, "The avatar tilts the same bottle toward the same wrist/forearm as if dispensing a small amount externally. Do not create an uncontrolled stream. Preserve bottle, cap, hand, and target-limb identity.", initial=s2r, resulting=s3r, visibility="same bottle, cap, hands, and limb", rules=["no uncontrolled liquid", "identity lock"], sources=[2], transition="oil:apply"),
        _step(4, 3.3, 4.2, "The avatar returns the bottle upright and places it label-forward on the table. The bottle's move from hand to table is explicit.", initial=s3r, resulting=s4r, visibility="explicit hand-to-table placement", rules=["explicit placement", "hand transfer to table"], sources=[4], transition="oil:store_table"),
        _step(5, 4.2, 7.7, "The avatar massages the same external wrist/forearm. The same bottle remains stationary and visible on the table; it does not disappear or return to the hand.", initial=s4r, resulting=s5r, visibility="bottle stationary on the table during massage", rules=["bottle does not return to the hand", "same target limb"], sources=[3], transition="oil:massage"),
        _step(6, 7.7, 8.0, "Hold the final state. No new prop, duplicate hand, cap-state change, bottle teleportation, or unexplained object motion.", initial=s5r, resulting=list(s5r), visibility="final lock of bottle on table and massaged limb", rules=["final-state lock", "no new prop"], final=True, transition="oil:final"),
    ]


def roll_on_steps_composed() -> list[ChoreographyStep]:
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
        _step(1, 0.0, 1.0, "Establish the capped roll-on already in hand. Cap, label, and target limb are present in the first frame.", initial=s1, resulting=list(s1), visibility="capped roll-on and limb visible", rules=["first-frame presence"], sources=[0], transition="rollon:hold"),
        _step(2, 1.0, 2.0, "The active hand removes the cap and places the same cap visibly on the table. Do not lose or duplicate the cap.", initial=s1, resulting=s2r, visibility="cap placed on the table", rules=["explicit cap placement", "component custody retained"], sources=[1], transition="rollon:uncap"),
        _step(3, 2.0, 3.6, "The support hand rolls one controlled pass on the same external wrist/forearm. No extra product appears.", initial=s2r, resulting=s3r, visibility="roll-on on the same limb; cap stays on the table", rules=["one pass", "cap stays put"], sources=[2], transition="rollon:roll"),
        _step(4, 3.6, 4.4, "Place the roll-on upright beside the same cap. Placement is explicit.", initial=s3r, resulting=s4r, visibility="product and cap side by side on the table", rules=["explicit placement"], sources=[4], transition="rollon:park"),
        _step(5, 4.4, 6.7, "Massage only if the verified label authorizes it. Product and cap remain visible and stationary. No invented medical outcome.", initial=s4r, resulting=s5r, visibility="product and cap stationary and visible", rules=["no disappearance", "label-authorized massage only"], sources=[3], transition="rollon:massage"),
        _step(6, 6.7, 7.6, "Pick up the roll-on, replace the same cap, and return it upright. This is an explicit pickup and recap.", initial=s5r, resulting=s6r, visibility="same cap returns to the same roll-on", rules=["explicit pickup", "explicit recap", "hand transfer"], sources=[4], transition="rollon:recap"),
        _step(7, 7.6, 8.0, "Hold the final recapped upright state. No new prop or duplicate cap.", initial=s6r, resulting=list(s6r), visibility="final recapped hold", rules=["final-state lock"], final=True, transition="rollon:final"),
    ]


SPECIAL_STRATEGY_BUILDERS = {
    "LIP_COLOR": lip_color_steps,
    "BABY_WIPES": baby_wipes_steps,
    "APPAREL": apparel_steps,
    "ELECTRONICS_SMALL_DEVICE": electronics_small_device_steps,
}

COMPOSED_FAMILIES = frozenset({"HERBAL_OIL", "ROLL_ON"})
