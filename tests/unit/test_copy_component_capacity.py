"""Phase B1 — atomic component pool capacity math."""
from agent.services import copy_component_service as svc

A1, A2 = "ang_aaaa11112222", "ang_bbbb33334444"


def _c(ctype, angle=A1, content="x", status=svc.STATUS_APPROVED, archived=0, n=1):
    """n components of one type/angle, each with distinct content."""
    return [
        {
            "component_type": ctype,
            "angle_key": angle,
            "content": f"{content}-{i}",
            "status": status,
            "archived": archived,
        }
        for i in range(n)
    ]


def _full_angle(angle, hooks=2, subhooks=2, usps=2, ctas=2):
    return (
        _c(svc.HOOK, angle, "h", n=hooks)
        + _c(svc.SUBHOOK, angle, "b", n=subhooks)
        + _c(svc.USP_SET, angle, "u", n=usps)
        + _c(svc.CTA, angle, "c", n=ctas)
    )


def test_capacity_is_multiplicative_not_additive():
    """The whole point: 8 components -> 16 copies, not 8."""
    cap = svc.pool_capacity(_full_angle(A1), [A1])
    assert cap["total_combinations"] == 2 * 2 * 2 * 2


def test_formulas_multiply_capacity():
    cap = svc.pool_capacity(_full_angle(A1), [A1], formula_count=6)
    assert cap["total_combinations"] == 16 * 6


def test_angles_sum_not_multiply():
    """Angles are alternatives, not factors — a colic hook must never pair with
    an aches body, so capacity SUMS across angles."""
    pool = _full_angle(A1) + _full_angle(A2)
    cap = svc.pool_capacity(pool, [A1, A2])
    assert cap["total_combinations"] == 16 + 16


def test_one_missing_type_zeroes_that_angle():
    pool = _c(svc.HOOK, A1, n=5) + _c(svc.SUBHOOK, A1, n=5) + _c(svc.USP_SET, A1, n=5)
    cap = svc.pool_capacity(pool, [A1])
    assert cap["total_combinations"] == 0
    assert cap["per_angle"][0]["missing_types"] == [svc.CTA]
    assert cap["blocked_angles"] == [A1]


def test_global_components_count_toward_every_angle():
    """An empty angle_key means 'applies to all angles' — how CTAs behave."""
    pool = (
        _c(svc.HOOK, A1, n=2) + _c(svc.SUBHOOK, A1, n=2) + _c(svc.USP_SET, A1, n=2)
        + _c(svc.HOOK, A2, n=2) + _c(svc.SUBHOOK, A2, n=2) + _c(svc.USP_SET, A2, n=2)
        + _c(svc.CTA, "", "shared", n=3)  # global CTAs
    )
    cap = svc.pool_capacity(pool, [A1, A2])
    assert cap["total_combinations"] == (2 * 2 * 2 * 3) * 2
    assert cap["blocked_angles"] == []


def test_unapproved_components_do_not_count():
    """An unreviewed component can never reach a composed copy."""
    pool = _full_angle(A1)
    pool += _c(svc.HOOK, A1, "pending", status="COMPONENT_REVIEW_REQUIRED", n=10)
    assert svc.pool_capacity(pool, [A1])["total_combinations"] == 16


def test_archived_components_do_not_count():
    pool = _full_angle(A1) + _c(svc.HOOK, A1, "old", archived=1, n=10)
    assert svc.pool_capacity(pool, [A1])["total_combinations"] == 16


def test_next_best_points_at_the_highest_leverage_slot():
    """3 hooks x 1 body x 2 usp x 2 cta = 12. Adding a SUBHOOK doubles it (+12);
    adding a HOOK adds only 4. The operator must be told SUBHOOK."""
    pool = (
        _c(svc.HOOK, A1, "h", n=3) + _c(svc.SUBHOOK, A1, "b", n=1)
        + _c(svc.USP_SET, A1, "u", n=2) + _c(svc.CTA, A1, "c", n=2)
    )
    cap = svc.pool_capacity(pool, [A1])
    assert cap["total_combinations"] == 12
    assert cap["per_angle"][0]["next_best_type"] == svc.SUBHOOK
    assert cap["next_best"]["component_type"] == svc.SUBHOOK
    assert cap["next_best"]["unlocks"] == 12


def test_blocked_angle_reports_zero_marginal_gain_for_non_blocking_types():
    """With no CTA at all, adding another hook unlocks nothing."""
    pool = _c(svc.HOOK, A1, n=2) + _c(svc.SUBHOOK, A1, n=2) + _c(svc.USP_SET, A1, n=2)
    gains = svc.pool_capacity(pool, [A1])["per_angle"][0]["marginal_gain"]
    assert gains[svc.HOOK] == 0
    assert gains[svc.CTA] > 0


def test_empty_pool_and_no_angles_are_safe():
    assert svc.pool_capacity([], [])["total_combinations"] == 0
    assert svc.pool_capacity([], [A1])["blocked_angles"] == [A1]
    assert svc.pool_capacity(_full_angle(A1), [])["total_combinations"] == 0


def test_components_on_an_unknown_angle_are_ignored():
    pool = _full_angle(A1) + _full_angle("ang_not_requested")
    assert svc.pool_capacity(pool, [A1])["total_combinations"] == 16


def test_dedupe_key_is_normalised_and_stable():
    a = svc.make_dedupe_key("Anak menangis malam?")
    b = svc.make_dedupe_key("  anak MENANGIS malam!!  ")
    assert a == b
    assert a != svc.make_dedupe_key("Sengal badan")
    assert a.startswith("cmp_")


def test_unknown_component_types_are_ignored():
    """BODY is the example on purpose: an earlier draft of this module had it as
    a real type, but CopySetResponse has no `body` slot, so it maps to nothing
    and must never contribute capacity."""
    pool = _full_angle(A1) + [
        {"component_type": "BODY", "angle_key": A1, "content": "x",
         "status": svc.STATUS_APPROVED, "archived": 0}
    ]
    assert svc.pool_capacity(pool, [A1])["total_combinations"] == 16
    assert "BODY" not in svc.COMPONENT_TYPES


def test_worked_example_from_the_architecture_doc():
    """The doc promises ~19,200 from 73 authored pieces: per angle
    8 hooks x 5 subhooks x 4 usp_sets x 5 ctas = 800, x4 angles x6 formulas."""
    angles = [f"ang_{i:012d}" for i in range(4)]
    pool = []
    for a in angles:
        pool += _c(svc.HOOK, a, "h", n=8) + _c(svc.SUBHOOK, a, "b", n=5)
        pool += _c(svc.USP_SET, a, "u", n=4) + _c(svc.CTA, a, "c", n=5)
    cap = svc.pool_capacity(pool, angles, formula_count=6)
    assert cap["total_combinations"] == 800 * 4 * 6 == 19200
