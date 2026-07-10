"""Template contract + render manifest + deterministic QA (POSTER_BUILDER_V2)."""
import pytest

from agent.models.poster_render_manifest import (
    PosterRenderReport,
    ZoneRenderResult,
    build_qa_report,
)
from agent.services import poster_recipe_service
from agent.services.poster_template_service import (
    PosterTemplateError,
    build_render_manifest,
    template_contract,
    template_version,
)

_COPY = {
    "poster_copy_set_id": "pcs-1",
    "version": 3,
    "primary_message": "Minyak warisan keluarga",
    "support_message": "Sedia bila anda perlukan.",
    "proof_points": ["Saiz poket", "Mudah dibawa"],
    "cta": "Beli sekarang",
    "disclaimer": "Untuk kegunaan luaran sahaja.",
    "language": "ms",
    "ai_model": "prov:model-x",
    "prompt_version": "poster-copy-ai-v1",
}


def test_every_launch_recipe_has_a_production_template_contract():
    """All six archetypes must carry tokens + a product-safe region that no
    text zone intersects (validated inside template_contract/build)."""
    recipes = poster_recipe_service.list_recipes()
    assert len(recipes) == 6
    for r in recipes:
        contract = template_contract(r.recipe_id)
        safe = contract["product_safe_region"]
        assert {"x", "y", "w", "h"} <= set(safe)
        assert contract["font_tokens"]["display"]["size"] > 0
        assert contract["component_styles"]["cta_button"]
        # No authored zone intersects the product region (by construction).
        for z in r.zones:
            no_overlap = (
                z.x + z.w <= safe["x"]
                or safe["x"] + safe["w"] <= z.x
                or z.y + z.h <= safe["y"]
                or safe["y"] + safe["h"] <= z.y
            )
            assert no_overlap, f"{r.recipe_id}/{z.zone_id} overlaps product region"


def test_unknown_recipe_fails_closed():
    with pytest.raises(PosterTemplateError) as exc:
        template_contract("does_not_exist")
    assert exc.value.code == "POSTER_RECIPE_UNKNOWN"


def test_manifest_carries_exact_strings_components_and_provenance():
    manifest = build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=_COPY,
        background_media_id="media-123",
        background_local_path="C:/tmp/bg.png",
        image_model="NANO_BANANA_PRO",
    )
    by_id = {z.zone_id: z for z in manifest.zones}
    # Exact strings preserved (deterministic-text acceptance criterion).
    assert by_id["headline"].text == _COPY["primary_message"]
    assert by_id["support"].text == _COPY["support_message"]
    assert by_id["chip_1"].text == "Saiz poket"
    assert by_id["cta"].text == "Beli sekarang"
    assert by_id["disclaimer"].text == _COPY["disclaimer"]
    # Component mapping: chips are pills, CTA is a button.
    assert by_id["chip_1"].component == "chip"
    assert by_id["cta"].component == "cta_button"
    assert by_id["headline"].component == "text"
    # Provenance chain for reconstruction.
    prov = manifest.provenance
    assert prov.poster_copy_set_id == "pcs-1"
    assert prov.poster_copy_set_version == 3
    assert prov.recipe_id == "product_hero_night_routine"
    assert prov.template_version == template_version()
    assert prov.image_model == "NANO_BANANA_PRO"
    # Composition strategy V1 default.
    assert manifest.product_layer.strategy == "REFERENCE_CONDITIONED"


def test_manifest_drops_empty_zones_and_requires_copy():
    sparse = dict(_COPY, support_message="", proof_points=[], disclaimer="")
    manifest = build_render_manifest(
        recipe_id="product_hero_night_routine",
        copy_set=sparse,
        background_local_path="C:/tmp/bg.png",
    )
    ids = {z.zone_id for z in manifest.zones}
    assert ids == {"headline", "cta"}  # no placeholder text in production posters
    with pytest.raises(PosterTemplateError) as exc:
        build_render_manifest(
            recipe_id="product_hero_night_routine",
            copy_set={"primary_message": "", "cta": ""},
            background_local_path="C:/tmp/bg.png",
        )
    assert exc.value.code == "POSTER_MANIFEST_NO_COPY"


def _zone(zone_id, *, fitted=True, overlaps=False, scale=1.0):
    return ZoneRenderResult(
        zone_id=zone_id, fitted=fitted, overflowed=not fitted,
        overlaps_product=overlaps, font_scale=scale,
    )


def _report(zones, *, w=1080, h=1920, errors=None):
    return PosterRenderReport(
        renderer="HTML_CHROMIUM_SERVICE_V1",
        canvas={"w": 1080, "h": 1920},
        output_png={"width": w, "height": h},
        zones=zones,
        errors=errors or [],
        ok=not errors,
    )


def test_qa_blocks_overflow_overlap_missing_and_bad_dimensions():
    report = _report(
        [
            _zone("headline", fitted=False),
            _zone("cta", overlaps=True),
        ],
        w=1000,
    )
    qa = build_qa_report(report, expected_zone_ids=["headline", "cta", "chip_1"])
    codes = {f.code for f in qa.findings if f.severity == "BLOCK"}
    assert {
        "TEXT_OVERFLOW",
        "PRODUCT_REGION_OVERLAP",
        "MISSING_RENDERED_ELEMENT",
        "OUTPUT_DIMENSIONS_INVALID",
    } <= codes
    assert qa.ok is False


def test_qa_warns_on_dense_copy_and_passes_clean_render():
    qa = build_qa_report(
        _report([_zone("headline", scale=0.8), _zone("cta")]),
        expected_zone_ids=["headline", "cta"],
    )
    assert qa.ok is True
    assert qa.block_count == 0
    assert [f.code for f in qa.findings] == ["DENSE_COPY_SCALED"]


def test_qa_blocks_render_failure():
    qa = build_qa_report(
        _report([], errors=["render failed: boom"]),
        expected_zone_ids=[],
    )
    assert qa.ok is False
    assert any(f.code == "RENDER_FAILURE" for f in qa.findings)
