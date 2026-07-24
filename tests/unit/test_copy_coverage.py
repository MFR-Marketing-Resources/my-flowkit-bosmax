"""Phase C2 — the angle coverage gate (uniqueness != diversity)."""
from agent.services import copy_coverage_service as svc

A, B, C, D = "ang_colic", "ang_aches", "ang_numb", "ang_bite"
ALL4 = [A, B, C, D]


def _items(**per_angle):
    out = []
    for key, n in per_angle.items():
        out += [{"angle_key": key} for _ in range(n)]
    return out


def test_the_live_failure_is_caught():
    """THE regression this module exists for: 57 of 58 MWTCB copy sets were one
    theme, and every existing gate passed them because each was textually
    unique. Coverage must call it monoculture."""
    items = _items(ang_colic=57, ang_aches=1)
    rep = svc.evaluate_coverage(items, ALL4)
    assert rep["status"] == svc.STATUS_MONOCULTURE
    assert rep["dominant_angle"] == A
    assert rep["dominant_share"] > 0.95
    assert set(rep["missing_angles"]) == {C, D}
    assert any(w.startswith("ANGLE_MONOCULTURE:") for w in rep["warnings"])


def test_even_spread_is_ok():
    rep = svc.evaluate_coverage(_items(ang_colic=5, ang_aches=5, ang_numb=5, ang_bite=5), ALL4)
    assert rep["status"] == svc.STATUS_OK
    assert rep["warnings"] == []
    assert rep["angles_covered"] == 4
    assert rep["dominant_share"] == 0.25


def test_mild_lean_is_skewed_not_monoculture():
    """40% is over the 35% threshold but nowhere near a takeover."""
    rep = svc.evaluate_coverage(_items(ang_colic=8, ang_aches=4, ang_numb=4, ang_bite=4), ALL4)
    assert rep["status"] == svc.STATUS_SKEWED
    assert any(w.startswith("ANGLE_SKEWED:") for w in rep["warnings"])


def test_unused_angles_are_flagged_even_when_the_split_is_even():
    """BREADTH axis: a perfect 50/50 across 2 of 4 angles still ignores two real
    use-cases. Concentration alone would have called this fine."""
    rep = svc.evaluate_coverage(_items(ang_colic=10, ang_aches=10), ALL4)
    assert rep["dominant_share"] == 0.5
    assert rep["status"] != svc.STATUS_OK
    assert sorted(rep["missing_angles"]) == sorted([C, D])
    assert any(w.startswith("ANGLES_UNUSED:") for w in rep["warnings"])


def test_available_angles_drive_the_verdict_not_just_present_ones():
    """Without `angle_keys` the unused angles are invisible — that blind spot is
    exactly what let the monoculture through."""
    items = _items(ang_colic=10, ang_aches=10)
    blind = svc.evaluate_coverage(items)
    seeing = svc.evaluate_coverage(items, ALL4)
    assert blind["missing_angles"] == []
    assert seeing["missing_angles"]
    assert blind["angles_available"] == 2
    assert seeing["angles_available"] == 4


def test_single_available_angle_is_never_a_monoculture():
    """With one angle there is nothing to spread across, so concentration
    carries no information and must not raise a false alarm."""
    rep = svc.evaluate_coverage(_items(ang_colic=20), [A])
    assert rep["status"] == svc.STATUS_OK
    assert rep["warnings"] == []


def test_items_without_an_angle_are_reported_not_silently_dropped():
    rep = svc.evaluate_coverage(
        [{"angle_key": A}, {"angle_key": ""}, {"nope": 1}], [A]
    )
    assert rep["unattributed_items"] == 2
    assert rep["attributed_items"] == 1
    assert any(w.startswith("ITEMS_WITHOUT_ANGLE:") for w in rep["warnings"])


def test_advisory_by_default_and_blocking_only_on_request():
    items = _items(ang_colic=57, ang_aches=1)
    assert svc.evaluate_coverage(items, ALL4)["blocked"] is False
    assert svc.evaluate_coverage(items, ALL4, blocking=True)["blocked"] is True
    # A merely skewed batch never blocks, even in blocking mode.
    mild = _items(ang_colic=8, ang_aches=4, ang_numb=4, ang_bite=4)
    assert svc.evaluate_coverage(mild, ALL4, blocking=True)["blocked"] is False


def test_labels_surface_pain_text_not_hashes():
    rep = svc.evaluate_coverage(
        _items(ang_colic=3), ALL4, labels={A: "Anak menangis malam"}
    )
    assert rep["dominant_label"] == "Anak menangis malam"
    assert rep["per_angle"][0]["angle_label"] == "Anak menangis malam"


def test_thresholds_are_tunable():
    items = _items(ang_colic=6, ang_aches=4)
    assert svc.evaluate_coverage(items, [A, B], max_share=0.9)["status"] == svc.STATUS_OK
    assert svc.evaluate_coverage(items, [A, B], max_share=0.5)["status"] == svc.STATUS_SKEWED


def test_thresholds_scale_with_angle_count_no_false_alarm_on_two_angles():
    """An ABSOLUTE bar is wrong for small angle counts: with 2 angles the
    dominant share can never drop below 0.50, so a fixed 0.35 bar would flag
    every 2-angle batch forever. Bars must scale off the even split."""
    even_two = svc.evaluate_coverage(_items(ang_colic=5, ang_aches=5), [A, B])
    assert even_two["dominant_share"] == 0.5
    assert even_two["status"] == svc.STATUS_OK          # would have been SKEWED
    assert even_two["max_share"] > 0.5

    # The same 0.5 share across FOUR available angles is genuinely skewed.
    even_four = svc.evaluate_coverage(_items(ang_colic=10, ang_aches=10), ALL4)
    assert even_four["dominant_share"] == 0.5
    assert even_four["status"] != svc.STATUS_OK
    assert even_four["max_share"] < 0.5


def test_reported_bars_are_the_ones_actually_applied():
    rep = svc.evaluate_coverage(_items(ang_colic=1, ang_aches=1, ang_numb=1, ang_bite=1), ALL4)
    assert abs(rep["max_share"] - 0.35) < 1e-9      # 4 angles -> even .25 x1.4
    assert rep["max_share"] <= 0.60


def test_empty_and_degenerate_inputs_are_safe():
    rep = svc.evaluate_coverage([], ALL4)
    assert rep["status"] == svc.STATUS_OK
    assert rep["total_items"] == 0
    assert rep["dominant_angle"] is None
    assert svc.evaluate_coverage([], [])["angles_available"] == 0
    assert svc.evaluate_coverage(None, None)["total_items"] == 0


def test_accepts_objects_as_well_as_dicts():
    class Item:
        angle_key = A

    rep = svc.evaluate_coverage([Item(), Item()], [A])
    assert rep["attributed_items"] == 2
