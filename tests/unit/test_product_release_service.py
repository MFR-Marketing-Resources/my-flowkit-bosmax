import pytest

from agent.access_control_constants import ROLE_PERMISSION_CODES
from agent.security.access_control import required_permission
from agent.services.product_release_service import (
    HIDDEN,
    RELEASED,
    annotate_product_release_state,
    resolve_product_release_state,
)


def _eligible_product(**overrides):
    product = {
        "id": "product-release-test",
        "lifecycle_status": "ACTIVE",
        "mapping_status": "READY",
        "product_truth_status": "APPROVED",
        "product_truth_update_pending": False,
        "prompt_readiness_status": "READY",
        "claim_gate": "CLAIM_SAFE",
        "staff_release_status": HIDDEN,
        "visual_readiness": {
            "canonical_media_status": "AVAILABLE",
            "exact_commerce_status": "EXACT_COMMERCE_CUTOUT_READY",
        },
    }
    product.update(overrides)
    return product


def test_release_requires_explicit_owner_decision_even_when_ready():
    state = resolve_product_release_state(_eligible_product())

    assert state["minimum_eligibility_status"] == "ELIGIBLE"
    assert state["owner_released"] is False
    assert state["operationally_visible"] is False
    assert state["visibility_reason"] == "OWNER_RELEASE_REQUIRED"
    assert state["blocker_codes"] == []


def test_released_product_becomes_invisible_when_current_readiness_blocks():
    state = resolve_product_release_state(
        _eligible_product(
            staff_release_status=RELEASED,
            claim_gate="CLAIM_BLOCKED",
        )
    )

    assert state["staff_release_status"] == RELEASED
    assert state["minimum_eligibility_status"] == "BLOCKED"
    assert state["operationally_visible"] is False
    assert state["visibility_reason"] == "RELEASED_BUT_BLOCKED"
    assert "COPY_READINESS_NOT_READY" in state["blocker_codes"]


def test_release_resolver_keeps_product_lifecycle_separate():
    state = resolve_product_release_state(
        _eligible_product(
            staff_release_status=RELEASED,
            lifecycle_status="ACTIVE",
        )
    )

    assert state["staff_release_status"] == RELEASED
    assert state["operationally_visible"] is True


def test_release_permission_is_separate_and_owner_only():
    assert required_permission("/api/product-release", "GET") == "products.release"
    assert required_permission("/api/product-release/item/release", "POST") == "products.release"
    assert "products.release" in ROLE_PERMISSION_CODES["OWNER"]
    assert "products.release" not in ROLE_PERMISSION_CODES["MANAGER"]
    assert "products.release" not in ROLE_PERMISSION_CODES["EDITOR"]
    assert "products.release" not in ROLE_PERMISSION_CODES["OPERATOR"]
    assert "products.release" not in ROLE_PERMISSION_CODES["VIEWER"]


@pytest.mark.asyncio
async def test_release_annotation_uses_one_set_based_visual_projection_for_the_page(monkeypatch):
    visual_calls: list[list[str]] = []

    async def annotate_visuals(products):
        visual_calls.append([str(product["id"]) for product in products])
        for product in products:
            product["visual_readiness"] = {
                "canonical_media_status": "AVAILABLE",
                "exact_commerce_status": "EXACT_COMMERCE_CUTOUT_READY",
            }

    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.annotate_products_visual_readiness",
        annotate_visuals,
    )

    products = [_eligible_product(id=f"product-{index}") for index in range(3)]
    await annotate_product_release_state(products, attach_truth=False)

    assert visual_calls == [["product-0", "product-1", "product-2"]]
    assert all(product["minimum_eligibility_status"] == "ELIGIBLE" for product in products)


@pytest.mark.asyncio
async def test_release_annotation_does_not_call_single_product_visual_readiness(monkeypatch):
    single_product_calls = 0

    async def forbidden_single_product_readiness(_product_id):
        nonlocal single_product_calls
        single_product_calls += 1
        raise AssertionError("release-control page must not fan out visual readiness reads")

    async def annotate_visuals(products):
        for product in products:
            product["visual_readiness"] = {
                "canonical_media_status": "AVAILABLE",
                "exact_commerce_status": "EXACT_COMMERCE_CUTOUT_READY",
            }

    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.get_product_visual_readiness",
        forbidden_single_product_readiness,
    )
    monkeypatch.setattr(
        "agent.services.product_visual_onboarding_service.annotate_products_visual_readiness",
        annotate_visuals,
    )

    await annotate_product_release_state([_eligible_product(id="product-batch")], attach_truth=False)

    assert single_product_calls == 0
