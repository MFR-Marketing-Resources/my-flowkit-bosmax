"""Phase A3 — legacy snapshots get product-specific angles WITHOUT mutation.

Approved snapshots are immutable, so the repair happens at read time and only
when the stored angles are verbatim a framework FAMILY template. A deliberately
authored angle list must survive untouched.
"""
from types import SimpleNamespace

from agent.services import copy_grounding_service as svc

# The exact template all 9 beauty-classified products carried on 2026-07-24.
FAMILY_TEMPLATE = [
    "routine_upgrade", "polished_finish", "portable_touch_up",
    "confidence_boost", "daily_convenience",
]

PERSONA = {
    "audience": "Ibu bapa di Malaysia",
    "pains": [
        "Anak sering menangis malam akibat perut kembung",
        "Sengal-sengal badan selepas bekerja",
        "Gigitan serangga menyebabkan kegatalan",
    ],
    "desires": ["Anak tidur lena", "Badan rasa ringan", "Kulit tidak gatal"],
}


def _snap(strategy, persona=PERSONA):
    return SimpleNamespace(
        copy_strategy_summary_json=strategy,
        buyer_persona_snapshot_json=persona,
    )


def test_family_template_is_recognised():
    assert svc._is_family_template(FAMILY_TEMPLATE) is True


def test_authored_angles_are_not_mistaken_for_a_template():
    assert svc._is_family_template(["anak menangis malam", "sengal badan"]) is False
    assert svc._is_family_template([]) is False
    # A partial overlap with a family template must NOT count as contamination.
    assert svc._is_family_template(["routine_upgrade", "sesuatu yang lain"]) is False


def test_legacy_family_template_is_replaced_by_derived_angles():
    got = svc._resolve_snapshot_angles(_snap({"angles": FAMILY_TEMPLATE}), None)
    assert got == PERSONA["pains"]
    assert "routine_upgrade" not in got


def test_deliberate_angles_are_respected():
    authored = ["Angle yang operator pilih sendiri", "Angle kedua"]
    got = svc._resolve_snapshot_angles(_snap({"angles": authored}), None)
    assert got == authored


def test_a2_stamped_angles_are_trusted_as_is():
    strategy = {
        "angles": ["Sesuatu"],
        "angle_source": "DERIVED_FROM_APPROVED_PERSONA",
    }
    assert svc._resolve_snapshot_angles(_snap(strategy), None) == ["Sesuatu"]


def test_empty_strategy_with_persona_derives():
    assert svc._resolve_snapshot_angles(_snap({}), None) == PERSONA["pains"]


def test_fail_closed_keeps_stored_angles_when_persona_is_underivable():
    """No persona to derive from -> the legacy list stands; the caller then
    applies the framework fallback exactly as before."""
    got = svc._resolve_snapshot_angles(
        _snap({"angles": FAMILY_TEMPLATE}, persona={}), None
    )
    assert got == FAMILY_TEMPLATE


def test_no_stored_and_no_persona_returns_empty_for_framework_fallback():
    assert svc._resolve_snapshot_angles(_snap({}, persona={}), None) == []
