"""Scene-context registry — manual single-row add + AI auto-generate support.

Mirror of the avatar manual/autogen contract:
- add_scene() adds ONE row through the fail-closed sync door (no CSV upload) and
  rejects a duplicate SceneCode;
- next_scene_code() emits SCN_{SLUG} (+ _NN when the base already exists);
- find_duplicate_scene() detects a same-name / identical-background scene;
- build_scene_prompt_v1() is a clean empty-plate prompt (no people/product, no
  rendered text).

The bridge (_BRIDGE_FILE) and pool (_POOL_FILE) are redirected to a tmp copy of
the real seed so add_scene never mutates the committed data/ bridge.
"""
from __future__ import annotations

import shutil

import pytest

from agent.services import scene_context_registry as scr


@pytest.fixture
def tmp_pool(tmp_path, monkeypatch):
    seed = tmp_path / "SCENE_CONTEXT_POOL.csv"
    shutil.copyfile(scr._POOL_FILE, seed)
    bridge = tmp_path / "bridge" / "SCENE_CONTEXT_POOL.csv"
    monkeypatch.setattr(scr, "_POOL_FILE", seed)
    monkeypatch.setattr(scr, "_BRIDGE_FILE", bridge)
    scr.reload_pool()
    yield tmp_path
    scr._load_pool.cache_clear()


def _sample_row(code: str, name: str = "Neon Arcade Lobby") -> dict:
    return {
        "SceneName": name,
        "SceneCode": code,
        "BackgroundPrompt": "Background: glowing neon arcade lobby, retro cabinets",
        "RouteFit": "IMAGE+VIDEO_SUPPORT",
        "PromptV1": scr.build_scene_prompt_v1(name, "glowing neon arcade lobby"),
        "approved_flag": "TRUE",
        "usage_tags": "test|neon",
    }


def test_add_scene_single_row_add(tmp_pool):
    before = len(scr.list_pool())
    result = scr.add_scene(_sample_row("SCN_NEON_ARCADE_LOBBY"))
    assert result["rows"] == before + 1
    codes = {p["scene_code"] for p in scr.list_pool()}
    assert "SCN_NEON_ARCADE_LOBBY" in codes
    assert scr._BRIDGE_FILE.exists()  # written through the sync door


def test_add_scene_duplicate_code_fails_closed(tmp_pool):
    scr.add_scene(_sample_row("SCN_NEON_ARCADE_LOBBY"))
    with pytest.raises(ValueError, match="(?i)SCENE_CODE_EXISTS:scn_neon_arcade_lobby"):
        scr.add_scene(_sample_row("scn_neon_arcade_lobby"))  # case-insensitive


def test_next_scene_code_slug_and_nn(tmp_pool):
    fresh = scr.next_scene_code("Neon Arcade Lobby")
    assert fresh == "SCN_NEON_ARCADE_LOBBY"
    # a seeded scene name → base exists → _NN appended
    dup_base = scr.next_scene_code("Raya Kampung")
    assert dup_base == "SCN_RAYA_KAMPUNG_02"
    with pytest.raises(ValueError, match="SCENE_NAME_EMPTY"):
        scr.next_scene_code("   ")


def test_find_duplicate_scene_by_name_and_background(tmp_pool):
    # matches by normalized scene_name (case/space-insensitive)
    dup = scr.find_duplicate_scene("  raya   KAMPUNG ", "unrelated background")
    assert dup is not None and dup["scene_code"] == "SCN_RAYA_KAMPUNG"
    # a genuinely distinct scene is NOT a duplicate
    assert scr.find_duplicate_scene(
        "Neon Arcade Lobby", "glowing neon arcade lobby") is None


def test_build_scene_prompt_v1_is_clean_empty_plate():
    prompt = scr.build_scene_prompt_v1(
        "Neon Arcade", "Background: glowing neon arcade with retro cabinets")
    low = prompt.lower()
    assert prompt.startswith("Create a photorealistic empty background scene")
    assert "scene: neon arcade" in low
    assert "no people and no product" in low
    assert "no rendered text" in low
    assert "clean" in low
    # the leading "Background:" label is stripped from the embedded description
    assert "scene: neon arcade. glowing neon arcade" in low
