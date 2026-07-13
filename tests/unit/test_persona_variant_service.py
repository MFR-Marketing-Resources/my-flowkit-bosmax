"""Avatar Persona variants — composer/coherence/scanner contract tests."""
import pytest

from agent.services import persona_variant_service as svc
from agent.services.prompt_compiler_runtime_config_service import (
    PERSONA_REGISTRY,
    get_runtime_config,
    normalize_creator_persona,
)
from agent.services.production_prompt_approval_service import scan_prompt_text


def test_config_loads_with_expected_vocab():
    config = svc.load_config()
    assert config.schema_version == "persona-variants-v1"
    assert {g.id for g in config.genders} == {"F", "F_HIJAB", "M"}
    assert len(config.ethnicities) == 8
    assert len(config.age_ranges) == 4
    assert len(config.bundles) == 10
    assert len(config.seeds) >= 6


def test_composed_ids_are_deterministic_and_unique():
    entries = svc.load_composed_personas()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids))
    assert ids == [e["id"] for e in svc.load_composed_personas()]  # stable
    assert svc.compose_persona_id("f_hijab", "melayu", "30s", "kenduri") == (
        "AVX_F_HIJAB_MELAYU_30S_KENDURI"
    )


def test_bundle_coherence_wardrobe_matches_environment():
    # The coherence law: wardrobe never travels without its paired environment.
    config = svc.load_config()
    kenduri = next(b for b in config.bundles if b.id == "KENDURI")
    desc = svc.compose_visual_description(config, "F", "MELAYU", "30S", "KENDURI")
    assert "baju kurung" in desc
    assert kenduri.environment_en in desc
    # baju kurung can never appear with the jogging park environment
    jogging = next(b for b in config.bundles if b.id == "JOGGING")
    jog_desc = svc.compose_visual_description(config, "F", "MELAYU", "30S", "JOGGING")
    assert "baju kurung" not in jog_desc
    assert jogging.environment_en in jog_desc


def test_hijab_variant_carried_by_wardrobe():
    config = svc.load_config()
    hijab_desc = svc.compose_visual_description(config, "F_HIJAB", "MELAYU", "30S", "OFFICE")
    plain_desc = svc.compose_visual_description(config, "F", "MELAYU", "30S", "OFFICE")
    assert "hijab" in hijab_desc
    assert "hijab" not in plain_desc
    sports = svc.compose_visual_description(config, "F_HIJAB", "CINA", "20S", "JOGGING")
    assert "sports hijab" in sports


def test_invalid_combo_returns_none():
    config = svc.load_config()
    assert svc.compose_visual_description(config, "X", "MELAYU", "30S", "OFFICE") is None
    assert svc.compose_visual_description(config, "F", "MELAYU", "30S", "NOPE") is None


def test_registry_contains_base_seeds_and_composed():
    ids = {p["id"] for p in PERSONA_REGISTRY}
    assert "DEFAULT_CREATOR" in ids and "CONFIDENT_EXPLAINER" in ids
    assert "AVATAR_ALYA_OFFICE" in ids
    assert "AVX_M_INDIA_40S_CAFE" in ids
    # 2 base + 6 seeds + 3*8*4*10 composed
    assert len(PERSONA_REGISTRY) == 2 + 6 + 960


def test_normalize_accepts_variants_and_rejects_unknown():
    assert normalize_creator_persona("avatar_haris_office") == "AVATAR_HARIS_OFFICE"
    assert (
        normalize_creator_persona("avx_f_melayu_30s_kitchen")
        == "AVX_F_MELAYU_30S_KITCHEN"
    )
    with pytest.raises(ValueError):
        normalize_creator_persona("AVX_F_MELAYU_30S_JOGGINGPARK")


def test_every_visual_description_passes_policy_scanner():
    # Registry-wide gate: no persona text may trip the compile-time scanner.
    for persona in PERSONA_REGISTRY:
        description = persona.get("visual_description")
        if not description:
            continue
        scan = scan_prompt_text(description, product_id="prod-persona-test")
        assert not any(scan.values()), (persona["id"], scan)


def test_runtime_config_ships_ui_slice_and_composer():
    cfg = get_runtime_config()
    ui_ids = [p["id"] for p in cfg["persona_registry"]]
    assert "DEFAULT_CREATOR" in ui_ids
    assert "AVATAR_ALYA_OFFICE" in ui_ids
    assert not any(i.startswith("AVX_") for i in ui_ids)  # composed stay server-side
    composer = cfg["persona_composer"]
    assert composer["id_prefix"] == "AVX"
    assert len(composer["bundles"]) == 10
    assert composer["visual_template_en"]


def test_compiler_injects_composed_description():
    from agent.services.ugc_video_prompt_compiler_service import (
        _persona_visual_description,
    )

    text = _persona_visual_description("AVX_F_HIJAB_MELAYU_30S_KENDURI")
    assert "baju kurung with a matching hijab" in text
    assert _persona_visual_description("DEFAULT_CREATOR") == ""  # base unchanged
