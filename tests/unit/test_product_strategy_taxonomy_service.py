from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from agent.db import crud
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTaxonomyBackfillRequest,
    ProductStrategyTaxonomyReviewRequest,
)
from agent.services import product_strategy_taxonomy_service as service


def _product_payload(product_id: str, title: str, product_type: str) -> dict:
    return {
        "id": product_id,
        "source": "MANUAL",
        "raw_product_title": title,
        "product_display_name": title,
        "product_short_name": title,
        "category": "Beauty & Personal Care",
        "subcategory": "Makeup",
        "type": product_type,
        "product_type": product_type,
        "product_type_id": product_type.upper(),
    }


def test_classification_separates_covered_partial_and_fallback(monkeypatch):
    monkeypatch.setattr(
        service,
        "resolve_product_intelligence_profile",
        lambda product: {
            "confidence": "HIGH",
            "intelligence_status": "READY",
            "taxonomy_conflict": False,
        },
    )

    covered = service.build_product_strategy_taxonomy_candidate(
        _product_payload("lip", "Velvet Lipstick", "Lipstick")
    )
    partial = service.build_product_strategy_taxonomy_candidate(
        _product_payload("mascara", "Waterproof Mascara", "Mascara")
    )
    fallback = service.build_product_strategy_taxonomy_candidate(
        {
            **_product_payload("unknown", "Mystery Item X9", "Unknown"),
            "category": "Miscellaneous",
            "subcategory": "",
        }
    )

    assert covered.scene_coverage_status == "COVERED"
    assert covered.review_status == "REVIEW_REQUIRED"
    assert covered.consumer_status == "BLOCKED_REVIEW_REQUIRED"
    assert "AUTO_DERIVED_REVIEW_REQUIRED" in covered.review_reasons
    assert partial.scene_coverage_status == "PARTIAL"
    assert partial.review_status == "REVIEW_REQUIRED"
    assert "SCENE_PARTIAL" in partial.review_reasons
    assert fallback.scene_coverage_status == "FALLBACK_ONLY"
    assert fallback.cluster == "generic_unclassified"
    assert fallback.consumer_status == "BLOCKED_REVIEW_REQUIRED"


def test_model_rejects_auto_derived_verified_taxonomy():
    candidate = service.build_product_strategy_taxonomy_candidate(
        _product_payload("lip", "Velvet Lipstick", "Lipstick"),
        materialization_status="MATERIALIZED",
    )

    with pytest.raises(
        ValidationError,
        match="VERIFIED_TAXONOMY_REQUIRES_MANUAL_OVERRIDE",
    ):
        ProductStrategyTaxonomy.model_validate(
            {
                **candidate.model_dump(),
                "review_status": "VERIFIED",
                "consumer_status": "READY",
            }
        )


@pytest.mark.asyncio
async def test_new_product_gets_fail_closed_placeholder_then_backfill_readback():
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Mystery Item X9",
        product_display_name="Mystery Item X9",
        product_short_name="Mystery Item X9",
        category="Miscellaneous",
        type="Unknown",
        product_type="Unknown",
    )

    placeholder = await crud.get_product_strategy_taxonomy(product["id"])
    assert placeholder is not None
    assert placeholder["materialization_status"] == "PLACEHOLDER"
    assert placeholder["review_status"] == "REVIEW_REQUIRED"

    dry_run = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest()
    )
    assert dry_run.dry_run is True
    assert dry_run.mutation_performed is False
    assert dry_run.planned_update_count == 1
    assert (
        await crud.get_product_strategy_taxonomy(product["id"])
    )["materialization_status"] == "PLACEHOLDER"

    applied = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )
    assert applied.mutation_performed is True
    readback = await service.get_product_strategy_taxonomy_read_model(product["id"])
    assert readback.materialization_status == "MATERIALIZED"
    assert readback.scene_coverage_status == "FALLBACK_ONLY"
    assert readback.review_status == "REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_backfill_materializes_archived_products(monkeypatch):
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Archived Mystery Item",
        product_display_name="Archived Mystery Item",
        product_short_name="Archived Mystery Item",
        category="Miscellaneous",
        type="Unknown",
        product_type="Unknown",
    )
    await crud.update_product(product["id"], lifecycle_status="ARCHIVED")
    archived_product = await crud.get_product(product["id"])

    async def fake_list_products(**kwargs):
        assert kwargs["include_archived"] is True
        return [archived_product]

    monkeypatch.setattr(crud, "list_products", fake_list_products)

    dry_run = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest()
    )
    assert dry_run.product_count == 1
    assert dry_run.planned_update_count == 1

    await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )
    readback = await service.get_product_strategy_taxonomy_read_model(product["id"])
    assert readback.materialization_status == "MATERIALIZED"
    assert readback.review_status == "REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_manual_verified_override_is_copy_ready_and_backfill_preserves_it():
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Velvet Lipstick",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Lipstick",
        product_type="Lipstick",
        product_type_id="LIPSTICK",
    )
    fingerprint = service.product_strategy_fingerprint(product)
    reviewed = await service.review_product_strategy_taxonomy(
        product["id"],
        ProductStrategyTaxonomyReviewRequest(
            expected_product_fingerprint=fingerprint,
            cluster="beauty_makeup",
            product_type_group="lipstick_lip_tint",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            review_status="VERIFIED",
            reviewer_id="admin-1",
            reviewer_note="Verified against owned product evidence.",
        ),
    )
    assert reviewed.authority_source == "MANUAL_OVERRIDE"
    assert (
        await service.require_verified_product_strategy_taxonomy(product["id"])
    ).consumer_status == "READY"

    preview = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest()
    )
    assert preview.preserved_manual_override_count == 1
    await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )
    preserved = await crud.get_product_strategy_taxonomy(product["id"])
    assert preserved["authority_source"] == "MANUAL_OVERRIDE"
    assert preserved["reviewer_id"] == "admin-1"


@pytest.mark.asyncio
async def test_atomic_bulk_write_rolls_back_every_row_on_constraint_failure():
    first = await crud.create_product(
        "First Lipstick",
        source="MANUAL",
        product_display_name="First Lipstick",
        product_short_name="First Lipstick",
    )
    second = await crud.create_product(
        "Second Lipstick",
        source="MANUAL",
        product_display_name="Second Lipstick",
        product_short_name="Second Lipstick",
    )
    first_candidate = service.build_product_strategy_taxonomy_candidate(
        {**first, "type": "Lipstick", "product_type": "Lipstick"},
        materialization_status="MATERIALIZED",
    )
    second_candidate = service.build_product_strategy_taxonomy_candidate(
        {**second, "type": "Lipstick", "product_type": "Lipstick"},
        materialization_status="MATERIALIZED",
    )
    first_record = service._taxonomy_to_record(first_candidate)
    second_record = service._taxonomy_to_record(second_candidate)
    second_record["classification_confidence"] = "INVALID"

    with pytest.raises(sqlite3.IntegrityError):
        await crud.materialize_product_strategy_taxonomies(
            [first_record, second_record]
        )

    assert (
        await crud.get_product_strategy_taxonomy(first["id"])
    )["materialization_status"] == "PLACEHOLDER"
    assert (
        await crud.get_product_strategy_taxonomy(second["id"])
    )["materialization_status"] == "PLACEHOLDER"


@pytest.mark.asyncio
async def test_stale_product_fingerprint_fails_closed():
    product = await crud.create_product(
        "Velvet Lipstick",
        source="MANUAL",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
    )
    await service.review_product_strategy_taxonomy(
        product["id"],
        ProductStrategyTaxonomyReviewRequest(
            expected_product_fingerprint=service.product_strategy_fingerprint(product),
            cluster="beauty_makeup",
            product_type_group="lipstick_lip_tint",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            review_status="VERIFIED",
            reviewer_id="admin-1",
            reviewer_note="Verified.",
        ),
    )
    await crud.update_product(product["id"], raw_product_title="Different Product")

    readback = await service.get_product_strategy_taxonomy_read_model(product["id"])
    assert readback.is_stale is True
    assert readback.review_status == "REVIEW_REQUIRED"
    with pytest.raises(
        service.ProductStrategyTaxonomyError,
        match="TAXONOMY_NOT_VERIFIED",
    ):
        await service.require_verified_product_strategy_taxonomy(product["id"])
