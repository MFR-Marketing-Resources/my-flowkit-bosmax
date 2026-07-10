"""Production compositor service — contract test (source + fixtures parse; no
browser inside pytest, per repo UI-contract convention).

The REAL render path is proven by the committed per-archetype fixture reports in
scripts/fixtures/poster-compositor/archetypes/ (regenerated offline by
scripts/generate_poster_fixtures.py — zero credits, zero network).
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RENDERER = ROOT / "scripts" / "poster-compositor-render.js"
FIXGEN = ROOT / "scripts" / "generate_poster_fixtures.py"
ARCHETYPE_FIXTURES = ROOT / "scripts" / "fixtures" / "poster-compositor" / "archetypes"

EXPECTED_RECIPES = (
    "product_hero_night_routine",
    "product_scale_portability",
    "heritage_infographic",
    "routine_use",
    "offer_promo",
    "problem_aware_safe",
)


def test_renderer_source_enforces_production_invariants():
    src = RENDERER.read_text(encoding="utf-8")
    # Manifest-driven, versioned contract.
    assert "poster-render-manifest-v1" in src
    # Shrink-to-fit text fitting exists (not just overflow detection).
    assert "min_scale" in src and "font_scale" in src
    # Component rendering: chips + CTA button + disclaimer.
    for component in ("chip", "cta_button", "disclaimer"):
        assert component in src, f"renderer must style {component}"
    # Product-safe-region invariant + missing-element reporting.
    assert "overlaps_product" in src and "missing_zones" in src
    # Watchdog + structured exit codes + browser cleanup on ALL paths.
    assert "watchdog" in src and "browser.close()" in src
    # Renderer is Playwright/Chromium.
    assert 'require("playwright")' in src


def test_renderer_is_offline_and_credit_free():
    src = RENDERER.read_text(encoding="utf-8")
    for banned in (
        "fetch(",
        'require("http',
        "/api/flow/generate",
        "start_generate",
        "startImgGeneration",
        "http://",
        "https://",
    ):
        assert banned not in src, f"renderer must be offline/credit-free: {banned}"


def test_every_launch_archetype_has_a_recorded_production_fixture():
    """Per-archetype visual fixtures: committed machine-checkable proof that each
    launch recipe renders 1080x1920 with every zone fitted, styled and clear of
    the product region. (PNGs are regenerated locally; reports are committed.)"""
    for recipe_id in EXPECTED_RECIPES:
        report_path = ARCHETYPE_FIXTURES / f"{recipe_id}.render_report.json"
        assert report_path.exists(), f"missing fixture report for {recipe_id}"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["renderer"].startswith("HTML_CHROMIUM_SERVICE"), recipe_id
        assert report["output_png"]["width"] == 1080
        assert report["output_png"]["height"] == 1920
        assert report["credit_spend"] is False
        assert report["network"] is False
        assert report["zones"], f"{recipe_id} rendered no zones"
        assert report["missing_zones"] == []
        for z in report["zones"]:
            assert z["fitted"] is True, f"{recipe_id}/{z['zone_id']} overflowed"
            assert z["overlaps_product"] is False, (
                f"{recipe_id}/{z['zone_id']} covers the product region"
            )
        assert report["ok"] is True


def test_fixture_generator_is_offline():
    src = FIXGEN.read_text(encoding="utf-8")
    for banned in ("/api/flow/generate", "start_generate", "http://", "https://"):
        assert banned not in src
