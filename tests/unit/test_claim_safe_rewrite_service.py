import json

import pytest

from agent.services.claim_safe_rewrite_service import (
    APPROVAL_PHRASE,
    STATUS_REVIEW_READY,
    approve_claim_safe_rewrite,
    get_stored_claim_safe_package,
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


@pytest.mark.asyncio
async def test_get_stored_claim_safe_package_refreshes_legacy_payload(monkeypatch):
    stored_updates = {}

    async def fake_get_product(product_id: str):
        base = {
            "id": product_id,
            "raw_product_title": "Pentavite UPGRADED Multivitamin Lelaki",
            "product_display_name": "[Amelia's Favourite] [Preorder 25 Days] Pentavite UPGRADED Multivitamin Lelaki",
            "section_6_copy_hint": "Multivitamin harian untuk lelaki aktif. Mengandungi 20 nutrien penting untuk tenaga dan kesihatan keseluruhan.",
            "copywriting_angle": "Trust-led health framing",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["health", "vitamin"],
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
            "claim_safe_copy_updated_at": "2026-05-18T04:51:33Z",
            "claim_safe_copy_payload": json.dumps(
                {
                    "product_id": product_id,
                    "product_name": "[Amelia's Favourite] [Preorder 25 Days] Pentavite UPGRADED Multivitamin Lelaki",
                    "safe_claim_rewrite": "Pentavite diposisikan sebagai produk kegunaan harian yang bertanggungjawab.",
                    "safe_hook_angles": [
                        "Tonjolkan Pentavite sebagai produk kegunaan harian yang bertanggungjawab."
                    ],
                    "safe_usp_list": ["Pentavite dibingkaikan sebagai produk kegunaan harian."],
                    "safe_cta_angles": ["Lihat bagaimana Pentavite dipersembahkan sebagai produk harian."],
                    "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
                    "approval_required": False,
                    "approved_at": "2026-05-18T04:51:33Z",
                    "approval_note": "Auto-approved sanitized claim-safe package for workspace generation.",
                    "production_generation_allowed": False,
                    "provenance": [
                        "claim_safe_rewrite_service:v1",
                        f"product_id:{product_id}",
                        "claim_safe_copy:auto_approved_low_risk",
                    ],
                },
                ensure_ascii=False,
            ),
        }
        base.update(stored_updates)
        return base

    async def fake_update_product(product_id: str, **kwargs):
        stored_updates.update(kwargs)
        return {"id": product_id, **stored_updates}

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.update_product", fake_update_product)
    monkeypatch.setattr(
        "agent.services.claim_safe_rewrite_service.RegistrationDraftStorageService.list_drafts",
        lambda: [],
    )

    payload = await get_stored_claim_safe_package("prod-pentavite")

    assert payload is not None
    assert payload["claim_safe_copy_status"] == "CLAIM_SAFE_COPY_APPROVED"
    assert payload["address_style"] == "SAYA_ABANG"
    assert "diposisikan sebagai" not in payload["safe_claim_rewrite"].casefold()
    assert "tonjolkan" not in " ".join(payload["safe_hook_angles"]).casefold()
    assert "lihat bagaimana" not in " ".join(payload["safe_cta_angles"]).casefold()
    assert "claim_safe_rewrite_service:v2" in payload["provenance"]
    assert "claim_safe_copy:refreshed_from_legacy_payload" in payload["provenance"]
    assert payload["approval_required"] is False
    assert stored_updates["claim_safe_copy_status"] == "CLAIM_SAFE_COPY_APPROVED"


@pytest.mark.asyncio
async def test_get_stored_claim_safe_package_returns_current_payload_without_refresh(monkeypatch):
    updates_called = False
    current_payload = {
        "product_id": "prod-current",
        "product_name": "Glad2Glow Brightening Lip Serum 7g",
        "safe_claim_rewrite": "Pada saya, Glad2Glow Brightening Lip Serum 7g ni sesuai je untuk rutin serum harian.",
        "safe_hook_angles": [
            "Akak, kalau tengah cari untuk serum harian - saya dah cuba Glad2Glow Brightening Lip Serum 7g ni dan memang okay.",
        ],
        "safe_usp_list": [
            "Yang saya suka pasal Glad2Glow Brightening Lip Serum 7g - nampak sesuai untuk rutin serum harian akak.",
        ],
        "safe_cta_angles": [
            "Kalau akak tengah cari untuk serum harian, boleh la try Glad2Glow Brightening Lip Serum 7g ni dulu.",
        ],
        "address_style": "SAYA_AKAK",
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
        "provenance": [
            "claim_safe_rewrite_service:v2",
            "product_id:prod-current",
        ],
    }

    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
            "claim_safe_copy_updated_at": "2026-05-22T10:00:00Z",
            "claim_safe_copy_payload": json.dumps(current_payload, ensure_ascii=False),
        }

    async def fake_update_product(product_id: str, **kwargs):
        nonlocal updates_called
        updates_called = True
        return {"id": product_id, **kwargs}

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.update_product", fake_update_product)

    payload = await get_stored_claim_safe_package("prod-current")

    assert payload is not None
    assert payload["address_style"] == "SAYA_AKAK"
    assert payload["claim_safe_copy_updated_at"] == "2026-05-22T10:00:00Z"
    assert updates_called is False
