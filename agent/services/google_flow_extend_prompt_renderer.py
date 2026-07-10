"""Route-aware prompt representations for Google Flow manual Extend research.

Architecture (read-only of planner; no second story path):

  FULL_STORY_PLAN → FULL_DIALOGUE_PLAN → BLOCK_ALLOCATION → prompt renderers

Representations per block:
  * INITIAL_GENERATION  — Block 1 full 9-section standalone prompt
  * INDEPENDENT_BLOCK   — existing full 9-section prompt (production route)
  * GOOGLE_FLOW_EXTEND  — Block 2+ compact extension-native prompt

``engine_prompt_text`` remains the independent-block representation for backward
compatibility with existing automation and consumers.

Does NOT authorize GOOGLE_FLOW_VEO_EXTEND production route authority.
Does NOT activate [8,7] duration plans. Manual research only.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

RENDERER_VERSION = "google_flow_extend_prompt_renderer_v2"
VALIDATION_VERSION = "flow_extend_validation_v2"

PROMPT_REPRESENTATION_INITIAL = "INITIAL_GENERATION"
PROMPT_REPRESENTATION_INDEPENDENT = "INDEPENDENT_BLOCK"
PROMPT_REPRESENTATION_EXTEND = "GOOGLE_FLOW_EXTEND"

PROMPT_PURPOSE_PRODUCTION = "PRODUCTION_INDEPENDENT"
PROMPT_PURPOSE_MANUAL_EXTEND = "MANUAL_EXTENSION_RESEARCH"

CONTINUATION_SOURCE_PREVIOUS_VIDEO = "PREVIOUS_GENERATED_VIDEO"
CONTINUATION_SOURCE_NONE = "NONE"

# Standalone-generation openings forbidden on extend prompts.
_STANDALONE_OPENING_PATTERNS = (
    r"(?i)^\s*you are generating\b",
    r"(?i)^\s*generate (?:another|an?|a new)\b",
    r"(?i)^\s*opening block\b",
    r"(?i)^\s*create (?:another|an?|a new)\s+(?:video|clip|block)\b",
    r"(?i)^\s*build a new video\b",
    r"(?i)^\s*start from the uploaded reference\b",
    r"(?i)^\s*recreate the (?:scene|presenter|product)\b",
    r"(?i)^\s*reintroduce the product\b",
)

_EXTEND_FIRST_LINE_RE = re.compile(r"(?i)^\s*extend this video\b")

_PLANNER_LEAK_PATTERNS = (
    r"\bBlockAllocation\b",
    r"\bWPS\b",
    r"\broute_id\b",
    r"\bsource_mode\b",
    r"\bfull_storyboard\b",
    r"\bplanner_fingerprint\b",
    r"\bGOOGLE_FLOW_VEO_EXTEND\b",
)

# Product-truth lock markers that must not dominate the extend prompt.
_PRODUCT_LOCK_MARKERS = (
    "PRODUCT IDENTITY LOCK",
    "PRODUCT GEOMETRY LOCK",
    "PRODUCT SCALE LOCK",
    "PRODUCT NEGATIVE MORPH RULES",
    "PRODUCT REFERENCE LOCK",
    "FRAME PERSISTENCE LOCK",
    "SECTION 1 - ROLE & OBJECTIVE",
    "SECTION 2 - PRODUCT TRUTH LOCK",
)

_DANGLING_END_RE = re.compile(
    r"(?i)\b(and|or|dan|atau|sebab|because|kalau|if|bila|when|supaya|untuk|yang|pun|dengan|dengan|macam|seperti|than|dengan)$"
)
_INCOMPLETE_NOUN_END_RE = re.compile(
    r"(?i)\b(badan|perut|malam|pagi|rutin|botol|minyak|anak|ibu|rutin malam)\.?$"
)


class ExtendPromptValidationError(ValueError):
    """Stable production invariant failure for extension prompt rendering."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "__dict__"):
        return dict(getattr(value, "__dict__", {}) or {})
    return {}


def _product_line(product: Mapping[str, Any] | None) -> str:
    product = product or {}
    return _clean(
        product.get("product_display_name")
        or product.get("name")
        or product.get("raw_product_title")
        or product.get("product_short_name")
        or "the product"
    )


def _compact_product_invariant(product: Mapping[str, Any] | None, source_mode: str) -> str:
    """One concise product lock line — never the full 9-section Product Truth Lock."""
    pname = _product_line(product)
    product = product or {}
    scale_hint = _clean(
        product.get("product_scale_lock")
        or product.get("recommended_scale")
        or product.get("section_5_product_physics_prompt")
    )
    if source_mode in {"HYBRID", "INGREDIENTS", "FRAMES"}:
        if scale_hint and len(scale_hint.split()) <= 28:
            return (
                f"Keep the exact same {_clean(pname)} already visible in the previous video "
                f"({scale_hint}). Do not regenerate, resize, relabel, replace, or reintroduce it."
            )
        return (
            f"Keep the exact same {_clean(pname)} already visible in the previous video — "
            "same scale, grip, label, and packaging truth. Do not regenerate, resize, "
            "relabel, replace, or reintroduce it."
        )
    # T2V — generated product state continues without reference restart.
    return (
        f"Preserve the same generated product state for {_clean(pname)} already visible in "
        "the previous video. Do not rebuild packaging or reintroduce the product as a new hero."
    )


def _mode_continuation_law(source_mode: str) -> str:
    mode = _clean(source_mode).upper() or "T2V"
    laws = {
        "T2V": (
            "Continue the generated person, product state, environment, camera path, action, "
            "emotional progression, and story. Do not rebuild the scene from the original "
            "text description or reintroduce the presenter or product as a new opening."
        ),
        "HYBRID": (
            "Continue the exact generated presenter, product relationship, grip, product scale, "
            "wardrobe, environment, lighting, camera, and action. Product and avatar references "
            "remain identity truth only — do not restart from the product image or rebuild a "
            "new composite scene."
        ),
        "FRAMES": (
            "Continue from the previous generated video, not the original uploaded frame. "
            "Do not reset pose to the initial frame, rebuild the composition, or describe the "
            "original frame as the new starting input."
        ),
        "INGREDIENTS": (
            "Reference images remain identity and product-truth anchors only. Continue from "
            "the prior generated video — do not reconstruct from the reference-image set, "
            "restart the avatar pose, restart the product reveal, or re-establish the style scene."
        ),
    }
    return laws.get(mode, laws["T2V"])


def _extend_command_line(*, block_index: int) -> str:
    if int(block_index) == 2:
        return "Extend this video from the exact ending of Video 1."
    return "Extend this video from the exact ending of the previously extended video."


def _state_summary(state: Mapping[str, Any] | None) -> str:
    state = _as_dict(state)
    if not state:
        return (
            "the exact final visible state of the previous video: same presenter, product, "
            "grip, wardrobe, room, lighting, camera distance, camera direction, motion, and emotional tone"
        )
    parts = [
        _clean(state.get("product_identity")),
        _clean(state.get("product_grip") or state.get("product_position")),
        _clean(state.get("presenter_pose") or state.get("presenter_identity")),
        _clean(state.get("wardrobe")),
        _clean(state.get("environment")),
        _clean(state.get("lighting")),
        _clean(state.get("camera_framing")),
        _clean(state.get("camera_direction_path")),
        _clean(state.get("motion_direction")),
        _clean(state.get("emotional_state")),
    ]
    joined = "; ".join(part for part in parts if part)
    if not joined:
        return (
            "the exact final visible state of the previous video: same presenter, product, "
            "grip, wardrobe, room, lighting, camera, motion, and emotional tone"
        )
    words = joined.split()
    if len(words) > 40:
        joined = " ".join(words[:40]).rstrip(",;:") + "..."
    return joined


def _next_visual_action(allocation: Mapping[str, Any]) -> str:
    beats = list(allocation.get("assigned_story_beats") or [])
    actions = [_clean(beat.get("visual_action") if isinstance(beat, Mapping) else getattr(beat, "visual_action", "")) for beat in beats]
    actions = [a for a in actions if a]
    if not actions:
        return (
            "Continue the exact hand, mouth, body, and camera movement already in progress "
            "through the allocated next commercial beat."
        )
    # Prefer first beat; keep compact for manual Extend paste (no multi-page story dump).
    action = actions[0]
    words = action.split()
    if len(words) > 55:
        action = " ".join(words[:55]).rstrip(",;:") + "."
    return action


def _ending_policy(*, is_final: bool, end_frame_instruction: str, final_cta_text: str) -> str:
    if is_final:
        cta = _clean(final_cta_text)
        close = _clean(end_frame_instruction)
        parts = [
            "End only after the allocated dialogue is complete, with the presenter and the same product in a believable final closing pose."
        ]
        if cta:
            parts.append("Land the final call-to-action naturally without shouting or a hard ad tableau.")
        if close and len(close.split()) <= 40:
            parts.append(close)
        return " ".join(parts)
    return (
        "Do not close the commercial arc yet. During the final second, the presenter remains "
        "naturally speaking and moving. Preserve mouth movement, hand motion, grip, camera "
        "direction, and emotional momentum so the next video can extend the same action and voice."
    )


def build_audio_seam_contract(
    *,
    allocation: Mapping[str, Any],
    previous_allocation: Mapping[str, Any] | None = None,
    next_allocation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit audio-seam metadata for extension research (Google Flow voice law).

    Voice extension is ineffective when voice is absent from the final ~1s of the source.
    """
    allocation = _as_dict(allocation)
    previous_allocation = _as_dict(previous_allocation) if previous_allocation else None
    next_allocation = _as_dict(next_allocation) if next_allocation else None
    is_final = bool(allocation.get("is_final"))
    duration = float(allocation.get("duration_seconds") or 0)
    start_s = float(allocation.get("start_s") or 0)
    end_s = float(allocation.get("end_s") or (start_s + duration))
    utterances = list(allocation.get("assigned_dialogue_utterances") or [])

    last_utt_end = 0.0
    first_utt_start = None
    for utt in utterances:
        u = _as_dict(utt)
        u_end = float(u.get("end_s") or 0)
        u_start = float(u.get("start_s") or 0)
        last_utt_end = max(last_utt_end, u_end)
        if first_utt_start is None or u_start < first_utt_start:
            first_utt_start = u_start

    # Prefer absolute timeline; fall back to relative block timing.
    if last_utt_end <= 0 and utterances:
        # Relative packing: assume dialogue spans most of the block.
        last_utt_end = end_s
    if first_utt_start is None:
        first_utt_start = start_s

    has_dialogue = bool(_clean(allocation.get("exact_dialogue_slice")))
    voice_required = (not is_final) and has_dialogue
    # Planned from actual utterance end times (no fabrication of missing dialogue).
    voice_planned = bool(voice_required and last_utt_end >= (end_s - 1.05))
    # Verified remains null until live runtime evidence exists.
    voice_verified = None
    voice_active_final = voice_planned

    prev_end = None
    if previous_allocation is not None:
        prev_end = float(previous_allocation.get("end_s") or 0)
        prev_utts = list(previous_allocation.get("assigned_dialogue_utterances") or [])
        for utt in prev_utts:
            prev_end = max(prev_end, float(_as_dict(utt).get("end_s") or 0))

    next_start = None
    if next_allocation is not None:
        next_start = float(next_allocation.get("start_s") or 0)
        next_utts = list(next_allocation.get("assigned_dialogue_utterances") or [])
        for utt in next_utts:
            u_start = float(_as_dict(utt).get("start_s") or 0)
            if next_start is None or u_start < next_start:
                next_start = u_start

    if is_final:
        policy = "FINAL_BLOCK_NO_NEXT_EXTENSION_SEAM"
    else:
        policy = "VOICE_ACTIVE_FINAL_SECOND_NATURAL_CLAUSE_BOUNDARY"

    return {
        "audio_seam_in": "CONTINUE_FROM_PRIOR_VOICE_AND_MOTION" if previous_allocation else "INITIAL_BLOCK_NO_PRIOR_SEAM",
        "audio_seam_out": (
            "FINAL_HOLD_AFTER_COMPLETE_DIALOGUE"
            if is_final
            else "VOICE_AND_MOTION_ACTIVE_FOR_EXTENSION"
        ),
        "voice_active_in_final_second_required": bool(voice_required) if not is_final else False,
        "voice_active_in_final_second_planned": bool(voice_planned) if not is_final else False,
        "voice_active_in_final_second_verified": voice_verified,
        # Compatibility mirror (planned only — not verified).
        "voice_active_in_final_second": bool(voice_planned) if not is_final else False,
        "dialogue_continuation_policy": policy,
        "previous_block_dialogue_end_s": prev_end if previous_allocation else None,
        "next_block_dialogue_start_s": next_start if next_allocation else None,
        "this_block_dialogue_start_s": float(first_utt_start) if first_utt_start is not None and has_dialogue else None,
        "this_block_dialogue_end_s": float(last_utt_end) if last_utt_end and has_dialogue else None,
        "requires_visible_mouth_motion_final_second": not is_final,
        "requires_body_or_hand_motion_final_second": not is_final,
        "requires_camera_momentum_final_second": not is_final,
        "forbid_silent_final_hold": not is_final,
        "forbid_frozen_pose_final_second": not is_final,
        "forbid_final_cta_until_last_block": not is_final,
    }


def render_flow_extend_prompt(
    *,
    allocation: Mapping[str, Any],
    previous_allocation: Mapping[str, Any],
    product: Mapping[str, Any] | None,
    source_mode: str,
    target_language: str = "BM_MS",
    previous_block_index: int | None = None,
) -> str:
    """Render a compact Google Flow Extend-native prompt for Block 2+.

    Required semantic order:
      1. Extension command
      2. Exact prior-state continuation
      3. No-cut / no-reset / no-reintroduction law
      4. Critical identity locks
      5. Next allocated visual action
      6. Exact allocated dialogue
      7. Audio seam behavior
      8. Final / next-seam ending
      9. No-overlay rule
    """
    allocation = _as_dict(allocation)
    previous_allocation = _as_dict(previous_allocation)
    block_index = int(allocation.get("block_index") or 0)
    if block_index < 2:
        raise ExtendPromptValidationError(
            "EXTEND_PROMPT_BLOCK1_FORBIDDEN",
            "flow_extend_prompt_text is only valid for block_index >= 2",
        )
    is_final = bool(allocation.get("is_final"))
    dialogue = _clean(allocation.get("exact_dialogue_slice"))
    entry = _as_dict(allocation.get("entry_continuity_state"))
    prev_exit = _as_dict(previous_allocation.get("exit_continuity_state"))
    # Continuity law: previous exit MUST equal current entry. Fail closed.
    if not prev_exit or not entry:
        raise ExtendPromptValidationError(
            "CONTINUITY_STATE_MISMATCH",
            f"block={allocation.get('block_index')} missing entry or previous exit continuity",
        )
    if prev_exit != entry:
        raise ExtendPromptValidationError(
            "CONTINUITY_STATE_MISMATCH",
            f"block={allocation.get('block_index')} previous exit != current entry",
        )
    continuity_state = entry

    prev_idx = int(previous_block_index if previous_block_index is not None else previous_allocation.get("block_index") or (block_index - 1))
    command = _extend_command_line(block_index=block_index)
    state = _state_summary(continuity_state)
    product_lock = _compact_product_invariant(product, source_mode)
    mode_law = _mode_continuation_law(source_mode)
    visual = _next_visual_action(allocation)
    ending = _ending_policy(
        is_final=is_final,
        end_frame_instruction=_clean(allocation.get("end_frame_instruction")),
        final_cta_text=_clean(allocation.get("final_cta_text")),
    )
    lang = "Malay" if str(target_language).upper().startswith("BM") else str(target_language)

    paragraphs = [
        command,
        (
            f"Continue immediately from the exact ending of Video {prev_idx if block_index == 2 else 'the previous extension'} "
            f"with no cut, reset, new opening, scene reconstruction, or dead air. {_mode_continuation_law(source_mode)}"
            if False
            else (
                "Continue immediately with no cut, reset, new opening, or scene reconstruction. "
                f"{mode_law}"
            )
        ),
        (
            f"Preserve the same presenter, product, grip, wardrobe, room, lighting, camera distance, "
            f"camera direction, motion, and emotional tone. Prior state to inherit: {state}."
        ),
        product_lock,
        (
            "Continue the exact hand, mouth, body, and camera movement already in progress. "
            f"{visual}"
        ),
    ]
    if dialogue:
        paragraphs.append(
            f"The presenter continues speaking in {lang}: \"{dialogue}\" "
            "Begin the speech and physical continuation naturally without dead air or a repeated hook. "
            "Do not repeat any earlier hook or opening line."
        )
    else:
        paragraphs.append(
            "Keep natural ambient presence with no new spoken hook and no dead-air restart."
        )
    if not is_final:
        paragraphs.append(
            "During the final second, the presenter remains naturally speaking and moving. "
            "Preserve mouth movement, hand motion, grip, camera direction, and emotional momentum "
            "so the next video can extend the same action and voice."
        )
    paragraphs.append(ending)
    paragraphs.append(
        "No captions, subtitles, graphic text, price text, stickers, watermarks, or new visual elements. "
        "The only readable text allowed is text physically printed on the real product label."
    )

    text = "\n\n".join(p.strip() for p in paragraphs if _clean(p))
    validate_flow_extend_prompt(text, independent_block_prompt_text=None)
    return text


def validate_flow_extend_prompt(
    text: str,
    *,
    independent_block_prompt_text: str | None = None,
) -> None:
    """Production validators for extension-native prompts."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ExtendPromptValidationError("EXTEND_PROMPT_EMPTY")
    if not _EXTEND_FIRST_LINE_RE.search(cleaned.splitlines()[0] if cleaned.splitlines() else cleaned):
        raise ExtendPromptValidationError(
            "EXTEND_PROMPT_STANDALONE_OPENING_FORBIDDEN",
            "first line must begin with 'Extend this video…'",
        )
    first = cleaned.splitlines()[0]
    for pattern in _STANDALONE_OPENING_PATTERNS:
        if re.search(pattern, first):
            raise ExtendPromptValidationError(
                "EXTEND_PROMPT_STANDALONE_OPENING_FORBIDDEN",
                first[:120],
            )
    if re.search(r"(?i)you are generating an?\s+\d+-second", cleaned):
        raise ExtendPromptValidationError(
            "EXTEND_PROMPT_STANDALONE_OPENING_FORBIDDEN",
            "standalone generation duration language present",
        )
    for pattern in _PLANNER_LEAK_PATTERNS:
        if re.search(pattern, cleaned):
            raise ExtendPromptValidationError("EXTEND_PROMPT_PLANNER_METADATA_LEAK", pattern)
    for marker in _PRODUCT_LOCK_MARKERS:
        if marker in cleaned:
            raise ExtendPromptValidationError(
                "EXTEND_PROMPT_EXCESSIVE_STANDALONE_DUPLICATION",
                marker,
            )
    if independent_block_prompt_text:
        ind = independent_block_prompt_text.strip()
        if cleaned == ind:
            raise ExtendPromptValidationError(
                "EXTEND_PROMPT_IDENTICAL_TO_INDEPENDENT",
            )
        # Detect wholesale 9-section duplication
        section_hits = sum(1 for i in range(1, 10) if f"SECTION {i} -" in cleaned)
        if section_hits >= 6:
            raise ExtendPromptValidationError(
                "EXTEND_PROMPT_EXCESSIVE_STANDALONE_DUPLICATION",
                f"section_hits={section_hits}",
            )
    words = cleaned.split()
    if len(words) > 450:
        raise ExtendPromptValidationError(
            "EXTEND_PROMPT_EXCESSIVE_STANDALONE_DUPLICATION",
            f"word_count={len(words)}",
        )



def validate_extend_representation(
    *,
    flow_extend_prompt_text: str | None,
    prompt_representation: str | None = None,
) -> dict:
    """Validate Extend representation; never classify as Extend on non-empty alone."""
    text = (flow_extend_prompt_text or "").strip()
    errors: list[str] = []
    if not text:
        return {
            "valid": False,
            "renderer_version": RENDERER_VERSION,
            "validation_version": VALIDATION_VERSION,
            "error_codes": ["EXTEND_PROMPT_EMPTY"],
        }
    try:
        validate_flow_extend_prompt(text)
    except ExtendPromptValidationError as exc:
        errors.append(exc.code)
    if prompt_representation and prompt_representation != PROMPT_REPRESENTATION_EXTEND:
        errors.append("EXTEND_REPRESENTATION_MISMATCH")
    return {
        "valid": not errors,
        "renderer_version": RENDERER_VERSION,
        "validation_version": VALIDATION_VERSION,
        "error_codes": errors,
    }


def dialogue_slice_is_natural_boundary(text: str, *, position: str) -> bool:
    """Linguistic seam check (not timestamp-only).

    Valid Malay/English sentences may end with object nouns such as:
    malam, anak, ibu, botol, minyak, badan, perut.
    Only incomplete stumps and dangling connectors fail.
    """
    cleaned = _clean(text)
    if not cleaned:
        return True
    if position == "end":
        bare = cleaned.rstrip(".!?…")
        dangling = (
            "and", "or", "dan", "atau", "sebab", "because", "kalau", "if", "bila",
            "when", "supaya", "untuk", "yang", "pun", "dengan", "the", "a", "an",
        )
        last = bare.split()[-1].casefold().strip(".,!?") if bare.split() else ""
        if last in dangling:
            return False
        if cleaned[-1] not in ".!?…" and len(cleaned.split()) <= 3:
            return False
        last_clause = cleaned
        for sep in (". ", "! ", "? "):
            if sep in cleaned:
                last_clause = cleaned.split(sep)[-1]
        last_bare = last_clause.strip().rstrip(".!?…")
        last_norm = last_bare.replace(",", " ").replace(";", " ")
        last_words = [w for w in last_norm.split() if w]
        if not last_words:
            return True
        joined = " ".join(last_words).casefold()
        incomplete_stumps = (
            "esok pagi badan",
            "esok pagi",
            "tidur tak lena, esok pagi badan",
            "tidur tak lena esok pagi badan",
        )
        joined_n = joined.replace(",", " ")
        for stump in incomplete_stumps:
            stump_n = stump.replace(",", " ")
            if joined_n == stump_n or joined_n.endswith(" " + stump_n):
                return False
        # Pure noun leftovers only (e.g. "badan." / "botol."). Verb+object
        # clauses like "Simpan botol." / "Legakan perut." remain valid.
        if len(last_words) == 1 and last in {
            "badan", "perut", "malam", "pagi", "rutin", "botol", "minyak", "anak", "ibu",
        }:
            return False
        return True
    if position == "start":
        if len(cleaned.split()) <= 2 and cleaned[-1] not in ".!?…":
            return False
        return True
    return True


def validate_dialogue_seams(allocations: Sequence[Mapping[str, Any]]) -> None:
    """Fail closed on unnatural dialogue block seams."""
    rows = [_as_dict(a) for a in allocations]
    for idx, allocation in enumerate(rows):
        slice_text = _clean(allocation.get("exact_dialogue_slice"))
        if not slice_text:
            continue
        if not allocation.get("is_final"):
            if not dialogue_slice_is_natural_boundary(slice_text, position="end"):
                raise ExtendPromptValidationError(
                    "UNNATURAL_DIALOGUE_SEAM",
                    f"block={allocation.get('block_index')} end={slice_text!r}",
                )
        if idx > 0:
            if not dialogue_slice_is_natural_boundary(slice_text, position="start"):
                # Allow short CTA-only final opens.
                utts = list(allocation.get("assigned_dialogue_utterances") or [])
                roles = {_clean(_as_dict(u).get("role")).upper() for u in utts}
                if roles <= {"CTA", "RESOLUTION"} and allocation.get("is_final"):
                    continue
                raise ExtendPromptValidationError(
                    "UNNATURAL_DIALOGUE_SEAM",
                    f"block={allocation.get('block_index')} start={slice_text!r}",
                )




RESEARCH_VOICE_ACTIVE_END_FRAME = (
    "During the final second, the presenter remains naturally speaking and moving with "
    "the product still in grip, face toward camera, mouth movement visible, hand motion "
    "active, and camera momentum preserved so the next video can extend the same action "
    "and voice. Do not end on a silent hold, frozen pose, completed commercial closure, "
    "or final CTA. Do not close the commercial arc yet."
)


def build_research_initial_generation_prompt(
    independent_block_prompt_text: str,
    *,
    multi_block: bool,
    is_final: bool,
) -> str:
    """Research-specific Block 1 prompt with active voice seam for multi-block plans.

    Production independent_block_prompt_text remains unchanged (seam-ready hold).
    """
    independent = independent_block_prompt_text or ""
    if not multi_block or is_final or not independent:
        return independent
    marker = "SECTION 8 - CTA & END FRAME"
    if marker not in independent:
        return independent
    head, _, rest = independent.partition(marker)
    s9 = "SECTION 9 - NO_OVERLAY"
    if s9 not in rest:
        return independent
    _body, _, tail = rest.partition(s9)
    nl = chr(10)
    return head + marker + nl + RESEARCH_VOICE_ACTIVE_END_FRAME + nl + nl + s9 + tail


def _representation_bundle(
    text: str | None,
    audio_base: Mapping[str, Any],
    *,
    role: str,
) -> dict[str, Any] | None:
    """Structured representation entry: prompt text + representation-specific audio contract."""
    cleaned = (text or "").strip()
    if not cleaned and role != PROMPT_REPRESENTATION_INDEPENDENT:
        return None
    audio = dict(_as_dict(audio_base))
    audio["representation"] = role
    if role == PROMPT_REPRESENTATION_INITIAL:
        audio["contract_purpose"] = "ACTIVE_FINAL_SECOND_FOR_EXTEND_CHAIN"
    elif role == PROMPT_REPRESENTATION_INDEPENDENT:
        audio["contract_purpose"] = "SEAM_READY_HOLD_INDEPENDENT_ROUTE"
    elif role == PROMPT_REPRESENTATION_EXTEND:
        audio["contract_purpose"] = "CONTINUATION_FROM_PRIOR_VIDEO"
    return {"text": cleaned or None, "audio_seam_contract": audio}


def attach_prompt_representations(
    *,
    block: dict[str, Any],
    independent_block_prompt_text: str,
    allocation: Mapping[str, Any] | None,
    previous_allocation: Mapping[str, Any] | None,
    next_allocation: Mapping[str, Any] | None,
    product: Mapping[str, Any] | None,
    source_mode: str,
    target_language: str = "BM_MS",
) -> dict[str, Any]:
    """Attach representation fields onto a compiled prompt block dict (mutates and returns)."""
    allocation = _as_dict(allocation) if allocation else {}
    block_index = int(block.get("block_index") or allocation.get("block_index") or 1)
    is_final = bool(block.get("is_final") if block.get("is_final") is not None else allocation.get("is_final"))
    independent = independent_block_prompt_text or block.get("engine_prompt_text") or ""

    block["independent_block_prompt_text"] = independent
    # Compatibility: engine_prompt_text stays independent-block representation.
    block["engine_prompt_text"] = independent
    block["engine_prompt_representation"] = PROMPT_REPRESENTATION_INDEPENDENT
    block["prompt_purpose_production"] = PROMPT_PURPOSE_PRODUCTION

    audio_seam = build_audio_seam_contract(
        allocation=allocation or block,
        previous_allocation=previous_allocation,
        next_allocation=next_allocation,
    )
    block["audio_seam_contract"] = audio_seam

    if block_index <= 1:
        multi_block = bool(block.get("_research_multi_block"))
        research_initial = build_research_initial_generation_prompt(
            independent,
            multi_block=multi_block,
            is_final=is_final,
        )
        block["initial_generation_prompt_text"] = research_initial
        block["flow_extend_prompt_text"] = None
        block["prompt_representation"] = PROMPT_REPRESENTATION_INITIAL
        # Research package may expose active-voice initial while production
        # independent remains the GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS text.
        block["prompt_purpose"] = (
            PROMPT_PURPOSE_MANUAL_EXTEND
            if multi_block and research_initial != independent
            else PROMPT_PURPOSE_PRODUCTION
        )
        block["previous_block_index"] = None
        block["continuation_source"] = CONTINUATION_SOURCE_NONE
        block["prompt_representations"] = {
            PROMPT_REPRESENTATION_INITIAL: _representation_bundle(
                research_initial, audio_seam, role=PROMPT_REPRESENTATION_INITIAL
            ),
            PROMPT_REPRESENTATION_INDEPENDENT: _representation_bundle(
                independent, audio_seam, role=PROMPT_REPRESENTATION_INDEPENDENT
            ),
            PROMPT_REPRESENTATION_EXTEND: None,
        }
        return block

    if not previous_allocation:
        raise ExtendPromptValidationError(
            "CONTINUATION_STATE_LINK_MISSING",
            f"block={block_index} missing previous allocation for extend render",
        )
    extend_text = render_flow_extend_prompt(
        allocation=allocation or block,
        previous_allocation=previous_allocation,
        product=product,
        source_mode=source_mode,
        target_language=target_language,
        previous_block_index=int(previous_allocation.get("block_index") or (block_index - 1)),
    )
    validate_flow_extend_prompt(extend_text, independent_block_prompt_text=independent)
    validation = validate_extend_representation(
        flow_extend_prompt_text=extend_text,
        prompt_representation=PROMPT_REPRESENTATION_EXTEND,
    )
    if not validation["valid"]:
        raise ExtendPromptValidationError(
            validation["error_codes"][0] if validation["error_codes"] else "EXTEND_PROMPT_INVALID",
        )
    block["initial_generation_prompt_text"] = None
    block["flow_extend_prompt_text"] = extend_text
    block["flow_extend_prompt_validation"] = validation
    block["prompt_representation"] = PROMPT_REPRESENTATION_EXTEND
    block["prompt_purpose"] = PROMPT_PURPOSE_MANUAL_EXTEND
    block["previous_block_index"] = int(previous_allocation.get("block_index") or (block_index - 1))
    block["continuation_source"] = CONTINUATION_SOURCE_PREVIOUS_VIDEO
    block["prompt_representations"] = {
        PROMPT_REPRESENTATION_INITIAL: None,
        PROMPT_REPRESENTATION_INDEPENDENT: _representation_bundle(
            independent, audio_seam, role=PROMPT_REPRESENTATION_INDEPENDENT
        ),
        PROMPT_REPRESENTATION_EXTEND: _representation_bundle(
            extend_text, audio_seam, role=PROMPT_REPRESENTATION_EXTEND
        ),
    }
    # Research-only metadata — must not claim VEO extend route authority.
    block["manual_extension_research"] = {
        "authorized_production_route": "GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS",
        "google_flow_veo_extend_authority": "ROUTE_DURATION_AUTHORITY_MISSING",
        "purpose": PROMPT_PURPOSE_MANUAL_EXTEND,
        "renderer_version": RENDERER_VERSION,
        "is_final_block": is_final,
    }
    return block


def enrich_compiled_prompt_blocks(
    *,
    compiled_blocks: list[dict[str, Any]],
    planner_result: Mapping[str, Any] | None,
    product: Mapping[str, Any] | None,
    source_mode: str,
    target_language: str = "BM_MS",
) -> list[dict[str, Any]]:
    """Post-process all compiled blocks with dual prompt representations."""
    planner = _as_dict(planner_result) if planner_result else {}
    allocations = list(planner.get("block_allocations") or [])
    allocation_by_index = {
        int(_as_dict(a).get("block_index") or 0): _as_dict(a) for a in allocations
    }
    # Dialogue seam validation on planner allocations (fail closed when present).
    if allocations:
        try:
            validate_dialogue_seams(allocations)
        except ExtendPromptValidationError:
            # Seam repair is attempted by the planner; re-raise for visibility.
            raise

    multi_block = len(compiled_blocks) > 1
    enriched: list[dict[str, Any]] = []
    for i, block in enumerate(compiled_blocks):
        b = dict(block)
        b["_research_multi_block"] = multi_block
        idx = int(b.get("block_index") or (i + 1))
        allocation = allocation_by_index.get(idx) or b.get("allocation")
        prev = allocation_by_index.get(idx - 1)
        nxt = allocation_by_index.get(idx + 1)
        independent = b.get("independent_block_prompt_text") or b.get("engine_prompt_text") or ""
        attach_prompt_representations(
            block=b,
            independent_block_prompt_text=independent,
            allocation=allocation,
            previous_allocation=prev,
            next_allocation=nxt,
            product=product,
            source_mode=source_mode,
            target_language=target_language,
        )
        b.pop("_research_multi_block", None)
        enriched.append(b)
    return enriched
