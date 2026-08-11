from __future__ import annotations

import pytest

from agent.models.product_strategy_taxonomy import (
    ProductStrategyTaxonomy,
    ProductStrategyTypeRegistryEntry,
    ProductStrategyTypeRegistryListResponse,
)
from agent.services import catalog_coverage_service as service


def _taxonomy(
    product_id: str,
    *,
    cluster: str = "beauty_makeup",
    product_type_group: str = "lipstick_lip_tint",
    scene_strategy_id: str = "LIP_COLOR",
    coverage: str = "COVERED",
    fallback_used: bool = False,
    specific_strategy: bool = True,
    review_status: str = "VERIFIED",
    consumer_status: str = "READY",
    authority_source: str = "MANUAL_OVERRIDE",
    is_stale: bool = False,
) -> ProductStrategyTaxonomy:
    return ProductStrategyTaxonomy.model_construct(
        product_id=product_id,
        taxonomy_version="product_strategy_taxonomy_v1",
        product_fingerprint=f"fingerprint-{product_id}",
        cluster=cluster,
        product_type_group=product_type_group,
        matched_scene_strategy_id=scene_strategy_id,
        scene_coverage_status=coverage,
        fallback_used=fallback_used,
        specific_strategy=specific_strategy,
        classification_confidence="HIGH",
        review_status=review_status,
        consumer_status=consumer_status,
        authority_source=authority_source,
        materialization_status="MATERIALIZED",
        review_reasons=[],
        is_stale=is_stale,
    )


def _product(
    product_id: str,
    taxonomy: ProductStrategyTaxonomy,
    *,
    lifecycle_status: str = "ACTIVE",
    source_type: str | None = "Lipstick & Lip Gloss",
) -> dict[str, object]:
    return {
        "id": product_id,
        "product_display_name": f"Product {product_id}",
        "raw_product_title": f"Product {product_id}",
        "lifecycle_status": lifecycle_status,
        "category": "Beauty & Personal Care",
        "subcategory": "Makeup",
        "type": source_type,
        "strategy_taxonomy": taxonomy.model_dump(mode="json"),
    }


@pytest.mark.asyncio
async def test_matrix_is_full_deterministic_and_launch_cohort_is_fail_closed(
    monkeypatch,
):
    eligible = _product("eligible", _taxonomy("eligible"))
    unknown_taxonomy = _taxonomy(
        "unknown",
        cluster="generic_unclassified",
        product_type_group="unknown_product_type",
        scene_strategy_id="GENERIC_FALLBACK",
        coverage="FALLBACK_ONLY",
        fallback_used=True,
        specific_strategy=False,
        review_status="REVIEW_REQUIRED",
        consumer_status="BLOCKED_REVIEW_REQUIRED",
        authority_source="AUTO_DERIVED",
    )
    unknown = _product("unknown", unknown_taxonomy, source_type=None)
    archived = _product(
        "archived",
        _taxonomy("archived"),
        lifecycle_status="ARCHIVED",
    )
    stale = _product("stale", _taxonomy("stale", is_stale=True))
    attached = [eligible, unknown, archived, stale]
    attach_calls = 0

    async def fake_products(**kwargs):
        assert kwargs == {"include_archived": True}
        return [{key: value for key, value in item.items() if key != "strategy_taxonomy"}
                for item in attached]

    async def fake_attach(products):
        nonlocal attach_calls
        attach_calls += 1
        assert len(products) == len(attached)
        return attached

    async def fake_registry():
        return ProductStrategyTypeRegistryListResponse(
            items=[
                ProductStrategyTypeRegistryEntry(
                    cluster="beauty_makeup",
                    product_type_group="lipstick_lip_tint",
                    display_name="Lipstick Lip Tint",
                    matched_scene_strategy_id="LIP_COLOR",
                    scene_coverage_status="COVERED",
                    registry_status="ACTIVE",
                    auto_classification_enabled=True,
                    authority_source="SYSTEM_SEED",
                ),
                ProductStrategyTypeRegistryEntry(
                    cluster="generic_unclassified",
                    product_type_group="unknown_product_type",
                    display_name="Unknown Product Type",
                    matched_scene_strategy_id="GENERIC_FALLBACK",
                    scene_coverage_status="FALLBACK_ONLY",
                    registry_status="REVIEW_REQUIRED",
                    auto_classification_enabled=False,
                    authority_source="SYSTEM_SEED",
                ),
            ],
            clusters=["beauty_makeup", "generic_unclassified"],
            scene_strategy_ids=["GENERIC_FALLBACK", "LIP_COLOR"],
        )

    monkeypatch.setattr(service.crud, "list_products", fake_products)
    monkeypatch.setattr(
        service,
        "attach_product_strategy_taxonomies",
        fake_attach,
    )
    monkeypatch.setattr(
        service,
        "list_product_strategy_type_registry",
        fake_registry,
    )

    first = await service.build_catalog_coverage_matrix()
    second = await service.build_catalog_coverage_matrix()

    assert first.total_products == 4
    assert first.active_products == 3
    assert first.archived_products == 1
    assert first.p6_launch_cohort_product_ids == ["eligible"]
    assert first.p6_launch_cohort_count == 1
    assert first.unknown_product_type_count == 1
    assert first.unknown_product_type_p4_supported_count == 0
    assert len(first.products) == first.total_products
    assert first.matrix_sha256 == second.matrix_sha256
    by_id = {row.product_id: row for row in first.products}
    assert by_id["eligible"].blockers == []
    assert by_id["eligible"].p6_launch_cohort is True
    assert "UNKNOWN_PRODUCT_TYPE" in by_id["unknown"].blockers
    assert "P4_NOT_SUPPORTED" in by_id["unknown"].blockers
    assert "PRODUCT_NOT_ACTIVE" in by_id["archived"].blockers
    assert "TAXONOMY_STALE" in by_id["stale"].blockers

    authority_first = await service.build_catalog_authority_matrix()
    authority_second = await service.build_catalog_authority_matrix()
    authority_by_id = {
        row.product_id: row for row in authority_first.products
    }
    assert authority_first.terminal_state_counts == {
        "ARCHIVED_NOT_IN_SCOPE": 1,
        "INSUFFICIENT_PRODUCT_TRUTH": 1,
        "P6_READY": 1,
        "REVIEW_BLOCKED_WITH_EXACT_REASON": 1,
    }
    assert authority_by_id["eligible"].terminal_state == "P6_READY"
    assert (
        authority_by_id["unknown"].terminal_state
        == "INSUFFICIENT_PRODUCT_TRUTH"
    )
    assert authority_by_id["archived"].terminal_state == "ARCHIVED_NOT_IN_SCOPE"
    assert (
        authority_by_id["stale"].terminal_state
        == "REVIEW_BLOCKED_WITH_EXACT_REASON"
    )
    assert authority_by_id["unknown"].p6_launch_cohort is False
    assert authority_first.matrix_sha256 == authority_second.matrix_sha256
    assert attach_calls == 4


@pytest.mark.asyncio
async def test_approved_product_truth_description_releases_description_absent_blocker(
    monkeypatch,
):
    product_id = "8e75f1a8-ba43-444e-8b40-c71d140c76c5"
    taxonomy = _taxonomy(
        product_id,
        cluster="sensitive_wellness",
        product_type_group="traditional_herbal_preparation",
        scene_strategy_id="SENSITIVE_WELLNESS",
        authority_source="MANUAL_OVERRIDE",
    )
    product = _product(
        product_id,
        taxonomy,
        source_type="Herbal Topical Cream",
    )
    product["category"] = "Health & Personal Care"
    product["subcategory"] = "Traditional Herbal Preparation"
    attached = [product]

    async def fake_products(**kwargs):
        assert kwargs == {"include_archived": True}
        return [
            {key: value for key, value in product.items() if key != "strategy_taxonomy"}
        ]

    async def fake_attach(products):
        assert len(products) == 1
        return attached

    async def fake_registry():
        return ProductStrategyTypeRegistryListResponse(
            items=[
                ProductStrategyTypeRegistryEntry(
                    cluster="sensitive_wellness",
                    product_type_group="traditional_herbal_preparation",
                    display_name="Traditional Herbal Preparation",
                    matched_scene_strategy_id="SENSITIVE_WELLNESS",
                    scene_coverage_status="COVERED",
                    registry_status="ACTIVE",
                    auto_classification_enabled=False,
                    authority_source="MANUAL_REGISTRATION",
                ),
            ],
            clusters=["sensitive_wellness"],
            scene_strategy_ids=["SENSITIVE_WELLNESS"],
        )

    async def fake_approved_snapshot(product_id):
        assert product_id == "8e75f1a8-ba43-444e-8b40-c71d140c76c5"
        return {"product_description": "Approved product truth description."}

    monkeypatch.setattr(service.crud, "list_products", fake_products)
    monkeypatch.setattr(service, "attach_product_strategy_taxonomies", fake_attach)
    monkeypatch.setattr(service, "list_product_strategy_type_registry", fake_registry)
    monkeypatch.setattr(
        service.crud,
        "get_latest_approved_product_intelligence_snapshot",
        fake_approved_snapshot,
    )

    report = await service.build_catalog_authority_matrix()

    row = report.products[0]
    assert row.terminal_state == "P6_READY"
    assert row.terminal_reasons == []
