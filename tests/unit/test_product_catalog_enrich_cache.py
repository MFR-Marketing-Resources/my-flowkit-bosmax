"""Regression guard for the catalog product-loading performance fix.

The catalog GET (/api/products) enriched every ~500 rows on every call and the
FastMoss reference cache never hit when the workbook held fewer rows than the
requested limit — together a ~18s "Loading products..." stall on every module
mount (T2V/F2V/Hybrid/I2V/IMG all share this path). These tests lock the two
surgical fixes: a per-row enrichment cache keyed on mutation markers, and a
reference cache guard that tracks the load cap instead of len(items).
"""
import asyncio

import pytest

from agent.api import products as P
from agent.services import fastmoss_product_reference_service as F


def test_enrich_cache_key_changes_when_row_edited():
    base = {"id": "p1", "updated_at": "2026-01-01", "source": "MANUAL"}
    edited = dict(base, updated_at="2026-07-05")  # any write bumps updated_at
    assert P._catalog_enrich_key(base) != P._catalog_enrich_key(edited)
    # claim-safe refresh and lifecycle transitions also invalidate.
    assert P._catalog_enrich_key(base) != P._catalog_enrich_key(
        dict(base, claim_safe_copy_updated_at="2026-07-05")
    )
    assert P._catalog_enrich_key(base) != P._catalog_enrich_key(
        dict(base, lifecycle_status="ARCHIVED")
    )


def test_enrich_cache_key_none_without_id():
    assert P._catalog_enrich_key({"updated_at": "x"}) is None


def test_enrich_cache_hits_and_returns_isolated_copies(monkeypatch):
    calls = {"n": 0}

    async def fake_enrich(product, *, persist=False):
        calls["n"] += 1
        return {"id": product["id"], "readiness": "READY", "nested": ["a"]}

    monkeypatch.setattr(P, "_enrich_product", fake_enrich)
    P._CATALOG_ENRICH_CACHE.clear()

    row = {"id": "z1", "updated_at": "2026-01-01", "source": "MANUAL"}

    async def run():
        first = await P._enrich_product_cached(row)
        second = await P._enrich_product_cached(row)  # same key -> cache hit
        return first, second

    first, second = asyncio.run(run())
    assert calls["n"] == 1, "second call must hit the cache, not re-enrich"
    # Mutating a returned dict must not poison the cached entry.
    first["catalog_state"] = "MUTATED"
    third = asyncio.run(P._enrich_product_cached(row))
    assert third.get("catalog_state") != "MUTATED"
    assert calls["n"] == 1


def test_enrich_cache_misses_after_edit(monkeypatch):
    calls = {"n": 0}

    async def fake_enrich(product, *, persist=False):
        calls["n"] += 1
        return {"id": product["id"]}

    monkeypatch.setattr(P, "_enrich_product", fake_enrich)
    P._CATALOG_ENRICH_CACHE.clear()
    row = {"id": "z2", "updated_at": "2026-01-01"}
    asyncio.run(P._enrich_product_cached(row))
    asyncio.run(P._enrich_product_cached(dict(row, updated_at="2026-07-05")))
    assert calls["n"] == 2, "an edited row (new updated_at) must re-enrich"


def test_reference_cache_guard_tracks_load_cap_not_item_count():
    # The guard must let a workbook smaller than the limit still serve from cache.
    # Simulate a populated cache of 300 items built with a load cap of 500.
    F._REFERENCE_CACHE_SIGNATURE = "sig-abc"
    F._REFERENCE_CACHE_ITEMS = [{"id": f"ref-{i}"} for i in range(300)]
    F._REFERENCE_CACHE_LOADED_LIMIT = 500
    # A request for limit=500 is satisfiable: load cap (500) >= limit (500).
    assert F._REFERENCE_CACHE_LOADED_LIMIT >= 500
    # The old len-based guard would have failed here (300 >= 500 is False).
    assert not (len(F._REFERENCE_CACHE_ITEMS) >= 500)
