"""SOLD fix — Kalodata units-sold must reach the bulk-queue writer.

Regression for the bug where 335/367 Kalodata rows persisted `sold_count = NULL`
and the UI rendered "—". Two facts combine to cause it:

1. `kalodata_import_service.build_staged_record` keeps `Item Sold` under
   `record["kalodata_meta"]["sold_count"]`.
2. Every reference row is run through `enrich_product` before the queue writer,
   and enrich NULLS the top-level `sold_count` (it recomputes it from a
   sales-metrics profile that finds nothing for reference rows) while leaving
   `kalodata_meta` intact.

So the writer's `ref.get("sold_count")` was always None. The fix reads the value
via `_resolve_ref_sold_count`, which falls back to `kalodata_meta`.
"""
from __future__ import annotations

import pytest

from agent.services.fastmoss_bulk_promotion_service import _resolve_ref_sold_count


def test_resolver_prefers_top_level_sold_count():
    assert _resolve_ref_sold_count({"sold_count": 3448}) == 3448


def test_resolver_falls_back_to_kalodata_meta():
    ref = {"sold_count": None, "kalodata_meta": {"sold_count": 6335}}
    assert _resolve_ref_sold_count(ref) == 6335


def test_resolver_none_when_absent_everywhere():
    assert _resolve_ref_sold_count({}) is None
    assert _resolve_ref_sold_count({"sold_count": None, "kalodata_meta": {}}) is None


def test_resolver_coerces_stringy_values():
    assert _resolve_ref_sold_count({"sold_count": "9056"}) == 9056
    assert _resolve_ref_sold_count({"sold_count": "  "}) is None


@pytest.mark.asyncio
async def test_enrich_nulls_top_level_but_preserves_kalodata_meta():
    """Documents WHY the fallback is required: enrich clobbers the top level."""
    from agent.services.product_intelligence import enrich_product

    enriched = await enrich_product(
        {"raw_product_title": "Enrich Fixture", "source": "KALODATA",
         "sold_count": 9056, "kalodata_meta": {"sold_count": 9056}},
        persist=False,
    )
    assert enriched.get("sold_count") is None  # nulled by the metric recompute
    assert enriched["kalodata_meta"]["sold_count"] == 9056  # ...meta survives
    # the writer's resolver therefore still recovers the value
    assert _resolve_ref_sold_count(enriched) == 9056
