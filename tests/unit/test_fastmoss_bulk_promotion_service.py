"""
Unit tests for fastmoss_bulk_promotion_service.
Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue: #92
"""
from __future__ import annotations

import pytest

from agent.services.fastmoss_bulk_promotion_service import (
    _classify_promotion_status,
    _derive_image_readiness,
    _apply_lineage_to_draft,
    _ref_to_completion_request,
    bulk_approve_drafts,
    update_queue_row_status,
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
