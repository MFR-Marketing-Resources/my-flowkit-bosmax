import os
import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import patch
from agent.models.product_registration import RegistrationReviewDraft, RegistrationReviewDraftFieldDecisions
from agent.services.registration_draft_storage_service import RegistrationDraftStorageService

@pytest.fixture
def temp_draft_dir(tmp_path):
    with patch("agent.services.registration_draft_storage_service.PRODUCT_REGISTRATION_DRAFTS_DIR", tmp_path):
        yield tmp_path

def test_save_and_get_draft(temp_draft_dir):
    draft = RegistrationReviewDraft(
        review_draft_id="test-draft-123",
        review_status="REVIEW_READY",
        source_lane="MANUAL",
        declared_evidence_fields={"product_name": "Test Product"},
        canonical_candidate_fields={"normalized_name": "Test Product"}
    )
    
    saved = RegistrationDraftStorageService.save_draft(draft)
    assert saved.review_draft_id == "test-draft-123"
    assert saved.created_at is not None
    
    loaded = RegistrationDraftStorageService.get_draft("test-draft-123")
    assert loaded is not None
    assert loaded.review_draft_id == "test-draft-123"
    assert loaded.declared_evidence_fields["product_name"] == "Test Product"

def test_list_drafts(temp_draft_dir):
    draft1 = RegistrationReviewDraft(review_draft_id="d1", review_status="READY", source_lane="M")
    draft2 = RegistrationReviewDraft(review_draft_id="d2", review_status="READY", source_lane="M")
    
    RegistrationDraftStorageService.save_draft(draft1)
    RegistrationDraftStorageService.save_draft(draft2)
    
    drafts = RegistrationDraftStorageService.list_drafts()
    assert len(drafts) == 2
    ids = [d.review_draft_id for d in drafts]
    assert "d1" in ids
    assert "d2" in ids

def test_update_field_decisions(temp_draft_dir):
    draft = RegistrationReviewDraft(
        review_draft_id="d3",
        review_status="NEEDS_HUMAN_REVIEW",
        source_lane="MANUAL",
        human_review_fields=["category"],
        canonical_candidate_fields={"category": "Electronics"}
    )
    RegistrationDraftStorageService.save_draft(draft)
    
    decisions = RegistrationReviewDraftFieldDecisions(
        approved_fields=["category"],
        rejected_fields=[],
        edited_declared_evidence={},
        requested_more_evidence_fields=[]
    )
    
    updated = RegistrationDraftStorageService.update_field_decisions("d3", decisions)
    assert updated.approval_checklist["category"] is True
    assert "category" not in updated.human_review_fields
