import json

import pytest

from agent.services.claim_safe_rewrite_service import (
    APPROVAL_PHRASE,
    STATUS_REVIEW_READY,
    approve_claim_safe_rewrite,
    preview_claim_safe_rewrite,
)


@pytest.mark.asyncio
async def test_preview_claim_safe_rewrite_detects_risky_male_health_claims(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["male_health_sensitive", "bahagian intim"],
        }

    class FakeDraft:
        def model_dump(self):
            return {
                "review_draft_id": "draft-bosmax-001",
                "updated_at": "2026-05-17T00:00:00Z",
                "declared_evidence_fields": {
                    "product_name": "Bosmax Herbs",
                    "benefits_text": "Meningkatkan stamina dan ketegangan di bahagian intim lelaki.",
                    "usage_text": "Urutan luaran pada bahagian intim lelaki.",
                },
                "canonical_candidate_fields": {"normalized_name": "Bosmax Herbs 5 ML"},
            }

        @property
        def declared_evidence_fields(self):
            return self.model_dump()["declared_evidence_fields"]

        @property
        def canonical_candidate_fields(self):
            return self.model_dump()["canonical_candidate_fields"]

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.claim_safe_rewrite_service.RegistrationDraftStorageService.list_drafts",
        lambda: [FakeDraft()],
    )

    preview = await preview_claim_safe_rewrite("prod-bosmax")

    assert preview["claim_safe_copy_status"] == "CLAIM_SAFE_COPY_PREVIEW_ONLY"
    assert preview["approval_required"] is True
    assert "bahagian intim" in " ".join(preview["unsafe_claims_detected"]).casefold()
    assert "male_health_sensitive" in preview["risky_claim_tokens"]
    assert "ubat kuat" not in preview["safe_claim_rewrite"].casefold()


@pytest.mark.asyncio
async def test_approve_claim_safe_rewrite_persists_review_ready_package(monkeypatch):
    stored_updates = {}

    async def fake_get_product(product_id: str):
        base = {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["male_health_sensitive"],
            "updated_at": "2026-05-17T04:00:00Z",
        }
        base.update(stored_updates)
        return base

    async def fake_update_product(product_id: str, **kwargs):
        stored_updates.update(kwargs)
        stored_updates["updated_at"] = "2026-05-17T05:00:00Z"
        return {"id": product_id, **stored_updates}

    class FakeDraft:
        def model_dump(self):
            return {
                "review_draft_id": "draft-bosmax-001",
                "updated_at": "2026-05-17T00:00:00Z",
                "declared_evidence_fields": {
                    "product_name": "Bosmax Herbs",
                    "benefits_text": "Meningkatkan stamina dan ketegangan.",
                },
                "canonical_candidate_fields": {"normalized_name": "Bosmax Herbs 5 ML"},
            }

        @property
        def declared_evidence_fields(self):
            return self.model_dump()["declared_evidence_fields"]

        @property
        def canonical_candidate_fields(self):
            return self.model_dump()["canonical_candidate_fields"]

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.update_product", fake_update_product)
    monkeypatch.setattr(
        "agent.services.claim_safe_rewrite_service.RegistrationDraftStorageService.list_drafts",
        lambda: [FakeDraft()],
    )

    approved = await approve_claim_safe_rewrite("prod-bosmax", APPROVAL_PHRASE)

    assert approved["claim_safe_copy_status"] == STATUS_REVIEW_READY
    assert stored_updates["claim_safe_copy_status"] == STATUS_REVIEW_READY
    payload = json.loads(stored_updates["claim_safe_copy_payload"])
    assert payload["approval_required"] is True
    assert payload["production_generation_allowed"] is False
