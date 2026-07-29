from __future__ import annotations

import pytest

from agent.authority.product_type_copy_strategy_registry import (
    PRODUCT_TYPE_COPY_STRATEGY_REGISTRY,
)
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services import product_type_copy_strategy_service as service
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
)


LIP_KEY = ("beauty_makeup", "lipstick_lip_tint", "LIP_COLOR")
REMPAH_KEY = ("food_cooking", "rempah_seasoning", "SPICE_SEASONING")


def _taxonomy(
    product_id: str,
    *,
    key: tuple[str, str, str] = LIP_KEY,
    coverage: str = "COVERED",
    fallback_used: bool = False,
    specific_strategy: bool = True,
    review_status: str = "VERIFIED",
    consumer_status: str = "READY",
    authority_source: str = "MANUAL_OVERRIDE",
    materialization_status: str = "MATERIALIZED",
    is_stale: bool = False,
) -> ProductStrategyTaxonomy:
    return ProductStrategyTaxonomy.model_construct(
        product_id=product_id,
        taxonomy_version="product_strategy_taxonomy_v1",
        product_fingerprint="fingerprint",
        cluster=key[0],
        product_type_group=key[1],
        matched_scene_strategy_id=key[2],
        scene_coverage_status=coverage,
        fallback_used=fallback_used,
        specific_strategy=specific_strategy,
        classification_confidence="HIGH",
        review_status=review_status,
        consumer_status=consumer_status,
        authority_source=authority_source,
        materialization_status=materialization_status,
        review_reasons=[],
        is_stale=is_stale,
    )


def _product(
    product_id: str,
    *,
    key: tuple[str, str, str] = LIP_KEY,
    name: str | None = None,
    lifecycle_status: str = "ACTIVE",
) -> dict[str, object]:
    default_name = (
        "ACME Velvet Matte Lipstick 4G"
        if key == LIP_KEY
        else "Rempah Nasi Khowmok (140g+- / pack)"
    )
    resolved_name = name or default_name
    return {
        "id": product_id,
        "product_display_name": resolved_name,
        "product_short_name": resolved_name,
        "raw_product_title": resolved_name,
        "lifecycle_status": lifecycle_status,
    }


async def _install_preview_fakes(
    monkeypatch,
    *,
    product: dict[str, object],
    taxonomy: ProductStrategyTaxonomy,
    canonical: ProductStrategyTaxonomy | None = None,
) -> list[str]:
    gate_calls: list[str] = []

    async def fake_product(product_id: str):
        assert product_id == product["id"]
        return product

    async def fake_read(product_id: str):
        assert product_id == product["id"]
        return taxonomy

    async def fake_gate(product_id: str):
        gate_calls.append(product_id)
        return canonical or taxonomy

    monkeypatch.setattr(service.crud, "get_product", fake_product)
    monkeypatch.setattr(
        service,
        "get_product_strategy_taxonomy_read_model",
        fake_read,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        fake_gate,
    )
    return gate_calls


def test_p4_registry_is_product_type_keyed_not_product_id_keyed():
    assert set(PRODUCT_TYPE_COPY_STRATEGY_REGISTRY) == {LIP_KEY, REMPAH_KEY}
    assert all(len(key) == 3 for key in PRODUCT_TYPE_COPY_STRATEGY_REGISTRY)
    assert not any(
        "product_id" in entry for entry in PRODUCT_TYPE_COPY_STRATEGY_REGISTRY.values()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_id", "key"),
    (
        ("future-owner-verified-lip-product", LIP_KEY),
        ("future-owner-verified-rempah-product", REMPAH_KEY),
    ),
)
async def test_p4_accepts_arbitrary_verified_products_for_all_durations(
    monkeypatch,
    product_id,
    key,
):
    product = _product(product_id, key=key)
    taxonomy = _taxonomy(product_id, key=key)
    gate_calls = await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    responses = [
        await service.build_product_type_copy_strategy(product_id, duration)
        for duration in (8, 10, 16)
    ]

    assert [int(response.duration_seconds) for response in responses] == [8, 10, 16]
    assert all(response.cluster == key[0] for response in responses)
    assert all(response.product_type_group == key[1] for response in responses)
    assert all(response.scene_strategy_id == key[2] for response in responses)
    assert all(response.blocked_reasons == [] for response in responses)
    assert all(
        response.source_strategy == "PRODUCT_TYPE_COPY_STRATEGY_REGISTRY"
        for response in responses
    )
    assert gate_calls == [product_id, product_id, product_id]


@pytest.mark.asyncio
async def test_p4_substitutes_lip_product_facts_and_scene_grammar(monkeypatch):
    product_id = "new-lip-id-not-in-p3a"
    product = _product(
        product_id,
        name="Maybelline Super Stay Matte Ink 16H Long Wear Liquid Lipstick 4G",
    )
    taxonomy = _taxonomy(product_id)
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    response = await service.build_product_type_copy_strategy(product_id, 16)

    assert "Maybelline lipstick" in response.demo_line
    assert "4g" in response.cta_line
    assert "kemasan matte" in response.hook_line
    assert "apply one clean pass to the lips" in response.scene_action
    assert "finished-lip result" in response.scene_action
    rendered = " ".join(
        (
            response.hook_line,
            response.demo_line,
            response.benefit_line,
            response.cta_line,
        )
    ).casefold()
    assert "16h" not in rendered
    assert "long wear" not in rendered


@pytest.mark.asyncio
async def test_p4_substitutes_rempah_dish_size_and_scene_grammar(monkeypatch):
    product_id = "new-rempah-id-not-in-p3b"
    product = _product(product_id, key=REMPAH_KEY)
    taxonomy = _taxonomy(product_id, key=REMPAH_KEY)
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    response = await service.build_product_type_copy_strategy(product_id, 10)

    assert "Rempah Nasi Khowmok" in response.demo_line
    assert "nasi khowmok" in response.hook_line
    assert "140g" in response.cta_line
    assert "sprinkle the seasoning into a pan" in response.scene_action
    assert "stir the seasoning through the dish" in response.scene_action
    assert "finished nasi khowmok result" in response.scene_action


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    (
        ({"review_status": "REVIEW_REQUIRED"}, "TAXONOMY_NOT_VERIFIED"),
        ({"consumer_status": "BLOCKED_REVIEW_REQUIRED"}, "TAXONOMY_NOT_READY"),
        ({"authority_source": "AUTO_DERIVED"}, "AUTO_DERIVED_NOT_ALLOWED"),
        ({"materialization_status": "PREVIEW"}, "TAXONOMY_NOT_MATERIALIZED"),
        ({"is_stale": True}, "TAXONOMY_STALE"),
        ({"coverage": "PARTIAL"}, "COVERAGE_NOT_COVERED"),
        (
            {"coverage": "FALLBACK_ONLY", "fallback_used": True},
            "FALLBACK_NOT_ALLOWED",
        ),
        ({"specific_strategy": False}, "SPECIFIC_STRATEGY_REQUIRED"),
    ),
)
async def test_p4_blocks_each_taxonomy_state(
    monkeypatch,
    overrides,
    expected_reason,
):
    product_id = "blocked-taxonomy-product"
    product = _product(product_id)
    taxonomy = _taxonomy(product_id, **overrides)
    gate_calls = await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert expected_reason in caught.value.blocked_reasons
    assert gate_calls == []


@pytest.mark.asyncio
async def test_p4_blocks_registered_type_with_wrong_scene(monkeypatch):
    product_id = "wrong-scene-product"
    product = _product(product_id)
    taxonomy = _taxonomy(
        product_id,
        key=("beauty_makeup", "lipstick_lip_tint", "BEAUTY_PERSONAL_CARE"),
    )
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "SCENE_STRATEGY_MISMATCH"


@pytest.mark.asyncio
async def test_p4_blocks_verified_product_without_registered_strategy(monkeypatch):
    product_id = "verified-fragrance-product"
    key = ("fragrance", "fragrance", "FRAGRANCE")
    product = _product(product_id, key=key, name="Verified Fragrance")
    taxonomy = _taxonomy(product_id, key=key)
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "COPY_STRATEGY_NOT_REGISTERED"


@pytest.mark.asyncio
async def test_p4_returns_product_not_found(monkeypatch):
    async def missing_product(_product_id: str):
        return None

    monkeypatch.setattr(service.crud, "get_product", missing_product)

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy("missing-product", 8)

    assert caught.value.code == "PRODUCT_NOT_FOUND"
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_p4_blocks_inactive_product_before_taxonomy(monkeypatch):
    product_id = "archived-product"
    product = _product(product_id, lifecycle_status="ARCHIVED")

    async def fake_product(_product_id: str):
        return product

    async def unexpected_taxonomy(_product_id: str):
        raise AssertionError("inactive product reached taxonomy")

    monkeypatch.setattr(service.crud, "get_product", fake_product)
    monkeypatch.setattr(
        service,
        "get_product_strategy_taxonomy_read_model",
        unexpected_taxonomy,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "PRODUCT_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_p4_rejects_unsupported_duration_before_product_lookup(monkeypatch):
    async def unexpected_product(_product_id: str):
        raise AssertionError("unsupported duration reached product lookup")

    monkeypatch.setattr(service.crud, "get_product", unexpected_product)

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy("any-product", 12)

    assert caught.value.code == "UNSUPPORTED_DURATION"
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_p4_translates_canonical_gate_rejection(monkeypatch):
    product_id = "canonical-gate-rejected"
    product = _product(product_id)
    taxonomy = _taxonomy(product_id)

    async def rejected_gate(_product_id: str):
        raise ProductStrategyTaxonomyError("TAXONOMY_NOT_VERIFIED")

    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        rejected_gate,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "TAXONOMY_NOT_VERIFIED"


@pytest.mark.asyncio
async def test_p4_rechecks_taxonomy_after_canonical_gate(monkeypatch):
    product_id = "taxonomy-changed-during-gate"
    product = _product(product_id)
    taxonomy = _taxonomy(product_id)
    changed = _taxonomy(product_id, is_stale=True)
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
        canonical=changed,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "TAXONOMY_STALE"


@pytest.mark.asyncio
async def test_p4_rejects_unsafe_rendered_copy(monkeypatch):
    product_id = "unsafe-rempah"
    product = _product(
        product_id,
        key=REMPAH_KEY,
        name="Rempah Confirm Sedap Ayam 100g",
    )
    taxonomy = _taxonomy(product_id, key=REMPAH_KEY)
    await _install_preview_fakes(
        monkeypatch,
        product=product,
        taxonomy=taxonomy,
    )

    with pytest.raises(service.ProductTypeCopyStrategyError) as caught:
        await service.build_product_type_copy_strategy(product_id, 8)

    assert caught.value.code == "UNSAFE_COPY_CLAIM"
    assert caught.value.status_code == 422


def test_p4_registry_templates_fit_duration_budgets_after_substitution():
    examples = (
        (_product("lip", name="ACME Velvet Matte Lipstick 4G"), LIP_KEY),
        (_product("spice", key=REMPAH_KEY), REMPAH_KEY),
    )
    for product, key in examples:
        entry = PRODUCT_TYPE_COPY_STRATEGY_REGISTRY[key]
        facts = service._resolve_product_facts(product, key)
        for duration in (8, 10, 16):
            slot = service._render_script_slot(entry, duration, facts)
            assert (
                service._spoken_word_count(slot)
                <= service.P4_WORD_BUDGETS[duration]
            )
            assert service._copy_blocked_reasons(
                slot,
                product_id=str(product["id"]),
                duration_seconds=duration,
            ) == []


@pytest.mark.asyncio
async def test_p4_eligible_report_counts_supported_blocked_and_missing(
    monkeypatch,
):
    lip = _product("eligible-lip")
    lip_taxonomy = _taxonomy("eligible-lip")
    spice = _product("eligible-spice", key=REMPAH_KEY)
    spice_taxonomy = _taxonomy("eligible-spice", key=REMPAH_KEY)
    unverified = _product("unverified-lip")
    unverified_taxonomy = _taxonomy(
        "unverified-lip",
        review_status="REVIEW_REQUIRED",
        consumer_status="BLOCKED_REVIEW_REQUIRED",
        authority_source="AUTO_DERIVED",
    )
    fragrance_key = ("fragrance", "fragrance", "FRAGRANCE")
    fragrance = _product(
        "verified-missing-strategy",
        key=fragrance_key,
        name="Verified Fragrance",
    )
    fragrance_taxonomy = _taxonomy(
        "verified-missing-strategy",
        key=fragrance_key,
    )
    archived = _product("archived-lip", lifecycle_status="ARCHIVED")
    archived_taxonomy = _taxonomy("archived-lip")
    sambal_key = (
        "food_ready_to_eat",
        "packaged_food",
        "PACKAGED_FOOD",
    )
    sambal = _product(
        "9c85cd83-32f1-4d8b-98bb-6a78f681ed1a",
        key=sambal_key,
        name="Sambal Serbaguna",
    )
    sambal_taxonomy = _taxonomy(
        str(sambal["id"]),
        key=sambal_key,
        review_status="REVIEW_REQUIRED",
        consumer_status="BLOCKED_REVIEW_REQUIRED",
        authority_source="AUTO_DERIVED",
    )
    pairs = (
        (lip, lip_taxonomy),
        (spice, spice_taxonomy),
        (unverified, unverified_taxonomy),
        (fragrance, fragrance_taxonomy),
        (archived, archived_taxonomy),
        (sambal, sambal_taxonomy),
    )
    products = [product for product, _taxonomy_value in pairs]
    attached = [
        {
            **product,
            "strategy_taxonomy": taxonomy.model_dump(mode="json"),
        }
        for product, taxonomy in pairs
    ]
    gate_calls: list[str] = []

    async def fake_products(**_kwargs):
        return products

    async def fake_attach(received_products):
        assert received_products == products
        return attached

    async def fake_gate(product_id: str):
        gate_calls.append(product_id)
        return {
            taxonomy.product_id: taxonomy for _product_value, taxonomy in pairs
        }[product_id]

    monkeypatch.setattr(service.crud, "list_products", fake_products)
    monkeypatch.setattr(
        service,
        "attach_product_strategy_taxonomies",
        fake_attach,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        fake_gate,
    )

    report = await service.build_product_type_copy_eligible_report()

    assert report.total_products == 6
    assert report.eligible_count == 2
    assert report.blocked_count == 4
    assert {
        (group.cluster, group.product_type_group, group.count)
        for group in report.eligible_by_product_type
    } == {
        ("beauty_makeup", "lipstick_lip_tint", 1),
        ("food_cooking", "rempah_seasoning", 1),
    }
    assert report.blocked_by_reason["PRODUCT_NOT_ACTIVE"] == 1
    assert report.blocked_by_reason["TAXONOMY_NOT_VERIFIED"] == 2
    assert report.blocked_by_reason["COPY_STRATEGY_NOT_REGISTERED"] == 2
    assert {
        group.product_type_group for group in report.missing_copy_strategy_groups
    } == {"fragrance", "packaged_food"}
    assert {item.product_id for item in report.sample_eligible} == {
        "eligible-lip",
        "eligible-spice",
    }
    assert "verified-missing-strategy" in {
        item.product_id for item in report.sample_blocked
    }
    assert gate_calls == ["eligible-lip", "eligible-spice"]
