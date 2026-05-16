import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from agent.models.product_registration import RegistrationReviewDraft, RegistrationCommitRequest
from agent.services.registration_commit_service import RegistrationCommitService

@pytest.fixture
def mock_storage():
    with patch("agent.services.registration_commit_service.RegistrationDraftStorageService") as mock:
        yield mock

@pytest.fixture
def mock_crud():
    with patch("agent.services.registration_commit_service.crud") as mock:
        mock.create_product = AsyncMock(return_value={"id": "prod-123"})
        yield mock

@pytest.mark.asyncio
async def test_commit_blocked_invalid_phrase(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d1", review_status="READY", source_lane="MANUAL",
        approval_checklist={"normalized_name": True}
    )
    
    req = RegistrationCommitRequest(
        draft_id="d1",
        write_back_confirmed=True,
        user_confirmation_phrase="WRONG_PHRASE"
    )
    
    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert "INVALID_CONFIRMATION_PHRASE" in result["blocked_reasons"]

@pytest.mark.asyncio
async def test_commit_blocked_unresolved_fields(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d2", review_status="NEEDS_REVIEW", source_lane="MANUAL",
        human_review_fields=["category"],
        approval_checklist={"normalized_name": True, "category": False}
    )
    
    req = RegistrationCommitRequest(
        draft_id="d2",
        write_back_confirmed=True,
        user_confirmation_phrase="REGISTER_OWNED_PRODUCT"
    )
    
    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert "UNRESOLVED_REVIEW_FIELDS: category" in result["blocked_reasons"]

@pytest.mark.asyncio
async def test_successful_commit(mock_storage, mock_crud):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d3", review_status="READY", source_lane="MANUAL",
        approval_checklist={"normalized_name": True},
        canonical_candidate_fields={"normalized_name": "Test Product"}
    )
    
    req = RegistrationCommitRequest(
        draft_id="d3",
        write_back_confirmed=True,
        user_confirmation_phrase="REGISTER_OWNED_PRODUCT"
    )
    
    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "COMMITTED"
    assert result["write_back_performed"] is True
    assert result["committed_product_id"] == "prod-123"
    mock_crud.create_product.assert_called_once()
