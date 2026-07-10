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


PLAN_VERSION = "full_storyboard_first_extend_planner_v2"


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


def _global_story_roles(total_duration: int) -> tuple[str, ...]:
    """Return one semantic arc from duration, never from block positions."""
    beat_count = max(2, total_duration // 4)
    if beat_count == 2:
        return ("HOOK", "CTA")
    if beat_count == 3:
        return ("HOOK", "PROOF", "CTA")
    middle_roles = ("PRODUCT_INTRODUCTION", "ROUTINE", "PROOF", "USP", "BENEFIT", "TRANSITION")
    needed_middle_roles = beat_count - 4
    return (
        "HOOK",
        "PROBLEM",
        *(middle_roles[index % len(middle_roles)] for index in range(needed_middle_roles)),
        "RESOLUTION",
        "CTA",
    )


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


def _exit_state(
    entry: ContinuityState,
    *,
    role: str,
    sequence: int,
    visual_action: str,
) -> ContinuityState:
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
    state_changes = {
        "HOOK": {
            "presenter_pose": "natural three-quarter selling pose leaning into the opening",
            "motion_direction": "subtle forward settling motion",
        },
        "PROBLEM": {
            "presenter_pose": "recognition pose with the product held in-frame",
            "camera_framing": "eye-level medium close-up tightening toward the product",
            "camera_direction_path": "continuous gentle inward camera push",
        },
        "PRODUCT_INTRODUCTION": {
            "product_position": "raised beside the presenter at chest level with the label facing camera",
            "product_grip": "secure label-facing presentation grip",
            "camera_framing": "medium close-up transitioning to a truthful product close-up",
            "motion_direction": "controlled hand lift toward the product label",
        },
        "ROUTINE": {
            "product_position": "moving naturally between the presenter and the routine surface",
            "product_grip": "controlled routine-use grip",
            "presenter_pose": "relaxed routine demonstration pose",
            "camera_direction_path": "short lateral camera track following the routine action",
            "motion_direction": "gentle lateral hand movement through the routine",
        },
        "PROOF": {
            "camera_framing": "truthful detail close-up with presenter and product co-presence",
            "camera_direction_path": "steady close-in proof framing",
            "motion_direction": "small deliberate handling adjustment",
        },
        "USP": {
            "product_position": "held steady at a readable angle inside the established scene",
            "product_grip": "stable readable-detail grip",
            "camera_framing": "steady product-detail medium close-up",
        },
        "BENEFIT": {
            "presenter_pose": "resolved practical-confidence pose",
            "camera_direction_path": "ease back to the established presenter-product framing",
            "motion_direction": "settling motion toward resolution",
        },
        "RESOLUTION": {
            "product_position": "held naturally at chest level for the resolved selling moment",
            "presenter_pose": "steady resolution pose with direct eye contact",
            "camera_framing": "balanced presenter-product closing frame",
            "motion_direction": "calm settling motion",
        },
        "CTA": {
            "product_position": "held truthfully in the final call-to-action frame",
            "product_grip": "steady final label-facing grip",
            "presenter_pose": "decision-ready final hold pose",
            "camera_direction_path": "stable final hold without a reset",
            "motion_direction": "minimal seam-free final stillness",
        },
    }.get(role, {})
    visual_progression = _clean(visual_action).split(".", 1)[0].lower()
    return replace(
        entry,
        presenter_expression=emotional,
        emotional_state=emotional,
        scene_progression=f"global beat {sequence} advances through {role.lower()}: {visual_progression}",
        **state_changes,
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
    state = _initial_state(
        source_mode=source_mode,
        product_name=product_name,
        scene_context=scene_context,
        presenter_identity=presenter_identity,
    )
    total_duration = sum(int(seconds) for seconds in resolved_block_plan)
    roles = _global_story_roles(total_duration)
    visual_templates = canonical._default_shot_plan(
        source_mode,
        product=product,
        shot_count=4,
        block_index=1,
        total_blocks=1,
        family=family,
        angle_hint=angle_hint,
        angle_signal=angle_signal,
        trigger_id=trigger_id,
        cta_type=cta_type,
    )
    beats: list[StoryBeat] = []
    beat_duration = total_duration / len(roles)
    for sequence, role in enumerate(roles, start=1):
        start_s = (sequence - 1) * beat_duration
        end_s = total_duration if sequence == len(roles) else sequence * beat_duration
        visual_template_index = (
            len(visual_templates) - 1
            if role in {"RESOLUTION", "CTA"}
            else (sequence - 1) % max(1, len(visual_templates) - 1)
        )
        visual_template = visual_templates[visual_template_index]
        visual_action = f"{visual_template} This is the allocated global {role.lower().replace('_', ' ')} beat."
        beat_exit = _exit_state(
            state,
            role=role,
            sequence=sequence,
            visual_action=visual_action,
        )
        beats.append(
            StoryBeat(
                beat_id=f"beat_{_stable_id(input_fingerprint, role, sequence)}",
                role=role,
                start_s=start_s,
                end_s=end_s,
                objective=f"Advance the {role.lower().replace('_', ' ')} beat without inventing unsupported claims.",
                visual_action=visual_action,
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
    cta = _clean(normalized_copy.get("cta"))
    clause_specs = _global_dialogue_clause_specs(
        normalized_copy=normalized_copy,
        approved_dialogue=approved_dialogue,
        final_cta=cta,
        target_language=target_language,
        family=canonical._infer_product_family(product, normalized_copy),
    ) if dialogue_enabled else []
    clause_specs = _compress_global_dialogue_clause_specs(
        clause_specs=clause_specs,
        total_budget=sum(budgets) if dialogue_enabled else 0,
        final_block_budget=budgets[-1] if dialogue_enabled else 0,
        total_blocks=len(story_plan.resolved_block_plan),
    )
    utterances = _timestamp_global_dialogue_utterances(
        clause_specs=clause_specs,
        total_duration=story_plan.total_duration_seconds,
        input_fingerprint=input_fingerprint,
        source_provenance=normalized_copy.get("copy_source") or "fallback_copy_intelligence",
    )
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
        compliance_metadata={"generated_once": True, "final_cta_required": bool(cta and dialogue_enabled)},
    )


def _dialogue_clause_key(clause: str) -> str:
    return " ".join(character.casefold() if character.isalnum() else " " for character in _clean(clause)).strip()


def _global_dialogue_clause_specs(
    *,
    normalized_copy: dict[str, Any],
    approved_dialogue: str | None,
    final_cta: str,
    target_language: str,
    family: str,
) -> list[tuple[str, str]]:
    """Build one semantic Copy Set sequence without any block-local inputs."""
    source_text = _clean(approved_dialogue)
    if source_text:
        raw_specs = [
            ("HOOK" if index == 0 else "CONTEXT", clause)
            for index, clause in enumerate(canonical._split_clauses(source_text))
        ]
    elif normalized_copy.get("copy_source") == "selected_copy_set":
        raw_specs = [
            *( ("HOOK", clause) for clause in canonical._split_clauses(normalized_copy.get("hook")) ),
            *( ("CONTEXT", clause) for clause in canonical._split_clauses(normalized_copy.get("subhook")) ),
            *( ("CONTEXT", clause) for clause in canonical._split_clauses(normalized_copy.get("angle")) ),
            *( ("USP", clause) for usp in normalized_copy.get("usps") or [] for clause in canonical._split_clauses(usp) ),
        ]
    else:
        fallback_clauses = canonical._formula_dialogue_clauses(
            normalized_copy,
            block_index=1,
            total_blocks=1,
            target_language=target_language,
            family=family,
        )
        family_closing = _clean(canonical._family_dialogue_clause(family, "cta", target_language))
        family_closing_key = _dialogue_clause_key(family_closing)
        cta_bridge = _clean(canonical._strategic_cta_bridge(
            normalized_copy.get("cta_type", ""),
            normalized_copy.get("cta", ""),
            target_language,
        ))
        cta_bridge_key = _dialogue_clause_key(cta_bridge)
        raw_specs = [
            (
                "HOOK"
                if index == 0
                else "RESOLUTION"
                if _dialogue_clause_key(clause) in {family_closing_key, cta_bridge_key}
                else "PROOF",
                clause,
            )
            for index, clause in enumerate(fallback_clauses)
        ]
        if family_closing and not any(
            _dialogue_clause_key(clause) == family_closing_key
            for _, clause in raw_specs
        ):
            raw_specs.append(("RESOLUTION", family_closing))
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    cta_key = _dialogue_clause_key(final_cta)
    for role, raw_clause in raw_specs:
        clause = _clean(raw_clause)
        key = _dialogue_clause_key(clause)
        if not key or key == cta_key or key in seen:
            continue
        seen.add(key)
        specs.append((role, clause))
    if final_cta:
        specs.append(("CTA", final_cta))
    return specs


def _compress_global_dialogue_clause_specs(
    *,
    clause_specs: Sequence[tuple[str, str]],
    total_budget: int,
    final_block_budget: int,
    total_blocks: int,
) -> list[tuple[str, str]]:
    cta_specs = [(role, text) for role, text in clause_specs if role == "CTA"]
    if len(cta_specs) > 1:
        raise PlannerValidationError("DUPLICATE_FINAL_CTA")
    cta_text = cta_specs[0][1] if cta_specs else ""
    cta_words = len(cta_text.split())
    if cta_text and cta_words > final_block_budget:
        raise PlannerValidationError("FINAL_CTA_CANNOT_FIT_WPS_BUDGET")
    final_roles = {"CTA"} if total_blocks == 1 else {"RESOLUTION", "CTA"}
    final_specs = [(role, text) for role, text in clause_specs if role in final_roles]
    reserved_final_words = sum(len(text.split()) for _, text in final_specs)
    if reserved_final_words > final_block_budget:
        remaining_final_words = final_block_budget - cta_words
        compressed_final_specs: list[tuple[str, str]] = []
        for role, text in final_specs:
            if role == "CTA":
                continue
            if len(text.split()) <= remaining_final_words:
                compressed_final_specs.append((role, text))
                remaining_final_words -= len(text.split())
                continue
            shortened = canonical._pack_dialogue_clauses([text], remaining_final_words)
            if shortened:
                compressed_final_specs.append((role, shortened))
            remaining_final_words = 0
            break
        if cta_text:
            compressed_final_specs.append(("CTA", cta_text))
        final_specs = compressed_final_specs
        reserved_final_words = sum(len(text.split()) for _, text in final_specs)
    remaining_budget = total_budget - reserved_final_words
    if remaining_budget < 0:
        raise PlannerValidationError("DIALOGUE_PLAN_EXCEEDS_WPS_BUDGET")
    compressed: list[tuple[str, str]] = []
    for role, text in clause_specs:
        if role in final_roles:
            continue
        words = len(text.split())
        if words <= remaining_budget:
            compressed.append((role, text))
            remaining_budget -= words
            continue
        shortened = canonical._pack_dialogue_clauses([text], remaining_budget)
        if shortened:
            compressed.append((role, shortened))
        remaining_budget = 0
        break
    compressed.extend(final_specs)
    return compressed


def _timestamp_global_dialogue_utterances(
    *,
    clause_specs: Sequence[tuple[str, str]],
    total_duration: int,
    input_fingerprint: str,
    source_provenance: str,
) -> list[DialogueUtterance]:
    total_words = sum(len(text.split()) for _, text in clause_specs)
    cursor_words = 0
    utterances: list[DialogueUtterance] = []
    for sequence, (role, text) in enumerate(clause_specs, start=1):
        word_count = len(text.split())
        start_s = (total_duration * cursor_words / total_words) if total_words else 0.0
        cursor_words += word_count
        end_s = (total_duration * cursor_words / total_words) if total_words else 0.0
        utterances.append(
            DialogueUtterance(
                utterance_id=f"utterance_{_stable_id(input_fingerprint, role, sequence)}",
                role=role,
                start_s=start_s,
                end_s=end_s,
                text=text,
                word_count=word_count,
                source_provenance=source_provenance,
            )
        )
    return utterances


def _allocate_dialogue_utterances(
    dialogue_plan: FullDialoguePlan,
    resolved_block_plan: Sequence[int],
) -> tuple[FullDialoguePlan, tuple[tuple[DialogueUtterance, ...], ...]]:
    budgets = [
        canonical.dialogue_word_budget(seconds, dialogue_plan.target_language, wps_mode=dialogue_plan.wps_mode)
        for seconds in resolved_block_plan
    ]
    cta_utterances = [utterance for utterance in dialogue_plan.utterances if utterance.role == "CTA"]
    if len(cta_utterances) > 1:
        raise PlannerValidationError("DUPLICATE_FINAL_CTA")
    cta_words = sum(utterance.word_count for utterance in cta_utterances)
    final_roles = {"CTA"} if len(resolved_block_plan) == 1 else {"RESOLUTION", "CTA"}
    final_utterances = [
        utterance for utterance in dialogue_plan.utterances if utterance.role in final_roles
    ]
    reserved_final_words = sum(utterance.word_count for utterance in final_utterances)
    if cta_words > budgets[-1]:
        raise PlannerValidationError("FINAL_CTA_CANNOT_FIT_WPS_BUDGET")
    if reserved_final_words > budgets[-1]:
        raise PlannerValidationError("DIALOGUE_PLAN_EXCEEDS_WPS_BUDGET")
    allocated_by_block: list[list[DialogueUtterance]] = [[] for _ in resolved_block_plan]
    used_words = [0 for _ in resolved_block_plan]
    block_index = 0
    for utterance in dialogue_plan.utterances:
        if utterance.role in final_roles:
            continue
        while block_index < len(resolved_block_plan):
            reserved_words = reserved_final_words if block_index == len(resolved_block_plan) - 1 else 0
            available_words = budgets[block_index] - reserved_words - used_words[block_index]
            if utterance.word_count <= available_words:
                allocated_by_block[block_index].append(utterance)
                used_words[block_index] += utterance.word_count
                break
            shortened = canonical._pack_dialogue_clauses([utterance.text], available_words)
            if shortened:
                compressed_utterance = replace(
                    utterance,
                    text=shortened,
                    word_count=len(shortened.split()),
                )
                allocated_by_block[block_index].append(compressed_utterance)
                used_words[block_index] += compressed_utterance.word_count
                break
            block_index += 1
        else:
            raise PlannerValidationError("DIALOGUE_PLAN_EXCEEDS_WPS_BUDGET")
    if final_utterances:
        final_index = len(resolved_block_plan) - 1
        if used_words[final_index] + reserved_final_words > budgets[final_index]:
            raise PlannerValidationError("FINAL_CTA_CANNOT_FIT_WPS_BUDGET")
        allocated_by_block[final_index].extend(final_utterances)
    allocated_utterances: list[DialogueUtterance] = []
    cursor = 0
    for position, seconds in enumerate(resolved_block_plan):
        block_budget = budgets[position]
        block_cursor_words = 0
        for utterance in allocated_by_block[position]:
            start_s = cursor + (seconds * block_cursor_words / block_budget) if block_budget else float(cursor)
            block_cursor_words += utterance.word_count
            end_s = cursor + (seconds * block_cursor_words / block_budget) if block_budget else float(cursor)
            allocated_utterances.append(
                replace(
                    utterance,
                    start_s=start_s,
                    end_s=end_s,
                    assigned_block_index=position + 1,
                )
            )
        cursor += int(seconds)
    full_text = " ".join(utterance.text for utterance in allocated_utterances)
    return (
        replace(
            dialogue_plan,
            actual_total_word_count=len(full_text.split()),
            full_dialogue_text=full_text,
            utterances=tuple(allocated_utterances),
        ),
        tuple(tuple(block) for block in allocated_by_block),
    )


def _allocate_story_beats(
    story_plan: FullStoryPlan,
) -> tuple[FullStoryPlan, tuple[tuple[StoryBeat, ...], ...]]:
    windows: list[tuple[int, int]] = []
    cursor = 0
    for seconds in story_plan.resolved_block_plan:
        windows.append((cursor, cursor + int(seconds)))
        cursor += int(seconds)
    allocated_by_block: list[list[StoryBeat]] = [[] for _ in windows]
    allocated_beats: list[StoryBeat] = []
    for beat in story_plan.story_beats:
        segments = [
            (block_index, max(beat.start_s, start_s), min(beat.end_s, end_s))
            for block_index, (start_s, end_s) in enumerate(windows, start=1)
            if beat.start_s < end_s and beat.end_s > start_s
        ]
        if not segments:
            raise PlannerValidationError("MISSING_STORY_BEAT_ALLOCATION", beat.beat_id)
        previous_exit: ContinuityState | None = None
        for segment_index, (block_index, start_s, end_s) in enumerate(segments, start=1):
            is_split = len(segments) > 1
            continuation_suffix = (
                " Continue this allocated beat from the prior segment without restarting the action."
                if is_split and segment_index > 1
                else " End this allocated segment seam-ready for the next window."
                if is_split
                else ""
            )
            continuity_in = previous_exit or beat.continuity_in
            continuity_out = beat.continuity_out
            continuation_prefix = (
                f"{_continuation_visual_instruction(story_plan.source_mode)} "
                if block_index > 1 and not allocated_by_block[block_index - 1]
                else ""
            )
            allocated_beat = replace(
                beat,
                beat_id=(
                    f"{beat.beat_id}_segment_{segment_index}"
                    if is_split
                    else beat.beat_id
                ),
                start_s=start_s,
                end_s=end_s,
                visual_action=f"{continuation_prefix}{beat.visual_action}{continuation_suffix}",
                continuity_in=continuity_in,
                continuity_out=continuity_out,
                assigned_block_index=block_index,
            )
            allocated_by_block[block_index - 1].append(allocated_beat)
            allocated_beats.append(allocated_beat)
            previous_exit = continuity_out
    return replace(story_plan, story_beats=tuple(allocated_beats)), tuple(
        tuple(block) for block in allocated_by_block
    )


def _continuation_visual_instruction(source_mode: str) -> str:
    instructions = {
        "FRAMES": (
            "Continue immediately from the prior generated state with the same finished-frame pose, grip, lighting, and camera path; never reset to the uploaded frame."
        ),
        "T2V": (
            "Continue immediately from the prior generated scene with the same presenter, grip, lighting, and camera path; keep it lived-in, scene-native, and socially believable rather than restarting the commercial."
        ),
        "HYBRID": (
            "Continue immediately from the prior generated state with the same avatar identity, product scale, wardrobe, grip, and camera path; do not rebuild from reference assets."
        ),
        "INGREDIENTS": (
            "Continue immediately from the prior generated state with product and presenter truth locked; do not reset to the reference image."
        ),
    }
    return instructions[source_mode]


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
    story_plan, story_by_block = _allocate_story_beats(story_plan)
    dialogue_plan, dialogue_by_block = _allocate_dialogue_utterances(
        dialogue_plan,
        story_plan.resolved_block_plan,
    )
    allocations: list[BlockAllocation] = []
    allocated_beats: list[StoryBeat] = []
    allocated_utterances: list[DialogueUtterance] = []
    cursor = 0
    previous_exit: ContinuityState | None = None
    for position, seconds in enumerate(story_plan.resolved_block_plan, start=1):
        start = cursor
        end = start + int(seconds)
        is_final = position == len(story_plan.resolved_block_plan)
        block_beats = list(story_by_block[position - 1])
        block_utterances = list(dialogue_by_block[position - 1])
        block_utterances = [
            replace(
                utterance,
                start_s=next(
                    planned.start_s
                    for planned in dialogue_plan.utterances
                    if planned.utterance_id == utterance.utterance_id
                ),
                end_s=next(
                    planned.end_s
                    for planned in dialogue_plan.utterances
                    if planned.utterance_id == utterance.utterance_id
                ),
                assigned_block_index=position,
            )
            for utterance in block_utterances
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
    final_allocation = allocations[-1]
    final_cta_text = _clean(final_allocation.get("final_cta_text"))
    if cta_required and not final_cta_text:
        raise PlannerValidationError("FINAL_CTA_REQUIRED")
    if cta_required:
        final_dialogue = _clean(final_allocation.get("exact_dialogue_slice"))
        final_utterances = list(final_allocation.get("assigned_dialogue_utterances") or [])
        if final_cta_text not in final_dialogue or not any(
            utterance.get("role") == "CTA" and _clean(utterance.get("text")) == final_cta_text
            for utterance in final_utterances
        ):
            raise PlannerValidationError("FINAL_CTA_CANNOT_FIT_WPS_BUDGET")
        if any(
            final_cta_text in _clean(allocation.get("exact_dialogue_slice"))
            for allocation in allocations[:-1]
        ):
            raise PlannerValidationError("CTA_IN_NON_FINAL_BLOCK")
    concatenated_dialogue = _clean(" ".join(
        _clean(allocation.get("exact_dialogue_slice")) for allocation in allocations
    ))
    full_dialogue = _clean((data.get("full_dialogue_plan") or {}).get("full_dialogue_text"))
    if concatenated_dialogue != full_dialogue:
        raise PlannerValidationError("DIALOGUE_ALLOCATION_TEXT_MISMATCH")
