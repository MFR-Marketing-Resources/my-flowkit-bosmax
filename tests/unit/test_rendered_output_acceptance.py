"""Round 3 — shared rendered-output BEHAVIORAL acceptance.

Proves the ONE shared acceptance seam enforces each surface's owner-specified
behavioral property set against the RENDERED clip, and — critically — that an
UNPROVEN property never silently becomes PASS.

PROVIDER-FREE and ffmpeg-independent: the media probes (ffprobe/ffmpeg/PIL) are
monkeypatched so the pure decision logic is tested deterministically in CI.
"""
import pytest

import agent.services.rendered_output_acceptance_service as roa


# --- deterministic media-probe fakes (no ffmpeg needed) ---------------------

def _patch_media(monkeypatch, *, truly_frozen=False, audio_present=True):
    monkeypatch.setattr(roa, "probe_media", lambda _p: {
        "path": str(_p), "exists": True, "probed": True, "duration_s": 8.0,
        "width": 720, "height": 1280, "aspect_ratio": "9:16",
        "has_video": True, "has_audio": bool(audio_present),
        "video_codec": "h264", "audio_codec": "aac" if audio_present else None,
    })
    monkeypatch.setattr(roa, "analyze_motion", lambda _p, **k: {
        "probed": True, "frame_count": 16, "max_diff": 0.4 if truly_frozen else 12.0,
        "mean_diff": 0.2 if truly_frozen else 6.0, "truly_frozen": bool(truly_frozen),
        "frame_paths": [],
    })
    monkeypatch.setattr(roa, "analyze_audio", lambda _p, **k: {
        "probed": True, "audio_present": bool(audio_present),
        "speech_proven": False, "speech_heuristic": None,
    })


def _all_pass_vision(_path, targets):
    return {p: roa.PROP_PASS for p in targets}


def _all_pass_speech(_path):
    return {"dialogue_present": True, "bgm_only": False}


DUMMY = "dummy_clip.mp4"


# --- A/B/C: lane property sets are exactly the owner's lists -----------------

def test_A_hybrid_property_set_is_exact():
    assert roa.surface_properties("HYBRID") == (
        "PRESENTER_VISIBLE", "PRESENTER_PRODUCT_INTERACTION", "SPOKEN_DIALOGUE_PRESENT",
        "LIPSYNC_PRESENT", "PRODUCT_FIDELITY", "NON_STATIC_SCENE", "BGM_ONLY_FALSE",
    )


def test_B_faceless_property_set_is_exact_and_has_no_lipsync():
    props = roa.surface_properties("FACELESS")
    assert props == (
        "HUMAN_PRESENCE", "HAND_PRODUCT_INTERACTION", "NO_FACE_HEAD", "SPOKEN_DIALOGUE_PRESENT",
        "PRODUCT_FIDELITY", "NON_STATIC_SCENE", "BGM_ONLY_FALSE",
    )
    # FACELESS has no face -> no lip-sync property, and never a presenter/mascot property.
    assert "LIPSYNC_PRESENT" not in props
    assert "PRESENTER_VISIBLE" not in props and "MASCOT_VISIBLE" not in props


def test_C_montage_property_set_and_alias():
    expected = (
        "MASCOT_VISIBLE", "MASCOT_IDENTITY_CONTINUITY", "MASCOT_ACTIVE_ACTION",
        "SPOKEN_DIALOGUE_PRESENT", "LIPSYNC_PRESENT", "PRODUCT_FIDELITY", "NON_STATIC_SCENE",
        "BGM_ONLY_FALSE",
    )
    assert roa.surface_properties("MONTAGE") == expected
    # PRODUCT_MASCOT_MONTAGE normalizes to the same MONTAGE contract.
    assert roa.normalize_surface("PRODUCT_MASCOT_MONTAGE") == "MONTAGE"
    assert roa.surface_properties("PRODUCT_MASCOT_MONTAGE") == expected


def test_D_unknown_surface_rejected():
    with pytest.raises(roa.RenderedOutputProbeError):
        roa.surface_properties("T2V")


# --- E: fully proven HYBRID clip -> PASS -------------------------------------

def test_E_hybrid_fully_proven_passes(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_PASS",
        vision_prover=_all_pass_vision, speech_prover=_all_pass_speech,
    )
    assert acc.status == roa.ACCEPT_PASS
    assert acc.failed == [] and acc.unproven == []
    assert all(v == roa.PROP_PASS for v in acc.properties.values())


# --- F: the core law — no provers -> UNPROVEN, never a silent PASS -----------

def test_F_no_provers_is_review_never_silent_pass(monkeypatch):
    _patch_media(monkeypatch)  # motion+audio present, but no vision/ASR provers
    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_PASS",
    )
    assert acc.status == roa.ACCEPT_REVIEW
    assert roa.ACCEPT_PASS != acc.status
    # every vision + ASR property is UNPROVEN, not PASS
    for p in ("PRESENTER_VISIBLE", "PRESENTER_PRODUCT_INTERACTION", "LIPSYNC_PRESENT",
              "SPOKEN_DIALOGUE_PRESENT", "BGM_ONLY_FALSE", "NON_STATIC_SCENE"):
        assert acc.properties[p] == roa.PROP_UNPROVEN
    # product fidelity was proven, so it is the one PASS
    assert acc.properties["PRODUCT_FIDELITY"] == roa.PROP_PASS


# --- G: cheap falsification overrides vision (truly-frozen -> FAIL) ----------

def test_G_truly_frozen_fails_non_static_even_with_vision_pass(monkeypatch):
    _patch_media(monkeypatch, truly_frozen=True)
    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_PASS",
        vision_prover=_all_pass_vision, speech_prover=_all_pass_speech,
    )
    assert acc.properties["NON_STATIC_SCENE"] == roa.PROP_FAIL
    assert "NON_STATIC_SCENE" in acc.failed
    assert acc.status == roa.ACCEPT_FAIL


# --- H: no audio stream -> spoken dialogue is a proven FAIL (the AQUABLANCE
#        BGM-only failure mode), even without an ASR prover --------------------

def test_H_no_audio_stream_fails_spoken_dialogue(monkeypatch):
    _patch_media(monkeypatch, audio_present=False)
    acc = roa.evaluate_surface_acceptance(
        "FACELESS", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_PASS",
        vision_prover=_all_pass_vision,  # everything visual proven...
    )
    assert acc.properties["SPOKEN_DIALOGUE_PRESENT"] == roa.PROP_FAIL  # ...but silent
    assert acc.status == roa.ACCEPT_FAIL


# --- I: ASR prover says BGM-only, no dialogue -> both speech props FAIL -------

def test_I_bgm_only_no_dialogue_fails(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_PASS",
        vision_prover=_all_pass_vision,
        speech_prover=lambda _p: {"dialogue_present": False, "bgm_only": True},
    )
    assert acc.properties["SPOKEN_DIALOGUE_PRESENT"] == roa.PROP_FAIL
    assert acc.properties["BGM_ONLY_FALSE"] == roa.PROP_FAIL
    assert acc.status == roa.ACCEPT_FAIL


# --- J/K: MONTAGE and FACELESS fully proven -> PASS with their exact props ----

def test_J_montage_fully_proven_passes(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance(
        "PRODUCT_MASCOT_MONTAGE", DUMMY, product_fidelity_status="PASS",
        vision_prover=_all_pass_vision, speech_prover=_all_pass_speech,
    )
    assert acc.surface == "MONTAGE"
    assert acc.status == roa.ACCEPT_PASS
    for p in ("MASCOT_VISIBLE", "MASCOT_IDENTITY_CONTINUITY", "MASCOT_ACTIVE_ACTION",
              "LIPSYNC_PRESENT"):
        assert acc.properties[p] == roa.PROP_PASS


def test_K_faceless_fully_proven_passes(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance(
        "FACELESS", DUMMY, product_fidelity_status="PASS",
        vision_prover=_all_pass_vision, speech_prover=_all_pass_speech,
    )
    assert acc.status == roa.ACCEPT_PASS
    for p in ("HUMAN_PRESENCE", "HAND_PRODUCT_INTERACTION", "NO_FACE_HEAD"):
        assert acc.properties[p] == roa.PROP_PASS


# --- L: product-fidelity FAIL sinks the whole clip ---------------------------

def test_L_product_fidelity_fail_forces_accept_fail(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PRODUCT_FIDELITY_QC_FAIL",
        vision_prover=_all_pass_vision, speech_prover=_all_pass_speech,
    )
    assert acc.properties["PRODUCT_FIDELITY"] == roa.PROP_FAIL
    assert acc.status == roa.ACCEPT_FAIL


# --- M: gate-status mapping (PASS/FAIL/REVIEW; dataclass or dict) -------------

def test_M_acceptance_gate_status_mapping():
    assert roa.acceptance_gate_status(roa.SurfaceAcceptance("HYBRID", roa.ACCEPT_PASS, {})) == roa.ACCEPT_PASS
    assert roa.acceptance_gate_status(roa.SurfaceAcceptance("HYBRID", roa.ACCEPT_FAIL, {})) == roa.ACCEPT_FAIL
    assert roa.acceptance_gate_status(roa.SurfaceAcceptance("HYBRID", roa.ACCEPT_REVIEW, {})) == roa.ACCEPT_REVIEW
    assert roa.acceptance_gate_status({"status": roa.ACCEPT_PASS}) == roa.ACCEPT_PASS
    assert roa.acceptance_gate_status(None) == roa.ACCEPT_REVIEW  # unknown -> review, never pass


# --- N: a partially-proven vision result still cannot silently pass -----------

def test_N_partial_vision_prover_stays_review(monkeypatch):
    _patch_media(monkeypatch)

    def _partial(_path, targets):
        # prove everything except presenter-product interaction, which it can't confirm
        return {p: (roa.PROP_UNPROVEN if p == "PRESENTER_PRODUCT_INTERACTION" else roa.PROP_PASS)
                for p in targets}

    acc = roa.evaluate_surface_acceptance(
        "HYBRID", DUMMY, product_fidelity_status="PASS",
        vision_prover=_partial, speech_prover=_all_pass_speech,
    )
    assert acc.properties["PRESENTER_PRODUCT_INTERACTION"] == roa.PROP_UNPROVEN
    assert "PRESENTER_PRODUCT_INTERACTION" in acc.unproven
    assert acc.status == roa.ACCEPT_REVIEW  # one UNPROVEN blocks PASS


# --- O: default (no fidelity, no provers) leaves fidelity UNPROVEN, not PASS --

def test_O_missing_product_fidelity_is_unproven(monkeypatch):
    _patch_media(monkeypatch)
    acc = roa.evaluate_surface_acceptance("HYBRID", DUMMY)  # nothing supplied
    assert acc.properties["PRODUCT_FIDELITY"] == roa.PROP_UNPROVEN
    assert acc.status == roa.ACCEPT_REVIEW
