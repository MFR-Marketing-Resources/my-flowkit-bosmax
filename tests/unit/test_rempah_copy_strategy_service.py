from __future__ import annotations

import pytest

from agent.authority.rempah_copy_registry import (
    P3B_ALLOWED_PRODUCT_IDS,
    REMPAH_COPY_REGISTRY,
)
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services import rempah_copy_strategy_service as service
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
)


def _taxonomy(
    product_id: str,
    *,
    cluster: str = "food_cooking",
    product_type_group: str = "rempah_seasoning",
    scene_strategy_id: str = "SPICE_SEASONING",
    coverage: str = "COVERED",
    fallback_used: bool = False,
    specific_strategy: bool = True,
    review_status: str = "VERIFIED",
    consumer_status: str = "READY",
    authority_source: str = "MANUAL_OVERRIDE",
    materialization_status: str = "MATERIALIZED",
    is_stale: bool = False,
) -> ProductStrategyTaxonomy:
    return ProductStrategyTaxonomy(
        product_id=product_id,
        taxonomy_version="product_strategy_taxonomy_v1",
        product_fingerprint="fingerprint",
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
        materialization_status=materialization_status,
        is_stale=is_stale,
    )


def _active_product(product_id: str) -> dict[str, object]:
    names = {
        "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab": (
            "Rempah Nasi Khowmok (140g+- / pack)"
        ),
        "3f0e0206-a21a-4db6-a323-170ce505703f": (
            "Rempah ayam madu by kakyah kaftan 100gram"
        ),
    }
    return {
        "id": product_id,
        "product_display_name": names[product_id],
        "raw_product_title": names[product_id],
        "lifecycle_status": "ACTIVE",
    }


@pytest.mark.asyncio
async def test_p3b_accepts_exact_two_products_for_all_durations(monkeypatch):
    gate_calls: list[str] = []

    async def fake_product(product_id: str):
        return _active_product(product_id)

    async def fake_read(product_id: str):
        return _taxonomy(product_id)

    async def fake_gate(product_id: str):
        gate_calls.append(product_id)
        return _taxonomy(product_id)

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

    outputs = []
    for product_id in sorted(P3B_ALLOWED_PRODUCT_IDS):
        entry = REMPAH_COPY_REGISTRY[product_id]
        for duration in (8, 10, 16):
            output = await service.build_rempah_copy_strategy(
                product_id,
                duration,
            )
            outputs.append(output)
            assert output.product_id == product_id
            assert output.duration_seconds == duration
            assert output.cluster == "food_cooking"
            assert output.product_type_group == "rempah_seasoning"
            assert output.scene_strategy_id == "SPICE_SEASONING"
            assert output.blocked_reasons == []
            assert entry["dish_context"] in output.scene_action
            assert "sprinkle" in output.scene_action
            assert "stir" in output.scene_action
            assert "finished" in output.scene_action
            assert service._spoken_word_count(
                entry["scripts"][duration]
            ) <= service.P3B_WORD_BUDGETS[duration]

    assert len(outputs) == 6
    assert len(gate_calls) == 6
    assert set(gate_calls) == P3B_ALLOWED_PRODUCT_IDS
    assert len({item.copy_strategy_id for item in outputs}) == 2
    assert len({item.hook_line for item in outputs}) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked_product_id",
    [
        "9c85cd83-32f1-4d8b-98bb-6a78f681ed1a",
        "db2dbbeb-79dc-4b78-b1ce-2257257cb7f8",
        "unknown-product-id",
    ],
)
async def test_p3b_blocks_nonallowed_before_product_or_taxonomy_lookup(
    monkeypatch,
    blocked_product_id: str,
):
    async def unexpected_product(_product_id: str):
        raise AssertionError("unallowlisted product reached product lookup")

    monkeypatch.setattr(service.crud, "get_product", unexpected_product)

    with pytest.raises(
        service.RempahCopyStrategyError,
        match="P3B_PRODUCT_NOT_ALLOWED",
    ) as exc:
        await service.build_rempah_copy_strategy(blocked_product_id, 8)

    assert exc.value.status_code == 403
    assert exc.value.blocked_reasons == ["P3B_PRODUCT_NOT_ALLOWED"]


@pytest.mark.asyncio
async def test_p3b_blocks_archived_allowed_product(monkeypatch):
    product_id = next(iter(P3B_ALLOWED_PRODUCT_IDS))

    async def archived_product(_product_id: str):
        return {
            **_active_product(product_id),
            "lifecycle_status": "ARCHIVED",
        }

    monkeypatch.setattr(service.crud, "get_product", archived_product)

    with pytest.raises(
        service.RempahCopyStrategyError,
        match="P3B_PRODUCT_NOT_ACTIVE",
    ):
        await service.build_rempah_copy_strategy(product_id, 8)


@pytest.mark.parametrize(
    ("taxonomy", "expected_reasons"),
    [
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                review_status="REVIEW_REQUIRED",
                consumer_status="BLOCKED_REVIEW_REQUIRED",
                authority_source="AUTO_DERIVED",
            ),
            {
                "P3B_TAXONOMY_NOT_VERIFIED",
                "P3B_TAXONOMY_NOT_READY",
                "P3B_AUTO_DERIVED_NOT_ALLOWED",
            },
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                materialization_status="PREVIEW",
                consumer_status="BLOCKED_REVIEW_REQUIRED",
            ),
            {
                "P3B_TAXONOMY_NOT_READY",
                "P3B_TAXONOMY_NOT_MATERIALIZED",
            },
        ),
        (
            _taxonomy(next(iter(P3B_ALLOWED_PRODUCT_IDS)), is_stale=True),
            {"P3B_TAXONOMY_STALE"},
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                cluster="food_ready_to_eat",
            ),
            {"P3B_WRONG_CLUSTER"},
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                product_type_group="sambal",
            ),
            {"P3B_WRONG_PRODUCT_TYPE_GROUP"},
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                scene_strategy_id="PACKAGED_SAUCE_SAMBAL",
            ),
            {"P3B_SCENE_STRATEGY_MISMATCH"},
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                coverage="PARTIAL",
            ),
            {"P3B_COVERAGE_NOT_COVERED"},
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                coverage="FALLBACK_ONLY",
                fallback_used=True,
                specific_strategy=False,
            ),
            {
                "P3B_COVERAGE_NOT_COVERED",
                "P3B_FALLBACK_NOT_ALLOWED",
                "P3B_SPECIFIC_STRATEGY_REQUIRED",
            },
        ),
        (
            _taxonomy(
                next(iter(P3B_ALLOWED_PRODUCT_IDS)),
                specific_strategy=False,
            ),
            {"P3B_SPECIFIC_STRATEGY_REQUIRED"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_p3b_blocks_every_noncanonical_taxonomy(
    monkeypatch,
    taxonomy: ProductStrategyTaxonomy,
    expected_reasons: set[str],
):
    async def fake_product(product_id: str):
        return _active_product(product_id)

    async def fake_read(_product_id: str):
        return taxonomy

    async def unexpected_gate(_product_id: str):
        raise AssertionError("blocked taxonomy reached canonical consumer gate")

    monkeypatch.setattr(service.crud, "get_product", fake_product)
    monkeypatch.setattr(
        service,
        "get_product_strategy_taxonomy_read_model",
        fake_read,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        unexpected_gate,
    )

    with pytest.raises(service.RempahCopyStrategyError) as exc:
        await service.build_rempah_copy_strategy(taxonomy.product_id, 10)

    assert expected_reasons <= set(exc.value.blocked_reasons)


@pytest.mark.asyncio
async def test_p3b_translates_canonical_gate_rejection(monkeypatch):
    product_id = next(iter(P3B_ALLOWED_PRODUCT_IDS))

    async def fake_product(_product_id: str):
        return _active_product(product_id)

    async def fake_read(_product_id: str):
        return _taxonomy(product_id)

    async def rejected_gate(_product_id: str):
        raise ProductStrategyTaxonomyError("TAXONOMY_NOT_VERIFIED")

    monkeypatch.setattr(service.crud, "get_product", fake_product)
    monkeypatch.setattr(
        service,
        "get_product_strategy_taxonomy_read_model",
        fake_read,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        rejected_gate,
    )

    with pytest.raises(
        service.RempahCopyStrategyError,
        match="P3B_VERIFIED_TAXONOMY_GATE_REJECTED",
    ) as exc:
        await service.build_rempah_copy_strategy(product_id, 8)

    assert exc.value.blocked_reasons == ["P3B_TAXONOMY_NOT_VERIFIED"]


@pytest.mark.asyncio
async def test_p3b_rechecks_constraints_after_canonical_gate(monkeypatch):
    product_id = next(iter(P3B_ALLOWED_PRODUCT_IDS))

    async def fake_product(_product_id: str):
        return _active_product(product_id)

    async def fake_read(_product_id: str):
        return _taxonomy(product_id)

    async def changed_gate_read(_product_id: str):
        return _taxonomy(product_id, coverage="PARTIAL")

    monkeypatch.setattr(service.crud, "get_product", fake_product)
    monkeypatch.setattr(
        service,
        "get_product_strategy_taxonomy_read_model",
        fake_read,
    )
    monkeypatch.setattr(
        service,
        "require_verified_product_strategy_taxonomy",
        changed_gate_read,
    )

    with pytest.raises(service.RempahCopyStrategyError) as exc:
        await service.build_rempah_copy_strategy(product_id, 8)

    assert exc.value.blocked_reasons == ["P3B_COVERAGE_NOT_COVERED"]


def test_p3b_registry_copy_is_distinct_direct_safe_and_duration_bounded():
    forbidden = (
        "confirm sedap",
        "sedap terjamin",
        "pasti menjadi",
        "tiktok",
        "security verified",
        "rawat",
        "sembuh",
        "ubat",
        "wellness",
        "confidence-led",
        "routine-led",
        "trust-led",
    )
    cooking_verbs = ("masukkan", "tabur", "gaul", "masak")
    rendered_scripts: set[str] = set()

    assert len(REMPAH_COPY_REGISTRY) == 2
    assert set(REMPAH_COPY_REGISTRY) == P3B_ALLOWED_PRODUCT_IDS

    for product_id, entry in REMPAH_COPY_REGISTRY.items():
        assert set(entry["scripts"]) == {8, 10, 16}
        for duration, slot in entry["scripts"].items():
            assert not service._registry_copy_blockers(
                slot,
                product_id=product_id,
                duration_seconds=duration,
            )
            rendered = " ".join(slot.values()).casefold()
            assert any(verb in rendered for verb in cooking_verbs)
            assert not any(term in rendered for term in forbidden)
            rendered_scripts.add(rendered)

    assert len(rendered_scripts) == 6
    assert (
        REMPAH_COPY_REGISTRY[
            "0a26caf0-1bc6-43a9-a267-7d2a1dbaccab"
        ]["scripts"][8]["hook_line"]
        != REMPAH_COPY_REGISTRY[
            "3f0e0206-a21a-4db6-a323-170ce505703f"
        ]["scripts"][8]["hook_line"]
    )


@pytest.mark.parametrize(
    ("unsafe_slot", "expected_reason"),
    [
        (
            {
                "hook_line": "TikTok approved dan checkout selamat.",
                "demo_line": "Tabur rempah.",
                "benefit_line": "Aroma lebih naik.",
                "cta_line": "Semak sekarang.",
                "overlay_text": "SECURITY VERIFIED",
            },
            "P3B_PLATFORM_OR_SECURITY_CLAIM_NOT_ALLOWED",
        ),
        (
            {
                "hook_line": "Nak lauk sedap?",
                "demo_line": "Tabur rempah.",
                "benefit_line": "Confirm sedap dan pasti menjadi.",
                "cta_line": "Cuba sekarang.",
                "overlay_text": "SEDAP TERJAMIN",
            },
            "P3B_GUARANTEED_RESULT_CLAIM_NOT_ALLOWED",
        ),
        (
            {
                "hook_line": "Nak rawat badan?",
                "demo_line": "Masukkan rempah.",
                "benefit_line": "Bantu detox dan kesihatan.",
                "cta_line": "Cuba sekarang.",
                "overlay_text": "WELLNESS",
            },
            "P3B_MEDICAL_OR_WELLNESS_CLAIM_NOT_ALLOWED",
        ),
    ],
)
def test_p3b_claim_gate_rejects_unsafe_claim_classes(
    unsafe_slot,
    expected_reason: str,
):
    blockers = service._registry_copy_blockers(
        unsafe_slot,
        product_id=next(iter(P3B_ALLOWED_PRODUCT_IDS)),
        duration_seconds=16,
    )

    assert expected_reason in blockers
