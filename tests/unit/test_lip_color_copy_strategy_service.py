from __future__ import annotations

import pytest

from agent.authority.lip_color_copy_registry import (
    LIP_COLOR_COPY_REGISTRY,
    P3A_ALLOWED_PRODUCT_IDS,
)
from agent.models.product_strategy_taxonomy import ProductStrategyTaxonomy
from agent.services import lip_color_copy_strategy_service as service
from agent.services.product_strategy_taxonomy_service import (
    ProductStrategyTaxonomyError,
)


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
    materialization_status: str = "MATERIALIZED",
    is_stale: bool = False,
) -> ProductStrategyTaxonomy:
    return ProductStrategyTaxonomy(
        product_id=product_id,
        taxonomy_version="PRODUCT_STRATEGY_TAXONOMY_V1",
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
    return {
        "id": product_id,
        "product_display_name": f"Verified Lip Product {product_id[:8]}",
        "raw_product_title": "Verified lip colour",
        "lifecycle_status": "ACTIVE",
    }


@pytest.mark.asyncio
async def test_p3a_accepts_exact_nine_products_for_all_durations(monkeypatch):
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
    for product_id in sorted(P3A_ALLOWED_PRODUCT_IDS):
        for duration in (8, 10, 16):
            output = await service.build_lip_color_copy_strategy(
                product_id,
                duration,
            )
            outputs.append(output)
            assert output.product_id == product_id
            assert output.duration_seconds == duration
            assert output.cluster == "beauty_makeup"
            assert output.product_type_group == "lipstick_lip_tint"
            assert output.scene_strategy_id == "LIP_COLOR"
            assert output.blocked_reasons == []
            assert "lip" in output.scene_action.casefold()
            assert service._spoken_word_count(
                LIP_COLOR_COPY_REGISTRY[product_id]["scripts"][duration]
            ) <= service.P3A_WORD_BUDGETS[duration]

    assert len(outputs) == 27
    assert len(gate_calls) == 27
    assert set(gate_calls) == P3A_ALLOWED_PRODUCT_IDS
    assert len({item.copy_strategy_id for item in outputs}) == 9
    assert len({item.hook_line for item in outputs if item.duration_seconds == 8}) >= 8


@pytest.mark.asyncio
async def test_p3a_blocks_merycode_before_product_or_taxonomy_lookup(monkeypatch):
    async def unexpected_product(_product_id: str):
        raise AssertionError("unallowlisted product reached product lookup")

    monkeypatch.setattr(service.crud, "get_product", unexpected_product)

    with pytest.raises(
        service.LipColorCopyStrategyError,
        match="P3A_PRODUCT_NOT_ALLOWED",
    ) as exc:
        await service.build_lip_color_copy_strategy(
            "db2dbbeb-79dc-4b78-b1ce-2257257cb7f8",
            8,
        )

    assert exc.value.status_code == 403
    assert exc.value.blocked_reasons == ["P3A_PRODUCT_NOT_ALLOWED"]


@pytest.mark.parametrize(
    ("taxonomy", "expected_reason"),
    [
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                review_status="REVIEW_REQUIRED",
                consumer_status="BLOCKED_REVIEW_REQUIRED",
                authority_source="AUTO_DERIVED",
            ),
            "P3A_TAXONOMY_NOT_VERIFIED",
        ),
        (
            _taxonomy(next(iter(P3A_ALLOWED_PRODUCT_IDS)), is_stale=True),
            "P3A_TAXONOMY_STALE",
        ),
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                cluster="beauty_personal_care",
            ),
            "P3A_WRONG_CLUSTER",
        ),
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                product_type_group="serum",
            ),
            "P3A_WRONG_PRODUCT_TYPE_GROUP",
        ),
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                scene_strategy_id="BEAUTY_PERSONAL_CARE",
            ),
            "P3A_SCENE_STRATEGY_MISMATCH",
        ),
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                coverage="PARTIAL",
            ),
            "P3A_COVERAGE_NOT_COVERED",
        ),
        (
            _taxonomy(
                next(iter(P3A_ALLOWED_PRODUCT_IDS)),
                coverage="FALLBACK_ONLY",
                fallback_used=True,
                specific_strategy=False,
            ),
            "P3A_COVERAGE_NOT_COVERED",
        ),
    ],
)
@pytest.mark.asyncio
async def test_p3a_blocks_every_noncanonical_taxonomy(
    monkeypatch,
    taxonomy: ProductStrategyTaxonomy,
    expected_reason: str,
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

    with pytest.raises(service.LipColorCopyStrategyError) as exc:
        await service.build_lip_color_copy_strategy(taxonomy.product_id, 10)

    assert expected_reason in exc.value.blocked_reasons


@pytest.mark.asyncio
async def test_p3a_translates_canonical_gate_rejection(monkeypatch):
    product_id = next(iter(P3A_ALLOWED_PRODUCT_IDS))

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
        service.LipColorCopyStrategyError,
        match="P3A_VERIFIED_TAXONOMY_GATE_REJECTED",
    ) as exc:
        await service.build_lip_color_copy_strategy(product_id, 8)

    assert exc.value.blocked_reasons == ["P3A_TAXONOMY_NOT_VERIFIED"]


@pytest.mark.asyncio
async def test_p3a_rechecks_specific_constraints_after_canonical_gate(
    monkeypatch,
):
    product_id = next(iter(P3A_ALLOWED_PRODUCT_IDS))

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

    with pytest.raises(service.LipColorCopyStrategyError) as exc:
        await service.build_lip_color_copy_strategy(product_id, 8)

    assert exc.value.blocked_reasons == ["P3A_COVERAGE_NOT_COVERED"]


def test_p3a_registry_copy_is_direct_safe_and_duration_bounded():
    forbidden_fluff = ("confidence-led", "routine-led", "trust-led")
    rendered_hooks: set[str] = set()

    assert len(LIP_COLOR_COPY_REGISTRY) == 9
    assert set(LIP_COLOR_COPY_REGISTRY) == P3A_ALLOWED_PRODUCT_IDS

    for product_id, entry in LIP_COLOR_COPY_REGISTRY.items():
        assert set(entry["scripts"]) == {8, 10, 16}
        for duration, slot in entry["scripts"].items():
            assert not service._registry_copy_blockers(
                slot,
                product_id=product_id,
                duration_seconds=duration,
            )
            rendered = " ".join(slot.values()).casefold()
            assert not any(phrase in rendered for phrase in forbidden_fluff)
            assert "tiktok" not in rendered
            assert "permanent" not in rendered
            rendered_hooks.add(slot["hook_line"])

    assert len(rendered_hooks) >= 20


def test_p3a_claim_gate_rejects_fake_platform_and_permanence_claims():
    unsafe_slot = {
        "hook_line": "TikTok safe dan algorithm approved.",
        "demo_line": "Sapu pada bibir.",
        "benefit_line": "Warna tahan 7 hari.",
        "cta_line": "Cuba sekarang.",
        "overlay_text": "TAK KENA BAN",
    }

    blockers = service._registry_copy_blockers(
        unsafe_slot,
        product_id=next(iter(P3A_ALLOWED_PRODUCT_IDS)),
        duration_seconds=16,
    )

    assert "P3A_PLATFORM_POLICY_CLAIM_NOT_ALLOWED" in blockers
    assert "P3A_UNSUPPORTED_PERMANENCE_CLAIM" in blockers
