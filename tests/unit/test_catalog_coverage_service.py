from __future__ import annotations

import json

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
async def test_exact_workbook_mapping_counts_as_product_truth_without_legacy_rule(
    monkeypatch,
):
    mapped = _product(
        "workbook-mapped",
        _taxonomy("workbook-mapped"),
        source_type="3D Scene Sticker Books",
    )
    mapped.update(
        {
            "category": "Toys & Games",
            "subcategory": "Creative Play",
            "type": "3D Scene Sticker Books",
            "copywriting_product_type_code": "3d_sticker_book",
            "copywriting_angle": (
                "Creativity-led city-scene storytelling, reusable play, and "
                "screen-free engagement"
            ),
        }
    )

    async def fake_products(**kwargs):
        assert kwargs == {"include_archived": True}
        return [
            {
                key: value
                for key, value in mapped.items()
                if key != "strategy_taxonomy"
            }
        ]

    async def fake_attach(products):
        assert len(products) == 1
        return [mapped]

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
            ],
            clusters=["beauty_makeup"],
            scene_strategy_ids=["LIP_COLOR"],
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
    monkeypatch.setattr(
        service,
        "resolve_catalog_product_type_truth",
        lambda _product: None,
    )

    coverage = await service.build_catalog_coverage_matrix()
    coverage_row = coverage.products[0]
    assert coverage_row.product_truth_mapped is True

    authority = await service.build_catalog_authority_matrix()
    authority_row = authority.products[0]
    assert authority_row.product_truth_mapped is True
    assert authority_row.mapping_provenance == "SOURCE_TAXONOMY"
    assert authority_row.terminal_state == "P6_READY"


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


@pytest.mark.asyncio
async def test_approved_product_intelligence_releases_only_resolved_p58_blockers(
    monkeypatch,
):
    power_id = "7712a709-d9eb-4203-a07f-249bceff9213"
    headlamp_id = "8014da71-6b87-4476-9eb2-a91baf7fc0dd"
    power = _product(
        power_id,
        _taxonomy(
            power_id,
            cluster="home_electrical",
            product_type_group="power_saver_device",
            scene_strategy_id="ELECTRICAL_DEVICE",
        ),
        source_type="Power Savers",
    )
    power.update(
        {
            "category": "Home & Living",
            "subcategory": "Electrical",
            "type": "Power Savers",
            "copywriting_product_type_code": "power_saver_device",
            "copywriting_angle": "Authority-led household utility and convenience",
        }
    )
    headlamp = _product(
        headlamp_id,
        _taxonomy(
            headlamp_id,
            cluster="outdoor_equipment",
            product_type_group="headlamp",
            scene_strategy_id="OUTDOOR_LIGHTING",
        ),
        source_type="High-Power Headlamps",
    )
    headlamp.update(
        {
            "category": "Sports & Outdoors",
            "subcategory": "Outdoor Lighting",
            "type": "High-Power Headlamps",
            "copywriting_product_type_code": "led_headlamp",
            "copywriting_angle": (
                "Performance-led extreme brightness, zoom, multi-colour modes, "
                "and long battery life"
            ),
        }
    )
    attached = [power, headlamp]

    async def fake_products(**kwargs):
        assert kwargs == {"include_archived": True}
        return [
            {key: value for key, value in product.items() if key != "strategy_taxonomy"}
            for product in attached
        ]

    async def fake_attach(products):
        assert len(products) == 2
        return attached

    async def fake_registry():
        return ProductStrategyTypeRegistryListResponse(
            items=[
                ProductStrategyTypeRegistryEntry(
                    cluster="home_electrical",
                    product_type_group="power_saver_device",
                    display_name="Power Saver Device",
                    matched_scene_strategy_id="ELECTRICAL_DEVICE",
                    scene_coverage_status="COVERED",
                    registry_status="ACTIVE",
                    auto_classification_enabled=True,
                    authority_source="SYSTEM_SEED",
                ),
                ProductStrategyTypeRegistryEntry(
                    cluster="outdoor_equipment",
                    product_type_group="headlamp",
                    display_name="Headlamp",
                    matched_scene_strategy_id="OUTDOOR_LIGHTING",
                    scene_coverage_status="COVERED",
                    registry_status="ACTIVE",
                    auto_classification_enabled=True,
                    authority_source="SYSTEM_SEED",
                ),
            ],
            clusters=["home_electrical", "outdoor_equipment"],
            scene_strategy_ids=["ELECTRICAL_DEVICE", "OUTDOOR_LIGHTING"],
        )

    snapshots = {
        power_id: {
            "status": "APPROVED",
            "claim_gate": "CLAIM_SAFE",
            "claim_risk_level": "LOW",
            "product_description": "Alat penjimat elektrik plug-in.",
            "allowed_claims_json": json.dumps(
                ["Save 80% power and MYR 3000 per year."]
            ),
            "blocked_claims_json": "[]",
            "warnings_text": "Jangan buka perumah alat. Jauhkan dari air.",
            "source_urls_json": json.dumps({"source_url": "https://example.test/power"}),
            "image_evidence_json": "{}",
        },
        headlamp_id: {
            "status": "APPROVED",
            "claim_gate": "CLAIM_SAFE",
            "claim_risk_level": "LOW",
            "product_description": "Lampu kepala LED 2200W, bateri tahan 96 jam.",
            "allowed_claims_json": json.dumps(
                ["Lampu kepala dengan beberapa mod cahaya."]
            ),
            "blocked_claims_json": "[]",
            "warnings_text": "Jangan suluh direct ke mata.",
            "source_urls_json": json.dumps({"source_url": "https://example.test/light"}),
            "image_evidence_json": "{}",
        },
    }

    async def fake_snapshot(product_id):
        return snapshots.get(product_id)

    monkeypatch.setattr(service.crud, "list_products", fake_products)
    monkeypatch.setattr(service, "attach_product_strategy_taxonomies", fake_attach)
    monkeypatch.setattr(service, "list_product_strategy_type_registry", fake_registry)
    monkeypatch.setattr(
        service.crud,
        "get_latest_approved_product_intelligence_snapshot",
        fake_snapshot,
    )

    report = await service.build_catalog_authority_matrix()
    rows = {row.product_id: row for row in report.products}
    assert rows[power_id].terminal_state == "REVIEW_BLOCKED_WITH_EXACT_REASON"
    assert rows[power_id].terminal_reasons == [
        "UNVERIFIED_ELECTRICITY_SAVINGS_CLAIM"
    ]
    assert rows[headlamp_id].terminal_state == "REVIEW_BLOCKED_WITH_EXACT_REASON"
    assert rows[headlamp_id].terminal_reasons == [
        "UNVERIFIED_LIGHT_OUTPUT_AND_RUNTIME_CLAIMS"
    ]

    snapshots[power_id]["allowed_claims_json"] = json.dumps(
        ["Kurangkan bil elektrik, stabilkan arus, mudah digunakan."]
    )
    power_released = await service.build_catalog_authority_matrix()
    power_released_rows = {
        row.product_id: row for row in power_released.products
    }
    assert power_released_rows[power_id].terminal_state == "P6_READY"
    assert power_released_rows[power_id].terminal_reasons == []
    assert power_released_rows[headlamp_id].terminal_state == (
        "REVIEW_BLOCKED_WITH_EXACT_REASON"
    )

    snapshots[headlamp_id]["product_description"] = (
        "Lampu kepala LED untuk aktiviti luar dengan beberapa mod cahaya; "
        "rujuk label produk untuk rating dan tempoh penggunaan."
    )
    released = await service.build_catalog_authority_matrix()
    released_rows = {row.product_id: row for row in released.products}
    assert released_rows[headlamp_id].terminal_state == "P6_READY"
    assert released_rows[headlamp_id].terminal_reasons == []
