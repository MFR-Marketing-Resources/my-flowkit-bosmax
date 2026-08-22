"""Shared provider-free video continuity and temporal occupancy authority.

This module is deliberately independent from any lane adapter.  It owns the
small, serialisable contract that every video surface must carry to the
canonical prompt compiler: shot handling, product custody, truth identity and
dialogue occupancy.  Provider text is generated from this receipt, but the
receipt is also validated before a job can be created.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


VIDEO_CONTINUITY_CONTRACT_VERSION = "VIDEO_CONTINUITY_V1"
PRODUCT_PRESENCE_MASCOT = "PRODUCT_MASCOT"

SHOT_TYPES = ("EWS", "WS", "MS", "MCU", "CU", "ECU", "POV", "OTS")
CUSTODY_STATES = (
    "HELD_LEFT",
    "HELD_RIGHT",
    "SUPPORTED_SURFACE",
    "WORN_OR_APPLIED",
    "PRODUCT_MASCOT_SELF",
)

ERR_SHOT_HANDLING_UNMAPPED = "SHOT_HANDLING_UNMAPPED"
ERR_PRODUCT_CUSTODY_INVALID = "PRODUCT_CUSTODY_INVALID"
ERR_PRODUCT_CUSTODY_TRANSITION_INVALID = "PRODUCT_CUSTODY_TRANSITION_INVALID"
ERR_DIALOGUE_SWEETWPS_UNDERRUN = "DIALOGUE_SWEETWPS_UNDERRUN"
ERR_DIALOGUE_SWEETWPS_OVERRUN = "DIALOGUE_SWEETWPS_OVERRUN"
ERR_DIALOGUE_TIMELINE_INVALID = "DIALOGUE_TIMELINE_INVALID"
ERR_DIALOGUE_WPS_MODE_REQUIRED = "DIALOGUE_SWEETWPS_REQUIRED"


class VideoContinuityContractError(ValueError):
    """Stable fail-closed contract error with machine-readable details."""

    def __init__(self, code: str, detail: str = "", *, details: Mapping[str, Any] | None = None):
        self.code = code
        self.detail = detail
        self.details = dict(details or {})
        message = code if not detail else f"{code}:{detail}"
        if self.details:
            message = f"{message}:{json.dumps(self.details, sort_keys=True, ensure_ascii=True)}"
        super().__init__(message)


_SHOT_HANDLING_MATRIX: dict[str, dict[str, str]] = {
    "EWS": {
        "handling": "Keep the product present at 0.0 seconds on a stable named surface or honestly held against the body.",
        "scale": "Use honest wide-distance scale; do not demand artificial label readability.",
        "transition": "No pickup, relocation or teleport to a close-up version without a validated timed transition.",
    },
    "WS": {
        "handling": "Keep the product present at 0.0 seconds on a stable named surface or honestly held against the body.",
        "scale": "Use honest wide-distance scale; do not demand artificial label readability.",
        "transition": "No pickup, relocation or teleport to a close-up version without a validated timed transition.",
    },
    "MS": {
        "handling": "Keep the product at waist-to-chest level or on the declared visible support surface; declare the holding hand, grip and label orientation.",
        "scale": "Keep the product at honest relative scale against the torso, fingers or support surface.",
        "transition": "The free hand must not cross or duplicate the product unexpectedly.",
    },
    "MCU": {
        "handling": "Keep the product at chest level, below and beside the speaking mouth, with the declared contact relationship preserved.",
        "scale": "Preserve honest product-to-hand and product-to-body scale through micro-gestures only.",
        "transition": "Hybrid keeps presenter and product co-present; no re-grip or hand transfer without a tracked transition.",
    },
    "CU": {
        "handling": "Move the camera closer to the already-existing product without creating a second object or changing custody.",
        "scale": "Preserve true physical scale relative to fingers or the support surface.",
        "transition": "Use a locked camera or one slow deliberate move; no re-grip, hand transfer, spin, flash insert or replacement object.",
    },
    "ECU": {
        "handling": "Focus one stable product detail while retaining a visible physical support relationship.",
        "scale": "Do not use detail framing to imply a new product, new label or impossible scale.",
        "transition": "Allow only one small controlled motion; keep the product anchored throughout.",
    },
    "POV": {
        "handling": "The same hands and product are already visible at 0.0 seconds; declare the entry edge, left/right hand roles and contact points.",
        "scale": "Keep the product at believable first-person hand scale and preserve screen direction.",
        "transition": "No third-person hand swap, extra hand or unexplained object entry.",
    },
    "OTS": {
        "handling": "Use the shoulder only as a foreground reference; keep the product on the named working plane or in the same declared hand.",
        "scale": "Preserve the declared focus plane, orientation and honest product scale.",
        "transition": "Keep screen direction, focus plane and product orientation continuous across the cut.",
    },
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _token(value: Any) -> str:
    return _clean(value).upper().replace("-", "_").replace(" ", "_")


def _stable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _stable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def truth_lock_fingerprint(product: Mapping[str, Any]) -> str:
    """Return a product identity digest without volatile paths or timestamps."""

    payload = {
        "product_id": product.get("id") or product.get("product_id"),
        "display_name": product.get("product_display_name") or product.get("name") or product.get("raw_product_title"),
        "brand": product.get("brand"),
        "product_type": product.get("product_type"),
        "canonical_media_id": product.get("canonical_media_id") or product.get("canonical_source_media_id"),
        "canonical_source_sha256": product.get("canonical_source_sha256") or product.get("source_sha256"),
        "canonical_cutout_media_id": product.get("canonical_cutout_media_id") or product.get("cutout_media_id"),
        "canonical_cutout_sha256": product.get("canonical_cutout_sha256") or product.get("cutout_sha256"),
        "truth_lock_schema_version": product.get("truth_lock_schema_version") or product.get("product_truth_lock_schema_version"),
    }
    encoded = json.dumps(_stable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def resolve_shot_handling(shot_type: str | Mapping[str, Any] | None) -> dict[str, Any]:
    """Resolve one governed shot-size rule or fail closed."""

    if isinstance(shot_type, Mapping):
        raw = shot_type.get("shot_type") or shot_type.get("type") or shot_type.get("framing")
    else:
        raw = shot_type
    normalized = _token(raw)
    if normalized not in _SHOT_HANDLING_MATRIX:
        raise VideoContinuityContractError(
            f"{ERR_SHOT_HANDLING_UNMAPPED}:{_clean(raw) or '<empty>'}",
            "No governed product handling rule exists for this shot type.",
        )
    return {
        "shot_type": normalized,
        "product_at_start_s": 0.0,
        "visibility_start_s": 0.0,
        "product_count": 1,
        **_SHOT_HANDLING_MATRIX[normalized],
    }


def _requires_holder(state: str) -> bool:
    return state in {"HELD_LEFT", "HELD_RIGHT", "WORN_OR_APPLIED"}


def _requires_surface(state: str) -> bool:
    return state == "SUPPORTED_SURFACE"


def validate_product_temporal_custody(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one block/shot custody receipt and return a normalised copy."""

    data = dict(receipt)
    shot = resolve_shot_handling(data.get("shot_type"))
    product_required = bool(data.get("product_required", True))
    try:
        count = int(data.get("product_count", 1))
        visibility_start_s = float(data.get("visibility_start_s", 0.0))
    except (TypeError, ValueError) as exc:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "Product count and visibility start must be numeric.",
        ) from exc
    if product_required and count != 1:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "A product-required shot must contain exactly one product.",
            details={"product_count": count},
        )
    if visibility_start_s != 0.0:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "Product visibility must begin at exactly 0.0 seconds.",
            details={"visibility_start_s": data.get("visibility_start_s")},
        )
    states = []
    for key in ("custody_in", "custody_during", "custody_out"):
        state = _token(data.get(key))
        if state not in CUSTODY_STATES:
            raise VideoContinuityContractError(
                ERR_PRODUCT_CUSTODY_INVALID,
                f"Unknown custody state for {key}.",
                details={"field": key, "state": data.get(key)},
            )
        states.append(state)
    transition = data.get("next_shot_transition") or data.get("transition")
    if (
        states[0] != states[1]
        or states[1] != states[2]
    ) and (
        not transition
        or _token(transition) == "SAME_CUSTODY_CONTINUOUS_CUT"
    ):
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_TRANSITION_INVALID,
            "Custody changes require a separately declared transition.",
            details={"custody_in": states[0], "custody_during": states[1], "custody_out": states[2]},
        )
    holder = _clean(data.get("holder"))
    surface = _clean(data.get("support_surface") or data.get("named_support_surface"))
    if any(_requires_holder(state) for state in states) and not holder:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "Held custody requires a declared holder and hand role.",
        )
    if any(_requires_surface(state) for state in states) and not surface:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "Supported-surface custody requires a named support surface.",
        )
    if any(_requires_holder(state) for state in states) and surface and any(
        _requires_surface(state) for state in states
    ) and not transition:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_TRANSITION_INVALID,
            "A shot cannot be simultaneously held and supported without a timed transition.",
        )
    fingerprint = _clean(data.get("truth_lock_fingerprint"))
    if len(fingerprint) < 16:
        raise VideoContinuityContractError(
            ERR_PRODUCT_CUSTODY_INVALID,
            "A truth-lock fingerprint is required for every custody receipt.",
        )
    if not _clean(data.get("screen_position")):
        raise VideoContinuityContractError(ERR_PRODUCT_CUSTODY_INVALID, "Screen position is required.")
    if not _clean(data.get("relative_scale")):
        raise VideoContinuityContractError(ERR_PRODUCT_CUSTODY_INVALID, "Honest relative scale is required.")
    if not _clean(data.get("label_orientation")):
        raise VideoContinuityContractError(ERR_PRODUCT_CUSTODY_INVALID, "Label orientation is required.")
    if not _clean(data.get("grip_contact_points")):
        raise VideoContinuityContractError(ERR_PRODUCT_CUSTODY_INVALID, "Grip or contact points are required.")
    if not _clean(data.get("approved_movement")):
        raise VideoContinuityContractError(ERR_PRODUCT_CUSTODY_INVALID, "Approved movement is required.")
    data.update(
        {
            "contract_version": VIDEO_CONTINUITY_CONTRACT_VERSION,
            "shot_type": shot["shot_type"],
            "product_required": product_required,
            "product_count": count,
            "visibility_start_s": 0.0,
            "custody_in": states[0],
            "custody_during": states[1],
            "custody_out": states[2],
            "holder": holder or None,
            "support_surface": surface or None,
            "next_shot_transition": transition or "SAME_CUSTODY_CONTINUOUS_CUT",
        }
    )
    return data


def build_product_temporal_custody(
    product: Mapping[str, Any],
    *,
    shot_type: str | Mapping[str, Any] = "MCU",
    custody_in: str = "SUPPORTED_SURFACE",
    custody_during: str | None = None,
    custody_out: str | None = None,
    holder: str | None = None,
    support_surface: str | None = None,
    screen_position: str = "product remains visible in the declared composition",
    relative_scale: str = "honest relative scale to the declared hand, body or support surface",
    label_orientation: str = "label orientation remains unchanged and faces the camera when physically visible",
    grip_contact_points: str = "no hand contact; full support contact is visible",
    approved_movement: str = "only the declared small continuous motion; no transfer, disappearance or replacement",
    next_shot_transition: str | Mapping[str, Any] | None = None,
    product_required: bool = True,
    product_count: int = 1,
    product_presence_type: str | None = None,
) -> dict[str, Any]:
    """Build and validate the shared physical product relationship."""

    resolved_shot = resolve_shot_handling(shot_type)
    presence = _token(product_presence_type)
    if presence == PRODUCT_PRESENCE_MASCOT:
        custody_in = custody_in or "PRODUCT_MASCOT_SELF"
        custody_during = custody_during or custody_in
        custody_out = custody_out or custody_during
        holder = holder or "the product mascot body and limbs"
        support_surface = support_surface or None
        grip_contact_points = grip_contact_points or "mascot limbs remain attached to the mascot body"
    else:
        custody_during = custody_during or custody_in
        custody_out = custody_out or custody_during
        states = (custody_in, custody_during, custody_out)
        if "SUPPORTED_SURFACE" in states:
            support_surface = support_surface or "the named stable support surface"
        if "HELD_LEFT" in states:
            holder = holder or "left hand"
        if "HELD_RIGHT" in states:
            holder = holder or "right hand"
    receipt = {
        "contract_version": VIDEO_CONTINUITY_CONTRACT_VERSION,
        "product_required": product_required,
        "product_count": product_count,
        "visibility_start_s": 0.0,
        "custody_in": custody_in,
        "custody_during": custody_during,
        "custody_out": custody_out,
        "holder": holder,
        "support_surface": support_surface,
        "screen_position": screen_position,
        "relative_scale": relative_scale,
        "label_orientation": label_orientation,
        "grip_contact_points": grip_contact_points,
        "approved_movement": approved_movement,
        "next_shot_transition": next_shot_transition or "SAME_CUSTODY_CONTINUOUS_CUT",
        "truth_lock_fingerprint": truth_lock_fingerprint(product),
        "product_presence_type": presence or "PRODUCT_OBJECT",
        "shot_type": resolved_shot["shot_type"],
    }
    return validate_product_temporal_custody(receipt)


def default_product_temporal_custody(
    product: Mapping[str, Any],
    *,
    source_mode: str,
    character_presence: str,
    product_presence_type: str | None = None,
    shot_type: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive an explicit safe default for active lanes."""

    presence = _token(product_presence_type)
    shot = shot_type or product.get("shot_type") or "MCU"
    surface = (
        product.get("support_surface")
        or product.get("named_support_surface")
        or "the named stable support surface"
    )
    if presence == PRODUCT_PRESENCE_MASCOT:
        return build_product_temporal_custody(
            product,
            shot_type=shot,
            custody_in="PRODUCT_MASCOT_SELF",
            product_presence_type=PRODUCT_PRESENCE_MASCOT,
            screen_position="mascot remains fully visible in the declared composition",
            relative_scale="one stable mascot-to-product scale throughout the shot",
            label_orientation="the product label and mascot identity remain unchanged",
            grip_contact_points="mascot limbs and shoes remain attached to the same mascot identity",
            approved_movement="the declared mascot action only; no product identity change or duplicate product",
        )
    if _token(character_presence) == "FACELESS":
        return build_product_temporal_custody(
            product,
            shot_type=shot,
            custody_in="SUPPORTED_SURFACE",
            support_surface=surface,
            screen_position="product remains anchored in the declared working plane while consistent hands and forearms may enter",
            relative_scale="honest scale against the support surface and any visible fingers",
            label_orientation="label faces the camera only when physically visible; no artificial wide-shot readability",
            grip_contact_points="hands do not fuse with, duplicate or unexpectedly transfer the product",
            approved_movement="micro camera or hand movement only; no pickup, re-grip or product-only insert",
        )
    return build_product_temporal_custody(
        product,
        shot_type=shot,
        custody_in="HELD_LEFT",
        holder="left hand",
        screen_position="product remains co-present below and beside the speaking mouth or in the declared composition",
        relative_scale="honest scale against the hand, fingers and body",
        label_orientation="label faces the camera when physically visible without twisting the object",
        grip_contact_points="left-hand contact points stay consistent; right hand remains free unless a transition is declared",
        approved_movement="micro-gestures only; no hand transfer, disappearance, flash or replacement object",
    )


def custody_prompt_lines(custody: Mapping[str, Any], *, product_name: str) -> list[str]:
    """Translate the receipt into provider-facing physical instructions."""

    receipt = validate_product_temporal_custody(custody)
    state_text = {
        "HELD_LEFT": "held by the left hand",
        "HELD_RIGHT": "held by the right hand",
        "SUPPORTED_SURFACE": f"resting on {receipt.get('support_surface')}",
        "WORN_OR_APPLIED": "kept in the declared worn or applied contact relationship",
        "PRODUCT_MASCOT_SELF": "kept as the same active product-mascot identity",
    }[receipt["custody_during"]]
    return [
        f"At exactly 0.0 seconds, exactly one {product_name} is already visible and {state_text}; it never enters later.",
        f"Keep {product_name} in {receipt['screen_position']} at {receipt['relative_scale']}; preserve {receipt['label_orientation']}.",
        f"Contact relationship: {receipt['grip_contact_points']}. Approved movement: {receipt['approved_movement']}.",
        f"The next shot inherits the same product identity and custody state: {receipt['next_shot_transition']}.",
        "Never allow disappearance, re-entry, duplication, replacement packaging, label or cap mutation, scale drift, hand-product fusion, extra hands, isolated flash, surprise packshot, spontaneous spotlight or product-only insert montage.",
    ]


def resolve_block_custody(
    custody: Mapping[str, Any],
    block_index: int,
) -> dict[str, Any]:
    """Resolve an optional per-block custody map without weakening validation."""

    by_block = custody.get("custody_by_block") if isinstance(custody, Mapping) else None
    if isinstance(by_block, Sequence) and not isinstance(by_block, (str, bytes)):
        item = by_block[block_index - 1] if block_index - 1 < len(by_block) else None
        if isinstance(item, Mapping):
            return validate_product_temporal_custody(item)
    return validate_product_temporal_custody(custody)


def validate_custody_sequence(receipts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validate custody continuity across adjacent shots or blocks."""

    normalised = [validate_product_temporal_custody(receipt) for receipt in receipts]
    for previous, current in zip(normalised, normalised[1:]):
        if previous["custody_out"] == current["custody_in"]:
            continue
        transition = current.get("next_shot_transition")
        if not transition or str(transition).upper() == "SAME_CUSTODY_CONTINUOUS_CUT":
            raise VideoContinuityContractError(
                ERR_PRODUCT_CUSTODY_TRANSITION_INVALID,
                "Adjacent shots change custody without a separately declared timed transition.",
                details={
                    "previous_custody_out": previous["custody_out"],
                    "current_custody_in": current["custody_in"],
                },
            )
    return normalised


def _word_count(text: Any) -> int:
    return len(_clean(text).split()) if _clean(text) else 0


def _rows_for_block(block: Mapping[str, Any]) -> list[dict[str, Any]]:
    allocation = block.get("allocation") if isinstance(block.get("allocation"), Mapping) else block
    raw = allocation.get("assigned_dialogue_utterances") or allocation.get("dialogue_utterances") or block.get("dialogue_utterances") or []
    rows = [dict(row) for row in raw if isinstance(row, Mapping)]
    rows.sort(key=lambda row: (float(row.get("start_s") or 0.0), str(row.get("utterance_id") or "")))
    return rows


def _occupancy_error(code: str, details: Mapping[str, Any]) -> None:
    raise VideoContinuityContractError(code, "Immutable dialogue cannot satisfy the temporal occupancy contract.", details=details)


def _sweet_target_for_duration(canonical: Any, duration_seconds: int, target_language: str) -> int:
    """Resolve the target from the canonical provider block plan.

    The 16s and 24s targets are intentionally block sums (22+22 and
    22+22+22 for Malay SweetWPS), not a rounded WPS calculation over the
    aggregate duration.  This keeps the receipt aligned with the same 8s/10s
    block authority used by the planner.
    """

    try:
        block_plan = canonical.resolve_block_plan(
            "GOOGLE_FLOW",
            int(duration_seconds),
            preferred_lane="8s",
        )
    except (AttributeError, ValueError):
        block_plan = [int(duration_seconds)]
    if len(block_plan) > 1 and sum(block_plan) == int(duration_seconds):
        return sum(
            int(
                canonical.strict_dialogue_word_budget(
                    int(seconds), target_language, wps_mode="SWEET"
                )
            )
            for seconds in block_plan
        )
    return int(
        canonical.strict_dialogue_word_budget(
            int(duration_seconds), target_language, wps_mode="SWEET"
        )
    )


def build_temporal_occupancy_receipt(
    *,
    blocks: Sequence[Mapping[str, Any]],
    target_language: str,
    wps_mode: str,
    dialogue_enabled: bool = True,
    strict: bool = True,
    required_terminal_hold_seconds: float = 0.25,
) -> dict[str, Any]:
    """Validate SweetWPS word targets and emit measured temporal occupancy."""

    mode = _token(wps_mode)
    if dialogue_enabled and mode != "SWEET":
        raise VideoContinuityContractError(ERR_DIALOGUE_WPS_MODE_REQUIRED, "Active dialogue-bearing video requires explicit SWEET mode.")
    from agent.services import canonical_prompt_compiler as canonical

    rows_out: list[dict[str, Any]] = []
    cursor = 0.0
    for position, raw in enumerate(blocks, start=1):
        block = dict(raw)
        duration = float(block.get("duration_seconds") or 0.0)
        if duration <= 0:
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Block duration must be positive.")
        start = float(block.get("start_s") if block.get("start_s") is not None else cursor)
        end = float(block.get("end_s") if block.get("end_s") is not None else start + duration)
        if not math.isclose(end - start, duration, abs_tol=1e-6):
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Block timeline duration mismatch.", details={"block_index": position})
        expected_block_start = 0.0 if position == 1 else cursor
        if not math.isclose(start, expected_block_start, abs_tol=1e-6):
            raise VideoContinuityContractError(
                ERR_DIALOGUE_TIMELINE_INVALID,
                "Blocks must cover one contiguous timeline with no gap or overlap.",
                details={
                    "block_index": position,
                    "expected_start_s": expected_block_start,
                    "actual_start_s": start,
                },
            )
        target = _sweet_target_for_duration(canonical, int(duration), target_language) if dialogue_enabled else 0
        allocation = block.get("allocation") if isinstance(block.get("allocation"), Mapping) else block
        dialogue = _clean(block.get("dialogue") or block.get("exact_dialogue_slice") or allocation.get("exact_dialogue_slice"))
        measured_actual = _word_count(dialogue)
        declared_actual = block.get("actual_dialogue_word_count")
        if declared_actual is not None and int(declared_actual) != measured_actual:
            raise VideoContinuityContractError(
                ERR_DIALOGUE_TIMELINE_INVALID,
                "Declared dialogue occupancy does not match the immutable dialogue text.",
                details={
                    "block_index": position,
                    "declared_word_count": int(declared_actual),
                    "measured_word_count": measured_actual,
                },
            )
        actual = measured_actual
        utterances = _rows_for_block(block)
        if not dialogue_enabled:
            actual = 0
            utterances = []
        previous_end = start
        for utterance in utterances:
            utterance_start = float(utterance.get("start_s") if utterance.get("start_s") is not None else -1.0)
            utterance_end = float(utterance.get("end_s") if utterance.get("end_s") is not None else -1.0)
            if (
                utterance_start < start - 1e-6
                or utterance_end <= utterance_start
                or utterance_end > end + 1e-6
                or utterance_start < previous_end - 1e-6
            ):
                raise VideoContinuityContractError(
                    ERR_DIALOGUE_TIMELINE_INVALID,
                    "Dialogue utterances overlap or leave the declared block bounds.",
                    details={
                        "block_index": position,
                        "utterance_id": utterance.get("utterance_id"),
                        "start_s": utterance_start,
                        "end_s": utterance_end,
                    },
                )
            previous_end = utterance_end
        sweet_wps = (
            float(canonical.strict_wps_profile(target_language)["sweet_wps"])
            if dialogue_enabled
            else 0.0
        )
        estimated_speech_duration = actual / sweet_wps if dialogue_enabled else 0.0
        if strict and dialogue_enabled and actual < target:
            _occupancy_error(ERR_DIALOGUE_SWEETWPS_UNDERRUN, {"block_index": position, "required_target": target, "actual_count": actual, "estimated_speech_duration_seconds": estimated_speech_duration, "requires_reauthoring": True})
        if strict and dialogue_enabled and actual > target:
            _occupancy_error(ERR_DIALOGUE_SWEETWPS_OVERRUN, {"block_index": position, "required_target": target, "actual_count": actual, "estimated_speech_duration_seconds": estimated_speech_duration, "requires_reauthoring": True})
        first_start = float(utterances[0].get("start_s") or 0.0) if utterances else None
        final_end = float(utterances[-1].get("end_s") or 0.0) if utterances else None
        expected_first_start = start if position == 1 else start + 0.5
        if strict and dialogue_enabled and (first_start is None or abs(first_start - expected_first_start) > 0.02):
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "The first utterance is not at the declared block entry window.", details={"block_index": position, "first_utterance_start_s": first_start, "required_start_s": expected_first_start})
        internal_gaps: list[float] = []
        for previous, current in zip(utterances, utterances[1:]):
            gap = float(current.get("start_s") or 0.0) - float(previous.get("end_s") or 0.0)
            internal_gaps.append(max(0.0, gap))
        max_gap = max(internal_gaps or [0.0])
        if strict and max_gap > 0.25 + 1e-6:
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "An internal speech gap is not explicitly occupied.", details={"block_index": position, "max_internal_gap_seconds": max_gap})
        terminal_hold_start = final_end if final_end is not None else start
        terminal_hold_seconds = max(0.0, end - terminal_hold_start)
        if strict and dialogue_enabled and final_end is not None:
            boundary_gap = end - final_end
            if boundary_gap < 0.20 - 1e-6 or boundary_gap > 0.50 + 1e-6:
                raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Final speech does not end inside the required terminal hold window.", details={"block_index": position, "speech_end_s": final_end, "block_end_s": end, "terminal_hold_seconds": boundary_gap})
        if strict and dialogue_enabled and terminal_hold_seconds < max(0.20, float(required_terminal_hold_seconds)) - 1e-6:
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Terminal visual hold is too short.", details={"block_index": position, "terminal_hold_seconds": terminal_hold_seconds})
        assignment: list[dict[str, Any]] = []
        if start < terminal_hold_start:
            assignment.append({"start_s": start, "end_s": terminal_hold_start, "role": "DIALOGUE_OR_EXPLICIT_SPEECH_WINDOW"})
        if terminal_hold_seconds > 0:
            assignment.append({"start_s": terminal_hold_start, "end_s": end, "role": "TERMINAL_PRODUCT_CUSTODY_HOLD", "product_position_unchanged": True, "grip_or_support_fixed": True, "label_orientation_preserved": True, "final_gesture_completed": True, "camera_locked_or_ambience_continuous": True})
        rows_out.append({
            "block_index": position,
            "start_s": start,
            "end_s": end,
            "duration_seconds": duration,
            "wps_mode": "SWEET" if dialogue_enabled else "NONE",
            "required_target_word_count": target,
            "actual_word_count": actual,
            "first_utterance_start_s": first_start,
            "required_first_utterance_start_s": expected_first_start if dialogue_enabled else None,
            "estimated_speech_end_s": final_end,
            "estimated_speech_duration_seconds": (
                max(0.0, final_end - first_start)
                if final_end is not None and first_start is not None
                else estimated_speech_duration
            ),
            "requires_reauthoring": False,
            "terminal_hold_seconds": terminal_hold_seconds,
            "max_internal_gap_seconds": max_gap,
            "utterances": utterances,
            "timeline_assignment": assignment,
            "terminal_hold": assignment[-1] if assignment and assignment[-1]["role"] == "TERMINAL_PRODUCT_CUSTODY_HOLD" else {"start_s": end, "end_s": end, "role": "NO_DIALOGUE_VISUAL_COVERAGE"},
            "status": "PASS",
        })
        cursor = end
    if rows_out and abs(float(rows_out[-1]["end_s"]) - cursor) > 1e-6:
        raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Timeline does not cover the requested duration.")
    return {
        "contract_version": VIDEO_CONTINUITY_CONTRACT_VERSION,
        "wps_mode": "SWEET" if dialogue_enabled else "NONE",
        "dialogue_enabled": bool(dialogue_enabled),
        "target_language": target_language,
        "blocks": rows_out,
        "status": "PASS",
        "timeline_coverage": {"start_s": rows_out[0]["start_s"] if rows_out else 0.0, "end_s": rows_out[-1]["end_s"] if rows_out else 0.0, "complete": True},
    }


def validate_temporal_occupancy(receipt: Mapping[str, Any]) -> None:
    if str(receipt.get("status") or "").upper() != "PASS":
        raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, "Temporal occupancy receipt is not PASS.")
    for block in receipt.get("blocks") or []:
        if block.get("status") != "PASS":
            raise VideoContinuityContractError(ERR_DIALOGUE_TIMELINE_INVALID, f"Block {block.get('block_index')} is not occupied.")


__all__ = [
    "CUSTODY_STATES",
    "ERR_DIALOGUE_SWEETWPS_OVERRUN",
    "ERR_DIALOGUE_SWEETWPS_UNDERRUN",
    "ERR_DIALOGUE_TIMELINE_INVALID",
    "ERR_DIALOGUE_WPS_MODE_REQUIRED",
    "ERR_PRODUCT_CUSTODY_INVALID",
    "ERR_PRODUCT_CUSTODY_TRANSITION_INVALID",
    "ERR_SHOT_HANDLING_UNMAPPED",
    "PRODUCT_PRESENCE_MASCOT",
    "SHOT_TYPES",
    "VIDEO_CONTINUITY_CONTRACT_VERSION",
    "VideoContinuityContractError",
    "build_product_temporal_custody",
    "build_temporal_occupancy_receipt",
    "custody_prompt_lines",
    "default_product_temporal_custody",
    "resolve_block_custody",
    "resolve_shot_handling",
    "validate_custody_sequence",
    "truth_lock_fingerprint",
    "validate_product_temporal_custody",
    "validate_temporal_occupancy",
]
