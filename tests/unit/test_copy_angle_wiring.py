"""Phase A2 — angle derivation wired into the review-draft write path.

Tests the pure payload transform directly (no DB), because that is the unit A2
introduces; both create_review_draft and update_review_draft route through it.
"""
from agent.services import product_intelligence_review_draft_service as svc

PERSONA = {
    "audience": "Ibu bapa di Malaysia yang mencari produk tradisional",
    "pains": [
        "Anak sering menangis malam akibat perut kembung",
        "Sengal-sengal badan selepas bekerja",
    ],
    "desires": ["Anak tidur lena tanpa menangis malam", "Badan rasa ringan selepas bekerja"],
    "triggers": ["Anak susah tidur kerana perut kembung", "Cuaca sejuk badan sengal"],
}


def test_angles_are_derived_when_absent():
    out = svc._apply_derived_angles({"buyer_persona_snapshot_json": PERSONA})
    strategy = out["copy_strategy_summary_json"]
    assert strategy["angles"] == PERSONA["pains"]
    assert strategy["angle_source"] == "DERIVED_FROM_APPROVED_PERSONA"


def test_angles_hold_readable_labels_not_hashes():
    """`angles` is injected into the LLM brief verbatim as target_angle_strategy.
    A hash there would be worse than the generic label it replaces."""
    out = svc._apply_derived_angles({"buyer_persona_snapshot_json": PERSONA})
    for angle in out["copy_strategy_summary_json"]["angles"]:
        assert not angle.startswith("ang_")
        assert " " in angle  # a real sentence, not a slug


def test_angle_registry_carries_stable_keys_for_phase_b():
    out = svc._apply_derived_angles({"buyer_persona_snapshot_json": PERSONA})
    registry = out["copy_strategy_summary_json"]["angle_registry"]
    assert len(registry) == 2
    assert all(r["angle_key"].startswith("ang_") for r in registry)
    assert {r["label"] for r in registry} == set(PERSONA["pains"])


def test_explicit_angles_are_never_overwritten():
    """Operator/caller intent wins over derivation."""
    payload = {
        "buyer_persona_snapshot_json": PERSONA,
        "copy_strategy_summary_json": {"angles": ["angle pilihan operator"]},
    }
    out = svc._apply_derived_angles(payload)
    assert out["copy_strategy_summary_json"]["angles"] == ["angle pilihan operator"]
    assert "angle_registry" not in out["copy_strategy_summary_json"]


def test_fail_closed_leaves_field_untouched_without_persona():
    """No derivable persona -> reader keeps today's framework-family fallback."""
    for persona in (None, {}, {"audience": "A"}, {"pains": []}):
        payload = {"buyer_persona_snapshot_json": persona}
        out = svc._apply_derived_angles(payload)
        strategy = out.get("copy_strategy_summary_json") or {}
        assert "angles" not in strategy


def test_existing_strategy_keys_are_preserved():
    """The Kalodata promotion path writes hook/cta/key_features here; derivation
    must add angles beside them, never replace the dict."""
    payload = {
        "buyer_persona_snapshot_json": PERSONA,
        "copy_strategy_summary_json": {
            "hook": "h", "cta": "c", "source": "approved_copy_intelligence",
        },
    }
    out = svc._apply_derived_angles(payload)
    strategy = out["copy_strategy_summary_json"]
    assert strategy["hook"] == "h"
    assert strategy["cta"] == "c"
    assert strategy["source"] == "approved_copy_intelligence"
    assert len(strategy["angles"]) == 2


def test_input_payload_is_not_mutated_in_place():
    payload = {"buyer_persona_snapshot_json": PERSONA}
    svc._apply_derived_angles(payload)
    assert "copy_strategy_summary_json" not in payload


def test_audience_conflict_surfaces_in_registry():
    out = svc._apply_derived_angles({"buyer_persona_snapshot_json": PERSONA})
    registry = out["copy_strategy_summary_json"]["angle_registry"]
    aches = [r for r in registry if "Sengal" in r["label"]][0]
    colic = [r for r in registry if "menangis" in r["label"]][0]
    assert aches["audience_conflict"] is True
    assert colic["audience_conflict"] is False
