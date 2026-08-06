"""Unit tests for the Creative Recipe generator (deterministic, no DB / no AI).

Proves the coherent-tuple core end-to-end against the REAL committed authority files
(the 7-row scene->variation->camera bridge + the camera block_content_mapping), so the
test fails if either authority drifts out of alignment.
"""

from agent.services import creative_recipe_service as recipe


def _scene(template_id: str, variant: str) -> dict:
    return {"template_id": template_id, "variant": variant, "cluster": "Food & Beverage"}


def test_variation_of_parses_number_else_none():
    assert recipe.variation_of("Variation 1 - Holding & Presenting") == 1
    assert recipe.variation_of("Variation 7 - Demonstrating Benefits") == 7
    assert recipe.variation_of("no variation here") is None
    assert recipe.variation_of("") is None


def test_camera_follows_scene_via_real_bridge():
    """Camera is DERIVED from the scene Variation through the committed authorities."""
    bridge = recipe.load_bridge()
    mapping = recipe.load_camera_mapping()
    index = recipe._camera_index(mapping)
    # Var1 Holding & Presenting -> Body/Product Demo -> BODY_A
    assert recipe.camera_for_variation(1, bridge, index)["camera_preset_code"] == "BODY_A"
    # Var5 Close-up Details -> Body/Ingredient Highlight -> BODY_B
    assert recipe.camera_for_variation(5, bridge, index)["camera_preset_code"] == "BODY_B"
    # Var7 Demonstrating Benefits -> CTA/Result Showcase -> CTA_B
    assert recipe.camera_for_variation(7, bridge, index)["camera_preset_code"] == "CTA_B"


def test_build_recipes_is_a_coherent_grid_with_scene_derived_camera():
    bridge = recipe.load_bridge()
    mapping = recipe.load_camera_mapping()
    avatars = ["BOS_F_AINA_01", "BOS_F_FARAH_01"]
    scenes = [
        _scene("SCN-FNB-01", "Variation 1 - Holding & Presenting Food"),
        _scene("SCN-FNB-05", "Variation 5 - Close-up Product Details"),
        _scene("SCN-FNB-07", "Variation 7 - Demonstrating Benefits"),
    ]
    recipes = recipe.build_recipes(avatars, scenes, bridge, mapping)
    # 2 avatars x 3 scenes = 6 coherent tuples
    assert len(recipes) == 6
    # Camera FOLLOWS scene: the same scene yields the same camera for every avatar.
    by_scene = {}
    for r in recipes:
        by_scene.setdefault(r.scene_template_id, set()).add(r.camera_preset_code)
    assert by_scene["SCN-FNB-01"] == {"BODY_A"}
    assert by_scene["SCN-FNB-05"] == {"BODY_B"}
    assert by_scene["SCN-FNB-07"] == {"CTA_B"}
    # Every recipe carries a real (non-empty) camera — no incoherent blank.
    assert all(r.camera_preset_code for r in recipes)


def test_unparseable_variant_falls_back_not_crashes():
    bridge = recipe.load_bridge()
    mapping = recipe.load_camera_mapping()
    recipes = recipe.build_recipes(
        ["BOS_F_AINA_01"], [_scene("SCN-X-99", "freeform label no number")], bridge, mapping
    )
    assert len(recipes) == 1
    # Fallback = Body/Product Demo -> BODY_A
    assert recipes[0].variation is None
    assert recipes[0].camera_preset_code == "BODY_A"


def test_blank_avatar_or_scene_is_skipped():
    bridge = recipe.load_bridge()
    mapping = recipe.load_camera_mapping()
    recipes = recipe.build_recipes(
        ["", "BOS_F_AINA_01"],
        [{"template_id": "", "variant": "Variation 1"}, _scene("SCN-A-01", "Variation 1 - X")],
        bridge,
        mapping,
    )
    assert len(recipes) == 1
    assert recipes[0].avatar_code == "BOS_F_AINA_01"
    assert recipes[0].scene_template_id == "SCN-A-01"


def test_pretick_is_diverse_and_capped():
    bridge = recipe.load_bridge()
    mapping = recipe.load_camera_mapping()
    avatars = ["A1", "A2", "A3"]
    scenes = [_scene(f"SCN-{v}", f"Variation {v} - X") for v in range(1, 7)]  # Var1..6
    recipes = recipe.build_recipes(avatars, scenes, bridge, mapping)
    assert len(recipes) == 18  # 3 avatars x 6 scenes
    pretick = recipe.pretick_recipes(recipes, avatar_cap=2, variation_cap=4)
    # avatar cap: only the first 2 avatars appear
    assert {r.avatar_code for r in pretick} == {"A1", "A2"}
    for avatar in ("A1", "A2"):
        variations = [r.variation for r in pretick if r.avatar_code == avatar]
        assert len(variations) == 4
        assert len(set(variations)) == 4  # distinct, not repeated
        # arc spread: spans the FULL range (includes first Var1 and last Var6),
        # not clustered at the start
        assert min(variations) == 1
        assert max(variations) == 6
    assert len(pretick) == 8
