import pytest

from agent.db import crud
from agent.services import product_intelligence_snapshot_service as snapshot_svc
from agent.services import product_intelligence_review_draft_service as svc
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewDraftRejectRequest,
    ProductIntelligenceReviewDraftUpdateRequest,
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
async def test_supersede_open_then_create_does_not_violate_unique():
    """Regression: a product may already hold one open draft (single-open-draft
    partial unique index). Superseding it first lets a fresh INSERT succeed instead
    of raising IntegrityError -> HTTP 500 (the Prepare-with-AI crash)."""
    product = await crud.create_product(
        raw_product_title="Bosmax Open Draft Collision",
        source="MANUAL",
        product_display_name="Bosmax Open Draft Collision",
        product_short_name="Bosmax Open Draft Collision",
    )
    first = await svc.create_review_draft(product["id"], _safe_request())
    assert first.review_status not in ("APPROVED", "REJECTED", "SUPERSEDED")

    superseded_count = await svc.supersede_open_review_drafts(
        product["id"], reason="regen", actor="test"
    )
    assert superseded_count == 1

    second = await svc.create_review_draft(product["id"], _safe_request())
    assert second.draft_id != first.draft_id

    first_after = await svc.get_review_draft_by_id(first.draft_id)
    assert first_after is not None
    assert first_after.review_status == "SUPERSEDED"


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


# ── allow_incomplete_product_knowledge: approve for COPY grounding ────────────
def _copy_ready_request(**kw) -> ProductIntelligenceReviewDraftCreateRequest:
    """Every COPY-critical field present, including the non-waivable claim boundary,
    but no optional product-knowledge fields (usage/ingredients/warnings) —
    exactly the shape the COPYWRITING HUB bulk importer produces."""
    base = {
        "product_description": "Pocket perfume with a long-lasting floral scent.",
        "benefits_json": ["tahan lama sepanjang hari", "wangian floral"],
        "usp_json": ["floral amber notes", "gift box"],
        "target_customer_text": "Wanita 18-40 yang mahu wangian tahan lama.",
        "allowed_claims_json": ["portable daily carry"],
        "buyer_persona_snapshot_json": {
            "audience": "wanita 18-40",
            "pains": ["wangi cepat hilang", "susah cari hadiah"],
        },
        "copy_strategy_summary_json": {"angles": ["tahan lama", "sesuai hadiah"]},
        "created_by": "COPYWRITING_HUB_BULK_IMPORT",
    }
    base.update(kw)
    return ProductIntelligenceReviewDraftCreateRequest(**base)


@pytest.mark.asyncio
async def test_allow_incomplete_product_knowledge_approves_copy_ready_draft():
    product = await crud.create_product(
        raw_product_title="Copy Ready Perfume",
        source="MANUAL",
        product_display_name="Copy Ready Perfume",
    )
    draft = await svc.create_review_draft(product["id"], _copy_ready_request())
    # Missing usage/ingredients/warnings -> strict approve blocks.
    with pytest.raises(ValueError, match="MISSING_REQUIRED_FIELDS"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="op"),
        )
    # But every COPY-critical field is present -> the opt-in flag approves.
    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(
            approved_by="op", allow_incomplete_product_knowledge=True,
        ),
    )
    assert approved.status == "APPROVED"
    assert approved.created_from_review_draft_id == draft.draft_id

@pytest.mark.asyncio
async def test_allow_incomplete_never_waives_empty_allowed_claims():
    product = await crud.create_product(
        raw_product_title="Copy Missing Claim Boundary",
        source="MANUAL",
        product_display_name="Copy Missing Claim Boundary",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _copy_ready_request(allowed_claims_json=[]),
    )
    with pytest.raises(
        ValueError,
        match="MISSING_COPY_CRITICAL_FIELDS:allowed_claims_json",
    ):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(
                approved_by="op",
                allow_incomplete_product_knowledge=True,
            ),
        )



@pytest.mark.asyncio
async def test_allow_incomplete_still_blocks_when_copy_critical_field_missing():
    product = await crud.create_product(
        raw_product_title="Copy Missing Desc",
        source="MANUAL",
        product_display_name="Copy Missing Desc",
    )
    # product_description is COPY-critical; empty -> flag must NOT approve.
    draft = await svc.create_review_draft(
        product["id"], _copy_ready_request(product_description=""),
    )
    with pytest.raises(ValueError, match="MISSING_COPY_CRITICAL_FIELDS:.*product_description"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(
                approved_by="op", allow_incomplete_product_knowledge=True,
            ),
        )


@pytest.mark.asyncio
async def test_allow_incomplete_does_not_bypass_claim_blocked():
    product = await crud.create_product(
        raw_product_title="Copy Ready Blocked",
        source="MANUAL",
        product_display_name="Copy Ready Blocked",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _copy_ready_request(
            product_description="Guaranteed relief untuk penyakit dan sembuh cepat.",
        ),
    )
    # Flag relaxes product-knowledge only; a CLAIM_BLOCKED gate still stops it dead.
    with pytest.raises(ValueError, match="CLAIM_BLOCKED"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(
                approved_by="op", allow_incomplete_product_knowledge=True,
            ),
        )


@pytest.mark.asyncio
async def test_allow_incomplete_does_not_auto_acknowledge_claim_review():
    product = await crud.create_product(
        raw_product_title="Copy Ready Review",
        source="MANUAL",
        product_display_name="Copy Ready Review",
    )
    draft = await svc.create_review_draft(
        product["id"],
        _copy_ready_request(
            product_description="Anti-inflammatory comfort positioning for review.",
        ),
    )
    assert draft.claim_gate == "CLAIM_REVIEW_REQUIRED"
    # allow_incomplete does NOT acknowledge claims -> still blocked...
    with pytest.raises(ValueError, match="CLAIM_REVIEW_REQUIRED"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(
                approved_by="op", allow_incomplete_product_knowledge=True,
            ),
        )
    # ...only the explicit acknowledgement (plus the flag) approves it.
    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(
            approved_by="op",
            allow_incomplete_product_knowledge=True,
            claim_review_acknowledged=True,
        ),
    )
    assert approved.status == "APPROVED"
    refreshed = await svc.get_review_draft_by_id(draft.draft_id)
    assert "CLAIM_REVIEW_ACKNOWLEDGED: op acknowledged" in (
        refreshed.reviewer_note or "")


# ── AI Fill Missing (DeepSeek-backed) — provider mocked, never spends credits ──
def _fake_fields_payload():
    return {"fields": {
        "product_description": {"value": "Stainless steel insulated bottle.", "status": "FACT", "confidence": 0.9, "rationale": "title"},
        "benefits_json": {"value": ["Keeps drinks cold for hours"], "status": "INFERENCE", "confidence": 0.6, "rationale": "category"},
        "usp_json": {"value": ["Double-wall vacuum insulation"], "status": "INFERENCE", "confidence": 0.5, "rationale": "category"},
        "usage_text": {"value": "Fill with a beverage and seal the lid.", "status": "FACT", "confidence": 0.8, "rationale": "form"},
        "target_customer_text": {"value": "Commuters who want a reusable bottle.", "status": "INFERENCE", "confidence": 0.7, "rationale": "avatar"},
        "ingredients_text": {"value": "Food-grade stainless steel body.", "status": "FACT", "confidence": 0.8, "rationale": "material"},
        "warnings_text": {"value": "Hand wash only.", "status": "INFERENCE", "confidence": 0.5, "rationale": "care"},
    }}


def _mock_provider(monkeypatch, *, configured=True, payload=None, capture=None):
    from agent.services import ai_copy_provider_adapter as prov
    monkeypatch.setattr(prov, "is_configured", lambda lane="structure": configured)
    monkeypatch.setattr(prov, "provider_status", lambda lane="structure": {
        "lane": "structure", "configured": configured,
        "provider_id": "deepseek", "model_id": "deepseek-chat", "execution_enabled": configured,
    })

    def fake_complete_json(system, user, **kwargs):
        if capture is not None:
            capture["system"] = system
            capture["user"] = user
        return payload if payload is not None else _fake_fields_payload()

    monkeypatch.setattr(prov, "complete_json", fake_complete_json)
    return prov


async def _empty_draft(product_id):
    return await svc.create_review_draft(
        product_id,
        ProductIntelligenceReviewDraftCreateRequest(
            buyer_persona_snapshot_json={"audience": "commuters"}, created_by="promo"
        ),
    )


async def _count_table(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_ai_fill_fills_only_empty_fields_records_provenance_no_snapshot(monkeypatch):
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bottle", product_display_name="Bottle",
        product_short_name="Bottle", copywriting_angle="x",
    )
    draft = await _empty_draft(product["id"])
    capture = {}
    _mock_provider(monkeypatch, capture=capture)

    snaps_before = await _count_table("product_intelligence_snapshot")
    cs_before = await _count_table("copy_set")

    result = await svc.ai_fill_missing_review_draft(draft.draft_id)

    assert result["provider"] == "deepseek"
    assert result["model"] == "deepseek-chat"
    assert result["review_status"] != "APPROVED"
    filled = {p["field"] for p in result["proposed"]}
    assert {"product_description", "benefits_json", "usp_json", "usage_text",
            "ingredients_text", "warnings_text", "target_customer_text"} <= filled

    after = await svc.get_review_draft_by_id(draft.draft_id)
    assert after.product_description == "Stainless steel insulated bottle."
    assert after.benefits_json == ["Keeps drinks cold for hours"]
    assert after.usp_json == ["Double-wall vacuum insulation"]
    assert after.review_status != "APPROVED"

    db = await crud.get_db()
    cur = await db.execute(
        "SELECT field_name, source_type, verification_status, extraction_method FROM "
        "product_intelligence_review_field_provenance WHERE draft_id=? AND source_type='AI_ENRICHMENT'",
        (draft.draft_id,),
    )
    prov_rows = await cur.fetchall()
    prov_fields = {r[0] for r in prov_rows}
    assert "product_description" in prov_fields and "benefits_json" in prov_fields
    assert all(r[1] == "AI_ENRICHMENT" and r[2] == "AI_PROPOSED" for r in prov_rows)
    assert all("deepseek" in (r[3] or "") for r in prov_rows)

    assert await _count_table("product_intelligence_snapshot") == snaps_before
    assert await _count_table("copy_set") == cs_before
    assert '"hook"' not in capture["user"] and '"cta"' not in capture["user"]


@pytest.mark.asyncio
async def test_ai_fill_preserves_non_empty_human_evidence(monkeypatch):
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bottle", product_display_name="Bottle",
        product_short_name="Bottle", copywriting_angle="x",
    )
    draft = await svc.create_review_draft(
        product["id"],
        ProductIntelligenceReviewDraftCreateRequest(
            product_description="HUMAN-authored truth.",
            buyer_persona_snapshot_json={"audience": "commuters"}, created_by="human",
        ),
    )
    _mock_provider(monkeypatch)

    await svc.ai_fill_missing_review_draft(draft.draft_id)

    after = await svc.get_review_draft_by_id(draft.draft_id)
    assert after.product_description == "HUMAN-authored truth."  # never overwritten
    assert after.usage_text == "Fill with a beverage and seal the lid."  # empty field filled


@pytest.mark.asyncio
async def test_ai_fill_leaves_insufficient_evidence_unresolved(monkeypatch):
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bottle", product_display_name="Bottle",
        product_short_name="Bottle", copywriting_angle="x",
    )
    draft = await _empty_draft(product["id"])
    payload = {"fields": {
        "warnings_text": {"value": "", "status": "INSUFFICIENT_EVIDENCE", "confidence": 0.0, "rationale": "no evidence"},
        "product_description": {"value": "Steel bottle.", "status": "FACT", "confidence": 0.9, "rationale": "title"},
    }}
    _mock_provider(monkeypatch, payload=payload)

    result = await svc.ai_fill_missing_review_draft(draft.draft_id)

    unresolved_fields = {u["field"] for u in result["unresolved"]}
    assert "warnings_text" in unresolved_fields
    after = await svc.get_review_draft_by_id(draft.draft_id)
    assert not after.warnings_text  # never fabricated
    assert after.product_description == "Steel bottle."


@pytest.mark.asyncio
async def test_ai_fill_fail_closed_when_provider_unconfigured(monkeypatch):
    from agent.services import ai_copy_provider_adapter as prov

    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bottle", product_display_name="Bottle",
        product_short_name="Bottle", copywriting_angle="x",
    )
    draft = await _empty_draft(product["id"])
    _mock_provider(monkeypatch, configured=False)

    with pytest.raises(prov.AICopyProviderNotConfigured):
        await svc.ai_fill_missing_review_draft(draft.draft_id)
    after = await svc.get_review_draft_by_id(draft.draft_id)
    assert not after.product_description  # nothing written on fail-closed


@pytest.mark.asyncio
async def test_ai_fill_only_approved_ci_and_hook_cta_stripped(monkeypatch):
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bottle", product_display_name="Bottle",
        product_short_name="Bottle", copywriting_angle="x",
    )
    draft = await _empty_draft(product["id"])
    capture = {}
    _mock_provider(monkeypatch, capture=capture)

    async def fake_ci(*, target_product_id=None, reference_id=None, seed_id=None, limit=100):
        assert target_product_id == product["id"]
        return {"total": 1, "items": [{
            "target_avatar": "Commuters", "pain_point": "Warm drinks", "emotion_trigger": "Relief",
            "dream_outcome": "Cold all day", "key_ingredients_features": "Insulated",
            "hook_script": "STILL drinking warm water", "cta_script": "BUY NOW",
        }]}

    monkeypatch.setattr(
        "agent.services.kalodata_import_service.get_approved_copy_intelligence_context", fake_ci
    )
    await svc.ai_fill_missing_review_draft(draft.draft_id)

    assert "Commuters" in capture["user"]  # approved avatar reached the prompt
    assert "STILL drinking warm water" not in capture["user"]  # hook stripped
    assert "BUY NOW" not in capture["user"]  # cta stripped


# ── Mission-08D: governed field-absence dispositions ─────────────────────────
from agent.models.product_intelligence_review_draft import (  # noqa: E402
    ProductIntelligenceFieldDispositionRequest,
)


def _knowledge_gap_request(**kw) -> ProductIntelligenceReviewDraftCreateRequest:
    """Copy-critical complete + allowed claims present, but usage/ingredients/warnings
    genuinely absent — the Nakamichi shape."""
    base = {
        "product_description": "Compact windshield washer fluid, 30ml concentrate.",
        "benefits_json": ["titisan air meluncur", "penglihatan jelas"],
        "usp_json": ["konsentrat 30ml"],
        "target_customer_text": "Pemandu harian.",
        "allowed_claims_json": ["kesan water repellent pada cermin"],
        "source_urls_json": {"source_url": "https://example.com/p"},
        "image_evidence_json": {"image_url": "https://example.com/i.jpg"},
        "buyer_persona_snapshot_json": {"audience": "pemandu", "pains": ["cermin kabur"]},
        "copy_strategy_summary_json": {"angles": ["keselamatan"]},
        "created_by": "op",
    }
    base.update(kw)
    return ProductIntelligenceReviewDraftCreateRequest(**base)


async def _strict_product(name: str, category: str = "Automotive") -> dict:
    return await crud.create_product(
        raw_product_title=name, source="MANUAL", product_display_name=name,
        category=category,
    )


def _disposition(field, disposition, note="Sumber tidak menyatakan fakta ini.",
                 reviewer="owner"):
    return ProductIntelligenceFieldDispositionRequest(
        field_name=field, disposition=disposition,
        reviewed_by=reviewer, reviewer_note=note,
    )


@pytest.mark.asyncio
async def test_not_stated_disposition_satisfies_the_field_and_classifies_governed():
    """THE 08D contract: a truthful absence unlocks approval WITHOUT the blanket flag,
    and the snapshot freezes READY_WITH_GOVERNED_ABSENCE — never FULLY complete."""
    product = await _strict_product("Governed NSIS")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())

    with pytest.raises(ValueError, match="MISSING_REQUIRED_FIELDS"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="op"))

    for field in ("ingredients_text", "warnings_text", "usage_text"):
        validation = await svc.set_field_disposition(
            draft.draft_id, _disposition(field, "NOT_STATED_IN_SOURCE"))
    assert validation.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    assert set(validation.governed_absent_fields) == {
        "ingredients_text", "warnings_text", "usage_text"}
    # governed absence is NOT presence: completeness stays truthful
    assert validation.completeness_score < 1.0
    assert not any(b.startswith("MISSING_REQUIRED_FIELDS")
                   for b in validation.approval_blockers)

    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="owner"))
    assert approved.status == "APPROVED"
    assert approved.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    assert (approved.completeness_score or 0) < 1.0
    # value columns stay EMPTY — absence is in provenance, never a magic string
    assert not (approved.ingredients_text or "").strip()
    assert not (approved.warnings_text or "").strip()


@pytest.mark.asyncio
async def test_claim_review_ack_preserves_governed_absence_snapshot_classification():
    """A reviewed automotive claim must not erase the governed-absence quality class."""
    product = await _strict_product("Nakamichi Windshield Treatment")
    draft = await svc.create_review_draft(
        product["id"],
        _knowledge_gap_request(
            product_description="Nakamichi Windshield Treatment 30ml.",
            usage_text="Apply to the automotive windshield.",
        ),
    )
    for field in ("ingredients_text", "warnings_text"):
        validation = await svc.set_field_disposition(
            draft.draft_id,
            _disposition(field, "NOT_STATED_IN_SOURCE"),
        )

    assert validation.claim_gate == "CLAIM_REVIEW_REQUIRED"
    assert validation.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    assert validation.approval_blockers == ["CLAIM_REVIEW_REQUIRED:treat"]

    with pytest.raises(ValueError, match="DRAFT_NOT_APPROVABLE:CLAIM_REVIEW_REQUIRED"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="owner"),
        )

    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(
            approved_by="owner",
            claim_review_acknowledged=True,
        ),
    )
    assert approved.status == "APPROVED"
    assert approved.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    assert (approved.completeness_score or 0) < 1.0


@pytest.mark.asyncio
async def test_disposition_upsert_is_idempotent_and_scoped_to_its_field():
    product = await _strict_product("Governed Idempotent")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    await svc.set_field_disposition(
        draft.draft_id, _disposition("ingredients_text", "NOT_STATED_IN_SOURCE"))
    await svc.set_field_disposition(
        draft.draft_id, _disposition("ingredients_text", "NOT_STATED_IN_SOURCE"))
    # changed decision UPDATES the same governing row
    await svc.set_field_disposition(
        draft.draft_id,
        _disposition("ingredients_text", "REQUIRES_EXTERNAL_EVIDENCE",
                     note="Tunggu SDS daripada pembekal."))
    refreshed = await svc.get_review_draft_by_id(draft.draft_id)
    rows = [item for item in refreshed.provenance_items
            if item.evidence_kind == "FIELD_ABSENCE_DISPOSITION"]
    assert len(rows) == 1, "retry/changed decision duplicated the disposition row"
    assert rows[0].field_name == "ingredients_text"
    assert rows[0].verification_status == "REQUIRES_EXTERNAL_EVIDENCE"
    # only its own field is governed — warnings/usage remain ungoverned blockers
    validation = await svc.validate_review_draft(draft.draft_id)
    assert "warnings_text" not in validation.governed_absent_fields


@pytest.mark.asyncio
async def test_requires_external_evidence_remains_an_approval_blocker():
    product = await _strict_product("Governed REE")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    for field in ("warnings_text", "usage_text"):
        await svc.set_field_disposition(
            draft.draft_id, _disposition(field, "NOT_STATED_IN_SOURCE"))
    validation = await svc.set_field_disposition(
        draft.draft_id,
        _disposition("ingredients_text", "REQUIRES_EXTERNAL_EVIDENCE",
                     note="SDS belum diterima."))
    assert "ingredients_text" in validation.unresolved_external_fields
    assert any(b.startswith("REQUIRES_EXTERNAL_EVIDENCE:ingredients_text")
               for b in validation.approval_blockers)
    with pytest.raises(ValueError, match="REQUIRES_EXTERNAL_EVIDENCE"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="op"))
    # the blanket copy flag must NOT clear it either
    with pytest.raises(ValueError, match="REQUIRES_EXTERNAL_EVIDENCE"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(
                approved_by="op", allow_incomplete_product_knowledge=True))


@pytest.mark.asyncio
async def test_not_applicable_is_refused_for_strict_and_unknown_categories():
    """Automotive is a chemical-risk family; unknown categories fail closed."""
    for name, category in (("Governed NA Auto", "Automotive"),
                           ("Governed NA Unknown", ""),
                           ("Governed NA Children", "Children's Apparel")):
        product = await _strict_product(name, category=category)
        draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
        with pytest.raises(ValueError, match="NOT_APPLICABLE_FORBIDDEN_FOR_CATEGORY"):
            await svc.set_field_disposition(
                draft.draft_id,
                _disposition("ingredients_text", "NOT_APPLICABLE",
                             note="Produk tiada bahan."))


@pytest.mark.asyncio
async def test_not_applicable_is_allowed_for_confirmable_category_with_note():
    product = await _strict_product("Governed NA Apparel",
                                    category="Apparel & Textiles")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    validation = await svc.set_field_disposition(
        draft.draft_id,
        _disposition("ingredients_text", "NOT_APPLICABLE",
                     note="Produk tekstil — tiada senarai bahan ramuan."))
    assert validation.governed_absent_fields.get("ingredients_text") == "NOT_APPLICABLE"
    # mandatory note enforced
    with pytest.raises(ValueError, match="REVIEWER_NOTE_REQUIRED"):
        await svc.set_field_disposition(
            draft.draft_id,
            _disposition("warnings_text", "NOT_APPLICABLE", note="  x "))


@pytest.mark.asyncio
async def test_dispositions_reject_ineligible_fields_filled_fields_and_terminal_drafts():
    product = await _strict_product("Governed Guards")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    # allowed_claims_json can never be waived
    with pytest.raises(ValueError, match="FIELD_NOT_DISPOSITION_ELIGIBLE"):
        await svc.set_field_disposition(
            draft.draft_id, _disposition("allowed_claims_json", "NOT_STATED_IN_SOURCE"))
    # an ELIGIBLE field holding a value cannot simultaneously be absent
    filled = await svc.create_review_draft(
        (await _strict_product("Governed Guards Filled"))["id"],
        _knowledge_gap_request(usage_text="Sembur dan lap dengan kain microfiber."))
    with pytest.raises(ValueError, match="FIELD_HAS_VALUE:usage_text"):
        await svc.set_field_disposition(
            filled.draft_id, _disposition("usage_text", "NOT_STATED_IN_SOURCE"))
    # terminal drafts refuse dispositions
    for field in ("ingredients_text", "warnings_text", "usage_text"):
        await svc.set_field_disposition(
            draft.draft_id, _disposition(field, "NOT_STATED_IN_SOURCE"))
    await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="op"))
    with pytest.raises(ValueError, match="DRAFT_DISPOSITION_FORBIDDEN:APPROVED"):
        await svc.set_field_disposition(
            draft.draft_id, _disposition("usage_text", "NOT_STATED_IN_SOURCE"))


@pytest.mark.asyncio
async def test_placeholder_strings_do_not_masquerade_as_knowledge():
    """Placeholder text typed into a required field is MISSING, not present — the
    governed disposition is the only way to resolve absence."""
    product = await _strict_product("Governed Placeholder")
    draft = await svc.create_review_draft(
        product["id"],
        _knowledge_gap_request(ingredients_text="N/A", warnings_text="  n/a ",
                               usage_text="NOT_AVAILABLE"))
    validation = await svc.validate_review_draft(draft.draft_id)
    for field in ("ingredients_text", "warnings_text", "usage_text"):
        assert field in validation.missing_required_fields, field
    with pytest.raises(ValueError, match="MISSING_REQUIRED_FIELDS"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="op"))


@pytest.mark.asyncio
async def test_disposition_provenance_survives_into_the_snapshot_lineage():
    from agent.services.product_intelligence_snapshot_service import (
        get_provenance_list_response,
    )

    product = await _strict_product("Governed Lineage")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    for field in ("ingredients_text", "warnings_text", "usage_text"):
        await svc.set_field_disposition(
            draft.draft_id, _disposition(field, "NOT_STATED_IN_SOURCE"))
    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="owner"))
    provenance = await get_provenance_list_response(approved.snapshot_id)
    rows = [item for item in provenance.items
            if getattr(item, "evidence_kind", None) == "FIELD_ABSENCE_DISPOSITION"]
    assert {getattr(r, "field_name", None) for r in rows} >= {
        "ingredients_text", "warnings_text", "usage_text"}, (
        "governed dispositions did not survive into snapshot provenance lineage")
    assert {getattr(r, "verification_status", None) for r in rows} == {
        "NOT_STATED_IN_SOURCE"}
    assert {getattr(r, "reviewer_decision", None) for r in rows} == {"owner"}


@pytest.mark.asyncio
async def test_disposition_requires_nonblank_reviewer_identity():
    product = await _strict_product("Governed Reviewer Required")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    with pytest.raises(ValueError, match="REVIEWER_REQUIRED"):
        await svc.set_field_disposition(
            draft.draft_id,
            _disposition(
                "ingredients_text",
                "NOT_STATED_IN_SOURCE",
                reviewer="   ",
            ),
        )


@pytest.mark.asyncio
async def test_dispositions_are_scoped_to_exact_draft_and_product():
    product = await _strict_product("Governed Scope One")
    first = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    await svc.set_field_disposition(
        first.draft_id,
        _disposition("ingredients_text", "NOT_STATED_IN_SOURCE"),
    )
    await crud.update_product_intelligence_review_draft(
        first.draft_id,
        review_status="SUPERSEDED",
    )

    second = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    second_validation = await svc.validate_review_draft(second.draft_id)
    assert "ingredients_text" not in second_validation.governed_absent_fields

    other_product = await _strict_product("Governed Scope Two")
    other = await svc.create_review_draft(
        other_product["id"],
        _knowledge_gap_request(),
    )
    other_validation = await svc.validate_review_draft(other.draft_id)
    assert "ingredients_text" not in other_validation.governed_absent_fields


@pytest.mark.asyncio
async def test_superseded_draft_is_terminal_for_every_mutation_path():
    product = await _strict_product("Governed Superseded")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    await crud.update_product_intelligence_review_draft(
        draft.draft_id,
        review_status="SUPERSEDED",
    )

    with pytest.raises(ValueError, match="DRAFT_UPDATE_FORBIDDEN:SUPERSEDED"):
        await svc.update_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftUpdateRequest(usage_text="changed"),
        )
    with pytest.raises(ValueError, match="DRAFT_DISPOSITION_FORBIDDEN:SUPERSEDED"):
        await svc.set_field_disposition(
            draft.draft_id,
            _disposition("ingredients_text", "NOT_STATED_IN_SOURCE"),
        )
    with pytest.raises(ValueError, match="DRAFT_UPDATE_FORBIDDEN:SUPERSEDED"):
        await svc.approve_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftApproveRequest(approved_by="owner"),
        )
    with pytest.raises(ValueError, match="DRAFT_UPDATE_FORBIDDEN:SUPERSEDED"):
        await svc.reject_review_draft(
            draft.draft_id,
            ProductIntelligenceReviewDraftRejectRequest(rejected_by="owner"),
        )


@pytest.mark.asyncio
async def test_source_unavailable_disposition_is_a_governed_absence_not_blocking():
    """PI-11: SOURCE_UNAVAILABLE (the live source cannot be acquired) satisfies the field
    blocker as a governed absence — like NOT_STATED — so a product stays COPY_GROUNDING_READY
    with a supply gap, WITHOUT ever claiming an inspected source omitted the fact, and never
    lowering completeness to a false 1.0."""
    product = await _strict_product("Governed SOURCE_UNAVAILABLE")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())

    for field in ("ingredients_text", "warnings_text", "usage_text"):
        validation = await svc.set_field_disposition(
            draft.draft_id,
            _disposition(field, "SOURCE_UNAVAILABLE",
                         note="TikTok live source is externally blocked; no source acquired."))
    assert validation.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    assert set(validation.governed_absent_fields) == {
        "ingredients_text", "warnings_text", "usage_text"}
    assert all(v == "SOURCE_UNAVAILABLE" for v in validation.governed_absent_fields.values())
    assert validation.completeness_score < 1.0
    assert not any(b.startswith("MISSING_REQUIRED_FIELDS") for b in validation.approval_blockers)

    approved = await svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="claude-owner-delegated-pi11"))
    assert approved.status == "APPROVED"
    assert approved.readiness_status == "READY_WITH_GOVERNED_ABSENCE"
    # absence lives in provenance, never as a fabricated value in the column
    assert not (approved.ingredients_text or "").strip()


@pytest.mark.asyncio
async def test_source_unavailable_is_offered_as_a_disposition_option():
    product = await _strict_product("SU Options")
    draft = await svc.create_review_draft(product["id"], _knowledge_gap_request())
    validation = await svc.validate_review_draft(draft.draft_id)
    for field in ("ingredients_text", "warnings_text"):
        assert "SOURCE_UNAVAILABLE" in validation.disposition_options.get(field, [])
        # and it never claims a source was inspected
        assert "NOT_STATED_IN_SOURCE" in validation.disposition_options.get(field, [])
