"""Regression lock: the canonical Product Detail page must always carry the four
owner-approved tabs and mount their panels. This is a SOURCE contract test (not a
pixel snapshot) so it runs in the backend pytest gate and structurally prevents a
future edit — or a stale runtime bundle built from such an edit — from dropping a
tab (the recurring "Visual / Canva missing" incident).
"""

from pathlib import Path

import pytest

_PDP = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "pages" / "ProductDetailPage.tsx"


@pytest.fixture(scope="module")
def source() -> str:
    assert _PDP.is_file(), f"ProductDetailPage.tsx not found at {_PDP}"
    return _PDP.read_text(encoding="utf-8")


def test_four_canonical_tabs_present(source):
    for label in ("Edit & Save", "Product Intelligence", "Creative Setup", "Visual / Canva"):
        assert label in source, f"canonical Product Detail tab missing: {label!r}"


def test_intelligence_panel_mounted(source):
    assert "ProductIntelligenceReviewDraftPanel" in source


def test_creative_setup_panel_mounted(source):
    assert "CreativeSetupPanel" in source


def test_visual_readiness_panel_mounted(source):
    assert "ProductVisualReadinessPanel" in source
