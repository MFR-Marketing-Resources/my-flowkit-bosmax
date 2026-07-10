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
REAL_PRODUCT_PROOF = ROOT / "scripts" / "generate_real_product_poster_proof.py"
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


def test_renderer_fails_closed_on_missing_fonts_and_declares_scope():
    """Repair PR: font determinism is HOST-SCOPED and fail-closed — the renderer
    must verify every named primary family via document.fonts.check() and fail
    with FONT_UNAVAILABLE instead of silently substituting a fallback font.
    (Runtime failure-path proof: real-products evidence run renders a bogus-font
    manifest and records the FONT_UNAVAILABLE exit.)"""
    src = RENDERER.read_text(encoding="utf-8")
    assert "document.fonts.check" in src
    # FontFaceSet.check returns true for an unknown family when a fallback can
    # render the text; the renderer needs an explicit metric-comparison guard.
    assert "fontFamilyLooksAvailable" in src
    assert "FONT_UNAVAILABLE" in src
    assert "HOST_SCOPED" in src
    # The claim language must be scoped: no cross-host determinism claim.
    assert "HOST-SCOPED determinism" in src


def test_qa_overlap_message_does_not_claim_product_detection():
    """PRODUCT_REGION_OVERLAP is an author-defined-geometry check; the finding
    text must say so instead of implying the actual product was detected."""
    model_src = (ROOT / "agent" / "models" / "poster_render_manifest.py").read_text(
        encoding="utf-8"
    )
    assert "AUTHOR-DEFINED" in model_src
    assert "NOT" in model_src and "detected" in model_src


def test_real_product_proof_targets_required_serum_and_warisan_assets():
    """The proof lane must use the requested real products, never a substitute."""
    src = REAL_PRODUCT_PROOF.read_text(encoding="utf-8")
    # The documented `python scripts/...` invocation must resolve `agent`.
    assert "sys.path.insert(0, str(ROOT))" in src
    # The isolated FLOW_AGENT_DIR must contain the renderer resolved by the
    # compositor service; it must not silently use the shared runtime.
    assert "scratch / \"scripts\" / \"poster-compositor-render.js\"" in src
    # The proof command must return zero on a Windows legacy console.
    assert "real-product runs →" not in src
    assert "Minyak Warisan Tok Cap Burung 25ml" in src
    assert "BOSMAX Serum 5 ML" in src
    assert "90349f8c-9e14-4efe-988e-76ec60ea31f4.png" in src
    assert "Bosmax Oil 10 ML" not in src
    assert ".qa_report.json" in src
    assert ".product_truth_review.json" in src
