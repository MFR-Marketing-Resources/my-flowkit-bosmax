"""Unit tests for the poster/creative cockpit builder-settings SSOT service."""
from agent.services.img_asset_factory_service import build_image_gen_settings
from agent.services.poster_builder_settings_service import (
    PosterBuilderSettingsService,
)

DIMENSIONS = [
    "poster_objectives",
    "poster_types",
    "languages",
    "visual_routes",
    "human_presence_modes",
    "text_density_options",
]


def test_every_dimension_has_options_and_exactly_one_default():
    s = PosterBuilderSettingsService.build_settings()
    dump = s.model_dump()
    for dim in DIMENSIONS:
        opts = dump[dim]
        assert len(opts) >= 2, f"{dim} should offer choices"
        defaults = [o for o in opts if o["default"]]
        assert len(defaults) == 1, f"{dim} must have exactly one default"
        ids = [o["id"] for o in opts]
        assert len(ids) == len(set(ids)), f"{dim} ids must be unique"


def test_defaults_match_existing_draft_contract():
    """The seed defaults must equal today's draft defaults so the prompt-draft /
    copy-recommendation contract stays byte-identical."""
    s = PosterBuilderSettingsService.build_settings()

    def default_id(options):
        return next(o.id for o in options if o.default)

    assert default_id(s.poster_objectives) == "Product awareness"
    assert default_id(s.poster_types) == "Product-only hero poster"
    assert default_id(s.languages) == "ms"
    assert default_id(s.visual_routes) == "Premium commercial"
    assert default_id(s.human_presence_modes) == "No human / product-forward"
    assert default_id(s.text_density_options) == "medium"


def test_flow_mirror_is_composed_from_image_gen_ssot_not_duplicated():
    """Flow mirror values must come from build_image_gen_settings (the shared
    image-gen SSOT), not a hand-rolled copy."""
    igs = build_image_gen_settings()
    s = PosterBuilderSettingsService.build_settings()

    assert s.flow_mirror.aspect_ratios == igs["aspect_options"]
    assert s.flow_mirror.counts == igs["count_options"]
    assert [m.label for m in s.flow_mirror.image_models] == [
        m["label"] for m in igs["models"]
    ]
    assert s.flow_mirror.defaults.aspect_ratio == igs["default_aspect"]
    assert s.flow_mirror.defaults.count == igs["default_count"]
    assert s.flow_mirror.defaults.image_model == igs["default_model"]
    # required aspect ratio menu
    for ratio in ("9:16", "1:1", "16:9", "4:3", "3:4"):
        assert ratio in s.flow_mirror.aspect_ratios
    # repo default model present
    assert any(m.label == "Nano Banana 2" for m in s.flow_mirror.image_models)


def test_copy_components_and_routes_present():
    s = PosterBuilderSettingsService.build_settings()
    for route in ("DIRECT", "STEALTH", "REVIEW_REQUIRED"):
        assert route in s.copy_components.routes
    assert s.copy_components.copy_sets_scope == "product"


def test_ai_provider_summary_has_no_secrets():
    s = PosterBuilderSettingsService.build_settings()
    ai = s.ai_provider.model_dump()
    assert ai["lane"] == "text_assist"
    assert ai["status"] in ("configured", "unavailable")
    # no secret / key field is ever exposed
    for key in ai:
        assert "key" not in key.lower()
        assert "secret" not in key.lower()
        assert "token" not in key.lower()


def test_sources_tagged_for_cockpit_provenance():
    s = PosterBuilderSettingsService.build_settings()
    assert s.sources.get("flow_mirror") == "models.json"
    assert s.sources.get("poster_dimensions") == "config"
    assert s.sources.get("ai_provider") == "ai_provider"
