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
        mock.list_products = AsyncMock(return_value=[])
        mock.update_product = AsyncMock(return_value={"id": "prod-123"})
        yield mock

@pytest.mark.asyncio
async def test_commit_blocked_invalid_phrase(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d1", review_status="READY", source_lane="MANUAL",
        approval_checklist={"normalized_name": True},
        draft_freshness_status="FRESH",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
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
async def test_commit_blocks_unapproved_human_review_fields(mock_storage, mock_crud):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d2", review_status="NEEDS_REVIEW", source_lane="MANUAL",
        human_review_fields=["category"],
        approval_checklist={"normalized_name": True, "category": False},
        canonical_candidate_fields={"normalized_name": "Review Product", "category": "Health"},
        draft_freshness_status="FRESH",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
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
async def test_successful_commit(mock_storage, mock_crud, tmp_path):
    image_path = tmp_path / "draft-product.jpg"
    image_path.write_bytes(b"draft-image")

    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d3", review_status="READY", source_lane="MANUAL",
        approval_checklist={"normalized_name": True},
        declared_evidence_fields={
            "product_name": "Test Product",
            "size_or_volume": "5 ML",
            "source_url": "https://example.com/product",
            "image_url": "https://example.com/product.jpg",
            "local_image_path": str(image_path),
            "price": 15.0,
            "currency": "MYR",
            "commission_amount": 1.5,
            "commission_rate": "10%",
            "image_notes": "Front bottle image",
            "packaging_description": "small bottle with cap",
        },
        canonical_candidate_fields={"normalized_name": "Test Product 5 ML", "size_or_volume": "5 ML"},
        draft_freshness_status="FRESH",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
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
    assert mock_crud.create_product.await_args.kwargs["raw_product_title"] == "Test Product 5 ML"
    assert mock_crud.create_product.await_args.kwargs["source_url"] == "https://example.com/product"
    assert mock_crud.create_product.await_args.kwargs["image_url"] == "https://example.com/product.jpg"
    assert mock_crud.create_product.await_args.kwargs["price"] == 15.0
    assert mock_crud.update_product.await_count == 1

@pytest.mark.asyncio
async def test_commit_blocked_duplicate_owned_product(mock_storage, mock_crud):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d4", review_status="READY", source_lane="MANUAL",
        approval_checklist={"normalized_name": True},
        declared_evidence_fields={"product_name": "Bosmax Herbs", "size_or_volume": "5 ML"},
        canonical_candidate_fields={"normalized_name": "Bosmax Herbs 5 ML"},
        draft_freshness_status="FRESH",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
    )
    mock_crud.list_products = AsyncMock(return_value=[{
        "id": "prod-existing",
        "raw_product_title": "Bosmax Herbs 5 ML",
        "product_display_name": "Bosmax Herbs 5 ML",
        "product_short_name": "Bosmax Herbs 5 ML",
    }])

    req = RegistrationCommitRequest(
        draft_id="d4",
        write_back_confirmed=True,
        user_confirmation_phrase="REGISTER_OWNED_PRODUCT"
    )

    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert "DUPLICATE_OWNED_PRODUCT_CANDIDATE:prod-existing" in result["blocked_reasons"]


@pytest.mark.asyncio
async def test_commit_blocks_reference_lane_from_owned_canonical_writeback(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d6",
        review_status="READY",
        source_lane="FASTMOSS_REFERENCE",
        approval_checklist={"normalized_name": True},
        draft_freshness_status="FRESH",
        last_evidence_edit_at="2026-05-17T10:00:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
    )

    req = RegistrationCommitRequest(
        draft_id="d6",
        write_back_confirmed=True,
        user_confirmation_phrase="REGISTER_OWNED_PRODUCT",
    )

    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert "SOURCE_LANE_NOT_ALLOWED_FOR_OWNED_COMMIT" in result["blocked_reasons"]


@pytest.mark.asyncio
async def test_commit_blocked_when_draft_recompute_required(mock_storage):
    mock_storage.get_draft.return_value = RegistrationReviewDraft(
        review_draft_id="d5",
        review_status="READY",
        source_lane="MANUAL",
        approval_checklist={"normalized_name": True},
        draft_freshness_status="STALE",
        last_evidence_edit_at="2026-05-17T10:05:00Z",
        last_recomputed_at="2026-05-17T10:00:00Z",
    )

    req = RegistrationCommitRequest(
        draft_id="d5",
        write_back_confirmed=True,
        user_confirmation_phrase="REGISTER_OWNED_PRODUCT",
    )

    result = await RegistrationCommitService.commit_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert "DRAFT_RECOMPUTE_REQUIRED" in result["blocked_reasons"]
