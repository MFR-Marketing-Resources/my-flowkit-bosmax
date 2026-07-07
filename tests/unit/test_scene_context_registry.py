"""Scene-context registry service proofs (mirror of the avatar registry contract).

Guards: the 20 seeded scene contexts load, resolve deterministically, expose only
sanitized public fields, keep PromptV1 server-side, and stay CLEAN (no baked text)
so a generated scene image is a usable background plate.
"""
import pytest

from agent.services import scene_context_registry as scr


def test_pool_loads_20_seeded_scenes():
    pool = scr.list_pool()
    assert len(pool) == 20
    codes = {p["scene_code"] for p in pool}
    assert "SCN_RAYA_KAMPUNG" in codes
    assert "SCN_WHITE_STUDIO_BERSIH" in codes
    # public view exposes only normalized fields — never PromptV1 / raw row
    for p in pool:
        assert set(p.keys()) == {
            "scene_code", "scene_name", "background_prompt", "route_fit", "usage_tags"
        }
        assert p["scene_code"] and p["scene_name"] and p["background_prompt"]


def test_background_prose_is_verbatim_background():
    scene = scr.resolve_scene_context("SCN_PANTAI_SUNSET")
    prose = scr.scene_background_prose(scene)
    assert prose.startswith("Background:")
    assert "beach" in prose.lower()


def test_resolve_by_code_and_deterministic_seed():
    a = scr.resolve_scene_context("SCN_CAFE_MINIMALIS_MODEN")
    assert a["scene_name"] == "Cafe Minimalis Moden"
    # deterministic: same seed → same scene, every call
    r1 = scr.resolve_scene_context(usage_context="kampung", seed="prod-xyz")
    r2 = scr.resolve_scene_context(usage_context="kampung", seed="prod-xyz")
    assert r1["scene_code"] == r2["scene_code"]
    assert "kampung" in " ".join(r1["usage_tags"]).lower() or "kampung" in r1["scene_name"].lower()


def test_unknown_scene_code_fails_closed():
    with pytest.raises(ValueError, match="SCENE_NOT_FOUND"):
        scr.resolve_scene_context("SCN_DOES_NOT_EXIST")


def test_generation_prompt_is_server_side_and_clean_no_text():
    gp = scr.get_generation_prompt("SCN_DAPUR_MODEN_OPEN_PLAN")
    assert gp["scene_code"] == "SCN_DAPUR_MODEN_OPEN_PLAN"
    prompt = gp["prompt"].lower()
    # clean background plate: no people, no product, no baked text
    assert "no rendered text" in prompt
    assert "no people and no product" in prompt
    assert "clean" in prompt


def test_sync_validation_fail_closed():
    # missing required columns
    with pytest.raises(ValueError, match="SCENE_REGISTRY_COLUMNS_MISSING"):
        scr.sync_pool_csv(b"Foo,Bar\n1,2\n")
    # empty
    with pytest.raises(ValueError, match="SCENE_REGISTRY_EMPTY"):
        scr.sync_pool_csv(b"SceneName,SceneCode,BackgroundPrompt,PromptV1\n")
    # a CSV missing PromptV1 fails closed at sync (not silently at generate time)
    with pytest.raises(ValueError, match="SCENE_REGISTRY_COLUMNS_MISSING"):
        scr.sync_pool_csv(b"SceneName,SceneCode,BackgroundPrompt\nA,SCN_A,Background: x\n")


def test_route_fit_carried_from_seed():
    scene = scr.resolve_scene_context("SCN_RAYA_KAMPUNG")
    assert "IMAGE+VIDEO_SUPPORT" in scene["route_fit"]
    assert "VIDEO+IMAGE_REFERENCE" in scene["route_fit"]
