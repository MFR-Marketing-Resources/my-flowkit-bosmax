"""Formula Validator + Sales Clarity QA — slot, market-language, grounding gates."""
from agent.models.copy_grounding import (
    GROUNDING_APPROVED_SNAPSHOT,
    BuyerPersona,
    CopyGrounding,
    ProductKnowledge,
)
from agent.services.formula_validator_service import validate_formula_copy
from agent.services.sales_clarity_qa_service import assess_sales_clarity


def _mwtcb_grounding(is_stealth: bool = False) -> CopyGrounding:
    return CopyGrounding(
        product_id="mwtcb",
        grounded=True,
        source=GROUNDING_APPROVED_SNAPSHOT,
        is_stealth=is_stealth,
        product_knowledge=ProductKnowledge(
            description="Minyak sapuan tradisional 25ml",
            benefits=["mudah dibawa", "cepat serap", "bau tidak kuat"],
            usps=["botol kecil", "sapuan tradisional"],
            target_customer="ibu ada anak kecil",
        ),
        buyer_persona=BuyerPersona(
            audience="ibu ada anak kecil",
            pains=["anak kembung perut", "anak susah lena"],
            triggers=["anak tak selesa waktu malam"],
        ),
    )


# Grounded MWTCB PAS copy from the owner's target example.
_MWTCB_PAS = {
    "angle": "anak kembung perut waktu malam",
    "hook": "Anak kecil kembung perut waktu malam, ibu pula susah nak rehat.",
    "subhook": "Bila anak merengek dan susah lena, rutin tidur satu rumah boleh terganggu.",
    "usp_set": [
        "MWTCB 25ml minyak sapuan tradisional keluarga",
        "botol kecil mudah dibawa, bau tidak kuat",
    ],
    "cta": "Jom cuba sendiri. Klik beg kuning untuk dapatkan botol pertama.",
}


def test_grounded_pas_copy_passes_validation():
    r = validate_formula_copy("PAS", _MWTCB_PAS, grounding=_mwtcb_grounding())
    assert r["valid"] is True
    assert r["review_required"] is False
    assert all(r["slot_coverage"].values())
    assert r["violations"] == []


def test_pas_missing_agitate_fails_slot():
    copy = {**_MWTCB_PAS, "subhook": ""}
    r = validate_formula_copy("PAS", copy, grounding=_mwtcb_grounding())
    codes = [v["code"] for v in r["violations"]]
    assert "SLOT_MISSING:agitate" in codes
    assert r["review_required"] is True


def test_vague_cowardly_copy_flagged_no_problem():
    vague = {
        "angle": "rutin harian",
        "hook": "Nak tampil yakin setiap hari tanpa perlu banyak langkah?",
        "subhook": "",
        "usp_set": ["Tekstur ringan", "mudah dibawa"],
        "cta": "Cuba sendiri",
    }
    r = validate_formula_copy("PAS", vague, grounding=_mwtcb_grounding())
    codes = [v["code"] for v in r["violations"]]
    assert "NO_PROBLEM_IDENTIFIED" in codes
    assert "SLOT_MISSING:agitate" in codes


def test_overclaim_is_hard_fail():
    bad = {**_MWTCB_PAS, "cta": "Dijamin 100% sembuh, terbukti klinikal!"}
    r = validate_formula_copy("PAS", bad, grounding=_mwtcb_grounding())
    codes = [v["code"] for v in r["violations"]]
    assert "OVERCLAIM" in codes
    assert r["valid"] is False


def test_usp_not_grounded_when_facts_exist():
    off = {**_MWTCB_PAS, "usp_set": ["warna cantik", "reka bentuk moden"]}
    r = validate_formula_copy("PAS", off, grounding=_mwtcb_grounding())
    codes = [v["code"] for v in r["violations"]]
    assert "USP_NOT_GROUNDED" in codes


def test_aida_requires_desire_and_hso_requires_story_offer():
    aida = {"angle": "", "hook": "attention line", "subhook": "interest line", "usp_set": [], "cta": "act now here"}
    r = validate_formula_copy("AIDA", aida, grounding=_mwtcb_grounding())
    assert r["slot_coverage"]["desire"] is False  # angle + usp (both map to desire) are empty
    hso = {"angle": "a", "hook": "hook line", "subhook": "", "usp_set": [], "cta": ""}
    r2 = validate_formula_copy("HSO", hso, grounding=_mwtcb_grounding())
    assert r2["slot_coverage"]["story"] is False and r2["slot_coverage"]["offer"] is False


def test_sales_clarity_passes_for_grounded_pas():
    v = validate_formula_copy("PAS", _MWTCB_PAS, grounding=_mwtcb_grounding())
    qa = assess_sales_clarity(_MWTCB_PAS, grounding=_mwtcb_grounding(), formula_id="PAS", validation=v)
    assert qa["answers"]["problem"] is True
    assert qa["answers"]["customer"] is True
    assert qa["answers"]["slots_satisfied"] is True
    assert qa["clear"] is True


def test_sales_clarity_flags_vague_copy():
    vague = {
        "angle": "rutin", "hook": "Nak yakin setiap hari?", "subhook": "",
        "usp_set": ["ringan"], "cta": "klik",
    }
    v = validate_formula_copy("PAS", vague, grounding=_mwtcb_grounding())
    qa = assess_sales_clarity(vague, grounding=_mwtcb_grounding(), formula_id="PAS", validation=v)
    assert qa["answers"]["problem"] is False
    assert "problem" in qa["gaps"]
    assert qa["clear"] is False


def test_stealth_preserves_problem_but_bans_anatomy():
    # Sensitive product: ego/confidence problem preserved, no explicit anatomy.
    g = _mwtcb_grounding(is_stealth=True)
    g.buyer_persona.pains = ["keyakinan diri menurun", "tekanan perbandingan"]
    ok = {
        "angle": "keyakinan", "hook": "Rasa kurang yakin depan pasangan?",
        "subhook": "Tekanan perbandingan boleh menghakis maruah seorang lelaki.",
        "usp_set": ["botol kecil mudah dibawa", "guna diskret dalam rutin harian"],
        "cta": "Cuba simpan satu dalam beg. Klik untuk dapatkan.",
    }
    r = validate_formula_copy("PESTA", ok, grounding=g)
    assert not any(v["code"] == "OVERCLAIM" for v in r["violations"])
    assert not any(v["code"] == "NO_PROBLEM_IDENTIFIED" for v in r["violations"])
    explicit = {**ok, "hook": "Masalah mati pucuk dan zakar lemah?"}
    r2 = validate_formula_copy("PESTA", explicit, grounding=g)
    assert any(v["code"] == "OVERCLAIM" for v in r2["violations"])
