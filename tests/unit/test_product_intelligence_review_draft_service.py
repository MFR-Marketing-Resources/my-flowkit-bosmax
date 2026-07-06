import pytest

from agent.db import crud
from agent.services import product_intelligence_snapshot_service as snapshot_svc
from agent.services import product_intelligence_review_draft_service as svc
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewDraftRejectRequest,
)


def _safe_request(**kw) -> ProductIntelligenceReviewDraftCreateRequest:
    base = {
        "product_description": "Compact 500ml bottle for daily routine storage.",
        "benefits_json": ["portable", "compact"],
        "usp_json": ["clean bottle format", "easy shelf fit"],
        "usage_text": "Use as part of a daily routine.",
        "ingredients_text": "Bottle, cap, printed label.",
        "warnings_text": "Store away from direct heat.",
        "target_customer_text": "Busy adults who prefer compact packaging.",
        "allowed_claims_json": ["portable daily carry", "compact shelf storage"],
        "source_urls_json": {"source_url": "https://example.com/source"},
        "image_evidence_json": {"image_url": "https://example.com/image.jpg"},
        "buyer_persona_snapshot_json": {"persona": "busy adults"},
        "copy_strategy_summary_json": {"angle": "compact routine convenience"},
        "created_by": "operator",
    }
    base.update(kw)
    return ProductIntelligenceReviewDraftCreateRequest(**base)


@pytest.mark.asyncio
async def test_create_and_validate_review_draft_returns_ready_state_with_auto_provenance():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft Service",
        source="MANUAL",
        source_url="https://example.com/source",
        image_url="https://example.com/image.jpg",
        product_display_name="Bosmax Review Draft Service",
        product_short_name="Bosmax Review Draft Service",
    )

    draft = await svc.create_review_draft(product["id"], _safe_request())
    assert draft.review_status == "READY_FOR_REVIEW"
    assert draft.claim_gate == "CLAIM_SAFE"
    assert draft.readiness_status == "READY_FOR_APPROVAL"
    assert draft.completeness_score == 1.0
    assert len(draft.provenance_items) >= 1

    report = await svc.validate_review_draft(draft.draft_id)
    assert report.draft.draft_id == draft.draft_id
    assert report.readiness_status == "READY_FOR_APPROVAL"
    assert report.approval_blockers == []


@pytest.mark.asyncio
async def test_approve_review_draft_creates_snapshot_supersedes_previous_and_copies_provenance():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft Approval",
        source="MANUAL",
        product_display_name="Bosmax Review Draft Approval",
        product_short_name="Bosmax Review Draft Approval",
    )
    previous = await snapshot_svc.create_snapshot(
        product_id=product["id"],
        version=1,
        status="APPROVED",
        product_description="Old approved truth",
        approved_at="2026-07-05T10:00:00Z",
        created_by="legacy",
    )
    draft = await svc.create_review_draft(product["id"], _safe_request())

    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(
            approved_by="reviewer-1",
            approval_note="Approved after manual review.",
        ),
    )

    assert approved.status == "APPROVED"
    assert approved.version == 2
    assert approved.created_from_review_draft_id == draft.draft_id
    assert approved.supersedes_snapshot_id == previous.snapshot_id
    assert approved.approved_by == "reviewer-1"

    previous_row = await crud.get_product_intelligence_snapshot(previous.snapshot_id)
    assert previous_row["status"] == "SUPERSEDED"

    approved_provenance = await snapshot_svc.list_field_provenance(
        snapshot_id=approved.snapshot_id
    )
    assert approved_provenance
    assert all(item.snapshot_id == approved.snapshot_id for item in approved_provenance)
    assert all(item.verification_status == "REVIEWED_APPROVED" for item in approved_provenance)

    updated_draft = await svc.get_review_draft_by_id(draft.draft_id)
    assert updated_draft is not None
    assert updated_draft.review_status == "APPROVED"
    assert updated_draft.approved_by == "reviewer-1"


@pytest.mark.asyncio
async def test_reject_review_draft_does_not_create_snapshot():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft Reject",
        source="MANUAL",
        product_display_name="Bosmax Review Draft Reject",
        product_short_name="Bosmax Review Draft Reject",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _safe_request(product_description="Needs human rejection note."),
    )

    rejected = await svc.reject_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftRejectRequest(
            rejected_by="reviewer-2",
            reviewer_note="Evidence insufficient.",
        ),
    )

    assert rejected.review_status == "REJECTED"
    assert rejected.rejected_by == "reviewer-2"
    assert rejected.reviewer_note == "Evidence insufficient."
    assert await snapshot_svc.get_latest_approved_snapshot(product["id"]) is None


@pytest.mark.asyncio
async def test_blocked_review_draft_cannot_be_approved():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft Blocked",
        source="MANUAL",
        product_display_name="Bosmax Review Draft Blocked",
        product_short_name="Bosmax Review Draft Blocked",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _safe_request(
            product_description="Guaranteed relief untuk penyakit dan sembuh cepat.",
            allowed_claims_json=["cure pain fast"],
        ),
    )

    with pytest.raises(ValueError, match="DRAFT_NOT_APPROVABLE:"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="reviewer-3"),
        )


@pytest.mark.asyncio
async def test_claim_review_required_draft_cannot_be_approved_without_override():
    product = await crud.create_product(
        raw_product_title="Bosmax Review Draft Review Required",
        source="MANUAL",
        product_display_name="Bosmax Review Draft Review Required",
        product_short_name="Bosmax Review Draft Review Required",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _safe_request(
            product_description="Anti-inflammatory comfort positioning for review.",
            allowed_claims_json=["portable daily carry"],
        ),
    )

    assert draft.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert draft.readiness_status == "CLAIM_REVIEW_REQUIRED"

    with pytest.raises(ValueError, match="CLAIM_REVIEW_REQUIRED:"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="reviewer-4"),
        )
