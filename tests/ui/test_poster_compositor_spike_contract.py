"""Phase 2A poster-compositor spike — contract test (text/JSON parse).

Follows the repo's UI-contract convention (parse source + emitted artifacts, do
NOT launch a browser inside pytest). Proves the spike's invariants and that its
recorded run produced a 1080x1920 poster with every overlay zone fitted and clear
of the product hero region, with zero credit spend / no network.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPIKE = ROOT / "scripts" / "poster-compositor-spike.js"
FIXTURES = ROOT / "scripts" / "fixtures" / "poster-compositor"
OVERLAY = FIXTURES / "sample_overlay_spec.json"
SAFE = FIXTURES / "sample_product_safe_region.json"
ZONES = FIXTURES / "rendered_zones.json"

CANVAS_W, CANVAS_H = 1080, 1920


def test_spike_source_enforces_invariants():
    src = SPIKE.read_text(encoding="utf-8")
    # Fixed 1080x1920 canvas.
    assert "w: 1080" in src and "h: 1920" in src
    # Product-safe-region overlap invariant is checked and fails loudly.
    assert "overlaps_product" in src
    assert "overlap product_safe_region" in src
    # Renderer is Playwright/Chromium (production-intended engine), not html2canvas.
    assert "require(\"playwright\")" in src
    assert "html2canvas" not in src


def test_spike_is_credit_free_and_offline():
    src = SPIKE.read_text(encoding="utf-8")
    # No network / no generation lane / no credit spend from the spike.
    for banned in (
        "fetch(",
        'require("http',
        "/api/flow/generate",
        "start_generate",
        "startImgGeneration",
        "http://",
        "https://",
    ):
        assert banned not in src, f"spike must be offline/credit-free: found {banned}"


def test_fixtures_are_valid():
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    assert overlay["zones"], "overlay_spec has no zones"
    for z in overlay["zones"]:
        for k in ("zone_id", "role", "x", "y", "w", "h", "font_role", "text"):
            assert k in z, f"zone missing {k}"
    safe = json.loads(SAFE.read_text(encoding="utf-8"))["product_safe_region"]
    assert {"x", "y", "w", "h"} <= set(safe)


def test_recorded_render_meets_acceptance():
    report = json.loads(ZONES.read_text(encoding="utf-8"))
    assert report["renderer"].startswith("HTML_CHROMIUM")
    assert report["canvas"] == {"w": CANVAS_W, "h": CANVAS_H}
    # 1080x1920 export.
    assert report["output_png"]["width"] == CANVAS_W
    assert report["output_png"]["height"] == CANVAS_H
    # Credit-free + offline recorded.
    assert report["credit_spend"] is False
    assert report["network"] is False
    # Every zone fitted (no overflow) AND clear of the product hero region.
    assert report["zones"], "no zones recorded"
    for z in report["zones"]:
        assert z["fitted"] is True, f"{z['zone_id']} overflowed"
        assert z["overflowed"] is False
        assert z["overlaps_product"] is False, f"{z['zone_id']} covers the product"


def test_overlay_zones_do_not_overlap_product_region_by_construction():
    # Independent (of the recorded run) geometric check on the authored fixtures.
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
    safe = json.loads(SAFE.read_text(encoding="utf-8"))["product_safe_region"]

    def intersects(a, b):
        return not (
            a["x"] + a["w"] <= b["x"]
            or b["x"] + b["w"] <= a["x"]
            or a["y"] + a["h"] <= b["y"]
            or b["y"] + b["h"] <= a["y"]
        )

    for z in overlay["zones"]:
        rect = {"x": z["x"], "y": z["y"], "w": z["w"], "h": z["h"]}
        assert not intersects(rect, safe), f"{z['zone_id']} overlaps product_safe_region"
