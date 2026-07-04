"""Locks the Product Asset Generator hydration fix (audit HOLD item A):
the selector must NOT depend only on BOSMAX authority contexts. Catalog products
must populate productById and productOptions even when authority is empty, and a
selected product without an authority context must show explicit state, not null
silence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_hydration_builds_productById_from_catalog_union():
    src = _read("dashboard/src/components/prompt-tool/usePromptToolHydration.ts")
    # productById seeded from catalog products (not only authority contexts)
    assert "for (const product of state.products)" in src
    assert "productById[product.id] = product" in src
    # empty authority options array must still fall back to catalog products
    assert "authorityOptions && authorityOptions.length > 0" in src
    # explicit "does this product have an authority context" accessor exposed
    assert "hasAuthorityContext" in src


def test_form_shows_explicit_missing_authority_state():
    src = _read(
        "dashboard/src/components/product-asset-generator/ProductAssetGeneratorForm.tsx"
    )
    assert "selectedProductMissingAuthority" in src
    assert "hasAuthorityContext" in src
    assert "No BOSMAX authority context for this product" in src
