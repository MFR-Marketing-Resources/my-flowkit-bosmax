"""Unit gate for the operator-policy video capability matrix (v1).

Asserts the operator-policy ∩ registry law, fail-closed validation codes, and
that the public matrix is a faithful, versioned mirror of the registry — the
frontend derives its options from this, so it must not drift.
"""

import pytest

from agent.services import video_capability_matrix as cm
from agent.services import video_models as vm


def test_google_flow_single_policy_is_exactly_8_and_10():
    assert cm.single_duration_policy("GOOGLE_FLOW") == [8, 10]


def test_grok_declared_but_unsupported_runtime():
    assert cm.single_duration_policy("GROK") == [6, 10]
    # No transport / no selectable models — nothing executable.
    assert cm.models_for_engine("GROK") == []
    assert cm.models_for_single("GROK", 6) == []


def test_models_for_single_is_policy_intersect_registry():
    keys_8 = {m["key"] for m in cm.models_for_single("GOOGLE_FLOW", 8)}
    keys_10 = {m["key"] for m in cm.models_for_single("GOOGLE_FLOW", 10)}
    # 8s: every registry model whose allowed_durations_s contains 8.
    assert keys_8 == {
        k for k, s in vm.VIDEO_MODELS.items() if 8 in s["allowed_durations_s"]
    }
    # 10s: only Omni Flash supports 10 in the current registry.
    assert keys_10 == {"omni_flash"}


def test_out_of_policy_duration_yields_no_models():
    # 6s is a real Veo/Omni capability but NOT in the Flow operator policy.
    assert cm.models_for_single("GOOGLE_FLOW", 6) == []


def test_default_model_is_deterministic_and_compatible():
    assert cm.default_model_for_single("GOOGLE_FLOW", 8) == vm.DEFAULT_MODEL
    assert cm.default_model_for_single("GOOGLE_FLOW", 10) == "omni_flash"


@pytest.mark.parametrize(
    "engine,model,duration,expected",
    [
        ("GOOGLE_FLOW", "Veo 3.1 - Lite", 8, (True, None)),
        ("GOOGLE_FLOW", "Omni Flash", 10, (True, None)),
        ("GOOGLE_FLOW", "Omni Flash", 8, (True, None)),
        # 6s / 12s never in Flow policy.
        ("GOOGLE_FLOW", "Omni Flash", 6, (False, cm.ERR_UNSUPPORTED_ENGINE_DURATION)),
        ("GOOGLE_FLOW", "Omni Flash", 12, (False, cm.ERR_UNSUPPORTED_ENGINE_DURATION)),
        # In policy, but the model can't do it (Veo has no 10s).
        ("GOOGLE_FLOW", "Veo 3.1 - Lite", 10, (False, cm.ERR_UNSUPPORTED_MODEL_DURATION)),
        # Unknown model.
        ("GOOGLE_FLOW", "Sora Turbo", 8, (False, cm.ERR_UNSUPPORTED_ENGINE_MODEL)),
        # Grok not runtime-integrated.
        ("GROK", "Omni Flash", 6, (False, cm.ERR_ENGINE_RUNTIME_NOT_INTEGRATED)),
        ("GROK", "Omni Flash", 10, (False, cm.ERR_ENGINE_RUNTIME_NOT_INTEGRATED)),
        # Unknown engine.
        ("MARS", "Omni Flash", 8, (False, cm.ERR_UNSUPPORTED_ENGINE)),
        (None, "Omni Flash", 8, (False, cm.ERR_UNSUPPORTED_ENGINE)),
    ],
)
def test_validate_single_fail_closed(engine, model, duration, expected):
    assert cm.validate_single(engine, model, duration) == expected


def test_public_matrix_shape_and_version():
    pm = cm.public_matrix()
    assert pm["capability_matrix_version"] == cm.CAPABILITY_MATRIX_VERSION
    assert pm["default_engine"] == "GOOGLE_FLOW"
    by_id = {e["id"]: e for e in pm["engines"]}
    assert set(by_id) == {"GOOGLE_FLOW", "GROK"}

    flow = by_id["GOOGLE_FLOW"]
    assert flow["supported"] is True
    assert flow["single_duration_policy"] == [8, 10]
    assert flow["default_single_duration"] == 8
    assert flow["single_models_by_duration"]["10"] == ["omni_flash"]
    assert flow["default_model_by_duration"] == {"8": "veo_3_1_lite", "10": "omni_flash"}
    # Mirror fidelity: every advertised model duration matches the registry.
    for m in flow["models"]:
        assert m["allowed_durations_s"] == vm.VIDEO_MODELS[m["key"]]["allowed_durations_s"]

    grok = by_id["GROK"]
    assert grok["supported"] is False
    assert grok["unsupported_reason"] == "Runtime not yet integrated."
    assert grok["models"] == []
