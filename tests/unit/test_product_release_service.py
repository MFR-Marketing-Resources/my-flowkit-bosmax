from agent.access_control_constants import ROLE_PERMISSION_CODES
from agent.security.access_control import required_permission
from agent.services.product_release_service import (
    HIDDEN,
    RELEASED,
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
