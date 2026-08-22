"""Pure view-contract tests for Copy Authority activation vs Reporting diagnostics."""

import pytest

from agent.services import copy_activation_candidate_view_service as views
from agent.services.copy_register_review_queue_service import CopyRegisterReviewQueueError


def _candidate(
    blueprint_id: str,
    *,
    state: str,
    activatable: bool,
) -> dict:
    return {
        "blueprint_id": blueprint_id,
        "revision": 1,
        "product_id": f"product-{blueprint_id}",
        "product_name": blueprint_id,
        "status": "PRODUCTION_VALID",
        "formula_id": "PAS",
        "angle": None,
        "activatable": activatable,
        "activation_allowed": activatable,
        "current_authority_state": state,
        "blocked_reason": (
            "COPY_V2_TAXONOMY_AUTHORITY_STALE" if state == "STALE" else None
        ),
        "current_authority_reason": (
            "COPY_V2_TAXONOMY_AUTHORITY_STALE" if state == "STALE" else None
        ),
        "current_authority_mismatches": [],
        "active_blueprint_id": blueprint_id if state == "CURRENT" else None,
        "active_revision": 1 if state == "CURRENT" else None,
        "active_lane_count": 8 if state == "CURRENT" else 0,
        "required_lane_count": 8,
    }


def _response() -> dict:
    return {
        "items": [
            _candidate("bp-ready", state="NONE", activatable=True),
            _candidate("bp-current", state="CURRENT", activatable=True),
            _candidate("bp-stale", state="STALE", activatable=False),
        ],
        "total": 3,
        "max_batch_size": 50,
        "provider_calls": 0,
        "credit_spend": 0,
        "activation_mutations": 0,
    }


def test_activation_view_contains_only_work_the_operator_can_act_on():
    projected = views.project_activation_candidate_view(_response(), view="activation")

    assert projected["view"] == "activation"
    assert projected["total"] == 1
    assert [item["blueprint_id"] for item in projected["items"]] == ["bp-ready"]
    assert projected["provider_calls"] == 0
    assert projected["activation_mutations"] == 0


def test_diagnostics_view_contains_only_stale_or_blocked_attention_rows():
    projected = views.project_activation_candidate_view(_response(), view="diagnostics")

    assert projected["view"] == "diagnostics"
    assert projected["total"] == 1
    assert [item["blueprint_id"] for item in projected["items"]] == ["bp-stale"]
    assert all(item["current_authority_state"] != "CURRENT" for item in projected["items"])


def test_all_view_preserves_full_authority_discovery_for_internal_governance():
    projected = views.project_activation_candidate_view(_response(), view="all")

    assert projected["view"] == "all"
    assert projected["total"] == 3
    assert [item["blueprint_id"] for item in projected["items"]] == [
        "bp-ready",
        "bp-current",
        "bp-stale",
    ]


def test_unknown_view_fails_closed():
    with pytest.raises(CopyRegisterReviewQueueError) as excinfo:
        views.project_activation_candidate_view(_response(), view="mystery")

    assert excinfo.value.code == "COPY_V2_ACTIVATION_VIEW_INVALID"
