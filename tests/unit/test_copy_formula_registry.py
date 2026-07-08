"""Formula Registry integrity + resolution."""
from agent.authority import copy_formula_registry as reg


COMPILER_WHITELIST = {"PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"}


def test_all_eight_formulas_present():
    ids = set(reg.FORMULA_REGISTRY)
    assert ids == {"PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA", "SavagePAS", "HPAS"}


def test_canonical_vs_operator_review_draft():
    for fid in ("PAS", "AIDA", "HSO", "BAB", "PASTOR", "PESTA"):
        assert reg.FORMULA_REGISTRY[fid]["definition_status"] == reg.DEFINITION_CANONICAL
    for fid in ("SavagePAS", "HPAS"):
        assert reg.FORMULA_REGISTRY[fid]["definition_status"] == reg.DEFINITION_OPERATOR_REVIEW_DRAFT


def test_every_formula_is_well_formed():
    for fid, f in reg.FORMULA_REGISTRY.items():
        assert f["formula_id"] == fid
        assert f["slots"], f"{fid} has no slots"
        slot_ids = {s["slot_id"] for s in f["slots"]}
        assert all(s.get("purpose") for s in f["slots"])
        # compiler family must be whitelisted or it silently downgrades to HSO
        assert f["compiler_family"] in COMPILER_WHITELIST
        # output mapping keys are valid copy fields; referenced slots exist
        for field, slot in f["output_mapping"].items():
            assert field in reg.COPY_FIELDS
            refs = slot if isinstance(slot, list) else [slot]
            for r in refs:
                assert r in slot_ids, f"{fid}: mapping {field} -> unknown slot {r}"


def test_canonical_slots_match_framework_yaml():
    # Faithful to COPYWRITING_FRAMEWORK_UNIVERSAL.yaml formula_library.
    assert reg.required_slot_ids("PAS")[:3] == ["problem", "agitate", "solution"]
    assert reg.required_slot_ids("AIDA") == ["attention", "interest", "desire", "action"]
    assert reg.required_slot_ids("HSO") == ["hook", "story", "offer"]
    assert reg.required_slot_ids("BAB") == ["before", "after", "bridge"]
    assert reg.required_slot_ids("PASTOR") == [
        "problem", "amplify", "story", "transformation", "offer", "response",
    ]
    assert reg.required_slot_ids("PESTA") == [
        "pain", "emotion", "solution", "transformation", "action",
    ]


def test_normalize_resolves_labels_and_aliases():
    assert reg.normalize_formula_id("PAS") == "PAS"
    assert reg.normalize_formula_id("pas") == "PAS"
    assert reg.normalize_formula_id("SAVAGE_HPAS") == "HPAS"
    assert reg.normalize_formula_id("SAVAGE_PAS") == "SavagePAS"
    # a grounding label like "PAS / HSO / AIDA (STEALTH silo)" -> first token
    assert reg.normalize_formula_id("PAS / HSO / AIDA (STEALTH silo)") == "PAS"
    assert reg.normalize_formula_id("") == "HSO"
    assert reg.normalize_formula_id("nonsense-xyz") == "HSO"


def test_savage_and_hpas_map_to_compiler_safe_family():
    assert reg.compiler_family_for("SavagePAS") == "PAS"
    assert reg.compiler_family_for("HPAS") == "PAS"


def test_recommend_formula():
    assert reg.recommend_formula(is_stealth=True) == "PESTA"
    assert reg.recommend_formula(family="MALE_HEALTH_SENSITIVE") == "PESTA"
    assert reg.recommend_formula() == "PAS"
