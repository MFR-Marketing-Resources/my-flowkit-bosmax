import json

import pytest

from agent.services.claim_safe_rewrite_service import (
    APPROVAL_PHRASE,
    REVIEW_DECISION_APPROVE_CANDIDATE,
    REVIEW_DECISION_DO_NOT_APPROVE,
    REVIEW_DECISION_HOLD_SENSITIVE_REVIEW,
    STATUS_REVIEW_READY,
    _detect_address_style,
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
    assert preview["review_decision"] == REVIEW_DECISION_DO_NOT_APPROVE
    assert preview["approval_after_operator_review"] is False
    assert "bahagian intim" in " ".join(preview["unsafe_claims_detected"]).casefold()
    assert "male_health_sensitive" in preview["risky_claim_tokens"]
    assert "ubat kuat" not in preview["safe_claim_rewrite"].casefold()


@pytest.mark.asyncio
async def test_preview_claim_safe_rewrite_strips_metadata_and_first_person_framing(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Mini USB LED Plug Lamp Mobile Power Charging USB Night Light Eye Protection Reading Bulb Indoor Bedroom Sleeping",
            "product_display_name": "Mini USB LED Plug Lamp Mobile Power Charging USB Night Light Eye Protection Reading Bulb Indoor Bedroom Sleeping",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": [],
        }

    class FakeDraft:
        def model_dump(self):
            return {
                "review_draft_id": "draft-lamp-001",
                "updated_at": "2026-05-17T00:00:00Z",
                "declared_evidence_fields": {
                    "benefits_text": "Lampu USB ringkas untuk bacaan meja dan kegunaan ruang tidur.",
                    "paste_anything_about_product": "Product: Lamp USB | Category: Lighting | Sold count: 88 | Commission: 12%",
                },
                "canonical_candidate_fields": {"normalized_name": "Mini USB LED Plug Lamp"},
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

    preview = await preview_claim_safe_rewrite("prod-lamp")
    combined = " ".join(
        [
            preview["safe_claim_rewrite"],
            preview["safe_hook"],
            preview["safe_subhook"],
            *preview["safe_hook_angles"],
            *preview["safe_usp_list"],
            *preview["safe_cta_angles"],
        ]
    ).casefold()

    assert preview["review_decision"] == REVIEW_DECISION_APPROVE_CANDIDATE
    assert preview["approval_after_operator_review"] is True
    assert "category:" not in combined
    assert "sold count" not in combined
    assert "commission" not in combined
    assert "eye protection" not in combined
    assert "saya dah cuba" not in combined
    assert "aku dah try" not in combined


@pytest.mark.asyncio
async def test_approve_claim_safe_rewrite_persists_review_ready_package_for_low_risk_preview(monkeypatch):
    stored_updates = {}

    async def fake_get_product(product_id: str):
        base = {
            "id": product_id,
            "raw_product_title": "Portable Handheld Fan USB Rechargeable Mini Cooling Fan",
            "product_display_name": "Portable Handheld Fan USB Rechargeable Mini Cooling Fan",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": [],
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
                "review_draft_id": "draft-fan-001",
                "updated_at": "2026-05-17T00:00:00Z",
                "declared_evidence_fields": {
                    "product_name": "Portable Handheld Fan",
                    "benefits_text": "Kipas mudah dibawa untuk kegunaan meja, perjalanan, dan ruang kerja.",
                },
                "canonical_candidate_fields": {"normalized_name": "Portable Handheld Fan USB Rechargeable Mini Cooling Fan"},
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

    approved = await approve_claim_safe_rewrite("prod-fan", APPROVAL_PHRASE)

    assert approved["claim_safe_copy_status"] == STATUS_REVIEW_READY
    assert approved["review_decision"] == REVIEW_DECISION_APPROVE_CANDIDATE
    assert approved["approval_after_operator_review"] is True
    assert stored_updates["claim_safe_copy_status"] == STATUS_REVIEW_READY
    payload = json.loads(stored_updates["claim_safe_copy_payload"])
    assert payload["approval_required"] is True
    assert payload["production_generation_allowed"] is False
    assert "saya sendiri guna" not in json.dumps(payload, ensure_ascii=False).casefold()


@pytest.mark.asyncio
async def test_approve_claim_safe_rewrite_blocks_non_approvable_preview(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Bosmax Herbs 5 ML",
            "product_display_name": "Bosmax Herbs 5 ML",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": ["male_health_sensitive"],
            "updated_at": "2026-05-17T04:00:00Z",
        }

    class FakeDraft:
        def model_dump(self):
            return {
                "review_draft_id": "draft-bosmax-001",
                "updated_at": "2026-05-17T00:00:00Z",
                "declared_evidence_fields": {
                    "product_name": "Bosmax Herbs",
                    "benefits_text": "Meningkatkan stamina dan ketegangan di bahagian intim lelaki.",
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

    with pytest.raises(PermissionError, match="CLAIM_SAFE_REVIEW_BLOCKED:DO_NOT_APPROVE"):
        await approve_claim_safe_rewrite("prod-bosmax", APPROVAL_PHRASE)


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
    assert "claim_safe_rewrite_service:v3" in payload["provenance"]
    assert "claim_safe_copy:refreshed_from_legacy_payload" in payload["provenance"]
    assert payload["approval_required"] is False
    assert stored_updates["claim_safe_copy_status"] == "CLAIM_SAFE_COPY_APPROVED"


@pytest.mark.asyncio
async def test_get_stored_claim_safe_package_returns_current_payload_without_refresh(monkeypatch):
    updates_called = False
    current_payload = {
        "product_id": "prod-current",
        "product_name": "Glad2Glow Brightening Lip Serum 7g",
        "safe_claim_rewrite": "Glad2Glow Brightening Lip Serum 7g dengan fokus pada penggunaan asas yang ringkas.",
        "safe_hook_angles": [
            "Glad2Glow Brightening Lip Serum 7g dengan ciri utama yang mudah difahami.",
        ],
        "safe_usp_list": [
            "Penerangan produk kekal fokus pada ciri asas tanpa janji berlebihan.",
        ],
        "safe_cta_angles": [
            "Semak ciri utama Glad2Glow Brightening Lip Serum 7g sebelum membuat pilihan.",
        ],
        "address_style": "SAYA_AKAK",
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_REVIEW_READY",
        "review_decision": REVIEW_DECISION_APPROVE_CANDIDATE,
        "provenance": [
            "claim_safe_rewrite_service:v3",
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


@pytest.mark.asyncio
async def test_preview_claim_safe_rewrite_holds_sensitive_devotional_products(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Buku Zikir & Wirid Harian Rasulullah by Ustaz Wadi Annuar",
            "product_display_name": "Buku Zikir & Wirid Harian Rasulullah by Ustaz Wadi Annuar",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": [],
        }

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.claim_safe_rewrite_service.RegistrationDraftStorageService.list_drafts",
        lambda: [],
    )

    preview = await preview_claim_safe_rewrite("prod-zikir")

    assert preview["review_decision"] == REVIEW_DECISION_HOLD_SENSITIVE_REVIEW
    assert preview["approval_after_operator_review"] is False
    assert preview["sensitive_review"]["status"] == "SENIOR_SENSITIVE_REVIEW_REQUIRED"


@pytest.mark.asyncio
async def test_preview_claim_safe_rewrite_flags_obvious_mapping_mismatch(monkeypatch):
    async def fake_get_product(product_id: str):
        return {
            "id": product_id,
            "raw_product_title": "Set Jarum Keluli Hidung, Saiz Besar, 34 Keping, untuk Menjahit Pakaian dan Kuilt",
            "product_display_name": "Set Jarum Keluli Hidung, Saiz Besar, 34 Keping, untuk Menjahit Pakaian dan Kuilt",
            "category": "Home Supplies",
            "subcategory": "Festive & Party Supplies",
            "type": "Party Bags & Gifts",
            "source": "MANUAL",
            "claim_gate": "CLAIM_REVIEW_REQUIRED",
            "claim_tokens": [],
        }

    monkeypatch.setattr("agent.services.claim_safe_rewrite_service.crud.get_product", fake_get_product)
    monkeypatch.setattr(
        "agent.services.claim_safe_rewrite_service.RegistrationDraftStorageService.list_drafts",
        lambda: [],
    )

    preview = await preview_claim_safe_rewrite("prod-needle")

    assert preview["review_decision"] == REVIEW_DECISION_DO_NOT_APPROVE
    assert preview["approval_after_operator_review"] is False
    assert preview["mapping_review"]["status"] == "MAPPING_REPAIR_REQUIRED"
    assert "party-gift taxonomy" in preview["mapping_review"]["reason"].casefold()


# ---------------------------------------------------------------------------
# _detect_address_style — gender mapping unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,text_blocks,expected",
    [
        # Women's Malay traditional fashion
        (
            "Bidasari Kurung Cotton Embroidery Cutwork",
            ["Baju kurung moden untuk wanita"],
            "SAYA_AKAK",
        ),
        # Women's fashion — kebaya
        (
            "Kebaya Labuh Chiffon Premium",
            [],
            "SAYA_AKAK",
        ),
        # Women's fashion — hijab / tudung
        (
            "Hijab Instant Bawal Cotton XL",
            ["Tudung bawal premium untuk akak"],
            "SAYA_AKAK",
        ),
        # Women's fashion — blouse / dress
        (
            "Floral Blouse Muslimah",
            ["blouse labuh untuk ibu"],
            "SAYA_AKAK",
        ),
        # Baby product — diapers (primary buyer = mother)
        (
            "MamyPoko Baby Diapers M50",
            ["lampin pakai buang untuk bayi"],
            "SAYA_AKAK",
        ),
        # Baby product — susu ibu / breastfeed
        (
            "Lansinoh HPA Lanolin Nipple Cream",
            ["Untuk ibu yang menyusukan bayi, breastfeed friendly"],
            "SAYA_AKAK",
        ),
        # Baby product — kanak-kanak apparel
        (
            "Baju Kanak-Kanak Cotton 3pcs Set",
            [],
            "SAYA_AKAK",
        ),
        # Men's supplement — SAYA_ABANG
        (
            "TestoPower Supplement Lelaki",
            ["vitamin untuk lelaki aktif, testosterone booster"],
            "SAYA_ABANG",
        ),
        # Men's product explicit signal
        (
            "ProShave Foam Men 200ml",
            ["untuk lelaki, stamina lelaki"],
            "SAYA_ABANG",
        ),
        # Generic product — no gender signal → AKU_KORANG
        (
            "Vitamin C 1000mg Tablet",
            ["supplement harian untuk semua"],
            "AKU_KORANG",
        ),
        # Skincare / beauty still maps to SAYA_AKAK
        (
            "Glow Lab Brightening Serum",
            ["skincare untuk rutin harian"],
            "SAYA_AKAK",
        ),
    ],
)
def test_detect_address_style_gender_signals(title: str, text_blocks: list, expected: str):
    result = _detect_address_style(title, text_blocks)
    assert result == expected, (
        f"Product '{title}' → expected {expected} but got {result}"
    )
