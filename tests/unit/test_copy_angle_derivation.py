"""Phase A1 — pure angle derivation from an approved buyer persona.

Fixtures use the REAL live persona shapes measured on 2026-07-24 so the tests
pin actual catalog behaviour, not an idealised one.
"""
from agent.services import copy_angle_derivation as mod


# The real MWTCB persona (product 6483d624…). Note that `triggers` is NOT
# index-aligned with `pains`: triggers[1] ("selepas makan") belongs to the
# colic pain at index 0, while the aches pain at index 1 is matched by
# triggers[2] ("cuaca sejuk ... badan sengal").
MWTCB = {
    "audience": "Ibu bapa di Malaysia yang aktif mencari produk tradisional untuk kegunaan keluarga",
    "pains": [
        "Anak sering menangis malam akibat perut kembung atau berangin",
        "Sengal-sengal badan selepas bekerja atau bangun tidur",
        "Kebas tangan dan kaki yang mengganggu aktiviti harian",
        "Gigitan serangga yang menyebabkan kegatalan",
    ],
    "desires": [
        "Anak tidur lena tanpa menangis malam",
        "Badan rasa ringan dan selesa selepas bekerja",
        "Tangan dan kaki tidak kebas ketika buat kerja harian",
        "Anak tidak gatal atau bengkak selepas digigit serangga",
    ],
    "fears": [
        "Anak terus menangis malam kerana perut kembung",
        "Sengal-sengal berlarutan sehingga susah nak bergerak",
        "Kebas tangan dan kaki makin teruk",
        "Gigitan serangga jadi bengkak dan bernanah",
    ],
    "triggers": [
        "Anak susah tidur kerana perut kembung",
        "Rasa tidak selesa selepas makan",
        "Cuaca sejuk atau hujan menyebabkan badan sengal",
        "Musim gigitan serangga",
    ],
    "tone": "mesra, prihatin, tradisional, meyakinkan",
    "pronoun": "anda",
}


def test_derives_one_angle_per_pain():
    out = mod.derive_angles(MWTCB)
    assert out["derived"] is True
    assert len(out["angles"]) == 4
    assert [a["label"] for a in out["angles"]] == MWTCB["pains"]


def test_angle_keys_are_stable_and_unique():
    out = mod.derive_angles(MWTCB)
    keys = mod.angle_keys(out)
    assert len(set(keys)) == 4
    assert all(k.startswith("ang_") and len(k) == 16 for k in keys)


def test_angle_key_survives_rewording_of_punctuation_and_case():
    """Components in Phase B hang off angle_key; copy-editing the pain's case or
    punctuation must NOT orphan them."""
    a = mod.derive_angles({"audience": "x", "pains": ["Sengal-sengal badan selepas bekerja"]})
    b = mod.derive_angles({"audience": "x", "pains": ["  sengal sengal BADAN, selepas bekerja!  "]})
    assert mod.angle_keys(a) == mod.angle_keys(b)


def test_angle_key_changes_when_the_pain_genuinely_changes():
    a = mod.derive_angles({"audience": "x", "pains": ["Kebas tangan dan kaki"]})
    b = mod.derive_angles({"audience": "x", "pains": ["Gigitan serangga gatal"]})
    assert mod.angle_keys(a) != mod.angle_keys(b)


def test_matching_is_by_token_overlap_not_list_index():
    """THE load-bearing contract. A naive zip() would give the aches pain the
    'selepas makan' trigger at the same index; overlap matching must instead
    pick the 'cuaca sejuk ... badan sengal' trigger."""
    out = mod.derive_angles(MWTCB)
    aches = out["angles"][1]
    assert "sengal" in aches["trigger"].lower()
    assert "makan" not in aches["trigger"].lower()
    # And the colic pain keeps its own themed matches.
    colic = out["angles"][0]
    assert "kembung" in colic["trigger"].lower()
    assert "menangis" in colic["desire"].lower()


def test_unmatchable_supporting_fields_are_empty_not_guessed():
    out = mod.derive_angles({
        "audience": "Sesiapa",
        "pains": ["Xyzzy plugh frobnicate"],
        "desires": ["Sesuatu yang langsung tiada kaitan"],
        "triggers": [],
    })
    angle = out["angles"][0]
    assert angle["desire"] == ""
    assert angle["trigger"] == ""


def test_audience_comes_from_product_level():
    out = mod.derive_angles(MWTCB)
    assert all(a["audience"] == MWTCB["audience"] for a in out["angles"])


def test_audience_conflict_is_flagged_not_resolved():
    """MWTCB's audience is parents, but the aches pain is about working adults.
    The machine must flag it for operator split, never silently reassign."""
    out = mod.derive_angles(MWTCB)
    aches = out["angles"][1]
    assert aches["audience_conflict"] is True
    assert "pekerja" in aches["audience_subjects"]
    # The colic pain agrees with the product audience -> no conflict.
    assert out["angles"][0]["audience_conflict"] is False
    assert any(w.startswith("AUDIENCE_CONFLICT:") for w in out["warnings"])


def test_fail_closed_on_missing_persona():
    for bad in (None, {}, [], "persona", 42):
        out = mod.derive_angles(bad)
        assert out["derived"] is False
        assert out["angles"] == []


def test_fail_closed_on_persona_without_pains():
    out = mod.derive_angles({"audience": "Lelaki 18-45", "desires": ["kemas"]})
    assert out["derived"] is False
    assert out["angles"] == []
    assert "NO_PAINS" in out["warnings"]


def test_nested_persona_is_unwrapped():
    out = mod.derive_angles({"persona": {"audience": "A", "pains": ["Rambut cepat panjang"]}})
    assert out["derived"] is True
    assert len(out["angles"]) == 1
    assert "PERSONA_NESTED_UNWRAPPED" in out["warnings"]


def test_duplicate_pains_collapse_to_one_angle():
    out = mod.derive_angles({
        "audience": "A",
        "pains": ["Kulit kusam", "kulit KUSAM!", "Rambut gugur"],
    })
    assert len(out["angles"]) == 2
    assert any(w.startswith("DUPLICATE_PAIN_SKIPPED:") for w in out["warnings"])


def test_angle_count_is_capped():
    out = mod.derive_angles(
        {"audience": "A", "pains": [f"Masalah nombor {i}" for i in range(40)]},
        max_angles=5,
    )
    assert len(out["angles"]) == 5
    assert any(w.startswith("PAINS_TRUNCATED:") for w in out["warnings"])


def test_missing_audience_is_marked_not_invented():
    out = mod.derive_angles({"pains": ["Kulit kering"]})
    assert out["angles"][0]["audience"] == mod.AUDIENCE_UNSPECIFIED
    assert "AUDIENCE_MISSING" in out["warnings"]


def test_non_string_pain_entries_are_dropped_without_raising():
    out = mod.derive_angles({"audience": "A", "pains": ["Sah", None, 7, "", {"x": 1}]})
    assert [a["label"] for a in out["angles"]] == ["Sah"]
