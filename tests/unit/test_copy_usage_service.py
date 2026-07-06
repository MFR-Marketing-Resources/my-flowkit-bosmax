"""Unit tests for copy_usage_service — usage/fatigue tracking."""
import pytest

from agent.db import crud
from agent.services.copy_usage_service import (
    FATIGUE_HIGH_THRESHOLD,
    FATIGUE_WARN_THRESHOLD,
    get_product_copy_usage_stats,
    increment_copy_usage,
)


@pytest.mark.asyncio
async def test_increment_usage_count_and_timestamp():
    """Single increment updates usage_count and sets last_used_at."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Usage Test Product",
        product_display_name="Usage Test Product",
        product_short_name="Usage Test Product",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Test hook",
        cta="Buy now",
        usp_set_json='["USP 1"]',
    )
    # Approve it first so usage tracking applies to approved copy
    await crud.update_copy_set(cs["copy_set_id"], status="COPY_APPROVED")

    updated = await increment_copy_usage(cs["copy_set_id"], mode="T2V")
    assert updated["usage_count"] == 1
    assert updated["last_used_at"] is not None
    assert "T2V" in updated["used_in_modes"]


@pytest.mark.asyncio
async def test_increment_multiple_modes_no_duplicates():
    """Using the same Copy Set in the same mode twice does not duplicate the mode."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Multi-Mode Product",
        product_display_name="Multi-Mode Product",
        product_short_name="Multi-Mode Product",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Multi hook",
        cta="CTA",
        usp_set_json='["USP"]',
    )
    await crud.update_copy_set(cs["copy_set_id"], status="COPY_APPROVED")

    await increment_copy_usage(cs["copy_set_id"], mode="T2V")
    await increment_copy_usage(cs["copy_set_id"], mode="T2V")
    await increment_copy_usage(cs["copy_set_id"], mode="HYBRID")

    final = await crud.get_copy_set(cs["copy_set_id"])
    assert final["usage_count"] == 3
    import json
    modes = json.loads(final["used_in_modes"])
    assert "T2V" in modes
    assert "HYBRID" in modes
    assert len(modes) == 2  # no duplicate T2V


@pytest.mark.asyncio
async def test_increment_not_found_raises():
    """Passing a non-existent copy_set_id raises ValueError."""
    with pytest.raises(ValueError, match="COPY_SET_NOT_FOUND"):
        await increment_copy_usage("nonexistent-id", mode="T2V")


@pytest.mark.asyncio
async def test_get_product_stats_basic():
    """Stats include counts and per-copy-set data."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Stats Product",
        product_display_name="Stats Product",
        product_short_name="Stats Product",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Stats hook",
        cta="CTA",
        usp_set_json='["USP"]',
    )
    await crud.update_copy_set(cs["copy_set_id"], status="COPY_APPROVED")

    stats = await get_product_copy_usage_stats(product["id"])
    assert stats["product_id"] == product["id"]
    assert stats["total_copy_sets"] >= 1
    assert stats["approved_count"] >= 1
    assert len(stats["usage_by_copy_set"]) >= 1
    assert stats["usage_by_copy_set"][0]["usage_count"] == 0  # never used yet
    assert stats["fatigue_warnings"] == []


@pytest.mark.asyncio
async def test_fatigue_warning_after_threshold():
    """A Copy Set used >= FATIGUE_WARN_THRESHOLD times triggers a warning."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Fatigue Product",
        product_display_name="Fatigue Product",
        product_short_name="Fatigue Product",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Fatigue hook",
        cta="CTA",
        usp_set_json='["USP"]',
    )
    await crud.update_copy_set(cs["copy_set_id"], status="COPY_APPROVED")

    # Increment to exactly the warn threshold
    for i in range(FATIGUE_WARN_THRESHOLD):
        await increment_copy_usage(cs["copy_set_id"], mode="T2V")

    stats = await get_product_copy_usage_stats(product["id"])
    assert len(stats["fatigue_warnings"]) >= 1
    warning = stats["fatigue_warnings"][0]
    assert warning["level"] in ("ELEVATED_USAGE", "HIGH_FATIGUE")
    assert warning["usage_count"] >= FATIGUE_WARN_THRESHOLD


@pytest.mark.asyncio
async def test_fatigue_high_after_high_threshold():
    """Usage >= FATIGUE_HIGH_THRESHOLD triggers HIGH_FATIGUE."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="High Fatigue Product",
        product_display_name="High Fatigue Product",
        product_short_name="High Fatigue Product",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="High fatigue hook",
        cta="CTA",
        usp_set_json='["USP"]',
    )
    await crud.update_copy_set(cs["copy_set_id"], status="COPY_APPROVED")

    for i in range(FATIGUE_HIGH_THRESHOLD):
        await increment_copy_usage(cs["copy_set_id"], mode="T2V")

    stats = await get_product_copy_usage_stats(product["id"])
    high_warnings = [w for w in stats["fatigue_warnings"] if w["level"] == "HIGH_FATIGUE"]
    assert len(high_warnings) >= 1
