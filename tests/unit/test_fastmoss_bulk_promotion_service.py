"""
Unit tests for fastmoss_bulk_promotion_service.
Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue: #92
"""
from __future__ import annotations

import csv
import io
import pytest
from unittest.mock import AsyncMock, MagicMock

from agent.services.fastmoss_bulk_promotion_service import (
    sync_bulk_queue,
    bulk_create_drafts,
    _classify_promotion_status,
    _derive_image_readiness,
    _apply_lineage_to_draft,
    _ref_to_completion_request,
    _detect_queue_duplicate,
    bulk_approve_drafts,
    recompute_selected,
    can_generate_content_for_fastmoss_reference,
    resolve_duplicate_queue_row,
    update_queue_row_status,
    export_missing_as_csv,
    import_enrichment,
)
from agent.models.product_registration import RegistrationReviewDraft


# ---------------------------------------------------------------------------
# _derive_image_readiness
# ---------------------------------------------------------------------------


def test_image_readiness_present():
    assert _derive_image_readiness("https://example.com/img.jpg") == "IMAGE_PRESENT"


def test_image_readiness_none():
    assert _derive_image_readiness(None) == "IMAGE_MISSING"


def test_image_readiness_empty_string():
    assert _derive_image_readiness("") == "IMAGE_MISSING"


def test_image_readiness_whitespace():
    assert _derive_image_readiness("   ") == "IMAGE_MISSING"


# ---------------------------------------------------------------------------
# _classify_promotion_status
# ---------------------------------------------------------------------------


def test_classify_low_risk_ready():
    status = _classify_promotion_status("LOW", "IMAGE_PRESENT", [], False)
    assert status == "READY_FOR_APPROVAL"


def test_classify_high_risk_blocked():
    status = _classify_promotion_status("HIGH", "IMAGE_PRESENT", [], False)
    assert status == "CLAIM_RISK"


def test_classify_medium_risk_needs_review():
    status = _classify_promotion_status("MEDIUM", "IMAGE_PRESENT", [], False)
    assert status == "NEEDS_REVIEW"


def test_classify_duplicate_always_wins():
    # Even LOW risk + good image → DUPLICATE_SUSPECTED if is_duplicate=True
    status = _classify_promotion_status("LOW", "IMAGE_PRESENT", [], True)
    assert status == "DUPLICATE_SUSPECTED"


def test_classify_low_risk_image_missing():
    status = _classify_promotion_status("LOW", "IMAGE_MISSING", [], False)
    assert status == "IMAGE_MISSING"


def test_classify_low_risk_missing_fields():
    status = _classify_promotion_status("LOW", "IMAGE_PRESENT", ["price"], False)
    assert status == "MISSING_REQUIRED_FIELD"


def test_classify_high_risk_overrides_image_missing():
    # HIGH risk should still be CLAIM_RISK even if image is missing
    status = _classify_promotion_status("HIGH", "IMAGE_MISSING", [], False)
    assert status == "CLAIM_RISK"


def test_classify_duplicate_overrides_missing_field():
    # Duplicate check should win over missing fields
    status = _classify_promotion_status("LOW", "IMAGE_PRESENT", ["price"], True)
    assert status == "DUPLICATE_SUSPECTED"


# ---------------------------------------------------------------------------
# _apply_lineage_to_draft
# ---------------------------------------------------------------------------


def _make_draft(**kwargs) -> RegistrationReviewDraft:
    defaults = dict(
        review_draft_id="draft-test-001",
        review_status="REVIEW_READY",
        source_lane="FASTMOSS_PROMOTED",
        declared_evidence_fields={},
        provenance=[],
    )
    defaults.update(kwargs)
    return RegistrationReviewDraft(**defaults)


def test_apply_lineage_sets_reference_id():
    draft = _make_draft()
    ref = {"id": "ref-001", "source_url": "https://src.com", "tiktok_product_url": None,
           "image_url": "https://img.com/img.jpg", "fastmoss_source_file": "batch-A.xlsx"}
    result = _apply_lineage_to_draft(draft, ref, "ref-001")
    assert result.fastmoss_reference_id == "ref-001"


def test_apply_lineage_source_lane_forced():
    draft = _make_draft(source_lane="MANUAL")
    ref = {"id": "ref-002", "source_url": None, "tiktok_product_url": None,
           "image_url": None, "fastmoss_source_file": None}
    result = _apply_lineage_to_draft(draft, ref, "ref-002")
    assert result.source_lane == "FASTMOSS_PROMOTED"


def test_apply_lineage_adds_provenance_entry():
    draft = _make_draft()
    ref = {"id": "ref-003", "source_url": None, "tiktok_product_url": None,
           "image_url": None, "fastmoss_source_file": "batch-B.xlsx"}
    result = _apply_lineage_to_draft(draft, ref, "ref-003")
    assert any("fastmoss_bulk_promotion:reference_id=ref-003" in p for p in result.provenance)
    assert any("fastmoss_source_file:batch-B.xlsx" in p for p in result.provenance)


def test_apply_lineage_does_not_overwrite_existing_source_url():
    draft = _make_draft(declared_evidence_fields={"source_url": "https://existing.com"})
    ref = {"id": "ref-004", "source_url": "https://other.com", "tiktok_product_url": None,
           "image_url": None, "fastmoss_source_file": None}
    result = _apply_lineage_to_draft(draft, ref, "ref-004")
    assert result.declared_evidence_fields["source_url"] == "https://existing.com"


def test_apply_lineage_idempotent():
    draft = _make_draft()
    ref = {"id": "ref-005", "source_url": None, "tiktok_product_url": None,
           "image_url": None, "fastmoss_source_file": None}
    result = _apply_lineage_to_draft(draft, ref, "ref-005")
    result2 = _apply_lineage_to_draft(result, ref, "ref-005")
    prov_entries = [p for p in result2.provenance if "fastmoss_bulk_promotion:reference_id=ref-005" in p]
    assert len(prov_entries) == 1


# ---------------------------------------------------------------------------
# _ref_to_completion_request
# ---------------------------------------------------------------------------


def test_ref_to_completion_request_source_lane():
    req = _ref_to_completion_request({
        "raw_product_title": "Test Serum",
        "image_url": "https://img.com",
        "source_url": "https://src.com",
        "tiktok_product_url": None,
        "commission_rate": "15%",
        "price": 29.9,
        "currency": "MYR",
    })
    assert req.source_lane == "FASTMOSS_PROMOTED"
    assert req.product_name == "Test Serum"


# ---------------------------------------------------------------------------
# update_queue_row_status — allowed vs blocked statuses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_status_blocked_for_approved(monkeypatch):
    result = await update_queue_row_status("ref-x", "APPROVED")
    assert "error" in result
    assert "STATUS_NOT_MANUALLY_SETTABLE" in result["error"]


@pytest.mark.asyncio
async def test_update_status_blocked_for_ready_for_approval(monkeypatch):
    result = await update_queue_row_status("ref-x", "READY_FOR_APPROVAL")
    assert "error" in result


@pytest.mark.asyncio
async def test_update_status_not_in_queue(monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
                        lambda ref_id: _async_return(None))
    result = await update_queue_row_status("ghost-ref", "REJECTED")
    assert result.get("error") == "NOT_IN_QUEUE"


# ---------------------------------------------------------------------------
# bulk_approve_drafts — phrase enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_approve_wrong_phrase_blocked():
    result = await bulk_approve_drafts(["ref-1", "ref-2"], "WRONG_PHRASE")
    assert result["commit_status"] == "BLOCKED"
    assert result["error"] == "INVALID_CONFIRMATION_PHRASE"


@pytest.mark.asyncio
async def test_bulk_approve_skips_non_ready_rows(monkeypatch):
    """Non-READY rows should be skipped, not cause failures."""
    async def _fake_get_row(ref_id):
        return {"reference_id": ref_id, "promotion_status": "NEEDS_REVIEW", "draft_id": None}

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
                        _fake_get_row)
    result = await bulk_approve_drafts(["ref-1"], "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH")
    assert result["skipped"] == 1
    assert result["approved"] == 0
    assert result["results"][0]["outcome"] == "SKIPPED"
    assert "NOT_READY" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_bulk_approve_skips_claim_risk_rows(monkeypatch):
    async def _fake_get_row(ref_id):
        return {"reference_id": ref_id, "promotion_status": "CLAIM_RISK", "draft_id": "d1"}

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
                        _fake_get_row)
    result = await bulk_approve_drafts(["ref-high"], "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH")
    assert result["skipped"] == 1
    assert result["approved"] == 0


@pytest.mark.asyncio
async def test_bulk_approve_skips_image_missing_rows(monkeypatch):
    async def _fake_get_row(ref_id):
        return {"reference_id": ref_id, "promotion_status": "IMAGE_MISSING", "draft_id": "d2"}

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
                        _fake_get_row)
    result = await bulk_approve_drafts(["ref-img"], "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH")
    assert result["skipped"] == 1
    assert result["approved"] == 0


@pytest.mark.asyncio
async def test_bulk_approve_not_in_queue_is_skipped(monkeypatch):
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
                        lambda ref_id: _async_return(None))
    result = await bulk_approve_drafts(["ghost-ref"], "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH")
    assert result["skipped"] == 1
    assert result["results"][0]["reason"] == "NOT_IN_QUEUE"


# ---------------------------------------------------------------------------
# recompute_selected — eligible only, no approval, lineage preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recompute_selected_improved_missing_row_becomes_ready_and_preserves_lineage(
    monkeypatch, tmp_path
):
    from agent.db import crud
    from agent.services.registration_draft_storage_service import RegistrationDraftStorageService

    monkeypatch.setattr(
        "agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR",
        tmp_path,
    )

    reference_id = "ref-recompute-ready-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Serum Vitamin C 30ml",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="MISSING_REQUIRED_FIELD",
        error_message="MISSING:SIZE_OR_VOLUME_EVIDENCE",
    )

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.list_fastmoss_reference_products", AsyncMock(return_value=[{
        "id": reference_id,
        "raw_product_title": "Serum Vitamin C 30ml",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com/src",
        "tiktok_product_url": None,
        "claim_risk_level": "LOW",
        "category": "Beauty",
        "commission_rate": "12%",
        "fastmoss_source_file": "batch-001.xlsx",
    }]))

    fake_draft = RegistrationReviewDraft(
        review_draft_id="draft-recompute-ready-001",
        review_status="REVIEW_READY",
        source_lane="FASTMOSS_PROMOTED",
        declared_evidence_fields={
            "product_name": "Serum Vitamin C 30ml",
            "image_url": "https://example.com/img.jpg",
            "source_url": "https://example.com/src",
            "category": "Beauty",
        },
        claim_gate="CLAIM_SAFE",
        claim_tokens=[],
        claim_risk_level="LOW",
        missing_required_evidence=[],
        approval_checklist={},
        provenance=[],
    )

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.complete_product_knowledge", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_registration_review_draft", MagicMock(return_value=fake_draft))
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.derive_draft_image_asset_state", MagicMock(return_value=("IMAGE_READY", "ok")))
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service._detect_queue_duplicate", AsyncMock(return_value=False))

    products_before = len(await crud.list_products(limit=5000))

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 1
    assert result["ready_for_approval"] == 1
    assert result["failed"] == 0
    assert result["skipped"] == 0
    row_result = result["results"][0]
    assert row_result["previous_status"] == "MISSING_REQUIRED_FIELD"
    assert row_result["new_status"] == "READY_FOR_APPROVAL"
    assert row_result["previous_error_message"] == "MISSING:SIZE_OR_VOLUME_EVIDENCE"
    assert row_result["new_error_message"] is None
    assert row_result["outcome"] == "OK"

    row = await crud.get_bulk_queue_row(reference_id)
    assert row is not None
    assert row["promotion_status"] == "READY_FOR_APPROVAL"
    assert row["draft_id"] == "draft-recompute-ready-001"
    assert row["recompute_previous_status"] == "MISSING_REQUIRED_FIELD"
    assert row["recompute_previous_error"] == "MISSING:SIZE_OR_VOLUME_EVIDENCE"
    assert row["error_message"] is None

    saved_draft = RegistrationDraftStorageService.get_draft("draft-recompute-ready-001")
    assert saved_draft is not None
    assert saved_draft.fastmoss_reference_id == reference_id
    assert saved_draft.source_lane == "FASTMOSS_PROMOTED"
    assert any(
        f"fastmoss_bulk_promotion:reference_id={reference_id}" in p
        for p in saved_draft.provenance
    )

    products_after = len(await crud.list_products(limit=5000))
    assert products_after == products_before, "recompute_selected must not create Product Truth rows"


@pytest.mark.asyncio
async def test_recompute_selected_missing_row_stays_missing_with_error_message(monkeypatch):
    from agent.db import crud

    reference_id = "ref-recompute-missing-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Missing Size Serum",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="MISSING_REQUIRED_FIELD",
        error_message="MISSING:OLD_FIELD",
    )

    async def _fake_recompute(ref_id: str):
        await crud.update_bulk_queue_row(
            ref_id,
            promotion_status="MISSING_REQUIRED_FIELD",
            draft_id="draft-recompute-missing-001",
            error_message="MISSING:SIZE_OR_VOLUME_EVIDENCE",
        )
        return {
            "reference_id": ref_id,
            "draft_id": "draft-recompute-missing-001",
            "promotion_status": "MISSING_REQUIRED_FIELD",
        }

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", _fake_recompute)

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 1
    assert result["missing_required_field"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["new_status"] == "MISSING_REQUIRED_FIELD"
    assert result["results"][0]["new_error_message"] == "MISSING:SIZE_OR_VOLUME_EVIDENCE"

    row = await crud.get_bulk_queue_row(reference_id)
    assert row is not None
    assert row["promotion_status"] == "MISSING_REQUIRED_FIELD"
    assert row["error_message"] == "MISSING:SIZE_OR_VOLUME_EVIDENCE"


@pytest.mark.asyncio
async def test_recompute_selected_skips_claim_risk(monkeypatch):
    from agent.db import crud

    reference_id = "ref-recompute-claim-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Risky Row",
        claim_risk_level="HIGH",
        image_readiness="IMAGE_PRESENT",
        promotion_status="CLAIM_RISK",
        error_message="CLAIM_RISK:CLAIM_REVIEW_REQUIRED",
    )
    mock = AsyncMock()
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", mock)

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 0
    assert result["skipped"] == 1
    assert result["results"][0]["outcome"] == "SKIPPED"
    assert result["results"][0]["error"] == "CLAIM_RISK_RECOMPUTE_BLOCKED"
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recompute_selected_skips_duplicate_suspected(monkeypatch):
    from agent.db import crud

    reference_id = "ref-recompute-dup-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Duplicate Row",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        error_message="DUPLICATE_MATCH",
    )
    mock = AsyncMock()
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", mock)

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 0
    assert result["skipped"] == 1
    assert result["results"][0]["error"] == "DUPLICATE_REVIEW_REQUIRED"
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recompute_selected_skips_approved(monkeypatch):
    from agent.db import crud

    reference_id = "ref-recompute-approved-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Approved Row",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="APPROVED",
        draft_id="draft-approved-001",
    )
    mock = AsyncMock()
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", mock)

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 0
    assert result["skipped"] == 1
    assert result["results"][0]["error"] == "APPROVED_ROWS_CANNOT_RECOMPUTE"
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recompute_selected_skips_rejected(monkeypatch):
    from agent.db import crud

    reference_id = "ref-recompute-rejected-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Rejected Row",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="REJECTED",
        error_message="MANUAL_REJECT",
    )
    mock = AsyncMock()
    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", mock)

    result = await recompute_selected([reference_id])

    assert result["recomputed"] == 0
    assert result["skipped"] == 1
    assert result["results"][0]["error"] == "REJECTED_ROWS_CANNOT_RECOMPUTE"
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_recompute_selected_summary_counts_are_correct(monkeypatch):
    from agent.db import crud

    await crud.create_bulk_queue_row(
        reference_id="ref-recompute-summary-ready",
        raw_product_title="Ready Candidate",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="MISSING_REQUIRED_FIELD",
        error_message="MISSING:OLD",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-recompute-summary-image",
        raw_product_title="Image Candidate",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-recompute-summary-claim",
        raw_product_title="Claim Candidate",
        claim_risk_level="HIGH",
        image_readiness="IMAGE_PRESENT",
        promotion_status="CLAIM_RISK",
        error_message="CLAIM_RISK:CLAIM_REVIEW_REQUIRED",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-recompute-summary-dup",
        raw_product_title="Duplicate Candidate",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        error_message="DUPLICATE_MATCH",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-recompute-summary-approved",
        raw_product_title="Approved Candidate",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="APPROVED",
    )

    async def _fake_recompute(ref_id: str):
        if ref_id == "ref-recompute-summary-ready":
            await crud.update_bulk_queue_row(
                ref_id,
                promotion_status="READY_FOR_APPROVAL",
                draft_id="draft-summary-ready",
                error_message=None,
            )
            return {"reference_id": ref_id, "draft_id": "draft-summary-ready", "promotion_status": "READY_FOR_APPROVAL"}
        if ref_id == "ref-recompute-summary-image":
            await crud.update_bulk_queue_row(
                ref_id,
                promotion_status="IMAGE_MISSING",
                draft_id="draft-summary-image",
                error_message=None,
            )
            return {"reference_id": ref_id, "draft_id": "draft-summary-image", "promotion_status": "IMAGE_MISSING"}
        raise AssertionError(f"Unexpected recompute call for {ref_id}")

    monkeypatch.setattr("agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference", _fake_recompute)

    result = await recompute_selected([
        "ref-recompute-summary-ready",
        "ref-recompute-summary-image",
        "ref-recompute-summary-claim",
        "ref-recompute-summary-dup",
        "ref-recompute-summary-approved",
    ])

    assert result["recomputed"] == 2
    assert result["ready_for_approval"] == 1
    assert result["image_missing"] == 1
    assert result["missing_required_field"] == 0
    assert result["claim_risk"] == 0
    assert result["duplicate_suspected"] == 0
    assert result["failed"] == 0
    assert result["skipped"] == 3


# ---------------------------------------------------------------------------
# duplicate review lane — governance and content authority
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolved_duplicate_suspected_cannot_generate_content():
    from agent.db import crud

    reference_id = "ref-dup-policy-unresolved-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Duplicate Policy Unresolved",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id="prod-suspect-001",
        suspected_existing_product_title="Canonical Existing Product",
    )

    result = await can_generate_content_for_fastmoss_reference(reference_id)

    assert result["content_generation_allowed"] is False
    assert result["resolved_product_id"] is None
    assert result["reason"] == "STATUS_BLOCKS_CONTENT_GENERATION:DUPLICATE_SUSPECTED"


@pytest.mark.asyncio
async def test_link_to_existing_product_allows_content_generation_without_creating_new_product():
    from agent.db import crud

    product_count_before = len(await crud.list_products(limit=5000))
    existing_product = await crud.create_product(
        raw_product_title="Canonical Linked Serum",
        source="MANUAL",
        product_display_name="Canonical Linked Serum",
        mapping_source="MANUAL_REVIEW",
        mapping_status="APPROVED",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-dup-link-001",
        raw_product_title="Canonical Linked Serum",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id=existing_product["id"],
        suspected_existing_product_title=existing_product["product_display_name"],
        suspected_existing_product_source=existing_product["source"],
        suspected_existing_product_mapping_source=existing_product.get("mapping_source"),
        duplicate_match_reason="TITLE_MATCH_EXISTING_PRODUCT",
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-link-001",
        action="LINK_TO_EXISTING_PRODUCT",
        linked_product_id=existing_product["id"],
        note="Operator linked duplicate to canonical product truth.",
    )

    assert result["new_status"] == "DUPLICATE_LINKED"
    assert result["linked_product_id"] == existing_product["id"]
    assert result["duplicate_resolution"] == "LINKED_TO_EXISTING_PRODUCT"
    assert result["content_generation_allowed"] is True
    assert result["message"] == "LINKED_EXISTING_PRODUCT_TRUTH"

    row = await crud.get_bulk_queue_row("ref-dup-link-001")
    assert row is not None
    assert row["promotion_status"] == "DUPLICATE_LINKED"
    assert row["linked_product_id"] == existing_product["id"]

    policy = await can_generate_content_for_fastmoss_reference("ref-dup-link-001")
    assert policy["content_generation_allowed"] is True
    assert policy["resolved_product_id"] == existing_product["id"]

    product_count_after = len(await crud.list_products(limit=5000))
    assert product_count_after == product_count_before + 1


@pytest.mark.asyncio
async def test_link_to_existing_product_blocks_unapproved_manual_row():
    from agent.db import crud

    existing_product = await crud.create_product(
        raw_product_title="Unapproved Manual Serum",
        source="MANUAL",
        product_display_name="Unapproved Manual Serum",
        mapping_source="MANUAL_REVIEW",
        mapping_status="NEEDS_REVIEW",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-dup-link-unapproved-001",
        raw_product_title="Unapproved Manual Serum",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id=existing_product["id"],
        suspected_existing_product_title=existing_product["product_display_name"],
        suspected_existing_product_source=existing_product["source"],
        suspected_existing_product_mapping_source=existing_product.get("mapping_source"),
        duplicate_match_reason="TITLE_MATCH_EXISTING_PRODUCT",
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-link-unapproved-001",
        action="LINK_TO_EXISTING_PRODUCT",
        linked_product_id=existing_product["id"],
    )

    assert result["error"] == "LINKED_PRODUCT_MUST_BE_CANONICAL_PRODUCT_TRUTH"

    policy = await can_generate_content_for_fastmoss_reference(
        "ref-dup-link-unapproved-001"
    )
    assert policy["content_generation_allowed"] is False
    assert policy["resolved_product_id"] is None
    assert policy["reason"] == "STATUS_BLOCKS_CONTENT_GENERATION:DUPLICATE_SUSPECTED"


@pytest.mark.asyncio
async def test_link_to_existing_product_requires_linked_product_id():
    from agent.db import crud

    await crud.create_bulk_queue_row(
        reference_id="ref-dup-link-missing-001",
        raw_product_title="Missing Linked Product Id",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-link-missing-001",
        action="LINK_TO_EXISTING_PRODUCT",
        linked_product_id=None,
    )

    assert result["error"] == "LINKED_PRODUCT_ID_REQUIRED"


@pytest.mark.asyncio
async def test_link_to_existing_product_requires_existing_product():
    from agent.db import crud

    await crud.create_bulk_queue_row(
        reference_id="ref-dup-link-notfound-001",
        raw_product_title="Missing Linked Product",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-link-notfound-001",
        action="LINK_TO_EXISTING_PRODUCT",
        linked_product_id="prod-does-not-exist",
    )

    assert result["error"] == "LINKED_PRODUCT_NOT_FOUND"


@pytest.mark.asyncio
async def test_claim_risk_duplicate_cannot_bypass_claim_gate():
    from agent.db import crud

    existing_product = await crud.create_product(
        raw_product_title="Claim Risk Canonical Product",
        source="MANUAL",
        product_display_name="Claim Risk Canonical Product",
        mapping_source="MANUAL_REVIEW",
    )
    await crud.create_bulk_queue_row(
        reference_id="ref-dup-claim-risk-001",
        raw_product_title="Claim Risk Duplicate",
        claim_risk_level="HIGH",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id=existing_product["id"],
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-claim-risk-001",
        action="LINK_TO_EXISTING_PRODUCT",
        linked_product_id=existing_product["id"],
    )

    assert result["error"] == "CLAIM_RISK_DUPLICATE_CANNOT_LINK"

    policy = await can_generate_content_for_fastmoss_reference(
        "ref-dup-claim-risk-001"
    )
    assert policy["content_generation_allowed"] is False
    assert policy["reason"] == "CLAIM_RISK_BLOCKS_CONTENT_GENERATION"


@pytest.mark.asyncio
async def test_mark_false_duplicate_requires_exact_confirmation_phrase():
    from agent.db import crud

    await crud.create_bulk_queue_row(
        reference_id="ref-dup-clear-phrase-001",
        raw_product_title="False Duplicate Phrase Gate",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id="prod-suspect-gate-001",
    )

    result = await resolve_duplicate_queue_row(
        "ref-dup-clear-phrase-001",
        action="MARK_FALSE_DUPLICATE",
        confirmation_phrase="WRONG_PHRASE",
    )

    assert result["error"] == "INVALID_FALSE_DUPLICATE_CONFIRMATION_PHRASE"


@pytest.mark.asyncio
async def test_mark_false_duplicate_recomputes_without_auto_approval(monkeypatch):
    from agent.db import crud

    reference_id = "ref-dup-clear-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="False Duplicate Recompute",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
        suspected_existing_product_id="prod-suspect-clear-001",
        error_message="DUPLICATE_CANDIDATE:prod-suspect-clear-001:TITLE_MATCH_EXISTING_PRODUCT",
    )

    async def _fake_recompute(ref_id: str):
        await crud.update_bulk_queue_row(
            ref_id,
            promotion_status="READY_FOR_APPROVAL",
            draft_id="draft-false-dup-001",
            committed_product_id=None,
            error_message=None,
            suspected_existing_product_id=None,
            suspected_existing_product_title=None,
            suspected_existing_product_source=None,
            suspected_existing_product_mapping_source=None,
            duplicate_match_reason=None,
        )
        return {
            "reference_id": ref_id,
            "promotion_status": "READY_FOR_APPROVAL",
            "draft_id": "draft-false-dup-001",
        }

    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.create_draft_from_reference",
        _fake_recompute,
    )

    result = await resolve_duplicate_queue_row(
        reference_id,
        action="MARK_FALSE_DUPLICATE",
        confirmation_phrase="CLEAR_DUPLICATE_FOR_REVIEW",
        note="Operator cleared duplicate blocker for recompute.",
    )

    assert result["new_status"] == "READY_FOR_APPROVAL"
    assert result["duplicate_resolution"] == "FALSE_DUPLICATE_CLEARED"
    assert result["content_generation_allowed"] is False
    assert result["message"] == "READY_FOR_APPROVAL_PREVIEW_ONLY"

    row = await crud.get_bulk_queue_row(reference_id)
    assert row is not None
    assert row["promotion_status"] == "READY_FOR_APPROVAL"
    assert row["committed_product_id"] is None
    assert row["duplicate_resolution"] == "FALSE_DUPLICATE_CLEARED"
    assert row["duplicate_ignore_product_id"] == "prod-suspect-clear-001"


@pytest.mark.asyncio
async def test_keep_blocked_preserves_duplicate_blocker():
    from agent.db import crud

    reference_id = "ref-dup-keep-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Keep Duplicate Blocked",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
    )

    result = await resolve_duplicate_queue_row(
        reference_id,
        action="KEEP_BLOCKED",
        note="Operator needs later review.",
    )

    assert result["new_status"] == "DUPLICATE_SUSPECTED"
    assert result["duplicate_resolution"] == "KEEP_BLOCKED"
    assert result["content_generation_allowed"] is False


@pytest.mark.asyncio
async def test_reject_reference_sets_rejected():
    from agent.db import crud

    reference_id = "ref-dup-reject-001"
    await crud.create_bulk_queue_row(
        reference_id=reference_id,
        raw_product_title="Reject Duplicate Reference",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="DUPLICATE_SUSPECTED",
    )

    result = await resolve_duplicate_queue_row(
        reference_id,
        action="REJECT_REFERENCE",
        note="Operator rejected duplicate reference.",
    )

    assert result["new_status"] == "REJECTED"
    assert result["duplicate_resolution"] == "REJECT_REFERENCE"
    assert result["content_generation_allowed"] is False


# ---------------------------------------------------------------------------
# Governance: raw lane blocker — raw FASTMOSS/FASTMOSS_REFERENCE cannot be committed
# ---------------------------------------------------------------------------


def test_classify_does_not_accept_unknown_risk_as_ready():
    status = _classify_promotion_status("UNKNOWN", "IMAGE_PRESENT", [], False)
    # UNKNOWN is not LOW → should not be READY_FOR_APPROVAL
    assert status != "READY_FOR_APPROVAL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_return(value):
    return value


# ---------------------------------------------------------------------------
# sync_bulk_queue — empty catalog / malformed rows / valid refs / idempotency
# ---------------------------------------------------------------------------

_REF_SVC = "agent.services.fastmoss_bulk_promotion_service.list_fastmoss_reference_products"


@pytest.mark.asyncio
async def test_sync_queue_empty_catalog_returns_zero_counts(monkeypatch):
    """Sync with empty reference catalog must return 200-shape with zero counts."""
    monkeypatch.setattr(_REF_SVC, AsyncMock(return_value=[]))
    result = await sync_bulk_queue()
    assert result["synced"] == 0
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert result["total_refs_loaded"] == 0
    assert "synced_at" in result


@pytest.mark.asyncio
async def test_sync_queue_skips_malformed_refs_no_crash(monkeypatch):
    """Refs missing id or raw_product_title increment errors and do not crash sync."""
    bad_refs = [
        {"id": "", "raw_product_title": "something"},
        {"id": "ref-x", "raw_product_title": ""},
        {"id": None, "raw_product_title": "test"},
    ]
    monkeypatch.setattr(_REF_SVC, AsyncMock(return_value=bad_refs))
    result = await sync_bulk_queue()
    assert result["errors"] == 3
    assert result["synced"] == 0
    assert result["total_refs_loaded"] == 3


@pytest.mark.asyncio
async def test_sync_queue_creates_rows_for_valid_refs(monkeypatch):
    """Valid FastMoss refs get inserted into fastmoss_bulk_draft_status."""
    valid_refs = [
        {
            "id": "ref-valid-001",
            "raw_product_title": "Test Serum",
            "image_url": "https://example.com/img.jpg",
            "source_url": "https://example.com/src",
            "tiktok_product_url": None,
            "claim_risk_level": "LOW",
            "category": "Beauty",
            "mapping_confidence": 0.9,
            "sold_count": 1000,
            "commission_rate": "10%",
            "fastmoss_source_file": "batch-001.xlsx",
        }
    ]
    monkeypatch.setattr(_REF_SVC, AsyncMock(return_value=valid_refs))
    result = await sync_bulk_queue()
    assert result["synced"] == 1
    assert result["skipped"] == 0
    assert result["errors"] == 0
    assert result["total_refs_loaded"] == 1


@pytest.mark.asyncio
async def test_sync_queue_idempotent(monkeypatch):
    """Running sync twice on the same refs skips already-queued rows."""
    valid_refs = [
        {
            "id": "ref-idem-001",
            "raw_product_title": "Idempotent Cream",
            "image_url": "https://example.com/img.jpg",
            "source_url": None,
            "tiktok_product_url": None,
            "claim_risk_level": "LOW",
        }
    ]
    mock = AsyncMock(return_value=valid_refs)
    monkeypatch.setattr(_REF_SVC, mock)
    first = await sync_bulk_queue()
    second = await sync_bulk_queue()
    assert first["synced"] == 1
    assert second["synced"] == 0
    assert second["skipped"] == 1


# ---------------------------------------------------------------------------
# DB migration — fastmoss_bulk_draft_status must exist after init_db()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_migration_creates_fastmoss_bulk_draft_status():
    """init_db() must create fastmoss_bulk_draft_status regardless of prior batch table state."""
    from agent.db.schema import get_db
    db = await get_db()
    cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='fastmoss_bulk_draft_status'"
    )
    row = await cursor.fetchone()
    assert row is not None, "fastmoss_bulk_draft_status table must exist after init_db()"


# ---------------------------------------------------------------------------
# CRUD whitelist — fastmoss_bulk_draft_status must be in _VALID_TABLES
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_bulk_queue_row_does_not_raise_invalid_table():
    """crud.update_bulk_queue_row must not raise ValueError 'Invalid table name'."""
    from agent.db import crud
    await crud.create_bulk_queue_row(
        reference_id="ref-whitelist-001",
        raw_product_title="Whitelist Patch Test",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )
    updated = await crud.update_bulk_queue_row(
        "ref-whitelist-001",
        promotion_status="NEEDS_REVIEW",
        draft_id="draft-test-999",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        updated_at="2026-05-19T00:00:00Z",
    )
    assert updated is not None, "update_bulk_queue_row returned None — table may still be missing from _VALID_TABLES"
    assert updated["promotion_status"] == "NEEDS_REVIEW"
    assert updated["draft_id"] == "draft-test-999"


@pytest.mark.asyncio
async def test_create_draft_from_reference_updates_queue_row(monkeypatch):
    """create_draft_from_reference must update the queue row without crashing on _validate_table."""
    from agent.db import crud
    from agent.services.fastmoss_bulk_promotion_service import create_draft_from_reference
    from unittest.mock import MagicMock

    # Seed a queue row so the function finds it
    await crud.create_bulk_queue_row(
        reference_id="ref-draft-test-001",
        raw_product_title="Draft Test Serum",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )

    _SVC = "agent.services.fastmoss_bulk_promotion_service"

    # Stub out the chain of dependencies after the queue row lookup
    monkeypatch.setattr(f"{_SVC}.list_fastmoss_reference_products", AsyncMock(return_value=[{
        "id": "ref-draft-test-001",
        "raw_product_title": "Draft Test Serum",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com",
        "tiktok_product_url": None,
        "claim_risk_level": "LOW",
        "commission_rate": "10%",
        "fastmoss_source_file": "batch.xlsx",
    }]))

    fake_draft = MagicMock()
    fake_draft.review_draft_id = "draft-generated-001"
    fake_draft.claim_risk_level = "LOW"
    fake_draft.missing_required_evidence = []
    fake_draft.declared_evidence_fields = {
        "product_name": "Draft Test Serum",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com",
        "tiktok_product_url": None,
    }
    fake_draft.provenance = []
    fake_draft.approval_checklist = {}
    fake_draft.model_dump = MagicMock(return_value={"review_draft_id": "draft-generated-001"})

    monkeypatch.setattr(f"{_SVC}.complete_product_knowledge", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(f"{_SVC}.create_registration_review_draft", MagicMock(return_value=fake_draft))
    monkeypatch.setattr(f"{_SVC}.derive_draft_image_asset_state", MagicMock(return_value=("IMAGE_READY", "ok")))
    monkeypatch.setattr(f"{_SVC}._detect_queue_duplicate", AsyncMock(return_value=False))

    saved = MagicMock()
    saved.review_draft_id = "draft-generated-001"
    saved.model_dump = MagicMock(return_value={"review_draft_id": "draft-generated-001"})
    from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
    monkeypatch.setattr(RegistrationDraftStorageService, "save_draft", MagicMock(return_value=saved))

    result = await create_draft_from_reference("ref-draft-test-001")
    assert "error" not in result, f"create_draft_from_reference failed: {result}"


@pytest.mark.asyncio
async def test_export_missing_as_csv_outputs_expected_columns(monkeypatch):
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.crud.list_bulk_queue",
        AsyncMock(
            return_value=[
                {
                    "reference_id": "ref-missing-001",
                    "draft_id": "draft-001",
                    "raw_product_title": "Missing Serum",
                    "category": "Beauty",
                    "tiktok_product_url": "https://tiktok.example/item",
                    "source_url": "https://source.example/item",
                    "image_url": "https://cdn.example/item.jpg",
                    "sold_count": 123,
                    "commission_rate": "15%",
                    "error_message": "MISSING:benefits_text,usage_text",
                }
            ]
        ),
    )

    csv_text = await export_missing_as_csv()
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(rows) == 1
    assert rows[0]["reference_id"] == "ref-missing-001"
    assert rows[0]["missing_fields"] == "benefits_text,usage_text"
    assert rows[0]["product_knowledge_text"] == ""
    assert rows[0]["warnings_text"] == ""


@pytest.mark.asyncio
async def test_import_enrichment_recomputes_missing_row(monkeypatch):
    row = {
        "reference_id": "ref-import-001",
        "raw_product_title": "Import Serum",
        "category": "Beauty",
        "image_url": "https://cdn.example/import.jpg",
        "source_url": "https://source.example/import",
        "tiktok_product_url": "https://tiktok.example/import",
        "commission_rate": "12%",
        "sold_count": 42,
        "duplicate_ignore_product_id": None,
    }
    saved_draft = _make_draft(
        declared_evidence_fields={
            "product_name": "Import Serum",
            "image_url": "https://cdn.example/import.jpg",
            "tiktok_product_url": "https://tiktok.example/import",
        },
        missing_required_evidence=[],
        claim_risk_level="LOW",
        claim_gate="CLAIM_SAFE",
        approval_checklist={},
    )
    update_mock = AsyncMock(return_value={})

    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.list_fastmoss_reference_products",
        AsyncMock(
            return_value=[
                {
                    "id": "ref-import-001",
                    "price": 29.9,
                    "currency": "MYR",
                    "raw_product_title": "Import Serum",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.crud.get_bulk_queue_row",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.complete_product_knowledge",
        MagicMock(return_value={"ok": True}),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.create_registration_review_draft",
        MagicMock(return_value=saved_draft),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.RegistrationDraftStorageService.save_draft",
        MagicMock(return_value=saved_draft),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service._detect_queue_duplicate_candidate",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "agent.services.fastmoss_bulk_promotion_service.crud.update_bulk_queue_row",
        update_mock,
    )

    result = await import_enrichment(
        [
            {
                "reference_id": "ref-import-001",
                "product_knowledge_text": "Hydrating serum for dry skin",
                "benefits_text": "Hydrates",
                "usage_text": "Apply nightly",
            }
        ]
    )

    assert result["recomputed"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["new_status"] == "READY_FOR_APPROVAL"
    assert result["results"][0]["draft_id"] == "draft-test-001"
    update_mock.assert_awaited()


@pytest.mark.asyncio
async def test_bulk_create_drafts_returns_success_not_all_error(monkeypatch):
    """bulk_create_drafts must return success > 0, not all ERROR."""
    _SVC = "agent.services.fastmoss_bulk_promotion_service"
    success_payload = {
        "reference_id": "ref-bc-001",
        "draft_id": "draft-bc-001",
        "promotion_status": "READY_FOR_APPROVAL",
        "claim_risk_level": "LOW",
        "image_readiness": "IMAGE_PRESENT",
        "draft": {"review_draft_id": "draft-bc-001"},
    }
    monkeypatch.setattr(
        f"{_SVC}.create_draft_from_reference",
        AsyncMock(return_value=success_payload),
    )
    result = await bulk_create_drafts(["ref-bc-001", "ref-bc-002"])
    assert result["success"] == 2, f"Expected 2 successes, got: {result}"
    assert result["failed"] == 0
    for r in result["results"]:
        assert r["status"] == "OK", f"Expected OK, got: {r}"


# ---------------------------------------------------------------------------
# _detect_queue_duplicate — governance policy
# Raw FASTMOSS reference rows must NOT block; MANUAL and FASTMOSS_PROMOTED must block.
# ---------------------------------------------------------------------------

_CRUD_SVC = "agent.services.fastmoss_bulk_promotion_service.crud"


@pytest.mark.asyncio
async def test_detect_dup_raw_fastmoss_not_a_blocker(monkeypatch):
    """Raw source=FASTMOSS catalog rows must NOT block promotion (self-match bug)."""
    raw_rows = [{"source": "FASTMOSS", "mapping_source": None,
                 "raw_product_title": "Test Serum", "product_display_name": "Test Serum",
                 "product_short_name": "Test Serum", "tiktok_product_url": None}]
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", AsyncMock(return_value=raw_rows))
    result = await _detect_queue_duplicate("ref-001", "Test Serum", None)
    assert result is False


@pytest.mark.asyncio
async def test_detect_dup_manual_row_blocks(monkeypatch):
    """source=MANUAL row with matching title must block promotion."""
    manual_rows = [{"source": "MANUAL", "mapping_source": None,
                    "raw_product_title": "Test Serum", "product_display_name": "Test Serum",
                    "product_short_name": "Test Serum", "tiktok_product_url": None}]
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", AsyncMock(return_value=manual_rows))
    result = await _detect_queue_duplicate("ref-001", "Test Serum", None)
    assert result is True


@pytest.mark.asyncio
async def test_detect_dup_fastmoss_promoted_committed_blocks(monkeypatch):
    """FASTMOSS row with mapping_source=FASTMOSS_PROMOTED must block (already committed)."""
    promoted_rows = [{"source": "FASTMOSS", "mapping_source": "FASTMOSS_PROMOTED",
                      "mapping_review_status": "REVIEWED_FASTMOSS_PROMOTED_COMMIT",
                      "raw_product_title": "Test Serum", "product_display_name": "Test Serum",
                      "product_short_name": "Test Serum", "tiktok_product_url": None}]
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", AsyncMock(return_value=promoted_rows))
    result = await _detect_queue_duplicate("ref-001", "Test Serum", None)
    assert result is True


@pytest.mark.asyncio
async def test_detect_dup_url_match_on_manual_blocks(monkeypatch):
    """TikTok product URL match on a MANUAL row must block even when titles differ."""
    manual_rows = [{"source": "MANUAL", "mapping_source": None,
                    "raw_product_title": "Different Title", "product_display_name": "Different",
                    "product_short_name": "Diff", "tiktok_product_url": "https://tiktok.com/prod/123"}]
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", AsyncMock(return_value=manual_rows))
    result = await _detect_queue_duplicate("ref-001", "Test Serum", "https://tiktok.com/prod/123")
    assert result is True


@pytest.mark.asyncio
async def test_detect_dup_empty_title_returns_false_no_query(monkeypatch):
    """Empty/whitespace raw_product_title must short-circuit to False without querying."""
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", mock)
    result = await _detect_queue_duplicate("ref-001", "   ", None)
    assert result is False
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_dup_no_matching_rows_returns_false(monkeypatch):
    """No rows returned from catalog → not a duplicate."""
    monkeypatch.setattr(f"{_CRUD_SVC}.list_products", AsyncMock(return_value=[]))
    result = await _detect_queue_duplicate("ref-001", "Test Serum", None)
    assert result is False


# ---------------------------------------------------------------------------
# _ref_to_completion_request — evidence mapping from FastMoss ref
# ---------------------------------------------------------------------------

from agent.services.fastmoss_bulk_promotion_service import _ref_to_completion_request


def test_ref_to_completion_maps_paste_knowledge():
    """_ref_to_completion_request must populate paste_anything_about_product from ref metadata."""
    ref = {
        "raw_product_title": "Serum Vitamin C 30ml",
        "category": "Beauty",
        "sold_count": 1500,
        "commission_rate": "12%",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com/src",
        "tiktok_product_url": None,
        "price": 29.9,
        "currency": "MYR",
    }
    req = _ref_to_completion_request(ref)
    assert req.paste_anything_about_product is not None
    assert "Serum Vitamin C 30ml" in req.paste_anything_about_product
    assert "Beauty" in req.paste_anything_about_product
    assert req.product_name == "Serum Vitamin C 30ml"
    assert req.source_lane == "FASTMOSS_PROMOTED"
    assert req.commission_rate == "12%"


def test_ref_to_completion_minimal_ref_no_crash():
    """_ref_to_completion_request must not crash on a ref with only id and title."""
    ref = {"raw_product_title": "Basic Lotion", "id": "ref-min-001"}
    req = _ref_to_completion_request(ref)
    assert req.product_name == "Basic Lotion"
    assert req.paste_anything_about_product is not None
    assert "Basic Lotion" in req.paste_anything_about_product


# ---------------------------------------------------------------------------
# create_draft_from_reference — error_message and READY_FOR_APPROVAL path
# ---------------------------------------------------------------------------

_SVC_PATH = "agent.services.fastmoss_bulk_promotion_service"


@pytest.mark.asyncio
async def test_create_draft_missing_field_stores_error_message(monkeypatch):
    """Queue row error_message must contain MISSING: fields when status is MISSING_REQUIRED_FIELD."""
    from agent.db import crud
    from agent.services.fastmoss_bulk_promotion_service import create_draft_from_reference
    from unittest.mock import MagicMock

    await crud.create_bulk_queue_row(
        reference_id="ref-missing-msg-001",
        raw_product_title="Test Serum",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )

    monkeypatch.setattr(f"{_SVC_PATH}.list_fastmoss_reference_products", AsyncMock(return_value=[{
        "id": "ref-missing-msg-001",
        "raw_product_title": "Test Serum",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com",
        "tiktok_product_url": None,
        "claim_risk_level": "LOW",
        "commission_rate": None,
        "fastmoss_source_file": None,
    }]))

    fake_draft = MagicMock()
    fake_draft.review_draft_id = "draft-mm-001"
    fake_draft.claim_risk_level = "LOW"
    fake_draft.claim_gate = "CLAIM_SAFE"
    fake_draft.claim_tokens = []
    fake_draft.missing_required_evidence = ["SIZE_OR_VOLUME_EVIDENCE", "COMMISSION_RATE_EVIDENCE"]
    fake_draft.declared_evidence_fields = {
        "product_name": "Test Serum",
        "image_url": "https://example.com/img.jpg",
    }
    fake_draft.provenance = []
    fake_draft.approval_checklist = {}
    fake_draft.model_dump = MagicMock(return_value={"review_draft_id": "draft-mm-001"})

    monkeypatch.setattr(f"{_SVC_PATH}.complete_product_knowledge", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(f"{_SVC_PATH}.create_registration_review_draft", MagicMock(return_value=fake_draft))
    monkeypatch.setattr(f"{_SVC_PATH}.derive_draft_image_asset_state", MagicMock(return_value=("IMAGE_READY", "ok")))
    monkeypatch.setattr(f"{_SVC_PATH}._detect_queue_duplicate", AsyncMock(return_value=False))

    saved = MagicMock()
    saved.review_draft_id = "draft-mm-001"
    saved.model_dump = MagicMock(return_value={"review_draft_id": "draft-mm-001"})
    from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
    monkeypatch.setattr(RegistrationDraftStorageService, "save_draft", MagicMock(return_value=saved))

    result = await create_draft_from_reference("ref-missing-msg-001")
    assert result.get("promotion_status") == "MISSING_REQUIRED_FIELD"

    row = await crud.get_bulk_queue_row("ref-missing-msg-001")
    assert row is not None
    assert row.get("error_message") is not None
    assert "MISSING:" in row["error_message"]
    assert "SIZE_OR_VOLUME_EVIDENCE" in row["error_message"]


@pytest.mark.asyncio
async def test_create_draft_claim_risk_stores_error_message(monkeypatch):
    """Queue row error_message must contain CLAIM_RISK info when claim gate blocks."""
    from agent.db import crud
    from agent.services.fastmoss_bulk_promotion_service import create_draft_from_reference
    from unittest.mock import MagicMock

    await crud.create_bulk_queue_row(
        reference_id="ref-claim-risk-001",
        raw_product_title="Ubat Kuat Lelaki Super",
        claim_risk_level="HIGH",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )

    monkeypatch.setattr(f"{_SVC_PATH}.list_fastmoss_reference_products", AsyncMock(return_value=[{
        "id": "ref-claim-risk-001",
        "raw_product_title": "Ubat Kuat Lelaki Super",
        "image_url": "https://example.com/img.jpg",
        "source_url": None,
        "tiktok_product_url": None,
        "claim_risk_level": "HIGH",
        "commission_rate": "10%",
        "fastmoss_source_file": None,
    }]))

    fake_draft = MagicMock()
    fake_draft.review_draft_id = "draft-cr-001"
    fake_draft.claim_risk_level = "HIGH"
    fake_draft.claim_gate = "CLAIM_REVIEW_REQUIRED"
    fake_draft.claim_tokens = ["kuat", "stamina"]
    fake_draft.missing_required_evidence = []
    fake_draft.declared_evidence_fields = {"product_name": "Ubat Kuat Lelaki Super", "image_url": "https://example.com/img.jpg"}
    fake_draft.provenance = []
    fake_draft.approval_checklist = {}
    fake_draft.model_dump = MagicMock(return_value={"review_draft_id": "draft-cr-001"})

    monkeypatch.setattr(f"{_SVC_PATH}.complete_product_knowledge", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(f"{_SVC_PATH}.create_registration_review_draft", MagicMock(return_value=fake_draft))
    monkeypatch.setattr(f"{_SVC_PATH}.derive_draft_image_asset_state", MagicMock(return_value=("IMAGE_READY", "ok")))
    monkeypatch.setattr(f"{_SVC_PATH}._detect_queue_duplicate", AsyncMock(return_value=False))

    saved = MagicMock()
    saved.review_draft_id = "draft-cr-001"
    saved.model_dump = MagicMock(return_value={"review_draft_id": "draft-cr-001"})
    from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
    monkeypatch.setattr(RegistrationDraftStorageService, "save_draft", MagicMock(return_value=saved))

    result = await create_draft_from_reference("ref-claim-risk-001")
    assert result.get("promotion_status") == "CLAIM_RISK"

    row = await crud.get_bulk_queue_row("ref-claim-risk-001")
    assert row is not None
    assert row.get("error_message") is not None
    assert "CLAIM_RISK" in row["error_message"]


@pytest.mark.asyncio
async def test_create_draft_low_risk_complete_becomes_ready(monkeypatch):
    """A LOW-risk FastMoss row with full evidence and no duplicate must become READY_FOR_APPROVAL."""
    from agent.db import crud
    from agent.services.fastmoss_bulk_promotion_service import create_draft_from_reference
    from unittest.mock import MagicMock

    await crud.create_bulk_queue_row(
        reference_id="ref-ready-001",
        raw_product_title="Serum Vitamin C 30ml",
        claim_risk_level="LOW",
        image_readiness="IMAGE_PRESENT",
        promotion_status="PENDING_DRAFT",
    )

    monkeypatch.setattr(f"{_SVC_PATH}.list_fastmoss_reference_products", AsyncMock(return_value=[{
        "id": "ref-ready-001",
        "raw_product_title": "Serum Vitamin C 30ml",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com/src",
        "tiktok_product_url": None,
        "claim_risk_level": "LOW",
        "category": "Beauty",
        "commission_rate": "12%",
        "fastmoss_source_file": "batch-001.xlsx",
    }]))

    fake_draft = MagicMock()
    fake_draft.review_draft_id = "draft-ready-001"
    fake_draft.claim_risk_level = "LOW"
    fake_draft.claim_gate = "CLAIM_SAFE"
    fake_draft.claim_tokens = []
    fake_draft.missing_required_evidence = []  # no missing fields
    fake_draft.declared_evidence_fields = {
        "product_name": "Serum Vitamin C 30ml",
        "image_url": "https://example.com/img.jpg",
        "source_url": "https://example.com/src",
        "category": "Beauty",
    }
    fake_draft.provenance = []
    fake_draft.approval_checklist = {}
    fake_draft.model_dump = MagicMock(return_value={"review_draft_id": "draft-ready-001"})

    monkeypatch.setattr(f"{_SVC_PATH}.complete_product_knowledge", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(f"{_SVC_PATH}.create_registration_review_draft", MagicMock(return_value=fake_draft))
    monkeypatch.setattr(f"{_SVC_PATH}.derive_draft_image_asset_state", MagicMock(return_value=("IMAGE_READY", "ok")))
    monkeypatch.setattr(f"{_SVC_PATH}._detect_queue_duplicate", AsyncMock(return_value=False))

    saved = MagicMock()
    saved.review_draft_id = "draft-ready-001"
    saved.model_dump = MagicMock(return_value={"review_draft_id": "draft-ready-001"})
    from agent.services.registration_draft_storage_service import RegistrationDraftStorageService
    monkeypatch.setattr(RegistrationDraftStorageService, "save_draft", MagicMock(return_value=saved))

    result = await create_draft_from_reference("ref-ready-001")
    assert result.get("promotion_status") == "READY_FOR_APPROVAL", (
        f"Expected READY_FOR_APPROVAL, got {result.get('promotion_status')}. "
        f"LOW-risk + IMAGE_PRESENT + no duplicates + no missing fields must be READY."
    )
    row = await crud.get_bulk_queue_row("ref-ready-001")
    assert row["promotion_status"] == "READY_FOR_APPROVAL"
    assert row["error_message"] is None
