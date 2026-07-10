"""Deterministic, storyboard-first planner for every production EXTEND video lane.

The planner is the only layer allowed to derive a multi-block story or spoken
dialogue from Copy Set intelligence. Renderers receive a ``BlockAllocation``
and may only render its assigned beats, exact dialogue slice, and continuity
state. This keeps F2V/FRAMES, T2V, HYBRID, and I2V on one canonical planning
contract while their visual-source laws remain explicit in small adapters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from typing import Any, Mapping, Sequence

from agent.services import canonical_prompt_compiler as canonical


PLAN_VERSION = "full_storyboard_first_extend_planner_v1"


class PlannerValidationError(ValueError):
    """A stable production invariant failure for a storyboard planner result."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


@dataclass(frozen=True)
class ContinuityState:
    product_identity: str
    product_scale: str
    product_position: str
    product_grip: str
    presenter_identity: str
    presenter_pose: str
    presenter_expression: str
    wardrobe: str
    environment: str
    lighting: str
    camera_framing: str
    camera_direction_path: str
    motion_direction: str
    emotional_state: str
    scene_progression: str
    reference_frame_relationship: str


@dataclass(frozen=True)
class StoryBeat:
    beat_id: str
    role: str
    start_s: float
    end_s: float
    objective: str
    visual_action: str
    product_state: str
    presenter_state: str
    environment_state: str
    camera_state: str
    motion_state: str
    emotional_state: str
    continuity_in: ContinuityState
    continuity_out: ContinuityState
    claim_constraints: tuple[str, ...]
    assigned_block_index: int | None = None


@dataclass(frozen=True)
class FullStoryPlan:
    plan_version: str
    route_id: str
    source_mode: str
    source_mode_adapter: str
    total_duration_seconds: int
    resolved_block_plan: tuple[int, ...]
    narrative_arc: str
    story_summary: str
    story_beats: tuple[StoryBeat, ...]
    compliance_metadata: dict[str, Any]
    source_copy_provenance: dict[str, Any]


@dataclass(frozen=True)
class DialogueUtterance:
    utterance_id: str
    role: str
    start_s: float
    end_s: float
    text: str
    word_count: int
    source_provenance: str
    assigned_block_index: int | None = None


@dataclass(frozen=True)
class FullDialoguePlan:
    plan_version: str
    target_language: str
    wps_mode: str
    total_duration_seconds: int
    total_word_budget: int
    actual_total_word_count: int
    full_dialogue_text: str
    utterances: tuple[DialogueUtterance, ...]
    approved_copy_provenance: dict[str, Any]
    compliance_metadata: dict[str, Any]


@dataclass(frozen=True)
class BlockAllocation:
    block_index: int
    block_role: str
    duration_seconds: int
    start_s: int
    end_s: int
    is_final: bool
    assigned_story_beat_ids: tuple[str, ...]
    assigned_story_beats: tuple[StoryBeat, ...]
    assigned_dialogue_utterance_ids: tuple[str, ...]
    assigned_dialogue_utterances: tuple[DialogueUtterance, ...]
    exact_dialogue_slice: str
    dialogue_word_budget: int
    actual_dialogue_word_count: int
    entry_continuity_state: ContinuityState
    exit_continuity_state: ContinuityState
    seam_policy: str
    continuation_instruction: str
    source_mode_adapter: str
    compliance_status: str
    final_cta_text: str
    end_frame_instruction: str


@dataclass(frozen=True)
class PlannerResult:
    plan_version: str
    input_fingerprint: str
    planner_fingerprint: str
    route_id: str
    source_mode: str
    total_duration_seconds: int
    resolved_block_plan: tuple[int, ...]
    full_story_plan: FullStoryPlan
    full_dialogue_plan: FullDialoguePlan
    block_allocations: tuple[BlockAllocation, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _stable_id(input_fingerprint: str, semantic_role: str, sequence: int) -> str:
    return hashlib.sha256(
        f"{PLAN_VERSION}|{input_fingerprint}|{semantic_role}|{sequence}".encode("utf-8")
    ).hexdigest()[:20]


def _mode_adapter(source_mode: str) -> str:
    adapters = {
        "FRAMES": "F2V_FRAMES_CONTINUITY",
        "T2V": "T2V_SCENE_CONTINUITY",
        "HYBRID": "HYBRID_REFERENCE_CONTINUITY",
        "INGREDIENTS": "I2V_REFERENCE_CONTINUITY",
    }
    try:
        return adapters[source_mode]
    except KeyError as exc:
        raise ValueError(f"UNSUPPORTED_STORYBOARD_SOURCE_MODE:{source_mode}") from exc


def _reference_frame_relationship(source_mode: str) -> str:
    relationships = {
        "FRAMES": "the uploaded finished frame is the initial state and is never reused as a reset source",
        "T2V": "the planned text-established scene is the initial state and each continuation inherits its prior generated exit",
        "HYBRID": "the product and presenter references lock identity, scale, wardrobe, and spatial relationship without resetting continuations",
        "INGREDIENTS": "the image references lock product and presenter truth while each continuation inherits the prior generated exit",
    }
    return relationships[source_mode]


def _block_role(index: int, total_blocks: int) -> str:
    if total_blocks == 1:
        return "ANCHOR"
    if index == 1:
        return "ANCHOR"
    if index == total_blocks:
        return "FINAL"
    return "CONTINUATION"


def _roles_for_block(index: int, total_blocks: int, shot_count: int) -> tuple[str, ...]:
    if total_blocks == 1:
        candidates = ("HOOK", "PROOF", "CTA")
    elif index == 1:
        candidates = ("HOOK", "PROBLEM", "CONTEXT")
    elif index == total_blocks:
        candidates = ("RESOLUTION", "CTA", "END_HOLD")
    elif index == 2:
        candidates = ("PRODUCT_INTRODUCTION", "ROUTINE", "PROOF")
    else:
        candidates = ("USP", "BENEFIT", "TRANSITION")
    return candidates[:max(1, shot_count)]


def _initial_state(
    *, source_mode: str, product_name: str, scene_context: str, presenter_identity: str,
) -> ContinuityState:
    environment = _clean(scene_context) or "the planned natural product-use environment"
    return ContinuityState(
        product_identity=product_name,
        product_scale="true real-world scale",
        product_position="held naturally within the established scene relationship",
        product_grip="stable, believable hand-object interaction",
        presenter_identity=presenter_identity,
        presenter_pose="natural three-quarter selling pose",
        presenter_expression="attentive and credible",
        wardrobe="the same established wardrobe",
        environment=environment,
        lighting="consistent soft natural light",
        camera_framing="eye-level medium close-up moving to product close-up",
        camera_direction_path="continuous forward commercial camera path",
        motion_direction="continuous natural forward motion",
        emotional_state="curious opening energy",
        scene_progression="opening story state",
        reference_frame_relationship=_reference_frame_relationship(source_mode),
    )


def _exit_state(entry: ContinuityState, *, role: str, block_index: int) -> ContinuityState:
    emotional = {
        "HOOK": "engaged opening energy",
        "PROBLEM": "recognition and relevance",
        "CONTEXT": "grounded context",
        "PRODUCT_INTRODUCTION": "credible product discovery",
        "ROUTINE": "easy routine confidence",
        "PROOF": "believable proof confidence",
        "USP": "clear product-value confidence",
        "BENEFIT": "resolved practical confidence",
        "TRANSITION": "forward narrative momentum",
        "RESOLUTION": "commercial resolution",
        "CTA": "decision-ready confidence",
        "END_HOLD": "calm final hold",
    }.get(role, entry.emotional_state)
    return replace(
        entry,
        presenter_expression=emotional,
        emotional_state=emotional,
        scene_progression=f"block {block_index} exits after {role.lower()}",
    )


def _state_text(state: ContinuityState) -> str:
    return (
        f"Keep {state.product_identity} at {state.product_scale}, {state.product_position}, with "
        f"{state.product_grip}; preserve {state.presenter_identity}, {state.presenter_pose}, "
        f"{state.wardrobe}, {state.environment}, {state.lighting}, {state.camera_framing}, "
        f"{state.camera_direction_path}, and {state.motion_direction}."
    )


def _build_story_plan(
    *,
    route_id: str,
    source_mode: str,
    product: dict[str, Any],
    normalized_copy: dict[str, Any],
    resolved_block_plan: Sequence[int],
    scene_context: str,
    shot_count_by_block: Sequence[int],
    input_fingerprint: str,
) -> FullStoryPlan:
    product_name = canonical._product_line(product)
    family = canonical._infer_product_family(product, normalized_copy)
    visual_name = canonical._product_visual_alias(product, family)
    focus = canonical._family_focus_terms(family)
    angle_hint = canonical._humanize_label(normalized_copy.get("angle", "")).lower()
    angle_signal = canonical._infer_angle_signal(normalized_copy, family)
    trigger_id = normalized_copy.get("trigger_id", "")
    cta_type = normalized_copy.get("cta_type", "")
    presenter_identity = "the resolved presenter" if source_mode in {"HYBRID", "T2V", "INGREDIENTS"} else "the source-frame presenter"
    cursor = 0
    state = _initial_state(
        source_mode=source_mode,
        product_name=product_name,
        scene_context=scene_context,
        presenter_identity=presenter_identity,
    )
    beats: list[StoryBeat] = []
    total_blocks = len(resolved_block_plan)
    for position, seconds in enumerate(resolved_block_plan, start=1):
        start = cursor
        end = start + int(seconds)
        shot_count = int(shot_count_by_block[position - 1])
        roles = _roles_for_block(position, total_blocks, shot_count)
        visuals = canonical._default_shot_plan(
            source_mode,
            product=product,
            shot_count=len(roles),
            block_index=position,
            total_blocks=total_blocks,
            family=family,
            angle_hint=angle_hint,
            angle_signal=angle_signal,
            trigger_id=trigger_id,
            cta_type=cta_type,
        )
        beat_start = float(start)
        interval = (end - start) / len(roles)
        for local_index, (role, visual) in enumerate(zip(roles, visuals), start=1):
            beat_end = float(end) if local_index == len(roles) else beat_start + interval
            beat_exit = _exit_state(state, role=role, block_index=position)
            sequence = len(beats) + 1
            beats.append(
                StoryBeat(
                    beat_id=f"beat_{_stable_id(input_fingerprint, role, sequence)}",
                    role=role,
                    start_s=beat_start,
                    end_s=beat_end,
                    objective=f"Advance the {role.lower().replace('_', ' ')} beat without inventing unsupported claims.",
                    visual_action=visual,
                    product_state=state.product_position,
                    presenter_state=state.presenter_pose,
                    environment_state=state.environment,
                    camera_state=state.camera_framing,
                    motion_state=state.motion_direction,
                    emotional_state=beat_exit.emotional_state,
                    continuity_in=state,
                    continuity_out=beat_exit,
                    claim_constraints=("approved_copy_only", "product_truth_locked", "no_unsupported_medical_claims"),
                )
            )
            state = beat_exit
            beat_start = beat_end
        cursor = end
    total_duration = sum(int(seconds) for seconds in resolved_block_plan)
    return FullStoryPlan(
        plan_version=PLAN_VERSION,
        route_id=route_id,
        source_mode=source_mode,
        source_mode_adapter=_mode_adapter(source_mode),
        total_duration_seconds=total_duration,
        resolved_block_plan=tuple(int(seconds) for seconds in resolved_block_plan),
        narrative_arc="HOOK_TO_PROOF_TO_RESOLUTION",
        story_summary=f"A single {total_duration}-second {source_mode.lower()} story moves from hook through product proof to one final CTA closure for {visual_name}.",
        story_beats=tuple(beats),
        compliance_metadata={
            "claims": "approved_copy_and_product_truth_only",
            "requires_final_cta": bool(normalized_copy.get("cta")),
            "product_truth_lock": "required",
        },
        source_copy_provenance={"copy_source": normalized_copy.get("copy_source") or "fallback", "route_id": route_id},
    )


def _build_dialogue_plan(
    *,
    product: dict[str, Any],
    normalized_copy: dict[str, Any],
    story_plan: FullStoryPlan,
    target_language: str,
    wps_mode: str,
    dialogue_enabled: bool,
    approved_dialogue: str | None,
    input_fingerprint: str,
) -> FullDialoguePlan:
    budgets = [
        canonical.dialogue_word_budget(seconds, target_language, wps_mode=wps_mode)
        for seconds in story_plan.resolved_block_plan
    ]
    utterances: list[DialogueUtterance] = []
    cursor = 0
    for position, seconds in enumerate(story_plan.resolved_block_plan, start=1):
        budget = budgets[position - 1]
        dialogue = ""
        if dialogue_enabled:
            dialogue = canonical.build_block_dialogue(
                copy=normalized_copy,
                block_index=position,
                total_blocks=len(story_plan.resolved_block_plan),
                budget=budget,
                target_language=target_language,
                family=canonical._infer_product_family(product, normalized_copy),
                approved_dialogue=approved_dialogue,
            )
        if dialogue:
            role = "CTA" if position == len(story_plan.resolved_block_plan) and normalized_copy.get("cta") else "DIALOGUE"
            utterances.append(
                DialogueUtterance(
                    utterance_id=f"utterance_{_stable_id(input_fingerprint, role, position)}",
                    role=role,
                    start_s=float(cursor),
                    end_s=float(cursor + int(seconds)),
                    text=dialogue,
                    word_count=len(dialogue.split()),
                    source_provenance=normalized_copy.get("copy_source") or "fallback_copy_intelligence",
                )
            )
        cursor += int(seconds)
    full_text = " ".join(utterance.text for utterance in utterances)
    return FullDialoguePlan(
        plan_version=PLAN_VERSION,
        target_language=target_language,
        wps_mode=str(wps_mode).upper(),
        total_duration_seconds=story_plan.total_duration_seconds,
        total_word_budget=sum(budgets) if dialogue_enabled else 0,
        actual_total_word_count=len(full_text.split()),
        full_dialogue_text=full_text,
        utterances=tuple(utterances),
        approved_copy_provenance={"copy_source": normalized_copy.get("copy_source") or "fallback"},
        compliance_metadata={"generated_once": True, "final_cta_required": bool(normalized_copy.get("cta"))},
    )


def _end_frame_instruction(
    *, source_mode: str, product: dict[str, Any], normalized_copy: dict[str, Any], is_final: bool,
) -> str:
    family = canonical._infer_product_family(product, normalized_copy)
    return canonical._section_8_end_frame(
        mode=source_mode,
        pname=canonical._product_line(product),
        visual_name=canonical._product_visual_alias(product, family),
        is_final=is_final,
        focus=canonical._family_focus_terms(family),
        family=family,
        angle_signal=canonical._infer_angle_signal(normalized_copy, family),
        trigger_id=normalized_copy.get("trigger_id", ""),
        cta_type=normalized_copy.get("cta_type", ""),
    )


def _allocate(
    *,
    story_plan: FullStoryPlan,
    dialogue_plan: FullDialoguePlan,
    product: dict[str, Any],
    normalized_copy: dict[str, Any],
) -> tuple[FullStoryPlan, FullDialoguePlan, tuple[BlockAllocation, ...]]:
    allocations: list[BlockAllocation] = []
    allocated_beats: list[StoryBeat] = []
    allocated_utterances: list[DialogueUtterance] = []
    cursor = 0
    previous_exit: ContinuityState | None = None
    for position, seconds in enumerate(story_plan.resolved_block_plan, start=1):
        start = cursor
        end = start + int(seconds)
        is_final = position == len(story_plan.resolved_block_plan)
        block_beats = [
            replace(beat, assigned_block_index=position)
            for beat in story_plan.story_beats
            if beat.start_s >= start and beat.end_s <= end
        ]
        block_utterances = [
            replace(utterance, assigned_block_index=position)
            for utterance in dialogue_plan.utterances
            if utterance.start_s >= start and utterance.end_s <= end
        ]
        if not block_beats:
            raise PlannerValidationError("MISSING_STORY_BEAT_ALLOCATION", f"block={position}")
        entry = previous_exit or block_beats[0].continuity_in
        exit_state = block_beats[-1].continuity_out
        dialogue_slice = " ".join(utterance.text for utterance in block_utterances)
        budget = canonical.dialogue_word_budget(seconds, dialogue_plan.target_language, wps_mode=dialogue_plan.wps_mode)
        allocations.append(
            BlockAllocation(
                block_index=position,
                block_role=_block_role(position, len(story_plan.resolved_block_plan)),
                duration_seconds=int(seconds),
                start_s=start,
                end_s=end,
                is_final=is_final,
                assigned_story_beat_ids=tuple(beat.beat_id for beat in block_beats),
                assigned_story_beats=tuple(block_beats),
                assigned_dialogue_utterance_ids=tuple(utterance.utterance_id for utterance in block_utterances),
                assigned_dialogue_utterances=tuple(block_utterances),
                exact_dialogue_slice=dialogue_slice,
                dialogue_word_budget=budget if dialogue_plan.total_word_budget else 0,
                actual_dialogue_word_count=len(dialogue_slice.split()),
                entry_continuity_state=entry,
                exit_continuity_state=exit_state,
                seam_policy="FINAL_CTA_END_HOLD" if is_final else "CONTINUE_FROM_EXIT_STATE_NO_FINAL_CTA",
                continuation_instruction=(
                    "Complete the allocated final resolution and end hold without opening a new story."
                    if is_final
                    else f"The next block must begin from this exact exit state: {_state_text(exit_state)}"
                ),
                source_mode_adapter=story_plan.source_mode_adapter,
                compliance_status="CLAIM_SAFE_COPY_BOUND",
                final_cta_text=_clean(normalized_copy.get("cta")) if is_final else "",
                end_frame_instruction=_end_frame_instruction(
                    source_mode=story_plan.source_mode,
                    product=product,
                    normalized_copy=normalized_copy,
                    is_final=is_final,
                ),
            )
        )
        allocated_beats.extend(block_beats)
        allocated_utterances.extend(block_utterances)
        previous_exit = exit_state
        cursor = end
    return (
        replace(story_plan, story_beats=tuple(allocated_beats)),
        replace(dialogue_plan, utterances=tuple(allocated_utterances)),
        tuple(allocations),
    )


def plan_full_storyboard(
    *,
    route_id: str,
    source_mode: str,
    product: dict[str, Any],
    copy_intelligence: dict[str, Any] | None,
    resolved_block_plan: Sequence[int],
    target_language: str,
    wps_mode: str,
    scene_context: str = "",
    dialogue_enabled: bool = True,
    approved_dialogue: str | None = None,
    shot_count_by_block: Sequence[int] | None = None,
) -> PlannerResult:
    """Build one complete story and dialogue plan before rendering any block."""
    source_mode = _clean(source_mode).upper()
    route_id = _clean(route_id).upper()
    plan = tuple(int(seconds) for seconds in resolved_block_plan)
    if not plan or any(seconds <= 0 for seconds in plan):
        raise PlannerValidationError("INVALID_BLOCK_PLAN", str(list(plan)))
    if source_mode not in {"FRAMES", "T2V", "HYBRID", "INGREDIENTS"}:
        raise PlannerValidationError("UNSUPPORTED_STORYBOARD_SOURCE_MODE", source_mode)
    if shot_count_by_block is None:
        shot_count_by_block = tuple(2 for _ in plan)
    if len(shot_count_by_block) != len(plan) or any(int(count) <= 0 for count in shot_count_by_block):
        raise PlannerValidationError("INVALID_SHOT_COUNT_PLAN")
    normalized_copy = canonical.normalize_copy_intelligence(copy_intelligence, product=product)
    input_fingerprint = _fingerprint(
        {
            "route_id": route_id,
            "source_mode": source_mode,
            "product": product,
            "copy": normalized_copy,
            "block_plan": plan,
            "target_language": target_language,
            "wps_mode": str(wps_mode).upper(),
            "scene_context": _clean(scene_context),
            "dialogue_enabled": dialogue_enabled,
            "approved_dialogue": _clean(approved_dialogue),
            "shot_count_by_block": list(shot_count_by_block),
        }
    )
    story_plan = _build_story_plan(
        route_id=route_id,
        source_mode=source_mode,
        product=product,
        normalized_copy=normalized_copy,
        resolved_block_plan=plan,
        scene_context=scene_context,
        shot_count_by_block=shot_count_by_block,
        input_fingerprint=input_fingerprint,
    )
    dialogue_plan = _build_dialogue_plan(
        product=product,
        normalized_copy=normalized_copy,
        story_plan=story_plan,
        target_language=target_language,
        wps_mode=wps_mode,
        dialogue_enabled=dialogue_enabled,
        approved_dialogue=approved_dialogue,
        input_fingerprint=input_fingerprint,
    )
    story_plan, dialogue_plan, allocations = _allocate(
        story_plan=story_plan,
        dialogue_plan=dialogue_plan,
        product=product,
        normalized_copy=normalized_copy,
    )
    draft = PlannerResult(
        plan_version=PLAN_VERSION,
        input_fingerprint=input_fingerprint,
        planner_fingerprint="",
        route_id=route_id,
        source_mode=source_mode,
        total_duration_seconds=sum(plan),
        resolved_block_plan=plan,
        full_story_plan=story_plan,
        full_dialogue_plan=dialogue_plan,
        block_allocations=allocations,
    )
    result = replace(draft, planner_fingerprint=_fingerprint(draft.to_dict()))
    validate_planner_result(result)
    return result


def _result_dict(result: PlannerResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result, PlannerResult):
        return result.to_dict()
    return dict(result)


def validate_planner_result(result: PlannerResult | Mapping[str, Any]) -> None:
    """Enforce canonical duration, allocation, continuity, CTA, and WPS laws."""
    data = _result_dict(result)
    allocations = list(data.get("block_allocations") or [])
    block_plan = [int(seconds) for seconds in data.get("resolved_block_plan") or []]
    total = int(data.get("total_duration_seconds") or 0)
    if not allocations or len(allocations) != len(block_plan):
        raise PlannerValidationError("INVALID_FINAL_BLOCK_COUNT")
    durations = [int(allocation.get("duration_seconds") or 0) for allocation in allocations]
    if durations != block_plan:
        raise PlannerValidationError("INCONSISTENT_ROUTE_BLOCK_PLAN")
    if sum(durations) != total:
        raise PlannerValidationError("PLANNER_DURATION_SUM_MISMATCH")
    cursor = 0
    final_count = 0
    allocated_beat_ids: list[str] = []
    allocated_utterance_ids: list[str] = []
    previous_exit: Any = None
    for allocation in allocations:
        start = int(allocation.get("start_s") or 0)
        end = int(allocation.get("end_s") or 0)
        if end <= start:
            raise PlannerValidationError("INVALID_BLOCK_DURATION")
        if start > cursor:
            raise PlannerValidationError("PLANNER_TIMELINE_GAP")
        if start < cursor:
            raise PlannerValidationError("PLANNER_TIMELINE_OVERLAP")
        if end - start != int(allocation.get("duration_seconds") or 0):
            raise PlannerValidationError("PLANNER_DURATION_SUM_MISMATCH")
        if allocation.get("is_final"):
            final_count += 1
        assigned_beats = list(allocation.get("assigned_story_beats") or [])
        assigned_utterances = list(allocation.get("assigned_dialogue_utterances") or [])
        if not assigned_beats:
            raise PlannerValidationError("MISSING_STORY_BEAT_ALLOCATION")
        allocated_beat_ids.extend(allocation.get("assigned_story_beat_ids") or [])
        allocated_utterance_ids.extend(allocation.get("assigned_dialogue_utterance_ids") or [])
        if not allocation.get("is_final") and (
            allocation.get("final_cta_text")
            or any(beat.get("role") == "CTA" for beat in assigned_beats)
            or any(utterance.get("role") == "CTA" for utterance in assigned_utterances)
        ):
            raise PlannerValidationError("CTA_IN_NON_FINAL_BLOCK")
        if previous_exit is not None and allocation.get("entry_continuity_state") != previous_exit:
            raise PlannerValidationError("CONTINUITY_STATE_MISMATCH")
        if allocation.get("block_index", 1) > 1 and not allocation.get("entry_continuity_state"):
            raise PlannerValidationError("CONTINUATION_STATE_LINK_MISSING")
        if int(allocation.get("actual_dialogue_word_count") or 0) > int(allocation.get("dialogue_word_budget") or 0):
            raise PlannerValidationError("DIALOGUE_PLAN_EXCEEDS_WPS_BUDGET")
        previous_exit = allocation.get("exit_continuity_state")
        cursor = end
    if cursor != total:
        raise PlannerValidationError("PLANNER_DURATION_SUM_MISMATCH")
    if final_count != 1 or not allocations[-1].get("is_final"):
        raise PlannerValidationError("INVALID_FINAL_BLOCK_COUNT")
    story_beats = list((data.get("full_story_plan") or {}).get("story_beats") or [])
    dialogue_utterances = list((data.get("full_dialogue_plan") or {}).get("utterances") or [])
    expected_beat_ids = [beat.get("beat_id") for beat in story_beats]
    expected_utterance_ids = [utterance.get("utterance_id") for utterance in dialogue_utterances]
    if len(allocated_beat_ids) != len(set(allocated_beat_ids)):
        raise PlannerValidationError("DUPLICATE_STORY_BEAT_ALLOCATION")
    if set(allocated_beat_ids) != set(expected_beat_ids):
        raise PlannerValidationError("MISSING_STORY_BEAT_ALLOCATION")
    if len(allocated_utterance_ids) != len(set(allocated_utterance_ids)):
        raise PlannerValidationError("DUPLICATE_DIALOGUE_UTTERANCE_ALLOCATION")
    if set(allocated_utterance_ids) != set(expected_utterance_ids):
        raise PlannerValidationError("MISSING_DIALOGUE_UTTERANCE_ALLOCATION")
    cta_required = bool((data.get("full_dialogue_plan") or {}).get("compliance_metadata", {}).get("final_cta_required"))
    if cta_required and not allocations[-1].get("final_cta_text"):
        raise PlannerValidationError("FINAL_CTA_REQUIRED")
