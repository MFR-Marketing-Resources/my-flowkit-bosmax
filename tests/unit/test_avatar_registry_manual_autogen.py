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
