import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from agent.config import PRODUCT_REGISTRATION_DRAFTS_DIR
from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationReviewDraftFieldDecisions
)

class RegistrationDraftStorageService:
    @staticmethod
    def _get_draft_path(draft_id: str) -> Path:
        return PRODUCT_REGISTRATION_DRAFTS_DIR / f"{draft_id}.json"

    @staticmethod
    def save_draft(draft: RegistrationReviewDraft) -> RegistrationReviewDraft:
        if not PRODUCT_REGISTRATION_DRAFTS_DIR.exists():
            PRODUCT_REGISTRATION_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not draft.created_at:
            draft.created_at = now
        draft.updated_at = now
        
        path = RegistrationDraftStorageService._get_draft_path(draft.review_draft_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(draft.model_dump_json(indent=2))
        return draft

    @staticmethod
    def get_draft(draft_id: str) -> RegistrationReviewDraft | None:
        path = RegistrationDraftStorageService._get_draft_path(draft_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return RegistrationReviewDraft.model_validate(data)

    @staticmethod
    def list_drafts() -> List[RegistrationReviewDraft]:
        if not PRODUCT_REGISTRATION_DRAFTS_DIR.exists():
            return []
        drafts = []
        for path in PRODUCT_REGISTRATION_DRAFTS_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    drafts.append(RegistrationReviewDraft.model_validate(data))
            except Exception:
                continue
        # Sort by updated_at descending
        drafts.sort(key=lambda x: x.updated_at or "", reverse=True)
        return drafts

    @staticmethod
    def delete_draft(draft_id: str) -> bool:
        path = RegistrationDraftStorageService._get_draft_path(draft_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def update_field_decisions(draft_id: str, decisions: RegistrationReviewDraftFieldDecisions) -> RegistrationReviewDraft | None:
        draft = RegistrationDraftStorageService.get_draft(draft_id)
        if not draft:
            return None
            
        # Update approval checklist
        for field in decisions.approved_fields:
            draft.approval_checklist[field] = True
            if field in draft.rejection_checklist:
                draft.rejection_checklist[field] = False
                
        # Update rejection checklist
        for field in decisions.rejected_fields:
            draft.rejection_checklist[field] = True
            if field in draft.approval_checklist:
                draft.approval_checklist[field] = False
                
        # Update human review fields (remove if approved/rejected)
        reviewed_fields = set(decisions.approved_fields + decisions.rejected_fields)
        draft.human_review_fields = [f for f in draft.human_review_fields if f not in reviewed_fields]
        
        # Add requested evidence fields
        if decisions.requested_more_evidence_fields:
            draft.missing_required_evidence = list(set(draft.missing_required_evidence + decisions.requested_more_evidence_fields))

        return RegistrationDraftStorageService.save_draft(draft)
