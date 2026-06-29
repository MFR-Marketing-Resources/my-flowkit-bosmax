"""Tests for the video model registry (patch I1) — pricing authority + I6 regression."""
from agent.services import video_models as vm


def test_lite_cost_flat():
    assert vm.expected_cost("veo_3_1_lite", 8) == 10
    assert vm.expected_cost("Veo 3.1 - Lite") == 10  # default 8s


def test_fast_cost():
    assert vm.expected_cost("veo_3_1_fast", 8) == 20


def test_quality_8s_only():
    assert vm.expected_cost("veo_3_1_quality", 8) == 100
    try:
        vm.expected_cost("veo_3_1_quality", 4)
        assert False, "Quality must reject 4s"
    except ValueError:
        pass


def test_omni_cost_by_duration_I6():
    # I6 regression: Omni Flash 10s MUST be 30, NOT 15 (15 is the 4s price).
    assert vm.expected_cost("omni_flash", 10) == 30
    assert vm.expected_cost("omni_flash", 4) == 15
    assert vm.expected_cost("Omni Flash") == 30  # default 10s -> 30


def test_resolve_by_labels():
    assert vm.resolve("Veo 3.1 - Lite")["key"] == "veo_3_1_lite"
    assert vm.resolve("Gemini Omni Flash")["key"] == "omni_flash"
    assert vm.resolve(None)["key"] == vm.DEFAULT_MODEL


def test_unknown_model_raises():
    try:
        vm.resolve("Nano Banana 2")
        assert False, "ghost model must raise"
    except ValueError:
        pass


def test_model_matches():
    assert vm.model_matches("veo_3_1_r2v_lite", "veo_3_1_lite")
    assert vm.model_matches("veo_3_1_r2v_fast", "veo_3_1_fast")
    assert not vm.model_matches("veo_3_1_r2v_lite", "veo_3_1_fast")
    assert not vm.model_matches(None, "veo_3_1_lite")


def test_public_list_shape():
    lst = vm.public_list()
    assert len(lst) == 4
    omni = [m for m in lst if m["key"] == "omni_flash"][0]
    assert omni["default_cost"] == 30 and omni["default_duration_s"] == 10


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
