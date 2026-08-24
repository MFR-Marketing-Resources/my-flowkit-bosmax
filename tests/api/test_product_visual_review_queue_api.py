from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api import product_visual_onboarding as api
from agent.security.access_control import required_permission


def _actor(*, owner: bool = True, can_update: bool = True):
    return SimpleNamespace(
        user_id="user-owner",
        staff_id="staff-owner",
        display_name="Authenticated Owner",
        role_codes=("OWNER",) if owner else ("EDITOR",),
        permission_codes=frozenset(
            {"products.update", "products.read"}
            if can_update
            else {"products.read"}
        ),
    )


def _request():
    return api.VisualReviewQueueApprovalRequest(
        confirm=True,
        confirmation_phrase="APPROVE SELECTED VISUALS",
        review_note="Owner visual recovery review",
        confirm_identity=True,
        confirm_label_logo=True,
        confirm_geometry_scale=True,
        confirm_product_isolation=True,
        items=[
            api.VisualReviewQueueApprovalItem(
                product_id="p-1",
                candidate_sha256="a" * 64,
                candidate_media_id="media-1",
                expected_lock_updated_at="v1",
                candidate_source_kind="AUTO_GENERATED",
            )
        ],
    )


def test_visual_review_approval_uses_existing_product_update_permission():
    assert required_permission(
        "/api/product-visual-onboarding/review-queue/approve-selected", "POST"
    ) == "products.update"


@pytest.mark.asyncio
async def test_queue_endpoint_exposes_cohort_projection(monkeypatch):
    captured = {}

    async def queue(**kwargs):
        captured.update(kwargs)
        return {"cohort": kwargs["cohort"], "cohort_counts": {}}

    monkeypatch.setattr(api, "get_product_visual_review_queue", queue)
    response = await api.get_visual_review_queue(
        cohort="SOURCE_REUPLOAD_REQUIRED", limit=25, offset=50
    )
    assert response["cohort"] == "SOURCE_REUPLOAD_REQUIRED"
    assert captured == {
        "cohort": "SOURCE_REUPLOAD_REQUIRED",
        "limit": 25,
        "offset": 50,
    }


@pytest.mark.asyncio
async def test_batch_approval_binds_authenticated_owner_and_does_not_accept_client_actor(monkeypatch):
    captured = {}

    async def approve(items, **kwargs):
        captured["items"] = items
        captured.update(kwargs)
        return {"status": "COMPLETED", "results": []}

    monkeypatch.setattr(api, "get_current_auth_context", lambda: _actor())
    monkeypatch.setattr(api, "approve_selected_product_visuals", approve)

    response = await api.approve_visual_review_queue_selection(_request())

    assert response["status"] == "COMPLETED"
    assert captured["items"][0]["product_id"] == "p-1"
    assert captured["actor"].display_name == "Authenticated Owner"
    assert captured["review_note"] == "Owner visual recovery review"
    assert captured["confirm_product_isolation"] is True


@pytest.mark.asyncio
async def test_batch_approval_denies_non_owner_even_with_products_update(monkeypatch):
    monkeypatch.setattr(api, "get_current_auth_context", lambda: _actor(owner=False))
    with pytest.raises(HTTPException) as raised:
        await api.approve_visual_review_queue_selection(_request())
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "OWNER_REQUIRED"


@pytest.mark.asyncio
async def test_batch_approval_denies_owner_without_product_update_permission(monkeypatch):
    monkeypatch.setattr(api, "get_current_auth_context", lambda: _actor(can_update=False))
    with pytest.raises(HTTPException) as raised:
        await api.approve_visual_review_queue_selection(_request())
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_batch_approval_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr(api, "get_current_auth_context", lambda: _actor())
    request = _request().model_copy(update={"confirm": False})
    with pytest.raises(HTTPException) as raised:
        await api.approve_visual_review_queue_selection(request)
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "EXPLICIT_CONFIRMATION_REQUIRED"
