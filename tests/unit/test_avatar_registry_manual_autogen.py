"""Avatar registry — manual single-row add + AI auto-generate support.

Proves the additive service layer for "manual add + AI auto-generate":
- add_avatar() adds ONE row through the fail-closed sync door (no CSV upload)
  and rejects a duplicate AvatarCode;
- next_avatar_code() emits a canonical BOS_{F|M}_{SLUG}_{NN} code;
- find_duplicate_avatar() detects a same-descriptor avatar (redundancy gate);
- build_avatar_prompt_v1() mirrors the seed PromptV1 format (Identity/Code/skin/
  hair) and adds the hijab styling when requested.

The bridge (_BRIDGE_FILE) and pool (_POOL_FILE) are redirected to a tmp copy of
the real seed so add_avatar never mutates the committed data/ bridge.
"""
from __future__ import annotations

import re
import shutil

import pytest

from agent.services import avatar_registry as ar


@pytest.fixture
def tmp_pool(tmp_path, monkeypatch):
    """Point the registry at an isolated tmp copy of the seed pool.

    add_avatar() writes _BRIDGE_FILE and reloads the cache; redirecting both the
    seed and the bridge into tmp keeps the real committed CSV/bridge untouched.
    """
    seed = tmp_path / "AVATAR_POOL_NORMALIZED.csv"
    shutil.copyfile(ar._POOL_FILE, seed)
    bridge = tmp_path / "bridge" / "AVATAR_POOL_NORMALIZED.csv"
    monkeypatch.setattr(ar, "_POOL_FILE", seed)
    monkeypatch.setattr(ar, "_BRIDGE_FILE", bridge)
    ar.reload_pool()
    yield tmp_path
    ar._load_pool.cache_clear()


def _sample_row(code: str) -> dict:
    return {
        "CharacterName": "Testina",
        "AvatarCode": code,
        "SkinTone": "Deep dark",
        "HairStyle": "Long wavy",
        "Wardrobe": "Neon streetwear",
        "Expression": "Confident",
        "PromptV1": "Create a photorealistic avatar reference image. Identity: "
                    f"Testina, Code: {code}. Demographic: Female.",
        "approved_flag": "TRUE",
        "usage_tags": "test|ugc",
    }


def test_add_avatar_single_row_add(tmp_pool):
    before = len(ar.list_pool())
    result = ar.add_avatar(_sample_row("BOS_F_TESTINA_NEON_99"))
    assert result["rows"] == before + 1
    codes = {p["avatar_code"] for p in ar.list_pool()}
    assert "BOS_F_TESTINA_NEON_99" in codes
    assert ar._BRIDGE_FILE.exists()  # written through the sync door


def test_add_avatar_duplicate_code_fails_closed(tmp_pool):
    ar.add_avatar(_sample_row("BOS_F_TESTINA_NEON_99"))
    with pytest.raises(ValueError, match="(?i)AVATAR_CODE_EXISTS:bos_f_testina_neon_99"):
        ar.add_avatar(_sample_row("bos_f_testina_neon_99"))  # case-insensitive


def test_next_avatar_code_matches_canonical_regex(tmp_pool):
    code = ar.next_avatar_code("F", "Nadia Batik Blouse")
    assert re.match(r"^BOS_[FM]_[A-Z0-9]+(?:_[A-Z0-9]+)*_[0-9]{2,}$", code)
    assert code.startswith("BOS_F_NADIA_BATIK_BLOUSE_")
    # unknown gender fails closed
    with pytest.raises(ValueError, match="AVATAR_GENDER_INVALID"):
        ar.next_avatar_code("X", "Foo")


def test_next_avatar_code_increments_existing_prefix(tmp_pool):
    ar.add_avatar(_sample_row("BOS_F_ZARA_KEBAYA_01"))
    nxt = ar.next_avatar_code("F", "Zara Kebaya")
    assert nxt == "BOS_F_ZARA_KEBAYA_02"


def test_find_duplicate_avatar_detects_same_descriptor(tmp_pool):
    row = _sample_row("BOS_F_TESTINA_NEON_99")
    ar.add_avatar(row)
    dup = ar.find_duplicate_avatar(
        "Deep dark", "Long wavy", "Neon streetwear", "Confident", "F")
    assert dup is not None
    assert dup["avatar_code"] == "BOS_F_TESTINA_NEON_99"
    # a genuinely distinct descriptor is NOT a duplicate
    assert ar.find_duplicate_avatar(
        "Fair", "Short bob", "Formal suit", "Serious", "M") is None


def test_build_avatar_prompt_v1_mirrors_seed_and_flags_hijab():
    prompt = ar.build_avatar_prompt_v1({
        "CharacterName": "Nadia",
        "AvatarCode": "BOS_F_NADIA_01",
        "SkinTone": "Tan",
        "HairStyle": "Long straight",
        "Wardrobe": "Batik blouse",
        "Expression": "Warm smile",
        "hijab": True,
    })
    assert prompt.startswith("Create a photorealistic avatar reference image.")
    assert "Identity: Nadia" in prompt
    assert "Code: BOS_F_NADIA_01" in prompt
    assert "Skin tone: Tan" in prompt
    assert "Hair: Long straight" in prompt
    assert "hijab" in prompt.lower()
    assert "general audience and commercial use" in prompt
    assert "AVATAR REFERENCE FREE-HAND LAW" in prompt
    assert "empty and free" in prompt.lower()
    assert "no cup, bottle, phone" in prompt.lower()

    # no hijab → no hijab mention
    no_hijab = ar.build_avatar_prompt_v1({
        "CharacterName": "Amir",
        "AvatarCode": "BOS_M_AMIR_01",
        "SkinTone": "Medium",
        "HairStyle": "Short",
        "Wardrobe": "Polo shirt",
        "Expression": "Neutral",
        "hijab": False,
    })
    assert "hijab" not in no_hijab.lower()
    assert "AVATAR REFERENCE FREE-HAND LAW" in no_hijab


def test_get_generation_prompt_hardens_legacy_promptv1_with_free_hand_law(tmp_pool):
    """Existing CSV PromptV1 rows without free-hand law are protected at runtime."""
    legacy = (
        "Create a photorealistic avatar reference image. Identity: Legacy, "
        "Code: BOS_F_LEGACY_FREEHAND_01. Demographic: Female."
    )
    ar.add_avatar({
        "CharacterName": "Legacy",
        "AvatarCode": "BOS_F_LEGACY_FREEHAND_01",
        "SkinTone": "Deep dark",
        "HairStyle": "Long wavy",
        "Wardrobe": "Neon streetwear",
        "Expression": "Confident",
        "PromptV1": legacy,
        "approved_flag": "TRUE",
        "usage_tags": "test|ugc",
    })
    identity = ar.get_generation_prompt("BOS_F_LEGACY_FREEHAND_01")
    assert identity["prompt"].startswith(legacy)
    assert "AVATAR REFERENCE FREE-HAND LAW" in identity["prompt"]
    assert "empty and free" in identity["prompt"].lower()
    # Idempotent: already-hardened PromptV1 is not double-appended.
    hardened = ar._with_free_hand_law(identity["prompt"])
    assert hardened.count("AVATAR REFERENCE FREE-HAND LAW") == 1


def test_get_generation_prompt_pool_seed_includes_free_hand_law():
    identity = ar.get_generation_prompt("BOS_F_ALYA_01")
    assert "AVATAR REFERENCE FREE-HAND LAW" in identity["prompt"]
    assert "no cup, bottle, phone" in identity["prompt"].lower()


def test_delete_avatar_removes_row(tmp_pool):
    ar.add_avatar(_sample_row("BOS_F_TESTINA_NEON_99"))
    before = len(ar.list_pool())
    result = ar.delete_avatar("BOS_F_TESTINA_NEON_99")
    assert result["remaining"] == before - 1
    codes = {p["avatar_code"] for p in ar.list_pool()}
    assert "BOS_F_TESTINA_NEON_99" not in codes


def test_delete_avatar_case_insensitive(tmp_pool):
    ar.add_avatar(_sample_row("BOS_F_TESTINA_NEON_99"))
    ar.delete_avatar("bos_f_testina_neon_99")  # different case still matches
    assert "BOS_F_TESTINA_NEON_99" not in {p["avatar_code"] for p in ar.list_pool()}


def test_delete_avatar_unknown_code_fails_closed(tmp_pool):
    with pytest.raises(ValueError, match="(?i)AVATAR_CODE_NOT_FOUND"):
        ar.delete_avatar("BOS_F_DOES_NOT_EXIST_00")


# ── Standardization: controlled vocabulary + persona helpers ────────────────

def test_load_vocab_has_all_fields():
    ar._vocab_doc.cache_clear()
    ar.load_vocab.cache_clear()
    vocab = ar.load_vocab()
    for field in ("skin_tone", "hair_style", "wardrobe", "expression",
                  "environment", "lighting", "camera", "usage_tags"):
        assert vocab.get(field), f"missing vocab field {field}"
    assert "Tan SEA" in vocab["skin_tone"]
    assert "Waist-up" in vocab["camera"]
    assert "Close portrait" in vocab["camera"]
    assert "Close product hold" not in vocab["camera"]
    assert not any("product hold" in str(v).lower() for v in vocab["camera"])


def test_snap_to_vocab_case_insensitive():
    assert ar.snap_to_vocab("skin_tone", "tan sea") == "Tan SEA"
    assert ar.snap_to_vocab("wardrobe", "MODEST SPORTSWEAR") == "Modest sportswear"
    assert ar.snap_to_vocab("skin_tone", "neon purple") is None
    assert ar.snap_to_vocab("skin_tone", "") is None


def test_validate_descriptors_fail_closed():
    good = {
        "skin_tone": "Tan SEA", "hair_style": "Short neat",
        "wardrobe": "Smart office wear", "expression": "Calm neutral",
        "environment": "Modern office interior", "usage_tags": "UGC|office",
    }
    ar.validate_descriptors(good)  # no raise
    with pytest.raises(ValueError, match="AVATAR_VALUE_NOT_IN_VOCAB:wardrobe"):
        ar.validate_descriptors({**good, "wardrobe": "Batik kebaya"})
    with pytest.raises(ValueError, match="AVATAR_VALUE_NOT_IN_VOCAB:usage_tags"):
        ar.validate_descriptors({**good, "usage_tags": "raya"})
    with pytest.raises(ValueError, match="AVATAR_VALUE_NOT_IN_VOCAB:environment"):
        ar.validate_descriptors({**good, "environment": "Moon base"})


def test_personas_from_pool_are_clean_tokens(tmp_pool):
    personas = ar.personas_from_pool()
    assert personas  # non-empty
    # Every persona is a single clean alnum token (no descriptor-slug leaks, no NN).
    assert all("_" not in p and p.isalnum() for p in personas)


# ── Gender-aware vocabulary + gender-dependency validation ──────────────────

def test_gender_specific_fields_lists_wardrobe():
    assert "wardrobe" in ar.gender_specific_fields()


def test_vocab_for_gender_narrows_wardrobe_only():
    full = ar.load_vocab()
    f = ar.vocab_for_gender("F")
    m = ar.vocab_for_gender("M")
    # Shared fields are identical to the superset for both genders.
    assert f["skin_tone"] == full["skin_tone"]
    assert m["expression"] == full["expression"]
    # Wardrobe is gender-partitioned: baju kurung/modest = F only, baju melayu = M only.
    assert "Modern baju kurung" in f["wardrobe"]
    assert "Modest sportswear" in f["wardrobe"]
    assert "Baju melayu modern" not in f["wardrobe"]
    assert "Baju melayu modern" in m["wardrobe"]
    assert "Modern baju kurung" not in m["wardrobe"]
    # A shared wardrobe value is valid for both.
    assert "Smart office wear" in f["wardrobe"]
    assert "Smart office wear" in m["wardrobe"]


def test_snap_to_vocab_for_gender_rejects_off_gender():
    # Canonical-but-off-gender snaps to None (fail-closed), shared/on-gender pass.
    assert ar.snap_to_vocab_for_gender("wardrobe", "modern baju kurung", "F") == "Modern baju kurung"
    assert ar.snap_to_vocab_for_gender("wardrobe", "Modern baju kurung", "M") is None
    assert ar.snap_to_vocab_for_gender("wardrobe", "baju melayu modern", "M") == "Baju melayu modern"
    assert ar.snap_to_vocab_for_gender("wardrobe", "Baju melayu modern", "F") is None
    # A shared / non-gender field ignores gender.
    assert ar.snap_to_vocab_for_gender("skin_tone", "tan sea", "M") == "Tan SEA"


def test_personas_by_gender_split_from_pool_prefix(tmp_pool):
    buckets = ar.personas_by_gender()
    assert "AMIR" in buckets["M"] and "AMIR" not in buckets["F"]
    assert "ALYA" in buckets["F"] and "ALYA" not in buckets["M"]
    # No token appears in both buckets.
    assert not (set(buckets["F"]) & set(buckets["M"]))


def test_persona_gender_case_insensitive(tmp_pool):
    assert ar.persona_gender("amir") == "M"
    assert ar.persona_gender("Alya") == "F"
    assert ar.persona_gender("BrandNewPersona") is None  # not in pool → unconstrained
    assert ar.persona_gender("") is None


def test_validate_gender_compatibility_fail_closed(tmp_pool):
    base = {
        "character_name": "NewFace", "gender": "F", "hijab": False,
        "skin_tone": "Tan SEA", "hair_style": "Short neat",
        "wardrobe": "Smart office wear", "expression": "Calm neutral",
    }
    ar.validate_gender_compatibility(base)  # shared wardrobe, no persona → ok
    ar.validate_gender_compatibility({**base, "wardrobe": "Modern baju kurung"})  # F-only on F ok
    # hijab on a male
    with pytest.raises(ValueError, match="AVATAR_HIJAB_MALE_INVALID"):
        ar.validate_gender_compatibility({**base, "gender": "M", "hijab": True,
                                          "wardrobe": "Smart office wear"})
    # female-only wardrobe on a male
    with pytest.raises(ValueError, match="AVATAR_VALUE_NOT_FOR_GENDER:wardrobe"):
        ar.validate_gender_compatibility({**base, "gender": "M",
                                          "wardrobe": "Modern baju kurung"})
    # male-only wardrobe on a female
    with pytest.raises(ValueError, match="AVATAR_VALUE_NOT_FOR_GENDER:wardrobe"):
        ar.validate_gender_compatibility({**base, "wardrobe": "Baju melayu modern"})
    # existing male persona claimed as female
    with pytest.raises(ValueError, match="AVATAR_PERSONA_GENDER_MISMATCH"):
        ar.validate_gender_compatibility({**base, "character_name": "Amir"})
    # unknown gender
    with pytest.raises(ValueError, match="AVATAR_GENDER_INVALID"):
        ar.validate_gender_compatibility({**base, "gender": "X"})
