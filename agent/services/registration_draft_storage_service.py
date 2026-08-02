import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal

from agent.config import DB_PATH, PRODUCT_REGISTRATION_DRAFTS_DIR
from agent.models.product_registration import (
    RegistrationReviewDraft,
    RegistrationReviewDraftFieldDecisions
)
from agent.services.registration_authority_fingerprint_service import (
    apply_authority_freshness,
)

class RegistrationDraftStorageService:
    _TABLE = "product_registration_review_draft"

    @staticmethod
    def _get_draft_path(draft_id: str) -> Path:
        return PRODUCT_REGISTRATION_DRAFTS_DIR / f"{draft_id}.json"

    @staticmethod
    def _database_location() -> str:
        return f"{Path(DB_PATH).name}:{RegistrationDraftStorageService._TABLE}"

    @staticmethod
    def _connect() -> sqlite3.Connection:
        connection = sqlite3.connect(str(DB_PATH), timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _from_payload(
        payload: str,
        *,
        storage_backend: Literal["LEGACY_JSON", "SQLITE_DATABASE"],
        storage_location: str,
    ) -> RegistrationReviewDraft:
        draft = RegistrationReviewDraft.model_validate_json(payload)
        draft.storage_backend = storage_backend
        draft.storage_location = storage_location
        return apply_authority_freshness(draft)

    @staticmethod
    def save_draft(draft: RegistrationReviewDraft) -> RegistrationReviewDraft:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not draft.created_at:
            draft.created_at = now
        draft.updated_at = now
        draft.storage_backend = "SQLITE_DATABASE"
        draft.storage_location = RegistrationDraftStorageService._database_location()
        payload_json = draft.model_dump_json()

        with closing(RegistrationDraftStorageService._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"""
                INSERT INTO {RegistrationDraftStorageService._TABLE}
                    (draft_id, review_status, source_lane, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    review_status=excluded.review_status,
                    source_lane=excluded.source_lane,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    draft.review_draft_id,
                    draft.review_status,
                    draft.source_lane,
                    payload_json,
                    draft.created_at,
                    draft.updated_at,
                ),
            )
            connection.commit()
        return draft

    @staticmethod
    def get_draft(draft_id: str) -> RegistrationReviewDraft | None:
        with closing(RegistrationDraftStorageService._connect()) as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {RegistrationDraftStorageService._TABLE} "
                "WHERE draft_id=?",
                (draft_id,),
            ).fetchone()
        if row:
            return RegistrationDraftStorageService._from_payload(
                row["payload_json"],
                storage_backend="SQLITE_DATABASE",
                storage_location=RegistrationDraftStorageService._database_location(),
            )

        path = RegistrationDraftStorageService._get_draft_path(draft_id)
        if not path.exists():
            return None
        return RegistrationDraftStorageService._from_payload(
            path.read_text(encoding="utf-8"),
            storage_backend="LEGACY_JSON",
            storage_location=f"data/product_registration/drafts/{path.name}",
        )

    @staticmethod
    def list_drafts() -> List[RegistrationReviewDraft]:
        drafts: list[RegistrationReviewDraft] = []
        persisted_ids: set[str] = set()
        with closing(RegistrationDraftStorageService._connect()) as connection:
            rows = connection.execute(
                f"SELECT draft_id, payload_json FROM {RegistrationDraftStorageService._TABLE}"
            ).fetchall()
        for row in rows:
            try:
                draft = RegistrationDraftStorageService._from_payload(
                    row["payload_json"],
                    storage_backend="SQLITE_DATABASE",
                    storage_location=RegistrationDraftStorageService._database_location(),
                )
            except Exception:
                continue
            persisted_ids.add(draft.review_draft_id)
            drafts.append(draft)

        if PRODUCT_REGISTRATION_DRAFTS_DIR.exists():
            for path in PRODUCT_REGISTRATION_DRAFTS_DIR.glob("*.json"):
                if path.stem in persisted_ids:
                    continue
                try:
                    drafts.append(
                        RegistrationDraftStorageService._from_payload(
                            path.read_text(encoding="utf-8"),
                            storage_backend="LEGACY_JSON",
                            storage_location=(
                                f"data/product_registration/drafts/{path.name}"
                            ),
                        )
                    )
                except Exception:
                    continue
        drafts.sort(key=lambda x: x.updated_at or "", reverse=True)
        return drafts

    @staticmethod
    def delete_draft(draft_id: str) -> bool:
        with closing(RegistrationDraftStorageService._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"DELETE FROM {RegistrationDraftStorageService._TABLE} WHERE draft_id=?",
                (draft_id,),
            )
            database_deleted = cursor.rowcount > 0
            connection.commit()

        path = RegistrationDraftStorageService._get_draft_path(draft_id)
        legacy_deleted = path.exists()
        if legacy_deleted:
            path.unlink()
        return database_deleted or legacy_deleted

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
