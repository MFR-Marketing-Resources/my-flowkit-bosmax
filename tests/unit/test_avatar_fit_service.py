"""Unit tests for avatar_fit_service — product-category to avatar mapping."""
import pytest

from agent.db import crud
from agent.services.avatar_fit_service import (
    get_avatar_fit_summary,
    get_suitable_avatars,
    normalise_category,
)


# ── normalise_category ─────────────────────────────────────

def test_normalise_simple():
    assert normalise_category("Beauty & Personal Care") == "BEAUTY_PERSONAL_CARE"


def test_normalise_with_slash():
    assert normalise_category("Health/Wellness") == "HEALTH_WELLNESS"


def test_normalise_multiple_spaces():
    assert normalise_category("  Laundry  Detergent  ") == "LAUNDRY_DETERGENT"


def test_normalise_empty():
    assert normalise_category("") == "UNCATEGORISED"


def test_normalise_none():
    assert normalise_category(None) == "UNCATEGORISED"


# ── get_suitable_avatars ───────────────────────────────────

@pytest.mark.asyncio
async def test_suitable_avatars_with_explicit_mapping():
    """Explicit fit rows are returned with enriched profile data."""
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="BEAUTY_PERSONAL_CARE",
        fit_score=0.95,
        suitability_notes="Ideal for beauty UGC demos",
    )
    suitable = await get_suitable_avatars(
        "Beauty & Personal Care",
        include_all_fallback=False,
    )
    assert len(suitable) >= 1
    first = suitable[0]
    assert first["avatar_code"] == "BOS_F_ALYA_01"
    assert first["fit_score"] == 0.95
    assert "character_name" in first  # enriched from avatar_registry


@pytest.mark.asyncio
async def test_suitable_avatars_fallback_when_no_mapping():
    """Without explicit mappings and include_all_fallback=True, returns all avatars."""
    suitable = await get_suitable_avatars(
        "SOME_RANDOM_CATEGORY_THAT_DOES_NOT_EXIST",
        include_all_fallback=True,
    )
    assert len(suitable) > 0
    # All should have the fallback fit_score
    for a in suitable:
        assert a["fit_score"] == 1.0
        assert "fallback" in str(a.get("suitability_notes", "")).lower()


@pytest.mark.asyncio
async def test_suitable_avatars_no_fallback():
    """Without mappings and include_all_fallback=False, returns empty."""
    suitable = await get_suitable_avatars(
        "NONEXISTENT_CATEGORY_12345",
        include_all_fallback=False,
    )
    assert suitable == []


@pytest.mark.asyncio
async def test_suitable_avatars_ordered_by_score():
    """Results are sorted by fit_score descending."""
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="TEST_CATEGORY",
        fit_score=0.60,
    )
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_M_HARIS_02",
        product_category="TEST_CATEGORY",
        fit_score=0.90,
    )
    suitable = await get_suitable_avatars(
        "Test Category",
        include_all_fallback=False,
    )
    scores = [a["fit_score"] for a in suitable]
    assert scores == sorted(scores, reverse=True)
    assert len(scores) >= 1  # at least one avatar resolved


# ── get_avatar_fit_summary ─────────────────────────────────

@pytest.mark.asyncio
async def test_fit_summary_with_mappings():
    """Summary reports has_explicit_mappings=True when mappings exist."""
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="SUMMARY_CATEGORY",
        fit_score=0.80,
    )
    summary = await get_avatar_fit_summary("Summary Category")
    assert summary["product_category"] == "SUMMARY_CATEGORY"
    assert summary["has_explicit_mappings"] is True
    assert summary["explicit_match_count"] >= 1
    assert summary["fallback_available"] is False


@pytest.mark.asyncio
async def test_fit_summary_without_mappings():
    """Summary reports has_explicit_mappings=False when no mappings exist."""
    summary = await get_avatar_fit_summary("NO_SUCH_CATEGORY")
    assert summary["has_explicit_mappings"] is False
    assert summary["explicit_match_count"] == 0
    assert summary["fallback_available"] is True
