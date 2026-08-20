from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_faceless_ui_separates_copy_authority_from_opening_strategy():
    page = _read("dashboard/src/pages/FacelessVideoPage.tsx")
    card = _read("dashboard/src/components/copywriting/CopyArchitectureV2LaneCard.tsx")
    api = _read("dashboard/src/api/creativeLaneSettings.ts")

    assert 'title="Opening Strategy"' in page
    assert 'data-testid="faceless-opening-strategy"' in page
    assert 'data-testid="faceless-actor-profile"' in page
    assert 'data-wire-field="hook_id"' in page
    assert 'title="Hook & background"' not in page
    assert 'data-testid="copy-v2-approved-hook"' in card
    assert "projection.derived_copy" in card
    assert "Read-only projection from the production V2 binding" in card
    assert "opening_strategy" in api
    assert "actor_profile" in api
    assert "lane=FACELESS" in api
    assert "product_id" in api
    assert "execution_identity" in page


def test_faceless_ui_filters_background_from_product_context_and_preserves_flow_order():
    page = _read("dashboard/src/pages/FacelessVideoPage.tsx")
    card_position = page.index("<CopyArchitectureV2LaneCard")
    product_position = page.index('title="Product"')
    opening_position = page.index('title="Opening Strategy"')
    background_position = page.index('title="Background"')
    video_position = page.index('title="Video settings"')

    assert product_position < card_position < opening_position
    assert opening_position < background_position < video_position
    assert "settings.background.options.map" in page
    assert "useCreativeLaneSettings(selectedProduct?.id)" in page
    assert 'title="Generate video"' in page
    assert 'key={selectedProduct?.id ?? "none"}' in page
    assert "avatar selector" not in page.casefold()
