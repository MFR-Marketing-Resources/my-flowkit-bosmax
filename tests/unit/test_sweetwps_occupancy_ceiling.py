"""Round 2.3 — SweetWPS temporal-occupancy is a CEILING, not an exact target.

Proves the corrected shared semantics in video_continuity_contract:
  - actual <= sweet_max  -> word-budget feasible (no underrun)
  - actual >  sweet_max  -> OVERRUN (kept)
  - dialogue required + 0 -> DIALOGUE_REQUIRED_MISSING
  - short dialogue is filled by explicit visual occupancy + terminal hold, never a
    dead dialogue gap
  - lip-sync / dialogue contracts for HYBRID / FACELESS / MONTAGE remain intact
    (only the LENGTH interpretation changed).
PROVIDER-FREE.
"""
import pytest

from agent.services.video_continuity_contract import (
    ERR_DIALOGUE_REQUIRED_MISSING,
    ERR_DIALOGUE_SWEETWPS_OVERRUN,
    ERR_DIALOGUE_TIMELINE_INVALID,
    VideoContinuityContractError,
    build_temporal_occupancy_receipt,
)


def _words(n: int) -> str:
    return " ".join(f"kata{i}" for i in range(n))


def _block(duration: int, words: int, *, start: float = 0.0, index: int = 1) -> dict:
    return {
        "block_index": index,
        "start_s": start,
        "end_s": start + duration,
        "duration_seconds": duration,
        "dialogue": _words(words),
        "actual_dialogue_word_count": words,
    }


def _receipt(*blocks, dialogue_enabled: bool = True):
    return build_temporal_occupancy_receipt(
        blocks=list(blocks), target_language="BM_MS", wps_mode="SWEET",
        dialogue_enabled=dialogue_enabled,
    )


# A — 8s SWEET, exactly the ceiling (22) → PASS
def test_A_ceiling_words_pass():
    b = _receipt(_block(8, 22))["blocks"][0]
    assert b["status"] == "PASS"
    assert b["max_dialogue_word_count"] == 22 and b["actual_dialogue_word_count"] == 22


# B — 8s SWEET, fewer than ceiling → NOT underrun
def test_B_short_dialogue_is_not_underrun():
    b = _receipt(_block(8, 9))["blocks"][0]
    assert b["status"] == "PASS"
    assert b["actual_dialogue_word_count"] == 9
    assert b["speech_window_seconds"] == pytest.approx(9 / 2.7, abs=0.02)


# C — 8s SWEET, above ceiling → OVERRUN
def test_C_over_ceiling_overruns():
    with pytest.raises(VideoContinuityContractError) as e:
        _receipt(_block(8, 23))
    assert e.value.code == ERR_DIALOGUE_SWEETWPS_OVERRUN


# D — dialogue required but 0 words → MISSING
def test_D_missing_dialogue_fails():
    with pytest.raises(VideoContinuityContractError) as e:
        _receipt({"block_index": 1, "start_s": 0.0, "end_s": 8.0, "duration_seconds": 8,
                  "dialogue": "", "actual_dialogue_word_count": 0})
    assert e.value.code == ERR_DIALOGUE_REQUIRED_MISSING


# E — short valid dialogue + explicit visual occupancy fills remaining time → PASS
def test_E_short_dialogue_fills_with_visual_occupancy():
    b = _receipt(_block(8, 9))["blocks"][0]
    assert b["visual_occupancy_seconds"] > 0.0
    roles = [seg["role"] for seg in b["timeline_assignment"]]
    assert "SPEECH_WINDOW" in roles
    assert "EXPLICIT_VISUAL_ACTION_OCCUPANCY" in roles
    assert roles[-1] == "TERMINAL_PRODUCT_CUSTODY_HOLD"


# F — unoccupied/non-contiguous timeline → TIMELINE failure, NOT a WPS underrun
def test_F_unoccupied_timeline_fails_timeline_not_wps():
    with pytest.raises(VideoContinuityContractError) as e:
        _receipt(_block(8, 9), _block(8, 9, start=9.0, index=2))  # 1s gap
    assert e.value.code == ERR_DIALOGUE_TIMELINE_INVALID


# G — too many words for the time (short block) → OVERRUN (rate ceiling via word ceiling)
def test_G_too_fast_rate_overruns():
    # 4s ceiling = round(4*2.7)=11; 15 words exceeds it.
    with pytest.raises(VideoContinuityContractError) as e:
        _receipt(_block(4, 15))
    assert e.value.code == ERR_DIALOGUE_SWEETWPS_OVERRUN


# H — explicit visual/demo occupancy is not treated as a dialogue gap
def test_H_visual_occupancy_is_not_a_gap():
    b = _receipt(_block(8, 6))["blocks"][0]
    assert b["status"] == "PASS"
    assert any(seg["role"] == "EXPLICIT_VISUAL_ACTION_OCCUPANCY" for seg in b["timeline_assignment"])


# I — terminal hold remains enforced
def test_I_terminal_hold_enforced():
    b = _receipt(_block(8, 12))["blocks"][0]
    assert b["terminal_hold_seconds"] == pytest.approx(0.25)
    assert b["timeline_assignment"][-1]["role"] == "TERMINAL_PRODUCT_CUSTODY_HOLD"


# J — 16s EXTEND [8,8] accepts short-but-valid per-block dialogue, each block occupied
def test_J_16s_extend_short_dialogue_passes():
    receipt = _receipt(_block(8, 9, index=1), _block(8, 10, start=8.0, index=2))
    assert receipt["status"] == "PASS"
    assert len(receipt["blocks"]) == 2
    for b in receipt["blocks"]:
        assert b["status"] == "PASS"
        assert b["actual_dialogue_word_count"] <= b["max_dialogue_word_count"]
        assert b["terminal_hold_seconds"] == pytest.approx(0.25)
    # continuation block reserves a seam-in visual beat
    assert receipt["blocks"][1]["seam_in_seconds"] == pytest.approx(0.5)


# K/L — HYBRID presenter + FACELESS dialogue contracts remain present (compiler unaffected)
def _compiled(character_presence: str) -> str:
    from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
    result = compile_ugc_video_prompt(
        product={"id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
                 "product_display_name": "Minyak Warisan Cap Burung 25ml",
                 "raw_product_title": "Minyak Warisan Cap Burung 25ml"},
        approved_package={"mode": "F2V", "claim_safe_rewrite": "Everyday comfort routine, no guaranteed outcomes."},
        avatar_id="BOS_F_AINA_01" if character_presence != "FACELESS" else None,
        mode="F2V", generation_mode="SINGLE", duration_seconds=8, camera_style="UGC_IPHONE_RAW",
        character_presence=character_presence, creator_persona="DEFAULT_CREATOR", target_language="BM_MS",
        safe_hook_angles=["Mulakan dengan rutin harian yang natural dan claim-safe."],
        safe_cta_angles=["Akhiri dengan CTA lembut."],
    )
    return str(result["final_compiled_prompt_text"])


def test_K_hybrid_presenter_lipsync_contract_intact():
    up = _compiled("VISIBLE_CREATOR").upper()
    assert "SECTION 6 - SPOKEN DIALOGUE" in up and "SECTION 7 - VOICE & DELIVERY" in up
    assert "PRESENTER" in up
    low = up.lower()
    assert "lip" in low or ("mouth" in low and "sync" in low) or "synchroni" in low


def test_L_faceless_dialogue_contract_intact():
    up = _compiled("FACELESS").upper()
    assert "SECTION 6 - SPOKEN DIALOGUE" in up and "SECTION 7 - VOICE & DELIVERY" in up
    low = up.lower()
    assert "voice" in low or "voiceover" in low or "narration" in low
    assert "no visible" in low or "no on-camera" in low or "no face" in low or "no head" in low


# M — MONTAGE mascot lip-sync contract remains present (occupancy change does not weaken it)
def test_M_montage_mascot_lipsync_contract_intact():
    import inspect

    from agent.services import montage_mascot_creative_grammar as grammar

    source = inspect.getsource(grammar).lower()
    # The mascot is the on-screen speaker with synchronized mouth animation and no
    # off-screen narrator substitution — the contract this repair must preserve.
    assert "mascot" in source
    assert "mouth" in source and ("speak" in source or "lip" in source or "sync" in source)
    assert "off-screen narrator" in source or "off screen narrator" in source
