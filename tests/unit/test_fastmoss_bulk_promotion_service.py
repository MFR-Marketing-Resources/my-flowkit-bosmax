"""
Unit tests for fastmoss_bulk_promotion_service.
Authority: docs/authority/working/BULK_FASTMOSS_PRODUCT_TRUTH_PROMOTION_PLAN_v0_1.md
Issue: #92
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from agent.services.fastmoss_bulk_promotion_service import (
    sync_bulk_queue,
    bulk_create_drafts,
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
    assert result["draft_id"] == "draft-generated-001"
    # Verify queue row was updated (update_bulk_queue_row must not raise)
    row = await crud.get_bulk_queue_row("ref-draft-test-001")
    assert row is not None
    assert row["draft_id"] == "draft-generated-001"
    assert row["promotion_status"] != "PENDING_DRAFT"


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
