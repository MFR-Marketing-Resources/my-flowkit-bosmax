"""Phase 1 DB foundation tests — schema columns, new tables, CRUD operations."""
import pytest

from agent.db import crud


# ── copy_set additive columns ──────────────────────────────

@pytest.mark.asyncio
async def test_copy_set_has_phase1_columns_after_init():
    """All seven Phase 1 columns exist with correct defaults on a fresh row."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Phase1 Column Test",
        product_display_name="Phase1 Column Test",
        product_short_name="Phase1 Column Test",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Test hook",
        cta="Test CTA",
        usp_set_json='["Test USP"]',
    )
    assert cs["usage_count"] == 0
    assert cs["last_used_at"] is None
    assert cs["used_in_modes"] == "[]"
    assert cs["uniqueness_score"] is None
    assert cs["similar_to_copy_set_id"] is None
    assert cs["similarity_score"] is None
    assert cs["archived"] == 0


@pytest.mark.asyncio
async def test_update_copy_set_phase1_fields():
    """New columns are writable through the CRUD whitelist."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Phase1 Update",
        product_display_name="Phase1 Update",
        product_short_name="Phase1 Update",
    )
    cs = await crud.create_copy_set(
        product["id"],
        hook="Hook text",
        cta="Buy now",
        usp_set_json='["USP"]',
    )
    updated = await crud.update_copy_set(
        cs["copy_set_id"],
        usage_count=5,
        last_used_at="2026-07-01T00:00:00Z",
        used_in_modes='["T2V","HYBRID"]',
        uniqueness_score=0.75,
        similar_to_copy_set_id=cs["copy_set_id"],
        similarity_score=0.85,
        archived=0,
    )
    assert updated["usage_count"] == 5
    assert updated["last_used_at"] == "2026-07-01T00:00:00Z"
    assert updated["used_in_modes"] == '["T2V","HYBRID"]'
    assert updated["uniqueness_score"] == 0.75
    assert updated["similar_to_copy_set_id"] == cs["copy_set_id"]
    assert updated["similarity_score"] == 0.85
    assert updated["archived"] == 0


# ── copy_generation_batch table ────────────────────────────

@pytest.mark.asyncio
async def test_copy_generation_batch_create_and_list():
    """Batch ledger rows can be created and listed by product."""
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Batch Ledger Test",
        product_display_name="Batch Ledger Test",
        product_short_name="Batch Ledger Test",
    )
    batch = await crud.create_copy_generation_batch(
        product_id=product["id"],
        requested_count=5,
        created_count=3,
        deduped_count=2,
        rejected_count=0,
        source="AI_COPY_ASSIST",
        provider_lane="text_assist",
        provider_model="deepseek-v4",
    )
    assert batch["product_id"] == product["id"]
    assert batch["requested_count"] == 5
    assert batch["created_count"] == 3
    assert batch["deduped_count"] == 2
    assert batch["rejected_count"] == 0
    assert batch["source"] == "AI_COPY_ASSIST"

    batches = await crud.list_copy_generation_batches(
        product_id=product["id"]
    )
    assert len(batches) >= 1
    assert batches[0]["batch_id"] == batch["batch_id"]


@pytest.mark.asyncio
async def test_copy_generation_batch_list_empty():
    """Listing for a product with no batches returns empty list."""
    batches = await crud.list_copy_generation_batches(
        product_id="nonexistent-product-id"
    )
    assert batches == []


# ── avatar_product_fit table ───────────────────────────────

@pytest.mark.asyncio
async def test_avatar_product_fit_upsert_and_list():
    """Upsert creates on first write and updates on second."""
    fit1 = await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="BEAUTY_PERSONAL_CARE",
        fit_score=0.95,
        suitability_notes="Good match for beauty demos",
    )
    assert fit1 is not None
    assert fit1["fit_score"] == 0.95

    # Upsert again with new score
    fit2 = await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="BEAUTY_PERSONAL_CARE",
        fit_score=0.80,
    )
    assert fit2["fit_score"] == 0.80
    # Should still be only one row for this key
    fits = await crud.list_avatar_product_fits(
        avatar_code="BOS_F_ALYA_01",
        product_category="BEAUTY_PERSONAL_CARE",
    )
    assert len(fits) == 1


@pytest.mark.asyncio
async def test_avatar_product_fit_list_by_category():
    """Filter by product_category only."""
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_F_ALYA_01",
        product_category="BEAUTY_PERSONAL_CARE",
        fit_score=0.90,
    )
    await crud.upsert_avatar_product_fit(
        avatar_code="BOS_M_HARIS_01",
        product_category="BEAUTY_PERSONAL_CARE",
        fit_score=0.70,
    )
    fits = await crud.list_avatar_product_fits(
        product_category="BEAUTY_PERSONAL_CARE",
    )
    assert len(fits) >= 2
    scores = [f["fit_score"] for f in fits]
    assert scores == sorted(scores, reverse=True)  # ordered by fit_score DESC
