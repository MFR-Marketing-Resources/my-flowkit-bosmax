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


def _content_only_request(**kw) -> ProductIntelligenceReviewDraftCreateRequest:
    # Every required CONTENT field, but NO source_urls_json / image_evidence_json — so the
    # seeding layer must supply the provenance (mirrors the AI-prepare lane, which also
    # leaves those unset).
    base = {
        "product_description": "Minyak angin tradisional untuk melegakan kembung perut.",
        "benefits_json": ["melegakan perut kembung", "mengurangkan rasa sengal"],
        "usp_json": ["resepi warisan", "ramuan herba asli"],
        "usage_text": "Sapukan pada bahagian tidak selesa, urut perlahan.",
        "ingredients_text": "Minyak herba tradisional.",
        "warnings_text": "Untuk kegunaan luaran sahaja.",
        "target_customer_text": "Individu yang kerap kembung perut atau sengal.",
        "allowed_claims_json": ["melegakan kembung perut", "sesuai kegunaan luaran"],
        "buyer_persona_snapshot_json": {"audience": "warga emas yang mahu kelegaan"},
        "copy_strategy_summary_json": {"angles": ["routine_upgrade"]},
        "created_by": "operator",
    }
    base.update(kw)
    return ProductIntelligenceReviewDraftCreateRequest(**base)


def test_seed_source_urls_manual_product_with_image():
    seed = svc._seed_payload_from_product(
        {
            "id": "p-1",
            "product_display_name": "Minyak Cap Burung",
            "local_image_path": "/data/img/p1.png",
        }
    )
    s = seed["source_urls_json"]
    assert s["source_type"] == "MANUAL_PRODUCT_RECORD"
    assert s["product_id"] == "p-1"
    assert s["product_name"] == "Minyak Cap Burung"
    assert s["local_image_path"] == "/data/img/p1.png"
    assert s["image_evidence_available"] is True


def test_seed_source_urls_manual_product_no_image():
    seed = svc._seed_payload_from_product({"id": "p-2", "product_short_name": "X"})
    s = seed["source_urls_json"]
    assert s["source_type"] == "MANUAL_PRODUCT_RECORD"
    assert s["product_id"] == "p-2"
    assert s["image_evidence_available"] is False
    # Never empty when the product row exists.
    assert svc._has_value(s)


def test_seed_source_urls_prefers_external_url():
    seed = svc._seed_payload_from_product(
        {"id": "p-3", "source_url": "https://shop.example/p3"}
    )
    assert seed["source_urls_json"] == {"source_url": "https://shop.example/p3"}
    assert "source_type" not in seed["source_urls_json"]


@pytest.mark.asyncio
async def test_manual_product_draft_auto_seeds_source_urls_so_it_is_not_missing():
    product = await crud.create_product(
        raw_product_title="Minyak Cap Burung Manual",
        source="MANUAL",
        product_display_name="Minyak Cap Burung Manual",
        image_url="https://example.com/burung.jpg",
    )
    # No source_urls_json supplied by the operator/AI → seed must fill it.
    draft = await svc.create_review_draft(product["id"], _content_only_request())
    assert svc._has_value(draft.source_urls_json)
    assert draft.source_urls_json["source_type"] == "MANUAL_PRODUCT_RECORD"

    report = await svc.validate_review_draft(draft.draft_id)
    assert "source_urls_json" not in report.missing_required_fields
    assert report.approval_blockers == []


@pytest.mark.asyncio
async def test_manual_product_auto_seeded_draft_can_be_approved():
    product = await crud.create_product(
        raw_product_title="Minyak Cap Burung Approve",
        source="MANUAL",
        product_display_name="Minyak Cap Burung Approve",
        image_url="https://example.com/burung2.jpg",
    )
    draft = await svc.create_review_draft(product["id"], _content_only_request())
    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="operator"),
    )
    assert approved.status == "APPROVED"
    assert approved.created_from_review_draft_id == draft.draft_id


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
