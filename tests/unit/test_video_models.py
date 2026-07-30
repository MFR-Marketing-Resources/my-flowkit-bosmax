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
    # I6 registry: Omni Flash 10s CEILING is 30 (the 4s ceiling is 15). Cap-gate treats these
    # as ceilings, not exact values — a promo proposal below the ceiling still approves.
    assert vm.expected_cost("omni_flash", 10) == 30
    assert vm.expected_cost("omni_flash", 4) == 15
    assert vm.expected_cost("Omni Flash") == 30  # default 10s -> 30 ceiling


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
    assert omni["extend_totals_s"] == []
    veo = [m for m in lst if m["key"] == "veo_3_1_lite"][0]
    assert veo["extend_block_duration_s"] == 8
    assert veo["extend_totals_s"] == [16, 24]


def test_governed_orchestration_distinguishes_single_and_extend():
    assert vm.resolve_orchestration("omni_flash", 10) == {
        "generation_mode": "SINGLE",
        "requested_total_duration_seconds": 10,
        "engine_block_duration_seconds": 10,
        "segment_count": 1,
        "execution_route": "SINGLE_SHOT_QUEUE",
    }
    assert vm.resolve_orchestration("veo_3_1_lite", 16) == {
        "generation_mode": "EXTEND",
        "requested_total_duration_seconds": 16,
        "engine_block_duration_seconds": 8,
        "segment_count": 2,
        "execution_route": "VIDEO_JOBS_ORCHESTRATOR",
    }
    assert vm.resolve_orchestration("veo_3_1_quality", 24)["segment_count"] == 3


def test_unproven_omni_extend_is_refused():
    try:
        vm.resolve_orchestration("omni_flash", 20)
        assert False, "Omni 20s must remain absent until a 10s-block contract is proven"
    except ValueError as exc:
        assert "does not support 20s" in str(exc)


def test_default_cost_field_compat():
    # Compatibility lock: `default_cost` must NOT be renamed (UI dropdown + tests read it).
    # Its SEMANTICS are now ceiling/typical (promo-variable), but the field name stays.
    for m in vm.public_list():
        assert "default_cost" in m, f"{m['key']} lost the default_cost field"
        assert isinstance(m["default_cost"], int)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
    print(f"\nALL {len(fns)} TESTS PASSED")
