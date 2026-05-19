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


# ---------------------------------------------------------------------------
# Hotfix #92 governance seal — non-LOW claim risk at final commit authority
# ---------------------------------------------------------------------------

def _make_fastmoss_promoted_draft(**overrides) -> RegistrationReviewDraft:
    defaults = dict(
        review_draft_id="dfp-001",
        review_status="REVIEW_READY",
        source_lane="FASTMOSS_PROMOTED",
        claim_risk_level="LOW",
        image_asset_status="IMAGE_URL_PRESENT",
        declared_evidence_fields={"product_name": "Test Serum", "image_url": "https://img.com/s.jpg"},
        canonical_candidate_fields={"normalized_name": "Test Serum"},
        fastmoss_reference_id="ref-001",
        missing_required_evidence=[],
    )
    defaults.update(overrides)
    return RegistrationReviewDraft(**defaults)


@pytest.mark.asyncio
async def test_commit_fastmoss_promoted_blocks_unknown_claim_risk(mock_storage, mock_crud):
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft(claim_risk_level="UNKNOWN")
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert any(
        "CLAIM_RISK_NOT_ELIGIBLE_FOR_FASTMOSS_PROMOTED_COMMIT:UNKNOWN" in r
        for r in result["blocked_reasons"]
    )


@pytest.mark.asyncio
async def test_commit_fastmoss_promoted_blocks_empty_claim_risk(mock_storage, mock_crud):
    # claim_risk_level is typed str (non-optional); empty string represents the "not set" case
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft(claim_risk_level="")
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "BLOCKED"
    # empty string coerces to "UNKNOWN" via `level or 'UNKNOWN'` in the blocked reason
    assert any(
        "CLAIM_RISK_NOT_ELIGIBLE_FOR_FASTMOSS_PROMOTED_COMMIT:UNKNOWN" in r
        for r in result["blocked_reasons"]
    )


@pytest.mark.asyncio
async def test_fastmoss_promoted_commit_preserves_source_lane_lineage(mock_storage, mock_crud):
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft()
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "COMMITTED"

    call_kwargs = mock_crud.create_product.await_args.kwargs
    assert call_kwargs["source"] == "MANUAL"
    assert call_kwargs["mapping_source"] == "FASTMOSS_PROMOTED"
    assert call_kwargs["mapping_review_status"] == "REVIEWED_FASTMOSS_PROMOTED_COMMIT"
    assert call_kwargs["mapping_status"] == "APPROVED"
    assert call_kwargs["fastmoss_reference_id"] == "ref-001"


# ---------------------------------------------------------------------------
# PR #102 governance tests — commit-time duplicate policy for FASTMOSS_PROMOTED
# Raw source=FASTMOSS reference catalog rows must NOT block; canonical rows must.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fastmoss_promoted_commit_ignores_raw_fastmoss_reference_duplicate(mock_storage, mock_crud):
    """Raw source=FASTMOSS row with matching title and no promotion markers must NOT block commit."""
    raw_fastmoss_row = {
        "id": "a7421ac4-7423-4262-86d4-d5be6e687c25",
        "source": "FASTMOSS",
        "mapping_source": None,
        "mapping_review_status": None,
        "fastmoss_reference_id": None,
        "raw_product_title": "Test Serum",
        "product_display_name": "Test Serum",
        "product_short_name": "Test Serum",
        "tiktok_product_url": None,
    }
    mock_crud.list_products.return_value = [raw_fastmoss_row]
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft()
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "COMMITTED", (
        f"Raw FASTMOSS reference row must not block commit; got: {result}"
    )


@pytest.mark.asyncio
async def test_fastmoss_promoted_commit_blocks_manual_duplicate(mock_storage, mock_crud):
    """MANUAL-source row with matching title must block commit with DUPLICATE_PRODUCT_CANDIDATE."""
    manual_row = {
        "id": "manual-123",
        "source": "MANUAL",
        "mapping_source": None,
        "mapping_review_status": None,
        "fastmoss_reference_id": None,
        "raw_product_title": "Test Serum",
        "product_display_name": "Test Serum",
        "product_short_name": "",
        "tiktok_product_url": None,
    }
    mock_crud.list_products.return_value = [manual_row]
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft()
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert any("DUPLICATE_PRODUCT_CANDIDATE" in r for r in result["blocked_reasons"]), (
        f"Expected DUPLICATE_PRODUCT_CANDIDATE block for MANUAL duplicate; got: {result['blocked_reasons']}"
    )


@pytest.mark.asyncio
async def test_fastmoss_promoted_commit_blocks_already_promoted_duplicate(mock_storage, mock_crud):
    """Already-committed FASTMOSS_PROMOTED row must block commit."""
    already_promoted_row = {
        "id": "promoted-456",
        "source": "FASTMOSS",
        "mapping_source": "FASTMOSS_PROMOTED",
        "mapping_review_status": "REVIEWED_FASTMOSS_PROMOTED_COMMIT",
        "fastmoss_reference_id": "ref-already-committed",
        "raw_product_title": "Test Serum",
        "product_display_name": "Test Serum",
        "product_short_name": "",
        "tiktok_product_url": None,
    }
    mock_crud.list_products.return_value = [already_promoted_row]
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft()
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "BLOCKED"
    assert any("DUPLICATE_PRODUCT_CANDIDATE" in r for r in result["blocked_reasons"]), (
        f"Expected DUPLICATE_PRODUCT_CANDIDATE block for already-promoted duplicate; got: {result['blocked_reasons']}"
    )


@pytest.mark.asyncio
async def test_fastmoss_promoted_commit_ignores_raw_fastmoss_tiktok_url_match(mock_storage, mock_crud):
    """Raw source=FASTMOSS row matching only on TikTok URL and no promotion markers must NOT block."""
    raw_fastmoss_url_row = {
        "id": "b1111111-0000-0000-0000-000000000001",
        "source": "FASTMOSS",
        "mapping_source": None,
        "mapping_review_status": None,
        "fastmoss_reference_id": None,
        "raw_product_title": "Different Title",
        "product_display_name": "Different Title",
        "product_short_name": "",
        "tiktok_product_url": "https://tiktok.com/product/test-serum-99",
    }
    mock_crud.list_products.return_value = [raw_fastmoss_url_row]
    mock_storage.get_draft.return_value = _make_fastmoss_promoted_draft(
        declared_evidence_fields={
            "product_name": "Test Serum",
            "image_url": "https://img.com/s.jpg",
            "tiktok_product_url": "https://tiktok.com/product/test-serum-99",
        }
    )
    req = RegistrationCommitRequest(
        draft_id="dfp-001",
        write_back_confirmed=True,
        user_confirmation_phrase="PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
    )
    result = await RegistrationCommitService.commit_fastmoss_promoted_draft(req)
    assert result["commit_status"] == "COMMITTED", (
        f"Raw FASTMOSS row matched only by TikTok URL must not block commit; got: {result}"
    )
