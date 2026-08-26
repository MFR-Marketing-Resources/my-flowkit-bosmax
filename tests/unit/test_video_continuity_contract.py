from __future__ import annotations

import pytest

from agent.services.video_continuity_contract import (
    ERR_DIALOGUE_REQUIRED_MISSING,
    ERR_DIALOGUE_SWEETWPS_OVERRUN,
    ERR_DIALOGUE_SWEETWPS_UNDERRUN,
    ERR_DIALOGUE_TIMELINE_INVALID,
    ERR_PRODUCT_CUSTODY_TRANSITION_INVALID,
    ERR_SHOT_HANDLING_UNMAPPED,
    VideoContinuityContractError,
    build_product_temporal_custody,
    build_temporal_occupancy_receipt,
    truth_lock_fingerprint,
    validate_custody_sequence,
    validate_product_temporal_custody,
    resolve_shot_handling,
)


PRODUCT = {
    "id": "product-1",
    "name": "MWCB 25 ML",
    "canonical_media_id": "media-1",
    "canonical_source_sha256": "a" * 64,
    "canonical_cutout_media_id": "cutout-1",
    "canonical_cutout_sha256": "b" * 64,
    "truth_lock_schema_version": "PRODUCT_TRUTH_LOCK_V1",
}


@pytest.mark.parametrize("shot_type", ["EWS", "WS", "MS", "MCU", "CU", "ECU", "POV", "OTS"])
def test_every_governed_shot_type_has_explicit_product_handling(shot_type: str):
    handling = resolve_shot_handling(shot_type)
    assert handling["shot_type"] == shot_type
    assert handling["product_at_start_s"] == 0.0
    assert handling["product_count"] == 1
    assert handling["handling"]
    assert handling["scale"]
    assert handling["transition"]


def test_unknown_shot_fails_closed_with_stable_code():
    with pytest.raises(VideoContinuityContractError) as exc:
        resolve_shot_handling("DUTCH_ANGLE")
    assert exc.value.code == f"{ERR_SHOT_HANDLING_UNMAPPED}:DUTCH_ANGLE"


def test_product_custody_requires_one_truthful_identity_from_zero():
    receipt = build_product_temporal_custody(
        PRODUCT,
        shot_type="MCU",
        custody_in="SUPPORTED_SURFACE",
        support_surface="named teak table",
        screen_position="below and beside the speaking mouth",
        relative_scale="honest scale against the table and fingers",
        label_orientation="front label remains camera-facing",
        grip_contact_points="full base contact with the table",
        approved_movement="slow camera move only",
    )
    assert receipt["product_required"] is True
    assert receipt["product_count"] == 1
    assert receipt["visibility_start_s"] == 0.0
    assert receipt["custody_in"] == receipt["custody_during"] == receipt["custody_out"] == "SUPPORTED_SURFACE"
    assert receipt["truth_lock_fingerprint"] == truth_lock_fingerprint(PRODUCT)


def test_contradictory_hand_and_surface_custody_requires_transition():
    with pytest.raises(VideoContinuityContractError) as exc:
        validate_product_temporal_custody(
            {
                **build_product_temporal_custody(PRODUCT, custody_in="HELD_LEFT"),
                "custody_during": "SUPPORTED_SURFACE",
                "custody_out": "SUPPORTED_SURFACE",
                "support_surface": "named table",
                "next_shot_transition": None,
            }
        )
    assert exc.value.code == ERR_PRODUCT_CUSTODY_TRANSITION_INVALID


def test_same_custody_transition_token_cannot_hide_a_real_custody_change():
    with pytest.raises(VideoContinuityContractError) as exc:
        validate_product_temporal_custody(
            {
                **build_product_temporal_custody(PRODUCT, custody_in="HELD_LEFT"),
                "custody_during": "HELD_RIGHT",
                "custody_out": "HELD_RIGHT",
                "holder": "right hand",
                "next_shot_transition": "SAME_CUSTODY_CONTINUOUS_CUT",
            }
        )
    assert exc.value.code == ERR_PRODUCT_CUSTODY_TRANSITION_INVALID


def test_adjacent_custody_change_requires_explicit_transition():
    held = build_product_temporal_custody(PRODUCT, custody_in="HELD_LEFT")
    surface = build_product_temporal_custody(PRODUCT, custody_in="SUPPORTED_SURFACE")
    with pytest.raises(VideoContinuityContractError) as exc:
        validate_custody_sequence([held, surface])
    assert exc.value.code == ERR_PRODUCT_CUSTODY_TRANSITION_INVALID


def _occupancy_block(duration: int, word_count: int, *, start: float = 0.0, continuation: bool = False):
    text = " ".join(f"kata{i}" for i in range(word_count))
    speech_start = start + (0.5 if continuation else 0.0)
    speech_end = start + duration - 0.25
    return {
        "block_index": 2 if continuation else 1,
        "start_s": start,
        "end_s": start + duration,
        "duration_seconds": duration,
        "dialogue": text,
        "actual_dialogue_word_count": word_count,
        "assigned_dialogue_utterances": [
            {"utterance_id": "u1", "start_s": speech_start, "end_s": speech_end, "text": text}
        ],
    }


@pytest.mark.parametrize(("duration", "words"), [(8, 22), (10, 27), (16, 44), (24, 66)])
def test_sweetwps_targets_use_authoritative_block_sums(duration: int, words: int):
    receipt = build_temporal_occupancy_receipt(
        blocks=[_occupancy_block(duration, words)],
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    block = receipt["blocks"][0]
    assert block["required_target_word_count"] == words
    assert block["actual_word_count"] == words
    assert block["terminal_hold_seconds"] == pytest.approx(0.25)
    assert block["timeline_assignment"][-1]["role"] == "TERMINAL_PRODUCT_CUSTODY_HOLD"
    assert block["requires_reauthoring"] is False


def test_sweetwps_is_a_ceiling_not_an_exact_target():
    # Round 2.3: SweetWPS is a hard maximum. A shorter-than-max script is VALID —
    # the remaining block time is explicit visual occupancy, never an underrun.
    receipt = build_temporal_occupancy_receipt(
        blocks=[_occupancy_block(8, 21)],
        target_language="BM_MS",
        wps_mode="SWEET",
    )
    block = receipt["blocks"][0]
    assert block["status"] == "PASS"
    assert block["max_dialogue_word_count"] == 22 and block["actual_dialogue_word_count"] == 21
    # Over the ceiling still fails closed.
    with pytest.raises(VideoContinuityContractError) as over:
        build_temporal_occupancy_receipt(
            blocks=[_occupancy_block(8, 23)],
            target_language="BM_MS",
            wps_mode="SWEET",
        )
    assert over.value.code == ERR_DIALOGUE_SWEETWPS_OVERRUN
    assert over.value.details["requires_reauthoring"] is True


def test_temporal_receipt_rejects_gaps_and_unexplained_internal_silence():
    first = _occupancy_block(8, 22)
    second = _occupancy_block(8, 22, start=9.0, continuation=True)
    with pytest.raises(VideoContinuityContractError) as gap:
        build_temporal_occupancy_receipt(
            blocks=[first, second],
            target_language="BM_MS",
            wps_mode="SWEET",
        )
    assert gap.value.code == ERR_DIALOGUE_TIMELINE_INVALID

    long_gap = _occupancy_block(8, 22)
    text = long_gap["dialogue"]
    long_gap["assigned_dialogue_utterances"] = [
        {"utterance_id": "u1", "start_s": 0.0, "end_s": 2.0, "text": text[:20]},
        {"utterance_id": "u2", "start_s": 2.26, "end_s": 7.75, "text": text[20:]},
    ]
    with pytest.raises(VideoContinuityContractError) as silence:
        build_temporal_occupancy_receipt(
            blocks=[long_gap],
            target_language="BM_MS",
            wps_mode="SWEET",
        )
    assert silence.value.code == ERR_DIALOGUE_TIMELINE_INVALID


def test_no_dialogue_requires_explicit_disabled_mode_but_covers_visual_timeline():
    receipt = build_temporal_occupancy_receipt(
        blocks=[{"block_index": 1, "start_s": 0.0, "end_s": 8.0, "duration_seconds": 8}],
        target_language="BM_MS",
        wps_mode="SAFE",
        dialogue_enabled=False,
    )
    assert receipt["wps_mode"] == "NONE"
    assert receipt["blocks"][0]["timeline_assignment"][0]["role"] == "TERMINAL_PRODUCT_CUSTODY_HOLD"


def test_mascot_is_a_distinct_actor_and_never_human_faceless_prompt_text():
    from agent.services import canonical_prompt_compiler as canonical

    rendered = canonical.render_block(
        source_mode="FRAMES",
        engine="GOOGLE_FLOW",
        block_index=1,
        total_blocks=1,
        block_seconds=8,
        product=PRODUCT,
        character_presence="FACELESS",  # legacy transport value; mascot owns the actor contract
        product_presence_type="PRODUCT_MASCOT",
        wps_mode="SWEET",
    )
    prompt = rendered["engine_prompt_text"]
    assert rendered["actor_contract"] == "PRODUCT_MASCOT"
    assert "PRODUCT MASCOT" in prompt.upper()
    assert "FACELESS" not in prompt.upper()
    assert "visible mouth" in prompt.lower()
