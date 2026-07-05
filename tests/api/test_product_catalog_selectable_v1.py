"""Issue #203 — BOSMAX / Minyak Warisan canonical products must be selectable
across operator modes.

Two defects are covered:

1. Discoverability. The operator product selector only client-filtered the first
   catalog page (`/api/products?limit=…`). Canonical MANUAL rows (BOSMAX Serum,
   Minyak Warisan Tok Cap Burung) sort after the FastMoss rows and fall outside
   that window, so a name search found nothing. The fix routes selector search
   through the full-catalog `/api/products/search` endpoint.

2. Readiness truthfulness. `get_product_package_readiness` collapsed the image
   gate so a fully-approved but image-less **T2V** product was wrongly reported
   blocked with a bogus ``NO_IMAGE_REQUIRED`` blocker instead of READY.

The tests are behavioural where cheap (pure functions / monkeypatched service
deps) and fall back to a live-agent probe for the end-to-end search proof,
matching the repo's existing catalog-test convention.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.api.products import _filter_products_for_catalog, _matches_catalog_query
from agent.services import approved_product_package_service as svc

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


# ── Readiness truthfulness — image gate must not block image-less modes ──────


def _approved_enriched(*, image_status: str, approved_modes, lifecycle: str = "ACTIVE"):
    """An enriched product row that has cleared claim-safe + production approval
    for the given modes. `image_status` controls the image cache state."""
    return {
        "id": "prod-1",
        "product_display_name": "Bosmax Herbs 5 ML",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "lifecycle_status": lifecycle,
        "image_readiness_status": image_status,
        "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
        "production_prompt_approved_modes": approved_modes,
    }


def _patch_readiness_deps(monkeypatch, enriched):
    async def fake_get_product(product_id: str):
        return {"id": product_id, "lifecycle_status": enriched.get("lifecycle_status", "ACTIVE")}

    async def fake_enrich(product, persist=False):
        return dict(enriched)

    async def fake_claim_safe(product_id: str):
        return {"claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED"}

    monkeypatch.setattr(svc.crud, "get_product", fake_get_product)
    monkeypatch.setattr(svc, "enrich_product", fake_enrich)
    monkeypatch.setattr(svc, "get_stored_claim_safe_package", fake_claim_safe)


async def test_readiness_t2v_ready_without_image(monkeypatch):
    """Regression: T2V never needs a product image. A fully-approved, image-less
    T2V product must report READY — not a NO_IMAGE_REQUIRED blocker."""
    enriched = _approved_enriched(image_status="LOCAL_CACHE_MISSING", approved_modes=["T2V", "IMG"])
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "T2V")

    assert result["readiness_status"] == "READY"
    assert result["blocker"] is None
    image_item = next(c for c in result["checklist"] if c["key"] == "image_reference")
    assert image_item["ready"] is True


async def test_readiness_f2v_blocked_start_frame_without_image(monkeypatch):
    """F2V still truthfully requires a start-frame image when the cache is gone."""
    enriched = _approved_enriched(image_status="LOCAL_CACHE_MISSING", approved_modes=["T2V", "IMG"])
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "F2V")

    assert result["readiness_status"] == "START_FRAME_REQUIRED"
    assert result["blocker"] == "START_FRAME_REQUIRED"


async def test_readiness_i2v_blocked_subject_without_image(monkeypatch):
    """I2V still truthfully requires a subject image when the cache is gone."""
    enriched = _approved_enriched(image_status="LOCAL_CACHE_MISSING", approved_modes=["T2V", "IMG"])
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "I2V")

    assert result["readiness_status"] == "SUBJECT_REQUIRED"
    assert result["blocker"] == "SUBJECT_REQUIRED"


async def test_readiness_img_ready_with_subject_fallback(monkeypatch):
    """IMG uses the prompt-subject fallback (product identity), so an approved
    product is READY even without a cached image."""
    enriched = _approved_enriched(image_status="LOCAL_CACHE_MISSING", approved_modes=["T2V", "IMG"])
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "IMG")

    assert result["readiness_status"] == "READY"
    assert result["blocker"] is None


async def test_readiness_f2v_ready_with_cached_image(monkeypatch):
    """Positive control: with a ready image cache, F2V clears the image gate."""
    enriched = _approved_enriched(image_status="IMAGE_CACHE_READY", approved_modes=["T2V", "IMG"])
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "F2V")

    assert result["readiness_status"] == "READY"
    assert result["blocker"] is None


async def test_readiness_still_blocks_when_not_production_approved(monkeypatch):
    """Guardrail: the fix must not weaken the production-approval gate."""
    enriched = _approved_enriched(image_status="IMAGE_CACHE_READY", approved_modes=[])
    enriched["production_prompt_approval_status"] = "PENDING"
    _patch_readiness_deps(monkeypatch, enriched)

    result = await svc.get_product_package_readiness("prod-1", "T2V")

    assert result["readiness_status"] == "PRODUCTION_APPROVAL_REQUIRED"


# ── Discoverability — search scans the full catalog, not the first page ──────


def _canonical(title: str, source: str = "MANUAL") -> dict:
    return {
        "id": title.lower().replace(" ", "-"),
        "raw_product_title": title,
        "product_display_name": title,
        "product_short_name": title,
        "source": source,
        "lifecycle_status": "ACTIVE",
    }


def test_search_filter_finds_product_beyond_first_page():
    """A canonical product that sorts far past the first 500-row window is still
    returned by the catalog query filter — the search is not page-limited."""
    filler = [_canonical(f"Unrelated Product {i}", source="FASTMOSS") for i in range(550)]
    target = _canonical("BOSMAX Serum 5ML")
    catalog = filler + [target]  # target at index 550, beyond a 500 window

    result = _filter_products_for_catalog(
        catalog,
        query="bosmax",
        source=None,
        source_lane=None,
        readiness=None,
    )

    assert any(p["id"] == target["id"] for p in result)


@pytest.mark.parametrize("term", ["bosmax", "serum", "warisan", "minyak", "cap burung"])
def test_search_filter_matches_target_terms(term: str):
    """Each of the operator search terms matches its canonical target row."""
    catalog = [
        _canonical("BOSMAX Serum 5ML"),
        _canonical("Minyak Warisan Tok Cap Burung 25ml", source="MANUAL"),
        _canonical("Unrelated FastMoss Cushion", source="FASTMOSS"),
    ]

    result = _filter_products_for_catalog(
        catalog,
        query=term,
        source=None,
        source_lane=None,
        readiness=None,
    )

    assert result, f"no product matched search term {term!r}"


# ── Search-only alias index — marketing synonyms find canonical rows ─────────


@pytest.mark.parametrize("term", ["serum", "bosmax serum", "herbal oil roll on"])
def test_search_alias_finds_bosmax_serum_row(term: str):
    """The BOSMAX HERBS 5ML roll-on (raw title "Bosmax Herbs 5 ML") carries no
    "serum" token in its identity fields, but the search-only alias index makes
    it findable by the marketing name the operator actually types."""
    product = _canonical("Bosmax Herbs 5 ML")
    assert _matches_catalog_query(product, term) is True


def test_search_alias_does_not_leak_to_unrelated_products():
    """The alias index must only widen the row it is keyed to — an unrelated
    product without "serum" in its own fields must not match "serum"."""
    unrelated = _canonical("Sumikko Baby Diaper Pants", source="FASTMOSS")
    assert _matches_catalog_query(unrelated, "serum") is False


def test_search_alias_does_not_affect_identity_fields():
    """Guardrail: aliases are search-only. The identity fields the prompt
    compiler reads (display_name / short_name / raw_product_title) are never
    mutated by the alias index."""
    product = _canonical("Bosmax Herbs 5 ML")
    assert product["product_display_name"] == "Bosmax Herbs 5 ML"
    assert product["product_short_name"] == "Bosmax Herbs 5 ML"


# ── Discoverability wiring — selector must use server-side search ────────────


def test_products_api_client_exports_search():
    src = _read("dashboard/src/api/products.ts")
    assert "searchProducts" in src
    assert "/api/products/search" in src


def test_selector_uses_server_side_search():
    """The selector must call the server-side search endpoint, not only filter
    the client-loaded array."""
    src = _read("dashboard/src/components/workspace/SearchableProductSelect.tsx")
    assert "searchProducts" in src
    assert "serverResults" in src


# ── Live end-to-end proof (skipped when the local agent is offline) ──────────


def _live_json(path: str):
    import urllib.request

    url = f"http://127.0.0.1:8100{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (localhost)
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


@pytest.mark.parametrize("term,needle", [("bosmax", "bosmax"), ("warisan", "warisan")])
def test_live_search_returns_targets(term: str, needle: str):
    payload = _live_json(f"/api/products/search?q={term}")
    if payload is None:
        pytest.skip("local agent not reachable on 127.0.0.1:8100")
    titles = " ".join((it.get("raw_product_title") or "").lower() for it in payload.get("items", []))
    assert needle in titles, f"live search for {term!r} did not surface the target product"
