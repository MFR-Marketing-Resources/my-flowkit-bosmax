from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from agent.db import crud
from agent.db.schema import get_db
from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTaxonomyBackfillRequest,
    ProductStrategyTaxonomyReviewRequest,
    ProductStrategyTypeRegistrationRequest,
    ProductStrategyTypeRegistrySeedRequest,
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


async def _seed_registry() -> None:
    await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=service.REGISTRY_SEED_CONFIRMATION,
        )
    )


@pytest.mark.asyncio
async def test_registry_seed_is_dry_run_safe_and_preserves_manual_pairs():
    preview = await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest()
    )
    assert preview.dry_run is True
    assert preview.mutation_performed is False
    assert preview.planned_insert_count == preview.seed_count
    assert preview.planned_update_count == 0
    assert await crud.list_product_strategy_type_registry() == []

    manual = await service.register_product_strategy_type(
        ProductStrategyTypeRegistrationRequest(
            cluster="beauty_makeup",
            product_type_group="custom_palette",
            display_name="Custom Palette",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            registry_status="ACTIVE",
            reviewer_id="admin-1",
            reviewer_note="Reviewed scene binding.",
        )
    )
    assert manual.authority_source == "MANUAL_REGISTRATION"

    applied = await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=service.REGISTRY_SEED_CONFIRMATION,
        )
    )
    assert applied.mutation_performed is True
    readback = await service.list_product_strategy_type_registry()
    assert len(readback.items) == applied.seed_count + 1
    assert next(
        item
        for item in readback.items
        if item.product_type_group == "custom_palette"
    ).authority_source == "MANUAL_REGISTRATION"
    traditional_rows = {
        item.product_type_group: item
        for item in readback.items
        if item.cluster == "traditional_wellness"
    }
    assert set(traditional_rows) == {
        "traditional_herbal_oil",
        "herbal_roll_on_oil",
    }
    assert all(item.registry_status == "ACTIVE" for item in traditional_rows.values())
    assert all(
        item.scene_coverage_status == "COVERED"
        for item in traditional_rows.values()
    )
    assert all(
        item.auto_classification_enabled is False
        for item in traditional_rows.values()
    )
    assert all(
        item.reviewer_id == "owner:Faris" and item.reviewed_at
        for item in traditional_rows.values()
    )

    reapplied = await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=service.REGISTRY_SEED_CONFIRMATION,
        )
    )
    assert reapplied.mutation_performed is False
    assert reapplied.planned_insert_count == 0
    assert reapplied.planned_update_count == 0
    assert len((await service.list_product_strategy_type_registry()).items) == len(
        readback.items
    )


@pytest.mark.asyncio
async def test_registry_seed_upgrades_existing_system_pair():
    await _seed_registry()
    db = await get_db()
    await db.execute(
        "UPDATE product_strategy_type_registry "
        "SET matched_scene_strategy_id='GENERIC_FALLBACK', "
        "scene_coverage_status='FALLBACK_ONLY', "
        "registry_status='REVIEW_REQUIRED', reviewer_id=NULL, "
        "reviewer_note=NULL, reviewed_at=NULL "
        "WHERE cluster='beauty_makeup' AND product_type_group='mascara'"
    )
    await db.commit()

    preview = await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest()
    )
    assert preview.planned_update_count == 1

    applied = await service.seed_product_strategy_type_registry(
        ProductStrategyTypeRegistrySeedRequest(
            dry_run=False,
            confirm_apply=service.REGISTRY_SEED_CONFIRMATION,
        )
    )
    assert applied.mutation_performed is True
    mascara = await crud.get_product_strategy_type_registry_entry(
        "beauty_makeup",
        "mascara",
    )
    assert mascara is not None
    assert mascara["matched_scene_strategy_id"] == "MASCARA"
    assert mascara["scene_coverage_status"] == "COVERED"
    assert mascara["registry_status"] == "ACTIVE"
    assert mascara["reviewer_id"] == "owner-mission:P5.7"


@pytest.mark.asyncio
async def test_startup_reconcile_refreshes_only_initialized_system_seed_rows():
    db = await get_db()
    await db.execute("DELETE FROM product_strategy_type_registry")
    await db.commit()
    assert (
        await service.reconcile_existing_system_product_strategy_type_registry()
        is None
    )
    assert await crud.list_product_strategy_type_registry() == []

    await _seed_registry()
    stale_pairs = (
        ("beauty_personal_care", "cleanser"),
        ("beauty_personal_care", "serum"),
        ("home_equipment", "vacuum"),
    )
    for cluster, product_type_group in stale_pairs:
        await db.execute(
            "UPDATE product_strategy_type_registry "
            "SET matched_scene_strategy_id='GENERIC_FALLBACK', "
            "scene_coverage_status='FALLBACK_ONLY', "
            "registry_status='REVIEW_REQUIRED' "
            "WHERE cluster=? AND product_type_group=?",
            (cluster, product_type_group),
        )
    await db.commit()

    reconciled = (
        await service.reconcile_existing_system_product_strategy_type_registry()
    )
    assert reconciled is not None
    assert reconciled.mutation_performed is True
    assert reconciled.planned_insert_count == 0
    assert reconciled.planned_update_count == 3
    assert reconciled.active_count == 125
    assert reconciled.review_required_count == 3

    expected_strategies = {
        ("beauty_personal_care", "cleanser"): "CLEANSER",
        ("beauty_personal_care", "serum"): "SERUM",
        ("home_equipment", "vacuum"): "VACUUM_CLEANER",
    }
    for pair, strategy_id in expected_strategies.items():
        row = await crud.get_product_strategy_type_registry_entry(*pair)
        assert row is not None
        assert row["matched_scene_strategy_id"] == strategy_id
        assert row["scene_coverage_status"] == "COVERED"
        assert row["registry_status"] == "ACTIVE"

    second_pass = (
        await service.reconcile_existing_system_product_strategy_type_registry()
    )
    assert second_pass is not None
    assert second_pass.mutation_performed is False
    assert second_pass.planned_update_count == 0


@pytest.mark.asyncio
async def test_registry_blocks_active_fallback_and_unregistered_assignment():
    with pytest.raises(
        service.ProductStrategyTaxonomyError,
        match="GENERIC_OR_FALLBACK_REGISTRY_PAIR_CANNOT_BE_ACTIVE",
    ):
        await service.register_product_strategy_type(
            ProductStrategyTypeRegistrationRequest(
                cluster="beauty_makeup",
                product_type_group="uncovered_makeup",
                display_name="Uncovered Makeup",
                matched_scene_strategy_id="GENERIC_FALLBACK",
                scene_coverage_status="FALLBACK_ONLY",
                registry_status="ACTIVE",
                reviewer_id="admin-1",
                reviewer_note="Invalid active fallback.",
            )
        )

    with pytest.raises(
        service.ProductStrategyTaxonomyError,
        match="UNREGISTERED_PRODUCT_STRATEGY_TYPE",
    ):
        await service.validate_product_strategy_assignment(
            cluster="beauty_makeup",
            product_type_group="not_registered",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            review_status="VERIFIED",
        )


@pytest.mark.asyncio
async def test_review_required_registry_pair_cannot_be_verified():
    await _seed_registry()

    entry = await service.validate_product_strategy_assignment(
        cluster="beauty_personal_care",
        product_type_group="beauty_personal_care_other",
        matched_scene_strategy_id="GENERIC_FALLBACK",
        scene_coverage_status="FALLBACK_ONLY",
        review_status="REVIEW_REQUIRED",
    )
    assert entry.registry_status == "REVIEW_REQUIRED"

    with pytest.raises(
        service.ProductStrategyTaxonomyError,
        match="PRODUCT_STRATEGY_TYPE_NOT_ACTIVE",
    ):
        await service.validate_product_strategy_assignment(
            cluster="beauty_personal_care",
            product_type_group="beauty_personal_care_other",
            matched_scene_strategy_id="GENERIC_FALLBACK",
            scene_coverage_status="FALLBACK_ONLY",
            review_status="VERIFIED",
        )


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
    newly_covered = service.build_product_strategy_taxonomy_candidate(
        _product_payload("serum", "Waterproof Beauty Serum", "Serum")
    )
    partial = service.build_product_strategy_taxonomy_candidate(
        _product_payload("chopper", "Mini Food Chopper", "Chopper")
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
    assert newly_covered.scene_coverage_status == "COVERED"
    assert newly_covered.matched_scene_strategy_id == "SERUM"
    assert "SCENE_PARTIAL" not in newly_covered.review_reasons
    assert partial.scene_coverage_status == "PARTIAL"
    assert partial.review_status == "REVIEW_REQUIRED"
    assert "SCENE_PARTIAL" in partial.review_reasons
    assert fallback.scene_coverage_status == "FALLBACK_ONLY"
    assert fallback.cluster == "generic_unclassified"
    assert fallback.consumer_status == "BLOCKED_REVIEW_REQUIRED"


@pytest.mark.parametrize(
    "product",
    [
        _product_payload("lip", "Velvet Lipstick", "Lipstick"),
        _product_payload("serum", "Waterproof Beauty Serum", "Serum"),
        _product_payload("chopper", "Mini Food Chopper", "Chopper"),
        {
            **_product_payload("unknown", "Mystery Item X9", "Unknown"),
            "category": "Miscellaneous",
            "subcategory": "",
        },
    ],
)
def test_strategy_binding_matches_full_candidate_semantics(
    monkeypatch,
    product,
):
    monkeypatch.setattr(
        service,
        "resolve_product_intelligence_profile",
        lambda _product: {
            "confidence": "HIGH",
            "intelligence_status": "READY",
            "taxonomy_conflict": False,
        },
    )

    binding = service._strategy_binding(product)
    candidate = service.build_product_strategy_taxonomy_candidate(product)

    assert binding == {
        "cluster": candidate.cluster,
        "product_type_group": candidate.product_type_group,
        "matched_scene_strategy_id": candidate.matched_scene_strategy_id,
        "scene_coverage_status": candidate.scene_coverage_status,
        "fallback_used": candidate.fallback_used,
        "specific_strategy": candidate.specific_strategy,
    }


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


def test_model_allows_verified_manual_preview_but_keeps_consumer_blocked():
    candidate = service.build_product_strategy_taxonomy_candidate(
        _product_payload("lip", "Velvet Lipstick", "Lipstick"),
    )

    preview = ProductStrategyTaxonomy.model_validate(
        {
            **candidate.model_dump(),
            "review_status": "VERIFIED",
            "consumer_status": "BLOCKED_REVIEW_REQUIRED",
            "authority_source": "MANUAL_OVERRIDE",
            "reviewer_id": "admin-1",
            "reviewer_note": "Reviewed registry binding.",
        }
    )

    assert preview.materialization_status == "PREVIEW"
    assert preview.consumer_status == "BLOCKED_REVIEW_REQUIRED"


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
async def test_backfill_refreshes_auto_derived_binding_when_classifier_changes():
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Waterproof Mascara",
        product_display_name="Waterproof Mascara",
        product_short_name="Waterproof Mascara",
        category="Beauty & Personal Care",
        subcategory="Makeup",
        type="Mascara",
        product_type="Mascara",
    )
    candidate = service.build_product_strategy_taxonomy_candidate(
        product,
        materialization_status="MATERIALIZED",
    )
    legacy_record = service._taxonomy_to_record(candidate)
    legacy_record.update(
        {
            "product_type_group": "beauty_personal_care_other",
            "matched_scene_strategy_id": "BEAUTY_PERSONAL_CARE",
            "scene_coverage_status": "PARTIAL",
            "specific_strategy": 0,
        }
    )
    await crud.materialize_product_strategy_taxonomies([legacy_record])

    preview = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest()
    )
    assert preview.planned_update_count == 1

    applied = await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )
    assert applied.mutation_performed is True
    refreshed = await service.get_product_strategy_taxonomy_read_model(
        product["id"]
    )
    assert refreshed.product_type_group == "mascara"
    assert refreshed.matched_scene_strategy_id == "MASCARA"
    assert refreshed.scene_coverage_status == "COVERED"
    assert refreshed.is_stale is False


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
    await _seed_registry()
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
    await _seed_registry()
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


@pytest.mark.asyncio
async def test_stale_taxonomy_binding_fails_closed_without_product_change(
    monkeypatch,
):
    await _seed_registry()
    product = await crud.create_product(
        "Velvet Lipstick",
        source="MANUAL",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
        category="Beauty & Personal Care",
        type="Lipstick & Lip Gloss",
        product_type="Lipstick & Lip Gloss",
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
            reviewer_note="Verified against the prior binding.",
        ),
    )
    real_binding = service._strategy_binding

    def changed_binding(product_payload):
        return {
            **real_binding(product_payload),
            "cluster": "beauty_makeup",
            "product_type_group": "mascara",
            "matched_scene_strategy_id": "MASCARA",
        }

    monkeypatch.setattr(service, "_strategy_binding", changed_binding)

    readback = await service.get_product_strategy_taxonomy_read_model(product["id"])

    assert readback.product_fingerprint == service.product_strategy_fingerprint(product)
    assert readback.is_stale is True
    assert readback.review_status == "REVIEW_REQUIRED"
    assert readback.consumer_status == "BLOCKED_REVIEW_REQUIRED"
    assert "STALE_TAXONOMY_BINDING" in readback.review_reasons


@pytest.mark.asyncio
async def test_manual_custom_binding_without_product_truth_remains_authoritative():
    await service.register_product_strategy_type(
        ProductStrategyTypeRegistrationRequest(
            cluster="beauty_makeup",
            product_type_group="custom_palette",
            display_name="Custom Palette",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            registry_status="ACTIVE",
            reviewer_id="admin-1",
            reviewer_note="Reviewed custom Product Truth evidence.",
        )
    )
    product = await crud.create_product(
        "Opaque Custom Palette",
        source="MANUAL",
        product_display_name="Opaque Custom Palette",
        product_short_name="Opaque Custom Palette",
        category="Beauty",
        type="Custom Palette",
        product_type="Custom Palette",
    )
    await service.review_product_strategy_taxonomy(
        product["id"],
        ProductStrategyTaxonomyReviewRequest(
            expected_product_fingerprint=service.product_strategy_fingerprint(product),
            cluster="beauty_makeup",
            product_type_group="custom_palette",
            matched_scene_strategy_id="LIP_COLOR",
            scene_coverage_status="COVERED",
            review_status="VERIFIED",
            reviewer_id="admin-1",
            reviewer_note="Verified against custom Product Truth evidence.",
        ),
    )

    readback = await service.get_product_strategy_taxonomy_read_model(product["id"])

    assert readback.product_type_group == "custom_palette"
    assert readback.review_status == "VERIFIED"
    assert readback.consumer_status == "READY"
    assert readback.is_stale is False


@pytest.mark.asyncio
async def test_catalog_attachment_checks_persisted_product_not_transient_enrichment():
    product = await crud.create_product(
        "Velvet Lipstick",
        source="MANUAL",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
        category="Beauty & Personal Care",
        type="Lipstick",
        product_type="Lipstick",
    )
    await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )

    attached = await service.attach_product_strategy_taxonomies(
        [
            {
                **product,
                "product_type": "TRANSIENT_ENRICHED_VALUE",
                "product_type_id": "TRANSIENT_ENRICHED_VALUE",
            }
        ]
    )

    assert attached[0]["strategy_taxonomy"]["is_stale"] is False
    assert (
        "STALE_PRODUCT_FINGERPRINT"
        not in attached[0]["strategy_taxonomy"]["review_reasons"]
    )


@pytest.mark.asyncio
async def test_materialized_attachment_skips_full_intelligence_candidate(
    monkeypatch,
):
    product = await crud.create_product(
        "Velvet Lipstick",
        source="MANUAL",
        product_display_name="Velvet Lipstick",
        product_short_name="Velvet Lipstick",
        category="Beauty & Personal Care",
        type="Lipstick",
        product_type="Lipstick",
    )
    await service.run_product_strategy_taxonomy_backfill(
        ProductStrategyTaxonomyBackfillRequest(
            dry_run=False,
            confirm_apply=service.BACKFILL_CONFIRMATION,
        )
    )

    def unexpected_candidate(_product, **_kwargs):
        raise AssertionError(
            "materialized readback must not rebuild product intelligence"
        )

    monkeypatch.setattr(
        service,
        "build_product_strategy_taxonomy_candidate",
        unexpected_candidate,
    )

    attached = await service.attach_product_strategy_taxonomies([product])

    assert attached[0]["strategy_taxonomy"]["product_id"] == product["id"]
    assert attached[0]["strategy_taxonomy"]["materialization_status"] == (
        "MATERIALIZED"
    )
