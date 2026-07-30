"""P7.5-B typed API and stable fail-closed error evidence."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent.api import creative_treatments as api
from agent.models.creative_treatment import (
    CreateTreatmentRequest,
    CreateVariationGroupRequest,
    ReviewTreatmentRequest,
    ReviewVariationGroupRequest,
    SubmitTreatmentReviewRequest,
    SubmitVariationGroupReviewRequest,
)
from agent.services.creative_treatment_service import CreativeTreatmentError


def _treatment_body() -> CreateTreatmentRequest:
    return CreateTreatmentRequest(
        product_id="product-api",
        product_truth_snapshot_id="truth-api",
        copy_set_id="copy-api",
        creative_selection_id="selection-api",
        scene_strategy_id="SPICE_SEASONING",
        format="PGC",
        duration_seconds=8,
        action_sequence=[
            {
                "sequence": 1,
                "allowed_action_index": 0,
                "action_text": "Canonical action",
                "actor_role": "PRODUCT",
                "initial_state": "sealed",
                "resulting_state": "demonstrated",
            },
        ],
        shot_grammar=[
            {
                "sequence": 1,
                "action_sequences": [1],
                "purpose": "demonstrate",
                "framing": "close-up",
                "camera_motion": "push-in",
                "subject": "product",
                "duration_seconds": 8,
            },
        ],
        compatibility_profile={
            "logical_mode": "F2V",
            "source_mode": "FRAMES",
            "required_asset_roles": ["PRODUCT_REFERENCE"],
        },
        asset_bindings=[
            {"role": "PRODUCT_REFERENCE", "asset_id": "asset-api"},
        ],
        created_by="api-author",
    )


def test_contract_refuses_extend_and_partial_variation_binding():
    payload = _treatment_body().model_dump(mode="json")
    payload["generation_mode"] = "EXTEND"
    with pytest.raises(ValidationError):
        CreateTreatmentRequest(**payload)

    payload["generation_mode"] = "SINGLE"
    payload["variation_ordinal"] = 1
    with pytest.raises(
        ValidationError,
        match="VARIATION_GROUP_AND_ORDINAL_REQUIRED_TOGETHER",
    ):
        CreateTreatmentRequest(**payload)


@pytest.mark.asyncio
async def test_create_and_review_endpoints_preserve_typed_contract(monkeypatch):
    create = AsyncMock(
        return_value={"treatment_id": "treatment-api", "status": "DRAFT"},
    )
    review = AsyncMock(
        return_value={"treatment_id": "treatment-api", "status": "APPROVED"},
    )
    monkeypatch.setattr(api.treatments, "create_treatment", create)
    monkeypatch.setattr(api.treatments, "review_treatment", review)

    created = await api.create_treatment(_treatment_body())
    review_body = ReviewTreatmentRequest(
        decision="APPROVED",
        actor_id="reviewer",
        expected_sha256="a" * 64,
        confirmation="APPROVE CREATIVE TREATMENT",
    )
    approved = await api.review_treatment("treatment-api", review_body)
    assert created["status"] == "DRAFT"
    assert approved["status"] == "APPROVED"
    assert isinstance(create.await_args.args[0], CreateTreatmentRequest)
    review.assert_awaited_once_with("treatment-api", review_body)


@pytest.mark.asyncio
async def test_variation_group_endpoints_preserve_review_authority(monkeypatch):
    create = AsyncMock(return_value={"group_id": "group-api", "status": "DRAFT"})
    submit = AsyncMock(
        return_value={"group_id": "group-api", "status": "REVIEW_REQUIRED"},
    )
    review = AsyncMock(
        return_value={"group_id": "group-api", "status": "APPROVED"},
    )
    monkeypatch.setattr(api.treatments, "create_variation_group", create)
    monkeypatch.setattr(
        api.treatments,
        "submit_variation_group_review",
        submit,
    )
    monkeypatch.setattr(api.treatments, "review_variation_group", review)

    create_body = CreateVariationGroupRequest(
        product_id="product-api",
        copy_set_id="copy-api",
        created_by="author",
    )
    submit_body = SubmitVariationGroupReviewRequest(actor_id="submitter")
    review_body = ReviewVariationGroupRequest(
        decision="APPROVED",
        actor_id="reviewer",
        expected_sha256="b" * 64,
        confirmation="APPROVE CREATIVE VARIATION GROUP",
    )
    await api.create_variation_group(create_body)
    await api.submit_variation_group_review("group-api", submit_body)
    await api.review_variation_group("group-api", review_body)
    create.assert_awaited_once_with(create_body)
    submit.assert_awaited_once_with("group-api", actor_id="submitter")
    review.assert_awaited_once_with("group-api", review_body)


@pytest.mark.asyncio
async def test_api_maps_stable_structured_error(monkeypatch):
    monkeypatch.setattr(
        api.treatments,
        "submit_treatment_review",
        AsyncMock(
            side_effect=CreativeTreatmentError(
                "TREATMENT_AUTHORITY_STALE",
                details={"stored_sha256": "a", "current_sha256": "b"},
            ),
        ),
    )
    with pytest.raises(HTTPException) as error:
        await api.submit_treatment_review(
            "treatment-api",
            SubmitTreatmentReviewRequest(actor_id="submitter"),
        )
    assert error.value.status_code == 409
    assert error.value.detail == {
        "error": "TREATMENT_AUTHORITY_STALE",
        "message": "TREATMENT_AUTHORITY_STALE",
        "details": {"stored_sha256": "a", "current_sha256": "b"},
    }


def test_router_exposes_bounded_treatment_control_plane():
    method_paths = {
        (method, route.path)
        for route in api.router.routes
        for method in route.methods
    }
    assert {
        ("POST", "/creative-treatments"),
        ("GET", "/creative-treatments"),
        ("GET", "/creative-treatments/{treatment_id}"),
        ("POST", "/creative-treatments/{treatment_id}/submit-review"),
        ("POST", "/creative-treatments/{treatment_id}/review"),
        ("POST", "/creative-treatments/variation-groups"),
        ("GET", "/creative-treatments/variation-groups"),
        ("GET", "/creative-treatments/variation-groups/{group_id}"),
        (
            "POST",
            "/creative-treatments/variation-groups/{group_id}/submit-review",
        ),
        ("POST", "/creative-treatments/variation-groups/{group_id}/review"),
    } <= method_paths
